# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The remote GM on the controller (plan phase 19; P4R12): its commands, its live view, its log, and the
stream it opens, against a small WebSocket server in this process (the real site server:
server/tests/test_remote_gm_e2e.py).

    cd controller && python -m unittest discover -s tests
"""

from __future__ import annotations

import copy
import json
import logging
import queue
import socket
import struct
import tempfile
import threading
import time
import unittest
import uuid
from typing import Any, Optional

from support import CORE, FakeModem, config, wait_for

from atalaia_controller import sync_format, ws_client
from atalaia_controller.config import ConfigError
from atalaia_controller.engine import Controller
from atalaia_controller.main import build
from atalaia_controller.remote_gm import RemoteGm, stream_url
from atalaia_controller.store import REMOTE_LOG_DAYS, SCHEMA_VERSION, Store
from atalaia_sim.packet import cmd_decode, hello_encode
from fastapi.testclient import TestClient

KEY = "k" * 43
DOMINATION = "org.atalaia.domination"
MEDIC = "org.atalaia.medic"
USER = {"id": "0192f3a4-0000-7000-8000-0000000000aa", "username": "gm-norte"}
GM = {"Authorization": "Bearer gm-secret"}
READ = {"Authorization": "Bearer read-secret"}
logging.getLogger("atalaia.remote_gm").setLevel(logging.CRITICAL)  # the tests provoke its warnings


def command(game: dict[str, Any], what: str, params: Optional[dict[str, Any]] = None, **kw: Any) -> dict[str, Any]:
    return {"id": str(uuid.uuid4()), "game": {"game_id": game["id"], "game_seed": game["game_seed"]},
            "command": what, "params": params or {}, "user": USER, "sent_at": time.time(), **kw}


class RemoteCase(unittest.TestCase):
    remote_gm = True

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = config(self.tmp.name, sync_enabled=True, sync_url="https://site.example.org", sync_api_key=KEY,
                          sync_remote_gm=self.remote_gm)
        self.store = Store(self.cfg.db_path)
        self.modem = FakeModem()
        self.ctrl = Controller(self.cfg, self.store, modem=self.modem, core=CORE)
        self.remote = RemoteGm(self.cfg, self.store, self.ctrl, api_key=KEY, controller_id=lambda: CONTROLLER_ID)

    def tearDown(self) -> None:
        self.ctrl.stop()
        self.store.close()
        self.tmp.cleanup()

    def game(self, mode: str = DOMINATION, joined: bool = True, **spec: Any) -> dict[str, Any]:
        body = {"name": "Domingo", "mode_id": mode, "teams": ["red", "blue"], "assignments": {"4": "zone"}, **spec}
        game = self.ctrl.create_game(body)
        if joined and mode == DOMINATION:
            # Box 4 says HELLO: the zone has a box, so a remote start is not refused (decision RJ-1).
            self.modem.rx(4, 0, "HELLO", hello_encode({"node_name": "box-4", "platform": 1, "fw_version": "0.4.0",
                                                       "core_version": "0.2.0", "tier": 0, "capabilities": [0],
                                                       "transports": 1, "epoch": 1}),
                          game_id=game["id"], epoch=1)
        return self.store.game(game["id"])

    def state(self, game: dict[str, Any]) -> str:
        return self.store.game(game["id"])["state"]


CONTROLLER_ID = "0192f3a4-5b6c-7d8e-9f01-23456789abcd"


class CommandTests(RemoteCase):
    def test_the_game_through_its_life(self) -> None:
        game = self.game()
        for what, params, state in (("start", {}, "running"), ("pause", {"reason": "medic"}, "paused"),
                                    ("resume", {}, "running"), ("end", {"reason": "time"}, "ended")):
            with self.subTest(what):
                out = self.remote.handle_command(command(game, what, params))
                self.assertEqual(out["code"], "done", out)
                self.assertEqual(self.state(game), state)
        log = self.store.remote_commands()
        self.assertEqual([e["command"] for e in reversed(log)], ["start", "pause", "resume", "end"])
        self.assertEqual({(e["user_id"], e["username"], e["result"]) for e in log}, {(USER["id"], "gm-norte", "done")})
        self.assertEqual(log[2]["params"], {"reason": "medic"})
        # The engine logged the pause with the remote GM's reason, as from the console.
        pause = [e for e in self.store.events(game["id"]) if e["type"] == "game.pause"]
        self.assertEqual(pause[0]["data"], {"reason": "medic"})

    def test_a_start_without_a_box_for_a_role_is_refused(self) -> None:
        """Without force the start guard holds (RJ-1) and the roles come back in ``missing`` (RG-1)."""
        game = self.game(joined=False)
        out = self.remote.handle_command(command(game, "start"))
        self.assertEqual(out["code"], "conflict")
        self.assertIn("zone", out["detail"])
        self.assertEqual(out["missing"], ["zone"])
        self.assertEqual(self.state(game), "ready")
        again = self.remote.handle_command(command(game, "start", {"force": False}))
        self.assertEqual((again["code"], again["missing"]), ("conflict", ["zone"]))
        self.assertEqual(self.state(game), "ready")
        self.assertEqual([e["result"] for e in self.store.remote_commands()], ["conflict", "conflict"])

    def test_a_forced_start_starts_anyway_and_is_logged(self) -> None:
        """``{"force": true}`` is the console's "Start anyway" (RG-1): logged here with force, told to the consoles."""
        game = self.game(joined=False)
        messages: list[dict[str, Any]] = []
        self.ctrl.add_listener(messages.append)
        out = self.remote.handle_command(command(game, "start", {"force": True}))
        self.assertEqual(out["code"], "done", out)
        self.assertNotIn("missing", out)
        self.assertIn("started anyway without nodes for: zone", out["detail"])
        self.assertEqual(self.state(game), "running")
        entry = self.store.remote_commands()[0]
        self.assertEqual((entry["command"], entry["params"], entry["result"]), ("start", {"force": True}, "done"))
        self.assertEqual([m["missing"] for m in messages if m.get("kind") == "start.forced"], [["zone"]])

    def test_force_with_every_box_joined_changes_nothing(self) -> None:
        game = self.game()
        out = self.remote.handle_command(command(game, "start", {"force": True}))
        self.assertEqual((out["code"], out["detail"]), ("done", f"game {game['id']} is running"))

    @unittest.skipIf(CORE is None, "the shared core library is not built")
    def test_a_message_and_a_mode_command_go_on_the_radio(self) -> None:
        game = self.game(MEDIC, assignments={"7": "medic"})
        self.ctrl.start_game(game["id"], force=True)
        out = self.remote.handle_command(command(game, "message", {"text": "5 minutos"}))
        self.assertEqual(out["code"], "done", out)
        self.assertEqual(cmd_decode(self.modem.of("CMD")[-1][1]), {"cmd": 5, "params": {"text": "5 minutos"}})
        out = self.remote.handle_command(command(game, "mode", {"name": "refill", "node": 7}))
        self.assertEqual(out["code"], "done", out)
        self.assertEqual(cmd_decode(self.modem.of("CMD")[-1][1])["params"], {"name": "refill"})
        out = self.remote.handle_command(command(game, "mode", {"name": "detonate"}))  # not declared by the game
        self.assertEqual(out["code"], "invalid")
        self.assertIn("mode commands", out["detail"])

    def test_commands_outside_the_list_are_refused_and_logged(self) -> None:
        game = self.game()
        self.ctrl.start_game(game["id"], force=True)
        sent = len(self.modem.of("CMD"))
        for what, params in (("set_owner", {"team": "red"}), ("reboot", {}), ("score", {"team": "red", "amount": 50}),
                             ("start", {"preset": "x"}), ("message", {"text": ""})):
            with self.subTest(what):
                out = self.remote.handle_command(command(game, what, params))
                self.assertEqual(out["code"], "invalid", out)
        self.assertEqual(len(self.modem.of("CMD")), sent)
        self.assertEqual(self.ctrl.score(game["id"])["teams"], {"red": 0, "blue": 0})
        self.assertEqual({e["result"] for e in self.store.remote_commands()}, {"invalid"})
        self.assertEqual(len(self.store.remote_commands()), 5)

    def test_another_game_a_stale_or_a_repeated_command(self) -> None:
        game = self.game()
        other = {**game, "game_seed": (game["game_seed"] + 1) % 2**32}
        self.assertEqual(self.remote.handle_command(command(other, "start"))["code"], "not_live")
        self.assertEqual(self.remote.handle_command(command(game, "start", sent_at=time.time() - 120))["code"],
                         "stale")
        self.assertEqual(self.state(game), "ready")
        once = command(game, "start")
        self.assertEqual(self.remote.handle_command(once)["code"], "done")
        self.ctrl.pause_game(game["id"])
        self.ctrl.resume_game(game["id"])
        again = self.remote.handle_command(copy.deepcopy(once))  # the same id: never carried out twice
        self.assertEqual(again["code"], "done")
        self.assertEqual(len([e for e in self.store.events(game["id"]) if e["type"] == "game.start"]), 1)
        self.assertEqual(self.remote.handle_command(command(game, "resume"))["code"], "conflict")  # not paused

    def test_the_log_keeps_365_days(self) -> None:
        self.store.add_remote_command({"command_id": str(uuid.uuid4()), "received_at": time.time()
                                       - (REMOTE_LOG_DAYS + 1) * 86400, "result": "done"})
        self.store.add_remote_command({"command_id": str(uuid.uuid4()), "result": "invalid"})
        self.assertEqual([e["result"] for e in self.store.remote_commands()], ["invalid"])
        self.assertGreaterEqual(SCHEMA_VERSION, 8)  # the remote GM log came with schema 8


