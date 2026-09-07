"""Realtime orderbook feed for the Binance Agent OS market maker.

Public Binance USD-M perpetual top-of-book via the ``!bookTicker`` WebSocket
stream. The bot's own order flow runs through Agent OS MCP; this feed is used
only to render live bid/ask/spread for every scanned market, independent of the
REST poll cadence, so the dashboard repaints on each exchange tick.

Runs in a background thread (own asyncio loop) and writes into a lock-guarded
dict; the renderer calls :meth:`BookFeed.snapshot` for a consistent view.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any

import websockets

# Raw combined stream (direct /ws/!bookTicker did not connect from some
# networks; the /stream endpoint with ?streams= worked reliably).
_FUTURES_STREAM = "wss://fstream.binance.com/stream?streams=!bookTicker"


class BookFeed:
    """Subscribes to !bookTicker and keeps per-symbol bid/ask/spread fresh."""

    def __init__(self, symbols: list[str], reconnect_s: float = 3.0) -> None:
        self.symbols: set[str] = set(symbols)
        self.reconnect_s = reconnect_s
        self._books: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.started_at = time.time()
        self.updates = 0
        self.connected = False
        self.error: str | None = None

    # -- lifecycle ---------------------------------------------------------- #

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="binance-bookfeed", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # -- thread body -------------------------------------------------------- #

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._connect()
            except Exception as exc:  # noqa: BLE001 - keep reconnecting
                self.error = f"{type(exc).__name__}: {exc}"
            if self._stop.wait(self.reconnect_s):
                break

    def _connect(self) -> None:
        async def _inner() -> None:
            self.connected = False
            self.error = None
            try:
                async with websockets.connect(
                    _FUTURES_STREAM, open_timeout=8, ping_interval=20, ping_timeout=20
                ) as ws:
                    self.connected = True
                    self.error = None
                    while not self._stop.is_set():
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=30)
                        except TimeoutError:
                            await ws.ping()
                            continue
                        self._handle(json.loads(msg))
            except Exception as exc:  # noqa: BLE001
                self.error = f"{type(exc).__name__}: {exc}"

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_inner())
        finally:
            loop.close()

    def _handle(self, msg: dict[str, Any]) -> None:
        data = msg.get("data", msg)
        symbol = data.get("s") or data.get("symbol")
        if symbol not in self.symbols:
            return
        bid = data.get("b")
        ask = data.get("a")
        try:
            bidf = float(bid)
            askf = float(ask)
        except (TypeError, ValueError):
            return
        if bidf <= 0 or askf <= 0:
            return
        spread = (askf - bidf) / ((bidf + askf) / 2) * 100 if (bidf + askf) > 0 else 0.0
        with self._lock:
            self._books[symbol] = {
                "bid": bidf,
                "ask": askf,
                "spread": spread,
                "ts": time.time(),
            }
        self.updates += 1

    # -- read --------------------------------------------------------------- #

    def snapshot(self) -> list[dict[str, Any]]:
        """Return a consistent list of book rows (symbol/bid/ask/spread)."""
        with self._lock:
            return [
                {"sym": s, "bid": b["bid"], "ask": b["ask"], "spread": b["spread"]}
                for s, b in self._books.items()
            ]
