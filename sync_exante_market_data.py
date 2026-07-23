"""Синхронизировать справочник рыночных данных EXANTE в PostgreSQL."""

import asyncio
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from connectors.exante_connector import EXANTEConnector
from db import create_pool

TABLE_NAME = "exante_market_data"
SPECIFICATION_REQUEST_DELAY = 0.7
RATE_LIMIT_RETRY_DELAY = 30
SPECIFICATION_RETRIES = 3

CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
    symbol_id TEXT PRIMARY KEY,
    ticker TEXT,
    short_name TEXT,
    instrument_type TEXT NOT NULL,
    minimum_step NUMERIC,
    step_price NUMERIC,
    step_price_currency TEXT,
    maturity_date DATE,
    lot_size NUMERIC,
    contract_multiplier NUMERIC,
    price_unit NUMERIC,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""

INSERT_SQL = f"""
INSERT INTO {TABLE_NAME} (
    symbol_id,
    ticker,
    short_name,
    instrument_type,
    minimum_step,
    step_price,
    step_price_currency,
    maturity_date,
    lot_size,
    contract_multiplier,
    price_unit
)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
"""


def _decimal(value: Any) -> Decimal | None:
    """Преобразовать число EXANTE в Decimal или None."""
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _date(value: Any) -> date | None:
    """Преобразовать дату EXANTE в date или None."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float, Decimal)):
        try:
            timestamp = float(value)
            if timestamp > 100_000_000_000:
                timestamp /= 1000
            return datetime.fromtimestamp(timestamp, tz=timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None
    try:
        return date.fromisoformat(str(value).replace("Z", "+00:00")[:10])
    except ValueError:
        return None


def _step_price(
    minimum_step: Decimal | None,
    contract_multiplier: Decimal | None,
    price_unit: Decimal | None,
) -> Decimal | None:
    """Рассчитать денежную стоимость минимального шага цены."""
    if minimum_step is None or contract_multiplier is None:
        return None
    if price_unit is None or price_unit == 0:
        return minimum_step * contract_multiplier
    return minimum_step * contract_multiplier / price_unit


async def _get_specifications(
    connector: EXANTEConnector,
    instruments: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Загрузить полные спецификации контрактов без превышения лимитов API."""
    specifications: dict[str, dict[str, Any]] = {}
    total = len(instruments)
    print(f"Получено фьючерсов: {total}. Начинаю загрузку спецификаций...", flush=True)

    for index, instrument in enumerate(instruments):
        symbol_id = str(instrument.get("symbolId") or instrument.get("id") or "").strip()
        if not symbol_id:
            continue

        specification: dict | bool = False
        attempt = 0
        while True:
            await asyncio.sleep(SPECIFICATION_REQUEST_DELAY)
            attempt += 1
            # print(
            #     f"[{index + 1}/{total}] Запрашиваю specification для {symbol_id} "
            #     f"(попытка {attempt})...",
            #     flush=True,
            # )
            specification = await connector.get_symbol_specification(symbol_id)

            if isinstance(specification, dict) and str(specification.get("code")) == "429":
                print(
                    f"[{index + 1}/{total}] EXANTE вернул 429. "
                    f"Жду {RATE_LIMIT_RETRY_DELAY} сек. и повторяю запрос...",
                    flush=True,
                )
                await asyncio.sleep(RATE_LIMIT_RETRY_DELAY)
                continue

            if isinstance(specification, dict):
                break

            if attempt >= SPECIFICATION_RETRIES:
                raise RuntimeError(
                    f"Не удалось получить спецификацию EXANTE для {symbol_id}"
                )
            print(
                f"[{index + 1}/{total}] Неуспешный ответ. Повтор через "
                f"{SPECIFICATION_REQUEST_DELAY} сек.",
                flush=True,
            )
        if not isinstance(specification, dict):
            raise RuntimeError(
                f"Не удалось получить спецификацию EXANTE для {symbol_id}"
            )
        if specification.get("lotSize") is None:
            raise RuntimeError(
                f"EXANTE не вернул lotSize для {symbol_id}"
            )

        specifications[symbol_id] = specification
        completed = len(specifications)
        percent = completed / total * 100 if total else 100
        print(
            f"Спецификации: {completed}/{total} ({percent:.1f}%) готово; "
            f"текущий {symbol_id}, lotSize={specification.get('lotSize')}",
            flush=True,
        )
    return specifications


def _to_row(
    instrument: dict[str, Any],
    specification: dict[str, Any],
) -> tuple[Any, ...] | None:
    symbol_id = str(instrument.get("symbolId") or instrument.get("id") or "").strip()
    if not symbol_id:
        return None

    minimum_step = _decimal(
        instrument.get("minPriceIncrement") or instrument.get("mpi")
    )
    contract_multiplier = _decimal(specification.get("contractMultiplier"))
    price_unit = _decimal(specification.get("priceUnit"))

    return (
        symbol_id,
        str(instrument.get("ticker") or "").strip() or None,
        str(instrument.get("name") or instrument.get("description") or "").strip() or None,
        str(instrument.get("symbolType") or instrument.get("type") or "").strip(),
        minimum_step,
        _step_price(minimum_step, contract_multiplier, price_unit),
        str(instrument.get("currency") or "").strip() or None,
        _date(instrument.get("expiration")),
        _decimal(specification.get("lotSize")),
        contract_multiplier,
        price_unit,
    )


async def sync_market_data() -> int:
    """Полностью заменить справочник EXANTE актуальными фьючерсами."""
    print("Подключаюсь к EXANTE и получаю список FUTURES...", flush=True)
    connector = EXANTEConnector()
    try:
        instruments = await connector.get_all_futures()
        if instruments is False:
            raise RuntimeError("Не удалось получить фьючерсы EXANTE; данные в БД не изменены.")
        specifications = await _get_specifications(connector, instruments)
    finally:
        await connector.close()

    rows = [
        row
        for instrument in instruments
        if (row := _to_row(
            instrument,
            specifications.get(str(instrument.get("symbolId") or instrument.get("id") or ""), {}),
        ))
    ]
    if not rows:
        raise RuntimeError("EXANTE не вернул ни одного корректного фьючерса; данные в БД не изменены.")

    print(f"Спецификации загружены. Подготовлено строк: {len(rows)}.", flush=True)
    print(f"Подключаюсь к БД и обновляю таблицу {TABLE_NAME}...", flush=True)
    pool = await create_pool()
    try:
        async with pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(CREATE_TABLE_SQL)
                await connection.execute(f"DELETE FROM {TABLE_NAME}")
                await connection.executemany(INSERT_SQL, rows)
    finally:
        await pool.close()

    print(f"Таблица {TABLE_NAME} успешно обновлена.", flush=True)
    return len(rows)


async def main() -> None:
    count = await sync_market_data()
    print(f"Таблица {TABLE_NAME} обновлена: {count} инструментов.")


if __name__ == "__main__":
    asyncio.run(main())
