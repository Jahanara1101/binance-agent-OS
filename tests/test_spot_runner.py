from decimal import Decimal

from binance_mm.models import Book, Market, Order, Side
from binance_mm.spot_runner import SpotRunner


class FakeSpotExecutor:
    def __init__(self):
        self.orders = []
        self.placed = []
        self.cancelled = []
        self.balances = {"USDT": Decimal(10000), "BTC": Decimal(0)}

    def spot_account(self):
        return {"balances": [{"asset": k, "free": str(v), "locked": "0"} for k, v in self.balances.items()]}

    def spot_open_orders(self, symbol=None):
        return [x for x in self.orders if symbol is None or x["symbol"] == symbol]

    def place_spot(self, order, client_order_id):
        self.placed.append((order, client_order_id))
        return {"orderId": len(self.placed), "status": "NEW"}

    def cancel_spot(self, symbol, order_id):
        self.cancelled.append((symbol, order_id))
        return {"orderId": order_id, "status": "CANCELED"}


def market(symbol="BTCUSDT"):
    return Market(symbol, "USDT", "SPOT", "TRADING", Decimal("0.1"), Decimal("0.001"), Decimal("0.001"), Decimal(5), Decimal(20000000))


def test_spot_without_base_inventory_places_buy_only_not_naked_sell():
    ex = FakeSpotExecutor()
    SpotRunner(ex).cycle([market()], {"BTCUSDT": Book(Decimal(100), Decimal("100.1"))}, 10000)
    assert len(ex.placed) == 1
    assert ex.placed[0][0].side is Side.BUY


def test_spot_base_inventory_places_sell_maker_exit_even_below_spread_gate():
    ex = FakeSpotExecutor()
    ex.balances["BTC"] = Decimal("0.1")
    SpotRunner(ex).cycle([market()], {"BTCUSDT": Book(Decimal(100), Decimal("100.001"))}, 10000)
    assert len(ex.placed) == 1
    order = ex.placed[0][0]
    assert order == Order("BTCUSDT", Side.SELL, Decimal("100.001"), Decimal("0.1"), True)


def test_spot_has_separate_30_order_cap_and_only_cancels_own_orders():
    ex = FakeSpotExecutor()
    ex.orders = [
        {"symbol": f"X{i}USDT", "orderId": i, "clientOrderId": f"manual-{i}", "time": 9999}
        for i in range(29)
    ] + [{"symbol": "OLDUSDT", "orderId": 40, "clientOrderId": "hmm-spot-old", "time": 1}]
    SpotRunner(ex, max_orders=30).cycle([market()], {"BTCUSDT": Book(Decimal(100), Decimal("100.1"))}, 10000)
    assert ex.cancelled == [("OLDUSDT", 40)]
    assert len(ex.orders) + len(ex.placed) - len(ex.cancelled) <= 30
