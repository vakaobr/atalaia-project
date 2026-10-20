# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The remote GM on PostgreSQL 16 (plan phase 19; P4R12): who may, what may be sent, where, and the audit log.

A controller's stream is driven here through the app's own ASGI interface,
in the test's event loop, so a command a user posts and the controller's
answer on its socket meet in one process: a command is refused while the
controller's ``remote_gm`` is off, refused when it is not in the list,
refused for a user without ``gm`` on that field, and every attempt is in the
audit log. The real controller over a real socket: ``test_remote_gm_e2e.py``.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Optional

from atalaia_controller import sync_format

from atalaia_server import sync
from atalaia_server.ratelimit import RequestLimit

from .base import AppTestCase

CONTROLLER = {"id": "0192f3a4-5b6c-7d8e-9f01-23456789abcd", "version": "0.1.0"}
STANDBY = {"id": "0192f3a4-5b6c-7d8e-9f01-23456789abce", "version": "0.1.0"}
ENV = {"sync_version": 1, "controller": CONTROLLER}
GAME = {"game_id": 4242, "game_seed": 3735928559}
LIVE = {"game": GAME, "name": "Domingo", "mode_id": "org.atalaia.domination", "teams": ["red", "blue"],
        "state": "ready", "in_charge": True, "totals": {"red": 0, "blue": 0}, "nodes": [], "events": []}


class Stream:
    """A controller's WebSocket to the app, through ASGI in the test's event loop."""

    def __init__(self, app: Any, key: str) -> None:
        self.app = app
        self.inbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.outbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.scope = {"type": "websocket", "asgi": {"version": "3.0", "spec_version": "2.3"}, "http_version": "1.1",
                      "scheme": "wss", "server": ("server.test", 443), "client": ("127.0.0.1", 50000),
                      "path": "/api/v1/sync/stream", "raw_path": b"/api/v1/sync/stream", "root_path": "",
                      "query_string": b"", "headers": [(b"host", b"server.test"),
                                                       (b"authorization", f"Bearer {key}".encode())],
                      "subprotocols": [], "extensions": {}}
        self.task: Optional[asyncio.Task[None]] = None

    async def open(self) -> dict[str, Any]:
        self.task = asyncio.create_task(self.app(self.scope, self.inbox.get, self.outbox.put))
        await self.inbox.put({"type": "websocket.connect"})
        return await asyncio.wait_for(self.outbox.get(), 5)

    async def send(self, msg: dict[str, Any]) -> None:
        await self.inbox.put({"type": "websocket.receive", "text": json.dumps(msg)})

    async def receive(self, timeout: float = 5.0) -> dict[str, Any]:
        msg = await asyncio.wait_for(self.outbox.get(), timeout)
        if msg["type"] == "websocket.close":
            return {"type": "closed", "code": msg.get("code")}
        return json.loads(msg["text"])

    def pending(self) -> int:
        return self.outbox.qsize()

    async def close(self) -> None:
        if self.task is not None and not self.task.done():
            await self.inbox.put({"type": "websocket.disconnect", "code": 1000})
            await asyncio.wait_for(self.task, 5)


