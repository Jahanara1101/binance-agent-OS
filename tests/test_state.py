from decimal import Decimal

from binance_mm.models import Book, Market, Order, Position, Side
from binance_mm.state import Fill, InventoryBook


def market():
    return Market("BTCUSDT", "USDT", "PERPETUAL", "TRADING", Decimal("0.1"), Decimal("0.001"), Decimal("0.001"), Decimal(5), Decimal(20000000))


def test_partial_fill_cancels_sibling_and_creates_reduce_only_exit_without_spread_gate():
    state = InventoryBook()
    buy = Order("BTCUSDT", Side.BUY, Decimal(100), Decimal("0.01"))
    sell = Order("BTCUSDT", Side.SELL, Decimal(101), Decimal("0.01"))
    state.track(1, buy)
    state.track(2, sell)

    sibling_ids = state.apply_fill(Fill(1, "BTCUSDT", Side.BUY, Decimal("0.004"), Decimal(100)))
    assert sibling_ids == [2]
    assert state.position("BTCUSDT") == Position("BTCUSDT", Decimal("0.004"), Side.BUY)

    exit_order = state.exit_order(market(), Book(Decimal(100), Decimal("100.001")))
    assert exit_order == Order("BTCUSDT", Side.SELL, Decimal("100.001"), Decimal("0.004"), True)


def test_exit_fill_reduces_inventory_and_flat_state_removes_position():
    state = InventoryBook()
    state.track(1, Order("BTCUSDT", Side.BUY, Decimal(100), Decimal("0.01")))
    state.apply_fill(Fill(1, "BTCUSDT", Side.BUY, Decimal("0.01"), Decimal(100)))
    state.track(3, Order("BTCUSDT", Side.SELL, Decimal("100.1"), Decimal("0.01"), True))
    state.apply_fill(Fill(3, "BTCUSDT", Side.SELL, Decimal("0.01"), Decimal("100.1")))
    assert state.position("BTCUSDT") is None


def test_dual_fills_are_netted_instead_of_reversing_position():
    state = InventoryBook()
    state.track(1, Order("BTCUSDT", Side.BUY, Decimal(100), Decimal("0.01")))
    state.track(2, Order("BTCUSDT", Side.SELL, Decimal(101), Decimal("0.01")))
    state.apply_fill(Fill(1, "BTCUSDT", Side.BUY, Decimal("0.006"), Decimal(100)))
    state.apply_fill(Fill(2, "BTCUSDT", Side.SELL, Decimal("0.004"), Decimal(101)))
    assert state.position("BTCUSDT") == Position("BTCUSDT", Decimal("0.002"), Side.BUY)
