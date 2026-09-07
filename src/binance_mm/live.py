"""Realtime market terminal for the Binance Agent OS market maker.

``binance-mm live`` shows EVERY eligible USDT-M perpetual with a live,
orderbook-fed bid/ask/spread (Binance !bookTicker WebSocket) in one scrollable
screen, plus a pinned summary of the running bot's equity / positions / open
orders (read from logs/*.jsonl). Nothing here places orders — order execution
always goes through Agent OS MCP in the bot process.

Scrolling:
  ↑/↓ or w/s      move one row
  PgUp/PgDn        page
  Home/End         top / bottom
  q                quit
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Any

from rich.console import Console, Group
from rich.live import Live
from rich.table import Table
from rich.text import Text

from .feeds import BookFeed

_FUTURES_REST = "https://fapi.binance.com"
_SPOT_REST = "https://api.binance.com"


def _eligible_symbols(venue: str = "perp") -> list[str]:
    from decimal import Decimal

    import httpx

    from .binance import parse_markets
    from .strategy import select_markets

    if venue == "spot":
        base, ctype = _SPOT_REST, "SPOT"
        info_path, ticker_path = "/api/v3/exchangeInfo", "/api/v3/ticker/24hr"
    else:
        base, ctype = _FUTURES_REST, "PERPETUAL"
        info_path, ticker_path = "/fapi/v1/exchangeInfo", "/fapi/v1/ticker/24hr"
    with httpx.Client(timeout=15) as c:
        info = c.get(base + info_path).json()
        tickers = c.get(base + ticker_path).json()
    markets = [m for m in parse_markets(info, tickers)
               if m.contract_type == ctype and m.status == "TRADING"]
    min_vol = Decimal(1_000_000) if venue == "spot" else Decimal(10_000_000)
    return [m.symbol for m in select_markets(markets, "USDT", min_vol)]


# --------------------------------------------------------------------------- #
# Read bot activity (equity / positions / orders) from the jsonl logs
# --------------------------------------------------------------------------- #


class BotState:
    """Last venue snapshot + open orders from the log the bot writes."""

    def __init__(self, log_path: str | Path, venue: str = "perp") -> None:
        self.path = Path(log_path)
        self.venue = venue
        self.equity = 0.0
        self.baseline: float | None = None
        self.positions: list[dict[str, Any]] = []
        self.open_orders: list[dict[str, Any]] = []
        self.activity: list[str] = []
        self.last_t = ""
        self._offset = 0
        self._seen = set()
        self._n_fill = 0
        self._n_cancel = 0

    def tick(self) -> None:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as fh:
            fh.seek(self._offset)
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self._apply(rec)
            self._offset = fh.tell()

    def _apply(self, rec: dict[str, Any]) -> None:
        venue = str(rec.get("venue", "")).lower()
        if venue != self.venue:
            return
        kind = rec.get("kind")
        self.last_t = str(rec.get("t", ""))[11:19]
        if kind == "snapshot":
            self.open_orders = list(rec.get("od", []))
            self.positions = [p for p in rec.get("pos", []) if float(p.get("amt", 0)) != 0]
            # spot snapshots carry balances; perp carries a margin-equity figure
            eq = rec.get("eq")
            if isinstance(eq, (int, float)):
                self.equity = float(eq)
                if self.baseline is None:
                    self.baseline = float(eq)
        elif kind == "event":
            event = str(rec.get("event", "")).upper()
            sym = str(rec.get("symbol", "?"))
            side = str(rec.get("side", "")).upper()
            price = str(rec.get("price", ""))
            qty = str(rec.get("qty", ""))
            oid = str(rec.get("order_id", ""))
            if event == "ORDER_CONFIRMED":
                color = "green" if side == "BUY" else "red"
                self.activity.append(f"[{color}]{side} {sym}[/] {qty}@{price} oid={oid}")
            elif event == "FILL":
                self._n_fill += 1
                self.activity.append(f"[cyan]FILL {side} {sym}[/] {qty}@{price}")
            elif event == "CANCEL_CONFIRMED":
                self._n_cancel += 1
                self.activity.append(f"[yellow]CANCEL {sym}[/] oid={oid}")
            if len(self.activity) > 14:
                self.activity = self.activity[-14:]


# --------------------------------------------------------------------------- #
# Realtime terminal
# --------------------------------------------------------------------------- #


class LiveTerminal:
    def __init__(self, log_path: str | Path, sort: str = "spread",
                 per_page: int = 30, venue: str = "perp") -> None:
        self.venue = venue
        self.feed: BookFeed | None = None
        self.bot = BotState(log_path, venue)
        self.offset = 0
        self.sort = sort
        self.per_page = per_page
        self.input_error: str | None = None
        self._key: str | None = None
        self._live: Live | None = None

    # -- keys --------------------------------------------------------------- #

    def _input_thread(self) -> None:
        if sys.platform == "win32":
            import msvcrt

            while True:
                ch = msvcrt.getwch()
                if ch in ("\x00", "\xe0"):
                    arrow = msvcrt.getwch()
                    if arrow in ("H", "A"):     # up
                        self._nudge(-1)
                    elif arrow in ("P", "B"):    # down
                        self._nudge(1)
                    elif arrow in ("I", "R"):    # pgup
                        self._nudge(-self.per_page)
                    elif arrow in ("Q", "S"):    # pgdn
                        self._nudge(self.per_page)
                    elif arrow == "G":           # home
                        self.offset = 0
                    elif arrow == "O":           # end
                        self.offset = 1 << 30
                elif ch in ("q", "Q"):
                    break
                elif ch in ("w", "W"):
                    self._nudge(-1)
                elif ch in ("s", "S"):
                    self._nudge(1)
        else:
            self._posix_input()

    def _posix_input(self) -> None:
        import termios
        import tty

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            while True:
                ch = sys.stdin.read(1)
                if not ch:
                    break
                if ch == "\x1b":
                    seq = sys.stdin.read(2)
                    if seq == "[A":
                        self._nudge(-1)
                    elif seq == "[B":
                        self._nudge(1)
                    elif seq == "[5~":
                        self._nudge(-self.per_page)
                    elif seq == "[6~":
                        self._nudge(self.per_page)
                elif ch in ("q", "Q"):
                    break
                elif ch in ("w", "W"):
                    self._nudge(-1)
                elif ch in ("s", "S"):
                    self._nudge(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    def _nudge(self, n: int) -> None:
        self.offset = max(0, self.offset + n)

    # -- render ------------------------------------------------------------- #

    def _market_table(self) -> Table:
        rows = self.feed.snapshot() if self.feed else []
        if self.sort == "spread":
            rows.sort(key=lambda r: -r["spread"])
        else:
            rows.sort(key=lambda r: r["sym"])
        t = Table(box=None, expand=True, pad_edge=False, show_edge=False)
        t.add_column("#", justify="right", style="dim")
        t.add_column("SYMBOL", style="bold cyan")
        t.add_column("BID", justify="right", style="white")
        t.add_column("ASK", justify="right", style="white")
        t.add_column("SPREAD %", justify="right")
        t.add_column("(B-A) TICKS", justify="right", style="dim")
        for i, r in enumerate(rows[self.offset:self.offset + self.per_page]):
            spread = r["spread"]
            color = ("bright_green" if spread >= 0.02
                     else "yellow" if spread >= 0.01 else "bright_red")
            px = max(r["bid"], r["ask"])
            tick = (r["ask"] - r["bid"]) / px if px else 0
            tick_disp = f"{tick * 100:.4f}%" if tick < 1 else f"{tick:.1f}x"
            t.add_row(str(self.offset + i + 1), r["sym"],
                      f"{r['bid']:.8g}", f"{r['ask']:.8g}",
                      f"[{color}]{spread:.4f}[/]", tick_disp)
        if not rows:
            t.add_row("[dim]connecting to orderbook feed…[/]", "", "", "", "", "")
        return t

    def _summary(self, total: int) -> Text:
        bot = self.bot
        eq_col = "bright_green" if bot.equity >= bot.baseline else "bright_red"
        fills = bot._n_fill
        cancels = bot._n_cancel
        posn = len(bot.positions)
        orders = len(bot.open_orders)
        feed_state = ("● live" if (self.feed and self.feed.connected)
                      else f"● reconnecting ({self.feed.error})" if (self.feed and self.feed.error)
                      else "○ connecting")
        t = Text.assemble(
            ("BINANCE ", "bold white"),
            (("USDT-M PERP LIVE" if self.venue == "perp" else "SPOT LIVE"), "bold"),
            ("   ", ""),
            (f"markets {total}", "cyan"),
            ("   ", ""), (feed_state, "green"),
            ("   ", ""),
            (f"EQUITY ${bot.equity:,.2f}", eq_col),
            ("   ", ""),
            (f"positions {posn}", "magenta"),
            ("   ", ""),
            (f"open orders {orders}", "yellow"),
            ("   ", ""),
            (f"fills {fills}", "cyan"),
            ("   ", ""),
            (f"cancels {cancels}", "white"),
        )
        return t

    def _panel(self, total: int, view_hint: str) -> Group:
        body = self._summary(total)
        head = Text.assemble(
            ("sort=", "dim"), (self.sort, "bold yellow"),
            ("   row ", "dim"), (f"{self.offset + 1}-{self.offset + self.per_page}", "cyan"),
            ("/", "dim"), (str(total), "cyan"),
            ("   ", "dim"),
            ("[↑↓ scroll] [PgUp/PgDn page] [q quit] ", "dim"),
        )
        return Group(head, self._market_table(), body)

    # -- main loop ---------------------------------------------------------- #

    def run(self) -> None:
        print("loading eligible markets…", end="", flush=True)
        syms = _eligible_symbols(self.venue)
        print(f" {len(syms)}", flush=True)
        self.feed = BookFeed(syms, venue=self.venue)
        self.feed.start()

        t = threading.Thread(target=self._input_thread, daemon=True)
        try:
            t.start()
        except Exception as exc:  # noqa: BLE001
            self.input_error = f"keyboard unavailable: {exc}"  # view still works

        with Live(console=Console(), refresh_per_second=8, screen=True) as live:
            self._live = live
            try:
                while True:
                    self.bot.tick()
                    live.update(self._panel(len(syms), ""))
                    time.sleep(0.15)
            except KeyboardInterrupt:
                pass
            finally:
                self.feed.stop()


def run_live(log_path: str | Path, venue: str = "perp") -> None:
    LiveTerminal(log_path, venue=venue).run()
