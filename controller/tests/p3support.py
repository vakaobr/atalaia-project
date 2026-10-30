# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared by the phase 3 controller tests: a whole controller (main.build) without a radio,
a fixed wall clock, field identities, and Ed25519-signed chrono readings."""

from __future__ import annotations

import base64
import datetime
import json
import os
import secrets
import tempfile
import unittest
import uuid
from typing import Any, Optional

from fastapi.testclient import TestClient

from support import CORE, config  # noqa: F401  (also puts the controller on the path)

from atalaia_controller import chrono
from atalaia_controller.addresses import FieldAddresses
from atalaia_controller.main import build

GM = {"Authorization": "Bearer gm-secret"}
READ = {"Authorization": "Bearer read-secret"}
DOMINATION = "org.atalaia.domination"
# 2027-01-15 10:00:00 UTC: a fixed field day for the tests.
T0 = datetime.datetime(2027, 1, 15, 10, 0, 0, tzinfo=datetime.timezone.utc).timestamp()
ALPHABET = "abcdefghijklmnopqrstuvwxyz234567"


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def new_identity() -> tuple[str, str]:
    pid = "p-" + "".join(secrets.choice(ALPHABET) for _ in range(12))
    secret = base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode("ascii")
    return pid, secret


def declaration(replica_id: Optional[str] = None, rclass: str = "rifle", rtype: str = "aeg",
                **extra: Any) -> dict[str, Any]:
    d = {"declaration_id": str(uuid.uuid4()), "type": rtype, "class": rclass, **extra}
    if replica_id:
        d["replica_id"] = replica_id
    return d


class Marshal:
    """A marshal's Ed25519 key and signed readings (protocol/chrono-record.md)."""

    def __init__(self, marshal_id: str = "m-ana", name: str = "Ana", field_id: str = "field") -> None:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        self.key = Ed25519PrivateKey.generate()
        self.marshal_id = marshal_id
        self.name = name
        self.field_id = field_id

    @property
    def public_b64(self) -> str:
        from cryptography.hazmat.primitives import serialization

        raw = self.key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        return base64.b64encode(raw).decode("ascii")

    def reading(self, replica_id: str, player_id: str, velocity: float, *, rtype: str = "checkin",
                bb: float = 0.2, game_id: Optional[int] = None, ref: Optional[str] = None,
                when: float = T0, sign: bool = True) -> dict[str, Any]:
        rec: dict[str, Any] = {
            "reading_id": str(uuid.uuid4()), "replica_id": replica_id, "player_id": player_id, "type": rtype,
            "velocity_mps": velocity, "bb_weight_g": bb,
            "energy_j": chrono.round_half_away(chrono.energy_j(bb, velocity), 3),
            "chrono_id": "chrono-1", "marshal_id": self.marshal_id, "marshal_name": self.name,
            "field_id": self.field_id,
            "timestamp": datetime.datetime.fromtimestamp(when, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        if game_id is not None:
            rec["game_id"] = str(game_id)
        if ref is not None:
            rec["ref_reading_id"] = ref
        if sign:
            rec["signature"] = base64.b64encode(self.key.sign(chrono.canonical(rec))).decode("ascii")
        return rec

    def series(self, replica_id: str, player_id: str, velocities: list[float], **kw: Any) -> list[dict[str, Any]]:
        return [self.reading(replica_id, player_id, v, **kw) for v in velocities]


class P3Case(unittest.TestCase):
    """A controller from main.build() with check-in, positions and the Wi-Fi prop link; no radio."""

    cfg_overrides: dict[str, Any] = {}

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = config(self.tmp.name, tls_names=["10.0.2.2"], **self.cfg_overrides)
        self.open_bundle()

    def open_bundle(self) -> None:
        # The configured address stands for one of this machine's (a test host has no 10.0.2.2).
        addrs = FieldAddresses.current(self.cfg.tls_names, self.cfg.tls_port, extra_interfaces=self.cfg.tls_names)
        self.bundle = build(self.cfg, core=CORE, load_core_lib=False, addresses=addrs)
        self.ctrl = self.bundle.controller
        self.svc = self.ctrl.checkin
        self.now = getattr(self, "now", T0)
        self.svc._wall = lambda: self.now
        self.svc._tz = datetime.timezone.utc
        self.ctrl.positions._wall = lambda: self.now
        self.client = TestClient(self.bundle.app)

    def close_bundle(self) -> None:
        self.client.close()
        if self.bundle.atak is not None:
            self.bundle.atak.stop()  # its sockets (the app's lifespan stops it when it ran)
        self.ctrl.stop()
        self.bundle.store.close()

    def restart(self) -> None:
        """A controller restart: a new process on the same store and TLS folder."""
        self.close_bundle()
        self.open_bundle()

    def tearDown(self) -> None:
        self.close_bundle()
        self.tmp.cleanup()

    # --- helpers ---------------------------------------------------------------------

    def new_game(self, **spec: Any) -> dict[str, Any]:
        body = {"name": "Domingo", "mode_id": DOMINATION, "teams": ["red", "blue"],
                "assignments": {"4": "zone"}, **spec}
        r = self.client.post("/api/v1/games", json=body, headers=GM)
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def info(self) -> dict[str, Any]:
        r = self.client.get("/api/v1/checkin")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def check_in(self, game_id: int, name: str = "Falcão", ident: Optional[tuple[str, str]] = None,
                 expect: int = 201, **extra: Any) -> dict[str, Any]:
        pid, secret = ident or new_identity()
        body = {"game_id": game_id, "player_id": pid, "player_secret": secret, "display_name": name,
                "notice_version": 1, "share_position": True, **extra}
        if body["share_position"] is None:  # a client that says nothing (an older app)
            del body["share_position"]
        r = self.client.post("/api/v1/checkin", json=body, headers={"X-Forwarded-For": "ignored"})
        self.assertEqual(r.status_code, expect, r.text)
        out = r.json()
        out["_ident"] = (pid, secret)
        return out

    def gm_patch(self, game_id: int, pid: str, **body: Any) -> dict[str, Any]:
        r = self.client.patch(f"/api/v1/games/{game_id}/checkins/{pid}", json=body, headers=GM)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def make_marshal(self, game_id: int, marshal: Optional[Marshal] = None) -> tuple[Marshal, str]:
        """A checked-in person given the marshal role by the GM, with their key registered: their token."""
        m = marshal or Marshal()
        me = self.check_in(game_id, name=m.name)
        pid = me["player_id"]
        # The GM's list is what makes a marshal (MR-1): adding the player gives them the role.
        r = self.client.post("/api/v1/marshals", headers=GM,
                             json={"marshal_id": m.marshal_id, "name": m.name, "player_id": pid})
        self.assertEqual(r.status_code, 201, r.text)
        r = self.client.post("/api/v1/checkin/token", headers=bearer(me["token"]))
        self.assertEqual(r.status_code, 200, r.text)
        token = r.json()["token"]
        self.assertEqual(r.json()["role"], "marshal")
        r = self.client.put("/api/v1/checkin/me/marshal-key", headers=bearer(token),
                            json={"marshal_id": m.marshal_id, "name": m.name, "public_key": m.public_b64})
        self.assertEqual(r.status_code, 200, r.text)
        return m, token

    def upload(self, token: str, readings: list[dict[str, Any]], expect: int = 200, **extra: Any) -> dict[str, Any]:
        r = self.client.post("/api/v1/chrono/readings", json={"readings": readings, **extra},
                             headers=bearer(token))
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    def chrono_list(self, game_id: int, headers: Optional[dict[str, str]] = None) -> dict[str, Any]:
        r = self.client.get(f"/api/v1/games/{game_id}/chrono-list", headers=headers or GM)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def events(self, game_id: int, etype: Optional[str] = None) -> list[dict[str, Any]]:
        evs = self.client.get(f"/api/v1/games/{game_id}/log", headers=READ).json()
        return [e for e in evs if etype is None or e["type"] == etype]

    def everything_public(self, game_id: int) -> str:
        """What the read token can see of a game, as one text (for the privacy checks)."""
        parts = [self.client.get(p, headers=READ).text for p in (
            f"/api/v1/games/{game_id}/log", f"/api/v1/games/{game_id}", "/api/v1/games",
            "/api/v1/nodes", f"/api/v1/games/{game_id}/score")]
        parts.append(self.client.get("/api/v1/checkin").text)
        return json.dumps(parts)
