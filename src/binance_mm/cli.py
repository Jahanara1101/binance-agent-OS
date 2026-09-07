import argparse
import asyncio
import signal
import time
from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.live import Live

from .binance import BinanceClient, parse_books, parse_markets
from .models import Book, Order
from .paper import PaperBroker
from .paths import demo_log, live_log
from .state import Fill, InventoryBook
from .strategy import bollinger_bandwidth, is_volatile, select_markets, size_quotes
from .watch import WatchLog


@dataclass
class Stats:
    cycles: int = 0
    placed: int = 0
    cancelled: int = 0
    fills: int = 0
    errors: int = 0
    events: deque[str] = field(default_factory=lambda: deque(maxlen=16))
    fill_events: deque[str] = field(default_factory=lambda: deque(maxlen=12))


class Agent:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.stats = Stats()
        self.running = True
        self.client = BinanceClient()
        self.paper = PaperBroker(Decimal(str(args.paper_equity)))
        self.active: dict[int, Order] = {}
        self.inventory = InventoryBook()
        self.log = WatchLog(args.log_file)
        self.market_count = 0
        self.eligible_count = 0
        self.last_scan = 0.0
        self.markets = []
        self.feed = None


    def stop(self, *_: object) -> None:
        self.running = False

    async def scan(self) -> tuple[dict, dict]:
        exchange_info, ticker_data, book_data = await asyncio.gather(
            self.client.exchange_info(), self.client.ticker_24h(), self.client.book_tickers()
        )
        all_markets = parse_markets(exchange_info, ticker_data)
        self.market_count = len(all_markets)
        markets = select_markets(all_markets, self.args.quote, Decimal(str(self.args.min_volume)))
        books = parse_books(book_data)
        if self.args.strategy == "volatile":
            semaphore = asyncio.Semaphore(10)

            async def check(m):
                async with semaphore:
                    raw = await self.client.klines(m.symbol, "5m", 220)
                    closes = [Decimal(str(row[4])) for row in raw]
                    widths = bollinger_bandwidth(closes, 20, Decimal(2))
                    return m if is_volatile(widths, Decimal("0.8"), 200) else None

            markets = [m for m in await asyncio.gather(*(check(m) for m in markets)) if m]
        self.markets = markets
        self.eligible_count = len(markets)
        return {m.symbol: m for m in markets}, books

    def render(self) -> Any:
        """Full-screen demo terminal: colored header band + two-column live view
        (orderbook | fills/portfolio). Colors via rich markup (from_markup), so
        they actually render instead of printing literal [tags]."""
        from datetime import UTC, datetime

        from rich.columns import Columns
        from rich.console import Group
        from rich.panel import Panel
        from rich.text import Text

        clock = datetime.now(UTC).strftime("%H:%M:%S")
        feed_state = ("● live" if self.feed and self.feed.connected
                      else "○ connecting" if not (self.feed and self.feed.error)
                      else "● reconnect")
        equity = float(self.args.paper_equity)
        eq_txt = f"${equity:,.2f}"
        eq_style = "bold black on bright_green" if equity >= 0 else "white on bright_red"

        # ---------- top header band (full width, colored background) ----------
        head = Text.assemble(
            ("  BINANCE MARKET MAKER", "bold white on bright_blue"),
            ("  · DEMO  ", "white on bright_blue"),
            ("EQUITY ", "white on bright_blue"),
            (eq_txt, eq_style),
            (f"   {self.eligible_count} mkts   ", "white on bright_blue"),
            (feed_state, "bold white on bright_blue"),
            ((f"   placed {self.stats.placed}   canc {self.stats.cancelled}   "
              f"fills {self.stats.fills}   open {len(self.active)}"), "white on bright_blue"),
            (f"      {clock} UTC", "white on bright_blue"),
        )

        # ---------- left panel: live orderbook ----------
        rows = self.feed.snapshot() if self.feed else []
        rows.sort(key=lambda r: -r["spread"])
        left_lines = [f"  [bold white]LIVE ORDERBOOK[/]  [dim]{self.eligible_count} symbols · spread %[/]"]
        if rows:
            for r in rows[:40]:
                spread = r["spread"]
                color = ("bright_green" if spread >= 0.02
                         else "yellow" if spread >= 0.01 else "bright_red")
                left_lines.append(
                    f"  {r['sym']:<13} [white]{r['bid']:>11.6g} {r['ask']:>11.6g}[/]"
                    f"   [{color}]{spread:>6.4f}%[/]"
                )
        else:
            left_lines.append("  connecting to live orderbook…")
        left_txt = Text.from_markup("\n".join(left_lines), emoji=False)
        left_panel = Panel(left_txt, border_style="bright_blue",
                           title="[bold]MARKETS[/]",
                           subtitle="[dim]highest spread first[/]", padding=(0, 1))

        # ---------- right panel: fills + trade tape + portfolio ----------
        right_lines = ["  [bold white]TRADE TAPE[/]"]
        for ev in list(self.stats.fill_events)[-6:]:
            right_lines.append("  [bright_cyan]FILL[/]  " + ev)
        for ev in list(self.stats.events)[-10:]:
            tag, _, rest = ev.partition(" ")
            if tag.startswith("QUOTE"):
                style = "bright_green" if " BUY " in ev else "bright_red"
                mark = "▲ BUY" if " BUY " in ev else "▼ SELL"
                right_lines.append(f"  [{style}]{mark}[/] " + rest)
            elif tag == "CANCEL":
                right_lines.append("  [yellow]CANCEL[/] " + rest)
            else:
                right_lines.append("  " + ev)
        right_lines.append("")
        right_lines.append("  [bold white]PORTFOLIO[/]")
        right_lines.append("  EQUITY  [bold]$" + f"{equity:,.2f}[/]")
        if self.inventory._net:
            for sym, net in list(self.inventory._net.items())[:8]:
                style = "bright_green" if net >= 0 else "bright_red"
                right_lines.append(f"  {sym:<12} [{style}]{net:+.4g}[/]")
        else:
            right_lines.append("  (no open positions)")
        right_txt = Text.from_markup("\n".join(right_lines), emoji=False)
        right_panel = Panel(right_txt, border_style="bright_green",
                            title="[bold]ACTIVITY[/]", padding=(0, 1))

        columns = Columns([left_panel, right_panel], equal=True, expand=True)
        return Group(head, columns)


    async def cancel_all(self) -> None:
        for order_id, order in list(self.active.items()):
            try:
                if self.args.environment == "paper":
                    self.paper.cancel(order_id)
                else:
                    raise RuntimeError("Authenticated cancels must run through the Binance Agent OS plugin")
                self.inventory.forget(order_id)
                self.stats.cancelled += 1
                self.stats.events.append(f"CANCEL {order.symbol} {order.side.value} #{order_id}")
                self.log.event("CANCEL_CONFIRMED", venue="perp", symbol=order.symbol,
                               side=order.side.value, price=str(order.price),
                               qty=str(order.quantity), order_id=str(order_id))
            except (RuntimeError, ValueError, OSError) as exc:
                self.stats.errors += 1
                self.stats.events.append(f"CANCEL_ERR {order.symbol}: {exc}")
            finally:
                self.active.pop(order_id, None)

    async def place_orders(self, orders: list[Order]) -> None:
        for order in orders:
            try:
                if self.args.environment == "paper":
                    order_id = self.paper.place(order)
                else:
                    raise RuntimeError("Authenticated orders must run through the Binance Agent OS plugin")
                self.active[order_id] = order
                self.inventory.track(order_id, order)
                self.stats.placed += 1
                tag = "EXIT" if order.reduce_only else "QUOTE"
                self.stats.events.append(
                    f"{tag} {order.symbol} {order.side.value} {order.quantity}@{order.price} #{order_id}"
                )
                self.log.event("ORDER_CONFIRMED", venue="perp", symbol=order.symbol,
                               side=order.side.value, price=str(order.price),
                               qty=str(order.quantity), order_id=str(order_id))
            except (RuntimeError, ValueError, OSError) as exc:
                self.stats.errors += 1
                self.stats.events.append(f"PLACE_ERR {order.symbol}: {exc}")

    def _emit_snapshot(self, books: dict[str, Book]) -> None:
        od = []
        for order_id, order in self.active.items():
            od.append({"orderId": order_id, "symbol": order.symbol,
                       "side": order.side.value, "price": str(order.price),
                       "quantity": str(order.quantity)})
        pos = []
        for sym, net in self.inventory._net.items():
            book = books.get(sym)
            mark = str(book.mid) if book else ""
            pos.append({"sym": sym, "amt": float(net), "mark": mark})
        mkts = []
        for market in self.markets:
            book = books.get(market.symbol)
            if book:
                mkts.append({"sym": market.symbol, "bid": str(book.bid),
                             "ask": str(book.ask),
                             "spread": f"{book.spread_fraction * Decimal(100):.3f}"})
        self.log.snapshot(
            venue="perp", src="demo", quote=self.args.quote, eq=float(self.args.paper_equity),
            od=od, pos=pos, bal=[], pnl=0.0, mkts=mkts,
        )

    async def run(self) -> None:
        if self.args.environment == "agent-os":
            raise RuntimeError(
                "Start authenticated execution through Hermes: hermes binance-agent-os status. "
                "The standalone scanner cannot bypass Binance Agent OS OAuth confirmations."
            )
        with Live(self.render(), console=Console(), refresh_per_second=8, screen=True) as live:
            try:
                while self.running:
                    started = time.monotonic()
                    _market_map, books = await self.scan()
                    if self.feed is None and self.markets:
                        from .feeds import BookFeed

                        self.feed = BookFeed([m.symbol for m in self.markets])
                        self.feed.start()
                    if self.args.environment == "paper":
                        for fill in self.paper.match(books):
                            self.stats.fills += 1
                            self.stats.fill_events.append(
                                f"{fill.symbol} {fill.side.value} {fill.quantity}@{fill.price} #{fill.order_id}"
                            )
                            self.log.event("FILL", venue="perp", symbol=fill.symbol,
                                           side=fill.side.value, price=str(fill.price),
                                           qty=str(fill.quantity), order_id=str(fill.order_id))
                            self.active.pop(fill.order_id, None)
                            sibling_ids = self.inventory.apply_fill(
                                Fill(fill.order_id, fill.symbol, fill.side, fill.quantity, fill.price)
                            )
                            for sibling_id in sibling_ids:
                                sibling = self.active.get(sibling_id)
                                if sibling:
                                    self.paper.cancel(sibling_id)
                                    self.active.pop(sibling_id, None)
                                    self.inventory.forget(sibling_id)
                                    self.stats.cancelled += 1
                                    self.stats.events.append(
                                        f"SIBLING_CANCEL {sibling.symbol} {sibling.side.value} #{sibling_id}"
                                    )
                    await self.cancel_all()
                    available = max(0, self.args.max_orders - len(self.active))
                    exits = [
                        exit_order
                        for market in self.markets
                        if market.symbol in books
                        and (exit_order := self.inventory.exit_order(market, books[market.symbol])) is not None
                    ]
                    await self.place_orders(exits[:available])
                    available = max(0, self.args.max_orders - len(self.active))
                    exposed = {market.symbol for market in self.markets if self.inventory.position(market.symbol)}
                    candidates = [m for m in self.markets if m.symbol not in exposed]
                    spread_ok = [m for m in candidates if m.symbol in books and books[m.symbol].spread_fraction >= Decimal(str(self.args.min_spread))]
                    orders = size_quotes(
                        spread_ok,
                        books,
                        Decimal(str(self.args.paper_equity)),
                        Decimal(str(self.args.margin_fraction)),
                        self.args.leverage,
                        available,
                    )
                    await self.place_orders(orders)
                    self.stats.cycles += 1
                    self._emit_snapshot(books)
                    live.update(self.render())
                    await asyncio.sleep(max(0.05, self.args.refresh - (time.monotonic() - started)))
            finally:
                await self.cancel_all()
                await self.client.close()
                self.log.close()
                if self.feed:
                    self.feed.stop()


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Binance USD-M perpetual liquidity agent")
    p.add_argument("--environment", choices=["agent-os", "paper"], default="agent-os")
    p.add_argument("--strategy", choices=["normal", "volatile"], default="normal")
    p.add_argument("--quote", choices=["USDT", "USDC"], default="USDT")
    p.add_argument("--min-volume", type=Decimal, default=Decimal(10000000))
    p.add_argument("--min-spread", type=Decimal, default=Decimal("0.0002"))
    p.add_argument("--refresh", type=float, default=1.0)
    p.add_argument("--max-orders", type=int, default=30)
    p.add_argument("--margin-fraction", type=Decimal, default=Decimal("0.01"))
    p.add_argument("--leverage", type=int, default=2)
    p.add_argument("--paper-equity", type=Decimal, default=Decimal(10000))
    p.add_argument(
        "--log-file",
        type=str,
        default=str(demo_log()),
    )

    return p


