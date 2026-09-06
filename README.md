# Binance Agent OS Liquidity Agent

A Binance Agent OS Track A project: AI-assisted USD-M perpetual and spot liquidity workflows using Binance Agent OS OAuth MCP for every authenticated account, order, leverage, position, and cancellation action.

No Binance API key or secret is accepted by this project. Hermes stores the Binance OAuth authorization and calls the official Binance MCP server.

## What it does

- Scans all Binance USD-M perpetual markets using public market data
- Defaults to USDT; USDC is selectable
- Skips markets below 10,000,000 quote-asset volume over 24 hours
- Detects entry opportunities when top-of-book spread is at least 0.02%
- Supports normal and volatile-only selection
- Volatile mode: closed 5-minute candles, BB(20,2) bandwidth above its rolling 80th percentile
- Limits a proposed batch to 30 open orders and 1% total margin at 2x leverage
- Displays scan, proposed order, cancellation, and fill state in the terminal
- Routes authenticated execution exclusively through Binance Agent OS MCP tools
- Keeps separate 1% allocation and maximum 30 open orders for Spot and Perp

## Architecture

    Public Binance market data -> scanner and strategy -> proposed action
                                                   |
                                                   v
    Hermes plugin -> Binance Agent OS OAuth MCP -> Binance Agentic sub-account

Public endpoints are used only for exchange metadata, 24-hour volume, books, and candles because the current Agent OS USD-M tool set does not expose all-market 24-hour quote volume or bookTicker. No authenticated REST signing exists in this repository.

Authenticated tools:

- `futures_usds.accountInformationV3`
- `futures_usds.positionInformationV2`
- `futures_usds.currentAllOpenOrders`
- `futures_usds.queryOrder`
- `futures_usds.changeInitialLeverage`
- `futures_usds.newOrder`
- `futures_usds.cancelOrder`

## Binance Agent OS OAuth setup

    hermes mcp add binance --url https://agent.binance.com/mcp/agentic --auth oauth
    hermes mcp test binance

Binance opens its own authorization page. The user logs in and selects permissions there; neither Hermes nor this repository receives the Binance password, 2FA code, API key, or secret.

## Install the Hermes plugin

Clone the repository:

    git clone https://github.com/ItzJulkar/binance-agent-OS.git
    cd binance-agent-OS
    uv sync --extra dev

Copy the complete `hermes-plugin` directory to the active Hermes profile's plugins directory, enable it, then grant only this plugin access to the configured `binance` MCP server:

    cp -r hermes-plugin "$LOCALAPPDATA/hermes/plugins/binance-agent-os"
    hermes plugins enable binance-agent-os
    hermes config set plugins.entries.binance-agent-os.mcp_allowlist '["binance"]'

Restart Hermes after plugin installation. The plugin exposes:

    hermes binance-agent-os status
    hermes binance-agent-os account
    hermes binance-agent-os positions
    hermes binance-agent-os orders
    hermes binance-agent-os orders --symbol BTCUSDT
    hermes binance-agent-os run-perp --cycles 1 --quote USDT --strategy normal
    hermes binance-agent-os run-spot --cycles 1 --quote USDT --strategy normal
    hermes binance-agent-os run-both --cycles 1 --quote USDT --strategy normal

Each run cycle scans current public books, reads account/order/position state through Agent OS, then submits every authenticated order or cancellation through Binance Agent OS OAuth MCP. Spot and Perp each enforce their own 30-open-order cap and 1% allocation because their funds are separate. Binance may request confirmation for each write. Start with one cycle and a low funded balance.

## Confirmation boundary

Binance Agent OS requires user confirmation for write actions. Therefore a truthful Agent OS workflow cannot silently place and cancel 30 orders every three seconds unattended.

The scanner refreshes opportunities every three seconds. The Agent OS execution layer presents authenticated order/cancel operations through Binance's confirmation flow. This preserves the Agent OS security model and Track A provenance instead of bypassing it with direct API credentials.

## Strategy defaults

- Quote asset: USDT
- Minimum 24-hour quote volume: 10,000,000
- Entry spread: 0.02%
- Refresh interval: 3 seconds
- Maximum proposed open orders: 30
- Total proposed margin: 1% of equity
- Leverage: 2x
- Maker order: LIMIT + GTX

Fill policy:

1. Detect inventory through Agent OS account/order queries.
2. Cancel the sibling quote through Agent OS.
3. Stop proposing fresh exposure for that symbol.
4. Propose an opposite reduce-only maker exit.
5. Refresh the exit after three seconds even when spread is below 0.02%.
6. Resume two-sided quoting only when the Agent OS position query confirms flat inventory.

## Scanner and paper visualization

The standalone terminal scanner does not authenticate or trade. Paper mode visualizes the strategy against live public books:

    uv run binance-mm --environment paper
    uv run binance-mm --environment paper --quote USDC
    uv run binance-mm --environment paper --strategy volatile

The default environment is `agent-os`; authenticated commands must run through the Hermes plugin so there is no fallback path that can accidentally use direct keys.

## Tests

    uv run ruff check .
    uv run pytest -q

Tests enforce that authenticated order and cancellation calls map to Agent OS MCP tools and that no API secret/HMAC order-signing path exists.

## Official references

- Binance Agent OS MCP: https://developers.binance.com/en/docs/agent-native/mcp-server/agentic
- Binance USD-M public market information: https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Exchange-Information
- Binance all-market book ticker: https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Symbol-Order-Book-Ticker
- Binance 24-hour ticker: https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/24hr-Ticker-Price-Change-Statistics
