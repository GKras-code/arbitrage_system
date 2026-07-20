# Промт-инструкция: Создание FastAPI сервера с фронтендом (доступ по IP, без домена)

## Цель

Создать новый проект с FastAPI бэкендом и фронтендом (Vue/React), который работает по IP-адресу сервера без привязки к доменному имени. Docker Compose для продакшена.

---

## 1. Структура проекта

```
my_project/
├── backend/                 # FastAPI-бэкенд
│   ├── main.py              # Точка входа + роуты
│   ├── requirements.txt     # Зависимости
│   └── Dockerfile           # Сборка образа
│
├── frontend/                # Фронтенд (Vue / React)
│   ├── src/
│   ├── public/
│   ├── Dockerfile           # Nginx + собранная статика
│   ├── nginx.conf           # Конфиг Nginx с проксированием /api/
│   └── package.json
│
├── docker-compose.yml       # Два сервиса: api + web
└── .env                     # Переменные окружения (БД, секреты)
```

---

## 2. FastAPI бэкенд

### `backend/requirements.txt`

```
fastapi>=0.115.0
uvicorn[standard]>=0.34.0
python-multipart>=0.0.12
sqlalchemy>=2.0.0
psycopg[binary]>=3.2.0   # или asyncpg для async
# Любые другие зависимости проекта
```

### `backend/main.py` — минимальный шаблон

```python
from __future__ import annotations

from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles  # если надо раздавать статику


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Здесь: инициализация БД, пула соединений, фоновых задач
    yield
    # Здесь: cleanup


app = FastAPI(title="My Project API", version="0.1.0", lifespan=lifespan)

# CORS — разрешить всё, т.к. фронт может быть на другом порту/IP
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
```

### `backend/Dockerfile`

```dockerfile
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## 3. Фронтенд (пример на Vue 3 + Vite)

### `frontend/Dockerfile`

```dockerfile
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

### `frontend/nginx.conf`

```nginx
server {
    listen 80;
    server_name _;                    # <--- ключ: отвечает на любой Host

    client_max_body_size 100M;

    location /api/ {
        proxy_pass http://backend:8000/api/;   # имя сервиса из docker-compose
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    root /usr/share/nginx/html;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

### `frontend/vite.config.js` (для локальной разработки)

```js
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
```

---

## 4. Docker Compose

### `docker-compose.yml`

```yaml
services:
  backend:
    build:
      context: ./backend
    container_name: my-api
    restart: unless-stopped
    environment:
      db_user: ${db_user}
      db_password: ${db_password}
      db_host: ${db_host}
      db_port: ${db_port:-5432}
      db_database: ${db_database}
      APP_SECRET: ${APP_SECRET:-change-me}
    ports:
      - "8000:8000"       # опционально — для прямого доступа к API
    volumes:
      - ./data:/app/data  # если нужны персистентные файлы

  frontend:
    build:
      context: ./frontend
    container_name: my-web
    restart: unless-stopped
    ports:
      - "80:80"
    depends_on:
      - backend
```

### `.env` (не в git, создать на сервере)

```
db_user=myuser
db_password=mypassword
db_host=host.docker.internal   # или IP внешней БД
db_port=5432
db_database=mydb
APP_SECRET=случайная-строка-32-символа
```

---

## 5. Файл для локального запуска (опционально)

### `run_local.py`

```python
import uvicorn

from backend.main import app

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=True, log_level="info")
```

Запуск:

```bash
pip install -r backend/requirements.txt
python run_local.py
```

---

## 6. Что нужно сделать пользователю (действия)

### Для нового проекта:

1. **Создать структуру папок** как в разделе 1
2. **Скопировать шаблоны файлов** (backend/main.py, Dockerfile, nginx.conf, docker-compose.yml)
3. **Установить зависимости фронта** и проверить сборку:
   ```bash
   cd frontend
   npm install
   npm run build
   ```
4. **Запустить локально и проверить**:
   - `http://localhost:8000/api/health` — бэкенд
   - `http://localhost:5173/` — фронт через Vite dev server (проксирует `/api` на бэкенд)

### Для деплоя на сервер (Ubuntu / любая VPS):

1. **Подключиться по SSH**: `ssh root@<IP_SERVERA>`
2. **Установить Docker + Docker Compose plugin**:
   ```bash
   apt update && apt install -y docker.io docker-compose-v2
   ```
3. **Загрузить проект на сервер** (git clone или scp)
4. **Создать `.env` файл** с реальными параметрами БД и секретами
5. **Собрать и запустить**:
   ```bash
   docker compose up -d --build
   ```
6. **Проверить**:
   ```bash
   curl http://127.0.0.1            # фронт
   curl http://127.0.0.1/api/health # API через Nginx
   ```
7. **Открыть в браузере**: `http://<IP_SERVERA>/`

### Важные моменты:

- **`server_name _;`** в nginx.conf — это ключевая строка, которая заставляет Nginx отвечать на любой Host header (в том числе голый IP)
- **HTTPS не будет** — Let's Encrypt требует доменное имя. На голом IP работает только HTTP (порт 80)
- **CORS** должен быть включён (`allow_origins=["*"]`), если фронт и бэкенд не через один Nginx
- **База данных** — если PostgreSQL, то проще всего использовать внешний сервис (например, на том же сервере) или SQLite для начала
- **Если используется SQLite** — нужно смонтировать volume для файла БД в docker-compose

---

## 7. Полезные команды для сервера

```bash
# Логи
docker compose logs -f backend
docker compose logs -f frontend

# Пересборка
docker compose up -d --build

# Остановка
docker compose down

# Вход в контейнер
docker exec -it my-api sh
```
