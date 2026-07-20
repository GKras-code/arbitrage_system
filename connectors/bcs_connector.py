"""
Коннектор для БКС Торгового API (BCS Express).

Документация: https://trade-api.bcs.ru/

Стиль — async/aiohttp (единый Binance-подобный dispatcher):
- send_request с retry-логикой
- _prepare_request для сборки URL/headers/body
- константы HTTP из .env
- методы возвращают данные или False при ошибке
"""

import os
import sys
import time
import asyncio
import uuid
import json
import ssl
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import aiohttp
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
# Константы HTTP (из .env)
# ---------------------------------------------------------------------------

HTTP_TIMEOUT_TOTAL = float(os.getenv("HTTP_TIMEOUT_TOTAL", "12"))
HTTP_TIMEOUT_CONNECT = float(os.getenv("HTTP_TIMEOUT_CONNECT", "5"))
HTTP_TIMEOUT_SOCK_READ = float(os.getenv("HTTP_TIMEOUT_SOCK_READ", "18"))
HTTP_RETRIES = int(os.getenv("HTTP_RETRIES", "2"))
HTTP_RETRY_BACKOFF = float(os.getenv("HTTP_RETRY_BACKOFF", "0.7"))

# ---------------------------------------------------------------------------
# Константы BCS API
# ---------------------------------------------------------------------------

BCS_REFRESH_TOKEN = os.getenv("BCS_REFRESH_TOKEN", "")
BCS_TOKEN_CACHE_PATH = os.getenv("BCS_TOKEN_CACHE_PATH", "")
BCS_SSL_VERIFY = os.getenv("BCS_SSL_VERIFY", "true").strip().lower() != "false"

# ---------------------------------------------------------------------------
# SSL context (единый для всех запросов)
# ---------------------------------------------------------------------------

_SSL_CONTEXT: ssl.SSLContext | bool = True
if not BCS_SSL_VERIFY:
    import ssl as _ssl_mod
    _SSL_CONTEXT = False
    logger.warning("BCS: проверка SSL отключена (BCS_SSL_VERIFY=false)")
else:
    try:
        _ctx = ssl.create_default_context()
        _SSL_CONTEXT = _ctx
    except Exception:
        _SSL_CONTEXT = False
        logger.warning("BCS: не удалось создать SSL context, проверка отключена")

AUTH_URL = (
    "https://be.broker.ru/trade-api-keycloak/"
    "realms/tradeapi/protocol/openid-connect/token"
)
PORTFOLIO_URL = "https://be.broker.ru/trade-api-bff-portfolio/api/v1/portfolio"
ORDERS_URL = "https://be.broker.ru/trade-api-bff-operations/api/v1/orders"
ORDERS_CANCEL_URL = f"{ORDERS_URL}/cancel"
ORDERS_EDIT_URL = f"{ORDERS_URL}/edit"
ORDERS_SEARCH_URL = (
    "https://be.broker.ru/trade-api-bff-order-details/api/v1/orders/search"
)
WS_MARKET_DATA_URL = (
    "wss://ws.broker.ru/trade-api-market-data-connector/"
    "api/v1/market-data/ws"
)

# Типы client_id
CLIENT_ID_READ = "trade-api-read"
CLIENT_ID_WRITE = "trade-api-write"

# Типы данных WebSocket
WS_DATA_TYPE_ORDER_BOOK = 0   # Стакан
WS_DATA_TYPE_CANDLES = 1      # Свечи
WS_DATA_TYPE_TRADES = 2       # Обезличенные сделки
WS_DATA_TYPE_QUOTES = 3       # Котировки

TIMEFRAMES = ("M1", "M5", "M15", "M30", "H1", "H4", "D", "W", "MN")

# Направление заявки
SIDE_BUY = "1"
SIDE_SELL = "2"

# Тип заявки
ORDER_TYPE_MARKET = "1"
ORDER_TYPE_LIMIT = "2"

# Тип идентификатора заявки
ORDER_ID_TYPE_CLIENT = "1"
ORDER_ID_TYPE_EXCHANGE = "2"

# Статусы заявок
ORDER_STATUS_CANCELLED = 1
ORDER_STATUS_FILLED = 2
ORDER_STATUS_ACTIVE = 3


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _i(x):
    """Безопасное приведение к int."""
    try:
        return int(x)
    except Exception:
        return 0


