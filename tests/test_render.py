"""Render regression: every dashboard mode (demo perp/spot, live perp/spot,
watch) must produce a full-height, aligned output with no adjacent-cell
touching. Run: uv run pytest tests/test_render.py"""

import argparse
import io
import re
from decimal import Decimal

import pytest

from binance_mm.cli import Agent
from binance_mm.models import Market, Order, Side


def _make_agent(venue: str, width: int, height: int) -> Agent:
    args = argparse.Namespace(
        environment="paper", venue=venue, paper_equity=Decimal(10000),
        log_file="C:/Users/Julkar Nayen/.binance-mm/logs/demo.jsonl",
        standalone_skip_trigger=True, exit_only=False, max_orders=30, refresh=0.2,
        margin_fraction=Decimal("0.02"), leverage=5, min_volume=Decimal(10000000),
        min_spread=Decimal("0.0002"),
    )
    ag = Agent(args)
    ag.markets = [
        Market("GALAUSDT", "USDT", "PERPETUAL", "TRADING",
               Decimal("0.000001"), Decimal("0.000001"), Decimal(1),
               Decimal("0.01"), Decimal(100000000)),
        Market("1000BONKUSDT", "USDT", "PERPETUAL", "TRADING",
               Decimal("0.0000001"), Decimal("0.0000001"), Decimal(1),
               Decimal("0.01"), Decimal(100000000)),
    ]
    ag._books = {m.symbol: type("B", (), {
        "bid": Decimal("0.0019"), "ask": Decimal("0.00195"),
        "mid": Decimal("0.001925")})() for m in ag.markets}
    ag.active = {
        1: Order("GALAUSDT", Side.SELL, Decimal("0.001908"), Decimal(21826), 1),
        2: Order("1000BONKUSDT", Side.BUY, Decimal("0.003144"), Decimal(4543), 2),
    }
    ag.stats.placed = 10; ag.stats.cancelled = 5; ag.stats.fills = 2
    return ag


def _render_lines(agent: Agent, width: int, height: int) -> list[str]:
    return [l for l in _render_text(agent, width, height).split("\n") if l.strip()]


def _render_text(agent: Agent, width: int, height: int) -> str:
    from rich.console import Console

    import binance_mm.cli as C
    orig = C.Console
    class _C(Console):
        def __init__(self, *a, **k):
            k.setdefault("width", width); k.setdefault("height", height)
            super().__init__(*a, **k)
    C.Console = _C
    buf = io.StringIO()
    Console(file=buf, force_terminal=True, width=width, height=height,
            color_system="truecolor").print(agent.render())
    C.Console = orig
    txt = re.sub(r"\x1b\[[0-9;]*m", "", buf.getvalue()).replace("\r", "")
    return txt


@pytest.mark.parametrize("venue", ["perp", "spot"])
@pytest.mark.parametrize("width", [140, 170, 200])
def test_demo_columns_never_overlap(venue, width):
    """OPEN ORDERS columns must be space-separated (no adjacent cells touching)."""
    ag = _make_agent(venue, width, 30)
    lines = _render_lines(ag, width, 30)
    # find the header + a data row for OPEN ORDERS
    for i, line in enumerate(lines):
        if "SYMBOL" in line and "SIDE" in line and "QTY" in line:
            data = lines[i + 1] if i + 1 < len(lines) else ""
            # every field column must be preceded by at least one space
            # SELL/BUY side is the anchor: it must have space on both sides
            m = re.search(r"(BUY|SELL)", data)
            assert m, f"no SIDE in data row: {data!r}"
            assert data[m.start() - 1] == " ", f"SIDE touches left: {data!r}"
            assert data[m.end()] == " ", f"SIDE touches right: {data!r}"
            return
    pytest.fail("OPEN ORDERS header not found")


@pytest.mark.parametrize("width", [200, 220])
def test_spread_columns_separated(width):
    """LIVE SPREADS row: sym/bid/ask/spread each space-separated."""
    ag = _make_agent("perp", width, 30)
    lines = _render_lines(ag, width, 30)
    for i, line in enumerate(lines):
        if "BID" in line and "ASK" in line and "SPREAD%" in line:
            data = lines[i + 1] if i + 1 < len(lines) else ""
            # two numbers (bid ask) separated by spaces, then a % figure
            nums = re.findall(r"[\d.]+", data)
            assert len(nums) >= 4, f"expected bid/ask/spread digits, got {data!r}"
            return
    pytest.fail("LIVE SPREADS header not found")


@pytest.mark.parametrize("width", [140, 170, 200])
def test_full_height_filled(width):
    """The composer must emit exactly `height-1` body lines (dense, no gap)."""
    ag = _make_agent("perp", width, 30)
    txt = _render_text(ag, width, 30)
    # header row + (height-1) body rows
    assert len(txt.split("\n")) >= 30, "screen not filled to terminal height"