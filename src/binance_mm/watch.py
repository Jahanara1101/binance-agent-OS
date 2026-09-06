"""Live trade dashboard bridge for the Binance Agent OS market maker.

Writer (in the bot) appends JSONL snapshots+events; viewer (separate terminal
tab) tails the file read-only and renders a rich, colored, live dashboard.

The viewer supports TWO trading modes, switchable with the Left/Right arrow
keys (or 'l' / 'd'):

  LIVE  -- Agent OS OAuth real account (bot writes .../live.jsonl)
  DEMO  -- internal paper simulation, no real funds (.../demo.jsonl)

Only the selected mode's view is shown; the other keeps being tailed in the
background so you can flip back instantly.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

# --------------------------------------------------------------------------- #
# Writer (runs inside the bot)
# --------------------------------------------------------------------------- #


class WatchLog:
    """Append-only JSONL writer living in the bot process."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh: TextIO = self.path.open("a", encoding="utf-8")

    def _write(self, kind: str, **data: Any) -> None:
        record = {"t": _utcnow(), "kind": kind, **data}
        self._fh.write(json.dumps(record, default=str) + "\n")
        self._fh.flush()

    def snapshot(self, **payload: Any) -> None:
        self._write("snapshot", **payload)

    def event(self, event: str, **payload: Any) -> None:
        self._write("event", event=event, **payload)

    def close(self) -> None:
        try:
            self._fh.flush()
            self._fh.close()
        except Exception:  # noqa: BLE001
            return


def _utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# Per-market rolling state
# --------------------------------------------------------------------------- #


def _side_color(side: str) -> str:
    return "green" if side.upper() == "BUY" else "red"


