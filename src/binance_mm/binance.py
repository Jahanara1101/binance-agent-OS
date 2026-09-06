from decimal import Decimal
from typing import Any

import httpx

from .models import Book, Market

PUBLIC_FUTURES_REST = "https://fapi.binance.com"
PUBLIC_SPOT_REST = "https://api.binance.com"


class BinanceMarketDataError(RuntimeError):
    pass


class PublicClient:
    def __init__(self, base_url: str, timeout: float = 15.0) -> None:
        self.http = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def close(self) -> None:
        await self.http.aclose()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = await self.http.get(path, params=params)
        if response.status_code >= 400:
            raise BinanceMarketDataError(f"{response.status_code} {response.text}")
        return response.json()


class BinanceMarketDataClient(PublicClient):
    """Public USD-M futures market data. Authenticated actions use Agent OS."""

    def __init__(self, timeout: float = 15.0) -> None:
        super().__init__(PUBLIC_FUTURES_REST, timeout)

    async def exchange_info(self) -> dict[str, Any]:
        return await self._get("/fapi/v1/exchangeInfo")

    async def ticker_24h(self) -> list[dict[str, Any]]:
        return await self._get("/fapi/v1/ticker/24hr")

    async def book_tickers(self) -> list[dict[str, Any]]:
        return await self._get("/fapi/v1/ticker/bookTicker")

    async def klines(self, symbol: str, interval: str = "5m", limit: int = 220) -> list[list[Any]]:
        return await self._get(
            "/fapi/v1/klines", {"symbol": symbol, "interval": interval, "limit": limit}
        )


class BinanceSpotMarketDataClient(PublicClient):
    """Public spot market data. Authenticated actions use Agent OS."""

    def __init__(self, timeout: float = 15.0) -> None:
        super().__init__(PUBLIC_SPOT_REST, timeout)

    async def exchange_info(self) -> dict[str, Any]:
        return await self._get("/api/v3/exchangeInfo")

    async def ticker_24h(self) -> list[dict[str, Any]]:
        return await self._get("/api/v3/ticker/24hr")

    async def book_tickers(self) -> list[dict[str, Any]]:
        return await self._get("/api/v3/ticker/bookTicker")

    async def klines(self, symbol: str, interval: str = "5m", limit: int = 220) -> list[list[Any]]:
        return await self._get(
            "/api/v3/klines", {"symbol": symbol, "interval": interval, "limit": limit}
        )


BinanceClient = BinanceMarketDataClient


def parse_markets(exchange_info: dict[str, Any], tickers: list[dict[str, Any]]) -> list[Market]:
    volumes = {ticker["symbol"]: Decimal(str(ticker.get("quoteVolume", "0"))) for ticker in tickers}
    markets: list[Market] = []
    for symbol in exchange_info.get("symbols", []):
        filters = {item["filterType"]: item for item in symbol.get("filters", [])}
        price_filter = filters.get("PRICE_FILTER", {})
        lot = filters.get("LOT_SIZE", {})
        min_notional = filters.get("MIN_NOTIONAL", filters.get("NOTIONAL", {}))
        contract_type = symbol.get("contractType", "SPOT")
        status = symbol.get("status", "")
        spot_allowed = symbol.get("isSpotTradingAllowed", True)
        markets.append(
            Market(
                symbol=symbol["symbol"],
                quote_asset=symbol["quoteAsset"],
                contract_type=contract_type,
                status=status if spot_allowed else "BREAK",
                tick_size=Decimal(str(price_filter.get("tickSize", "0"))),
                step_size=Decimal(str(lot.get("stepSize", "0"))),
                min_qty=Decimal(str(lot.get("minQty", "0"))),
                min_notional=Decimal(str(min_notional.get("minNotional", min_notional.get("notional", "0")))),
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
