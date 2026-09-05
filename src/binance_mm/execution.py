from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from .models import Order, Side
from .state import Fill, InventoryBook


@dataclass
class UpdateResult:
    duplicate: bool = False
    exit_required: bool = False
    position_quantity: Decimal = Decimal(0)
    cancelled_siblings: list[int] = field(default_factory=list)


@dataclass
class ReconcileResult:
    unknown_manual_orders: list[int] = field(default_factory=list)
    restored_bot_orders: list[int] = field(default_factory=list)


class ExecutionCoordinator:
    def __init__(self, client: Any, inventory: InventoryBook, client_prefix: str = "hmm-") -> None:
        self.client = client
        self.inventory = inventory
        self.client_prefix = client_prefix
        self._seen_trades: set[tuple[str, int, int | str]] = set()

    async def handle_order_update(self, event: dict[str, Any]) -> UpdateResult:
        if event.get("e") != "ORDER_TRADE_UPDATE":
            return UpdateResult()
        order = event.get("o", {})
        if order.get("x") != "TRADE" or Decimal(str(order.get("l", "0"))) <= 0:
            return UpdateResult()
        order_id = int(order["i"])
        trade_key = (str(order["s"]), order_id, order.get("t", f"{order.get('l')}:{order.get('L')}"))
        if trade_key in self._seen_trades:
            return UpdateResult(duplicate=True)
        self._seen_trades.add(trade_key)
        fill = Fill(
            order_id=order_id,
            symbol=str(order["s"]),
            side=Side(str(order["S"])),
            quantity=Decimal(str(order["l"])),
            price=Decimal(str(order["L"])),
        )
        siblings = self.inventory.apply_fill(fill)
        cancelled: list[int] = []
        for sibling_id in siblings:
            sibling = self.inventory.orders.get(sibling_id)
            if sibling is None:
                continue
            try:
                await self.client.cancel_order(sibling.symbol, sibling_id)
            finally:
                self.inventory.forget(sibling_id)
            cancelled.append(sibling_id)
        position = self.inventory.position(fill.symbol)
        return UpdateResult(
            exit_required=position is not None,
            position_quantity=position.quantity if position else Decimal(0),
            cancelled_siblings=cancelled,
        )

    async def reconcile(self, exchange_orders: list[dict[str, Any]]) -> ReconcileResult:
        result = ReconcileResult()
        exchange_ids = set()
        for row in exchange_orders:
            order_id = int(row["orderId"])
            exchange_ids.add(order_id)
            client_id = str(row.get("clientOrderId", ""))
            if not client_id.startswith(self.client_prefix):
                result.unknown_manual_orders.append(order_id)
                continue
            if order_id not in self.inventory.orders:
                self.inventory.track(
                    order_id,
                    Order(
                        symbol=str(row["symbol"]),
                        side=Side(str(row["side"])),
                        price=Decimal(str(row["price"])),
                        quantity=Decimal(str(row["origQty"])),
                        reduce_only=bool(row.get("reduceOnly", False)),
                    ),
                )
                result.restored_bot_orders.append(order_id)
        for order_id in list(self.inventory.orders):
            if order_id not in exchange_ids:
                self.inventory.forget(order_id)
        return result
