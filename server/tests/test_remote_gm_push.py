# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The remote GM's view pushed to the browser on PostgreSQL 16 (plan phase 19's S19-11; decision FU9-6).

``GET /api/v1/fields/{id}/remote-gm/stream`` is driven through the app's own ASGI interface, in the test's event
loop, so each chunk the server pushes can be read as it comes (httpx's ASGI transport would hold the answer until
the stream ends) while a controller's socket (``test_remote_gm.Stream``) changes the live view. The same page in a
real browser, over real sockets: ``tests_browser`` (``RemoteGmTests``).

    python3 tools/docker_server.py test tests.test_remote_gm_push
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Optional
from unittest import mock

from atalaia_server.api import remote_gm as remote_api

from .test_remote_gm import CONTROLLER, ENV, LIVE, STANDBY, RemoteCase


class View:
    """A browser's ``GET .../remote-gm/stream``."""

    def __init__(self, app: Any, path: str, headers: dict[str, str]) -> None:
        self.chunks: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.gone = asyncio.Event()
        self.sent_request = False
        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}, "http_version": "1.1",
                 "method": "GET", "scheme": "https", "server": ("server.test", 443),
                 "client": ("127.0.0.1", 50001), "path": path, "raw_path": path.encode(), "root_path": "",
                 "query_string": b"", "headers": [(b"host", b"server.test"),
                                                  *[(k.lower().encode(), v.encode()) for k, v in headers.items()]]}
        self.task = asyncio.create_task(app(scope, self._receive, self.chunks.put))
        self.status = 0
        self.headers: dict[str, str] = {}
        self.buffer = ""
        self.ended = False

    async def _receive(self) -> dict[str, Any]:
        if not self.sent_request:
            self.sent_request = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await self.gone.wait()
        return {"type": "http.disconnect"}

    async def start(self) -> int:
        msg = await asyncio.wait_for(self.chunks.get(), 5)
        self.status = msg["status"]
        self.headers = {k.decode(): v.decode() for k, v in msg["headers"]}
        return self.status

    async def frame(self, timeout: float = 5.0) -> str:
        """The next complete frame (up to a blank line), comments included."""
        while "\n\n" not in self.buffer and not self.ended:
            msg = await asyncio.wait_for(self.chunks.get(), timeout)
            self.buffer += msg.get("body", b"").decode()
            self.ended = not msg.get("more_body", False)
        frame, _, self.buffer = self.buffer.partition("\n\n")
        return frame

    async def event(self, timeout: float = 5.0) -> tuple[str, Any]:
        """The next event: its name and data (a comment line is skipped)."""
        while True:
            frame = await self.frame(timeout)
            if frame.startswith(":"):
                continue
            lines = dict(line.split(": ", 1) for line in frame.splitlines())
            return lines["event"], json.loads(lines["data"])

    async def close(self) -> None:
        self.gone.set()
        await asyncio.wait_for(self.task, 5)


class PushTests(RemoteCase):
    def view(self, headers: Optional[dict[str, str]] = None, path: Optional[str] = None) -> View:
        return View(self.app, path or self.url("/stream"), self.gm if headers is None else headers)

    async def test_a_view_now_and_one_for_each_change(self) -> None:
        stream = await self.controller()
        view = self.view()
        self.assertEqual(await view.start(), 200)
        self.assertEqual(view.headers["content-type"], "text/event-stream; charset=utf-8")
        self.assertEqual(view.headers["cache-control"], "no-store")
        self.assertEqual(view.headers["x-accel-buffering"], "no")
        name, body = await view.event()
        self.assertEqual(name, "view")
        self.assertEqual(body, (await self.client.get(self.url(), headers=self.gm)).json())  # as the GET gives it
        self.assertEqual(body["controllers"][0]["live"]["state"], "ready")
        # A new live view from the controller arrives without anyone asking.
        await stream.send({"type": "live", **ENV, "live": {**LIVE, "state": "running", "game_time_ms": 1000}})
        name, body = await view.event(2)
        self.assertEqual((name, body["controllers"][0]["live"]["state"]), ("view", "running"))
        # A second controller connecting, and one leaving.
        other = await self.controller(ctrl=STANDBY, live=None)
        name, body = await view.event(2)
        self.assertEqual(sorted(c["controller_id"] for c in body["controllers"]),
                         sorted([CONTROLLER["id"], STANDBY["id"]]))
        await other.close()
        name, body = await view.event(2)
        self.assertEqual([c["controller_id"] for c in body["controllers"]], [CONTROLLER["id"]])
        self.assertEqual(len(self.app.state.remote_hub._watchers), 1)
        await view.close()
        self.assertEqual(self.app.state.remote_hub._watchers, {})  # the watch is gone with the browser

    async def test_changes_in_a_burst_are_one_view(self) -> None:
        stream = await self.controller()
        view = self.view()
        await view.start()
        await view.event()
        for n in range(5):
            await stream.send({"type": "live", **ENV, "live": {**LIVE, "game_time_ms": n}})
        await asyncio.sleep(0.3)
        name, body = await view.event(2)
        self.assertEqual(body["controllers"][0]["live"]["game_time_ms"], 4)  # the latest, not five views
        with self.assertRaises(asyncio.TimeoutError):
            await view.event(0.3)
        await view.close()

    async def test_the_stream_keeps_alive_and_ends_after_its_time(self) -> None:
        await self.controller()
        with mock.patch.object(remote_api, "STREAM_MAX_S", 0.5), mock.patch.object(remote_api, "STREAM_BEAT_S", 0.1):
            view = self.view()
            await view.start()
            self.assertEqual((await view.event())[0], "view")
            self.assertEqual(await view.frame(), ": keep-alive")
            self.assertEqual(await view.event(2), ("end", {}))
            await asyncio.wait_for(view.task, 5)  # the response is complete: the page opens a new stream
            self.assertEqual(await view.frame(), "")  # nothing more, and the body is closed
        self.assertTrue(view.ended)
        self.assertEqual(self.app.state.remote_hub._watchers, {})

    async def test_the_same_rules_as_the_view(self) -> None:
        marshal, _ = await self.staff("marshal")
        admin, _ = await self.staff("admin")
        for headers, status in ((marshal, 403), (admin, 403), ({}, 401)):
            view = self.view(headers)
            self.assertEqual(await view.start(), status)
            await view.close()
        other_field = await self.make_field("campo-sul")
        view = self.view(path=self.url("/stream", other_field))  # a gm here is nothing there
        self.assertEqual(await view.start(), 403)
        await view.close()
        # A gm without the TOTP step does not count (ADR-P4-2).
        user_id, name, _ = await self.make_user()
        await self.fetch("INSERT INTO user_field_roles (user_id, field_id, role_id) VALUES ($1, $2, 5)", user_id,
                         self.field_id)
        view = self.view(await self.auth(name))
        self.assertEqual(await view.start(), 403)
        await view.close()
        self.assertEqual(self.app.state.remote_hub._watchers, {})

    async def test_a_revoked_key_changes_the_view(self) -> None:
        await self.controller()
        view = self.view()
        await view.start()
        self.assertEqual(len((await view.event())[1]["controllers"]), 1)
        admin, _ = await self.staff("admin")
        r = await self.client.delete(f"/api/v1/fields/{self.field_id}/sync-keys/{self.key_id}", headers=admin)
        self.assertEqual(r.status_code, 204, r.text)
        self.assertEqual((await view.event(2))[1]["controllers"], [])
        await view.close()
