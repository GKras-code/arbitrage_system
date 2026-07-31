"""
FastAPI бэкенд для Arbitrage System.

Запуск (локально):
    uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import os
import sys
import asyncio
import ssl
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import pbkdf2_hmac
from hmac import compare_digest
from time import monotonic
from typing import Literal

import jwt
import aiohttp
import certifi
from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Путь к корню проекта (чтобы импортировать connectors)
# ---------------------------------------------------------------------------
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from connectors.bcs_connector import BCSConnector
from connectors.exante_connector import EXANTEConnector
from db import create_pool
from sync_bcs_market_data import sync_market_data as sync_bcs_market_data
from sync_exante_market_data import sync_market_data as sync_exante_market_data
from sync_forts_margin import sync_forts_market_parameters
JWT_ALGORITHM = "HS256"
JWT_SECRET = os.getenv("JWT_SECRET", "change-this-jwt-secret-before-production")
PASSWORD_SALT = b"arbitrage-system-user-v1"
bearer_scheme = HTTPBearer(auto_error=False)
REFERENCE_CACHE_TTL_SECONDS = 15 * 60
REFERENCE_SYNC_HOUR_UTC = 3
FORTS_MARGIN_SYNC_INTERVAL_SECONDS = 3 * 60 * 60
BCS_FUTURES_CLASS_CODE = os.getenv("BCS_FUTURES_CLASS_CODE", "SPBFUT")
MOEX_FUTURES_SECURITY_URL = "https://iss.moex.com/iss/engines/futures/markets/forts/securities/{ticker}.json"
CURRENCY_RATE_SOURCES = {
    "USD": ("EUR/USD", Decimal("10")),
    "CNY": ("USD/CNY", Decimal("1")),
}
CURRENCY_RATE_SYNC_INTERVAL_SECONDS = 6 * 60 * 60

_instrument_cache: dict[str, tuple[float, list[dict[str, str]]]] = {}
_market_data_tasks: list[asyncio.Task] = []
_reference_sync_task: asyncio.Task | None = None
_forts_margin_sync_task: asyncio.Task | None = None
_currency_rate_sync_task: asyncio.Task | None = None
_price_update_subscribers: set[asyncio.Queue[None]] = set()
ARBITRAGE_PAIR_COLUMNS = {
    "id", "cme_name", "cme_data_exp", "cme_price", "cme_margin_usd", "cme_lot",
    "forts_name", "forts_data_exp", "forts_price", "price_ratio", "forts_margin_rub",
    "forts_price_step", "forts_price_step_value", "forts_trade_lot", "trade_lot_currency", "dte", "virt_0",
    "diff", "diff_percent", "diff_ytm_margin",
}


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class PairCreateRequest(BaseModel):
    cme_name: str = Field(min_length=1, max_length=100)
    forts_name: str = Field(min_length=0, max_length=100, default="")


class PairManualValueUpdate(BaseModel):
    field: Literal["virt_0", "price_ratio", "cme_margin_usd"]
    value: Decimal


class PairTradeLotCurrencyUpdate(BaseModel):
    currency: Literal["USD", "CNY"]


def password_hash(password: str) -> str:
    return pbkdf2_hmac("sha256", password.encode(), PASSWORD_SALT, 100_000).hex()


def _normalize_option(value: str, label: str, details: str = "") -> dict[str, str]:
    return {"value": value, "label": label, "details": details}


def _unique_options(items: list[dict[str, str]], limit: int) -> list[dict[str, str]]:
    unique: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        value = item.get("value", "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        unique.append(item)
        if len(unique) >= limit:
            break
    return unique


def _matches_query(*values: str, query: str) -> bool:
    if not query:
        return True
    query_folded = query.casefold()
    return any(query_folded in value.casefold() for value in values if value)


async def _market_data_options(
    table_name: str,
    value_column: str,
    query: str,
    limit: int,
    provider_label: str,
) -> list[dict[str, str]]:
    """Найти инструменты в синхронизированном справочнике провайдера."""
    pool = await create_pool()
    try:
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                f"""
                SELECT {value_column} AS value, ticker, short_name, instrument_type,
                       maturity_date
                FROM {table_name}
                WHERE COALESCE({value_column}, '') <> ''
                  AND (
                      $1 = ''
                      OR {value_column} ILIKE '%' || $1 || '%'
                      OR COALESCE(ticker, '') ILIKE '%' || $1 || '%'
                      OR COALESCE(short_name, '') ILIKE '%' || $1 || '%'
                  )
                ORDER BY {value_column}
                LIMIT $2
                """,
                query.strip(),
                limit,
            )
    except Exception:
        # Справочник может ещё не быть создан синхронизатором.
        return []

    items: list[dict[str, str]] = []
    for row in rows:
        value = str(row["value"] or "").strip()
        ticker = str(row["ticker"] or "").strip()
        short_name = str(row["short_name"] or "").strip()
        instrument_type = str(row["instrument_type"] or "").strip()
        maturity_date = row["maturity_date"]
        details = ", ".join(
            part for part in (ticker, short_name, instrument_type) if part
        ) or f"Инструмент {provider_label}"
        if maturity_date:
            details = f"{details}, exp {maturity_date}"
        label = value if value == ticker or not ticker else f"{value} ({ticker})"
        items.append(_normalize_option(value, label, details))
    return _unique_options(items, limit)


def _cached_reference(name: str) -> list[dict[str, str]] | None:
    cached = _instrument_cache.get(name)
    if cached is None:
        return None
    created_at, items = cached
    if monotonic() - created_at > REFERENCE_CACHE_TTL_SECONDS:
        _instrument_cache.pop(name, None)
        return None
    return items


def _store_reference(name: str, items: list[dict[str, str]]) -> list[dict[str, str]]:
    _instrument_cache[name] = (monotonic(), items)
    return items


def _extract_bcs_items(payload: dict | list | bool) -> list[dict[str, str]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        for key in ("content", "items", "records", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                rows = value
                break
        else:
            rows = []
    else:
        rows = []

    items: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("ticker") or "").strip()
        if not ticker:
            continue

        # BCS возвращает boards = [{"classCode": "TQBR", "exchange": "MOEX"}, ...]
        boards = row.get("boards") or []
        first_class_code = ""
        if isinstance(boards, list) and boards:
            first_board = boards[0]
            if isinstance(first_board, dict):
                first_class_code = str(first_board.get("classCode") or "").strip()

        short_name = str(row.get("shortName") or row.get("displayName") or row.get("name") or "").strip()
        instrument_type = str(row.get("type") or row.get("instrumentType") or "").strip()

        label = ticker if not first_class_code else f"{ticker} ({first_class_code})"
        details_parts = [part for part in (short_name, instrument_type) if part]
        details = ", ".join(details_parts) if details_parts else "Инструмент BCS"
        items.append(_normalize_option(ticker, label, details))
    return items


async def _search_exante_options(query: str, limit: int) -> list[dict[str, str]]:
    return await _market_data_options(
        "exante_market_data", "symbol_id", query, limit, "EXANTE"
    )


async def _search_bcs_options(query: str, limit: int) -> list[dict[str, str]]:
    return await _market_data_options(
        "bcs_market_data", "ticker", query, limit, "BCS"
    )


async def initialize_database() -> None:
    pool = await create_pool()
    async with pool.acquire() as connection:
        existing_columns = {
            row["column_name"]
            for row in await connection.fetch(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'arbitrage_pairs'
                """
            )
        }
        if existing_columns and not existing_columns <= ARBITRAGE_PAIR_COLUMNS:
            await connection.execute("DROP TABLE arbitrage_pairs CASCADE")
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id BIGSERIAL PRIMARY KEY,
                username VARCHAR(100) NOT NULL UNIQUE,
                password_hash VARCHAR(128) NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS arbitrage_pairs (
                id BIGSERIAL PRIMARY KEY,
                cme_name VARCHAR(100) NOT NULL,
                cme_data_exp DATE,
                cme_price NUMERIC(18, 4),
                cme_margin_usd NUMERIC(18, 2),
                cme_lot NUMERIC(18, 4),
                forts_name VARCHAR(100),
                forts_data_exp DATE,
                forts_price NUMERIC(18, 4),
                price_ratio NUMERIC(18, 4),
                forts_margin_rub NUMERIC(18, 2),
                forts_price_step NUMERIC(18, 8),
                forts_price_step_value NUMERIC(18, 8),
                forts_trade_lot NUMERIC(18, 8),
                trade_lot_currency VARCHAR(3) NOT NULL DEFAULT 'USD'
                    CHECK (trade_lot_currency IN ('USD', 'CNY')),
                dte INTEGER,
                virt_0 NUMERIC(18, 4) NOT NULL DEFAULT 0,
                diff NUMERIC(18, 4),
                diff_percent NUMERIC(18, 4),
                diff_ytm_margin NUMERIC(18, 4)
            );

            CREATE TABLE IF NOT EXISTS currency_rates (
                currency_code VARCHAR(3) PRIMARY KEY,
                rate NUMERIC(18, 6) NOT NULL,
                nominal INTEGER NOT NULL,
                rate_date DATE NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        await connection.execute(
            """
            ALTER TABLE arbitrage_pairs
            ADD COLUMN IF NOT EXISTS trade_lot_currency VARCHAR(3) NOT NULL DEFAULT 'USD'
                CHECK (trade_lot_currency IN ('USD', 'CNY'))
            """
        )
        await connection.execute(
            """
            INSERT INTO users (username, password_hash)
            VALUES ($1, $2)
            ON CONFLICT (username) DO NOTHING
            """,
            "user",
            password_hash("user1155"),
        )


async def _publish_price_update() -> None:
    """Notify connected browser clients after a price is saved."""
    for queue in tuple(_price_update_subscribers):
        queue.put_nowait(None)


def _as_decimal(value: object) -> Decimal | None:
    """Преобразовать значение БД или API в конечное Decimal."""
    if value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _calculate_pair_metrics(
    pair: dict,
    trade_lot_rate: Decimal | None,
    today: date,
) -> tuple[
    int | None,
    Decimal | None,
    Decimal | None,
    Decimal | None,
    Decimal | None,
]:
    """Рассчитать DTE, diff, доходность на ГО для одной арбитражной пары."""
    expirations = [
        expiration
        for expiration in (pair["cme_data_exp"], pair["forts_data_exp"])
        if expiration is not None
    ]
    dte = (min(expirations) - today).days if expirations else None

    values = {
        name: _as_decimal(pair[name])
        for name in (
            "forts_price",
            "price_ratio",
            "cme_price",
            "virt_0",
            "cme_lot",
            "cme_margin_usd",
            "forts_margin_rub",
            "forts_price_step",
            "forts_price_step_value",
        )
    }
    if (
        dte is None
        or dte <= 0
        or any(value is None for value in values.values())
        or trade_lot_rate is None
        or trade_lot_rate <= 0
    ):
        return dte, None, None, None, None

    forts_price = values["forts_price"]
    price_ratio = values["price_ratio"]
    cme_price = values["cme_price"]
    virt_0 = values["virt_0"]
    cme_lot = values["cme_lot"]
    cme_margin_usd = values["cme_margin_usd"]
    forts_margin_rub = values["forts_margin_rub"]
    forts_price_step = values["forts_price_step"]
    forts_price_step_value = values["forts_price_step_value"]
    if cme_lot <= 0 or forts_price_step <= 0 or forts_price_step_value <= 0:
        return dte, None, None, None, None

    forts_trade_lot = cme_lot / (forts_price_step_value / forts_price_step / trade_lot_rate) * price_ratio
    if forts_trade_lot <= 0:
        return dte, None, None, None, None

    total_margin = cme_margin_usd + forts_margin_rub * forts_trade_lot / trade_lot_rate
    if total_margin <= 0:
        return dte, None, None, None, None

    diff = forts_price * price_ratio - cme_price - virt_0
    diff_percent = diff * cme_lot / total_margin
    diff_ytm_margin = diff_percent / dte * Decimal("365")
    return dte, forts_trade_lot, diff, diff_percent, diff_ytm_margin


def _moex_step_price(payload: dict[str, object]) -> Decimal | None:
    """Извлечь стоимость шага цены из публичного ответа MOEX ISS."""
    securities = payload.get("securities")
    if not isinstance(securities, dict):
        return None
    columns = securities.get("columns")
    rows = securities.get("data")
    if not isinstance(columns, list) or not isinstance(rows, list) or not rows:
        return None
    try:
        value = rows[0][columns.index("STEPPRICE")]
    except (IndexError, ValueError):
        return None
    return _as_decimal(value)


async def _refresh_currency_rates() -> list[dict[str, object]]:
    """Рассчитать и сохранить курсы USD и CNY по стоимости шага фьючерсов MOEX."""
    pool = await create_pool()
    async with pool.acquire() as connection:
        source_rows = await connection.fetch(
            "SELECT base_asset, ticker FROM bcs_market_data "
            "WHERE base_asset = ANY($1::text[]) AND ticker <> '' "
            "AND (maturity_date IS NULL OR maturity_date >= CURRENT_DATE) "
            "ORDER BY base_asset, maturity_date NULLS LAST, ticker",
            [source[0] for source in CURRENCY_RATE_SOURCES.values()],
        )
    tickers_by_asset: dict[str, str] = {}
    for row in source_rows:
        tickers_by_asset.setdefault(str(row["base_asset"]), str(row["ticker"]))

    missing_assets = [
        base_asset
        for base_asset, _ in CURRENCY_RATE_SOURCES.values()
        if base_asset not in tickers_by_asset
    ]
    if missing_assets:
        raise ValueError(f"В bcs_market_data не найдены фьючерсы: {', '.join(missing_assets)}")

    timeout = aiohttp.ClientTimeout(total=15)
    connector = aiohttp.TCPConnector(ssl=ssl.create_default_context(cafile=certifi.where()))
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        payloads = {}
        for currency_code, (base_asset, _) in CURRENCY_RATE_SOURCES.items():
            async with session.get(
                MOEX_FUTURES_SECURITY_URL.format(ticker=tickers_by_asset[base_asset]),
                params={"iss.meta": "off", "iss.only": "securities"},
            ) as response:
                response.raise_for_status()
                payloads[currency_code] = await response.json(content_type=None)

    rate_date = date.today()
    rates: list[tuple[str, Decimal, int, date]] = []
    for currency_code, (_, multiplier) in CURRENCY_RATE_SOURCES.items():
        step_price = _moex_step_price(payloads[currency_code])
        if step_price is None or step_price <= 0:
            raise ValueError(
                f"MOEX ISS не вернула стоимость шага цены для {currency_code} "
                f"({tickers_by_asset[CURRENCY_RATE_SOURCES[currency_code][0]]})"
            )
        rates.append((currency_code, step_price * multiplier, 1, rate_date))

    async with pool.acquire() as connection:
        await connection.executemany(
            """
            INSERT INTO currency_rates (currency_code, rate, nominal, rate_date, updated_at)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (currency_code) DO UPDATE
            SET rate = EXCLUDED.rate, nominal = EXCLUDED.nominal,
                rate_date = EXCLUDED.rate_date, updated_at = NOW()
            """,
            rates,
        )
        rows = await connection.fetch(
            """
            SELECT currency_code, rate, nominal, rate_date, updated_at
            FROM currency_rates
            WHERE currency_code = ANY($1::varchar[])
            ORDER BY currency_code
            """,
            list(CURRENCY_RATE_SOURCES),
        )
    return [dict(row) for row in rows]


async def _get_currency_rates() -> list[dict[str, object]]:
    """Вернуть последние сохранённые курсы без внепланового обновления."""
    pool = await create_pool()
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT currency_code, rate, nominal, rate_date, updated_at
            FROM currency_rates
            WHERE currency_code = ANY($1::varchar[])
            ORDER BY currency_code
            """,
            list(CURRENCY_RATE_SOURCES),
        )
    return [dict(row) for row in rows]


async def _refresh_arbitrage_metrics() -> bool:
    """Пересчитать показатели всех пар с последними сохранёнными курсами."""
    pool = await create_pool()
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            """
                 SELECT id, cme_data_exp, forts_data_exp, cme_price, cme_margin_usd,
                     cme_lot, virt_0, forts_price, price_ratio, forts_margin_rub,
                     forts_price_step, forts_price_step_value, trade_lot_currency
            FROM arbitrage_pairs
            """
        )

    currency_rates = await _get_currency_rates()
    rates_by_currency = {
        str(rate["currency_code"]): _as_decimal(rate["rate"])
        for rate in currency_rates
    }
    if not rates_by_currency:
        return False

    today = date.today()
    updates = [
        (forts_trade_lot, diff, diff_percent, diff_ytm_margin, dte, row["id"])
        for row in rows
        for dte, forts_trade_lot, diff, diff_percent, diff_ytm_margin in [
            _calculate_pair_metrics(
                dict(row),
                rates_by_currency.get(str(row["trade_lot_currency"])),
                today,
            )
        ]
    ]
    async with pool.acquire() as connection:
        await connection.executemany(
            """
            UPDATE arbitrage_pairs
            SET forts_trade_lot = $1, diff = $2, diff_percent = $3,
                diff_ytm_margin = $4, dte = $5
            WHERE id = $6
            """,
            updates,
        )
    return bool(updates)


async def _save_market_price(column: str, instrument: str, price: object) -> None:
    """Store the latest price and fill a missing CME-to-FORTS price ratio once."""
    if price is None or not instrument:
        return
    try:
        value = Decimal(str(price))
    except Exception:
        return

    pool = await create_pool()
    async with pool.acquire() as connection:
        updated = await connection.fetch(
            f"UPDATE arbitrage_pairs SET {column} = $1::numeric, "
            "price_ratio = CASE WHEN price_ratio IS NULL AND COALESCE("
            f"{'$1::numeric' if column == 'cme_price' else 'cme_price'}, 0::numeric) <> 0::numeric "
            "AND COALESCE("
            f"{'$1::numeric' if column == 'forts_price' else 'forts_price'}, 0::numeric) <> 0::numeric "
            "THEN ROUND("
            f"{'$1::numeric' if column == 'cme_price' else 'cme_price'} / "
            f"{'$1::numeric' if column == 'forts_price' else 'forts_price'}, 0) "
            "ELSE price_ratio END WHERE "
            f"{'cme_name' if column == 'cme_price' else 'forts_name'} = $2 RETURNING id",
            value,
            instrument,
        )
    if updated:
        await _refresh_arbitrage_metrics()
        await _publish_price_update()


async def _stream_bcs_prices(instruments: list[dict[str, str]]) -> None:
    """Receive BCS quote updates and persist the `last` price."""
    connector = BCSConnector()
    try:
        async def on_quote(quote: dict) -> None:
            if quote.get("responseType") == "Quotes":
                await _save_market_price("forts_price", str(quote.get("ticker") or ""), quote.get("last"))

        await connector.stream_quotes(instruments, on_quote)
    finally:
        await connector.close()


async def _stream_exante_prices(symbol_ids: list[str]) -> None:
    """Receive EXANTE trade updates and persist the `price` field."""
    connector = EXANTEConnector()
    try:
        async def on_trade(trade: dict) -> None:
            await _save_market_price("cme_price", str(trade.get("symbolId") or ""), trade.get("price"))

        await connector.stream_trades(symbol_ids, on_trade, buffer_size=1)
    finally:
        await connector.close()


async def _restart_market_subscriptions() -> None:
    """Subscribe exactly to the instruments currently present in arbitrage_pairs."""
    global _market_data_tasks
    for task in _market_data_tasks:
        task.cancel()
    if _market_data_tasks:
        await asyncio.gather(*_market_data_tasks, return_exceptions=True)

    pool = await create_pool()
    async with pool.acquire() as connection:
        cme_symbols = await connection.fetch("SELECT DISTINCT cme_name FROM arbitrage_pairs WHERE cme_name <> ''")
        forts_tickers = await connection.fetch("SELECT DISTINCT forts_name FROM arbitrage_pairs WHERE COALESCE(forts_name, '') <> ''")

    _market_data_tasks = []
    exante_auth_configured = (
        os.getenv("EXANTE_JWT")
        or os.getenv("EXANTE_SECRET_KEY")
        or (
            os.getenv("EXANTE_CLIENT_ID")
            and os.getenv("EXANTE_APPLICATION_ID")
            and os.getenv("EXANTE_SHARED_KEY")
        )
    )
    if cme_symbols and exante_auth_configured:
        for row in cme_symbols:
            symbol_id = str(row["cme_name"])
            _market_data_tasks.append(asyncio.create_task(
                _stream_exante_prices([symbol_id]),
                name=f"exante-price-stream:{symbol_id}",
            ))
    if forts_tickers and os.getenv("BCS_REFRESH_TOKEN"):
        instruments = [
            {"ticker": row["forts_name"], "classCode": BCS_FUTURES_CLASS_CODE}
            for row in forts_tickers
        ]
        _market_data_tasks.append(asyncio.create_task(
            _stream_bcs_prices(instruments), name="bcs-price-stream"
        ))


async def _stop_market_subscriptions() -> None:
    global _market_data_tasks
    for task in _market_data_tasks:
        task.cancel()
    if _market_data_tasks:
        await asyncio.gather(*_market_data_tasks, return_exceptions=True)
    _market_data_tasks = []


def _seconds_until_reference_sync() -> float:
    """Рассчитать задержку до ближайшего запуска в 03:00 UTC."""
    now = datetime.now(timezone.utc)
    scheduled = now.replace(
        hour=REFERENCE_SYNC_HOUR_UTC, minute=0, second=0, microsecond=0
    )
    if scheduled <= now:
        scheduled += timedelta(days=1)
    return (scheduled - now).total_seconds()


async def _sync_reference_data_periodically() -> None:
    """Обновлять справочники BCS и EXANTE каждый день в 03:00 UTC."""
    while True:
        # Фиксированное время не зависит от момента запуска или перезапуска API.
        await asyncio.sleep(_seconds_until_reference_sync())
        try:
            bcs_count = await sync_bcs_market_data()
            print(f"Справочник BCS обновлен: {bcs_count} инструментов.", flush=True)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print(f"Ошибка обновления справочника BCS: {error}", flush=True)
        try:
            exante_count = await sync_exante_market_data()
            print(f"Справочник EXANTE обновлен: {exante_count} инструментов.", flush=True)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print(f"Ошибка обновления справочника EXANTE: {error}", flush=True)


async def _stop_reference_data_sync() -> None:
    global _reference_sync_task
    if _reference_sync_task is not None:
        _reference_sync_task.cancel()
        await asyncio.gather(_reference_sync_task, return_exceptions=True)
        _reference_sync_task = None


async def _sync_forts_margins_periodically() -> None:
    """Обновлять ГО и стоимость шага FORTS сразу после запуска и каждые три часа."""
    while True:
        try:
            updated = await sync_forts_market_parameters()
            print(f"Параметры FORTS обновлены: {updated} тикеров.", flush=True)
            if updated:
                await _refresh_arbitrage_metrics()
                await _publish_price_update()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print(f"Ошибка обновления ГО FORTS: {error}", flush=True)
        await asyncio.sleep(FORTS_MARGIN_SYNC_INTERVAL_SECONDS)


async def _stop_forts_margin_sync() -> None:
    global _forts_margin_sync_task
    if _forts_margin_sync_task is not None:
        _forts_margin_sync_task.cancel()
        await asyncio.gather(_forts_margin_sync_task, return_exceptions=True)
        _forts_margin_sync_task = None


async def _sync_currency_rates_periodically() -> None:
    """Обновлять курсы по фьючерсам MOEX сразу и затем каждые шесть часов."""
    while True:
        try:
            rates = await _refresh_currency_rates()
            print(f"Курсы MOEX обновлены: {len(rates)} валют.", flush=True)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            print(f"Ошибка обновления курсов MOEX: {error}", flush=True)
        await asyncio.sleep(CURRENCY_RATE_SYNC_INTERVAL_SECONDS)


async def _stop_currency_rate_sync() -> None:
    global _currency_rate_sync_task
    if _currency_rate_sync_task is not None:
        _currency_rate_sync_task.cancel()
        await asyncio.gather(_currency_rate_sync_task, return_exceptions=True)
        _currency_rate_sync_task = None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Требуется авторизация")
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        username = payload.get("sub")
    except jwt.PyJWTError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Недействительный токен") from error
    if not isinstance(username, str):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Недействительный токен")
    return username


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Жизненный цикл приложения: инициализация / cleanup."""
    global _reference_sync_task, _forts_margin_sync_task, _currency_rate_sync_task
    await initialize_database()
    await _restart_market_subscriptions()
    # Планировщики стартуют вместе с API и ждут ближайшего времени запуска.
    _reference_sync_task = asyncio.create_task(
        _sync_reference_data_periodically(), name="reference-data-sync"
    )
    _forts_margin_sync_task = asyncio.create_task(
        _sync_forts_margins_periodically(), name="forts-margin-sync"
    )
    _currency_rate_sync_task = asyncio.create_task(
        _sync_currency_rates_periodically(), name="currency-rate-sync"
    )
    yield
    await _stop_currency_rate_sync()
    await _stop_forts_margin_sync()
    await _stop_reference_data_sync()
    await _stop_market_subscriptions()
    pool = await create_pool()
    await pool.close()


app = FastAPI(
    title="Arbitrage System API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — разрешить всё (фронт на любом IP/порту)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===========================================================================
# Health-check
# ===========================================================================

@app.post("/api/auth/login")
async def login(request: LoginRequest):
    pool = await create_pool()
    async with pool.acquire() as connection:
        user = await connection.fetchrow(
            "SELECT username, password_hash FROM users WHERE username = $1", request.username
        )
    if user is None or not compare_digest(user["password_hash"], password_hash(request.password)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный логин или пароль")

    token = jwt.encode({"sub": user["username"]}, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return {"access_token": token, "token_type": "bearer", "username": user["username"]}


@app.get("/api/auth/me")
async def current_user(username: str = Depends(get_current_user)):
    return {"username": username}


@app.get("/api/arbitrage-pairs")
async def list_arbitrage_pairs(_: str = Depends(get_current_user)):
    await _refresh_arbitrage_metrics()
    pool = await create_pool()
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            """
                 SELECT id, cme_name, cme_data_exp, cme_price, cme_margin_usd, cme_lot,
                     forts_name, forts_data_exp, forts_price, price_ratio, forts_margin_rub,
                                         forts_price_step, forts_price_step_value, forts_trade_lot, trade_lot_currency, dte, virt_0,
                   diff, diff_percent, diff_ytm_margin
            FROM arbitrage_pairs
            ORDER BY id
            """
        )
    return {"pairs": [dict(row) for row in rows]}


@app.get("/api/currency-rates")
async def list_currency_rates(_: str = Depends(get_current_user)):
    return {"source": "MOEX", "rates": await _get_currency_rates()}


@app.get("/api/arbitrage-pairs/events")
async def arbitrage_pair_events(token: str = Query(min_length=1)):
    """SSE stream used by the table to refresh after a live price update."""
    try:
        jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Недействительный токен") from error

    async def events():
        queue: asyncio.Queue[None] = asyncio.Queue()
        _price_update_subscribers.add(queue)
        try:
            yield "data: {\"type\": \"connected\"}\n\n"
            while True:
                await queue.get()
                yield "data: {\"type\": \"prices\"}\n\n"
        finally:
            _price_update_subscribers.discard(queue)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/arbitrage-pairs", status_code=status.HTTP_201_CREATED)
async def create_arbitrage_pair(request: PairCreateRequest, _: str = Depends(get_current_user)):
    exante_symbol_id = request.cme_name.strip()
    bcs_ticker = request.forts_name.strip()
    pool = await create_pool()
    try:
        async with pool.acquire() as connection:
            exante_exists = await connection.fetchval(
                "SELECT EXISTS (SELECT 1 FROM exante_market_data WHERE symbol_id = $1)",
                exante_symbol_id,
            )
            if not exante_exists:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="EXANTE тикер отсутствует в справочнике",
                )

            if bcs_ticker:
                bcs_exists = await connection.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM bcs_market_data WHERE ticker = $1)",
                    bcs_ticker,
                )
                if not bcs_exists:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="BCS тикер отсутствует в справочнике",
                    )

            row = await connection.fetchrow(
                "INSERT INTO arbitrage_pairs (cme_name, forts_name) VALUES ($1, $2) RETURNING id",
                exante_symbol_id,
                bcs_ticker or None,
            )
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Справочники инструментов недоступны. Сначала синхронизируйте данные.",
        ) from error

    # Заполнить доступные метаданные из справочников
    async with pool.acquire() as connection:
        await connection.execute(
            """
            UPDATE arbitrage_pairs
            SET
                cme_data_exp = ex.maturity_date,
                cme_lot = ex.contract_multiplier,
                forts_data_exp = (
                    SELECT maturity_date FROM bcs_market_data
                    WHERE ticker = arbitrage_pairs.forts_name
                ),
                forts_price_step = (
                    SELECT minimum_step FROM bcs_market_data
                    WHERE ticker = arbitrage_pairs.forts_name
                ),
                forts_price_step_value = NULL
            FROM exante_market_data ex
            WHERE arbitrage_pairs.id = $1
              AND ex.symbol_id = arbitrage_pairs.cme_name
            """,
            row["id"],
        )
    await _restart_market_subscriptions()
    if bcs_ticker:
        try:
            await sync_forts_market_parameters([bcs_ticker])
            await _refresh_arbitrage_metrics()
        except Exception as error:
            print(f"Ошибка первичной загрузки параметров FORTS для {bcs_ticker}: {error}", flush=True)
    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            """
            SELECT id, cme_name, cme_data_exp, forts_name, forts_data_exp, cme_lot,
                   forts_price_step, forts_price_step_value
            FROM arbitrage_pairs
            WHERE id = $1
            """,
            row["id"],
        )
    return dict(row)


