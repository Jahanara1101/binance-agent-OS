import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

PROD_WS = "wss://fstream.binance.com/ws/"
DEMO_WS = "wss://demo-fstream.binance.com/ws/"


class UserDataStream:
    def __init__(self, client: Any, environment: str, on_event: Callable[[dict[str, Any]], Awaitable[None]]):
        self.client = client
        self.environment = environment
        self.on_event = on_event
        self.running = False
        self.listen_key: str | None = None

    @property
    def websocket_url(self) -> str:
        if not self.listen_key:
            raise RuntimeError("listen key has not been created")
        base = DEMO_WS if self.environment == "demo" else PROD_WS
        return base + self.listen_key

    async def _keepalive(self) -> None:
        while self.running:
            await asyncio.sleep(45 * 60)
            if self.listen_key:
                await self.client.keepalive_listen_key(self.listen_key)

    async def run(self) -> None:
        try:
            import websockets
        except ImportError as exc:
            raise RuntimeError("websockets dependency is required") from exc
        self.running = True
        while self.running:
            self.listen_key = await self.client.create_listen_key()
            keeper = asyncio.create_task(self._keepalive())
            try:
                async with websockets.connect(self.websocket_url, ping_interval=20, ping_timeout=20) as ws:
                    async for raw in ws:
                        payload = json.loads(raw)
                        await self.on_event(payload)
            except (TimeoutError, OSError):
                if self.running:
                    await asyncio.sleep(2)
            finally:
                keeper.cancel()
                await asyncio.gather(keeper, return_exceptions=True)

    async def stop(self) -> None:
        self.running = False
        if self.listen_key:
            try:
                await self.client.close_listen_key(self.listen_key)
            except (httpx.HTTPError, RuntimeError):
                pass
