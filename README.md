# Binance Agent OS - Spot + Perpetual Liquidity Agent

A Binance Agent OS Track A project for scanning and providing maker liquidity on Binance Spot and USD-M Perpetual markets.

All authenticated reads and writes use the official Binance Agent OS OAuth MCP server. This repository does not accept Binance API keys or secrets and contains no authenticated REST-signing fallback.

## Features

| Feature | USD-M Perpetual | Spot |
|---|---:|---:|
| Binance Agent OS OAuth execution | Yes | Yes |
| USDT default | Yes | Yes |
| Optional USDC markets | Yes | Yes |
| Minimum 24h quote volume | $10M | $10M |
| Minimum entry spread | 0.02% | 0.02% |
| Refresh/expiry target | 3 seconds | 3 seconds |
| Maximum simultaneously open orders | 30 | 30 |
| Allocation | 1% of Perp equity | 1% of Spot quote balance |
| Leverage | 2x | Not applicable |
| Normal mode | Yes | Yes |
| Volatile-only mode | Yes | Yes |

Spot and Perp limits are independent because the balances are separate. Running both can therefore allow up to 30 open Perp orders plus 30 open Spot orders.

Alpha Trading is intentionally excluded because the current Binance Agent OS MCP tool catalog does not expose authenticated Alpha order and cancellation tools. There is no API-key fallback.

## Strategy

Normal mode:

1. Scan all trading pairs for the selected market and quote asset.
2. Skip pairs below $10M rolling 24-hour quote volume.
3. Calculate `(best ask - best bid) / midpoint`.
4. Propose maker liquidity when spread is at least 0.02%.
5. Cancel or refresh bot-owned maker orders after 3 seconds.

Volatile-only mode:

- Closed 5-minute candles
- Bollinger Bands period 20, standard deviation 2
- Current bandwidth must be above the rolling 80th percentile of 200 bandwidth observations

Perpetual sizing:

- Total proposed margin across open Perp entry orders: 1% of Perp equity
- Leverage: 2x
- Maker order: `LIMIT` with `GTX`
- Maximum open Perp orders: 30

Spot sizing:

- Total proposed BUY allocation: 1% of available Spot quote balance
- Maker order: `LIMIT_MAKER`
- No naked shorting: without base-token inventory, the agent does not submit a SELL
- Maximum open Spot orders: 30

Fill/inventory policy:

1. Cancel the bot-owned sibling quote through Agent OS.
2. Stop new exposure on that symbol.
3. Place an opposite maker exit through Agent OS.
4. Refresh the exit after 3 seconds even if current spread is below 0.02%.
5. Resume new entries only after Agent OS account/position data confirms inventory is flat.

## Architecture

    Binance public market data
      - exchange information
      - 24h quote volume
      - book ticker
      - 5m candles
                |
                v
      scanner + BB/spread strategy
                |
                v
      Hermes plugin using ctx.call_mcp
                |
                v
      Binance Agent OS OAuth MCP
                |
                v
      Binance Agentic sub-account

Public endpoints are only used for unauthenticated market data. The current Agent OS USD-M catalog does not expose all-market `bookTicker` and 24-hour `quoteVolume`, so these two scanner inputs use Binance's official public endpoints. Account, balance, position, open-order, order query, leverage, order placement, and cancellation actions use Agent OS MCP.

## Agent OS tools used

Perpetual:

- `futures_usds.accountInformationV3`
- `futures_usds.positionInformationV2`
- `futures_usds.currentAllOpenOrders`
- `futures_usds.queryOrder`
- `futures_usds.changeInitialLeverage`
- `futures_usds.newOrder`
- `futures_usds.cancelOrder`

Spot:

- `spot.getAccount`
- `spot.getOpenOrders`
- `spot.getOrder`
- `spot.newOrder`
- `spot.deleteOrder`

## Installation

Requirements:

- Python 3.11+
- `uv`
- Hermes Agent
- Binance account eligible for Agent OS

Clone and install dependencies:

    git clone https://github.com/ItzJulkar/binance-agent-OS.git
    cd binance-agent-OS
    uv sync --extra dev

Connect Hermes to Binance Agent OS:

    hermes mcp add binance --url https://agent.binance.com/mcp/agentic --auth oauth
    hermes mcp test binance

