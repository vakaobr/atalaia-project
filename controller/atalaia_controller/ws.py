# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The live feed behind WS /api/v1/stream.

The engine publishes from its own threads; the hub hands each message to
every connected client's queue on the web server's event loop. A client
that falls more than ``max_queue`` messages behind is disconnected rather
than slowing everyone down (it reconnects and gets a fresh snapshot).
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Optional


class Hub:
    def __init__(self, max_queue: int = 256) -> None:
        self.max_queue = max_queue
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._clients: set[asyncio.Queue] = set()
        self._lock = threading.Lock()
        self.dropped_clients = 0

    def subscribe(self) -> asyncio.Queue:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue(self.max_queue)
        with self._lock:
            self._loop = loop
            self._clients.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._lock:
            self._clients.discard(queue)

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
            clients = list(self._clients)
        for queue in clients:
            try:
                queue.put_nowait(msg)
            except asyncio.QueueFull:
                self.dropped_clients += 1
                self.unsubscribe(queue)
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(None)  # tells the client's sender to close