class RemoteGmOffTests(RemoteCase):
    remote_gm = False

    def test_every_command_is_refused_while_remote_gm_is_off(self) -> None:
        game = self.game()
        for what, params in (("start", {}), ("message", {"text": "olá"}), ("end", {})):
            with self.subTest(what):
                self.assertEqual(self.remote.handle_command(command(game, what, params))["code"], "remote_gm_off")
        self.assertEqual(self.state(game), "ready")
        self.assertEqual(self.modem.of("CMD"), [])
        self.assertEqual(len(self.store.remote_commands()), 3)


class LiveTests(RemoteCase):
    @unittest.skipIf(CORE is None, "the shared core library is not built")
    def test_the_live_view(self) -> None:
        self.assertEqual(self.remote.live_body()["live"], None)
        game = self.game(MEDIC, assignments={"7": "medic"})
        self.ctrl.start_game(game["id"], force=True)
        self.ctrl._on_event({"node": 7, "seq": 1, "t": 1000, "type": "zone.captured", "team": "red", "squad": 0,
                             "prio": "normal", "data": {"zone": "alpha"}, "epoch": 1, "pkt_seq": 1})
        self.ctrl.adjust_score(game["id"], "red", -5, "penalty")
        body = self.remote.live_body()
        live = body["live"]
        self.assertEqual((live["game"]["game_id"], live["state"], live["in_charge"]), (game["id"], "running", True))
        self.assertEqual(live["totals"], {"red": -5, "blue": 0})
        self.assertEqual([e["type"] for e in live["events"]][-1], "score.delta")
        self.assertEqual(live["mode_commands"], [{"name": "refill", "roles": ["medic"]}])
        sync_format.check_live(copy.deepcopy(body))
        text = json.dumps(body)
        for secret in ("gm-secret", "read-secret", KEY, self.ctrl.transport.key.hex()):
            self.assertNotIn(secret, text)

    def test_at_most_fifty_events(self) -> None:
        game = self.game()
        self.ctrl.start_game(game["id"], force=True)
        for seq in range(1, 81):
            self.ctrl._on_event({"node": 4, "seq": seq, "t": seq, "type": "zone.captured", "team": "red", "squad": 0,
                                 "prio": "normal", "data": {}, "epoch": 1, "pkt_seq": seq})
        events = self.remote.live()["events"]
        self.assertEqual(len(events), sync_format.MAX_LIVE_EVENTS)
        self.assertEqual(events[-1]["seq"], 80)
        # Box 4 said HELLO with capabilities [0]: it is in the view, its capabilities as texts (PE24-121).
        nodes = self.remote.live()["nodes"]
        self.assertEqual([n["node_id"] for n in nodes], [4])
        self.assertEqual(nodes[0]["info"]["capabilities"], ["0"])


