# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The API's shared contract cases (protocol/vectors/controller_api.json) against this controller.

    cd controller && python -m unittest tests.test_api_contract   (or discover -s tests)

The same cases run against the Android field controller (decision PE24,
app/test/controller/api_contract_test.dart): this controller is the
reference, so every case must pass here first. Each case gets a fresh
controller with a recording modem and a clock that only moves on an
``advance_ms`` step, which also runs the controller's tick once; a
``restart`` step stops the controller, closes its SQLite store and starts a
new controller on the same file (slice S3), with the case's
``persist_game_key`` (the default, true, unless the case says). Stream
steps (``ws_*``, ``ws``) use the TestClient's WebSocket sessions, all on the
one event loop of the entered TestClient; ``mqtt`` steps read what the MQTT
bridge (mqtt.py) published to a recording client; the ``mqtt_acl`` checks
run against the Mosquitto ACL the Pi installs (controller/deploy/atalaia.acl).
Field check-in and player positions (slice S5) are set up on every controller
as main.py sets them up, with HTTPS off (no field CA), the wall clock at the
vectors' ``wall_start`` moving with the clock and the field's day in UTC;
request and ``ws_connect`` steps may give a player token (``bearer``), and
``ws_closed`` reads a connection to its end. The field plan and the radio channel
(slice S7a, the vectors' ``field_and_radio`` block) add requests with a raw body
(``raw``: an uploaded image), answers that are not JSON (``content_type``,
``body_base64``) and the noise scan's steps (``noise``, ``hold_measure``,
``scan_wait``) on the recording modem.

A ``tag_check`` step (decision TW-1) checks a player tag the controller made with
``POST /games/{id}/tags``: its NDEF record and memory hold the payload, which decodes
with the live game's key to the player, team and game asked for.

