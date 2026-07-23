"""
FastAPI бэкенд для Arbitrage System.

Запуск (локально):
    uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import pbkdf2_hmac
from hmac import compare_digest
from time import monotonic
from typing import Literal

import jwt
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Путь к корню проекта (чтобы импортировать connectors)
# ---------------------------------------------------------------------------
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from db import create_pool
JWT_ALGORITHM = "HS256"
JWT_SECRET = os.getenv("JWT_SECRET", "change-this-jwt-secret-before-production")
PASSWORD_SALT = b"arbitrage-system-user-v1"
bearer_scheme = HTTPBearer(auto_error=False)
REFERENCE_CACHE_TTL_SECONDS = 15 * 60

_instrument_cache: dict[str, tuple[float, list[dict[str, str]]]] = {}


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class PairCreateRequest(BaseModel):
    cme_name: str = Field(min_length=1, max_length=100)
    forts_name: str = Field(min_length=0, max_length=100, default="")


class PairManualValueUpdate(BaseModel):
    field: Literal["virt_0", "cme_margin", "forts_margin_rub"]
    value: Decimal


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
                cme_expiration DATE,
                cme_price NUMERIC(18, 4),
                cme_margin NUMERIC(18, 2),
                cme_lot NUMERIC(18, 4),
                virt_0 NUMERIC(18, 4),
                forts_name VARCHAR(100),
                forts_expiration DATE,
                forts_price NUMERIC(18, 4),
                price_ratio NUMERIC(18, 4),
                forts_margin_rub NUMERIC(18, 2),
                forts_lot NUMERIC(18, 4),
                dte INTEGER,
                diff NUMERIC(18, 4),
                diff_percent NUMERIC(18, 4),
                diff_ytm_margin NUMERIC(18, 4),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
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
        await connection.execute(
            """
            INSERT INTO arbitrage_pairs (
                cme_name, cme_expiration, cme_price, cme_margin, cme_lot, virt_0,
                forts_name, forts_expiration, forts_price, price_ratio,
                forts_margin_rub, forts_lot, dte, diff, diff_percent, diff_ytm_margin
            )
            SELECT * FROM UNNEST(
                $1::varchar[], $2::date[], $3::numeric[], $4::numeric[], $5::numeric[], $6::numeric[],
                $7::varchar[], $8::date[], $9::numeric[], $10::numeric[], $11::numeric[], $12::numeric[],
                $13::integer[], $14::numeric[], $15::numeric[], $16::numeric[]
            )
            WHERE NOT EXISTS (SELECT 1 FROM arbitrage_pairs)
            """,
            ["BZ.NYMEX.U2026", "NG.NYMEX.U2026", "MES.CME.U2026", "GC.COMEX.V2026"],
            [date(2026, 7, 31), date(2026, 8, 27), date(2026, 9, 18), date(2026, 10, 28)],
            [87.12, 2.86, 7550, 4042], [14000, 7160, 2350, 29270], [1000, 10000, 5, 100], [0, 0, -10, -18],
            ["BRQ6", "NGQ6", "SFU6", "GDU6"], [date(2026, 8, 3), date(2026, 8, 27), date(2026, 9, 18), date(2026, 9, 18)],
            [87.35, 2.88, 750, 4032], [1, 1, 10, 1], [15400, 6300, 7500, 28400], [10, 100, 1, 1],
            [9, 36, 58, 58], [0.23, 0.02, -40, 8], [0.26, 0.70, -0.53, 0.20], [27.72, 13.34, -17.64, 7.68],
        )


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
    await initialize_database()
    yield
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
    pool = await create_pool()
    async with pool.acquire() as connection:
        rows = await connection.fetch(
            """
            SELECT id, cme_name, cme_expiration, cme_price, cme_margin, cme_lot, virt_0,
                   forts_name, forts_expiration, forts_price, price_ratio, forts_margin_rub,
                   forts_lot,
                   CASE
                       WHEN cme_expiration IS NULL AND forts_expiration IS NULL THEN NULL
                       WHEN cme_expiration IS NULL THEN forts_expiration - CURRENT_DATE
                       WHEN forts_expiration IS NULL THEN cme_expiration - CURRENT_DATE
                       ELSE LEAST(
                           cme_expiration - CURRENT_DATE,
                           forts_expiration - CURRENT_DATE
                       )
                   END AS dte,
                   diff, diff_percent, diff_ytm_margin
            FROM arbitrage_pairs
            ORDER BY id
            """
        )
    return {"pairs": [dict(row) for row in rows]}


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
                cme_expiration = ex.maturity_date,
                cme_lot = ex.lot_size,
                forts_expiration = (
                    SELECT maturity_date FROM bcs_market_data
                    WHERE ticker = arbitrage_pairs.forts_name
                ),
                forts_lot = (
                    SELECT lot_size FROM bcs_market_data
                    WHERE ticker = arbitrage_pairs.forts_name
                )
            FROM exante_market_data ex
            WHERE arbitrage_pairs.id = $1
              AND ex.symbol_id = arbitrage_pairs.cme_name
            """,
            row["id"],
        )
        # Перечитать обновлённую запись
        row = await connection.fetchrow(
            "SELECT id, cme_name, cme_expiration, forts_name, forts_expiration, cme_lot, forts_lot FROM arbitrage_pairs WHERE id = $1",
            row["id"],
        )
    return dict(row)


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
    if request.field in {"cme_margin", "forts_margin_rub"} and request.value < 0:
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
    return {"id": row["id"], "field": request.field, "value": row["value"]}


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
