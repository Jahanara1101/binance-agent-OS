from decimal import Decimal

from binance_mm.agent_os import AgentOSExecutor
from binance_mm.models import Order, Side


class FakeMCP:
    def __init__(self):
        self.calls = []

    def call(self, tool, arguments):
        self.calls.append((tool, arguments))
        if tool == "spot.newOrder":
            return {"result": {"orderId": 11, "status": "NEW"}}
        if tool == "spot.deleteOrder":
            return {"result": {"orderId": 11, "status": "CANCELED"}}
        if tool == "spot.getOrder":
            return {"result": {"orderId": 11, "status": "NEW"}}
        if tool == "spot.getAccount":
            return {"result": {"balances": []}}
        return {"result": []}


def test_spot_order_uses_agent_os_spot_new_order():
    mcp = FakeMCP()
    executor = AgentOSExecutor(mcp.call)
    order = Order("BTCUSDT", Side.BUY, Decimal(100), Decimal("0.01"))
    result = executor.place_spot(order, "hmm-spot-test")
    assert result["orderId"] == 11
    assert mcp.calls == [(
        "spot.newOrder",
        {
            "symbol": "BTCUSDT", "side": "BUY", "type": "LIMIT_MAKER",
            "quantity": "0.01", "price": "100", "newClientOrderId": "hmm-spot-test",
        },
    )]


def test_spot_cancel_query_account_and_orders_use_agent_os():
    mcp = FakeMCP()
    executor = AgentOSExecutor(mcp.call)
    executor.cancel_spot("BTCUSDT", 11)
    executor.query_spot_order("BTCUSDT", 11)
    executor.spot_account()
    executor.spot_open_orders("BTCUSDT")
    assert [x[0] for x in mcp.calls] == [
        "spot.deleteOrder", "spot.getOrder", "spot.getAccount", "spot.getOpenOrders"
    ]
