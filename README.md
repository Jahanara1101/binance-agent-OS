# Binance Agent OS - Spot + Perpetual Liquidity Agent

A Binance Agent OS Track A project for scanning and providing maker liquidity on Binance Spot and USD-M Perpetual markets.

All authenticated reads and writes use the official Binance Agent OS OAuth MCP server. This repository does not accept Binance API keys or secrets and contains no authenticated REST-signing fallback.

## Quick start (demo, no real money, no AI needed)

1. Install [uv](https://docs.astral.sh/uv/#installation) (one command).
2. Clone and **install once** (this puts the `binance-mm` command on your PATH):
   ```
   git clone https://github.com/ItzJulkar/binance-agent-OS
   cd binance-agent-OS
   uv tool install -e .
   ```
3. Now run `binance-mm` **from any folder — no `cd` needed**:
   - `binance-mm demo perp` → paper perp bot (USDT-M futures): real market data, simulated fills.
   - `binance-mm demo spot` → paper spot bot (no-naked-sell, 2% of quote per BUY).
   - `binance-mm live perp` → realtime perp orderbook (every market's spread).
   - `binance-mm live spot` → realtime spot orderbook.
   - `binance-mm watch`     → two-venue dashboard (LIVE ⇄ DEMO).
   - `binance-mm safe-exit` → cancel opens, hedge inventory out via maker, no new entries, stop when flat.

   (There is no bare `binance-mm demo` — always pick a venue.)

   Example — open two terminals, run in each:
   ```
   binance-mm demo perp     # terminal 1: the perp bot
   binance-mm demo spot     # or a spot bot in its own terminal
   binance-mm live perp     # terminal 2: live perp spreads / orderbook
   ```
   Stop the bot with `Ctrl+C`. `live`/`watch` scroll with ↑/↓ (or w/s),
   PgUp/PgDn, Home/End; switch dashboard views with ←/→; quit with `q`.
   Windows users can double-click **`demo.bat`** / **`live.bat`** / **`watch.bat`**
   instead of typing.

No flags, no API keys, no per-terminal `cd`. Logs go to `~/.binance-mm/logs/`.

Live real-money execution goes through the Binance Agent OS OAuth MCP
connection (see "Installation / live" below) and is driven from an MCP client;
everything in `demo` / `live` / `watch` runs standalone.

## Features

| Feature | USD-M Perpetual | Spot |
|---|---:|---:|
| Binance Agent OS OAuth execution | Yes | Yes |
| USDT default | Yes | Yes |
| Optional USDC markets | Yes | Yes |
| Minimum 24h quote volume | $10M | $1M |
| Minimum entry spread | 0.02% | 0.02% |
| Refresh/expiry target | 1 second | 1 second |
| Maximum simultaneously open orders | 30 | 30 |
| Portfolio allocation per leg | 2% | 2% |
| Leverage | 5x | Not applicable |
| Normal mode | Yes | Yes |

Spot and Perp limits are independent because the balances are separate. Running both can therefore allow up to 30 open Perp orders plus 30 open Spot orders.

Alpha Trading is intentionally excluded because the current Binance Agent OS MCP tool catalog does not expose authenticated Alpha order and cancellation tools. There is no API-key fallback.

## Configuration

The bot is a maker liquidity agent on Binance Spot and USD-M Perpetual. Public
configuration (the internal selection/exit algorithm is kept private):

- Portfolio allocation per leg: **2%** (`--margin-fraction 0.02`)
- Futures leverage: **5x** (`--leverage 5`)
- Minimum entry spread: 0.02% (`--min-spread`)
- Maximum open orders: 30 (`--max-orders`)
- Refresh cadence: 1 second (`--refresh`)
- Minimum 24h quote volume: perp $10M, spot $1M (`--min-volume`)

Safe-exit (`binance-mm safe-exit`): cancels all open quotes, hedges any
inventory out via maker orders on the opposite side, places no new entries, and
stops once flat. Optional venue: `binance-mm safe-exit spot` | `safe-exit perp`.

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

    hermes binance-agent-os run-perp --cycles 1 --quote USDT

Run only Spot:

    hermes binance-agent-os run-spot --cycles 1 --quote USDT

Run Spot and Perp together:

    hermes binance-agent-os run-both --cycles 1 --quote USDT

USDC mode:

    hermes binance-agent-os run-both --cycles 1 --quote USDC

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

    binance-mm demo perp     # or: binance-mm demo spot

Open a second terminal and start a **realtime orderbook terminal** — every
eligible USDT-M perpetual (or spot) with live bid/ask/spread streamed from
Binance's WebSocket (!bookTicker), plus the bot's equity/orders summary.
Scroll with ↑/↓ (or w/s), PgUp/PgDn, Home/End; `q` quits:

    binance-mm live perp     # or: binance-mm live spot

There is also a richer two-venue dashboard (LIVE/DEMO toggle):

    binance-mm watch          # ←/→ switches LIVE ⇄ DEMO, q quits

Keys:  Left/Right arrow (or `l` / `d`) switch between LIVE and DEMO views
       in `watch`. LIVE shows the Agent OS account stream (`~/.binance-mm/logs/live.jsonl`),
       DEMO shows the paper stream (`~/.binance-mm/logs/demo.jsonl`).

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
