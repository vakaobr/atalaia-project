# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The API's shared contract cases (protocol/vectors/controller_api.json) against this controller.

    cd controller && python -m unittest tests.test_api_contract   (or discover -s tests)

The same cases run against the Android field controller (decision PE24,
app/test/controller/api_contract_test.dart): this controller is the
reference, so every case must pass here first. Each case gets a fresh
controller with a recording modem and a clock that only moves on an
``advance_ms`` step, which also runs the controller's tick once.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from support import CORE, FakeModem, config
from atalaia_controller.api import Auth, create_app
from atalaia_controller.engine import Controller
from atalaia_controller.store import Store
from atalaia_controller.ws import Hub
from atalaia_sim import codec
from atalaia_sim.packet import hello_encode, state_encode

VECTORS = json.loads((Path(__file__).resolve().parents[2] / "protocol" / "vectors" /
                      "controller_api.json").read_text(encoding="utf-8"))
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


class ContractCase(unittest.TestCase):
    def run_case(self, case: dict[str, Any]) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config(tmp, gm_token=VECTORS["tokens"]["gm"], read_token=VECTORS["tokens"]["read"])
            store = Store(cfg.db_path)
            modem = FakeModem()
            now = [0.0]
            ctrl = Controller(cfg, store, modem=modem, core=CORE, clock=lambda: now[0])
            client = TestClient(create_app(ctrl, Hub(), Auth(cfg.gm_token, cfg.read_token)))
            saved: dict[str, Any] = {}
            try:
                for i, step in enumerate(case["steps"]):
                    with self.subTest(step=i):
                        self.run_step(step, client, modem, ctrl, now, saved)
            finally:
                client.close()
                ctrl.stop()
                store.close()

    def run_step(self, step, client, modem, ctrl, now, saved) -> None:
        if "advance_ms" in step:
            now[0] += step["advance_ms"] / 1000
            ctrl.tick()
            return
        if "rx" in step:
            rx = step["rx"]
            game_id = ctrl.game["id"]
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
            modem.rx(rx["source"], rx["seq"], kind, payload, game_id=game_id, epoch=rx.get("epoch", 0))
            return
        req = substitute(step["request"], saved)
        headers = {}
        token = req.get("token", "none")
        if token == "bad":
            headers["Authorization"] = "Bearer not-a-token"
        elif token != "none":
            headers["Authorization"] = f"Bearer {VECTORS['tokens'][token]}"
        kwargs: dict[str, Any] = {"headers": headers}
        if "body" in req:
            kwargs["json"] = req["body"]
        r = client.request(req["method"], req["path"], **kwargs)
        self.assertEqual(r.status_code, step["status"], f"{req['method']} {req['path']}: {r.text}")
        body = r.json()
        if "json" in step:
            why = mismatch(substitute(step["json"], saved), body)
            self.assertIsNone(why, f"{req['method']} {req['path']}: {why}")
        for name, path in step.get("save", {}).items():
            saved[name] = dig(body, path)


def _make(case: dict[str, Any]):
    def test(self: ContractCase) -> None:
        if CORE is None:
            self.skipTest("the core library is not built")
        self.run_case(case)
    return test


for _n, _case in enumerate(VECTORS["cases"]):
    setattr(ContractCase, f"test_{_n:02d}_" + re.sub(r"\W+", "_", _case["name"]).strip("_").lower(),
            _make(_case))


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
