from dataclasses import dataclass
from decimal import Decimal

from .models import Book, Market, Order, Position, Side


@dataclass(frozen=True)
class Fill:
    order_id: int
    symbol: str
    side: Side
    quantity: Decimal
    price: Decimal


class InventoryBook:
    def __init__(self) -> None:
        self.orders: dict[int, Order] = {}
        self._net: dict[str, Decimal] = {}

    def track(self, order_id: int, order: Order) -> None:
        self.orders[order_id] = order

    def forget(self, order_id: int) -> None:
        self.orders.pop(order_id, None)

    def apply_fill(self, fill: Fill) -> list[int]:
        signed = fill.quantity if fill.side is Side.BUY else -fill.quantity
        new_net = self._net.get(fill.symbol, Decimal(0)) + signed
        if new_net == 0:
            self._net.pop(fill.symbol, None)
        else:
            self._net[fill.symbol] = new_net
        self.orders.pop(fill.order_id, None)
        return [
            order_id
            for order_id, order in self.orders.items()
            if order.symbol == fill.symbol and not order.reduce_only
        ]

    def position(self, symbol: str) -> Position | None:
        net = self._net.get(symbol, Decimal(0))
        if net == 0:
            return None
        return Position(symbol, abs(net), Side.BUY if net > 0 else Side.SELL)

    def exit_order(self, market: Market, book: Book) -> Order | None:
        position = self.position(market.symbol)
        if position is None:
            return None
        side = Side.SELL if position.side is Side.BUY else Side.BUY
        price = book.ask if side is Side.SELL else book.bid
        return Order(market.symbol, side, price, position.quantity, reduce_only=True)
