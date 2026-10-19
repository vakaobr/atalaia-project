# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Lockouts and the per-address request limit, on a fake clock (no database)."""

from __future__ import annotations

import asyncio
import unittest
from typing import Any

from atalaia_server.ratelimit import Limits, Lockout, RequestLimit, RequestLimitMiddleware


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class LockoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = Clock()
        self.lock = Lockout(5, 900, 900, self.clock)

    def test_five_failures_lock_for_fifteen_minutes(self) -> None:
        for _ in range(4):
            self.assertFalse(self.lock.fail("10.0.0.1"))
            self.assertEqual(self.lock.retry_after("10.0.0.1"), 0)
        self.assertTrue(self.lock.fail("10.0.0.1"))
        self.assertEqual(self.lock.retry_after("10.0.0.1"), 900)
        self.assertEqual(self.lock.retry_after("10.0.0.2"), 0)  # per key
        self.clock.t += 899.5
        self.assertEqual(self.lock.retry_after("10.0.0.1"), 1)
        self.clock.t += 0.5
        self.assertEqual(self.lock.retry_after("10.0.0.1"), 0)
        # After the lockout the count starts again.
        self.assertFalse(self.lock.fail("10.0.0.1"))

    def test_old_failures_fall_out_of_the_window(self) -> None:
        for _ in range(4):
            self.lock.fail("k")
        self.clock.t += 901
        self.assertFalse(self.lock.fail("k"))
        self.assertEqual(self.lock.retry_after("k"), 0)

    def test_clear(self) -> None:
        for _ in range(4):
            self.lock.fail("k")
        self.lock.clear("k")
        self.assertFalse(self.lock.fail("k"))

    def test_memory_is_bounded(self) -> None:
        lock = Lockout(5, 900, 900, self.clock, max_keys=100)
        for i in range(1000):
            lock.fail(f"10.0.{i // 256}.{i % 256}")
        self.assertLessEqual(len(lock._failures), 100)
        for i in range(1000):
            for _ in range(5):
                lock.fail(f"k{i}")
        self.assertLessEqual(len(lock._locked), 100)


class RequestLimitTests(unittest.TestCase):
    def test_sliding_minute(self) -> None:
        clock = Clock()
        limit = RequestLimit(100, 60, clock)
        for i in range(100):
            self.assertEqual(limit.hit("a"), 0, i)
            clock.t += 0.1
        wait = limit.hit("a")
        self.assertGreater(wait, 0)
        self.assertLessEqual(wait, 60)
        self.assertEqual(limit.hit("b"), 0)
        clock.t += wait
        self.assertEqual(limit.hit("a"), 0)

    def test_memory_is_bounded(self) -> None:
        limit = RequestLimit(100, 60, Clock(), max_keys=50)
        for i in range(500):
            limit.hit(f"ip{i}")
        self.assertLessEqual(len(limit._hits), 50)

    def test_adr_p4_2_numbers(self) -> None:
        limits = Limits()
        self.assertEqual((limits.login.limit, limits.login.window_s, limits.login.lock_s), (5, 900, 900))
        self.assertEqual((limits.totp.limit, limits.totp.window_s, limits.totp.lock_s), (5, 900, 900))
        self.assertEqual((limits.requests.limit, limits.requests.window_s), (100, 60))


class MiddlewareTests(unittest.TestCase):
    def run_requests(self, paths: list[str], limits: Limits) -> list[tuple[int, dict[bytes, bytes]]]:
        async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        mw = RequestLimitMiddleware(app, get_limits=lambda: limits)
        out: list[tuple[int, dict[bytes, bytes]]] = []

        async def go() -> None:
            for path in paths:
                sent: list[dict[str, Any]] = []

                async def send(message: dict[str, Any]) -> None:
                    sent.append(message)

                async def receive() -> dict[str, Any]:
                    return {"type": "http.request", "body": b""}

                await mw({"type": "http", "path": path, "client": ("192.0.2.7", 5000), "headers": []}, receive, send)
                out.append((sent[0]["status"], dict(sent[0]["headers"])))

        asyncio.run(go())
        return out

    def test_429_with_retry_after_past_the_limit(self) -> None:
        limits = Limits(clock=Clock())
        limits.requests = RequestLimit(3, 60, Clock())
        results = self.run_requests(["/api/v1/me"] * 4, limits)
        self.assertEqual([s for s, _ in results], [200, 200, 200, 429])
        self.assertEqual(results[3][1][b"retry-after"], b"60")

    def test_health_and_non_api_paths_are_not_counted(self) -> None:
        limits = Limits(clock=Clock())
        limits.requests = RequestLimit(1, 60, Clock())
        results = self.run_requests(["/api/v1/health"] * 5 + ["/other"] * 5 + ["/api/v1/me"] * 2, limits)
        self.assertEqual([s for s, _ in results], [200] * 11 + [429])


if __name__ == "__main__":
    unittest.main()