@app.delete("/api/arbitrage-pairs/{pair_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_arbitrage_pair(
    pair_id: int,
    _: str = Depends(get_current_user),
):
    """Удалить арбитражную пару и обновить подписки на котировки."""
    pool = await create_pool()
    async with pool.acquire() as connection:
        deleted = await connection.fetchval(
            "DELETE FROM arbitrage_pairs WHERE id = $1 RETURNING id",
            pair_id,
        )
    if deleted is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пара не найдена")
    await _restart_market_subscriptions()
    await _publish_price_update()


@app.patch("/api/arbitrage-pairs/{pair_id}/manual-value")
async def update_pair_manual_value(
    pair_id: int,
    request: PairManualValueUpdate,
    _: str = Depends(get_current_user),
):
    """Сохранить вручную заданный параметр арбитражной пары."""
    if not request.value.is_finite():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Значение должно быть конечным числом",
        )
    if request.field == "cme_margin_usd" and request.value < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Margin не может быть отрицательным",
        )

    pool = await create_pool()
    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            f"""
            UPDATE arbitrage_pairs
            SET {request.field} = $1
            WHERE id = $2
            RETURNING id, {request.field} AS value
            """,
            request.value,
            pair_id,
        )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пара не найдена")
    await _refresh_arbitrage_metrics()
    await _publish_price_update()
    return {"id": row["id"], "field": request.field, "value": row["value"]}


