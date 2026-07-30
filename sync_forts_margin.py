"""Обновлять гарантийное обеспечение FORTS из публичного MOEX ISS."""

from __future__ import annotations

import asyncio
import ssl
from decimal import Decimal, InvalidOperation
from typing import Iterable
from urllib.parse import quote

import aiohttp
import certifi

from db import create_pool

ISS_SECURITY_URL = "https://iss.moex.com/iss/engines/futures/markets/forts/securities/{ticker}.json"
REQUEST_TIMEOUT_SECONDS = 15
MAX_CONCURRENT_REQUESTS = 10


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
                "SELECT DISTINCT forts_name FROM arbitrage_pairs "
                "WHERE COALESCE(forts_name, '') <> ''"
            )
        ticker_list = [str(row["forts_name"]) for row in rows]
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

    async with pool.acquire() as connection:
        await connection.executemany(
            "UPDATE arbitrage_pairs "
            "SET forts_margin_rub = COALESCE($1, forts_margin_rub), "
            "forts_price_step_value = COALESCE($2, forts_price_step_value) "
            "WHERE forts_name = $3",
            updates,
        )
    return len(updates)


async def sync_forts_margins(tickers: Iterable[str] | None = None) -> int:
    """Совместимое имя синхронизации параметров FORTS."""
    return await sync_forts_market_parameters(tickers)