# Binance Agent OS - Spot + Perpetual Liquidity Agent

A maker-liquidity agent for Binance Spot and USD-M Perpetual markets. Runs a
live orderbook dashboard and a market-making bot, all from one `binance-mm`
command. No API keys anywhere — authenticated trading goes through the
official Binance Agent OS OAuth MCP server.

## Quick start (demo — no real money, no AI client needed)

1. Install [uv](https://docs.astral.sh/uv/#installation) (one command).
2. Clone and **install once** (puts `binance-mm` on your PATH):
   ```
   git clone https://github.com/ItzJulkar/binance-agent-OS
   cd binance-agent-OS
   uv tool install -e .
   ```
3. Run `binance-mm` from any folder:
   - `binance-mm demo perp` → paper perp bot (USDT-M futures, simulated fills)
   - `binance-mm demo spot` → paper spot bot
   - `binance-mm live perp` → realtime perp orderbook (every market's spread)
   - `binance-mm live spot` → realtime spot orderbook
   - `binance-mm watch`     → two-venue dashboard (LIVE ⇄ DEMO)
   - `binance-mm safe-exit` → cancel opens, hedge inventory out via maker, no new entries, stop when flat

   (There is no bare `binance-mm demo` — always pick a venue.)

   Stop the bot with `Ctrl+C`. `live`/`watch` scroll with ↑/↓ (or w/s),
   PgUp/PgDn, Home/End; switch views with ←/→; quit with `q`.
   Windows users can double-click **`demo.bat`** / **`live.bat`** / **`watch.bat`**.

No flags, no API keys, no per-terminal `cd`. Logs go to `~/.binance-mm/logs/`.

## Live trading (real money) — any AI client

Live order execution runs through the **Binance Agent OS OAuth MCP server**
(`agent.binance.com/mcp/agentic`). This is how the bot meets the Agent OS
campaign's no-API-key requirement — Binance authorizes the connection itself.

You do **not** need Hermes. Connect the Agent OS MCP endpoint from **any** MCP
client you already use — Claude, GPT, Cursor, or any MCP-aware assistant:

- Endpoint: `https://agent.binance.com/mcp/agentic`
- Auth: **OAuth** (Binance opens its own authorization page; login, 2FA,
  sub-account selection and permission approval happen only on Binance. The
  project never receives those credentials.)

Full setup and tool reference: see the official docs →
**https://developers.binance.com/en/docs/agent-native/mcp-server/agentic**

Once connected, the client can read account/positions/orders and place/cancel
orders through the Agent OS tools. The `binance-mm` dashboard (demo/live/watch)
is independent of that connection — it reads local log files and needs no AI
client at all.

## Features

| Feature | USD-M Perpetual | Spot |
|---|---:|---:|
| Binance Agent OS OAuth execution | Yes | Yes |
| USDT default | Yes | Yes |
| Optional USDC markets | Yes | Yes |
| Portfolio allocation per leg | 2% | 2% |
| Leverage | 5x | Not applicable |
| Normal mode | Yes | Yes |

Spot and Perp limits are independent because the balances are separate. Running
both can therefore allow up to 30 open Perp orders plus 30 open Spot orders.

Alpha Trading is intentionally excluded because the current Binance Agent OS MCP
tool catalog does not expose authenticated Alpha order and cancellation tools.
There is no API-key fallback.

## Configuration

The bot is a maker liquidity agent on Binance Spot and USD-M Perpetual. Public
configuration is limited to the two parameters that users most need to tune
(internal selection, sizing and exit thresholds are kept private):

- Portfolio allocation per leg: **2%** (`--margin-fraction 0.02`)
- Futures leverage: **5x** (`--leverage 5`)

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
      scanner + market-maker strategy
                |
                v
      any MCP client (Claude / GPT / Hermes / …)
                |
                v
      Binance Agent OS OAuth MCP
                |
                v
      Binance Agentic sub-account

Public endpoints are only used for unauthenticated market data. The current
Agent OS USD-M catalog does not expose all-market `bookTicker` and 24-hour
`quoteVolume`, so these two scanner inputs use Binance's official public
endpoints. Account, balance, position, open-order, order query, leverage, order
placement, and cancellation actions use Agent OS MCP.

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

## Terminal output

The command prints separate prefixed activity for each market:

- `PERP SCAN` / `SPOT SCAN`
- `ORDER_CONFIRMED`
- `CANCEL_CONFIRMED`
- `FILL_OR_POSITION`
- confirmation count
- cycle elapsed time

## Confirmation boundary

Binance Agent OS requires confirmation for write actions. A live order or
cancellation may block while waiting for Binance confirmation. Therefore:

- The refresh value is an expiry/earliest target, not a guarantee while
  confirmation is pending.
- The agent does not bypass confirmation using API credentials.
- Start with one cycle and a low funded Agentic sub-account.
- Never blindly retry a timed-out write without querying order state.

## Verification

    uv run ruff check .
    uv run pytest -q

## License

MIT