@app.patch("/api/arbitrage-pairs/{pair_id}/trade-lot-currency")
async def update_pair_trade_lot_currency(
    pair_id: int,
    request: PairTradeLotCurrencyUpdate,
    _: str = Depends(get_current_user),
):
    """Выбрать валюту официального курса ЦБ РФ для расчёта пары."""
    pool = await create_pool()
    async with pool.acquire() as connection:
        row = await connection.fetchrow(
            """
            UPDATE arbitrage_pairs
            SET trade_lot_currency = $1
            WHERE id = $2
            RETURNING id, trade_lot_currency
            """,
            request.currency,
            pair_id,
        )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пара не найдена")
    await _refresh_arbitrage_metrics()
    await _publish_price_update()
    return {"id": row["id"], "trade_lot_currency": row["trade_lot_currency"]}


@app.get("/api/instrument-options")
async def list_instrument_options(
    provider: str,
    query: str = "",
    limit: int = 20,
    _: str = Depends(get_current_user),
):
    provider_normalized = provider.strip().lower()
    safe_limit = min(max(limit, 1), 20000)

    if provider_normalized == "exante":
        items = await _search_exante_options(query, safe_limit)
    elif provider_normalized == "bcs":
        items = await _search_bcs_options(query, safe_limit)
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Неизвестный провайдер")

    return {"provider": provider_normalized, "query": query, "items": items}