def _f(x, default=0.0):
    """Безопасное приведение к float."""
    try:
        return float(x)
    except Exception:
        return default


def _generate_uuid() -> str:
    """Генерирует UUID для clientOrderId."""
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# BCSConnector
# ---------------------------------------------------------------------------

class BCSConnector:
    """
    Коннектор к БКС Торговому API.

    Использование
    -------------
    connector = BCSConnector()
    await connector.ensure_token()
    portfolio = await connector.get_portfolio()
    orders = await connector.get_orders()
    """

    def __init__(
        self,
        refresh_token: str | None = None,
        client_id: str = CLIENT_ID_READ,
        token_cache_path: str | None = None,
    ):
        """
        Параметры
        ---------
        refresh_token : str | None
            Refresh-токен из веб-версии БКС Мир инвестиций.
            Если None — берётся из .env (BCS_REFRESH_TOKEN).
        client_id : str
            trade-api-read (только чтение) или trade-api-write (чтение + торговля).
        token_cache_path : str | None
            Путь к файлу кэша токена между запусками.
        """
        self._refresh_token = refresh_token or BCS_REFRESH_TOKEN
        if not self._refresh_token:
            raise ValueError(
                "Не задан BCS_REFRESH_TOKEN. Передайте refresh_token "
                "или укажите в .env."
            )

        self._client_id = client_id
        self._token_cache_path = token_cache_path or BCS_TOKEN_CACHE_PATH or None

        # HTTP session (экземплярная, не классовая!)
        self._session_pool: aiohttp.ClientSession | None = None

        # Текущий access-токен
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

        # Пробуем загрузить кэш
        self._load_cached_token()

    # ------------------------------------------------------------------
    # Управление токеном
    # ------------------------------------------------------------------

    def _load_cached_token(self) -> None:
        """Загружает токен из файла кэша."""
        path = self._token_cache_path
        if not path:
            return
        try:
            p = Path(path)
            if p.exists():
                data = p.read_text(encoding="utf-8").strip().split("|")
                if len(data) == 2:
                    self._access_token = data[0]
                    self._token_expires_at = float(data[1])
                    logger.info("Загружен кэшированный BCS-токен")
        except Exception as e:
            logger.warning("Не удалось загрузить кэш токена: %s", e)

    def _save_cached_token(self) -> None:
        """Сохраняет токен в файл кэша."""
        path = self._token_cache_path
        if not path:
            return
        try:
            Path(path).write_text(
                f"{self._access_token}|{self._token_expires_at}",
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning("Не удалось сохранить кэш токена: %s", e)

    async def ensure_token(self) -> str:
        """
        Гарантирует наличие действующего access-токена.
        При необходимости обновляет его.

        Returns
        -------
        str
            Актуальный access-токен.
        """
        if (
            self._access_token is None
            or time.time() >= self._token_expires_at - 60
        ):
            await self._refresh_access_token()
        return self._access_token  # type: ignore[return-value]

    async def _refresh_access_token(self) -> None:
        """
        Обменивает refresh-токен на access-токен.

        POST .../token  (application/x-www-form-urlencoded)
        """
        logger.info("Запрашиваю новый BCS access-токен...")

        payload = {
            "client_id": self._client_id,
            "refresh_token": self._refresh_token,
            "grant_type": "refresh_token",
        }

        async with self._create_session().post(
            AUTH_URL,
            data=payload,
            headers={"Accept": "application/json"},
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()

        self._access_token = data["access_token"]
        expires_in = _i(data.get("expires_in", 86400)) or 86400
        self._token_expires_at = time.time() + expires_in

        new_refresh = data.get("refresh_token")
        if new_refresh:
            self._refresh_token = new_refresh

        self._save_cached_token()
        logger.info("BCS access-токен получен (истекает через %d сек)", expires_in)

    async def set_client_id(self, client_id: str) -> None:
        """Меняет client_id и принудительно перевыпускает токен."""
        self._client_id = client_id
        self._token_expires_at = 0.0
        await self.ensure_token()

    # ------------------------------------------------------------------
    # HTTP-диспетчер
    # ------------------------------------------------------------------

    @staticmethod
    async def _call_handler(handler, *args, **kwargs):
        """Вызывает handler независимо от того, sync он или async."""
        if handler is None:
            return
        result = handler(*args, **kwargs)
        if result is not None and hasattr(result, "__await__"):
            await result

    def _create_session(self) -> aiohttp.ClientSession:
        """
        Создаёт aiohttp.ClientSession с едиными таймаутами и SSL-настройкой.

        SSL: использует глобальный _SSL_CONTEXT (True = системный,
        False = без проверки, ssl.SSLContext = кастомный).
        """
        if self._session_pool is None or self._session_pool.closed:
            timeout = aiohttp.ClientTimeout(
                total=HTTP_TIMEOUT_TOTAL,
                connect=HTTP_TIMEOUT_CONNECT,
                sock_read=HTTP_TIMEOUT_SOCK_READ,
            )
            connector = aiohttp.TCPConnector(ssl=_SSL_CONTEXT)
            self._session_pool = aiohttp.ClientSession(
                timeout=timeout, connector=connector
            )
        return self._session_pool

    async def close(self) -> None:
        """Закрывает пул сессий."""
        pool = self._session_pool
        self._session_pool = None
        if pool and not pool.closed:
            await pool.close()

    async def _prepare_request(
        self,
        url: str,
        param: dict | None = None,
        body: dict | None = None,
    ) -> tuple[str, dict, dict | None]:
        """
        Собирает URL, заголовки и тело запроса.

        Returns
        -------
        (url, headers, body)
        """
        token = await self.ensure_token()
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        }
        if param:
            qs = "&".join(f"{k}={v}" for k, v in param.items() if v is not None)
            if qs:
                url = f"{url}?{qs}"
        return url, headers, body

    async def send_request(
        self,
        type_request: str,
        url: str,
        param: dict | None = None,
        body: dict | None = None,
    ) -> dict | list | bool:
        """
        Единый диспетчер HTTP-запросов с retry-логикой.

        Параметры
        ---------
        type_request : str
            GET / POST / DELETE.
        url : str
            Полный URL эндпоинта.
        param : dict | None
            Query-параметры.
        body : dict | None
            JSON-тело запроса.

        Returns
        -------
        Ответ API (dict/list) или False при ошибке.
        """
        url_final, headers, body_final = await self._prepare_request(
            url, param, body
        )

        for attempt in range(HTTP_RETRIES + 1):
            try:
                session = self._create_session()
                async with session.request(
                    type_request, url_final, headers=headers, json=body_final
                ) as response:
                    response.raise_for_status()
                    try:
                        data = await response.json()
                    except aiohttp.ContentTypeError:
                        text = await response.text()
                        return {"code": response.status, "msg": text[:200]}
                    return data

            except aiohttp.ClientResponseError as e:
                if 400 <= e.status < 500:
                    logger.error("BCS HTTP %d: %s", e.status, e.message)
                    return {"code": e.status, "msg": e.message}
                if attempt < HTTP_RETRIES:
                    await asyncio.sleep(HTTP_RETRY_BACKOFF * (2**attempt))
                    continue
                logger.error("BCS HTTP %d после %d попыток", e.status, HTTP_RETRIES)
                return {"code": e.status, "msg": e.message}

            except (asyncio.TimeoutError, aiohttp.ClientError) as e:
                if attempt < HTTP_RETRIES:
                    await asyncio.sleep(HTTP_RETRY_BACKOFF * (2**attempt))
                    continue
                logger.error("BCS HTTP error: %s", e)
                return False
            except Exception as e:
                logger.error("BCS unexpected error: %s", e)
                return False

        return False

    async def _request_with_retry(
        self,
        type_request: str,
        url: str,
        param: dict | None = None,
        body: dict | None = None,
        *,
        retries: int = 3,
        delay_s: float = 5.0,
        validate=None,
    ) -> dict | list | bool:
        """Повторяет запрос, пока validate не вернёт True."""
        last = None
        for attempt in range(1, retries + 1):
            last = await self.send_request(type_request, url, param, body)
            if validate is None or validate(last):
                return last
            if attempt < retries:
                await asyncio.sleep(delay_s)
        return last

    # -------------------- ПОРТФЕЛЬ --------------------

    async def get_portfolio(self) -> list | bool:
        """
        Получение позиций портфеля.

        GET /api/v1/portfolio

        Returns
        -------
        list[dict] | False
            [{"ticker": "SBER", "quantity": 10, "currentPrice": 250.0, ...}]
        """
        res = await self.send_request("GET", PORTFOLIO_URL)
        if not isinstance(res, list):
            logger.error("BCS portfolio: %s", res)
            return False
        return res

    # -------------------- ЗАЯВКИ --------------------

    async def get_orders(
        self,
        page: int = 0,
        size: int = 50,
        sort: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        side: str | None = None,
        order_statuses: list[int] | None = None,
        order_types: list[int] | None = None,
        tickers: list[str] | None = None,
        class_codes: list[str] | None = None,
    ) -> dict | bool:
        """
        Список заявок с фильтрацией.

        POST /api/v1/orders/search

        Returns
        -------
        {"records": [...], "totalRecords": int, "totalPages": int} | False
        """
        params: dict[str, object] = {"page": page, "size": size}
        if sort:
            params["sort"] = sort

        body: dict[str, object] = {}
        if start_date:
            body["startDateTime"] = start_date.isoformat()
        if end_date:
            body["endDateTime"] = end_date.isoformat()
        if side:
            body["side"] = int(side)
        if order_statuses:
            body["orderStatus"] = order_statuses
        if order_types:
            body["orderTypes"] = order_types
        if tickers:
            body["tickers"] = tickers
        if class_codes:
            body["classCodes"] = class_codes

        res = await self.send_request("POST", ORDERS_SEARCH_URL, param=params, body=body)
        if not isinstance(res, dict) or "records" not in res:
            logger.error("BCS get_orders: %s", res)
            return False
        return res

    async def create_order(
        self,
        ticker: str,
        class_code: str,
        side: str,
        order_type: str,
        quantity: int,
        price: float | None = None,
        client_order_id: str | None = None,
    ) -> dict | bool:
        """
        Создать торговую заявку.

        POST /api/v1/orders

        Параметры
        ---------
        ticker : str
            Тикер (например "SBER").
        class_code : str
            Код класса бумаги (например "TQBR").
        side : str
            '1' — покупка, '2' — продажа.
        order_type : str
            '1' — рыночная, '2' — лимитная.
        quantity : int
            Количество (>= 1).
        price : float | None
            Цена (для лимитной заявки, >= 1e-7).
        client_order_id : str | None
            UUID заявки (генерируется автоматически).

        Returns
        -------
        {"clientOrderId": "...", "status": "..."} | False
        """
        body: dict[str, object] = {
            "clientOrderId": client_order_id or _generate_uuid(),
            "side": side,
            "orderType": order_type,
            "orderQuantity": quantity,
            "ticker": ticker,
            "classCode": class_code,
        }
        if price is not None:
            body["price"] = price

        res = await self.send_request("POST", ORDERS_URL, body=body)
        if not isinstance(res, dict) or "clientOrderId" not in res:
            logger.error("BCS create_order: %s", res)
            return False
        return res

    async def cancel_order(
        self,
        order_id: str,
        order_id_type: str = ORDER_ID_TYPE_CLIENT,
        client_order_id: str | None = None,
    ) -> dict | bool:
        """
        Отменить заявку.

        POST /api/v1/orders/cancel

        Параметры
        ---------
        order_id : str
            ID заявки (UUID клиента или биржевой).
        order_id_type : str
            '1' — UUID клиента, '2' — биржевой ID.
        client_order_id : str | None
            UUID запроса (генерируется автоматически).

        Returns
        -------
        {"clientOrderId": "...", "status": "..."} | False
        """
        body = {
            "orderIdType": order_id_type,
            "orderId": order_id,
            "clientOrderId": client_order_id or _generate_uuid(),
        }
        res = await self.send_request("POST", ORDERS_CANCEL_URL, body=body)
        if not isinstance(res, dict) or "clientOrderId" not in res:
            logger.error("BCS cancel_order: %s", res)
            return False
        return res

    async def edit_order(
        self,
        order_id: str,
        quantity: int,
        order_id_type: str = ORDER_ID_TYPE_CLIENT,
        order_type: str | None = None,
        price: float | None = None,
        client_order_id: str | None = None,
    ) -> dict | bool:
        """
        Изменить заявку.

        POST /api/v1/orders/edit

        Параметры
        ---------
        order_id : str
            ID заявки.
        quantity : int
            Новое количество (>= 1).
        order_id_type : str
            '1' — UUID клиента, '2' — биржевой ID.
        order_type : str | None
            '1' — рыночная, '2' — лимитная.
        price : float | None
            Новая цена (>= 1e-7).
        client_order_id : str | None
            UUID запроса.

        Returns
        -------
        {"clientOrderId": "...", "status": "..."} | False
        """
        body: dict[str, object] = {
            "orderIdType": order_id_type,
            "orderId": order_id,
            "clientOrderId": client_order_id or _generate_uuid(),
            "orderQuantity": quantity,
        }
        if order_type is not None:
            body["orderType"] = order_type
        if price is not None:
            body["price"] = price

        res = await self.send_request("POST", ORDERS_EDIT_URL, body=body)
        if not isinstance(res, dict) or "clientOrderId" not in res:
            logger.error("BCS edit_order: %s", res)
            return False
        return res

    # -------------------- WEBSOCKET: рыночные данные (aiohttp async) --------------------

    def build_subscription_message(
        self,
        data_type: int,
        instruments: list[dict[str, str]],
        subscribe: bool = True,
        depth: int = 20,
        time_frame: str | None = None,
    ) -> dict:
        """
        Формирует JSON-сообщение подписки/отписки WebSocket.

        Параметры
        ---------
        data_type : int
            0=стакан, 1=свечи, 2=сделки, 3=котировки.
        instruments : list[dict]
            [{"ticker":"SBER","classCode":"TQBR"}, ...].
        subscribe : bool
            True=подписка, False=отписка.
        depth : int
            Глубина стакана (1–20), только для data_type=0.
        time_frame : str | None
            Таймфрейм (M1...MN), только для data_type=1.

        Returns
        -------
        dict
        """
        msg: dict[str, object] = {
            "subscribeType": 0 if subscribe else 1,
            "dataType": data_type,
            "instruments": instruments,
        }
        if data_type == WS_DATA_TYPE_ORDER_BOOK:
            msg["depth"] = depth
        elif data_type == WS_DATA_TYPE_CANDLES and time_frame:
            msg["timeFrame"] = time_frame

        return msg

    async def _ws_stream(
        self,
        data_type: int,
        instruments: list[dict[str, str]],
        on_message: Callable[[dict], Any] | None = None,
        depth: int = 20,
        time_frame: str | None = None,
        stream_name: str = "WS",
    ) -> None:
        """
        Универсальный async WebSocket-стрим на aiohttp ws_connect.

        **Блокирующий вызов** — работает до CancelledError.
        Автореконнект с паузой 5с.
        """
        if on_message is None:
            on_message = lambda msg: logger.info("BCS %s: %s", stream_name, msg)

        sub_msg = self.build_subscription_message(
            data_type=data_type,
            instruments=instruments,
            subscribe=True,
            depth=depth,
            time_frame=time_frame,
        )

        while True:
            try:
                token = await self.ensure_token()
                headers = {"Authorization": f"Bearer {token}"}

                async with self._create_session().ws_connect(
                    WS_MARKET_DATA_URL,
                    headers=headers,
                    heartbeat=30.0,
                ) as ws:
                    logger.info("BCS %s WS connected", stream_name)
                    await ws.send_json(sub_msg)

                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                payload = json.loads(msg.data)
                            except json.JSONDecodeError:
                                logger.warning(
                                    "BCS %s non-JSON: %s", stream_name, msg.data
                                )
                                continue
                            await self._call_handler(on_message, payload)

                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            logger.error(
                                "BCS %s WS error: %s", stream_name, ws.exception()
                            )
                            break

                        elif msg.type == aiohttp.WSMsgType.CLOSED:
                            logger.info("BCS %s WS closed", stream_name)
                            break

            except asyncio.CancelledError:
                logger.info("BCS %s WS cancelled", stream_name)
                return

            except Exception as e:
                logger.error("BCS %s WS error: %s", stream_name, e)
                await asyncio.sleep(5)

    async def stream_orderbook(
        self,
        instruments: list[dict[str, str]],
        on_orderbook: Callable[[dict], Any] | None = None,
        depth: int = 20,
    ) -> None:
        """
        Подписка на стаканы (order book) через WebSocket.

        **Блокирующий вызов** — работает до CancelledError.
        """
        await self._ws_stream(
            data_type=WS_DATA_TYPE_ORDER_BOOK,
            instruments=instruments,
            on_message=on_orderbook,
            depth=depth,
            stream_name="orderbook",
        )

    async def stream_candles(
        self,
        instruments: list[dict[str, str]],
        time_frame: str,
        on_candle: Callable[[dict], Any] | None = None,
    ) -> None:
        """
        Подписка на свечи через WebSocket.
        """
        await self._ws_stream(
            data_type=WS_DATA_TYPE_CANDLES,
            instruments=instruments,
            on_message=on_candle,
            time_frame=time_frame,
            stream_name="candles",
        )

    async def stream_trades(
        self,
        instruments: list[dict[str, str]],
        on_trade: Callable[[dict], Any] | None = None,
    ) -> None:
        """
        Подписка на обезличенные сделки через WebSocket.
        """
        await self._ws_stream(
            data_type=WS_DATA_TYPE_TRADES,
            instruments=instruments,
            on_message=on_trade,
            stream_name="trades",
        )

    async def stream_quotes(
        self,
        instruments: list[dict[str, str]],
        on_quote: Callable[[dict], Any] | None = None,
    ) -> None:
        """
        Подписка на котировки (best bid/ask) через WebSocket.
        """
        await self._ws_stream(
            data_type=WS_DATA_TYPE_QUOTES,
            instruments=instruments,
            on_message=on_quote,
            stream_name="quotes",
        )


# ---------------------------------------------------------------------------
# Тест (запуск: python connectors/bcs_connector.py)
# ---------------------------------------------------------------------------

async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    connector = BCSConnector()

    try:
        # Портфель
        print("\n=== Портфель ===")
        portfolio = await connector.get_portfolio()
        if portfolio:
            for pos in portfolio:
                print(
                    f"  {pos.get('ticker', '?'):8s}  "
                    f"qty={_f(pos.get('quantity')):>10.0f}  "
                    f"cur={_f(pos.get('currentPrice')):>10.2f}  "
                    f"P/L={_f(pos.get('unrealizedPL')):>10.2f}"
                )
        else:
            print("  ошибка получения портфеля")

        # Заявки
        print("\n=== Заявки ===")
        orders = await connector.get_orders(size=10)
        if orders:
            print(f"  Всего записей: {orders.get('totalRecords', 0)}")
            for rec in orders.get("records", []):
                print(f"  {rec}")
        else:
            print("  ошибка получения заявок")

        # Подписка на стакан — 10 сообщений
        print("\n=== Подписка на стакан SBER (10 сообщений) ===")

        ob_count = 0
        _ob_done = False

        async def on_orderbook(msg):
            nonlocal ob_count, _ob_done

            # Пропускаем сообщения-подтверждения подписки (нет данных стакана)
            if msg.get("responseType") == "OrderBookSuccess":
                return

            # Пропускаем сообщения с ошибками
            if "errors" in msg:
                logger.warning("BCS orderbook error: %s", msg["errors"])
                return

            ob_count += 1
            ticker = msg.get("ticker", "?")
            bids = msg.get("bids", [])
            asks = msg.get("asks", [])
            bid_volume = msg.get("bidVolume", "")
            ask_volume = msg.get("askVolume", "")
            print(f"\n  [{ob_count}] {ticker}  bidVol={bid_volume}  askVol={ask_volume}")
            print(f"  Bids ({len(bids)}):")
            for b in bids[:5]:
                print(f"    {b['price']:>10.2f}  x {b['quantity']}")
            print(f"  Asks ({len(asks)}):")
            for a in asks[:5]:
                print(f"    {a['price']:>10.2f}  x {a['quantity']}")
            if ob_count >= 10 and not _ob_done:
                _ob_done = True
                raise asyncio.CancelledError("got 10 messages")

        try:
            await asyncio.wait_for(
                connector.stream_orderbook(
                    instruments=[{"ticker": "SBER", "classCode": "TQBR"}],
                    on_orderbook=on_orderbook,
                    depth=20,
                ),
                timeout=120.0,
            )
        except (asyncio.CancelledError, asyncio.TimeoutError) as e:
            print(f"\n  ➜ Поток остановлен: {e}")

    finally:
        await connector.close()


if __name__ == "__main__":
    asyncio.run(main())
