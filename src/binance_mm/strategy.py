from decimal import ROUND_DOWN, Decimal
from math import floor
from statistics import pstdev

from .models import Book, Market, Order, Position, Side


def select_markets(markets: list[Market], quote_asset: str, min_volume: Decimal) -> list[Market]:
    quote_asset = quote_asset.upper()
    return [
        market
        for market in markets
        if market.quote_asset == quote_asset
        and market.contract_type in {"PERPETUAL", "SPOT"}
        and market.status == "TRADING"
        and market.quote_volume >= min_volume
    ]


def _floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def quote_candidates(
    markets: dict[str, Market],
    books: dict[str, Book],
    min_spread: Decimal,
    positions: dict[str, Position] | None = None,
) -> list[Order]:
    positions = positions or {}
    orders: list[Order] = []
    for symbol in markets:
        book = books.get(symbol)
        if not book or book.bid <= 0 or book.ask <= book.bid:
            continue
        position = positions.get(symbol)
        if position and position.quantity > 0:
            exit_side = Side.SELL if position.side is Side.BUY else Side.BUY
            price = book.ask if exit_side is Side.SELL else book.bid
            orders.append(Order(symbol, exit_side, price, position.quantity, reduce_only=True))
            continue
        if book.spread_fraction >= min_spread:
            orders.extend(
                [
                    Order(symbol, Side.BUY, book.bid, Decimal(0)),
                    Order(symbol, Side.SELL, book.ask, Decimal(0)),
                ]
            )
    return orders


def size_quotes(
    markets: list[Market],
    books: dict[str, Book],
    equity: Decimal,
    margin_fraction: Decimal,
    leverage: int,
    max_orders: int = 30,
) -> list[Order]:
    selected = [m for m in markets if m.symbol in books][: max_orders // 2]
    order_count = min(max_orders, len(selected) * 2)
    if order_count == 0 or equity <= 0:
        return []
    notional_per_order = equity * margin_fraction * Decimal(leverage) / Decimal(order_count)
    result: list[Order] = []
    for market in selected:
        book = books[market.symbol]
        for side, price in ((Side.BUY, book.bid), (Side.SELL, book.ask)):
            quantity = _floor_to_step(notional_per_order / price, market.step_size)
            if quantity < market.min_qty or quantity * price < market.min_notional:
                continue
            result.append(Order(market.symbol, side, price, quantity))
    return result[:max_orders]


def bollinger_bandwidth(
    closes: list[Decimal], period: int = 20, stddevs: Decimal = Decimal(2)
) -> list[Decimal]:
    values: list[Decimal] = []
    for end in range(period, len(closes) + 1):
        window = closes[end - period : end]
        mean = sum(window) / Decimal(period)
        if mean == 0:
            values.append(Decimal(0))
            continue
        std = Decimal(str(pstdev(float(x) for x in window)))
        values.append((Decimal(2) * stddevs * std) / mean)
    return values


def is_volatile(
    bandwidths: list[Decimal], percentile: Decimal = Decimal("0.8"), lookback: int = 200
) -> bool:
    if len(bandwidths) < lookback:
        return False
    history = sorted(bandwidths[-lookback:-1])
    if not history:
        return False
    index = min(len(history) - 1, max(0, floor(float(percentile) * len(history))))
    return bandwidths[-1] > history[index]
