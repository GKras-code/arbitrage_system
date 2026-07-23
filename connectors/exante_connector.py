"""
Коннектор для EXANTE HTTP API (Market Data).

Документация: https://api-live.exante.eu/api-docs/

Аутентификация:
- JWT (HS256) — передаётся в заголовке Authorization: Bearer <jwt>
- Либо Basic auth (api-key:secret-key)

Стиль — async/aiohttp (единый BCS-подобный dispatcher).
"""

import os
import sys
import json
import time
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import aiohttp
import jwt as pyjwt
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Пути и загрузка .env
# ---------------------------------------------------------------------------

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Константы HTTP (из .env, общие с BCS)
# ---------------------------------------------------------------------------

HTTP_TIMEOUT_TOTAL = float(os.getenv("HTTP_TIMEOUT_TOTAL", "12"))
HTTP_TIMEOUT_CONNECT = float(os.getenv("HTTP_TIMEOUT_CONNECT", "5"))
HTTP_TIMEOUT_SOCK_READ = float(os.getenv("HTTP_TIMEOUT_SOCK_READ", "18"))
HTTP_RETRIES = int(os.getenv("HTTP_RETRIES", "2"))
HTTP_RETRY_BACKOFF = float(os.getenv("HTTP_RETRY_BACKOFF", "0.7"))

# ---------------------------------------------------------------------------
# Константы EXANTE API
# ---------------------------------------------------------------------------

# Аутентификация
EXANTE_API_KEY = os.getenv("EXANTE_API_KEY", "")
EXANTE_SECRET_KEY = os.getenv("EXANTE_SECRET_KEY", "")       # для basic auth
EXANTE_SHARED_KEY = os.getenv("EXANTE_SHARED_KEY", "")        # для JWT (HS256)
EXANTE_CLIENT_ID = os.getenv("EXANTE_CLIENT_ID", "")          # iss
EXANTE_APPLICATION_ID = os.getenv("EXANTE_APPLICATION_ID", "")  # sub
EXANTE_JWT = os.getenv("EXANTE_JWT", "")                      # готовый JWT
EXANTE_SSL_VERIFY = os.getenv("EXANTE_SSL_VERIFY", "true").strip().lower() != "false"

# API Base URLs
EXANTE_MD_API = os.getenv("EXANTE_MD_API", "https://api-live.exante.eu/md")
EXANTE_TRADE_API = os.getenv("EXANTE_TRADE_API", "https://api-live.exante.eu/trade")

# Версия API (по умолчанию 3.0)
EXANTE_API_VERSION = os.getenv("EXANTE_API_VERSION", "3.0")

# Допустимые аудитории JWT
JWT_AUD = [
    "ohlc",
    "crossrates",
    "symbols",
    "change",
    "feed",
    "orders",
    "summary",
    "accounts",
]

# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def _f(x, default=0.0):
    """Безопасное приведение к float."""
    try:
        return float(x)
    except Exception:
        return default


def _generate_jwt(
    client_id: str,
    application_id: str,
    shared_key: str,
    aud: list[str] | None = None,
    ttl_seconds: int = 3600,
) -> str:
    """
    Генерирует JWT для EXANTE API (HS256).

    Параметры
    ---------
    client_id : str
        Идентификатор клиента (claim 'iss').
    application_id : str
        Идентификатор приложения (claim 'sub').
    shared_key : str
        Секрет для подписи (HS256).
    aud : list[str] | None
        Список разрешённых сервисов. По умолчанию JWT_AUD.
    ttl_seconds : int
        Время жизни токена в секундах (по умолчанию 1 час).

    Returns
    -------
    str
        Закодированный JWT.
    """
    now = int(time.time())
    payload = {
        "iss": client_id,
        "sub": application_id,
        "iat": now,
        "exp": now + ttl_seconds,
        "aud": aud or JWT_AUD,
    }
    return pyjwt.encode(payload, shared_key, algorithm="HS256")


# ---------------------------------------------------------------------------
# EXANTEConnector
# ---------------------------------------------------------------------------

