"""Persist-then-fan-out hub. Every channel publishes here; websockets (and later the
Telegram notifier) subscribe. `origin` lets subscribers skip echoing back to the sender."""
import asyncio
import logging
from collections import defaultdict
from typing import Any, Awaitable, Callable

from fastapi import WebSocket

log = logging.getLogger("wayfare.hub")

Subscriber = Callable[[int, dict[str, Any]], Awaitable[None]]


class EventHub:
    def __init__(self) -> None:
        self._rooms: dict[int, set[WebSocket]] = defaultdict(set)
        self._subscribers: list[Subscriber] = []  # e.g. Telegram notifier
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self, fn: Subscriber) -> None:
        if fn not in self._subscribers:      # idempotent: a restarted lifespan must not double-forward
            self._subscribers.append(fn)

    def unsubscribe(self, fn: Subscriber) -> None:
        if fn in self._subscribers:
            self._subscribers.remove(fn)

    async def connect(self, trip_id: int, ws: WebSocket) -> None:
        self._rooms[trip_id].add(ws)

    def disconnect(self, trip_id: int, ws: WebSocket) -> None:
        self._rooms[trip_id].discard(ws)
        if not self._rooms[trip_id]:
            self._rooms.pop(trip_id, None)

    async def publish(self, trip_id: int, event: dict[str, Any]) -> None:
        for ws in list(self._rooms.get(trip_id, ())):
            try:
                await ws.send_json(event)
            except Exception:
                self.disconnect(trip_id, ws)
        for fn in self._subscribers:
            try:
                await fn(trip_id, event)
            except Exception:
                log.exception("Hub subscriber failed")  # one bad subscriber must not block others

    def publish_threadsafe(self, trip_id: int, event: dict[str, Any]) -> None:
        """For sync route handlers running in the threadpool."""
        if self._loop is None or self._loop.is_closed():
            return
        fut = asyncio.run_coroutine_threadsafe(self.publish(trip_id, event), self._loop)
        fut.add_done_callback(lambda f: f.exception() and log.error("publish failed: %s", f.exception()))


hub = EventHub()
