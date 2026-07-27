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


def _initial_margin(payload: dict) -> Decimal | None:
    """Извлечь INITIALMARGIN из ответа ISS в табличном формате."""
    securities = payload.get("securities")
    if not isinstance(securities, dict):
        return None
    columns = securities.get("columns")
    rows = securities.get("data")
    if not isinstance(columns, list) or not isinstance(rows, list) or not rows:
        return None
    try:
        margin_index = columns.index("INITIALMARGIN")
        value = rows[0][margin_index]
        margin = Decimal(str(value))
    except (IndexError, InvalidOperation, ValueError):
        return None
    return margin if margin.is_finite() and margin >= 0 else None


async def _fetch_initial_margin(session: aiohttp.ClientSession, ticker: str) -> Decimal | None:
    url = ISS_SECURITY_URL.format(ticker=quote(ticker, safe=""))
    async with session.get(
        url,
        params={"iss.meta": "off", "iss.only": "securities"},
    ) as response:
        response.raise_for_status()
        payload = await response.json(content_type=None)
    return _initial_margin(payload)


async def sync_forts_margins(tickers: Iterable[str] | None = None) -> int:
    """Сохранить актуальное ГО покупки для заданных FORTS-тикеров."""
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

    async def fetch(ticker: str) -> tuple[Decimal, str] | None:
        try:
            async with semaphore:
                margin = await _fetch_initial_margin(session, ticker)
            return (margin, ticker) if margin is not None else None
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
            "SET forts_margin_rub = $1, forts_margin_updated_at = NOW() "
            "WHERE forts_name = $2",
            updates,
        )
    return len(updates)