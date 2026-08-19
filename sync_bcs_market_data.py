"""Синхронизировать справочник рыночных данных BCS в PostgreSQL."""

import asyncio
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from db import create_pool
from connectors.bcs_connector import BCSConnector

TABLE_NAME = "bcs_market_data"
INSTRUMENT_TYPES = ("FUTURES", "CURRENCY", "STOCK")

CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
    ticker TEXT PRIMARY KEY,
    short_name TEXT,
    instrument_type TEXT NOT NULL,
    minimum_step NUMERIC,
    step_price NUMERIC,
    step_price_currency TEXT,
    base_asset TEXT,
    maturity_date DATE,
    lot_size NUMERIC,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

ALTER_TABLE_SQL = f"""
ALTER TABLE {TABLE_NAME}
    ADD COLUMN IF NOT EXISTS step_price NUMERIC,
    ADD COLUMN IF NOT EXISTS step_price_currency TEXT,
    ADD COLUMN IF NOT EXISTS base_asset TEXT
"""

INSERT_SQL = f"""
INSERT INTO {TABLE_NAME} (
    ticker,
    short_name,
    instrument_type,
    minimum_step,
    step_price,
    step_price_currency,
    base_asset,
    maturity_date,
    lot_size
)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
"""


def _decimal(value: Any) -> Decimal | None:
    """Преобразовать число BCS в Decimal или None."""
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _date(value: Any) -> date | None:
    """Преобразовать дату BCS в date или None."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).replace("Z", "+00:00")[:10])
    except ValueError:
        return None


def _primary_board(instrument: dict[str, Any]) -> str:
    """Вернуть первый (первичный) борд инструмента."""
    boards = instrument.get("boards") or []
    if boards and isinstance(boards[0], dict):
        return str(boards[0].get("classCode") or "").strip()
    return ""


def _dedupe_instruments(
    instruments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Оставить один инструмент на тикер, предпочитая первичный борд MOEX (TQBR).

    BCS возвращает по одной записи на каждый торговый режим (board) — например,
    акция SBER есть и в TQBR, и в SPBRU. Таблица индексирована по ticker, поэтому
    дубликаты нужно схлопывать в одну строку.
    """
    best: dict[str, dict[str, Any]] = {}
    for instrument in instruments:
        ticker = str(instrument.get("ticker") or "").strip()
        if not ticker:
            continue
        current = best.get(ticker)
        if current is None or _primary_board(instrument) == "TQBR":
            best[ticker] = instrument
    return list(best.values())


def _to_row(instrument: dict[str, Any]) -> tuple[Any, ...] | None:
    ticker = str(instrument.get("ticker") or "").strip()
    if not ticker:
        return None

    return (
        ticker,
        str(instrument.get("shortName") or "").strip() or None,
        str(instrument.get("instrumentType") or instrument.get("type") or "").strip(),
        _decimal(instrument.get("minimumStep")),
        _decimal(instrument.get("stepPrice") or instrument.get("step_price")),
        str(instrument.get("currencyStepPrice") or instrument.get("stepPriceCurrency") or "").strip() or None,
        str(instrument.get("baseAsset") or instrument.get("base_asset") or "").strip() or None,
        _date(instrument.get("maturityDate")),
        _decimal(instrument.get("lotSize")),
    )


async def get_instruments(connector: BCSConnector) -> list[dict[str, Any]] | bool:
    """Получить типы инструментов, заданные для синхронизации."""
    instruments: list[dict[str, Any]] = []
    for instrument_type in INSTRUMENT_TYPES:
        batch = await connector.get_all_by_type(instrument_type)
        if batch is False:
            return False
        instruments.extend(batch)
    return instruments


async def sync_market_data() -> int:
    """Полностью заменить справочник BCS актуальными инструментами."""
    connector = BCSConnector()
    try:
        instruments = await get_instruments(connector)
    finally:
        await connector.close()

    if instruments is False:
        raise RuntimeError("Не удалось получить инструменты BCS; данные в БД не изменены.")

    instruments = _dedupe_instruments(instruments)
    rows = [row for instrument in instruments if (row := _to_row(instrument))]
    pool = await create_pool()
    try:
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(CREATE_TABLE_SQL)
                await connection.execute(ALTER_TABLE_SQL)
                await connection.execute(f"DELETE FROM {TABLE_NAME}")
                await connection.executemany(INSERT_SQL, rows)
    finally:
        await pool.close()

    return len(rows)


async def main() -> None:
    count = await sync_market_data()
    print(f"Таблица {TABLE_NAME} обновлена: {count} инструментов.")


if __name__ == "__main__":
    asyncio.run(main())
