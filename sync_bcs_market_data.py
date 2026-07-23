"""Синхронизировать справочник рыночных данных BCS в PostgreSQL."""

import asyncio
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from db import create_pool
from connectors.bcs_connector import BCSConnector

TABLE_NAME = "bcs_market_data"
INSTRUMENT_TYPES = ("FUTURES",)

CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
    ticker TEXT PRIMARY KEY,
    short_name TEXT,
    instrument_type TEXT NOT NULL,
    minimum_step NUMERIC,
    step_price NUMERIC,
    step_price_currency TEXT,
    maturity_date DATE,
    lot_size NUMERIC,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

INSERT_SQL = f"""
INSERT INTO {TABLE_NAME} (
    ticker,
    short_name,
    instrument_type,
    minimum_step,
    step_price,
    step_price_currency,
    maturity_date,
    lot_size
)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
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


def _to_row(instrument: dict[str, Any]) -> tuple[Any, ...] | None:
    ticker = str(instrument.get("ticker") or "").strip()
    if not ticker:
        return None

    return (
        ticker,
        str(instrument.get("shortName") or "").strip() or None,
        str(instrument.get("instrumentType") or instrument.get("type") or "").strip(),
        _decimal(instrument.get("minimumStep")),
        _decimal(instrument.get("stepPrice")),
        str(instrument.get("currencyStepPrice") or "").strip() or None,
        _date(instrument.get("maturityDate")),
        _decimal(instrument.get("lotSize")),
    )


async def get_instruments(connector: BCSConnector) -> list[dict[str, Any]] | bool:
    """Получить типы инструментов, заданные для синхронизации."""
    instruments: list[dict[str, Any]] = []
    for instrument_type in INSTRUMENT_TYPES:
        if instrument_type == "FUTURES":
            batch = await connector.get_all_futures()
        else:
            raise ValueError(f"Не поддержан тип инструмента: {instrument_type}")
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

    rows = [row for instrument in instruments if (row := _to_row(instrument))]
    pool = await create_pool()
    try:
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(CREATE_TABLE_SQL)
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
