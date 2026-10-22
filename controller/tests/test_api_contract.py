# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The API's shared contract cases (protocol/vectors/controller_api.json) against this controller.

    cd controller && python -m unittest tests.test_api_contract   (or discover -s tests)

The same cases run against the Android field controller (decision PE24,
app/test/controller/api_contract_test.dart): this controller is the
reference, so every case must pass here first. Each case gets a fresh
controller with a recording modem and a clock that only moves on an
``advance_ms`` step, which also runs the controller's tick once. Stream
steps (``ws_*``, ``ws``) use the TestClient's WebSocket sessions, all on the
one event loop of the entered TestClient; ``mqtt`` steps read what the MQTT
bridge (mqtt.py) published to a recording client; the ``mqtt_acl`` checks
run against the Mosquitto ACL the Pi installs (controller/deploy/atalaia.acl).
"""

from __future__ import annotations

import contextlib
import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import paho.mqtt.client as paho
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from support import CORE, FakeModem, config
from atalaia_controller.api import Auth, create_app
from atalaia_controller.engine import Controller
from atalaia_controller.mqtt import MqttBridge
from atalaia_controller.store import Store
from atalaia_controller.ws import Hub
from atalaia_sim import codec
from atalaia_sim.packet import hello_encode, state_encode

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


class ContractCase(unittest.TestCase):
    def run_case(self, case: dict[str, Any]) -> None:
        with tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
            cfg = config(tmp, gm_token=VECTORS["tokens"]["gm"], read_token=VECTORS["tokens"]["read"])
            store = Store(cfg.db_path)
            stack.callback(store.close)
            modem = FakeModem()
            now = [0.0]
            ctrl = Controller(cfg, store, modem=modem, core=CORE, clock=lambda: now[0])
            stack.callback(ctrl.stop)
            hub = Hub()
            if "stream_max_queue" in case:
                hub.max_queue = case["stream_max_queue"]
            mqtt = RecordingMqtt()
            MqttBridge(cfg, ctrl).client = mqtt  # type: ignore[assignment]
            # Entered, so that every WebSocket session runs on one event loop with the hub.
            client = stack.enter_context(TestClient(create_app(ctrl, hub, Auth(cfg.gm_token, cfg.read_token))))
            env = SimpleNamespace(client=client, modem=modem, ctrl=ctrl, hub=hub, mqtt=mqtt, now=now,
                                  saved={}, sockets={}, stack=stack, sentinel=0)
            for i, step in enumerate(case["steps"]):
                with self.subTest(step=i):
                    self.run_step(step, env)

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
        if "advance_ms" in step:
            env.now[0] += step["advance_ms"] / 1000
            env.ctrl.tick()
            return
        if "rx" in step:
            rx = step["rx"]
            game_id = env.ctrl.game["id"]
            kind = rx["type"]
            if kind == "HELLO":
                payload = hello_encode(rx["hello"])
            elif kind == "STATE":
                state = dict(rx["state"])
                state["counters"] = {int(k): v for k, v in state["counters"].items()}
                payload = state_encode(state)
            elif kind == "EVENT":
                payload = codec.encode_event(rx["event"])
            else:
                raise ValueError(f"unknown rx type {kind}")
            env.modem.rx(rx["source"], rx["seq"], kind, payload, game_id=game_id, epoch=rx.get("epoch", 0))
            return
        if "ws_connect" in step:
            self.ws_connect(step, env)
            return
        if "ws" in step:
            got = self.until_sentinel(env.sockets[step["ws"]], env)
            self.check(step["messages"], got, f"stream {step['ws']}", env)
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
        if "mqtt" in step:
            got = list(env.mqtt.published)
            env.mqtt.published.clear()
            self.check(step["mqtt"], got, "MQTT", env)
            return
        req = substitute(step["request"], env.saved)
        headers = {}
        token = req.get("token", "none")
        if token == "bad":
            headers["Authorization"] = "Bearer not-a-token"
        elif token != "none":
            headers["Authorization"] = f"Bearer {VECTORS['tokens'][token]}"
        kwargs: dict[str, Any] = {"headers": headers}
        if "body" in req:
            kwargs["json"] = req["body"]
        r = env.client.request(req["method"], req["path"], **kwargs)
        self.assertEqual(r.status_code, step["status"], f"{req['method']} {req['path']}: {r.text}")
        body = r.json()
        if "json" in step:
            self.check(step["json"], body, f"{req['method']} {req['path']}", env)
        for name, path in step.get("save", {}).items():
            env.saved[name] = dig(body, path)

    def ws_connect(self, step: dict[str, Any], env: SimpleNamespace) -> None:
        token = step.get("token", "none")
        secret = "not-a-token" if token == "bad" else VECTORS["tokens"].get(token)
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


for _n, _case in enumerate(VECTORS["cases"]):
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
