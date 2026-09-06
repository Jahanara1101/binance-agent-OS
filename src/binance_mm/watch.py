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
        market.open_orders = list(rec.get("od", []))
        market.mark_open({str(o.get("orderId", o.get("order_id", ""))) for o in market.open_orders})
        if rec.get("quote"):
            self.quote = str(rec["quote"])
        self.mode = str(rec.get("src", self.mode)).lower()
        eq = rec.get("eq")
        if isinstance(eq, (int, float)):
            self.equity = float(eq)
            if self.baseline_equity is None:
                self.baseline_equity = float(eq)
        if rec.get("pos") is not None:
            self.position_rows = list(rec["pos"])
        if rec.get("bal") is not None:
            self.balance_rows = list(rec["bal"])
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


def _table(venue_name: str, market: MarketState) -> Any:
    from rich.table import Table

    t = Table(title=f"{venue_name} OPEN ORDERS", box=None, expand=True)
    t.add_column("SYM", style="bold cyan")
    t.add_column("SIDE")
    t.add_column("QTY", justify="right")
    t.add_column("PRICE", justify="right")
    t.add_column("NOTIONAL", justify="right")
    t.add_column("OID", style="dim")
    for o in market.open_orders[:30]:
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
        t.add_row("[dim]— none —[/]", "", "", "", "", "")
    return t


def _portfolio(view: ModeView) -> Any:
    from rich.console import Group
    from rich.panel import Panel
    from rich.table import Table

    t = Table(box=None, expand=True, pad_edge=False)
    t.add_column("SYM", style="bold cyan")
    t.add_column("POS", justify="right")
    t.add_column("MARK", justify="right", style="magenta")
    t.add_column("EST VALUE", justify="right")
    for p in view.position_rows:
        amt = p.get("amt")
        mark = p.get("mark", "")
        try:
            value = float(amt) * float(mark) if amt is not None and mark else 0.0
        except (TypeError, ValueError):
            value = 0.0
        color = "green" if float(amt or 0) >= 0 else "red"
        t.add_row(str(p.get("sym", "?")), f"[{color}]{amt:+.6g}[/]", str(mark), f"{value:,.2f}")

    total_fills = view.perp.filled_est + view.spot.filled_est + len(view.perp.fills) + len(view.spot.fills)
    pnl_color = "green" if view.realized_pnl >= 0 else "red"
    spot_free = ", ".join(f"{b.get('asset')}={b.get('free')}" for b in view.balance_rows)
    pnl_line = (f"[bold]REALIZED PnL[/] [{pnl_color}]{view.realized_pnl:+,.2f}[/]   "
                f"fills(est)={total_fills}   buys={view.perp.buy_count + view.spot.buy_count}  "
                f"sells={view.perp.sell_count + view.spot.sell_count}")
    return Panel(
        Group(t, f"[bold]EQUITY[/] [green]${view.equity:,.2f}[/]", pnl_line,
              "[dim]spot free:[/] " + (spot_free or "[dim]spot none[/]")),
        title=f"[bold]{view.label} PORTFOLIO / PnL[/]", border_style="blue")


def _activity(view: ModeView) -> Any:
    from rich.panel import Panel

    body = "\n".join(view.activity[-16:]) if view.activity else "[dim]awaiting activity…[/]"
    return Panel(body, title="[bold]ACTIVITY LOG[/]", border_style="green")


def _render(view: ModeView, hint: str) -> Any:
    from rich.console import Group
    from rich.panel import Panel

    eq_color = "green" if view.equity >= 0 else "red"
    header = Panel(
        f"[bold white]BINANCE MARKET MAKER — {view.label} MODE[/]\n"
        f"src={view.mode}  quote={view.quote}  "
        f"equity=[{eq_color}]${view.equity:,.2f}[/]  "
        f"last=[dim]{view.last_t} UTC[/]  file=[dim]{view.path.name}[/]\n[dim]{hint}[/]",
        title="[bold]DASHBOARD[/]", border_style="bright_blue",
    )
    return Group(header,
                 _table("PERP", view.perp),
                 _table("SPOT", view.spot),
                 _portfolio(view),
                 _activity(view))


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
                if ch in ("\x1b",):  # could be escape sequence; read arrows
                    seq = sys.stdin.read(2)
                    if seq == "[C":      # Right
                        self.active = "DEMO"
                    elif seq == "[D":    # Left
                        self.active = "LIVE"
                elif ch in ("l", "L"):
                    self.active = "LIVE"
                elif ch in ("d", "D"):
                    self.active = "DEMO"
                elif ch in ("q", "Q"):
                    break
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

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