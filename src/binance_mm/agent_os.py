import json
from collections.abc import Callable
from typing import Any

from .models import Order


def parse_mcp_payload(envelope: dict[str, Any]) -> Any:
    if not envelope.get("ok", True):
        raise RuntimeError(str(envelope.get("error", "Binance Agent OS call failed")))
    value: Any = envelope.get("structuredContent", envelope.get("result"))
    for _ in range(3):
        if isinstance(value, str):
            try:
                value = json.loads(value)
                continue
            except json.JSONDecodeError:
                return value
        if isinstance(value, dict) and set(value) == {"result"}:
            value = value["result"]
            continue
        break
    return value


class AgentOSExecutor:
    """Authenticated execution adapter backed exclusively by Binance Agent OS MCP."""

    def __init__(self, call_mcp: Callable[[str, dict[str, Any]], dict[str, Any]]) -> None:
        self.call_mcp = call_mcp

    def place(self, order: Order, client_order_id: str) -> dict[str, Any]:
        result = self.call_mcp(
            "futures_usds.newOrder",
            {
                "symbol": order.symbol,
                "side": order.side.value,
                "type": "LIMIT",
                "timeInForce": "GTX",
                "quantity": str(order.quantity),
                "price": str(order.price),
                "reduceOnly": order.reduce_only,
                "newClientOrderId": client_order_id,
            },
        )
        payload = parse_mcp_payload(result)
        if not isinstance(payload, dict):
            raise TypeError(f"Unexpected Agent OS order response: {payload!r}")
        return payload

    def cancel(self, symbol: str, order_id: int) -> dict[str, Any]:
        result = self.call_mcp(
            "futures_usds.cancelOrder", {"symbol": symbol, "orderId": order_id}
        )
        payload = parse_mcp_payload(result)
        if not isinstance(payload, dict):
            raise TypeError(f"Unexpected Agent OS cancel response: {payload!r}")
        return payload

    def query_order(self, symbol: str, order_id: int) -> dict[str, Any]:
        payload = parse_mcp_payload(
            self.call_mcp("futures_usds.queryOrder", {"symbol": symbol, "orderId": order_id})
        )
        if not isinstance(payload, dict):
            raise TypeError(f"Unexpected Agent OS query response: {payload!r}")
        return payload

    def open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        arguments = {"symbol": symbol} if symbol else {}
        payload = parse_mcp_payload(self.call_mcp("futures_usds.currentAllOpenOrders", arguments))
        return payload if isinstance(payload, list) else []

    def account(self) -> dict[str, Any]:
        payload = parse_mcp_payload(self.call_mcp("futures_usds.accountInformationV3", {}))
        if not isinstance(payload, dict):
            raise TypeError(f"Unexpected Agent OS account response: {payload!r}")
        return payload

    def positions(self, symbol: str | None = None) -> list[dict[str, Any]]:
        arguments = {"symbol": symbol} if symbol else {}
        payload = parse_mcp_payload(self.call_mcp("futures_usds.positionInformationV2", arguments))
        return payload if isinstance(payload, list) else []

    def set_leverage(self, symbol: str, leverage: int) -> dict[str, Any]:
        payload = parse_mcp_payload(
            self.call_mcp(
                "futures_usds.changeInitialLeverage", {"symbol": symbol, "leverage": leverage}
            )
        )
        if not isinstance(payload, dict):
            raise TypeError(f"Unexpected Agent OS leverage response: {payload!r}")
        return payload