class FakeStream:
    """A site server's stream on a loopback socket: the RFC 6455 handshake, masked frames from the client,
    text messages in a queue, and switches to refuse the upgrade or close with a code."""

    def __init__(self, refuse: Optional[int] = None, close_with: Optional[int] = None) -> None:
        self.refuse = refuse
        self.close_with = close_with
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.received: "queue.Queue[dict[str, Any]]" = queue.Queue()
        self.headers: list[dict[str, str]] = []
        self.unmasked = 0
        self.pongs = 0
        self.conn: Optional[socket.socket] = None
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._one, args=(conn,), daemon=True).start()

    def _one(self, conn: socket.socket) -> None:
        raw = b""
        while b"\r\n\r\n" not in raw:
            chunk = conn.recv(4096)
            if not chunk:
                return
            raw += chunk
        lines = raw.split(b"\r\n\r\n")[0].decode("latin-1").split("\r\n")
        headers = {k.strip().lower(): v.strip() for k, _, v in (ln.partition(":") for ln in lines[1:])}
        headers["request"] = lines[0]
        self.headers.append(headers)
        if self.refuse:
            conn.sendall(f"HTTP/1.1 {self.refuse} Forbidden\r\nContent-Length: 0\r\n\r\n".encode())
            conn.close()
            return
        accept = ws_client.accept_key(headers["sec-websocket-key"])
        conn.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                      f"Sec-WebSocket-Accept: {accept}\r\n\r\n").encode())
        self.conn = conn
        if self.close_with:
            conn.sendall(ws_client.encode_frame(ws_client.OP_CLOSE, struct.pack("!H", self.close_with)))
        buf = b""
        while True:
            try:
                chunk = conn.recv(65536)
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while len(buf) >= 2:
                n, at = buf[1] & 0x7F, 2
                if n == 126:
                    n, at = struct.unpack("!H", buf[2:4])[0], 4
                elif n == 127:
                    n, at = struct.unpack("!Q", buf[2:10])[0], 10
                masked = bool(buf[1] & 0x80)
                need = at + (4 if masked else 0) + n
                if len(buf) < need:
                    break
                if not masked:
                    self.unmasked += 1
                    payload = buf[at:need]
                else:
                    payload = ws_client.mask(buf[at + 4:need], buf[at:at + 4])
                opcode = buf[0] & 0x0F
                buf = buf[need:]
                if opcode == ws_client.OP_TEXT:
                    self.received.put(json.loads(payload))
                elif opcode == ws_client.OP_PONG:
                    self.pongs += 1
                elif opcode == ws_client.OP_CLOSE:
                    conn.close()
                    return

    def send(self, msg: dict[str, Any], fragmented: bool = False) -> None:
        assert self.conn is not None
        data = json.dumps(msg).encode()
        if not fragmented:
            self.conn.sendall(ws_client.encode_frame(ws_client.OP_TEXT, data))
            return
        half = len(data) // 2
        first = ws_client.encode_frame(ws_client.OP_TEXT, data[:half])
        self.conn.sendall(bytes([first[0] & 0x7F]) + first[1:])  # FIN off
        self.conn.sendall(ws_client.encode_frame(ws_client.OP_CONT, data[half:]))

    def ping(self) -> None:
        assert self.conn is not None
        self.conn.sendall(ws_client.encode_frame(ws_client.OP_PING, b"hi"))

    def next(self, kind: str, timeout: float = 5.0) -> dict[str, Any]:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                msg = self.received.get(timeout=max(end - time.monotonic(), 0.01))
            except queue.Empty:
                break
            if msg.get("type") == kind:
                return msg
        raise AssertionError(f"no {kind} message")

    def close(self) -> None:
        self.sock.close()
        if self.conn is not None:
            try:
                self.conn.close()
            except OSError:
                pass


