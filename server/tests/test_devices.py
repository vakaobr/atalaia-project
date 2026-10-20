# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Device health and the firmware catalogue on PostgreSQL 16 (plan phase 19).

Health comes from what a controller syncs (``POST /api/v1/sync/nodes`` and the
``node.online``, ``node.offline``, ``battery.low`` and ``node.tamper`` events);
the catalogue takes only entries signed by a configured release key, checks them
again whenever it lists them, and stores no image. The signing rules alone, with
RFC 8032's own vectors: ``test_firmware.py``.
"""

from __future__ import annotations

import base64
import hashlib
import uuid
from typing import Any, Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from atalaia_server import firmware, sync
from atalaia_server.config import Settings

from .base import AppTestCase

CTRL = {"id": "0192f3a4-5b6c-7d8e-9f01-23456789abcd", "version": "0.1.0"}
RELEASE_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
OTHER_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))


def public(key: Ed25519PrivateKey) -> str:
    return base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()


def release(version: str, platform: str = "esp32s3", key: Ed25519PrivateKey = RELEASE_KEY,
            **extra: Any) -> dict[str, Any]:
    image = f"firmware {platform} {version}".encode()
    entry = {"platform": platform, "version": version, "size": len(image), "sha256": hashlib.sha256(image).hexdigest()}
    signature = key.sign(firmware.manifest(entry["platform"], entry["version"], entry["size"], entry["sha256"]))
    return {**entry, "signature": base64.b64encode(signature).decode(), **extra}


class DeviceCase(AppTestCase):
    keys: tuple[str, ...] = (public(RELEASE_KEY),)

    def settings(self) -> Settings:
        base = super().settings()
        return Settings(database_url=base.database_url, secret_key=base.secret_key, metrics_token=base.metrics_token,
                        db_timeout_s=base.db_timeout_s, purge_hour=None, firmware_keys=self.keys)

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.field_id = (await self.fetch("INSERT INTO fields (name, slug) VALUES ('Campo', 'campo') RETURNING id"))[0][0]
        self.key = sync.new_key()
        await self.fetch("INSERT INTO field_api_keys (field_id, key_sha256) VALUES ($1, $2)", self.field_id,
                         sync.key_hash(self.key))
        self.gm = await self.staff("gm")
        _, name, secret = await self.make_user(server_admin=True)
        self.root = await self.auth(name, secret=secret)

    async def staff(self, role: str, field_id: Optional[uuid.UUID] = None) -> dict[str, str]:
        user_id, name, secret = await self.make_user(with_totp=True)
        await self.fetch("INSERT INTO user_field_roles (user_id, field_id, role_id) VALUES ($1, $2, $3)",
                         user_id, field_id or self.field_id, {"marshal": 4, "gm": 5, "admin": 7}[role])
        return await self.auth(name, secret=secret)

    async def push(self, kind: str, game: dict[str, int], **body: Any) -> dict[str, Any]:
        r = await self.client.post(f"/api/v1/sync/{kind}", json={"sync_version": 1, "controller": CTRL, "game": game,
                                                                   **body},
                                   headers={"Authorization": f"Bearer {self.key}"})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    async def game(self, game_id: int, state: str, nodes: list[dict[str, Any]],
                   events: Optional[list[dict[str, Any]]] = None) -> str:
        game = {"game_id": game_id, "game_seed": 1000 + game_id}
        answer = await self.push("games", game, meta={"name": f"Jogo {game_id}", "mode_id": "org.atalaia.domination",
                                                      "teams": ["red", "blue"], "state": state,
                                                      "created_at": 1792000000.0 + game_id})
        await self.push("nodes", game, nodes=nodes)
        if events:
            await self.push("events", game, after_id=0, events=events)
        return answer["game"]


def node(node_id: int, name: str, seen: float, **info: Any) -> dict[str, Any]:
    return {"node_id": node_id, "name": name, "role": "zone", "last_seen": seen, "info": info}


def event(i: int, node_id: int, kind: str, **data: Any) -> dict[str, Any]:
    return {"id": i, "node": node_id, "seq": i, "t": i * 1000, "type": kind, "prio": "telemetry", "data": data}


class DeviceTests(DeviceCase):
    async def test_health_from_the_synced_nodes_and_events(self) -> None:
        r = await self.client.post("/api/v1/firmware", json=release("0.5.0"), headers=self.root)
        self.assertEqual(r.status_code, 201, r.text)
        await self.game(1, "ended", [node(3, "alpha", 1792000100.0, battery_pct=90, fw_version="0.3.0",
                                          platform="1")])
        gid = await self.game(2, "running", [
            node(3, "alpha", 1792000500.0, battery_pct=15, rssi=-97, snr=4.5, fw_version="0.4.0", platform="1",
                 tier="0"),
            node(4, "bravo", 1792000400.0, fw_version="0.5.0", platform="1"),
            node(5, "charlie", 1792000300.0, fw_version="0.4.0", platform="3", battery_pct=60)],
            events=[event(1, 3, "node.online", fw="0.4.0", tier=0), event(2, 3, "battery.low", percent=15),
                    event(3, 4, "node.online"), event(4, 4, "node.offline", last_seen=3000),
                    event(5, 4, "battery.low", percent=18), event(6, 5, "node.tamper", reason="kiosk_broken")])
        r = await self.client.get(f"/api/v1/fields/{self.field_id}/devices", headers=self.gm)
        self.assertEqual(r.status_code, 200, r.text)
        devices = {d["name"]: d for d in r.json()["devices"]}
        self.assertEqual(sorted(devices), ["alpha", "bravo", "charlie"])
        alpha = devices["alpha"]
        self.assertEqual((alpha["game"]["id"], alpha["games"], alpha["battery_pct"], alpha["rssi"]), (gid, 2, 15, -97))
        self.assertEqual(alpha["firmware"], {"platform": "esp32s3", "version": "0.4.0", "latest": "0.5.0",
                                             "outdated": True})
        self.assertEqual((alpha["battery_low"], alpha["offline"], alpha["silent"], alpha["tampered"]),
                         (True, False, True, False))  # its last_seen is long gone: silent in a live game
        self.assertEqual(alpha["events"], {"node.online": 1, "battery.low": 1})
        bravo = devices["bravo"]
        self.assertEqual((bravo["battery_low"], bravo["offline"], bravo["firmware"]["outdated"]), (True, True, False))
        charlie = devices["charlie"]
        self.assertEqual((charlie["battery_low"], charlie["tampered"], charlie["firmware"]["latest"]),
                         (False, True, None))  # an android prop: no catalogue entry for its platform
        r = await self.client.get(f"/api/v1/games/{gid}/devices", headers=self.gm)
        self.assertEqual([d["node_id"] for d in r.json()["devices"]], [3, 4, 5])

    async def test_who_may_read_it(self) -> None:
        gid = await self.game(1, "ready", [node(3, "alpha", 1792000100.0)])
        admin = await self.staff("admin")
        marshal = await self.staff("marshal")
        _, name, _ = await self.make_user()
        player = await self.auth(name)
        for headers, code in ((admin, 200), (self.gm, 200), (marshal, 403), (player, 403)):
            r = await self.client.get(f"/api/v1/fields/{self.field_id}/devices", headers=headers)
            self.assertEqual(r.status_code, code)
            r = await self.client.get(f"/api/v1/games/{gid}/devices", headers=headers)
            self.assertEqual(r.status_code, code)
        other = (await self.fetch("INSERT INTO fields (name, slug) VALUES ('Sul', 'sul') RETURNING id"))[0][0]
        elsewhere = await self.staff("gm", field_id=other)
        self.assertEqual((await self.client.get(f"/api/v1/games/{gid}/devices", headers=elsewhere)).status_code, 403)
        r = await self.client.get(f"/api/v1/fields/{other}/devices", headers=elsewhere)
        self.assertEqual(r.json()["devices"], [])


class CatalogueTests(DeviceCase):
    async def test_only_signed_entries(self) -> None:
        r = await self.client.post("/api/v1/firmware", json=release("0.5.0"), headers=self.root)
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual((r.json()["verified"], r.json()["key_id"]), (True, firmware.key_id(public(RELEASE_KEY))))
        cases = (
            ({**release("0.6.0"), "size": 999}, "signature_not_verified", "signature"),   # signed for another size
            (release("0.6.0", key=OTHER_KEY), "signature_not_verified", "signature"),     # an untrusted key
            ({**release("0.6.0"), "signature": "A" * 87}, "bad_signature", "signature"),
            (release("0.6.0", platform="esp8266"), "bad_platform", "platform"),
            (release("v0.6"), "bad_version", "version"),
            ({**release("0.6.0"), "sha256": "AB" * 32}, "bad_sha256", "sha256"),
            ({**release("0.6.0"), "url": "https://example.org/fw.bin"}, "unknown_field", "url"),
        )
        for body, error, path in cases:
            with self.subTest(error=error, path=path):
                r = await self.client.post("/api/v1/firmware", json=body, headers=self.root)
                self.assertEqual(r.status_code, 400, r.text)
                self.assertEqual(r.json(), {"detail": "invalid_release", "error": error, "path": path})
        r = await self.client.post("/api/v1/firmware", json=release("0.5.0"), headers=self.root)
        self.assertEqual(r.status_code, 409)
        self.assertEqual((await self.client.post("/api/v1/firmware", json=release("0.7.0"),
                                                 headers=self.gm)).status_code, 403)
        rows = await self.fetch("SELECT action FROM audit_log WHERE action LIKE 'firmware%' ORDER BY id")
        self.assertEqual([r[0] for r in rows], ["firmware_add", "firmware_refused", "firmware_refused"])

    async def test_latest_pre_releases_and_withdrawn(self) -> None:
        ids = {}
        for version in ("0.4.0", "0.5.0", "0.6.0-rc.1", "0.10.0"):
            r = await self.client.post("/api/v1/firmware", json=release(version), headers=self.root)
            ids[version] = r.json()["id"]
        r = await self.client.get("/api/v1/firmware", headers=self.gm)
        self.assertEqual(r.json()["latest"], {"esp32s3": "0.10.0"})
        self.assertEqual([e["version"] for e in r.json()["releases"]], ["0.10.0", "0.6.0-rc.1", "0.5.0", "0.4.0"])
        r = await self.client.delete(f"/api/v1/firmware/{ids['0.10.0']}?reason=bricks+boards", headers=self.root)
        self.assertEqual((r.status_code, r.json()["yank_reason"]), (200, "bricks boards"))
        self.assertEqual((await self.client.delete(f"/api/v1/firmware/{ids['0.5.0']}",
                                                   headers=self.gm)).status_code, 403)
        r = await self.client.get("/api/v1/firmware", headers=self.gm)
        self.assertEqual(r.json()["latest"], {"esp32s3": "0.5.0"})  # never a pre-release, never a withdrawn one


class UntrustedKeyTests(DeviceCase):
    keys = (public(OTHER_KEY),)

    async def test_a_removed_key_withdraws_what_it_signed(self) -> None:
        # Signed by RELEASE_KEY while it was trusted; this server now trusts only OTHER_KEY.
        entry = release("0.5.0")
        await self.fetch("INSERT INTO firmware_releases (platform, version, size, sha256, signature, key_id) "
                         "VALUES ($1, $2, $3, $4, $5, $6)", entry["platform"], entry["version"], entry["size"],
                         entry["sha256"], entry["signature"], firmware.key_id(public(RELEASE_KEY)))
        r = await self.client.get("/api/v1/firmware", headers=self.gm)
        self.assertEqual(([e["verified"] for e in r.json()["releases"]], r.json()["latest"]), ([False], {}))
        self.assertEqual(r.json()["keys"], [firmware.key_id(public(OTHER_KEY))])


class NoKeyTests(DeviceCase):
    keys = ()

    async def test_no_key_no_entry(self) -> None:
        r = await self.client.post("/api/v1/firmware", json=release("0.5.0"), headers=self.root)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "no_release_keys"))
