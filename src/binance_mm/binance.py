import hashlib
import hmac
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import httpx

from .models import Book, Market

LIVE_REST = "https://fapi.binance.com"
DEMO_REST = "https://demo-fapi.binance.com"


class BinanceAPIError(RuntimeError):
    pass


@dataclass
class BinanceClient:
    environment: str = "paper"
    api_key: str | None = None
    api_secret: str | None = None
    timeout: float = 15.0

    def __post_init__(self) -> None:
        self.base_url = DEMO_REST if self.environment == "demo" else LIVE_REST
        self.http = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout)
        self._time_offset_ms = 0

    async def close(self) -> None:
        await self.http.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        signed: bool = False,
    ) -> Any:
        values = dict(params or {})
        headers: dict[str, str] = {}
        if signed:
            if not self.api_key or not self.api_secret:
                raise BinanceAPIError("BINANCE_API_KEY and BINANCE_API_SECRET are required")
            values.setdefault("timestamp", int(time.time() * 1000) + self._time_offset_ms)
            values.setdefault("recvWindow", 5000)
            query = urlencode(values)
            values["signature"] = hmac.new(
                self.api_secret.encode(), query.encode(), hashlib.sha256
            ).hexdigest()
            headers["X-MBX-APIKEY"] = self.api_key
        response = await self.http.request(method, path, params=values, headers=headers)
        if response.status_code >= 400:
            raise BinanceAPIError(f"{response.status_code} {response.text}")
        return response.json()

    async def sync_time(self) -> None:
        payload = await self._request("GET", "/fapi/v1/time")
        self._time_offset_ms = int(payload["serverTime"]) - int(time.time() * 1000)

    async def exchange_info(self) -> dict[str, Any]:
        return await self._request("GET", "/fapi/v1/exchangeInfo")

    async def ticker_24h(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/fapi/v1/ticker/24hr")

    async def book_tickers(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/fapi/v1/ticker/bookTicker")

    async def klines(self, symbol: str, interval: str = "5m", limit: int = 220) -> list[list[Any]]:
        return await self._request(
            "GET", "/fapi/v1/klines", {"symbol": symbol, "interval": interval, "limit": limit}
        )

    async def account(self) -> dict[str, Any]:
        return await self._request("GET", "/fapi/v3/account", signed=True)

    async def open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        params = {"symbol": symbol} if symbol else {}
        return await self._request("GET", "/fapi/v1/openOrders", params, signed=True)

    async def position_risk(self, symbol: str | None = None) -> list[dict[str, Any]]:
        params = {"symbol": symbol} if symbol else {}
        return await self._request("GET", "/fapi/v2/positionRisk", params, signed=True)

    async def position_mode(self) -> dict[str, Any]:
        return await self._request("GET", "/fapi/v1/positionSide/dual", signed=True)

    async def create_listen_key(self) -> str:
        if not self.api_key:
            raise BinanceAPIError("BINANCE_API_KEY is required")
        response = await self.http.post("/fapi/v1/listenKey", headers={"X-MBX-APIKEY": self.api_key})
        if response.status_code >= 400:
            raise BinanceAPIError(f"{response.status_code} {response.text}")
        return str(response.json()["listenKey"])

    async def keepalive_listen_key(self, listen_key: str) -> None:
        if not self.api_key:
            raise BinanceAPIError("BINANCE_API_KEY is required")
        response = await self.http.put(
            "/fapi/v1/listenKey",
            params={"listenKey": listen_key},
            headers={"X-MBX-APIKEY": self.api_key},
        )
        if response.status_code >= 400:
            raise BinanceAPIError(f"{response.status_code} {response.text}")

    async def close_listen_key(self, listen_key: str) -> None:
        if not self.api_key:
            raise BinanceAPIError("BINANCE_API_KEY is required")
        response = await self.http.delete(
            "/fapi/v1/listenKey",
            params={"listenKey": listen_key},
            headers={"X-MBX-APIKEY": self.api_key},
        )
        if response.status_code >= 400:
            raise BinanceAPIError(f"{response.status_code} {response.text}")

    async def set_leverage(self, symbol: str, leverage: int) -> dict[str, Any]:
        return await self._request(
            "POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": leverage}, signed=True
        )

    async def new_order(self, **params: Any) -> dict[str, Any]:
        return await self._request("POST", "/fapi/v1/order", params, signed=True)

    async def cancel_order(self, symbol: str, order_id: int) -> dict[str, Any]:
        return await self._request(
            "DELETE", "/fapi/v1/order", {"symbol": symbol, "orderId": order_id}, signed=True
        )

    async def query_order(self, symbol: str, order_id: int) -> dict[str, Any]:
        return await self._request(
            "GET", "/fapi/v1/order", {"symbol": symbol, "orderId": order_id}, signed=True
        )


def parse_markets(exchange_info: dict[str, Any], tickers: list[dict[str, Any]]) -> list[Market]:
    volumes = {ticker["symbol"]: Decimal(str(ticker.get("quoteVolume", "0"))) for ticker in tickers}
    markets: list[Market] = []
    for symbol in exchange_info.get("symbols", []):
        filters = {item["filterType"]: item for item in symbol.get("filters", [])}
        price_filter = filters.get("PRICE_FILTER", {})
        lot = filters.get("LOT_SIZE", {})
        min_notional = filters.get("MIN_NOTIONAL", {})
        markets.append(
            Market(
                symbol=symbol["symbol"],
                quote_asset=symbol["quoteAsset"],
                contract_type=symbol.get("contractType", ""),
                status=symbol.get("status", ""),
                tick_size=Decimal(str(price_filter.get("tickSize", "0"))),
                step_size=Decimal(str(lot.get("stepSize", "0"))),
                min_qty=Decimal(str(lot.get("minQty", "0"))),
                min_notional=Decimal(str(min_notional.get("notional", "0"))),
                quote_volume=volumes.get(symbol["symbol"], Decimal(0)),
            )
        )
    return markets


def parse_books(payload: list[dict[str, Any]]) -> dict[str, Book]:
    return {
        row["symbol"]: Book(Decimal(str(row["bidPrice"])), Decimal(str(row["askPrice"])))
        for row in payload
        if Decimal(str(row.get("bidPrice", "0"))) > 0
        and Decimal(str(row.get("askPrice", "0"))) > 0
    }