class StreamTests(RemoteCase):
    def start(self, site: FakeStream) -> RemoteGm:
        self.cfg.sync_url = site.url
        remote = RemoteGm(self.cfg, self.store, self.ctrl, api_key=KEY, controller_id=lambda: CONTROLLER_ID)
        self.ctrl.add_listener(remote.on_controller_message)
        remote.start()
        self.addCleanup(remote.stop)
        self.addCleanup(site.close)
        return remote

    def test_hello_live_and_a_command_on_the_socket(self) -> None:
        site = FakeStream()
        game = self.game()
        remote = self.start(site)
        hello = site.next("hello")
        self.assertEqual((hello["remote_gm"], hello["controller"]["id"]), (True, CONTROLLER_ID))
        sync_format.check_hello({k: v for k, v in hello.items() if k != "type"})
        headers = site.headers[0]
        self.assertEqual(headers["request"], "GET /api/v1/sync/stream HTTP/1.1")
        self.assertEqual((headers["authorization"], headers["upgrade"]), (f"Bearer {KEY}", "websocket"))
        live = site.next("live")
        self.assertEqual(live["live"]["state"], "ready")
        site.ping()
        cmd = command(game, "start")
        site.send({"type": "command", **cmd}, fragmented=True)
        result = site.next("command.result")
        self.assertEqual((result["id"], result["code"]), (cmd["id"], "done"))
        sync_format.check_result({k: v for k, v in result.items() if k != "type"})
        self.assertEqual(self.state(game), "running")
        self.assertTrue(wait_for(lambda: site.next("live")["live"]["state"] == "running", 5))
        self.assertTrue(wait_for(lambda: site.pongs >= 1, 2))
        self.assertEqual(site.unmasked, 0)  # every client frame is masked (RFC 6455 section 5.3)
        self.assertTrue(remote.status()["connected"])

    def test_a_refused_key_is_reported(self) -> None:
        for site in (FakeStream(refuse=403), FakeStream(close_with=4401)):
            with self.subTest(refuse=site.refuse, close=site.close_with):
                remote = self.start(site)
                self.assertTrue(wait_for(lambda: remote.last_error == "the site server refused the API key", 5),
                                remote.last_error)
                remote.stop()

    def test_the_stream_address(self) -> None:
        self.assertEqual(stream_url("https://site.example.org"), "wss://site.example.org/api/v1/sync/stream")
        self.assertEqual(stream_url("https://site.example.org:8443/atalaia/"),
                         "wss://site.example.org:8443/atalaia/api/v1/sync/stream")
        self.assertEqual(stream_url("http://127.0.0.1:8000"), "ws://127.0.0.1:8000/api/v1/sync/stream")


