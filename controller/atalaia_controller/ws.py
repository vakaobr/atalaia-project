# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The live feed behind WS /api/v1/stream.

The engine publishes from its own threads; the hub hands each message to
every connected client's queue on the web server's event loop. A client
that falls more than ``max_queue`` messages behind is disconnected rather
than slowing everyone down (it reconnects and gets a fresh snapshot).

Each client has a viewer (the GM token, the read token or a player token,
checkin.Viewer), and every message goes through ``route(viewer, msg)``
before it is queued (decision PE6): check-in and chrono-list messages
(names!) only to staff (the GM token, marshal and gm player tokens) and,
for their own row, to the player; player positions only to those who may
see them (positions.Positions.can_see); a player's connection gets no
radio or controller internals. Keys starting with "_" are routing marks and
never leave the controller.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Callable, Optional

CLOSE = "close"  # a queued ("close", code): the sender closes the socket with that code

# What a player-token connection is sent (besides its own check-in messages).
PLAYER_TYPES = {"hello", "game", "score", "node", "event", "field_state", "positions", "player_position",
                "checkin", "chrono_list", "checkin_open", "pong"}

Route = Callable[[Any, dict[str, Any]], Any]


def public(msg: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in msg.items() if not k.startswith("_")}


def default_route(viewer: Any, msg: dict[str, Any]) -> Any:
    """Without check-in: every message to everyone, minus the routing marks."""
    if msg.get("_staff") or "_player" in msg or msg.get("_position") or msg.get("_positions_refresh"):
        return None
    return public(msg)


class Hub:
    def __init__(self, max_queue: int = 256, route: Optional[Route] = None) -> None:
        self.max_queue = max_queue
        self.route: Route = route or default_route
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._clients: dict[asyncio.Queue, Any] = {}
        self._lock = threading.Lock()
        self.dropped_clients = 0

    def subscribe(self, viewer: Any = None) -> asyncio.Queue:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue(self.max_queue)
        with self._lock:
            self._loop = loop
            self._clients[queue] = viewer
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._lock:
            self._clients.pop(queue, None)

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def publish(self, msg: dict[str, Any]) -> None:
        """Thread-safe: called by the engine's listeners."""
        with self._lock:
            loop = self._loop
            if loop is None or not self._clients:
                return
        try:
            loop.call_soon_threadsafe(self._fanout, msg)
        except RuntimeError:  # the loop has closed
            pass

    def _fanout(self, msg: dict[str, Any]) -> None:
        with self._lock:
            clients = list(self._clients.items())
        for queue, viewer in clients:
            try:
                out = self.route(viewer, msg)
            except Exception:  # a routing bug must not stop the feed for everyone
                out = None
            if out is None:
                continue
            items = out if isinstance(out, list) else [out]
            try:
                for item in items:
                    queue.put_nowait(item)
            except asyncio.QueueFull:
                self.dropped_clients += 1
                self.unsubscribe(queue)
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(None)  # tells the client's sender to close
