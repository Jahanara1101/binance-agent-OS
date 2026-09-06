from decimal import Decimal

from binance_mm.agent_os_runner import AgentOSRunner
from binance_mm.models import Book, Market, Side


class FakeExecutor:
    def __init__(self):
        self.placed = []
        self.cancelled = []
        self.orders = []
        self.positions_data = []
        self.account_data = {"totalMarginBalance": "10000"}

    def account(self):
        return self.account_data

    def positions(self, symbol=None):
        return [x for x in self.positions_data if symbol is None or x["symbol"] == symbol]

    def open_orders(self, symbol=None):
        return [x for x in self.orders if symbol is None or x["symbol"] == symbol]

    def place(self, order, client_order_id):
        self.placed.append((order, client_order_id))
        return {"orderId": len(self.placed), "status": "NEW"}

    def cancel(self, symbol, order_id):
        self.cancelled.append((symbol, order_id))
        return {"orderId": order_id, "status": "CANCELED"}

    def set_leverage(self, symbol, leverage):
        return {"symbol": symbol, "leverage": leverage}


def market(symbol="BTCUSDT"):
    return Market(symbol, "USDT", "PERPETUAL", "TRADING", Decimal("0.1"), Decimal("0.001"), Decimal("0.001"), Decimal(5), Decimal(20000000))


def test_cycle_cancels_expired_bot_orders_and_places_agent_os_quotes():
    ex = FakeExecutor()
    ex.orders = [
        {"symbol": "OLDUSDT", "orderId": 8, "clientOrderId": "hmm-old", "time": 1},
        {"symbol": "MANUALUSDT", "orderId": 9, "clientOrderId": "manual", "time": 1},
    ]
    runner = AgentOSRunner(ex, refresh_seconds=3, max_orders=30)
    result = runner.cycle(
        [market()], {"BTCUSDT": Book(Decimal(100), Decimal("100.1"))}, now_ms=10000
    )
    assert ex.cancelled == [("OLDUSDT", 8)]
    assert len(ex.placed) == 2
    assert {order.side for order, _ in ex.placed} == {Side.BUY, Side.SELL}
    assert result.awaiting_confirmations == 3


def test_cycle_never_cancels_manual_orders():
    ex = FakeExecutor()
    ex.orders = [{"symbol": "BTCUSDT", "orderId": 7, "clientOrderId": "manual", "time": 1}]
    AgentOSRunner(ex).cycle([], {}, now_ms=10000)
    assert ex.cancelled == []


def test_position_suppresses_entries_and_places_reduce_only_maker_exit():
    ex = FakeExecutor()
    ex.positions_data = [{"symbol": "BTCUSDT", "positionAmt": "0.01"}]
    runner = AgentOSRunner(ex)
    runner.cycle([market()], {"BTCUSDT": Book(Decimal(100), Decimal("100.001"))}, now_ms=10000)
    assert len(ex.placed) == 1
    exit_order = ex.placed[0][0]
    assert exit_order.side is Side.SELL
    assert exit_order.reduce_only
    assert exit_order.price == Decimal("100.001")


def test_order_capacity_counts_existing_exchange_orders():
    ex = FakeExecutor()
    ex.orders = [
        {"symbol": f"X{i}USDT", "orderId": i, "clientOrderId": f"manual-{i}", "time": 9999}
        for i in range(29)
    ]
    AgentOSRunner(ex, max_orders=30).cycle(
        [market()], {"BTCUSDT": Book(Decimal(100), Decimal("100.1"))}, now_ms=10000
    )
    assert len(ex.placed) == 1
