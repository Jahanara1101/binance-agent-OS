import json
import sys
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

    def call(tool, arguments):
        return ctx.call_mcp("binance", tool, arguments, timeout=120)

    def setup(subparser):
        subparser.add_argument("action", choices=["status", "account", "positions", "orders"])
        subparser.add_argument("--symbol")

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
        print(json.dumps(handlers[args.action](), indent=2, default=str))
        return 0

    ctx.register_cli_command(
        "binance-agent-os",
        "Use Binance Agent OS OAuth MCP for account and execution state",
        setup,
        handle,
        description="Binance Agent OS liquidity agent",
    )
