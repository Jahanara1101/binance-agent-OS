import json
import sys
import time
from decimal import Decimal
from pathlib import Path

def _project_root() -> Path:
    installed = Path(__file__).resolve().parent
    candidates = [installed, Path.cwd(), installed.parents[2] / "binance-agent-market-maker"]
    for root in candidates:
        if (root / "src" / "binance_mm" / "agent_os.py").exists():
            return root
    raise RuntimeError("Clone binance-agent-OS and run Hermes from the repository directory")


def register(ctx):
    src = _project_root() / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))

    from binance_mm.agent_os import AgentOSExecutor
    from binance_mm.agent_os_runner import AgentOSRunner
    from binance_mm.binance import (
        BinanceMarketDataClient,
        BinanceSpotMarketDataClient,
        parse_books,
        parse_markets,
    )
    from binance_mm.spot_runner import SpotRunner
    from binance_mm.strategy import bollinger_bandwidth, is_volatile, select_markets

    def call(tool, arguments):
        return ctx.call_mcp("binance", tool, arguments, timeout=120)

    def setup(subparser):
        subparser.add_argument(
            "action",
            choices=["status", "account", "positions", "orders",
                     "run-perp", "run-spot", "run-both", "watch"],
        )
        subparser.add_argument("--symbol")
        subparser.add_argument("--quote", choices=["USDT", "USDC"], default="USDT")
        subparser.add_argument("--strategy", choices=["normal", "volatile"], default="normal")
        subparser.add_argument("--min-volume", type=Decimal, default=Decimal(10000000))
        subparser.add_argument("--min-spread", type=Decimal, default=Decimal("0.0002"))
        subparser.add_argument("--max-orders", type=int, default=30)
        subparser.add_argument("--refresh", type=int, default=3)
        subparser.add_argument("--cycles", type=int, default=1)

    async def market_snapshot(client, args, kind):
        info = await client.exchange_info()
        tickers = await client.ticker_24h()
        books = parse_books(await client.book_tickers())
        markets = select_markets(parse_markets(info, tickers), args.quote, args.min_volume)
        expected_type = "PERPETUAL" if kind == "perp" else "SPOT"
        markets = [m for m in markets if m.contract_type == expected_type]
        if args.strategy == "volatile":
            selected = []
            for market in markets:
                raw = await client.klines(market.symbol, "5m", 220)
                widths = bollinger_bandwidth([Decimal(str(row[4])) for row in raw], 20, Decimal(2))
                if is_volatile(widths, Decimal("0.8"), 200):
                    selected.append(market)
            markets = selected
        return markets, books

    def print_result(kind, result, executor, log, markets, books):
        for row in result.cancelled:
            print(f"{kind.upper()} CANCEL_CONFIRMED {json.dumps(row, default=str)}", flush=True)
            log.event("CANCEL_CONFIRMED", venue=kind, symbol=str(row.get("symbol", "?")),
                      order_id=str(row.get("orderId", row.get("order_id", ""))))
        for row in result.placed:
            print(f"{kind.upper()} ORDER_CONFIRMED {json.dumps(row, default=str)}", flush=True)
            log.event(
                "ORDER_CONFIRMED", venue=kind, symbol=str(row.get("symbol", "?")),
                side=str(row.get("side", "")).upper(),
                price=str(row.get("price", row.get("orderPrice", ""))),
                qty=str(row.get("quantity", row.get("origQty", ""))),
                order_id=str(row.get("orderId", row.get("order_id", ""))),
            )
        positions = executor.positions() if kind == "perp" else []
        for row in positions:
            if Decimal(str(row.get("positionAmt", "0"))):
                print(f"PERP FILL_OR_POSITION {json.dumps(row, default=str)}", flush=True)
        print(
            f"{kind.upper()} CYCLE_DONE placed={len(result.placed)} cancelled={len(result.cancelled)} "
            f"confirmations={result.awaiting_confirmations}",
            flush=True,
        )
        _emit_snapshot(kind, executor, log, markets, books)

    def _emit_snapshot(kind, executor, log, markets, books):
        mkts = []
        for m in markets:
            b = books.get(m.symbol)
            if b:
                spread = b.spread_fraction * Decimal(100)
                mkts.append({"sym": m.symbol, "bid": str(b.bid), "ask": str(b.ask),
                             "spread": f"{spread:.3f}"})
        if kind == "perp":
            od = executor.open_orders()
            pos = []
            for row in executor.positions():
                amt = Decimal(str(row.get("positionAmt", "0")))
                if amt:
                    pos.append({"sym": str(row["symbol"]), "amt": float(amt),
                                "mark": str(row.get("markPrice", ""))})
            bal = []
            eq_num = executor.account().get("totalMarginBalance", 0)
        else:
            od = executor.spot_open_orders()
            pos = []
            account = executor.spot_account()
            bal = [{"asset": str(r.get("asset")), "free": str(r.get("free", "0"))}
                   for r in account.get("balances", [])]
            eq_num = 0.0
            for r in account.get("balances", []):
                if str(r.get("asset", "")).upper() == "USDT":
                    try:
                        eq_num = float(r.get("free", 0))
                    except (TypeError, ValueError):
                        eq_num = 0.0
                    break
        log.snapshot(venue=kind, src="live", quote="USDT", eq=float(eq_num),
                     od=od, pos=pos, bal=bal, pnl=0.0, mkts=mkts)

    async def run_cycles(args, executor, kinds):
        from binance_mm.watch import WatchLog

        root = _project_root()
        log = WatchLog(root / "logs" / "live.jsonl")
        clients = {
            "perp": BinanceMarketDataClient(),
            "spot": BinanceSpotMarketDataClient(),
        }
        runners = {
            "perp": AgentOSRunner(executor, args.refresh, args.max_orders, min_spread=args.min_spread),
            "spot": SpotRunner(executor, args.refresh, args.max_orders, min_spread=args.min_spread),
        }
        try:
            for cycle_index in range(args.cycles):
                started = time.monotonic()
                for kind in kinds:
                    markets, books = await market_snapshot(clients[kind], args, kind)
                    print(
                        f"{kind.upper()} SCAN cycle={cycle_index + 1}/{args.cycles} quote={args.quote} "
                        f"eligible={len(markets)} open_cap={args.max_orders} execution=BINANCE_AGENT_OS_MCP",
                        flush=True,
                    )
                    result = runners[kind].cycle(markets, books, int(time.time() * 1000))
                    print_result(kind, result, executor, log, markets, books)
                print(f"ALL_SELECTED_DONE elapsed={time.monotonic() - started:.2f}s", flush=True)
                if cycle_index + 1 < args.cycles:
                    time.sleep(args.refresh)
        finally:
            for client in clients.values():
                await client.close()
            log.close()

    def handle(args):
        executor = AgentOSExecutor(call)
        handlers = {
            "account": executor.account,
            "positions": lambda: executor.positions(args.symbol),
            "orders": lambda: executor.open_orders(args.symbol),
            "status": lambda: {
                "execution": "Binance Agent OS OAuth MCP",
                "markets": ["USD-M perpetuals", "spot"],
                "separate_open_order_cap": getattr(args, "max_orders", 30),
                "credentials": "OAuth token managed by Hermes; no API key/secret",
            },
        }
        run_map = {"run-perp": ("perp",), "run-spot": ("spot",), "run-both": ("perp", "spot")}
        if args.action == "watch":
            from binance_mm.watch import run_watch

            root = _project_root()
            run_watch(live_path=root / "logs" / "live.jsonl",
                      demo_path=root / "logs" / "demo.jsonl", start="live")
        elif args.action in run_map:
            import asyncio

            asyncio.run(run_cycles(args, executor, run_map[args.action]))
        else:
            print(json.dumps(handlers[args.action](), indent=2, default=str))
        return 0

    ctx.register_cli_command(
        "binance-agent-os",
        "Run Binance Agent OS OAuth MCP spot/perpetual liquidity workflows",
        setup,
        handle,
        description="Binance Agent OS spot and perpetual liquidity agent",
    )
