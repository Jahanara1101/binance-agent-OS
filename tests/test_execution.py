from decimal import Decimal

import pytest

from binance_mm.execution import ExecutionCoordinator
from binance_mm.models import Order, Side
from binance_mm.state import InventoryBook


class FakeClient:
    def __init__(self):
        self.cancelled = []
        self.queried = []
        self.positions = []

    async def cancel_order(self, symbol, order_id):
        self.cancelled.append((symbol, order_id))
        return {"status": "CANCELED", "executedQty": "0"}

    async def query_order(self, symbol, order_id):
        self.queried.append((symbol, order_id))
        return {"status": "CANCELED", "executedQty": "0"}

    async def position_risk(self, symbol=None):
        return self.positions


@pytest.mark.asyncio
async def test_partial_fill_triggers_sibling_cancel_before_exit_signal():
    state = InventoryBook()
    state.track(1, Order("BTCUSDT", Side.BUY, Decimal(100), Decimal("0.01")))
    state.track(2, Order("BTCUSDT", Side.SELL, Decimal(101), Decimal("0.01")))
    client = FakeClient()
    coordinator = ExecutionCoordinator(client, state)

    result = await coordinator.handle_order_update({
        "e": "ORDER_TRADE_UPDATE",
        "o": {"s": "BTCUSDT", "S": "BUY", "i": 1, "x": "TRADE", "l": "0.004", "L": "100"},
    })

    assert client.cancelled == [("BTCUSDT", 2)]
    assert result.exit_required is True
    assert result.position_quantity == Decimal("0.004")


@pytest.mark.asyncio
async def test_duplicate_trade_event_is_idempotent():
    state = InventoryBook()
    state.track(1, Order("BTCUSDT", Side.BUY, Decimal(100), Decimal("0.01")))
    client = FakeClient()
    coordinator = ExecutionCoordinator(client, state)
    event = {
        "e": "ORDER_TRADE_UPDATE",
        "o": {"s": "BTCUSDT", "S": "BUY", "i": 1, "t": 77, "x": "TRADE", "l": "0.004", "L": "100"},
    }
    first = await coordinator.handle_order_update(event)
    second = await coordinator.handle_order_update(event)
    assert first.exit_required is True
    assert second.duplicate is True
    assert state.position("BTCUSDT").quantity == Decimal("0.004")


@pytest.mark.asyncio
async def test_reconcile_keeps_locally_unknown_exchange_order_out_of_bot_state():
    state = InventoryBook()
    client = FakeClient()
    coordinator = ExecutionCoordinator(client, state)
    result = await coordinator.reconcile([
        {"symbol": "BTCUSDT", "orderId": 999, "clientOrderId": "manual", "side": "BUY", "price": "1", "origQty": "1", "reduceOnly": False},
    ])
    assert result.unknown_manual_orders == [999]
    assert state.orders == {}