Binance opens its own authorization page. Login, 2FA, sub-account selection, and permission approval happen only on Binance. The project never receives those credentials.

Install and authorize the Hermes plugin on Windows Git Bash:

    cp -r hermes-plugin "$LOCALAPPDATA/hermes/plugins/binance-agent-os"
    hermes plugins enable binance-agent-os
    hermes config set plugins.entries.binance-agent-os.mcp_allowlist '["binance"]'

Restart Hermes after installation.

## Commands

Check integration:

    hermes binance-agent-os status

Read Agent OS account state:

    hermes binance-agent-os account
    hermes binance-agent-os positions
    hermes binance-agent-os orders
    hermes binance-agent-os orders --symbol BTCUSDT

Run only USD-M Perpetual:

    hermes binance-agent-os run-perp --cycles 1 --quote USDT --strategy normal

Run only Spot:

    hermes binance-agent-os run-spot --cycles 1 --quote USDT --strategy normal

Run Spot and Perp together:

    hermes binance-agent-os run-both --cycles 1 --quote USDT --strategy normal

USDC mode:

    hermes binance-agent-os run-both --cycles 1 --quote USDC

Volatile-only mode:

    hermes binance-agent-os run-both --cycles 1 --strategy volatile

Continuous cycles:

    hermes binance-agent-os run-both --cycles 20 --refresh 3

Custom thresholds:

    hermes binance-agent-os run-both --min-volume 20000000 --min-spread 0.0003 --max-orders 30

## Observe live — standalone dashboard (no AI agent needed)

The trade dashboard is a **read-only, standalone viewer**. Anyone who clones the
repo can run it directly — it does not require Hermes, Claude, or any MCP client.
The bot writes activity to `logs/*.jsonl`; the dashboard tails that file and
renders a live, color-coded terminal UI (scanned markets + spreads, open orders,
positions, portfolio/PnL, buy/sell counts, activity log).

Run a paper (demo) bot in one terminal:

    uv run binance-mm --environment paper --refresh 2 --max-orders 10

Open a second terminal and start the dashboard (any directory inside the repo):

    uv run binance-mm watch

Keys:  Left/Right arrow (or `l` / `d`) switch between LIVE and DEMO views
       `q` quits. LIVE shows the Agent OS account stream (`logs/live.jsonl`),
       DEMO shows the paper stream (`logs/demo.jsonl`).

Note on LIVE mode: real order execution always runs through the Binance Agent OS
OAuth MCP endpoint (`agent.binance.com/mcp/agentic`) — that is how this bot meets
the Agent OS campaign's no-API-key requirement. So live runs are driven from an
MCP-connected context (e.g. `hermes binance-agent-os run-perp`); the dashboard
itself is independent of that connection.

## Terminal output

The command prints separate prefixed activity for each market:

- `PERP SCAN` / `SPOT SCAN`
- `ORDER_CONFIRMED`
- `CANCEL_CONFIRMED`
- `FILL_OR_POSITION`
- confirmation count
- cycle elapsed time

This makes Spot and Perp activity distinguishable when `run-both` is used.

## Confirmation boundary

Binance Agent OS requires confirmation for write actions. A live order or cancellation may block while waiting for Binance confirmation. Therefore:

- The 3-second value is an expiry/earliest refresh target, not a guarantee while confirmation is pending.
- The agent does not bypass confirmation using API credentials.
- Start with one cycle and a low funded Agentic sub-account.
- Never blindly retry a timed-out write without querying order state.

## Paper visualization

Paper mode uses live public market data and simulated orders, without authentication:

    uv run binance-mm --environment paper
    uv run binance-mm --environment paper --quote USDC
    uv run binance-mm --environment paper --strategy volatile

Authenticated execution must use the Hermes Agent OS plugin.

## Verification

    uv run ruff check .
    uv run pytest -q
    hermes plugins doctor binance-agent-os
    hermes binance-agent-os --help

## Official references

- Binance Agent OS MCP: https://developers.binance.com/en/docs/agent-native/mcp-server/agentic
- Binance Spot market data: https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints
- Binance USD-M exchange information: https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Exchange-Information
- Binance USD-M book ticker: https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Symbol-Order-Book-Ticker
- Binance USD-M 24-hour ticker: https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/24hr-Ticker-Price-Change-Statistics
