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
    from binance_mm.binance import BinanceMarketDataClient, parse_books, parse_markets
    from binance_mm.strategy import select_markets

    def call(tool, arguments):
        return ctx.call_mcp("binance", tool, arguments, timeout=120)

    def setup(subparser):
        subparser.add_argument("action", choices=["status", "account", "positions", "orders", "run"])
        subparser.add_argument("--symbol")
        subparser.add_argument("--quote", choices=["USDT", "USDC"], default="USDT")
        subparser.add_argument("--strategy", choices=["normal", "volatile"], default="normal")
        subparser.add_argument("--min-volume", type=Decimal, default=Decimal(10000000))
        subparser.add_argument("--min-spread", type=Decimal, default=Decimal("0.0002"))
        subparser.add_argument("--max-orders", type=int, default=30)
        subparser.add_argument("--refresh", type=int, default=3)
        subparser.add_argument("--cycles", type=int, default=1)

    async def run_cycles(args, executor):
        market_data = BinanceMarketDataClient()
        runner = AgentOSRunner(
            executor,
            refresh_seconds=args.refresh,
            max_orders=args.max_orders,
            min_spread=args.min_spread,
        )
        try:
            for cycle_index in range(args.cycles):
                info = await market_data.exchange_info()
                tickers = await market_data.ticker_24h()
                books = parse_books(await market_data.book_tickers())
                markets = select_markets(parse_markets(info, tickers), args.quote, args.min_volume)
                started = time.monotonic()
                print(
                    f"SCAN cycle={cycle_index + 1}/{args.cycles} quote={args.quote} "
                    f"eligible={len(markets)} spread>={args.min_spread} execution=BINANCE_AGENT_OS_MCP",
                    flush=True,
                )
                result = runner.cycle(markets, books, int(time.time() * 1000))
                for row in result.cancelled:
                    print(f"CANCEL_CONFIRMED {json.dumps(row, default=str)}", flush=True)
                for row in result.placed:
                    print(f"ORDER_CONFIRMED {json.dumps(row, default=str)}", flush=True)
                positions = executor.positions()
                for row in positions:
                    if Decimal(str(row.get("positionAmt", "0"))):
                        print(f"FILL_OR_POSITION {json.dumps(row, default=str)}", flush=True)
                print(
                    f"CYCLE_DONE placed={len(result.placed)} cancelled={len(result.cancelled)} "
                    f"confirmations={result.awaiting_confirmations} elapsed={time.monotonic() - started:.2f}s",
                    flush=True,
                )
                if cycle_index + 1 < args.cycles:
                    time.sleep(args.refresh)
        finally:
            await market_data.close()

    def handle(args):
        executor = AgentOSExecutor(call)
        handlers = {
            "account": executor.account,
            "positions": lambda: executor.positions(args.symbol),
            "orders": lambda: executor.open_orders(args.symbol),
            "status": lambda: {
                "execution": "Binance Agent OS OAuth MCP",
                "server": "binance",
                "credentials": "OAuth token managed by Hermes; no API key/secret",
            },
        }
        if args.action == "run":
            import asyncio

            asyncio.run(run_cycles(args, executor))
        else:
            print(json.dumps(handlers[args.action](), indent=2, default=str))
        return 0

    ctx.register_cli_command(
        "binance-agent-os",
        "Run the Binance Agent OS OAuth MCP liquidity workflow",
        setup,
        handle,
        description="Binance Agent OS liquidity agent",
    )
