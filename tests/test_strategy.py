from decimal import Decimal

from binance_mm.models import Book, Market, Position, Side
from binance_mm.strategy import (
    bollinger_bandwidth,
    is_volatile,
    quote_candidates,
    select_markets,
    size_quotes,
)


def market(symbol="BTCUSDT", quote="USDT", volume="20000000"):
    return Market(
        symbol=symbol,
        quote_asset=quote,
        contract_type="PERPETUAL",
        status="TRADING",
        tick_size=Decimal("0.1"),
        step_size=Decimal("0.001"),
        min_qty=Decimal("0.001"),
        min_notional=Decimal(5),
        quote_volume=Decimal(volume),
    )


def test_select_markets_defaults_to_usdt_perpetuals_and_10m_volume():
    markets = [
        market(),
        market("ETHUSDC", "USDC"),
        market("LOWUSDT", volume="9999999"),
        Market(**{**market("OLDUSDT").__dict__, "status": "BREAK"}),
    ]
    selected = select_markets(markets, "USDT", Decimal(10000000))
    assert [m.symbol for m in selected] == ["BTCUSDT"]


def test_spread_gate_is_inclusive_at_two_basis_points():
    m = market()
    eligible = quote_candidates(
        {m.symbol: m}, {m.symbol: Book(Decimal("99.99"), Decimal("100.01"))}, Decimal("0.0002")
    )
    assert len(eligible) == 2
    assert {x.symbol for x in eligible} == {m.symbol}
    assert {x.side for x in eligible} == {Side.BUY, Side.SELL}


def test_size_quotes_uses_one_percent_margin_total_and_two_x_notional():
    markets = [market("BTCUSDT"), market("ETHUSDT")]
    books = {
        "BTCUSDT": Book(Decimal(100), Decimal("100.1")),
        "ETHUSDT": Book(Decimal(10), Decimal("10.01")),
    }
    sized = size_quotes(
        markets, books, equity=Decimal(10000), margin_fraction=Decimal("0.01"), leverage=2
    )
    total_notional = sum(x.notional for x in sized)
    assert total_notional <= Decimal(200)
    assert len(sized) <= 4


def test_bollinger_wide_band_uses_current_bandwidth_above_80th_percentile():
    closes = [Decimal(100) for _ in range(219)] + [Decimal(130)]
    bandwidths = bollinger_bandwidth(closes, period=20, stddevs=Decimal(2))
    assert is_volatile(bandwidths, percentile=Decimal("0.8"), lookback=200)


def test_exit_order_ignores_entry_spread_gate_and_is_reduce_only():
    position = Position("BTCUSDT", Decimal("0.01"), Side.BUY)
    book = Book(Decimal(100), Decimal("100.001"))
    orders = quote_candidates(
        {"BTCUSDT": market()},
        {"BTCUSDT": book},
        Decimal("0.0002"),
        positions={"BTCUSDT": position},
    )
    assert len(orders) == 1
    assert orders[0].side is Side.SELL
    assert orders[0].reduce_only is True
    assert orders[0].quantity == position.quantity


def test_global_order_cap_never_exceeds_30():
    markets = [market(f"C{i}USDT") for i in range(40)]
    books = {m.symbol: Book(Decimal(99), Decimal(101)) for m in markets}
    sized = size_quotes(markets, books, Decimal(100000), Decimal("0.01"), 2, max_orders=30)
    assert len(sized) == 30
