from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal
from typing import Any

from .models import Book, Market, Order, Side
from .strategy import size_quotes


@dataclass
class CycleResult:
    placed: list[dict[str, Any]] = field(default_factory=list)
    cancelled: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    awaiting_confirmations: int = 0


class AgentOSRunner:
    """One confirmation-gated Binance Agent OS market-making cycle."""

    def __init__(
        self,
        executor: Any,
        refresh_seconds: int = 3,
        max_orders: int = 30,
        margin_fraction: Decimal = Decimal("0.01"),
        leverage: int = 2,
        min_spread: Decimal = Decimal("0.0002"),
    ) -> None:
        self.executor = executor
        self.refresh_seconds = refresh_seconds
        self.max_orders = max_orders
        self.margin_fraction = margin_fraction
        self.leverage = leverage
        self.min_spread = min_spread
        self.sequence = 0
        self.last_snapshot: dict[str, Any] = {}

    def _positions(self) -> dict[str, Decimal]:
        result = {}
        for row in self.executor.positions():
            amount = Decimal(str(row.get("positionAmt", "0")))
            if amount:
                result[str(row["symbol"])] = amount
        return result

    def _exit_order(self, market: Market, book: Book, amount: Decimal) -> Order:
        side = Side.SELL if amount > 0 else Side.BUY
        price = book.ask if side is Side.SELL else book.bid
        quantity = (abs(amount) / market.step_size).to_integral_value(rounding=ROUND_DOWN) * market.step_size
        return Order(market.symbol, side, price, quantity, reduce_only=True)

    def cycle(self, markets: list[Market], books: dict[str, Book], now_ms: int) -> CycleResult:
        result = CycleResult()
        exchange_orders = self.executor.open_orders()
        active_count = len(exchange_orders)
        ttl_ms = self.refresh_seconds * 1000
        for row in exchange_orders:
            client_id = str(row.get("clientOrderId", ""))
            created = int(row.get("time", row.get("updateTime", now_ms)))
            if client_id.startswith("hmm-") and now_ms - created >= ttl_ms:
                cancelled = self.executor.cancel(str(row["symbol"]), int(row["orderId"]))
                result.cancelled.append(cancelled)
                result.awaiting_confirmations += 1
                active_count -= 1
        capacity = max(0, self.max_orders - active_count)
        if capacity == 0:
            return result

        positions = self._positions()
        market_by_symbol = {market.symbol: market for market in markets}
        exit_orders = []
        for symbol, amount in positions.items():
            if symbol in market_by_symbol and symbol in books:
                exit_orders.append(self._exit_order(market_by_symbol[symbol], books[symbol], amount))
        candidates = [m for m in markets if m.symbol not in positions and m.symbol in books]
        candidates = [m for m in candidates if books[m.symbol].spread_fraction >= self.min_spread]
        equity = Decimal(str(self.executor.account().get("totalMarginBalance", "0")))
        entry_capacity = max(0, capacity - len(exit_orders))
        sizing_capacity = entry_capacity if entry_capacity % 2 == 0 else entry_capacity + 1
        entries = size_quotes(
            candidates, books, equity, self.margin_fraction, self.leverage, sizing_capacity
        )[:entry_capacity]
        for order in (exit_orders + entries)[:capacity]:
            self.sequence += 1
            response = self.executor.place(order, f"hmm-{now_ms}-{self.sequence}")
            result.placed.append(response)
            result.awaiting_confirmations += 1
        return result