class MarketState:
    """One venue (perp/spot) view within a mode."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.markets: list[dict[str, Any]] = []
        self.open_orders: list[dict[str, Any]] = []
        self.fills: list[dict[str, Any]] = []          # explicit FILL events
        self.seen_open: set[str] = set()               # order ids still on book
        self.cancelled_total = 0
        self.buy_count = 0
        self.sell_count = 0
        self.place_total = 0
        self.filled_est = 0                            # open->disappeared (no cancel)

    def place(self, side: str) -> None:
        self.place_total += 1
        if side.upper() == "BUY":
            self.buy_count += 1
        else:
            self.sell_count += 1

    def reconcile_fill(self, open_ids: set[str]) -> None:
        """Estimate fills: orders that were placed, then left the book silently."""
        filled = [i for i in self.seen_open if i not in open_ids]
        self.filled_est += len(filled)
        self.seen_open = open_ids

    def mark_open(self, open_ids: set[str]) -> None:
        self.reconcile_fill(open_ids)


class ModeView:
    """All dashboard state for one trading mode (live or demo)."""

    def __init__(self, label: str, path: Path) -> None:
        self.label = label
        self.path = Path(path)
        self.perp = MarketState("PERP")
        self.spot = MarketState("SPOT")
        self.activity: list[str] = []
        self.equity = 0.0
        self.baseline_equity: float | None = None
        self.realized_pnl = 0.0
        self.position_rows: list[dict[str, Any]] = []
        self.balance_rows: list[dict[str, Any]] = []
        self.quote = "USDT"
        self.mode = label.lower()
        self.last_t = ""
        self._offset = 0
        self._tail_bytes = 200_000

    # -- ingestion --------------------------------------------------------- #

    def apply(self, line: str) -> None:
        rec = json.loads(line)
        self.last_t = str(rec.get("t", ""))[11:19]
        if rec.get("kind") == "snapshot":
            self._snapshot(rec)
        else:
            self._event(rec)

    def _snapshot(self, rec: dict[str, Any]) -> None:
        venue = str(rec.get("venue", rec.get("mode", ""))).lower()
        market = self.perp if venue == "perp" else self.spot
        if rec.get("mkts") is not None:
            market.markets = list(rec["mkts"])
        market.open_orders = list(rec.get("od", []))
        market.mark_open({str(o.get("orderId", o.get("order_id", ""))) for o in market.open_orders})
        if rec.get("quote"):
            self.quote = str(rec["quote"])
        self.mode = str(rec.get("src", self.mode)).lower()
        # Perp is the authoritative equity/positions venue; spot only carries
        # balances so its snapshot must not clear perp positions/equity.
        if venue == "perp":
            self.position_rows = list(rec["pos"]) if rec.get("pos") is not None else []
            eq = rec.get("eq")
            if isinstance(eq, (int, float)):
                self.equity = float(eq)
                if self.baseline_equity is None:
                    self.baseline_equity = float(eq)
        else:
            self.balance_rows = list(rec["bal"]) if rec.get("bal") is not None else []
        if rec.get("pnl") is not None:
            self.realized_pnl = float(rec["pnl"])

    def _event(self, rec: dict[str, Any]) -> None:
        venue = str(rec.get("venue", rec.get("mode", ""))).lower()
        market = self.perp if venue == "perp" else self.spot
        event = str(rec.get("event", "")).upper()
        symbol = str(rec.get("symbol", "?"))
        side = str(rec.get("side", "")).upper()
        price = str(rec.get("price", ""))
        qty = str(rec.get("qty", ""))
        oid = str(rec.get("order_id", ""))
        stamp = str(rec.get("t", ""))[11:19]

        if event == "ORDER_CONFIRMED" and side:
            market.place(side)
            self.activity.append(
                f"[{_side_color(side)}]{side} {symbol}[/] {qty}@{price}  oid={oid}  [dim]{stamp}[/]"
            )
        elif event == "CANCEL_CONFIRMED":
            market.cancelled_total += 1
            self.activity.append(f"[yellow]CANCEL {symbol}[/] oid={oid}  [dim]{stamp}[/]")
        elif event == "FILL":
            market.fills.append({"symbol": symbol, "side": side, "price": price,
                                 "qty": qty, "t": stamp})
            self.activity.append(f"[cyan]FILL {side} {symbol}[/] {qty}@{price}  [dim]{stamp}[/]")
        elif event:
            self.activity.append(f"[white]{event} {symbol}[/] {side} {qty}@{price}  [dim]{stamp}[/]")
        if len(self.activity) > 28:
            self.activity = self.activity[-28:]

    def tick(self) -> None:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as fh:
            # Start near the tail (tail -f semantics): on first open jump to a
            # bounded recent window so huge existing logs don't replay fully.
            if self._offset == 0:
                fh.seek(0, 2)
                size = fh.tell()
                if size > self._tail_bytes:
                    fh.seek(size - self._tail_bytes)
                    fh.readline()  # drop partial leading line
                else:
                    fh.seek(0)
            else:
                fh.seek(self._offset)
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    self.apply(line)
                except (json.JSONDecodeError, ValueError):
                    continue
            self._offset = fh.tell()


# --------------------------------------------------------------------------- #
# Rich rendering
# --------------------------------------------------------------------------- #


def _orders_table(market: MarketState, limit: int = 12) -> Any:
    from rich import box
    from rich.table import Table

    t = Table(box=box.SIMPLE, expand=True, pad_edge=False, show_edge=False)
    t.add_column("SYM", style="bold cyan")
    t.add_column("SIDE")
    t.add_column("QTY", justify="right", style="yellow")
    t.add_column("PRICE", justify="right", style="bold white")
    t.add_column("NOTIONAL", justify="right", style="magenta")
    t.add_column("OID", style="dim")
    for o in market.open_orders[:limit]:
        sym = str(o.get("symbol", "?"))
        side = str(o.get("side", "")).upper()
        px = str(o.get("price", ""))
        qt = str(o.get("quantity", o.get("qty", "")))
        try:
            notional = float(px) * float(qt)
        except (TypeError, ValueError):
            notional = 0.0
        t.add_row(sym, f"[{_side_color(side)}]{side}[/]", qt, px,
                  f"{notional:,.2f}", str(o.get("orderId", o.get("order_id", "")))[:10])
    if not market.open_orders:
        t.add_row("[dim]— no live orders —[/]", "", "", "", "", "")
    return t


def _markets_tbl(market: MarketState, limit: int = 10) -> Any:
    from rich import box
    from rich.table import Table

    t = Table(box=box.SIMPLE, expand=True, pad_edge=False, show_edge=False)
    t.add_column("SYM", style="bold cyan")
    t.add_column("BID", justify="right")
    t.add_column("ASK", justify="right")
    t.add_column("SPR %", justify="right")
    rows = sorted(market.markets, key=lambda r: float(r.get("spread", 0)), reverse=True)[:limit]
    for m in rows:
        sym = str(m.get("sym", "?"))
        spread = float(m.get("spread", 0))
        # min-spread gate default = 0.02% (0.0002 fraction)
        color = "bright_green" if spread >= 0.02 else ("yellow" if spread >= 0.01 else "bright_red")
        t.add_row(sym, str(m.get("bid", "")), str(m.get("ask", "")), f"[{color}]{spread:.3f}[/]")
    if not rows:
        t.add_row("[dim]awaiting scan…[/]", "", "", "")
    return t


def _venue_panel(label: str, subtitle: str, market: MarketState, border: str) -> Any:
    from rich.console import Group
    from rich.panel import Panel
    from rich.text import Text

    head = Text()
    head.append("SCANNED", style="bold white")
    head.append(f"  {len(market.markets)} symbols   ", style="dim")
    head.append("SPR≥0.02 = pass", style="dim")
    inner = Group(head, _markets_tbl(market, 6),
                  Text("OPEN ORDERS", style="bold white"),
                  _orders_table(market, 8))
    return Panel(
        inner,
        title=f"[bold]{label}[/] [dim]{subtitle}[/]",
        subtitle=f"[dim]{len(market.open_orders)} live[/]",
        border_style=border,
        padding=(0, 1),
    )


def _portfolio_band(view: ModeView) -> Any:
    """Compact one-row-ish PnL/portfolio summary with colored deltas."""
    from rich import box
    from rich.console import Group
    from rich.panel import Panel
    from rich.table import Table

    total_fills = view.perp.filled_est + view.spot.filled_est + len(view.perp.fills) + len(view.spot.fills)
    buys = view.perp.buy_count + view.spot.buy_count
    sells = view.perp.sell_count + view.spot.sell_count
    equity = view.equity
    baseline = view.baseline_equity or equity
    delta = equity - baseline
    delta_pct = (delta / baseline * 100) if baseline else 0.0
    dcol = "bright_green" if delta >= 0 else "bright_red"
    pnl = view.realized_pnl
    pcol = "bright_green" if pnl >= 0 else "bright_red"

    t = Table(box=box.SIMPLE, expand=True, pad_edge=False, show_edge=False)
    t.add_column("SYM", style="bold cyan")
    t.add_column("POS", justify="right")
    t.add_column("MARK", justify="right", style="magenta")
    t.add_column("EST VALUE", justify="right", style="white")
    for p in view.position_rows[:6]:
        amt = p.get("amt")
        mark = p.get("mark", "")
        try:
            value = float(amt) * float(mark) if amt is not None and mark else 0.0
        except (TypeError, ValueError):
            value = 0.0
        color = "bright_green" if float(amt or 0) >= 0 else "bright_red"
        t.add_row(str(p.get("sym", "?")), f"[{color}]{amt:+.6g}[/]", str(mark), f"{value:,.2f}")

    stat = Table(box=None, expand=True, show_header=False, pad_edge=False)
    stat.add_column(justify="left")
    stat.add_column(justify="right")
    stat.add_row(
        "[bold]EQUITY[/]",
        f"[bold white]$[/][bold]{equity:,.2f}[/]",
    )
    stat.add_row(
        "[bold]SESSION Δ[/]",
        f"[{dcol}]{delta:+,.2f} ({delta_pct:+.2f}%)[/]",
    )
    stat.add_row(
        "[bold]REALIZED PnL[/]",
        f"[{pcol}]{pnl:+,.2f}[/]",
    )
    stat.add_row(
        "[bold]TOTAL[/]",
        f"orders={view.perp.place_total + view.spot.place_total}  "
        f"fills≈{total_fills}  cancels={view.perp.cancelled_total + view.spot.cancelled_total}",
    )
    stat.add_row(
        "[bold]BUY / SELL[/]",
        f"[bright_green]{buys}▲[/]  [bright_red]{sells}▼[/]",
    )
    spot_txt = " ".join(f"[yellow]{b.get('asset')}[/]=[white]{b.get('free')}[/]"
                        for b in view.balance_rows) or "[dim]—[/]"
    stat.add_row("[bold]SPOT FREE[/]", spot_txt)

    return Panel(
        Group(t, stat),
        title=f"[bold]{view.label} PORTFOLIO · PnL · STATS[/]",
        border_style="blue",
        padding=(0, 1),
    )


def _activity(view: ModeView) -> Any:
    from rich import box
    from rich.table import Table

    t = Table(box=box.SIMPLE, expand=True, show_edge=False, pad_edge=False)
    t.add_column("", style="dim", width=8)
    t.add_column("ACTIVITY", no_wrap=False)
    for line in view.activity[-12:]:
        t.add_row("", line)
    if not view.activity:
        t.add_row("", "[dim]awaiting activity…[/]")
    return t


def _render(view: ModeView, hint: str) -> Any:
    from datetime import UTC, datetime

    from rich.console import Group
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    clock = datetime.now(UTC).strftime("%H:%M:%S")
    eq_color = "bright_green" if view.equity >= 0 else "bright_red"
    mode = view.label

    # Header tape (no Panel wrapper — rich Panel needs a real box)
    tabs = Text()
    if mode == "LIVE":
        tabs.append("● LIVE ", style="reverse bright_white")
        tabs.append(" DEMO  ", style="dim")
    else:
        tabs.append(" LIVE  ", style="dim")
        tabs.append("● DEMO ", style="reverse bright_white")

    head = Group(
        Text.assemble(
            ("  BINANCE ", "bold white"), ("MARKET MAKER", "bold"),
            ("   ·   ", "dim"),
            (f"{mode} MODE", "bold bright_yellow" if mode == "LIVE" else "bold bright_green"),
            ("   │   ", "dim"),
            (f"EQUITY ${view.equity:,.2f}", eq_color),
            ("   │   ", "dim"),
            (f"quote {view.quote}", "cyan"),
        ),
        Text.assemble(
            ("  ", ""), tabs,
            (f"   src={view.mode}    file={view.path.name}    clock {clock} UTC", "dim"),
        ),
    )

    perp = _venue_panel("USDT-M PERP", "futures", view.perp, "bright_magenta")
    spot = _venue_panel("SPOT", "trading", view.spot, "bright_cyan")
    two_col = Table(box=None, expand=True, show_header=False, pad_edge=False)
    two_col.add_column(ratio=1)
    two_col.add_column(ratio=1)
    two_col.add_row(perp, spot)

    body = Group(head, two_col, _portfolio_band(view), Text("  "), _activity(view))
    return Panel(body, border_style="dim", padding=(1, 1))


# --------------------------------------------------------------------------- #
# Controller: tails both modes, arrow-key switches the active view
# --------------------------------------------------------------------------- #


class Dashboard:
    def __init__(self, live_path: Path, demo_path: Path, start: str = "live",
                 sleep_s: float = 1.0) -> None:
        self.views = {
            "LIVE": ModeView("LIVE", live_path),
            "DEMO": ModeView("DEMO", demo_path),
        }
        self.active = "LIVE" if start.lower() == "live" else "DEMO"
        self.sleep_s = sleep_s
        self._key_holder: threading.Event = threading.Event()
        self._current: list[str] = [self.active]

    def _input_thread(self) -> None:
        import sys

        if sys.platform == "win32":
            self._windows_input()
            return
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
                    if seq == "[C":
                        self.active = "DEMO"
                    elif seq == "[D":
                        self.active = "LIVE"
                elif ch in ("l", "L"):
                    self.active = "LIVE"
                elif ch in ("d", "D"):
                    self.active = "DEMO"
                elif ch in ("q", "Q"):
                    break
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    def _windows_input(self) -> None:
        import msvcrt

        while True:
            ch = msvcrt.getwch()
            if ch in ("\x00", "\xe0"):  # arrow/function key prefix
                arrow = msvcrt.getwch()
                if arrow == "M":       # Right
                    self.active = "DEMO"
                elif arrow == "K":     # Left
                    self.active = "LIVE"
            elif ch in ("l", "L"):
                self.active = "LIVE"
            elif ch in ("d", "D"):
                self.active = "DEMO"
            elif ch in ("q", "Q"):
                break

    def run(self) -> None:
        from rich.console import Console
        from rich.live import Live

        for v in self.views.values():
            v.path.parent.mkdir(parents=True, exist_ok=True)
            v.path.touch(exist_ok=True)
        # best-effort keyboard input; falls back to file-free defaults if no tty
        t = threading.Thread(target=self._input_thread, daemon=True)
        self._input_error: str | None = None
        try:
            t.start()
        except Exception as exc:  # noqa: BLE001
            self._input_error = str(exc)  # keyboard nav unavailable; view still works
        with Live(console=Console(), refresh_per_second=2, screen=True) as live:
            while True:
                for v in self.views.values():
                    v.tick()
                active = self.views[self.active]
                hint = (f"LIVE = [green]{self.views['LIVE'].path.name}[/]  DEMO = "
                        f"[yellow]{self.views['DEMO'].path.name}[/]  |  ←/→ switch, q quit")
                live.update(_render(active, hint))
                time.sleep(self.sleep_s)


def run_watch(live_path: str | Path, demo_path: str | Path, start: str = "live",
              sleep_s: float = 1.0) -> None:
    Dashboard(Path(live_path), Path(demo_path), start, sleep_s).run()