from decimal import Decimal

from binance_mm.binance import parse_books, parse_markets
from binance_mm.models import Book, Order, Side
from binance_mm.paper import PaperBroker


def test_parse_filters_and_quote_volume():
    info = {
        "symbols": [{
            "symbol": "BTCUSDT", "quoteAsset": "USDT", "contractType": "PERPETUAL", "status": "TRADING",
            "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": "0.1"},
                {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
                {"filterType": "MIN_NOTIONAL", "notional": "5"},
            ],
        }]
    }
    parsed = parse_markets(info, [{"symbol": "BTCUSDT", "quoteVolume": "12345678"}])
    assert parsed[0].quote_volume == Decimal(12345678)
    assert parsed[0].min_notional == Decimal(5)


def test_parse_books_rejects_zero_sided_books():
    result = parse_books([
        {"symbol": "OKUSDT", "bidPrice": "10", "askPrice": "11"},
        {"symbol": "BADUSDT", "bidPrice": "0", "askPrice": "11"},
    ])
    assert result == {"OKUSDT": Book(Decimal(10), Decimal(11))}


def test_paper_order_only_fills_after_market_crosses_limit():
    broker = PaperBroker()
    oid = broker.place(Order("BTCUSDT", Side.BUY, Decimal(100), Decimal(1)))
    assert broker.match({"BTCUSDT": Book(Decimal(100), Decimal(101))}) == []
    fills = broker.match({"BTCUSDT": Book(Decimal(99), Decimal(100))})
    assert fills[0].order_id == oid
    assert oid not in broker.orders