class AtakStreamTests(RemoteCase):
    """The remote ATAK relay on the same stream (Phase 4 follow-up FU5): opened with remote_gm off too."""

    remote_gm = False

    def start(self, site: FakeStream) -> RemoteGm:
        self.cfg.sync_url = site.url
        self.cfg.atak_enabled = self.cfg.atak_remote = True
        remote = RemoteGm(self.cfg, self.store, self.ctrl, api_key=KEY, controller_id=lambda: CONTROLLER_ID)
        self.reopened = 0

        def again() -> None:
            self.reopened += 1
        remote.on_relay_open = again
        remote.start()
        self.addCleanup(remote.stop)
        self.addCleanup(site.close)
        return remote

    def test_cot_goes_once_the_site_server_takes_it(self) -> None:
        site = FakeStream()
        self.game()
        remote = self.start(site)
        hello = site.next("hello")
        self.assertEqual((hello["remote_gm"], hello["atak"]), (False, True))
        sync_format.check_hello({k: v for k, v in hello.items() if k != "type"})
        self.assertTrue(wait_for(lambda: remote.connected, 5))
        events = [sync_format.cot_event(t)["xml"].encode() for t in COT_EVENTS]
        self.assertEqual(remote.push_cot(events), 0)  # not before the site server said yes
        site.send({"type": "hello.ack", "remote_gm": False, "atak_relay": True})
        self.assertTrue(wait_for(lambda: remote.atak_relay, 5))
        self.assertEqual(self.reopened, 1)  # the emitter is asked for its whole picture again
        self.assertEqual(remote.push_cot(events), len(events))
        cot = site.next("cot")
        self.assertEqual(cot["events"], [e.decode() for e in events])
        sync_format.check_cot({k: v for k, v in cot.items() if k != "type"})
        self.assertEqual(remote.status()["atak"], {"enabled": True, "relay": True, "sent": len(events)})
        # No live view leaves without the remote GM, and a command is still refused.
        self.assertFalse(any(m.get("type") == "live" for m in list(site.received.queue)))
        game = self.store.game(self.ctrl.game["id"])
        site.send({"type": "command", **command(game, "start")})
        self.assertEqual(site.next("command.result")["code"], "remote_gm_off")

    def test_a_site_server_without_the_relay(self) -> None:
        site = FakeStream()
        remote = self.start(site)
        site.next("hello")
        site.send({"type": "hello.ack", "remote_gm": False, "atak_relay": False})
        time.sleep(0.3)
        self.assertFalse(remote.atak_relay)
        self.assertEqual(remote.push_cot([b"x"]), 0)
        self.assertEqual(self.reopened, 0)

    def test_hello_without_atak_when_off(self) -> None:
        self.cfg.sync_remote_gm = True
        site = FakeStream()
        self.cfg.sync_url = site.url
        remote = RemoteGm(self.cfg, self.store, self.ctrl, api_key=KEY, controller_id=lambda: CONTROLLER_ID)
        remote.start()
        self.addCleanup(remote.stop)
        self.addCleanup(site.close)
        self.assertNotIn("atak", site.next("hello"))  # an older site server would refuse the field


