from dataclasses import dataclass, field
from decimal import Decimal
from itertools import count

from .models import Book, Order, Side


@dataclass
class PaperFill:
    symbol: str
    side: Side
    price: Decimal
    quantity: Decimal
    order_id: int


@dataclass
class PaperBroker:
    equity: Decimal = Decimal(10000)
    orders: dict[int, Order] = field(default_factory=dict)
    fills: list[PaperFill] = field(default_factory=list)
    _ids: count = field(default_factory=lambda: count(1))

    def place(self, order: Order) -> int:
        order_id = next(self._ids)
        self.orders[order_id] = order
        return order_id

    def cancel(self, order_id: int) -> Order | None:
        return self.orders.pop(order_id, None)

    def match(self, books: dict[str, Book]) -> list[PaperFill]:
        new_fills: list[PaperFill] = []
        for order_id, order in list(self.orders.items()):
            book = books.get(order.symbol)
            if not book:
                continue
            crossed = (order.side is Side.BUY and book.ask <= order.price) or (
                order.side is Side.SELL and book.bid >= order.price
            )
            if not crossed:
                continue
            fill = PaperFill(order.symbol, order.side, order.price, order.quantity, order_id)
            new_fills.append(fill)
            self.fills.append(fill)
            self.orders.pop(order_id, None)
        return new_fills