@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": "arbitrage-system-api",
    }


# ===========================================================================
# Заглушки для API
# ===========================================================================

@app.get("/api/portfolio")
async def get_portfolio():
    """
    Получить информацию о портфеле.
    """
    return {
        "totalValue": 0.0,
        "freeBalance": 0.0,
        "positions": [],
        "message": "Заглушка — подключите коннектор БКС или EXANTE",
    }


@app.get("/api/orders")
async def list_orders():
    """Получить список активных заявок."""
    return {
        "orders": [],
        "message": "Заглушка — подключите коннектор БКС или EXANTE",
    }


@app.get("/api/market-data")
async def get_market_data():
    """Получить рыночные данные."""
    return {
        "data": [],
        "message": "Заглушка — подключите WebSocket БКС или EXANTE",
    }


@app.get("/api/connectors")
async def list_connectors():
    """Информация о доступных коннекторах."""
    return {
        "connectors": [
            {
                "name": "bcs",
                "description": "БКС Trade API",
                "status": "configured" if os.getenv("BCS_REFRESH_TOKEN") else "not configured",
            },
            {
                "name": "exante",
                "description": "EXANTE HTTP API",
                "status": "configured" if os.getenv("EXANTE_API_KEY") else "not configured",
            },
        ]
    }


# ===========================================================================
# Точка входа (при прямом запуске)
# ===========================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
