"""Обновлять гарантийное обеспечение FORTS из публичного MOEX ISS."""

from __future__ import annotations

import asyncio
import ssl
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Iterable
from urllib.parse import quote

import aiohttp
import certifi

from db import create_pool

ISS_SECURITY_URL = "https://iss.moex.com/iss/engines/futures/markets/forts/securities/{ticker}.json"
REQUEST_TIMEOUT_SECONDS = 15
MAX_CONCURRENT_REQUESTS = 10
MAX_CURRENCY_STEP_DIVISOR_POWER = 12


def _security_decimal(payload: dict, column_name: str) -> Decimal | None:
    """Извлечь числовой параметр из ответа ISS в табличном формате."""
    securities = payload.get("securities")
    if not isinstance(securities, dict):
        return None
    columns = securities.get("columns")
    rows = securities.get("data")
    if not isinstance(columns, list) or not isinstance(rows, list) or not rows:
        return None
    try:
        value = rows[0][columns.index(column_name)]
        result = Decimal(str(value).replace(",", "."))
    except (IndexError, InvalidOperation, ValueError):
        return None
    return result if result.is_finite() and result >= 0 else None


def _restore_step_price_precision(
    step_price: Decimal | None,
    currency_rate: Decimal | None,
) -> Decimal | None:
    """Восстановить знаки STEPPRICE, усечённые MOEX при пересчёте через валютный курс."""
    if (
        step_price is None
        or currency_rate is None
        or step_price <= 0
        or currency_rate <= 0
    ):
        return step_price

    decimal_places = max(0, -step_price.as_tuple().exponent)
    precision = Decimal(1).scaleb(-decimal_places)
    for power in range(1, MAX_CURRENCY_STEP_DIVISOR_POWER + 1):
        precise_step_price = currency_rate / (Decimal(10) ** power)
        if precise_step_price.quantize(precision, rounding=ROUND_HALF_UP) == step_price:
            return precise_step_price
    return step_price


async def _fetch_market_parameters(
    session: aiohttp.ClientSession,
    ticker: str,
) -> tuple[Decimal | None, Decimal | None]:
    """Получить ГО и стоимость шага цены из одной карточки ISS."""
    url = ISS_SECURITY_URL.format(ticker=quote(ticker, safe=""))
    async with session.get(
        url,
        params={"iss.meta": "off", "iss.only": "securities"},
    ) as response:
        response.raise_for_status()
        payload = await response.json(content_type=None)
    return (
        _security_decimal(payload, "INITIALMARGIN"),
        _security_decimal(payload, "STEPPRICE"),
    )


async def sync_forts_market_parameters(tickers: Iterable[str] | None = None) -> int:
    """Сохранить актуальные ГО и стоимость шага цены FORTS из MOEX ISS."""
    pool = await create_pool()
    if tickers is None:
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT forts_name AS ticker FROM cme_future_pairs
                WHERE COALESCE(forts_name, '') <> ''
                UNION
                SELECT first_name AS ticker FROM moex_future_future_pairs
                UNION
                SELECT second_name AS ticker FROM moex_future_future_pairs
                UNION
                SELECT future_name AS ticker FROM moex_spot_future_pairs
                WHERE COALESCE(future_name, '') <> ''
                """
            )
        ticker_list = [str(row["ticker"]) for row in rows if row["ticker"]]
    else:
        ticker_list = list(dict.fromkeys(ticker.strip() for ticker in tickers if ticker.strip()))

    if not ticker_list:
        return 0

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
    ssl_context = ssl.create_default_context(cafile=certifi.where())

    async def fetch(ticker: str) -> tuple[Decimal | None, Decimal | None, str] | None:
        try:
            async with semaphore:
                margin, step_price = await _fetch_market_parameters(session, ticker)
            return (margin, step_price, ticker) if margin is not None or step_price is not None else None
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            return None

    connector = aiohttp.TCPConnector(ssl=ssl_context)
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        results = await asyncio.gather(*(fetch(ticker) for ticker in ticker_list))

    updates = [result for result in results if result is not None]
    if not updates:
        return 0

    parameters_by_ticker = {
        ticker: (margin, step_price)
        for margin, step_price, ticker in updates
    }
    async with pool.acquire() as connection:
        pairs = await connection.fetch(
            """
            SELECT pairs.id, pairs.forts_name, pairs.trade_lot_currency,
                   rates.rate AS currency_rate
            FROM cme_future_pairs AS pairs
            LEFT JOIN currency_rates AS rates
                ON rates.currency_code = pairs.trade_lot_currency
            WHERE pairs.forts_name = ANY($1::varchar[])
            ORDER BY pairs.id
            """,
            list(parameters_by_ticker),
        )
        pair_updates = [
            (
                margin,
                _restore_step_price_precision(step_price, row["currency_rate"]),
                row["id"],
            )
            for row in pairs
            for margin, step_price in [parameters_by_ticker[str(row["forts_name"])]]
        ]
        await connection.executemany(
            "UPDATE cme_future_pairs "
            "SET forts_margin_rub = COALESCE($1, forts_margin_rub), "
            "forts_price_step_value = COALESCE($2, forts_price_step_value) "
            "WHERE id = $3",
            pair_updates,
        )
        future_future_pairs = await connection.fetch(
            """
            SELECT id, first_name, second_name
            FROM moex_future_future_pairs
            WHERE first_name = ANY($1::varchar[]) OR second_name = ANY($1::varchar[])
            """,
            list(parameters_by_ticker),
        )
        future_future_updates = [
            (
                ticker,
                parameters_by_ticker[ticker][0],
                row["id"],
            )
            for row in future_future_pairs
            for ticker in (str(row["first_name"]), str(row["second_name"]))
            if ticker in parameters_by_ticker
        ]
        await connection.executemany(
            """
            UPDATE moex_future_future_pairs
            SET first_margin = CASE WHEN first_name = $1 THEN $2 ELSE first_margin END,
                second_margin = CASE WHEN second_name = $1 THEN $2 ELSE second_margin END
            WHERE id = $3
            """,
            future_future_updates,
        )
        moex_pairs = await connection.fetch(
            """
            SELECT id, future_name
            FROM moex_spot_future_pairs
            WHERE future_name = ANY($1::varchar[])
            """,
            list(parameters_by_ticker),
        )
        await connection.executemany(
            "UPDATE moex_spot_future_pairs "
            "SET future_margin = COALESCE($1, future_margin) "
            "WHERE id = $2",
            [
                (parameters_by_ticker[str(row["future_name"])][0], row["id"])
                for row in moex_pairs
            ],
        )
    return len(updates)


async def sync_forts_margins(tickers: Iterable[str] | None = None) -> int:
    """Совместимое имя синхронизации параметров FORTS."""
    return await sync_forts_market_parameters(tickers)