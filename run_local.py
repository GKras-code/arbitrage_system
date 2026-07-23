#!/usr/bin/env python3
"""Локальный запуск бэкенда — uvicorn с авто-перезагрузкой."""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
