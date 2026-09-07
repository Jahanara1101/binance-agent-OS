"""Paper (demo) spot market maker.

Mirrors the live Agent OS SpotRunner logic but executes against the local
PaperBroker (simulated fills) instead of the exchange. Spot semantics:

* We hold a quote balance (e.g. USDT) and base inventory per symbol.
* Existing base inventory is exited first with a maker SELL (no spread gate).
* Fresh BUY entries are sized to a fraction of the quote balance and only
  proposed when the spread gate (>= min_spread) is met.
* No naked SELL: we never sell a base we do not hold.

The Agent class drives the cycle; this module only decides which orders to
propose given markets, books, balances and open inventory.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from .models import Book, Market, Order, Side


def _floor(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def base_asset(market: Market) -> str:
    return market.symbol[: -len(market.quote_asset)]


def propose_spot_orders(
    markets: list[Market],
    books: dict[str, Book],
    quote_balance: Decimal,
    base_balances: dict[str, Decimal],
    allocation: Decimal = Decimal("0.01"),
    min_spread: Decimal = Decimal("0.0002"),
    max_orders: int = 30,
) -> list[Order]:
    """Return maker orders for one paper-spot cycle (exits first, then buys)."""
    proposals: list[Order] = []
    inventory_symbols: set[str] = set()

    # 1) Exit existing base inventory with a maker SELL (no spread gate).
    for market in markets:
        book = books.get(market.symbol)
        if not book:
            continue
        base = base_asset(market)
        amount = _floor(base_balances.get(base, Decimal(0)), market.step_size)
        if amount >= market.min_qty and amount * book.ask >= market.min_notional:
            inventory_symbols.add(market.symbol)
            proposals.append(Order(market.symbol, Side.SELL, book.ask, amount, reduce_only=True))

    # 2) Fresh BUY entries on non-inventory symbols that meet the spread gate.
    buy_markets = [
        m for m in markets
        if m.symbol not in inventory_symbols
        and m.symbol in books
        and books[m.symbol].spread_fraction >= min_spread
    ]
    slots = max(0, max_orders - len(proposals))
    if slots and buy_markets and quote_balance > 0:
        notional_per = quote_balance * allocation / Decimal(min(slots, len(buy_markets)))
        for market in buy_markets[:slots]:
            book = books[market.symbol]
            quantity = _floor(notional_per / book.bid, market.step_size)
            if quantity >= market.min_qty and quantity * book.bid >= market.min_notional:
                proposals.append(Order(market.symbol, Side.BUY, book.bid, quantity))

    return proposals[:max_orders]