class RemoteCase(AppTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.field_id = await self.make_field("campo-norte")
        self.key = sync.new_key()
        self.key_id = (await self.fetch("INSERT INTO field_api_keys (field_id, key_sha256) VALUES ($1, $2) "
                                        "RETURNING id", self.field_id, sync.key_hash(self.key)))[0][0]
        self.gm, self.gm_id = await self.staff("gm")
        self.streams: list[Stream] = []

    async def asyncTearDown(self) -> None:
        for s in self.streams:
            await s.close()
        await super().asyncTearDown()

    async def make_field(self, slug: str) -> uuid.UUID:
        return (await self.fetch("INSERT INTO fields (name, slug) VALUES ($1, $2) RETURNING id", slug.title(),
                                 slug))[0][0]

    async def staff(self, *roles: str, field_id: Optional[uuid.UUID] = None,
                    server_admin: bool = False) -> tuple[dict[str, str], uuid.UUID]:
        user_id, name, secret = await self.make_user(with_totp=True, server_admin=server_admin)
        for role in roles:
            await self.fetch("INSERT INTO user_field_roles (user_id, field_id, role_id) VALUES ($1, $2, $3)",
                             user_id, field_id or self.field_id, {"marshal": 4, "gm": 5, "admin": 7}[role])
        return await self.auth(name, secret=secret), user_id

    async def controller(self, remote_gm: bool = True, ctrl: dict[str, str] = CONTROLLER,
                         live: Optional[dict[str, Any]] = LIVE) -> Stream:
        stream = Stream(self.app, self.key)
        self.streams.append(stream)
        self.assertEqual((await stream.open())["type"], "websocket.accept")
        await stream.send({"type": "hello", "sync_version": 1, "controller": ctrl, "remote_gm": remote_gm})
        self.assertEqual(await stream.receive(), {"type": "hello.ack", "remote_gm": remote_gm})
        if live is not None:
            await stream.send({"type": "live", "sync_version": 1, "controller": ctrl, "live": live})
        await asyncio.sleep(0.05)
        return stream

    def url(self, path: str = "", field: Optional[uuid.UUID] = None) -> str:
        return f"/api/v1/fields/{field or self.field_id}/remote-gm{path}"

    async def post(self, body: dict[str, Any], headers: Optional[dict[str, str]] = None,
                   field: Optional[uuid.UUID] = None) -> Any:
        return await self.client.post(self.url("/commands", field), json=body, headers=headers or self.gm)

    async def answered(self, stream: Stream, body: dict[str, Any], code: str = "done",
                       detail: Optional[str] = "game 4242 is running", ctrl: dict[str, str] = CONTROLLER) -> Any:
        """Posts a command, answers it on the controller's socket, returns (the HTTP answer, the command sent)."""
        post = asyncio.create_task(self.post(body))
        cmd = await stream.receive()
        self.assertEqual(cmd["type"], "command")
        await stream.send({"type": "command.result", "sync_version": 1, "controller": ctrl, "id": cmd["id"],
                           "code": code, **({"detail": detail} if detail else {})})
        return await post, cmd

    async def audit(self) -> list[Any]:
        return await self.fetch("SELECT action, user_id, details FROM audit_log WHERE action LIKE 'remote_gm%' "
                                "ORDER BY id")


class CommandTests(RemoteCase):
    async def test_a_command_goes_to_the_controller_and_back(self) -> None:
        stream = await self.controller()
        r, cmd = await self.answered(stream, {"game": GAME, "command": "start"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["code"], r.json()["controller_id"]), ("done", CONTROLLER["id"]))
        sync_format.check_command({k: v for k, v in cmd.items() if k != "type"})  # what the controller checks
        self.assertEqual((cmd["command"], cmd["params"], cmd["game"]), ("start", {}, GAME))
        self.assertEqual(cmd["user"]["id"], str(self.gm_id))
        [row] = await self.audit()
        details = json.loads(row["details"])
        self.assertEqual((row["action"], row["user_id"]), ("remote_gm_command", self.gm_id))
        self.assertEqual((details["command"], details["result"], details["controller_id"], details["game_id"]),
                         ("start", "done", CONTROLLER["id"], 4242))
        for what, params in (("pause", {"reason": "medic"}), ("resume", {}), ("message", {"text": "5 min"}),
                             ("mode", {"name": "refill", "node": 7}), ("end", {})):
            with self.subTest(what):
                r, cmd = await self.answered(stream, {"game": GAME, "command": what, "params": params})
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(cmd["params"], sync_format.check_command_params(what, dict(params)))
        self.assertEqual(len(await self.audit()), 6)

    async def test_refused_while_remote_gm_is_off(self) -> None:
        stream = await self.controller(remote_gm=False)
        r = await self.post({"game": GAME, "command": "start"})
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "remote_gm_off"))
        self.assertEqual(stream.pending(), 0)  # nothing went to the controller
        [row] = await self.audit()
        self.assertEqual((row["action"], json.loads(row["details"])["reason"]), ("remote_gm_denied", "remote_gm_off"))
        # Named explicitly, too.
        r = await self.post({"game": GAME, "command": "start", "controller_id": CONTROLLER["id"]})
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "remote_gm_off"))

    async def test_refused_outside_the_list(self) -> None:
        stream = await self.controller()
        for body, error, path in (({"game": GAME, "command": "set_owner", "params": {"team": "red"}}, "not_allowed",
                                   "command"),
                                  ({"game": GAME, "command": "score", "params": {"team": "red", "amount": 9}},
                                   "not_allowed", "command"),
                                  ({"game": GAME, "command": "reboot"}, "not_allowed", "command"),
                                  ({"game": GAME, "command": "start", "params": {"preset": "x"}}, "unknown_field",
                                   "params.preset"),
                                  ({"game": GAME, "command": "message", "params": {"text": "x" * 101}}, "bad_text",
                                   "params.text"),
                                  ({"game": {"game_id": 70000, "game_seed": 1}, "command": "start"}, "out_of_range",
                                   "game.game_id")):
            with self.subTest(body=body):
                r = await self.post(body)
                self.assertEqual(r.status_code, 400, r.text)
                self.assertEqual(r.json(), {"detail": "invalid_command", "error": error, "path": path})
        r = await self.post({"game": GAME, "command": "start", "user": {"id": str(uuid.uuid4()), "username": "x"}})
        self.assertEqual((r.status_code, r.json()["error"]), (400, "bad_body"))  # who sends it is the server's to say
        self.assertEqual(stream.pending(), 0)
        rows = await self.audit()
        self.assertEqual({r["action"] for r in rows}, {"remote_gm_denied"})
        self.assertEqual(len(rows), 7)

    async def test_refused_without_gm_on_that_field(self) -> None:
        stream = await self.controller()
        other = await self.make_field("campo-sul")
        admin, _ = await self.staff("admin")
        marshal, _ = await self.staff("marshal")
        elsewhere, _ = await self.staff("gm", field_id=other)
        server, _ = await self.staff(server_admin=True)
        player_id, name, _ = await self.make_user()
        player = await self.auth(name)
        for who, headers in (("admin", admin), ("marshal", marshal), ("gm elsewhere", elsewhere),
                             ("server admin", server), ("no role", player)):
            with self.subTest(who):
                r = await self.post({"game": GAME, "command": "end"}, headers=headers)
                self.assertEqual((r.status_code, r.json()["detail"]), (403, "role_required"))
                r = await self.client.get(self.url(), headers=headers)
                self.assertEqual(r.status_code, 403)
        r = await self.client.post(self.url("/commands"), json={"game": GAME, "command": "end"})
        self.assertEqual(r.status_code, 401)
        # The gm of the other field cannot reach this field's controller through their own field either.
        r = await self.post({"game": GAME, "command": "end"}, headers=elsewhere, field=other)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "controller_offline"))
        self.assertEqual(stream.pending(), 0)
        rows = await self.audit()
        self.assertEqual([json.loads(r["details"])["reason"] for r in rows], ["role_required"] * 5
                         + ["controller_offline"])

    async def test_the_controller_refuses_or_does_not_answer(self) -> None:
        stream = await self.controller()
        r, _ = await self.answered(stream, {"game": GAME, "command": "resume"}, code="conflict",
                                   detail="only a paused game resumes")
        self.assertEqual(r.status_code, 409)
        self.assertEqual((r.json()["detail"], r.json()["code"], r.json()["message"]),
                         ("refused_by_controller", "conflict", "only a paused game resumes"))
        self.app.state.remote_hub.timeout_s = 0.2
        r = await self.post({"game": GAME, "command": "start"})
        self.assertEqual((r.status_code, r.json()["detail"]), (504, "controller_timeout"))
        await stream.receive()  # the command it never answered
        rows = await self.audit()
        self.assertEqual([json.loads(r["details"])["result"] for r in rows], ["conflict", "controller_timeout"])

    async def test_offline_and_a_revoked_key(self) -> None:
        r = await self.post({"game": GAME, "command": "start"})
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "controller_offline"))
        stream = await self.controller()
        await stream.close()
        r = await self.post({"game": GAME, "command": "start"})
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "controller_offline"))
        stream = await self.controller()
        admin, _ = await self.staff("admin")
        r = await self.client.delete(f"/api/v1/fields/{self.field_id}/sync-keys/{self.key_id}", headers=admin)
        self.assertEqual(r.status_code, 204)
        r = await self.post({"game": GAME, "command": "start"})
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "controller_offline"))
        await stream.send({"type": "live", **ENV, "live": LIVE})  # its next message closes the socket
        self.assertEqual(await stream.receive(), {"type": "closed", "code": 4401})

    async def test_which_controller(self) -> None:
        primary = await self.controller()
        await self.controller(ctrl=STANDBY, live={**LIVE, "in_charge": False})
        r, cmd = await self.answered(primary, {"game": GAME, "command": "start"})
        self.assertEqual((r.status_code, r.json()["controller_id"]), (200, CONTROLLER["id"]))
        r = await self.post({"game": GAME, "command": "start", "controller_id": str(uuid.uuid4())})
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "controller_offline"))

    async def test_a_rate_limit_per_account(self) -> None:
        await self.controller(remote_gm=False)
        self.app.state.limits.remote_commands = RequestLimit(2, 60)
        codes = [(await self.post({"game": GAME, "command": "start"})).status_code for _ in range(3)]
        self.assertEqual(codes, [409, 409, 429])