class EXANTEConnector:
    """
    Коннектор к EXANTE HTTP API (Market Data + Trades).

    Использование
    -------------
    connector = EXANTEConnector()
    accounts = await connector.get_accounts()
    trades = await connector.stream_trades(["AAPL.NASDAQ"], callback)
    last_quote = await connector.get_last_quote(["AAPL.NASDAQ"])
    ticks = await connector.get_ticks("AAPL.NASDAQ", type="trades")
    """

    def __init__(
        self,
        jwt_token: str | None = None,
        api_key: str | None = None,
        secret_key: str | None = None,
        shared_key: str | None = None,
        client_id: str | None = None,
        application_id: str | None = None,
        ssl_verify: bool | None = None,
    ):
        """
        Параметры
        ---------
        jwt_token : str | None
            Готовый JWT-токен. Если передан — используется он.
            Иначе будет сгенерирован из api_key/shared_key/client_id/application_id.
        api_key : str | None
            API-ключ (он же application_id / sub).
        secret_key : str | None
            Секретный ключ (для Basic Auth, если JWT не используется).
        shared_key : str | None
            Shared key (для генерации JWT HS256).
        client_id : str | None
            Идентификатор клиента (iss).
        application_id : str | None
            Идентификатор приложения (sub) = api_key.
        ssl_verify : bool | None
            Проверка SSL-сертификатов.
        """
        self._api_key = api_key or EXANTE_API_KEY
        self._secret_key = secret_key or EXANTE_SECRET_KEY
        self._shared_key = shared_key or EXANTE_SHARED_KEY
        self._client_id = client_id or EXANTE_CLIENT_ID
        self._application_id = application_id or EXANTE_APPLICATION_ID
        self._ssl_verify = ssl_verify if ssl_verify is not None else EXANTE_SSL_VERIFY

        # JWT
        self._jwt_token: str | None = jwt_token or EXANTE_JWT or None

        # Если JWT не задан явно, но есть все компоненты — генерируем
        if not self._jwt_token:
            if self._client_id and self._application_id and self._shared_key:
                self._jwt_token = _generate_jwt(
                    self._client_id, self._application_id, self._shared_key
                )
                logger.info("Сгенерирован новый JWT для EXANTE")
            else:
                logger.warning(
                    "EXANTE: JWT не задан. Будет использована Basic Auth."
                )

        # HTTP session (экземплярная, не классовая!)
        self.__init_session_pool()

        self._jwt_expires_at: float = 0.0
        self._decode_jwt_expiry()

    @property
    def jwt_token(self) -> str:
        """Возвращает текущий JWT-токен (полезно для отладки)."""
        return self._jwt_token or ""

    # ------------------------------------------------------------------
    # Управление JWT
    # ------------------------------------------------------------------

    def _decode_jwt_expiry(self) -> None:
        """Декодирует exp из JWT (без проверки подписи)."""
        if not self._jwt_token:
            return
        try:
            unverified = pyjwt.decode(
                self._jwt_token, options={"verify_signature": False}
            )
            exp = unverified.get("exp", 0)
            self._jwt_expires_at = float(exp) if exp else 0.0
        except Exception:
            self._jwt_expires_at = 0.0

    async def ensure_token(self) -> str:
        """
        Гарантирует наличие действующего JWT.
        Если токен истекает < 60 сек, генерирует новый.

        Returns
        -------
        str
            Актуальный JWT (или None при Basic Auth).
        """
        if self._jwt_token and time.time() >= self._jwt_expires_at - 60:
            if self._client_id and self._application_id and self._shared_key:
                self._jwt_token = _generate_jwt(
                    self._client_id, self._application_id, self._shared_key
                )
                self._decode_jwt_expiry()
                logger.info("EXANTE JWT обновлён")
            else:
                logger.warning("EXANTE: нет компонентов для перегенерации JWT")
        return self._jwt_token or ""

    # ------------------------------------------------------------------
    # Построение заголовков аутентификации
    # ------------------------------------------------------------------

    @staticmethod
    async def _call_handler(handler, *args, **kwargs):
        """Вызывает handler независимо от того, sync он или async."""
        if handler is None:
            return
        result = handler(*args, **kwargs)
        if result is not None and hasattr(result, "__await__"):
            await result

    def _build_auth_headers(self) -> dict[str, str]:
        """
        Строит заголовки аутентификации:
        - JWT Bearer, если есть токен
        - Basic Auth, если есть api_key + secret_key и нет JWT
        """
        if self._jwt_token:
            return {"Authorization": f"Bearer {self._jwt_token}"}
        if self._api_key and self._secret_key:
            import base64
            credentials = f"{self._api_key}:{self._secret_key}"
            encoded = base64.b64encode(credentials.encode()).decode()
            return {"Authorization": f"Basic {encoded}"}
        return {}

    # ------------------------------------------------------------------
    # HTTP-диспетчер
    # ------------------------------------------------------------------

    def __init_session_pool(self) -> None:
        """Инициализирует экземплярную сессию (вызывается из __init__)."""
        self._session_pool: aiohttp.ClientSession | None = None

    def _create_session(self) -> aiohttp.ClientSession:
        """Создаёт/возвращает единую сессию с таймаутами и SSL."""
        if self._session_pool is None or self._session_pool.closed:
            timeout = aiohttp.ClientTimeout(
                total=HTTP_TIMEOUT_TOTAL,
                connect=HTTP_TIMEOUT_CONNECT,
                sock_read=HTTP_TIMEOUT_SOCK_READ,
            )
            tcp_connector = aiohttp.TCPConnector(ssl=self._ssl_verify)
            self._session_pool = aiohttp.ClientSession(
                timeout=timeout, connector=tcp_connector
            )
        return self._session_pool

    async def close(self) -> None:
        """Закрывает пул сессий."""
        pool = self._session_pool
        self._session_pool = None
        if pool and not pool.closed:
            await pool.close()

    async def send_request(
        self,
        method: str,
        url: str,
        params: dict | None = None,
        body: dict | None = None,
        stream: bool = False,
    ) -> dict | list | bool:
        """
        Единый диспетчер HTTP-запросов с retry-логикой.

        Параметры
        ---------
        method : str
            GET / POST / PUT / DELETE.
        url : str
            Полный URL эндпоинта.
        params : dict | None
            Query-параметры.
        body : dict | None
            JSON-тело запроса.
        stream : bool
            Если True — вернуть сырой response для потокового чтения.

        Returns
        -------
        dict | list | aiohttp.ClientResponse | False
        """
        await self.ensure_token()
        headers = {
            "Accept": "application/json",
            **self._build_auth_headers(),
        }

        # Query string
        if params:
            qs = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
            if qs:
                url = f"{url}?{qs}"

        for attempt in range(HTTP_RETRIES + 1):
            try:
                session = self._create_session()
                async with session.request(
                    method, url, headers=headers, json=body
                ) as response:
                    if stream:
                        return response

                    try:
                        data = await response.json()
                    except aiohttp.ContentTypeError:
                        return {
                            "code": response.status,
                            "msg": response.reason,
                        }

                    if response.status >= 400:
                        # 429 Too Many Requests — retry с Retry-After
                        if response.status == 429:
                            retry_after = int(
                                response.headers.get("Retry-After", "5")
                            )
                            logger.warning(
                                "EXANTE 429, пауза %d сек (попытка %d/%d)",
                                retry_after,
                                attempt + 1,
                                HTTP_RETRIES + 1,
                            )
                            await asyncio.sleep(retry_after)
                            # 429 — это не ошибка данных, пробуем снова в цикле
                            # (не выходим через return False)
                            continue

                        logger.error(
                            "EXANTE HTTP %s %s: %s", response.status, url, data
                        )
                        return False
                    return data

            except (asyncio.TimeoutError, aiohttp.ClientError) as e:
                if attempt < HTTP_RETRIES:
                    await asyncio.sleep(HTTP_RETRY_BACKOFF * (2**attempt))
                    continue
                logger.error("EXANTE HTTP error: %s", e)
                return False
            except Exception as e:
                logger.error("EXANTE unexpected error: %s", e)
                return False

        return False

    # ------------------------------------------------------------------
    # MD API — Accounts (получение списка счетов)
    # ------------------------------------------------------------------

    async def get_accounts(self) -> list | bool:
        """
        GET /md/{version}/accounts

        Returns
        -------
        list[dict] | False
            [{"status": "Full", "accountId": "ABC1234.001"}, ...]
        """
        url = f"{EXANTE_MD_API}/{EXANTE_API_VERSION}/accounts"
        res = await self.send_request("GET", url)
        if not isinstance(res, list):
            logger.error("EXANTE accounts: %s", res)
            return False
        return res

    # ------------------------------------------------------------------
    # MD API — Account Summary
    # ------------------------------------------------------------------

    async def get_account_summary(
        self, account_id: str, currency: str = "USD"
    ) -> dict | bool:
        """
        GET /md/{version}/summary/{id}/{currency}

        Returns
        -------
        dict | False
        """
        url = f"{EXANTE_MD_API}/{EXANTE_API_VERSION}/summary/{account_id}/{currency}"
        res = await self.send_request("GET", url)
        if not isinstance(res, dict):
            logger.error("EXANTE account summary: %s", res)
            return False
        return res

    # ------------------------------------------------------------------
    # MD API — Symbol Info
    # ------------------------------------------------------------------

    async def get_symbol(self, symbol_id: str) -> dict | bool:
        """
        GET /md/{version}/symbols/{symbolId}

        Returns
        -------
        dict | False
        """
        url = f"{EXANTE_MD_API}/{EXANTE_API_VERSION}/symbols/{symbol_id}"
        res = await self.send_request("GET", url)
        if not isinstance(res, dict):
            logger.error("EXANTE symbol: %s", res)
            return False
        return res

    async def get_symbol_schedule(self, symbol_id: str) -> dict | bool:
        """
        GET /md/{version}/symbols/{symbolId}/schedule
        """
        url = f"{EXANTE_MD_API}/{EXANTE_API_VERSION}/symbols/{symbol_id}/schedule"
        return await self.send_request("GET", url)

    async def get_symbol_specification(self, symbol_id: str) -> dict | bool:
        """
        GET /md/{version}/symbols/{symbolId}/specification
        """
        url = f"{EXANTE_MD_API}/{EXANTE_API_VERSION}/symbols/{symbol_id}/specification"
        return await self.send_request("GET", url)

    async def get_exchanges(self) -> list | bool:
        """
        GET /md/{version}/exchanges
        """
        url = f"{EXANTE_MD_API}/{EXANTE_API_VERSION}/exchanges"
        return await self.send_request("GET", url)

    async def get_exchange_symbols(self, exchange_id: str) -> list | bool:
        """
        GET /md/{version}/exchanges/{exchangeId}
        """
        url = f"{EXANTE_MD_API}/{EXANTE_API_VERSION}/exchanges/{exchange_id}"
        return await self.send_request("GET", url)

    async def get_groups(self) -> list | bool:
        """
        GET /md/{version}/groups
        """
        url = f"{EXANTE_MD_API}/{EXANTE_API_VERSION}/groups"
        return await self.send_request("GET", url)

    async def get_group_symbols(self, group_id: str) -> list | bool:
        """
        GET /md/{version}/groups/{groupId}
        """
        url = f"{EXANTE_MD_API}/{EXANTE_API_VERSION}/groups/{group_id}"
        return await self.send_request("GET", url)

    async def get_all_futures(self) -> list[dict] | bool:
        """Получить все доступные фьючерсы EXANTE.

        Каталог групп содержит группы с типом FUTURE, но отдельная группа может
        также включать опционы. Поэтому результат дополнительно фильтруется по
        полю symbolType и дедуплицируется по symbolId.

        Returns
        -------
        list[dict] | False
            Полный список фьючерсов или False, если не удалось загрузить
            каталог либо одну из групп.
        """
        groups = await self.get_groups()
        if not isinstance(groups, list):
            logger.error("EXANTE get_all_futures: не удалось получить группы")
            return False

        future_group_ids: list[str] = []
        for group in groups:
            types = group.get("types") or []
            if isinstance(types, str):
                types = [types]
            if "FUTURE" not in {str(item).upper() for item in types}:
                continue

            group_id = str(group.get("group") or "").strip()
            if group_id and group_id not in future_group_ids:
                future_group_ids.append(group_id)

        total_groups = len(future_group_ids)
        print(
            f"EXANTE: найдено FUTURE-групп: {total_groups}. "
            "Начинаю загрузку групп...",
            flush=True,
        )
        futures_by_id: dict[str, dict] = {}
        for group_index, group_id in enumerate(future_group_ids, start=1):
            print(
                f"EXANTE FUTURES: группа {group_index}/{total_groups} "
                f"({group_id}), накоплено контрактов: {len(futures_by_id)}...",
                flush=True,
            )
            await asyncio.sleep(1.0)  # небольшая пауза между запросами
            symbols = await self.get_group_symbols(group_id)
            if not isinstance(symbols, list):
                logger.error(
                    "EXANTE get_all_futures: не удалось получить группу '%s'",
                    group_id,
                )
                continue

            for symbol in symbols:
                symbol_type = str(
                    symbol.get("symbolType") or symbol.get("type") or ""
                ).upper()
                symbol_id = str(
                    symbol.get("symbolId") or symbol.get("id") or ""
                ).strip()
                if symbol_type == "FUTURE" and symbol_id:
                    futures_by_id[symbol_id] = symbol

            # print(
            #     f"EXANTE FUTURES: группа {group_index}/{total_groups} готова, "
            #     f"всего контрактов: {len(futures_by_id)}.",
            #     flush=True,
            # )

        futures = list(futures_by_id.values())
        print(
            f"EXANTE FUTURES: загрузка завершена, контрактов: {len(futures)}.",
            flush=True,
        )
        return futures

    # ------------------------------------------------------------------
    # MD API — Daily Change
    # ------------------------------------------------------------------

    async def get_daily_change(self, symbol_ids: str | list[str]) -> dict | list | bool:
        """
        GET /md/{version}/change/{symbolId}

        symbol_ids : str | list[str]
            Один символ (str) или список символов, разделённых запятой.
        """
        if isinstance(symbol_ids, (list, tuple)):
            symbol_ids = ",".join(symbol_ids)
        url = f"{EXANTE_MD_API}/{EXANTE_API_VERSION}/change/{symbol_ids}"
        return await self.send_request("GET", url)

    # ------------------------------------------------------------------
    # MD API — Crossrates
    # ------------------------------------------------------------------

    async def get_crossrate(self, from_c: str, to_c: str) -> dict | bool:
        """
        GET /md/{version}/crossrates/{from}/{to}
        """
        url = f"{EXANTE_MD_API}/{EXANTE_API_VERSION}/crossrates/{from_c}/{to_c}"
        return await self.send_request("GET", url)

    # ------------------------------------------------------------------
    # MD API — Historical Ticks
    # ------------------------------------------------------------------

    async def get_ticks(
        self,
        symbol_id: str,
        tick_type: str = "trades",
        from_ts: int | None = None,
        to_ts: int | None = None,
        size: int = 1000,
    ) -> list | bool:
        """
        GET /md/3.0/ticks/{symbolId}

        Возвращает исторические тики (сделки или котировки).

        Параметры
        ---------
        symbol_id : str
            ID инструмента (например "AAPL.NASDAQ").
        tick_type : str
            "trades" или "quotes".
        from_ts : int | None
            Начальный timestamp в ms.
        to_ts : int | None
            Конечный timestamp в ms.
        size : int
            Максимум записей (по умолч. 1000).

        Returns
        -------
        list[dict] | False
        """
        params = {"type": tick_type, "size": str(size)}
        if from_ts is not None:
            params["from"] = str(from_ts)
        if to_ts is not None:
            params["to"] = str(to_ts)

        url = f"{EXANTE_MD_API}/3.0/ticks/{symbol_id}"
        res = await self.send_request("GET", url, params=params)
        if not isinstance(res, list):
            logger.error("EXANTE ticks: %s", res)
            return False
        return res

    # ------------------------------------------------------------------
    # MD API — Historical OHLC
    # ------------------------------------------------------------------

    async def get_ohlc(
        self,
        symbol_id: str,
        duration: int = 3600,
        from_ts: int | None = None,
        to_ts: int | None = None,
        size: int = 60,
        ohlc_type: str = "quotes",
    ) -> list | bool:
        """
        GET /md/{version}/ohlc/{symbolId}/{duration}

        Возвращает исторические OHLC-свечи.

        Параметры
        ---------
        symbol_id : str
        duration : int
            Интервал в секундах: 60, 300, 600, 900, 1800, 3600, 14400, 21600, 86400
        from_ts : int | None
            Начальный timestamp в ms.
        to_ts : int | None
            Конечный timestamp в ms.
        size : int
            Максимум свечей.
        ohlc_type : str
            "quotes" или "trades".
        """
        params = {"size": str(size), "type": ohlc_type}
        if from_ts is not None:
            params["from"] = str(from_ts)
        if to_ts is not None:
            params["to"] = str(to_ts)

        url = f"{EXANTE_MD_API}/{EXANTE_API_VERSION}/ohlc/{symbol_id}/{duration}"
        res = await self.send_request("GET", url, params=params)
        if not isinstance(res, list):
            logger.error("EXANTE OHLC: %s", res)
            return False
        return res

    # ------------------------------------------------------------------
    # MD API — Live Feed: Last Quote
    # ------------------------------------------------------------------

    async def get_last_quote(
        self, symbol_ids: str | list[str]
    ) -> list | bool:
        """
        GET /md/{version}/feed/{symbolIds}/last

        Возвращает последнюю котировку для запрошенных инструментов.

        Параметры
        ---------
        symbol_ids : str | list[str]
            Один или несколько symbolId, разделённых запятой.

        Returns
        -------
        list[dict] | False
        """
        if isinstance(symbol_ids, (list, tuple)):
            symbol_ids = ",".join(symbol_ids)
        url = f"{EXANTE_MD_API}/{EXANTE_API_VERSION}/feed/{symbol_ids}/last"
        res = await self.send_request("GET", url)
        if not isinstance(res, list):
            logger.error("EXANTE last quote: %s", res)
            return False
        return res

    # ------------------------------------------------------------------
    # MD API — Live Feed: Trades Stream (HTTP streaming)
    # ------------------------------------------------------------------

    async def stream_trades(
        self,
        symbol_ids: str | list[str],
        on_trade: Callable[[dict], Any] | None = None,
        on_error: Callable[[Exception], Any] | None = None,
        buffer_size: int = 100,
    ) -> None:
        """
        GET /md/3.0/feed/trades/{symbolIds}
        Accept: application/x-json-stream

        Потоковое получение сделок в реальном времени (HTTP Streaming).
        **Блокирующий вызов** — работает, пока соединение не будет закрыто.

        Параметры
        ---------
        symbol_ids : str | list[str]
            Один или несколько symbolId, разделённых запятой.
        on_trade : callable | None
            Обработчик каждой сделки. Принимает dict:
            {
                "timestamp": 1550833075530,
                "symbolId": "AAPL.NASDAQ",
                "price": "101.02",
                "size": "42"
            }
        on_error : callable | None
            Обработчик ошибок.
        buffer_size : int
            Размер буфера сообщений перед вызовом колбэка.
        """
        if isinstance(symbol_ids, (list, tuple)):
            symbol_ids = ",".join(symbol_ids)

        url = f"{EXANTE_MD_API}/3.0/feed/trades/{symbol_ids}"

        if on_trade is None:
            on_trade = lambda trade: logger.info("EXANTE trade: %s", trade)

        await self.ensure_token()
        headers = {
            "Accept": "application/x-json-stream",
            **self._build_auth_headers(),
        }

        buffer: list[dict] = []
        stream_session: aiohttp.ClientSession | None = None

        while True:
            try:
                # Закрываем предыдущую сессию стрима (если была)
                if stream_session is not None and not stream_session.closed:
                    await stream_session.close()
                    stream_session = None

                # Отдельная сессия для стрима
                timeout = aiohttp.ClientTimeout(total=None)
                tcp_connector = aiohttp.TCPConnector(
                    ssl=self._ssl_verify, force_close=True
                )
                stream_session = aiohttp.ClientSession(
                    timeout=timeout, connector=tcp_connector
                )

                async with stream_session.get(
                    url, headers=headers,
                ) as response:
                        response.raise_for_status()
                        logger.info(
                            "EXANTE trades stream connected: %s", url
                        )

                        async for line_bytes in response.content:
                            raw = line_bytes.decode("utf-8").strip()
                            if not raw:
                                continue

                            try:
                                trade = json.loads(raw)
                            except json.JSONDecodeError:
                                logger.warning(
                                    "EXANTE stream non-JSON: %s", raw
                                )
                                continue

                            buffer.append(trade)
                            if len(buffer) >= buffer_size:
                                for t in buffer:
                                    await self._call_handler(on_trade, t)
                                buffer.clear()

            except asyncio.CancelledError:
                logger.info("EXANTE trades stream cancelled")
                for t in buffer:
                    await self._call_handler(on_trade, t)
                buffer.clear()
                if stream_session and not stream_session.closed:
                    await stream_session.close()
                stream_session = None
                return

            except Exception as e:
                logger.error("EXANTE trades stream error: %s", e)
                if on_error:
                    await self._call_handler(on_error, e)

                for t in buffer:
                    await self._call_handler(on_trade, t)
                buffer.clear()

                if stream_session and not stream_session.closed:
                    await stream_session.close()
                stream_session = None

                await asyncio.sleep(5)
                logger.info("EXANTE trades stream reconnecting in 5s...")

    # ------------------------------------------------------------------
    # MD API — Live Feed: Quotes Stream (HTTP streaming)
    # ------------------------------------------------------------------

    async def _stream_feed(
        self,
        symbol_ids: str | list[str],
        params: dict[str, str],
        stream_name: str,
        on_data: Callable[[dict], Any] | None = None,
        on_error: Callable[[Exception], Any] | None = None,
        buffer_size: int = 100,
    ) -> None:
        """
        Универсальный HTTP-стрим для feed-эндпоинтов EXANTE.
        Не WebSocket — обычный HTTP с Content-Type application/x-json-stream.

        **Блокирующий вызов**. Автореконнект с паузой 5с.
        """
        if isinstance(symbol_ids, (list, tuple)):
            symbol_ids = ",".join(symbol_ids)

        url = f"{EXANTE_MD_API}/{EXANTE_API_VERSION}/feed/{symbol_ids}"

        if on_data is None:
            on_data = lambda d: logger.info("EXANTE %s: %s", stream_name, d)

        await self.ensure_token()
        headers = {
            "Accept": "application/x-json-stream",
            **self._build_auth_headers(),
        }

        buffer: list[dict] = []
        stream_session: aiohttp.ClientSession | None = None

        while True:
            try:
                if stream_session is not None and not stream_session.closed:
                    await stream_session.close()
                    stream_session = None

                timeout = aiohttp.ClientTimeout(total=None)
                tcp_connector = aiohttp.TCPConnector(
                    ssl=self._ssl_verify, force_close=True
                )
                stream_session = aiohttp.ClientSession(
                    timeout=timeout, connector=tcp_connector
                )

                qs = "&".join(f"{k}={v}" for k, v in params.items())
                full_url = f"{url}?{qs}"
                async with stream_session.get(
                    full_url, headers=headers,
                ) as response:
                        response.raise_for_status()
                        logger.info("EXANTE %s stream connected", stream_name)

                        async for line_bytes in response.content:
                            raw = line_bytes.decode("utf-8").strip()
                            if not raw:
                                continue
                            try:
                                data = json.loads(raw)
                            except json.JSONDecodeError:
                                logger.warning(
                                    "EXANTE %s non-JSON: %s", stream_name, raw
                                )
                                continue

                            buffer.append(data)
                            if len(buffer) >= buffer_size:
                                batch = list(buffer)
                                buffer.clear()
                                for item in batch:
                                    await self._call_handler(on_data, item)

            except asyncio.CancelledError:
                logger.info("EXANTE %s stream cancelled", stream_name)
                for item in buffer:
                    await self._call_handler(on_data, item)
                buffer.clear()
                if stream_session and not stream_session.closed:
                    await stream_session.close()
                stream_session = None
                return

            except Exception as e:
                logger.error("EXANTE %s stream error: %s", stream_name, e)
                if on_error:
                    await self._call_handler(on_error, e)
                for item in buffer:
                    await self._call_handler(on_data, item)
                buffer.clear()
                if stream_session and not stream_session.closed:
                    await stream_session.close()
                stream_session = None
                await asyncio.sleep(5)

    async def stream_quotes(
        self,
        symbol_ids: str | list[str],
        level: str = "best_price",
        on_quote: Callable[[dict], Any] | None = None,
        on_error: Callable[[Exception], Any] | None = None,
        buffer_size: int = 100,
    ) -> None:
        """
        GET /md/{version}/feed/{symbolIds}?level=best_price|market_depth
        Accept: application/x-json-stream

        Поток котировок. level='market_depth' даёт полный стакан.

        Параметры
        ---------
        symbol_ids : str | list[str]
            Один или несколько symbolId, разделённых запятой.
        level : str
            "best_price" (только лучшие bid/ask) или "market_depth" (весь стакан).
        """
        await self._stream_feed(
            symbol_ids=symbol_ids,
            params={"level": level},
            stream_name=f"quotes({level})",
            on_data=on_quote,
            on_error=on_error,
            buffer_size=buffer_size,
        )

    async def stream_orderbook(
        self,
        symbol_ids: str | list[str],
        on_orderbook: Callable[[dict], Any] | None = None,
        on_error: Callable[[Exception], Any] | None = None,
        buffer_size: int = 1,
    ) -> None:
        """
        Поток стакана (market depth = полная книга заявок).

        То же, что stream_quotes(level='market_depth'), но с buffer_size=1
        для минимальной задержки.

        **Блокирующий вызов**. Автореконнект.
        """
        await self._stream_feed(
            symbol_ids=symbol_ids,
            params={"level": "market_depth"},
            stream_name="orderbook",
            on_data=on_orderbook,
            on_error=on_error,
            buffer_size=buffer_size,
        )

    async def stream_best_quotes(
        self,
        symbol_ids: str | list[str],
        on_quote: Callable[[dict], Any] | None = None,
        on_error: Callable[[Exception], Any] | None = None,
        buffer_size: int = 100,
    ) -> None:
        """
        Поток лучших цен (top of book).

        То же, что stream_quotes(level='best_price').

        **Блокирующий вызов**. Автореконнект.
        """
        await self._stream_feed(
            symbol_ids=symbol_ids,
            params={"level": "best_price"},
            stream_name="best_quotes",
            on_data=on_quote,
            on_error=on_error,
            buffer_size=buffer_size,
        )

    async def stream_multiple(
        self,
        symbol_ids: str | list[str],
        on_quote: Callable[[dict], Any] | None = None,
        on_error: Callable[[Exception], Any] | None = None,
        buffer_size: int = 100,
    ) -> None:
        """
        Поток best_price для нескольких инструментов через один стрим.
        Просто псевдоним stream_best_quotes.
        """
        await self.stream_best_quotes(
            symbol_ids=symbol_ids,
            on_quote=on_quote,
            on_error=on_error,
            buffer_size=buffer_size,
        )

    # ------------------------------------------------------------------
    # TRADE API — Orders
    # ------------------------------------------------------------------

    async def get_active_orders(
        self,
        limit: int = 100,
        account_id: str | None = None,
        symbol_id: str | None = None,
    ) -> list | bool:
        """
        GET /trade/{version}/orders/active
        """
        params: dict[str, str] = {"limit": str(limit)}
        if account_id:
            params["accountId"] = account_id
        if symbol_id:
            params["symbolId"] = symbol_id

        url = f"{EXANTE_TRADE_API}/{EXANTE_API_VERSION}/orders/active"
        res = await self.send_request("GET", url, params=params)
        if not isinstance(res, list):
            logger.error("EXANTE active orders: %s", res)
            return False
        return res

    async def get_orders(
        self,
        limit: int = 100,
        from_date: str | None = None,
        to_date: str | None = None,
        account_id: str | None = None,
    ) -> list | bool:
        """
        GET /trade/{version}/orders
        """
        params: dict[str, str] = {"limit": str(limit)}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        if account_id:
            params["accountId"] = account_id

        url = f"{EXANTE_TRADE_API}/{EXANTE_API_VERSION}/orders"
        res = await self.send_request("GET", url, params=params)
        if not isinstance(res, list):
            logger.error("EXANTE orders: %s", res)
            return False
        return res

    async def get_order(self, order_id: str) -> dict | bool:
        """
        GET /trade/{version}/orders/{orderId}
        """
        url = f"{EXANTE_TRADE_API}/{EXANTE_API_VERSION}/orders/{order_id}"
        res = await self.send_request("GET", url)
        if not isinstance(res, dict):
            logger.error("EXANTE get_order: %s", res)
            return False
        return res

    async def place_order(
        self,
        account_id: str,
        symbol_id: str,
        side: str,
        quantity: str,
        order_type: str,
        limit_price: str | None = None,
        stop_price: str | None = None,
        duration: str = "day",
        client_tag: str | None = None,
    ) -> list | bool:
        """
        POST /trade/{version}/orders

        Параметры
        ---------
        account_id : str
        symbol_id : str
        side : str
            "buy" или "sell".
        quantity : str
            Количество в виде строки (например "6").
        order_type : str
            "market", "limit", "stop", "stop_limit", "twap", "trailing_stop", "iceberg".
        limit_price : str | None
        stop_price : str | None
        duration : str
            "day", "fill_or_kill", "immediate_or_cancel", "good_till_cancel",
            "good_till_time", "at_the_opening", "at_the_close".
        client_tag : str | None
            Произвольная метка заявки.

        Returns
        -------
        list[dict] | False
        """
        body: dict[str, str] = {
            "accountId": account_id,
            "symbolId": symbol_id,
            "side": side,
            "quantity": quantity,
            "orderType": order_type,
            "duration": duration,
        }
        if limit_price:
            body["limitPrice"] = limit_price
        if stop_price:
            body["stopPrice"] = stop_price
        if client_tag:
            body["clientTag"] = client_tag

        url = f"{EXANTE_TRADE_API}/{EXANTE_API_VERSION}/orders"
        res = await self.send_request("POST", url, body=body)
        if not isinstance(res, list):
            logger.error("EXANTE place_order: %s", res)
            return False
        return res

    async def cancel_order(self, order_id: str) -> dict | bool:
        """
        POST /trade/{version}/orders/{orderId}
        action: "cancel"
        """
        url = f"{EXANTE_TRADE_API}/{EXANTE_API_VERSION}/orders/{order_id}"
        body = {"action": "cancel"}
        return await self.send_request("POST", url, body=body)

    async def modify_order(
        self,
        order_id: str,
        quantity: str | None = None,
        limit_price: str | None = None,
        stop_price: str | None = None,
        price_distance: str | None = None,
    ) -> dict | bool:
        """
        POST /trade/{version}/orders/{orderId}
        action: "replace"
        """
        url = f"{EXANTE_TRADE_API}/{EXANTE_API_VERSION}/orders/{order_id}"
        params: dict[str, str] = {}
        if quantity is not None:
            params["quantity"] = quantity
        if limit_price is not None:
            params["limitPrice"] = limit_price
        if stop_price is not None:
            params["stopPrice"] = stop_price
        if price_distance is not None:
            params["priceDistance"] = price_distance

        body = {"action": "replace", "parameters": params}
        return await self.send_request("POST", url, body=body)

    # ------------------------------------------------------------------
    # TRADE API — Transactions
    # ------------------------------------------------------------------

    async def get_transactions(
        self,
        account_id: str | None = None,
        symbol_id: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list | bool:
        """
        GET /md/{version}/transactions
        """
        params: dict[str, str] = {"limit": str(limit), "offset": str(offset)}
        if account_id:
            params["accountId"] = account_id
        if symbol_id:
            params["symbolId"] = symbol_id
        if from_date:
            params["fromDate"] = from_date
        if to_date:
            params["toDate"] = to_date

        url = f"{EXANTE_MD_API}/{EXANTE_API_VERSION}/transactions"
        res = await self.send_request("GET", url, params=params)
        if not isinstance(res, list):
            logger.error("EXANTE transactions: %s", res)
            return False
        return res

    # ------------------------------------------------------------------
    # TRADE API — Streams (order updates, trades)
    # ------------------------------------------------------------------

    async def _stream_sse(
        self,
        url: str,
        on_data: Callable[[dict], Any] | None,
        on_error: Callable[[Exception], Any] | None,
        stream_name: str,
    ) -> None:
        """
        Универсальный SSE-стрим с корректным управлением сессией.

        Параметры
        ---------
        url : str
            Полный URL эндпоинта.
        on_data : callable
            Обработчик каждого JSON-объекта.
        on_error : callable
            Обработчик ошибок.
        stream_name : str
            Имя стрима для логов.
        """
        if on_data is None:
            on_data = lambda d: logger.info(
                "EXANTE %s: %s", stream_name, d
            )

        await self.ensure_token()
        headers = {
            "Accept": "application/x-json-stream",
            **self._build_auth_headers(),
        }

        stream_session: aiohttp.ClientSession | None = None

        while True:
            try:
                if stream_session is not None and not stream_session.closed:
                    await stream_session.close()
                    stream_session = None

                timeout = aiohttp.ClientTimeout(total=None)
                tcp_connector = aiohttp.TCPConnector(
                    ssl=self._ssl_verify, force_close=True
                )
                stream_session = aiohttp.ClientSession(
                    timeout=timeout, connector=tcp_connector
                )

                async with stream_session.get(
                    url, headers=headers,
                ) as response:
                        response.raise_for_status()
                        logger.info("EXANTE %s stream connected", stream_name)

                        async for line_bytes in response.content:
                            raw = line_bytes.decode("utf-8").strip()
                            if not raw:
                                continue
                            try:
                                data = json.loads(raw)
                            except json.JSONDecodeError:
                                continue
                            await self._call_handler(on_data, data)

            except asyncio.CancelledError:
                logger.info("EXANTE %s stream cancelled", stream_name)
                if stream_session and not stream_session.closed:
                    await stream_session.close()
                stream_session = None
                return

            except Exception as e:
                logger.error("EXANTE %s stream error: %s", stream_name, e)
                if on_error:
                    await self._call_handler(on_error, e)
                if stream_session and not stream_session.closed:
                    await stream_session.close()
                stream_session = None
                await asyncio.sleep(5)

    async def stream_order_updates(
        self,
        on_update: Callable[[dict], Any] | None = None,
        on_error: Callable[[Exception], Any] | None = None,
    ) -> None:
        """
        GET /trade/{version}/stream/orders
        Accept: application/x-json-stream

        Поток обновлений по заявкам.
        """
        url = f"{EXANTE_TRADE_API}/{EXANTE_API_VERSION}/stream/orders"
        await self._stream_sse(url, on_update, on_error, "order")

    async def stream_trade_updates(
        self,
        on_trade: Callable[[dict], Any] | None = None,
        on_error: Callable[[Exception], Any] | None = None,
    ) -> None:
        """
        GET /trade/{version}/stream/trades
        Accept: application/x-json-stream

        Поток сделок по счету.
        """
        url = f"{EXANTE_TRADE_API}/{EXANTE_API_VERSION}/stream/trades"
        await self._stream_sse(url, on_trade, on_error, "trade updates")


# ---------------------------------------------------------------------------
# Тест (запуск: python connectors/exante_connector.py)
# ---------------------------------------------------------------------------

async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    connector = EXANTEConnector()

    # # 1. Аккаунты
    # print("\n=== Аккаунты ===")
    # accounts = await connector.get_accounts()
    # if accounts:
    #     for acc in accounts:
    #         print(f"  accountId={acc.get('accountId')}  status={acc.get('status')}")
    # else:
    #     print("  не удалось получить аккаунты (401 или ошибка)")

    # # 2. Последняя котировка
    # print("\n=== Последняя котировка AAPL.NASDAQ ===")
    # last = await connector.get_last_quote("AAPL.NASDAQ")
    # if last:
    #     print(f"  {last}")
    # else:
    #     print("  нет данных")

    # # 3. Исторические тики (сделки)
    # print("\n=== Исторические тики AAPL.NASDAQ (trades, 5 шт) ===")
    # ticks = await connector.get_ticks("AAPL.NASDAQ", tick_type="trades", size=5)
    # if ticks:
    #     for t in ticks:
    #         print(f"  {t}")
    # else:
    #     print("  нет данных")

    # # 4. OHLC
    # print("\n=== OHLC AAPL.NASDAQ (H1, 3 свечи) ===")
    # ohlc = await connector.get_ohlc("AAPL.NASDAQ", duration=3600, size=3)
    # if ohlc:
    #     for c in ohlc:
    #         print(f"  {c}")
    # else:
    #     print("  нет данных")

    # 5. Информация о символе
    print("\n=== Symbol AAPL.NASDAQ ===")
    sym = await connector.get_symbol("AAPL.NASDAQ")
    if sym:
        print(
            f"  name={sym.get('name')}  ticker={sym.get('ticker')}  "
            f"type={sym.get('symbolType') or sym.get('type')}  "
            f"currency={sym.get('currency')}"
        )
    else:
        print("  не найден")

    # 6. Список бирж и инструментов биржи
    print("\n=== Exchanges ===")
    exchanges = await connector.get_exchanges()
    if isinstance(exchanges, list):
        print(f"  Всего бирж: {len(exchanges)}")
        for exc in exchanges[:10]:
            print(f"  {exc.get('id','?'):12s}  {exc.get('name','')}")
        if exchanges:
            exc_id = exchanges[0].get("id", "")
            print(f"\n=== Инструменты биржи {exc_id} ===")
            exc_syms = await connector.get_exchange_symbols(exc_id)
            if isinstance(exc_syms, list):
                print(f"  Найдено: {len(exc_syms)}")
                for es in exc_syms[:5]:
                    print(
                        f"  symbolId={es.get('symbolId','?'):20s}  "
                        f"ticker={es.get('ticker','?'):10s}  "
                        f"type={es.get('symbolType','?')}"
                    )
            else:
                print(f"  ошибка: {exc_syms}")
    else:
        print(f"  ошибка: {exchanges}")

    # 7. Группы
    print("\n=== Groups ===")
    groups = await connector.get_groups()
    if isinstance(groups, list):
        print(f"  Всего групп: {len(groups)}")
        for grp in groups[:10]:
            print(f"  {grp.get('group','?'):30s}  exchange={grp.get('exchange','?')}  "
                  f"name={grp.get('name','')}")

    # # 6. Активные заявки
    # print("\n=== Активные заявки ===")
    # orders = await connector.get_active_orders(limit=5)
    # if orders:
    #     for o in orders:
    #         print(f"  {o.get('id')}  {o.get('orderParameters', {}).get('symbolId')}  "
    #               f"status={o.get('orderState', {}).get('status')}")
    # else:
    #     print("  нет активных заявок или ошибка")

    # 7. Подписка на поток стакана (market_depth) — 10 сообщений
    print("\n=== Поток стакана AAPL.NASDAQ (market_depth, 10 сообщений) ===")

    msg_count = 0
    _stream_done = False

    async def on_orderbook(q):
        nonlocal msg_count, _stream_done
        msg_count += 1
        sym = q.get("symbolId", "?")
        ts = q.get("timestamp", 0)
        bids = q.get("bid", [])
        asks = q.get("ask", [])

        print(f"\n  [{msg_count}] {sym} @ {ts}")
        print(f"  Bids ({len(bids)}):")
        for b in bids[:10]:
            print(f"    {b.get('price','?'):>10s}  x {b.get('size','?')}")
        print(f"  Asks ({len(asks)}):")
        for a in asks[:10]:
            print(f"    {a.get('price','?'):>10s}  x {a.get('size','?')}")

        if msg_count >= 10 and not _stream_done:
            _stream_done = True
            raise asyncio.CancelledError("got 10 messages")

    try:
        await asyncio.wait_for(
            connector.stream_orderbook(
                symbol_ids="AAPL.NASDAQ",
                on_orderbook=on_orderbook,
                buffer_size=1,
            ),
            timeout=120.0,
        )
    except (asyncio.CancelledError, asyncio.TimeoutError) as e:
        print(f"\n  ➜ Поток остановлен: {e}")
    finally:
        # Явно закрыть сессию — это предотвращает ошибку __del__
        await connector.close()


if __name__ == "__main__":
    asyncio.run(main())
