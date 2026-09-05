import json
from decimal import Decimal

from binance_mm.agent_os import AgentOSExecutor, parse_mcp_payload
from binance_mm.models import Order, Side


class FakeMCP:
    def __init__(self):
        self.calls = []

    def call(self, tool, arguments):
        self.calls.append((tool, arguments))
        if tool == "futures_usds.newOrder":
            return {"result": {"orderId": 321, "status": "NEW"}}
        if tool == "futures_usds.cancelOrder":
            return {"result": {"orderId": 321, "status": "CANCELED"}}
        return {"result": []}


def test_live_order_uses_agent_os_futures_tool_not_api_credentials():
    mcp = FakeMCP()
    executor = AgentOSExecutor(mcp.call)
    order = Order("BTCUSDT", Side.BUY, Decimal(100), Decimal("0.01"))
    result = executor.place(order, "hmm-test")
    assert result["orderId"] == 321
    assert mcp.calls == [(
        "futures_usds.newOrder",
        {
            "symbol": "BTCUSDT", "side": "BUY", "type": "LIMIT", "timeInForce": "GTX",
            "quantity": "0.01", "price": "100", "reduceOnly": False,
            "newClientOrderId": "hmm-test",
        },
    )]


def test_cancel_uses_agent_os_cancel_tool():
    mcp = FakeMCP()
    executor = AgentOSExecutor(mcp.call)
    result = executor.cancel("BTCUSDT", 321)
    assert result["status"] == "CANCELED"
    assert mcp.calls[0] == ("futures_usds.cancelOrder", {"symbol": "BTCUSDT", "orderId": 321})


def test_nested_mcp_text_result_is_normalized():
    raw = {"result": json.dumps({"orderId": 9, "status": "NEW"})}
    assert parse_mcp_payload(raw)["orderId"] == 9
