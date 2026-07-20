"""
FastAPI бэкенд для Arbitrage System.

Запуск (локально):
    uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ---------------------------------------------------------------------------
# Путь к корню проекта (чтобы импортировать connectors)
# ---------------------------------------------------------------------------
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Жизненный цикл приложения: инициализация / cleanup."""
    # --- startup ---
    yield
    # --- shutdown ---


app = FastAPI(
    title="Arbitrage System API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — разрешить всё (фронт на любом IP/порту)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===========================================================================
# Health-check
# ===========================================================================

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
