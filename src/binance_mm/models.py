from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class Market:
    symbol: str
    quote_asset: str
    contract_type: str
    status: str
    tick_size: Decimal
    step_size: Decimal
    min_qty: Decimal
    min_notional: Decimal
    quote_volume: Decimal


@dataclass(frozen=True)
class Book:
    bid: Decimal
    ask: Decimal

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / Decimal(2)

    @property
    def spread_fraction(self) -> Decimal:
        if self.mid <= 0:
            return Decimal(0)
        return (self.ask - self.bid) / self.mid


@dataclass(frozen=True)
class Position:
    symbol: str
    quantity: Decimal
    side: Side


@dataclass(frozen=True)
class Order:
    symbol: str
    side: Side
    price: Decimal
    quantity: Decimal
    reduce_only: bool = False

    @property
    def notional(self) -> Decimal:
        return self.price * self.quantity