Slice S7 (failover, the vectors' ``s7`` block): a case may set ``failover_mode``
(manual when not given); ``rx`` steps may be another controller's TIME or CLAIM (their
fields by name); ``join_encode`` seals a join payload with the case's join key and saves
its text (a standby's join, made by the controller that leads).

Slice S7c (boxes over the radio, adoption and firmware updates on the phone
controller): adoption (adoption.py, USB off as on the phone) and firmware updates
(firmware_updates.py, the case's ``firmware_keys``, releases in the case's folder,
the wall clock) are set up on every controller; a case may set ``https`` (the
controller serves HTTPS: a field CA and an address for join keys 13 and 14). Field
steps: ``field_rx`` is a field frame a box sends (its fields, sealed with the case's
join key, the nonce from that device's own counter; ``replay`` sends the previous
one again), ``pair_rx`` a pair frame (in the clear), ``field_tx`` the field and pair
frames the controller sent since the last look, decoded (``save`` keeps values),
``field_ack`` the radio's FIELD_ACK, ``pair_box`` and ``pair_box_done`` play an
unadopted box's side of a pairing run with a code (its REPLY to the last START, its
DONE to the last KEY). A request may send raw bytes (``body_hex``, ``body_text``)
and headers, and sign the body with ``mac_key`` (X-Atalaia-Mac, a box's report).

Slice S7b (presets, mode packages, scenarios and branding): the vectors'
``fixtures``' values are saved in every case; a case's ``mode_keys``,
``mode_revoked`` and ``box_keys`` set up signed mode packages and the modes sent to
boxes; a raw body may name its ``content_type``, and an answer's ``headers`` are
matched.
"""

from __future__ import annotations

import base64
import contextlib
import datetime
import hashlib
import hmac
import json
import re
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import paho.mqtt.client as paho
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from support import CORE, FakeModem, config
from atalaia_controller.adoption import Adoption
from atalaia_controller.api import Auth, create_app
from atalaia_controller.checkin import Checkin
from atalaia_controller.engine import Controller
from atalaia_controller.firmware_updates import FirmwareUpdates
from atalaia_controller.mode_fetch import ModeFetch
from atalaia_controller.signed_modes import SignedModes
from atalaia_controller.positions import Positions
from atalaia_controller import prop_link
from atalaia_controller.mqtt import MqttBridge
from atalaia_controller.prop_link import PropLinks
from atalaia_controller.store import Store
from atalaia_controller.ws import Hub
from atalaia_sim import codec, cpace, packet
from atalaia_sim import field_frame as ff
from atalaia_sim import join as joinfmt
from atalaia_sim import tag as tagfmt
from atalaia_sim import pair_frame as pf
from atalaia_sim.packet import hello_encode, state_encode
from atalaia_sim.protocol import MESSAGE_TYPES

ROOT = Path(__file__).resolve().parents[2]
VECTORS = json.loads((ROOT / "protocol" / "vectors" / "controller_api.json").read_text(encoding="utf-8"))
ACL = ROOT / "controller" / "deploy" / "atalaia.acl"
_VAR = re.compile(r"\$\{(\w+)\}")


def substitute(value: Any, saved: dict[str, Any]) -> Any:
    """'${name}' as a whole string is the saved value; inside a string, its text."""
    if isinstance(value, str):
        whole = _VAR.fullmatch(value)
        if whole:
            return saved[whole.group(1)]
        return _VAR.sub(lambda m: str(saved[m.group(1)]), value)
    if isinstance(value, list):
        return [substitute(v, saved) for v in value]
    if isinstance(value, dict):
        return {k: substitute(v, saved) for k, v in value.items()}
    return value


def mismatch(pattern: Any, actual: Any, where: str = "$") -> str | None:
    """Why actual does not match pattern (the rules in the vectors' description), or None."""
    if isinstance(pattern, dict) and set(pattern) == {"$contains"}:
        if not isinstance(actual, list):
            return f"{where}: a list was expected, got {actual!r}"
        for i, p in enumerate(pattern["$contains"]):
            if all(mismatch(p, a) is not None for a in actual):
                return f"{where}: no element matches $contains[{i}] {p!r}"
        return None
    if isinstance(pattern, dict):
        if not isinstance(actual, dict):
            return f"{where}: an object was expected, got {actual!r}"
        for k, p in pattern.items():
            if p == "$absent":
                if k in actual:
                    return f"{where}.{k}: should be absent, is {actual[k]!r}"
                continue
            if k not in actual:
                return f"{where}.{k}: missing"
            if p == "$any":
                continue
            why = mismatch(p, actual[k], f"{where}.{k}")
            if why:
                return why
        return None
    if isinstance(pattern, list):
        if not isinstance(actual, list) or len(actual) != len(pattern):
            return f"{where}: {len(pattern)} elements were expected, got {actual!r}"
        for i, (p, a) in enumerate(zip(pattern, actual)):
            why = mismatch(p, a, f"{where}[{i}]")
            if why:
                return why
        return None
    if pattern == "$any":
        return None
    if type(pattern) is not type(actual) and not (isinstance(pattern, (int, float))
                                                  and isinstance(actual, (int, float))
                                                  and not isinstance(actual, bool)
                                                  and not isinstance(pattern, bool)):
        return f"{where}: {pattern!r} was expected, got {actual!r}"
    return None if pattern == actual else f"{where}: {pattern!r} was expected, got {actual!r}"


def dig(value: Any, path: str) -> Any:
    for part in path.split("."):
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


class RecordingMqtt:
    """Stands in for the bridge's paho client: what it published, in order."""

    def __init__(self) -> None:
        self.published: list[dict[str, Any]] = []

    def publish(self, topic: str, payload: bytes, qos: int = 0, retain: bool = False) -> SimpleNamespace:
        self.published.append({"topic": topic, "qos": qos, "retain": retain, "payload": json.loads(payload)})
        return SimpleNamespace(rc=0)


PRIOS = ("telemetry", "normal", "critical", "reserved")
TYPE_NAMES = {v: k for k, v in MESSAGE_TYPES.items()}


def _plain(value: Any) -> Any:
    """Decoded payload values as JSON: bytes in hex."""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).hex()
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


class RecordingModem(FakeModem):
    """The FakeModem, with what the controller asked of the radio in one ordered list, as the
    shared cases' 'tx' steps see it (packets with their header and payload by field name, and
    the modem commands)."""

    def __init__(self) -> None:
        super().__init__()
        self.log: list[dict[str, Any]] = []

    def configure(self, game_id, node_id, epoch, max_hops, channel_hz, key) -> None:
        super().configure(game_id, node_id, epoch, max_hops, channel_hz, key)
        self.log.append({"kind": "configure", "game_id": game_id, "node_id": node_id, "epoch": epoch,
                         "max_hops": max_hops, "channel_hz": channel_hz})

    def clear(self) -> None:
        super().clear()
        self.log.append({"kind": "clear"})

    def set_channel(self, channel_hz: int) -> bool:
        self.log.append({"kind": "channel", "channel_hz": channel_hz})
        return super().set_channel(channel_hz)

    def set_peer_epochs(self, epochs: dict[int, int]) -> None:
        super().set_peer_epochs(epochs)
        self.log.append({"kind": "peer_epochs", "epochs": {str(k): v for k, v in sorted(epochs.items())}})

    def measure(self, channel_hz: int, dwell_ms: int, cad: bool = True, timeout=None):
        # Slice S7a: the noise scan's MEASUREs, answered from self.noise (FakeModem).
        self.log.append({"kind": "measure", "channel_hz": channel_hz, "dwell_ms": dwell_ms})
        return super().measure(channel_hz, dwell_ms, cad, timeout)

    def send_packet(self, header, payload: bytes) -> bool:
        if not super().send_packet(header, payload):
            return False
        name = TYPE_NAMES.get(header.type, str(header.type))
        fields = (_plain(packet._decode_payload(payload, packet._key_table(name)))
                  if name in packet._PF else {})
        self.log.append({"kind": name, "source": header.source, "seq": header.seq,
                         "hop_limit": header.hop_limit, "prio": PRIOS[(header.version_flags >> 3) & 3],
                         "ack": bool(header.version_flags & 4), "fields": fields})
        return True


class ContractCase(unittest.TestCase):
    def run_case(self, case: dict[str, Any]) -> None:
        with tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
            cfg = config(tmp, gm_token=VECTORS["tokens"]["gm"], read_token=VECTORS["tokens"]["read"],
                         persist_game_key=case.get("persist_game_key", True), adopt_usb=False,
                         controller_pace_ms=case.get("controller_pace_ms", 0),
                         failover_mode=case.get("failover_mode", "manual"),
                         firmware_release_keys=case.get("firmware_keys", []))
            env = SimpleNamespace(cfg=cfg, case=case, modem=RecordingModem(), mqtt=RecordingMqtt(), now=[0.0],
                                  saved=dict(VECTORS.get("fixtures", {}).get("values", {})), stack=stack,
                                  sentinel=0, tmp=tmp, field_seen=0, senders={}, last_field=None, pair=None)
            self.boot(env)
            for i, step in enumerate(case["steps"]):
                with self.subTest(step=i):
                    self.run_step(step, env)

    @staticmethod
    def boot(env: SimpleNamespace) -> None:
        """A controller on the case's store (a new one after a 'restart' step), with its API, stream and
        MQTT bridge; the clock, the radio and the recorded MQTT messages go on across restarts."""
        now = env.now
        env.store = Store(env.cfg.db_path)
        env.ctrl = Controller(env.cfg, env.store, modem=env.modem, core=CORE, clock=lambda: now[0],
                              join_key=bytes.fromhex(env.case.get("join_key", "")))
        # The controller then the store, on a restart or at the end of the case.
        env.stops = contextlib.ExitStack()
        env.stops.callback(env.store.close)
        env.stops.callback(env.ctrl.stop)
        env.stack.callback(env.stops.close)
        env.hub = Hub()
        if "stream_max_queue" in env.case:
            env.hub.max_queue = env.case["stream_max_queue"]
        MqttBridge(env.cfg, env.ctrl).client = env.mqtt  # type: ignore[assignment]
        PropLinks(env.ctrl)  # WS /api/v1/prop
        wall = lambda: VECTORS["wall_start"] + now[0]  # noqa: E731
        svc = Checkin(env.ctrl)  # no field CA: HTTPS off, as on the phone until its slice S6
        svc._wall = wall
        svc._tz = datetime.timezone.utc
        Positions(env.ctrl, wall=wall)
        # Slice S7c: adoption (no USB, as on a phone) and firmware updates, as main.build sets them up.
        Adoption(env.ctrl, lister=lambda: [])
        FirmwareUpdates(env.ctrl, Path(env.tmp) / "firmware", env.cfg.firmware_release_keys, clock=wall)
        # Slice S7b: signed mode packages and the modes sent to boxes, as main.build sets them up.
        SignedModes(env.ctrl, env.case.get("mode_keys", []), env.case.get("mode_revoked", []), "")
        ModeFetch(env.ctrl, env.case.get("box_keys", []), clock=wall)
        if env.case.get("https"):
            env.ctrl.ca_sha256 = bytes(range(32))
            env.ctrl.link_urls = ["https://192.0.2.10:8443"]
        # Entered, so that every WebSocket session runs on one event loop with the hub.
        env.client = env.stack.enter_context(
            TestClient(create_app(env.ctrl, env.hub, Auth(env.cfg.gm_token, env.cfg.read_token))))
        env.sockets = {}
        env.props = {}

    def check(self, pattern: Any, actual: Any, where: str, env: SimpleNamespace) -> None:
        why = mismatch(substitute(pattern, env.saved), actual)
        self.assertIsNone(why, f"{where}: {why}")

    @staticmethod
    def until_sentinel(ws: Any, env: SimpleNamespace) -> list[dict[str, Any]]:
        """Every message the connection got since the last look: a marker goes through the
        hub after them, and what came before it is returned (without the markers sent
        to every connection for the other connections' looks)."""
        env.sentinel += 1
        mark = env.sentinel
        env.hub.publish({"type": "pong", "sentinel": mark})
        got = []
        while True:
            m = ws.receive_json()
            if m.get("type") == "pong" and "sentinel" in m:
                if m["sentinel"] == mark:
                    return got
                continue
            got.append(m)

    def run_step(self, step: dict[str, Any], env: SimpleNamespace) -> None:
        if "restart" in step:
            # The Pi reboots: the old controller stops and its store closes; its stream
            # connections are left behind (closed with the case).
            env.stops.close()
            self.boot(env)
            return
        if "advance_ms" in step:
            env.now[0] += step["advance_ms"] / 1000
            env.ctrl.tick()
            return
        if "rx" in step:
            rx = step["rx"]
            game_id = env.ctrl.game["id"]
            kind = rx["type"]
            if kind == "HELLO":
                hello = dict(rx["hello"])
                if "device_id" in hello:
                    hello["device_id"] = bytes.fromhex(substitute(hello["device_id"], env.saved))
                payload = hello_encode(hello)
            elif kind == "STATE":
                state = dict(rx["state"])
                state["counters"] = {int(k): v for k, v in state["counters"].items()}
                payload = state_encode(state)
            elif kind == "EVENT":
                payload = codec.encode_event(rx["event"])
            elif kind == "TIME":
                # Slice S7 (failover): another controller's beacon, its fields by name.
                payload = packet.time_encode(rx["time"])
            elif kind == "CLAIM":
                claim = dict(rx["claim"])
                if "last_ack_seq" in claim:
                    claim["last_ack_seq"] = {int(k): v for k, v in claim["last_ack_seq"].items()}
                payload = packet.claim_encode(claim)
            else:
                raise ValueError(f"unknown rx type {kind}")
            env.modem.rx(rx["source"], rx["seq"], kind, payload, game_id=game_id, epoch=rx.get("epoch", 0),
                         ack=rx.get("ack", False))
            return
        if "tag_check" in step:
            # A player tag the controller made (POST /games/{id}/tags): its NDEF bytes, memory and
            # payload agree, and the payload decodes with the live game's key to what was asked.
            spec = substitute(step["tag_check"], env.saved)
            game_id = spec["game_id"]
            payload = bytes.fromhex(spec["payload"])
            self.assertEqual(spec["ndef"], joinfmt.ndef_record(payload, tagfmt.NDEF_TYPE).hex(), "the NDEF record")
            self.assertEqual(spec["memory"], tagfmt.to_ndef_tag(payload).hex(), "the Type 2 memory")
            self.assertEqual(tagfmt.from_ndef_tag(bytes.fromhex(spec["memory"])), payload, "memory reads back")
            read = tagfmt.decode(payload, game_id, env.ctrl.game_key(game_id), spec["teams"])
            self.assertEqual(read, {"player": spec["player"], "team": spec["team"], "game_id": game_id})
            return
        if "radio_state" in step:
            # The modem's link went down or came back.
            env.modem.state = step["radio_state"]
            env.modem.on_state(step["radio_state"])
            return
        if "tx_ack" in step:
            env.modem.on_tx_ack(step["tx_ack"]["seq"], step["tx_ack"]["status"])
            return
        if "ws_connect" in step:
            self.ws_connect(step, env)
            return
        if "ws" in step:
            got = self.until_sentinel(env.sockets[step["ws"]], env)
            self.check(step["messages"], got, f"stream {step['ws']}", env)
            return
        if "ws_closed" in step:
            # Every message until the controller closes the connection.
            ws = env.sockets.pop(step["ws_closed"])
            got = []
            with self.assertRaises(WebSocketDisconnect) as ctx:
                while True:
                    m = ws.receive_json()
                    if m.get("type") == "pong" and "sentinel" in m:
                        continue  # the markers of earlier looks at other connections
                    got.append(m)
            self.check(step["messages"], got, f"stream {step['ws_closed']}", env)
            self.assertEqual(ctx.exception.code, step["close"])
            return
        if "ws_send" in step:
            ws = env.sockets[step["ws_send"]]
            ws.send_json(step["json"])
            self.check(step["reply"], ws.receive_json(), f"stream {step['ws_send']}: the reply", env)
            return
        if "ws_flood" in step:
            # More messages than the client takes: all handed to the clients in one turn of
            # the event loop, before any of them is sent.
            msgs = [{"type": "system", "kind": "test", "i": i} for i in range(step["count"])]
            hub = env.hub
            assert hub._loop is not None
            hub._loop.call_soon_threadsafe(lambda: [hub._fanout(m) for m in msgs])
            ws = env.sockets.pop(step["ws_flood"])
            with self.assertRaises(WebSocketDisconnect) as ctx:
                while True:
                    ws.receive_json()
            self.assertEqual(ctx.exception.code, step["close"])
            return
        if "prop_connect" in step:
            self.prop_connect(step, env)
            return
        if "prop_send" in step:
            env.props[step["prop_send"]].send_json(substitute(step["json"], env.saved))
            return
        if "prop" in step:
            # Every message since the last look: a ping goes after them, its pong ends the list.
            ws = env.props[step["prop"]]
            ws.send_json({"type": "ping"})
            got = []
            while (m := ws.receive_json()) != {"type": "pong"}:
                got.append(m)
            self.check(step["messages"], got, f"prop {step['prop']}", env)
            return
        if "prop_closed" in step:
            ws = env.props.pop(step["prop_closed"])
            got = []
            with self.assertRaises(WebSocketDisconnect) as ctx:
                while True:
                    got.append(ws.receive_json())
            self.check(step["messages"], got, f"prop {step['prop_closed']}", env)
            self.assertEqual(ctx.exception.code, step["close"])
            return
        if "join_encode" in step:
            # Slice S7 (failover): a join payload sealed with the case's field join key, as
            # another controller makes one (a standby's, kind "controller"); its text is saved.
            fields = dict(substitute(step["join_encode"], env.saved))
            fields["game_key"] = bytes.fromhex(fields["game_key"])
            text = joinfmt.to_text(joinfmt.encode(fields, bytes.fromhex(env.case["join_key"])))
            env.saved[step["save"]] = text
            return
        if "join_decode" in step:
            # A join payload's text, opened with the case's field join key.
            text = substitute(step["join_decode"], env.saved)
            j = joinfmt.decode(joinfmt.from_text(text), bytes.fromhex(env.case["join_key"]))
            self.check(step["json"], _plain(j), "the join payload", env)
            for name, path in step.get("save", {}).items():
                env.saved[name] = dig(_plain(j), path)
            return
        if self.field_step(step, env):
            return
        if "tx" in step:
            got = list(env.modem.log)
            env.modem.log.clear()
            kinds = step.get("kinds")
            if kinds is not None:
                got = [e for e in got if e["kind"] in kinds]
            self.check(step["tx"], got, "the radio", env)
            return
        if "noise" in step:
            # Slice S7a: what the radio measures on each channel: [p90 dBm, CAD detections of 10].
            for hz, (p90, hits) in step["noise"].items():
                env.modem.noise[int(hz)] = (p90, hits)
            return
        if "hold_measure" in step:
            # Measurements wait (the scan stays running) until a 'scan_wait' step.
            env.modem.measure_gate = threading.Event()
            return
        if "scan_wait" in step:
            # Lets held measurements go and waits until the scan has ended.
            gate = env.modem.measure_gate
            env.modem.measure_gate = None
            if gate is not None:
                gate.set()
            if env.ctrl.scan is not None:
                env.ctrl.scan.join(10)
                self.assertFalse(env.ctrl.scan.running, "the scan did not end")
            return
        if "mqtt" in step:
            got = list(env.mqtt.published)
            env.mqtt.published.clear()
            self.check(step["mqtt"], got, "MQTT", env)
            return
        req = substitute(step["request"], env.saved)
        headers = {}
        token = req.get("token", "none")
        if "bearer" in req:
            headers["Authorization"] = f"Bearer {req['bearer']}"
        elif token == "bad":
            headers["Authorization"] = "Bearer not-a-token"
        elif token != "none":
            headers["Authorization"] = f"Bearer {VECTORS['tokens'][token]}"
        kwargs: dict[str, Any] = {"headers": headers}
        if "body" in req:
            kwargs["json"] = req["body"]
        if "raw" in req:
            # Slice S7a: a raw body (an uploaded image), zero bytes added up to 'size' if given.
            raw = base64.b64decode(req["raw"].get("base64", ""))
            raw += bytes(max(0, req["raw"].get("size", 0) - len(raw)))
            kwargs["content"] = raw
            headers["Content-Type"] = req["raw"]["content_type"]
        # Slices S7c and S7b: raw bytes (hex or text) with their type, signed with 'mac_key' as a box
        # signs its report.
        raw_body = bytes.fromhex(req["body_hex"]) if "body_hex" in req else \
            req["body_text"].encode("utf-8") if "body_text" in req else None
        if raw_body is not None:
            kwargs["content"] = raw_body
            headers["Content-Type"] = req.get("content_type", "application/octet-stream")
            if "mac_key" in req:
                headers["X-Atalaia-Mac"] = hmac.new(bytes.fromhex(req["mac_key"]), raw_body,
                                                    hashlib.sha256).hexdigest()
        headers.update(req.get("headers", {}))
        r = env.client.request(req["method"], req["path"], **kwargs)
        self.assertEqual(r.status_code, step["status"], f"{req['method']} {req['path']}: {r.text[:500]}")
        where = f"{req['method']} {req['path']}"
        if "headers" in step:
            # Slice S7b: the answer's headers, by lower-case name.
            got = {k.lower(): v for k, v in r.headers.items()}
            self.check({k.lower(): v for k, v in step["headers"].items()}, got, where + ": headers", env)
        ctype = r.headers.get("content-type", "").split(";")[0].strip()
        if "content_type" in step:
            self.assertEqual(ctype, step["content_type"], where)
        if "body_base64" in step:
            self.assertEqual(r.content, base64.b64decode(step["body_base64"]), where)
        if "text" in step:
            # A plain answer (a release text): its text, exactly.
            self.assertEqual(r.text, substitute(step["text"], env.saved))
            return
        if "bytes_sha256" in step:
            self.assertEqual(hashlib.sha256(r.content).hexdigest(), substitute(step["bytes_sha256"], env.saved))
            return
        body = r.json() if ctype == "application/json" else None
        if "json" in step:
            self.check(step["json"], body, f"{req['method']} {req['path']}", env)
        for name, path in step.get("save", {}).items():
            env.saved[name] = dig(body, path)

    def field_step(self, step: dict[str, Any], env: SimpleNamespace) -> bool:
        """The field and pair frame steps (slice S7c); False for any other step."""
        join_key = bytes.fromhex(env.case.get("join_key", "00" * 32))
        if "field_rx" in step:
            spec = substitute(step["field_rx"], env.saved)
            if spec.get("replay"):
                frame = env.last_field
            else:
                msg = {k: bytes.fromhex(v) if k in ("device_id", "token", "key_tag", "chunk") else v
                       for k, v in spec.items()}
                sender = msg.get("device_id", bytes(8))
                if sender.hex() not in env.senders:
                    env.senders[sender.hex()] = ff.NonceSource(join_key, sender)
                frame = ff.encode(ff.field_key(join_key), msg, env.senders[sender.hex()].next())
            env.last_field = frame
            env.modem.on_field_rx(frame, -61, 7)
            return True
        if "pair_rx" in step:
            spec = substitute(step["pair_rx"], env.saved)
            msg = {k: bytes.fromhex(v) if k in ("pair_id", "sid", "point", "tag", "fingerprint") else v
                   for k, v in spec.items()}
            env.modem.on_field_rx(pf.encode(msg), -62, 6)
            return True
        if "field_ack" in step:
            env.modem.on_field_ack(step["field_ack"]["id"], step["field_ack"]["status"])
            return True
        if "field_tx" in step:
            got = [self.field_json(f, join_key) for f in env.modem.fields[env.field_seen:]]
            env.field_seen = len(env.modem.fields)
            kinds = step.get("kinds")
            if kinds is not None:
                got = [g for g in got if g["kind"] in kinds]
            self.check(step["field_tx"], got, "the field frames", env)
            for name, path in step.get("save", {}).items():
                env.saved[name] = dig(got, path)
            return True
        if "pair_box" in step:
            # An unadopted box answers the last START with its own code.
            spec = step["pair_box"]
            start = self.last_pair(env, "start")
            yb_secret = bytes.fromhex(spec.get("yb", "6b" * 32))
            g = pf.generator(spec["code"], start["pair_id"], start["sid"])
            yb = cpace.scalar_mult(yb_secret, g)
            k = cpace.scalar_mult_vfy(yb_secret, start["point"])
            keys = pf.keys(pf.isk(start["sid"], k, start["point"], yb), start["sid"])
            env.pair = (start, keys)
            env.modem.on_field_rx(pf.encode({"kind": "reply", "pair_id": start["pair_id"], "sid": start["sid"],
                                             "point": yb, "tag": pf.tag_reply(keys)}), -62, 6)
            return True
        if "pair_box_done" in step:
            # The box checks KEY, opens the join key and answers DONE with its result.
            spec = step["pair_box_done"]
            start, keys = env.pair
            key = self.last_pair(env, "key")
            self.assertEqual(key["tag"], pf.tag_key(keys), "KEY's confirmation")
            join, name = pf.open_key(keys, key["nonce"], key["pair_id"], key["sid"], key["sealed"])
            self.check(spec.get("opened", {}), {"join_key": join.hex(), "field_name": name}, "the sealed key", env)
            result = spec.get("result", "adopted")
            fp = bytes.fromhex(spec["fingerprint"]) if "fingerprint" in spec else pf.fingerprint_bytes(join)
            env.modem.on_field_rx(pf.encode({"kind": "done", "pair_id": key["pair_id"], "sid": key["sid"],
                                             "result": result, "fingerprint": fp,
                                             "tag": pf.tag_done(keys, result, fp)}), -62, 6)
            return True
        return False

    @staticmethod
    def field_json(frame: bytes, join_key: bytes) -> dict[str, Any]:
        """A frame the controller sent, as the cases see it: its kind and fields, bytes in hex."""
        if pf.is_frame(frame):
            return {"type": "pair", **_plain(pf.decode(frame))}
        return {"type": "field", **_plain(ff.decode(ff.field_key(join_key), frame))}

    def last_pair(self, env: SimpleNamespace, kind: str) -> dict[str, Any]:
        for frame in reversed(env.modem.fields):
            if pf.is_frame(frame):
                msg = pf.decode(frame)
                if msg["kind"] == kind:
                    return msg
        self.fail(f"the controller sent no {kind.upper()}")

    def prop_connect(self, step: dict[str, Any], env: SimpleNamespace) -> None:
        """An Android prop's link (protocol/prop-link.md): the challenge, the proof with the key given
        (hex), then the welcome, or the refusal and the close code."""
        def run(ws: Any) -> None:
            challenge = ws.receive_json()
            self.check({"type": "challenge", "version": 1, "nonce": "$any"}, challenge, "the challenge", env)
            nonce = base64.urlsafe_b64decode(challenge["nonce"] + "=" * (-len(challenge["nonce"]) % 4))
            key = bytes.fromhex(substitute(step["key"], env.saved))
            gid = substitute(step.get("game_id", "${gid}"), env.saved)
            node = step["node_id"]
            proof = base64.urlsafe_b64encode(prop_link.proof(key, nonce, gid, node)).rstrip(b"=").decode()
            ws.send_json({"type": "auth", "game_id": gid, "node_id": node, "proof": proof})

        if "close" in step:
            got = []
            with self.assertRaises(WebSocketDisconnect) as ctx:
                with env.client.websocket_connect("/api/v1/prop") as ws:
                    run(ws)
                    while True:
                        got.append(ws.receive_json())
            self.check(step["messages"], got, f"prop {step['prop_connect']}", env)
            self.assertEqual(ctx.exception.code, step["close"])
            return
        ws = env.stack.enter_context(env.client.websocket_connect("/api/v1/prop"))
        run(ws)
        env.props[step["prop_connect"]] = ws
        self.check(step["welcome"], ws.receive_json(), f"prop {step['prop_connect']}: welcome", env)

    def ws_connect(self, step: dict[str, Any], env: SimpleNamespace) -> None:
        token = step.get("token", "none")
        secret = "not-a-token" if token == "bad" else VECTORS["tokens"].get(token)
        if "bearer" in step:
            secret = substitute(step["bearer"], env.saved)
        path, headers = "/api/v1/stream", {}
        if secret is not None and step.get("via", "query") == "header":
            headers["Authorization"] = f"Bearer {secret}"
        elif secret is not None:
            path += f"?token={secret}"
        if "close" in step:
            with self.assertRaises(WebSocketDisconnect) as ctx:
                with env.client.websocket_connect(path, headers=headers) as ws:
                    ws.receive_json()
            self.assertEqual(ctx.exception.code, step["close"])
            return
        ws = env.stack.enter_context(env.client.websocket_connect(path, headers=headers))
        env.sockets[step["ws_connect"]] = ws
        self.check(step["hello"], ws.receive_json(), f"stream {step['ws_connect']}: hello", env)


def _make(case: dict[str, Any]):
    def test(self: ContractCase) -> None:
        if CORE is None:
            self.skipTest("the core library is not built")
        self.run_case(case)
    return test


# The cases, then slice S7a's block (the field plan and the radio channel), then slice S7's (failover, ...).
for _n, _case in enumerate(VECTORS["cases"] + VECTORS["field_and_radio"]["cases"] + VECTORS["s7"]["cases"]):
    setattr(ContractCase, f"test_{_n:02d}_" + re.sub(r"\W+", "_", _case["name"]).strip("_").lower(),
            _make(_case))


def parse_acl(text: str) -> dict[str, list[tuple[str, str]]]:
    """Mosquitto's acl_file: 'user NAME', then 'topic [read|write|readwrite] PATTERN' lines."""
    rules: dict[str, list[tuple[str, str]]] = {}
    user = None
    for line in text.splitlines():
        words = line.split()
        if not words or words[0].startswith("#"):
            continue
        if words[0] == "user":
            user = words[1]
            rules.setdefault(user, [])
        elif words[0] == "topic" and user is not None:
            access, pattern = (words[1], words[2]) if len(words) == 3 else ("readwrite", words[1])
            rules[user].append((access, pattern))
    return rules


def acl_allows(rules: dict[str, list[tuple[str, str]]], user: str, topic: str, access: str) -> bool:
    return any(a in (access, "readwrite") and paho.topic_matches_sub(p, topic) for a, p in rules.get(user, []))


class PropProofVectors(unittest.TestCase):
    """The prop link's proof against protocol/vectors/prop_link.json (the app checks the same)."""

    def test_vectors(self):
        vectors = json.loads((ROOT / "protocol" / "vectors" / "prop_link.json").read_text(encoding="utf-8"))
        for v in vectors["valid"]:
            with self.subTest(v["name"]):
                got = prop_link.proof(bytes.fromhex(v["game_key"]), bytes.fromhex(v["nonce"]), v["game_id"],
                                      v["node_id"])
                self.assertEqual(got.hex(), v["proof"])


class MqttAclContract(unittest.TestCase):
    """The broker's permissions (the vectors' mqtt_acl) against the Pi's Mosquitto ACL file."""

    def test_acl(self):
        rules = parse_acl(ACL.read_text(encoding="utf-8"))
        self.assertEqual(set(rules), set(VECTORS["mqtt_acl"]["users"]) | {"controller"})
        for check in VECTORS["mqtt_acl"]["checks"]:
            for access in ("read", "write"):
                with self.subTest(user=check["user"], topic=check["topic"], access=access):
                    self.assertEqual(acl_allows(rules, check["user"], check["topic"], access), check[access])


class MatcherTests(unittest.TestCase):
    """The matching rules themselves (the Dart runner has the same tests)."""

    def test_rules(self):
        self.assertIsNone(mismatch({"a": 1}, {"a": 1, "b": 2}))
        self.assertIsNotNone(mismatch({"a": 1}, {"a": 2}))
        self.assertIsNone(mismatch({"a": "$absent"}, {"b": 1}))
        self.assertIsNotNone(mismatch({"a": "$absent"}, {"a": None}))
        self.assertIsNone(mismatch({"a": "$any"}, {"a": None}))
        self.assertIsNotNone(mismatch({"a": "$any"}, {}))
        self.assertIsNotNone(mismatch([1], [1, 2]))
        self.assertIsNone(mismatch({"$contains": [{"t": 2}]}, [{"t": 1}, {"t": 2}]))
        self.assertIsNotNone(mismatch({"$contains": [{"t": 3}]}, [{"t": 1}]))
        self.assertIsNotNone(mismatch(1, True))
        self.assertIsNotNone(mismatch(None, 0))
        self.assertEqual(substitute({"p": "/g/${gid}/x", "id": "${gid}"}, {"gid": 7}), {"p": "/g/7/x", "id": 7})


if __name__ == "__main__":
    unittest.main()