class LiveTests(RemoteCase):
    async def test_the_live_view_and_the_log(self) -> None:
        stream = await self.controller()
        r = await self.client.get(self.url(), headers=self.gm)
        self.assertEqual(r.status_code, 200, r.text)
        [entry] = r.json()["controllers"]
        self.assertEqual((entry["controller_id"], entry["remote_gm"], entry["live"]["state"]),
                         (CONTROLLER["id"], True, "ready"))
        self.assertEqual(r.json()["commands"], ["start", "pause", "resume", "end", "message", "mode"])
        self.assertIsNotNone(entry["controller"])  # the controllers row the hello made
        rows = await self.fetch("SELECT controller_id, version FROM controllers")
        self.assertEqual((str(rows[0][0]), rows[0][1]), (CONTROLLER["id"], "0.1.0"))
        # A live view with a position is refused and the last good one stays.
        bad = {**LIVE, "events": [{"id": 1, "node": 3, "seq": 1, "t": 5, "type": "vip.moved", "prio": "normal",
                                   "data": {"lat": 38.7}}]}
        await stream.send({"type": "live", **ENV, "live": bad})
        answer = await stream.receive()
        self.assertEqual((answer["type"], answer["error"]), ("error", "position_not_allowed"))
        r = await self.client.get(self.url(), headers=self.gm)
        self.assertEqual(r.json()["controllers"][0]["live"]["events"], [])
        await self.answered(stream, {"game": GAME, "command": "start"})
        r = await self.client.get(self.url("/log"), headers=self.gm)
        self.assertEqual([(e["action"], e["details"]["command"]) for e in r.json()], [("remote_gm_command", "start")])
        marshal, _ = await self.staff("marshal")
        self.assertEqual((await self.client.get(self.url("/log"), headers=marshal)).status_code, 403)

    async def test_hello_first_and_another_controller_id(self) -> None:
        stream = Stream(self.app, self.key)
        self.streams.append(stream)
        await stream.open()
        await stream.send({"type": "live", **ENV, "live": None})
        self.assertEqual(await stream.receive(), {"type": "error", "detail": "hello_first"})
        await stream.send({"type": "hello", **ENV, "remote_gm": True})
        await stream.receive()
        await stream.send({"type": "live", "sync_version": 1, "controller": STANDBY, "live": None})
        self.assertEqual((await stream.receive())["error"], "not_this_controller")
        # The sync bodies still work on the same socket.
        await stream.send({"type": "ping"})
        self.assertEqual(await stream.receive(), {"type": "pong"})
        await stream.close()
        self.assertEqual(self.app.state.remote_hub.links(self.field_id), [])