class BrandingStreamTests(RemoteCase):
    """BR24: with ``[sync] branding = "site"`` the stream opens for the site server's ``field.changed`` note alone."""

    remote_gm = False

    def test_only_the_note_travels(self) -> None:
        self.cfg.sync_branding = "site"
        site = FakeStream()
        self.cfg.sync_url = site.url
        remote = RemoteGm(self.cfg, self.store, self.ctrl, api_key=KEY, controller_id=lambda: CONTROLLER_ID)
        notes: list[int] = []
        remote.on_field_changed = lambda: notes.append(1)
        self.ctrl.add_listener(remote.on_controller_message)
        remote.start()
        self.addCleanup(remote.stop)
        self.addCleanup(site.close)
        hello = site.next("hello")
        self.assertEqual((hello["remote_gm"], "atak" in hello), (False, False))
        site.send({"type": "field.changed", "sync_version": 1})
        self.assertTrue(wait_for(lambda: notes == [1], 5))
        site.send({"type": "field.changed", "sync_version": 1, "etag": "x"})  # not in the form: ignored
        site.send({"type": "field.changed", "sync_version": 2})
        site.send({"type": "field.changed", "sync_version": 1})
        self.assertTrue(wait_for(lambda: notes == [1, 1], 5))
        self.assertFalse(any(m.get("type") == "live" for m in list(site.received.queue)))  # nothing of the game
        self.assertFalse(remote.status()["enabled"])  # the remote GM stays off


def _cot_events() -> list[str]:
    from atalaia_controller import atak  # noqa: PLC0415

    now = time.time()
    return [atak.event_xml(uid="atalaia.field.node.4", cot_type=atak.TYPE_PROP, how=atak.HOW_IMAGE, lat=38.72,
                           lon=-9.14, now=now, start=now, stale=now + 60,
                           detail=atak.marker_detail("Caixa", "Atalaia: -", -1)).decode(),
            atak.drop_xml("atalaia.field.node.5", atak.TYPE_PROP, 38.72, -9.14, now).decode()]


COT_EVENTS = _cot_events()


