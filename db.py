import asyncpg
import os
from dotenv import load_dotenv
from loguru import logger  # Импортируем логгер

load_dotenv()

_pool = None

def _pool_is_usable(pool) -> bool:
    if pool is None:
        return False
    try:
        is_closed = getattr(pool, "is_closed", None)
        if callable(is_closed):
            return not is_closed()
        return not bool(getattr(pool, "_closed", False))
    except Exception:
        return False

async def create_pool():
    global _pool

    if not _pool_is_usable(_pool):
        if _pool is not None:
            try:
                await _pool.close()
            except Exception as e:
                logger.warning(f"Error closing old pool: {e}")
        try:
             _pool = await asyncpg.create_pool(
                user=os.getenv('db_user'),
                password=os.getenv('db_password'),
                host=os.getenv('db_host'),
                port=os.getenv('db_port'),
                database=os.getenv('db_database'),
                max_size=100  # Установите максимальное количество соединений
            )
        except Exception as e:
            logger.error(f"Error creating database pool: {e}")
            raise
    return _pool




# Как посмотреть текущее число соединений в PostgreSQL:
# Использование SQL-запроса: Выполните следующий запрос, чтобы увидеть текущее число соединений:
# SELECT count(*) AS total_connections
# FROM pg_stat_activity;

# Посмотреть соединения по базе данных: Чтобы увидеть количество соединений для каждой базы данных:
# SELECT datname, count(*) AS connections
# FROM pg_stat_activity
# GROUP BY datname;

# Посмотреть подробности о соединениях: Чтобы увидеть подробную информацию о каждом соединении:
# SELECT pid, usename, datname, client_addr, state, backend_start
# FROM pg_stat_activity;


# sudo apt update && sudo apt -y upgrade
# sudo apt -y install python3 python3-venv python3-pip build-essential python3-dev
# pip install -r requirements.txt

#sudo apt install postgresql
#sudo systemctl start postgresql.service
#sudo systemctl enable postgresql --now
# apt install mcedit
#Для начала посмотрим путь расположения конфигурационного файла postgresql.conf:
# su - postgres -c "psql -c 'SHOW config_file;'"
#mcedit /etc/postgresql/16/main/postgresql.conf
#listen_addresses = '*'
# mcedit /etc/postgresql/16/main/pg_hba.conf     host all all 0.0.0.0/0 password
# systemctl restart postgresql
# После установки надо поменять пароль главного юзера
# sudo -u postgres psql
# postgres=# \password
# Создать базу данных для проекта
# postgres=# CREATE DATABASE arbitrage_system;
# Проверить, что база создана
# postgres=# \l
# Выйти из psql
# postgres=# \q
#sudo reboot now

# # Скопировать unit-файлы в systemd (если ещё не скопированы)
# sudo cp amb2.service /etc/systemd/system/amb2.service
# sudo cp fastapi2.service /etc/systemd/system/fastapi2.service

# # Перечитать юниты и включить автозапуск с немедленным стартом
# sudo systemctl daemon-reload
# sudo systemctl enable --now amb2.service fastapi2.service

# # Проверить статус
# systemctl status amb2.service --no-pager
# systemctl status fastapi2.service --no-pager

# # Логи в реальном времени
# journalctl -u amb2.service -n 200 -f
# journalctl -u fastapi2.service -n 200 -f

# # Скопировать unit-файлы в systemd (если ещё не скопированы)
# sudo cp amb2.service /etc/systemd/system/amb2.service
# sudo cp fastapi.service /etc/systemd/system/fastapi.service

# # Перечитать юниты и включить автозапуск с немедленным стартом
# sudo systemctl daemon-reload
# sudo systemctl enable --now amb2.service fastapi.service

# # Проверить статус
# systemctl status amb2.service --no-pager
# systemctl status fastapi.service --no-pager

# # Логи в реальном времени
# journalctl -u amb2.service -n 200 -f
# journalctl -u fastapi.service -n 200 -f