from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal
from typing import Any

from .models import Book, Market, Order, Side


@dataclass
class SpotCycleResult:
    placed: list[dict[str, Any]] = field(default_factory=list)
    cancelled: list[dict[str, Any]] = field(default_factory=list)
    awaiting_confirmations: int = 0


class SpotRunner:
    """One confirmation-gated Binance Agent OS spot cycle."""

    def __init__(
        self,
        executor: Any,
        refresh_seconds: int = 3,
        max_orders: int = 30,
        allocation: Decimal = Decimal("0.01"),
        min_spread: Decimal = Decimal("0.0002"),
    ) -> None:
        self.executor = executor
        self.refresh_seconds = refresh_seconds
        self.max_orders = max_orders
        self.allocation = allocation
        self.min_spread = min_spread
        self.sequence = 0

    @staticmethod
    def _balances(account: dict[str, Any]) -> dict[str, Decimal]:
        return {
            str(row["asset"]): Decimal(str(row.get("free", "0")))
            for row in account.get("balances", [])
            if Decimal(str(row.get("free", "0"))) > 0
        }

    @staticmethod
    def _base_asset(market: Market) -> str:
        return market.symbol[: -len(market.quote_asset)]

    @staticmethod
    def _floor(value: Decimal, step: Decimal) -> Decimal:
        return (value / step).to_integral_value(rounding=ROUND_DOWN) * step

    def cycle(self, markets: list[Market], books: dict[str, Book], now_ms: int) -> SpotCycleResult:
        result = SpotCycleResult()
        exchange_orders = self.executor.spot_open_orders()
        active_count = len(exchange_orders)
        ttl_ms = self.refresh_seconds * 1000
        for row in exchange_orders:
            client_id = str(row.get("clientOrderId", ""))
            created = int(row.get("time", row.get("updateTime", now_ms)))
            if client_id.startswith("hmm-spot-") and now_ms - created >= ttl_ms:
                result.cancelled.append(self.executor.cancel_spot(str(row["symbol"]), int(row["orderId"])))
                result.awaiting_confirmations += 1
                active_count -= 1
        capacity = max(0, self.max_orders - active_count)
        if capacity == 0:
            return result
        balances = self._balances(self.executor.spot_account())
        quote_balance = balances.get(markets[0].quote_asset, Decimal(0)) if markets else Decimal(0)
        eligible = [m for m in markets if m.symbol in books]
        # Existing base inventory exits first and does not require the entry spread gate.
        proposals: list[Order] = []
        inventory_symbols = set()
        for market in eligible:
            base = self._base_asset(market)
            amount = self._floor(balances.get(base, Decimal(0)), market.step_size)
            if amount >= market.min_qty and amount * books[market.symbol].ask >= market.min_notional:
                inventory_symbols.add(market.symbol)
                proposals.append(Order(market.symbol, Side.SELL, books[market.symbol].ask, amount, True))
        buy_markets = [
            m for m in eligible
            if m.symbol not in inventory_symbols and books[m.symbol].spread_fraction >= self.min_spread
        ]
        slots = max(0, capacity - len(proposals))
        if slots and buy_markets and quote_balance > 0:
            notional = quote_balance * self.allocation / Decimal(min(slots, len(buy_markets)))
            for market in buy_markets[:slots]:
                quantity = self._floor(notional / books[market.symbol].bid, market.step_size)
                if quantity >= market.min_qty and quantity * books[market.symbol].bid >= market.min_notional:
                    proposals.append(Order(market.symbol, Side.BUY, books[market.symbol].bid, quantity))
        for order in proposals[:capacity]:
            self.sequence += 1
            result.placed.append(
                self.executor.place_spot(order, f"hmm-spot-{now_ms}-{self.sequence}")
            )
            result.awaiting_confirmations += 1
        return result
