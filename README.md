# Binance Agent Market Maker

A terminal-first Binance USD-M perpetual liquidity agent. It scans every perpetual market, filters by quote asset and 24-hour quote volume, and posts two-sided maker quotes only when the visible spread is at least the configured threshold.

Warning: market making can lose money through adverse selection, taker exits, fees, funding, API latency, and liquidation. Paper mode is the default. Demo mode uses separate Binance Futures Demo credentials. Live mode is locked behind an explicit flag.

## Strategy

Defaults:

- Environment: `paper`
- Quote asset: `USDT` (`USDC` supported)
- Minimum 24-hour quote volume: `10,000,000`
- Entry spread: `0.02%` (`0.0002` as a fraction)
- Quote lifetime: `3 seconds`
- Maximum open orders: `30`
- Total margin allocation: `1%` of equity across all entry orders
- Leverage: `2x`
- Order type: post-only limit (`GTX`) in demo/live

Modes:

- `normal`: quote every eligible market whose spread passes the gate.
- `volatile`: additionally require 5-minute Bollinger Band Width, BB(20,2), to be above the rolling 80th percentile of the latest 200 bandwidth observations.

Fill behavior:

1. Detect a fill.
2. Cancel the sibling quote.
3. Stop creating fresh exposure on that symbol.
4. Place an opposite, reduce-only maker exit.
5. Refresh that exit every 3 seconds, even if spread is below 0.02%.
6. Resume normal quoting only after inventory is flat.

## Install

Requires Python 3.11+ and `uv`.

    git clone https://github.com/ItzJulkar/binance-agent-market-maker.git
    cd binance-agent-market-maker
    uv sync --extra dev

## Commands

Paper mode with live Binance market data and simulated orders:

    uv run binance-mm

Normal USDT mode explicitly:

    uv run binance-mm --environment paper --strategy normal --quote USDT

USDC perpetuals:

    uv run binance-mm --environment paper --strategy normal --quote USDC

Volatile-only mode:

    uv run binance-mm --environment paper --strategy volatile --quote USDT

Change spread, volume floor, refresh time, allocation, leverage, or cap:

    uv run binance-mm --min-spread 0.0003 --min-volume 20000000 --refresh 3 --margin-fraction 0.01 --leverage 2 --max-orders 30

Use a different virtual equity in paper mode:

    uv run binance-mm --paper-equity 25000

The terminal dashboard separates order/cancel activity from fills and shows the environment, strategy, quote asset, eligible market count, open-order count, and error totals.

## Binance Agent OS connection

Hermes can connect through Binance OAuth without receiving your Binance password or API secret:

    hermes mcp add binance --url https://agent.binance.com/mcp/agentic --auth oauth
    hermes mcp test binance

The Agent OS MCP is useful for the hackathon demonstration and permissioned account actions. Binance requires user confirmation for write actions, so it is not appropriate for autonomous 3-second cancel/requote execution. The autonomous demo/live runners below use Binance's official Futures API instead.

## Futures Demo mode

Create Futures Demo credentials from Binance's demo environment. These are separate from your main-account credentials. Never commit them.

Git Bash/macOS/Linux:

    export BINANCE_API_KEY='demo-key'
    export BINANCE_API_SECRET='demo-secret'
    uv run binance-mm --environment demo --strategy normal --quote USDT

Windows PowerShell:

    $env:BINANCE_API_KEY='demo-key'
    $env:BINANCE_API_SECRET='demo-secret'
    uv run binance-mm --environment demo --strategy normal --quote USDT

Demo REST base URL used by the code:

    https://demo-fapi.binance.com

Start small and verify account mode, precision, leverage, fills, cancellation reconciliation, and API limits before considering live use.

## Live mode

Live credentials require Futures trading permission. Disable withdrawals on the key, restrict IPs, and use a dedicated low-balance account where possible.

    export BINANCE_API_KEY='live-key'
    export BINANCE_API_SECRET='live-secret'
    uv run binance-mm --environment live --yes-live --strategy normal --quote USDT

Without `--yes-live`, live mode exits immediately.

## Verification

    uv run pytest -q
    uv run ruff check .

## Current status

- Market discovery, volume/quote filtering, spread gating, BB Width detection, precision-aware sizing, 30-order cap, HTTP signing, paper broker, demo/live REST client, and terminal display are implemented.
- Paper mode has been exercised against current public Binance Futures market data.
- Demo/live authenticated execution is code-complete but not account-tested because no Demo API credentials have been supplied.
- Before real funds, fill/cancel reconciliation should be moved to Binance's user-data WebSocket and tested under partial fills and network faults.

## Official references

- Binance USD-M Futures general information: https://developers.binance.com/docs/derivatives/usds-margined-futures/general-info
- Exchange information: https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Exchange-Information
- All book tickers: https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Symbol-Order-Book-Ticker
- 24-hour ticker: https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/24hr-Ticker-Price-Change-Statistics
- New order: https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api
- Binance Agent OS MCP: https://developers.binance.com/en/docs/agent-native/mcp-server/agentic
- Market-making inventory risk background: https://hummingbot.org/blog/guide-to-the-avellaneda--stoikov-strategy/