def _run_bot(args) -> None:
    agent = Agent(args)
    signal.signal(signal.SIGINT, agent.stop)
    signal.signal(signal.SIGTERM, agent.stop)
    asyncio.run(agent.run())


def main() -> None:
    import sys

    argv = sys.argv[1:]

    # --- subcommand dispatch (simple for public users) -------------------- #
    if argv and argv[0] == "watch":
        start = "live"
        live = live_log()
        demo = demo_log()
        i = 1
        while i < len(argv):
            if argv[i] == "--live" and i + 1 < len(argv):
                live = Path(argv[i + 1]); i += 2
            elif argv[i] == "--demo" and i + 1 < len(argv):
                demo = Path(argv[i + 1]); i += 2
            elif argv[i] == "--mode" and i + 1 < len(argv):
                start = argv[i + 1]; i += 2
            else:
                i += 1
        from .watch import run_watch

        run_watch(live_path=live, demo_path=demo, start=start)
        return

    if argv and argv[0] == "live":
        log = demo_log()
        i = 1
        while i < len(argv):
            if argv[i] == "--log" and i + 1 < len(argv):
                log = Path(argv[i + 1]); i += 2
            else:
                i += 1
        from .live import run_live

        run_live(log)
        return

    # `demo` / bare `binance-mm` => paper (demo) bot, sensible defaults.
    if argv and argv[0] in ("demo", "paper"):
        argv = argv[1:]
    elif argv and argv[0].startswith("-"):
        pass  # legacy: bare flags only
    else:
        argv = []  # bare `binance-mm` == demo

    sys.argv = [sys.argv[0]] + argv
    args = parser().parse_args()
    if args.environment == "agent-os":
        args.environment = "paper"
        args.log_file = str(demo_log())
    _run_bot(args)


if __name__ == "__main__":
    main()
