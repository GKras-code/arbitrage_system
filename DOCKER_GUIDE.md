# Руководство по управлению Docker

## 📋 Содержание

1. [Первичная настройка](#1-первичная-настройка)
2. [Сборка и запуск](#2-сборка-и-запуск)
3. [Остановка](#3-остановка)
4. [Просмотр логов](#4-просмотр-логов)
5. [Перезапуск отдельных сервисов](#5-перезапуск-отдельных-сервисов)
6. [Работа с базой данных](#6-работа-с-базой-данных)
7. [Полезные команды](#7-полезные-команды)
8. [Устранение неполадок](#8-устранение-неполадок)

---

## 1. Первичная настройка

### 1.1. Копируем `.env`

Файл `.env` уже есть. Убедитесь, что все переменные заполнены.

### 1.2. Убедитесь, что Docker установлен

```bash
docker --version
docker compose version    # или docker-compose --version
```

Если Docker не установлен — скачайте [Docker Desktop](https://www.docker.com/products/docker-desktop/).

---

## 2. Сборка и запуск

### Первый запуск (сборка образов + старт)

```bash
docker compose up -d --build
```

- `-d` — в фоновом режиме
- `--build` — пересобрать образы перед запуском

При повторных запусках можно без `--build`, если код не менялся:

```bash
docker compose up -d
```

### Что запускается?

| Сервис | Контейнер | Доступ по адресу        |
|--------|-----------|-------------------------|
| `web`  | `web`     | `http://<IP-сервера>`   |
| `api`  | `api`     | `http://<IP>:8000/docs` |

> ⚠️ **PostgreSQL** работает отдельно (не в Docker), на IP `109.94.211.122:5432`.

---

## 3. Остановка

### Остановить все сервисы (сохраняя данные)

```bash
docker compose down
```

### Остановить только один сервис

```bash
docker compose stop api
# или:
docker compose stop web
```

---

## 4. Просмотр логов

### Логи всех сервисов

```bash
docker compose logs -f
```

### Логи конкретного сервиса

```bash
docker compose logs -f api
docker compose logs -f web
```

- `-f` — следить за логами в реальном времени (Ctrl+C для выхода)
- `--tail 100` — показать последние 100 строк:

```bash
docker compose logs --tail 100 -f backend
```

---

## 5. Перезапуск отдельных сервисов

### Перезапустить один сервис

```bash
docker compose restart api
```

### Перезапустить с пересборкой образа (после изменений в коде)

```bash
docker compose up -d --build --no-deps api
```

### Перезапустить фронтенд

```bash
docker compose up -d --build --no-deps web
```

---

## 6. Полезные команды

| Команда                                              | Описание                              |
|------------------------------------------------------|---------------------------------------|
| `docker compose ps`                                  | Состояние контейнеров                 |
| `docker compose images`                              | Список собранных образов              |
| `docker compose top`                                 | Процессы внутри контейнеров           |
| `docker compose exec api python -c "..."`            | Выполнить Python-команду в контейнере |
| `docker compose exec api /bin/sh`                    | Зайти в shell контейнера api          |
| `docker compose exec web /bin/sh`                    | Зайти в shell контейнера web          |
| `docker system df`                                   | Место на диске (образы, контейнеры)   |
| `docker system prune -a`                             | Очистить неиспользуемые образы (⚠️)   |

---

## 8. Работа с базой данных

База данных PostgreSQL **не в Docker**, работает отдельно на `109.94.211.122:5432`.

### Подключиться

```bash
psql -h 109.94.211.122 -U postgres -d anymoneybot2_0_new
```

### Создать резервную копию (dump)

```bash
pg_dump -h 109.94.211.122 -U postgres anymoneybot2_0_new > backup.sql
```

### Восстановить из дампа

```bash
psql -h 109.94.211.122 -U postgres -d anymoneybot2_0_new < backup.sql
```

---

## 8. Устранение неполадок

### 🔴 Порт 80 уже занят

Измените внешний порт в `docker-compose.yml`:

```yaml
ports:
  - "8080:80"     # теперь фронт доступен на порту 8080
```

### 🔴 Бэкенд не может подключиться к БД

1. Убедитесь, что PostgreSQL доступен:
   ```bash
   psql -h 109.94.211.122 -U postgres -d anymoneybot2_0_new -c "SELECT 1"
   ```

2. Проверьте логи бэкенда:
   ```bash
   docker compose logs backend
   ```

3. Убедитесь, что `db_host` в `.env` указывает на правильный IP.

### 🔴 Ошибка "port is already allocated"

Убейте процесс, занимающий порт:

```bash
netstat -ano | findstr :5432    # Windows
# или
docker compose down              # остановить контейнеры
```

### 🔴 Пересобрать всё с нуля

```bash
docker compose down -v          # остановить + удалить volume
docker compose up -d --build    # собрать заново и запустить
```

---

## 💡 Быстрый старт (шпаргалка)

```bash
# 1. Настроить окружение
copy .env.example .env
# → отредактировать .env

# 2. Собрать и запустить
docker compose up -d --build

# 3. Проверить
docker compose ps
curl http://localhost/api/health
# Открыть в браузере http://localhost

# 4. Смотреть логи
docker compose logs -f

# 5. Остановить
docker compose down
```