class WsClientTests(unittest.TestCase):
    def test_the_accept_key_of_rfc_6455(self) -> None:
        # RFC 6455 section 1.3's example.
        self.assertEqual(ws_client.accept_key("dGhlIHNhbXBsZSBub25jZQ=="), "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")

    def test_masking(self) -> None:
        # RFC 6455 section 5.7: "Hello" masked with 37 fa 21 3d.
        frame = ws_client.encode_frame(ws_client.OP_TEXT, b"Hello", bytes.fromhex("37fa213d"))
        self.assertEqual(frame.hex(), "818537fa213d7f9f4d5158")
        self.assertEqual(ws_client.encode_frame(ws_client.OP_TEXT, b"Hello").hex(), "810548656c6c6f")
        self.assertEqual(len(ws_client.encode_frame(ws_client.OP_TEXT, b"x" * 300)), 304)
        self.assertEqual(len(ws_client.encode_frame(ws_client.OP_TEXT, b"x" * 70000)), 70010)

    def test_a_masked_or_reserved_frame_from_the_server_breaks_the_link(self) -> None:
        a, b = socket.socketpair()
        self.addCleanup(a.close)
        self.addCleanup(b.close)
        ws = ws_client.WebSocket(a)
        b.sendall(ws_client.encode_frame(ws_client.OP_TEXT, b"hi", b"abcd"))
        with self.assertRaises(ws_client.WsError) as caught:
            ws.recv(1)
        self.assertEqual(caught.exception.code, 1002)
        a2, b2 = socket.socketpair()
        self.addCleanup(a2.close)
        self.addCleanup(b2.close)
        ws = ws_client.WebSocket(a2)
        b2.sendall(bytes([0xC1, 0x00]))  # RSV1: no extension was negotiated
        with self.assertRaises(ws_client.WsError):
            ws.recv(1)

    def test_a_partial_frame_waits(self) -> None:
        a, b = socket.socketpair()
        self.addCleanup(a.close)
        self.addCleanup(b.close)
        ws = ws_client.WebSocket(a)
        frame = ws_client.encode_frame(ws_client.OP_TEXT, "olá".encode())
        b.sendall(frame[:3])
        self.assertIsNone(ws.recv(0.05))
        b.sendall(frame[3:])
        self.assertEqual(ws.recv(1), "olá")


class SettingsTests(unittest.TestCase):
    def test_remote_gm_needs_the_sync_and_is_off_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(config(tmp).sync_remote_gm)
            with self.assertRaisesRegex(ConfigError, "remote_gm needs sync.enabled"):
                config(tmp, sync_remote_gm=True)

    def test_remote_atak_needs_the_feed_and_the_sync_and_is_off_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config(tmp)
            self.assertEqual((cfg.atak_remote, cfg.atak_remote_players), (False, False))
            sync = {"sync_enabled": True, "sync_url": "https://site.example.org", "sync_api_key": KEY}
            with self.assertRaisesRegex(ConfigError, "atak.remote needs atak.enabled and sync.enabled"):
                config(tmp, atak_enabled=True, atak_remote=True)
            with self.assertRaisesRegex(ConfigError, "atak.remote needs atak.enabled and sync.enabled"):
                config(tmp, atak_remote=True, **sync)
            with self.assertRaisesRegex(ConfigError, "atak.remote_players needs atak.remote"):
                config(tmp, atak_enabled=True, atak_remote_players=True, **sync)
            cfg = config(tmp, atak_enabled=True, atak_remote=True, atak_remote_players=True, **sync)
            bundle = build(cfg, core=CORE, load_core_lib=False)
            try:  # the stream is built for the relay alone, and the emitter pushes on it
                self.assertIsNotNone(bundle.remote)
                assert bundle.atak is not None
                self.assertIs(bundle.atak.remote, bundle.remote)
                self.assertEqual(bundle.remote.on_relay_open, bundle.atak.resend_all)
            finally:
                bundle.controller.stop()
                bundle.store.close()

    def test_built_only_when_on_and_the_log_needs_the_gm_token(self) -> None:
        for on in (False, True):
            with self.subTest(remote_gm=on), tempfile.TemporaryDirectory() as tmp:
                cfg = config(tmp, sync_enabled=True, sync_url="https://site.example.org", sync_api_key=KEY,
                             sync_remote_gm=on)
                bundle = build(cfg, core=CORE, load_core_lib=False)
                try:
                    self.assertEqual(bundle.remote is not None, on)
                    client = TestClient(bundle.app)  # no lifespan: nothing connects to the site server
                    self.assertEqual(client.get("/api/v1/remote-gm", headers=READ).status_code, 403)
                    body = client.get("/api/v1/remote-gm", headers=GM).json()
                    self.assertEqual((body["enabled"], body["log"]), (on, []))
                    status = client.get("/api/v1/controller", headers=GM).json()["sync"]["remote_gm"]
                    self.assertEqual(status["enabled"], on)
                    client.close()
                finally:
                    bundle.controller.stop()
                    bundle.store.close()


if __name__ == "__main__":
    unittest.main()
