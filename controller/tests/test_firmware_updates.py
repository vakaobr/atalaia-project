# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Firmware updates (protocol/firmware-update.md, decisions FU3-*).

The shared Python (firmware_release.py: the site server's catalogue, this
controller and tools/firmware_release.py) against protocol/vectors/firmware.json,
whose RFC 8032 vectors come from the RFC and which the Field Box's C side checks
too; then the controller's service and API in-process (TestClient) over the real
engine with a fake modem: uploads, what the boxes fetch, the offer and its
refusals (never during a game), the box's report and HELLO, timeouts.
"""

from __future__ import annotations

import base64
import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from support import CORE, FakeModem, config
from atalaia_controller import firmware_release as fr
from atalaia_controller.api import Auth, create_app
from atalaia_controller.config import ConfigError
from atalaia_controller.engine import Controller
from atalaia_controller.firmware_updates import MAX_RELEASES, FirmwareUpdates
from atalaia_controller.store import Store
from atalaia_controller.ws import Hub
from atalaia_sim.packet import cmd_decode, hello_encode

REPO = Path(__file__).resolve().parents[2]
VECTORS = json.loads((REPO / "protocol" / "vectors" / "firmware.json").read_text(encoding="utf-8"))
SIGNING = VECTORS["signing_key"]
OTHER = VECTORS["other_key"]
GM = {"Authorization": "Bearer gm-secret"}
READ = {"Authorization": "Bearer read-secret"}
DOMINATION = "org.atalaia.domination"


class VectorTests(unittest.TestCase):
    def test_rfc_8032(self) -> None:
        self.assertEqual(len(VECTORS["rfc8032"]), 5)
        for v in VECTORS["rfc8032"]:
            with self.subTest(v["name"]):
                key, msg, sig = (bytes.fromhex(v[k]) for k in ("public_key", "message", "signature"))
                self.assertTrue(fr.verify_signature(key, msg, sig))
                self.assertFalse(fr.verify_signature(key, msg + b"x", sig))
                # The secret key gives the public key and the signature (Ed25519 is deterministic).
                private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(v["secret_key"]))
                self.assertEqual(private.sign(msg), sig)

    def test_releases(self) -> None:
        for v in VECTORS["releases"]:
            with self.subTest(v["name"]):
                self.assertEqual(fr.manifest(v["platform"], v["version"], v["size"], v["sha256"]).decode(),
                                 v["manifest"])
                self.assertEqual(fr.release_text(v["platform"], v["version"], v["size"], v["sha256"],
                                                 v["signature"]).decode(), v["release_text"])
                got = fr.signer([SIGNING["public_key_b64"]], v["platform"], v["version"], v["size"], v["sha256"],
                                v["signature"])
                self.assertEqual(got is not None, v["valid"])
                if v["valid"]:
                    self.assertEqual(got, fr.key_id(SIGNING["public_key_b64"]))
                    seed = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(SIGNING["seed"]))
                    self.assertEqual(base64.b64encode(seed.sign(v["manifest"].encode())).decode(), v["signature"])
        untrusted = next(v for v in VECTORS["releases"] if v["name"] == "untrusted_key")
        self.assertIsNotNone(fr.signer([SIGNING["public_key_b64"], OTHER["public_key_b64"]], untrusted["platform"],
                                       untrusted["version"], untrusted["size"], untrusted["sha256"],
                                       untrusted["signature"]))

    def test_versions(self) -> None:
        v = VECTORS["versions"]
        for name in ("semver_order", "semver_core_order", "order"):
            items = v[name]
            self.assertEqual(sorted(reversed(items), key=fr.version_key), items, name)
            for a, b in zip(items, items[1:]):
                self.assertEqual((fr.compare_versions(a, b), fr.compare_versions(b, a)), (-1, 1), (a, b))
        for a, b in v["equal"]:
            self.assertEqual(fr.compare_versions(a, b), 0)
        for good in v["valid"]:
            self.assertIsNotNone(fr.version_key(good), good)
        for bad in v["invalid"]:
            self.assertIsNone(fr.version_key(bad), bad)
        with self.assertRaises(ValueError):
            fr.compare_versions("1.0", "1.0.0")

    def test_images(self) -> None:
        for v in VECTORS["images"]["valid"]:
            info = fr.image_info(bytes.fromhex(v["head"]))
            self.assertEqual((info.version, info.project, info.variant, info.board),
                             (v["version"], v["project"], v["variant"], v["board"]))
        for v in VECTORS["images"]["invalid"]:
            with self.subTest(v["name"]), self.assertRaises(fr.ReleaseError):
                fr.image_info(bytes.fromhex(v["head"]))

    def test_reports(self) -> None:
        key = bytes.fromhex(VECTORS["reports"]["game_key"])
        for v in VECTORS["reports"]["valid"]:
            body = fr.report_body(v["game"], v["node"], v["release"], v["result"], v["version"])
            self.assertEqual(body.decode(), v["body"])
            self.assertEqual(fr.report_mac(key, body), v["mac"])
            self.assertEqual(fr.parse_report(body)["result"], v["result"])
        good = VECTORS["reports"]["valid"][0]["body"]
        for bad in (good.replace("result=installed", "result=great"), good.replace("game=4242", "game=04242"),
                    good.replace("\n", "\r\n"), good + "x=1\n", good.replace("release=", "release=X"),
                    good.replace("version=0.3.0", "version=0.3"), good.replace("node=7", "node=65535"), ""):
            with self.subTest(bad=bad), self.assertRaises(fr.ReleaseError):
                fr.parse_report(bad.encode())

    def test_the_site_server_uses_the_same_code(self) -> None:
        import sys  # noqa: PLC0415

        sys.path.insert(0, str(REPO / "server"))
        try:
            from atalaia_server import firmware  # noqa: PLC0415
        except ImportError as exc:  # the server's own dependencies are not needed for this module
            self.fail(f"server/atalaia_server/firmware.py does not import: {exc}")
        self.assertIs(firmware.manifest, fr.manifest)
        self.assertIs(firmware.signer, fr.signer)
        self.assertIs(firmware.version_key, fr.version_key)


# ---- the controller's service and API ---------------------------------------------------------

def box_image(version: str, size: int = 4096, variant: str = "box", board: str = "heltec_v4_3",
              salt: int = 0) -> bytes:
    """A stand-in for a Field Box image: the ESP-IDF headers and the descriptors a box and the
    controller read, then filler."""
    head = bytearray(fr.IMAGE_HEAD)
    head[0], head[1] = fr.ESP_IMAGE_MAGIC, 4
    struct.pack_into("<I", head, fr.APP_DESC_OFFSET, fr.APP_DESC_MAGIC)
    head[48:48 + len(version)] = version.encode()
    head[80:80 + len(fr.PROJECT_NAME)] = fr.PROJECT_NAME.encode()
    head[288:292], head[292] = fr.ATALAIA_DESC_MAGIC, fr.ATALAIA_DESC_FORMAT
    head[296:296 + len(variant)] = variant.encode()
    head[308:308 + len(board)] = board.encode()
    body = bytes((i * 7 + salt) & 0xFF for i in range(size - len(head)))
    return bytes(head) + body


def sign(image: bytes, version: str, platform: str = "esp32s3", seed: str = SIGNING["seed"]) -> str:
    key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(seed))
    sha = hashlib.sha256(image).hexdigest()
    return base64.b64encode(key.sign(fr.manifest(platform, version, len(image), sha))).decode()


class Clock:
    def __init__(self) -> None:
        self.t = 1_000_000.0

    def __call__(self) -> float:
        return self.t


class FirmwareCase(unittest.TestCase):
    keys = [SIGNING["public_key_b64"]]

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        cfg = config(self.tmp.name, firmware_release_keys=list(self.keys))
        self.store = Store(cfg.db_path)
        self.modem = FakeModem()
        self.ctrl = Controller(cfg, self.store, modem=self.modem, core=CORE)
        self.ctrl.ca_sha256 = b"\xca" * 32
        self.ctrl.link_urls = ["https://10.42.0.1:8443"]
        self.clock = Clock()
        self.fw = FirmwareUpdates(self.ctrl, Path(self.tmp.name) / "firmware", cfg.firmware_release_keys,
                                  cfg.firmware_update_timeout_s, clock=self.clock)
        self.messages: list[dict] = []
        self.ctrl.add_listener(self.messages.append)
        self.app = create_app(self.ctrl, Hub(), Auth(cfg.gm_token, cfg.read_token))
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.client.close()
        self.ctrl.stop()
        self.store.close()
        self.tmp.cleanup()

    def upload(self, image: bytes, version: str, signature: str | None = None, platform: str = "esp32s3"):
        return self.client.post("/api/v1/firmware", content=image, headers={**GM, "Content-Type":
                                                                            "application/octet-stream"},
                                params={"platform": platform, "version": version,
                                        "signature": signature if signature is not None else sign(image, version,
                                                                                                    platform)})

    def new_game(self) -> dict:
        r = self.client.post("/api/v1/games", json={"name": "Sunday", "mode_id": DOMINATION, "teams": ["red", "blue"],
                                                     "assignments": {"4": "zone", "5": "zone", "6": "zone"}},
                             headers=GM)
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def hello(self, game: dict, node: int, fw: str, platform: int = 1, tier: int = 0, seq: int = 0) -> None:
        self.modem.rx(node, seq, "HELLO", hello_encode({
            "node_name": f"box-{node}", "platform": platform, "fw_version": fw, "core_version": "0.2.0",
            "tier": tier, "capabilities": [0], "transports": 1, "battery_pct": 80, "epoch": 1}),
            game_id=game["id"], epoch=1)

    def update_cmds(self) -> list[dict]:
        return [d for d in (cmd_decode(p) for _, p in self.modem.of("CMD")) if d["cmd"] == 9]

    def report(self, game: dict, node: int, release: str, result: str, version: str, key: bytes | None = None):
        body = fr.report_body(game["id"], node, release, result, version)
        mac = fr.report_mac(key if key is not None else self.ctrl.game_key(game["id"]), body)
        return self.client.post("/api/v1/firmware/report", content=body,
                                headers={"Content-Type": "text/plain", "X-Atalaia-Mac": mac})


class ReleaseTests(FirmwareCase):
    def test_upload_list_fetch_delete(self) -> None:
        image = box_image("0.3.0")
        r = self.upload(image, "0.3.0")
        self.assertEqual(r.status_code, 201, r.text)
        rel = r.json()
        sha = hashlib.sha256(image).hexdigest()
        self.assertEqual((rel["id"], rel["sha256"], rel["size"], rel["board"], rel["variant"], rel["verified"]),
                         (sha[:16], sha, len(image), "heltec_v4_3", "box", True))
        self.assertEqual(rel["key_id"], fr.key_id(SIGNING["public_key_b64"]))
        status = self.client.get("/api/v1/firmware", headers=GM).json()
        self.assertEqual(([x["id"] for x in status["releases"]], status["keys"], status["https"]),
                         ([rel["id"]], [rel["key_id"]], True))
        # What a box fetches, with no token: the signed text, then the image.
        text = self.client.get(f"/api/v1/firmware/{rel['id']}/release")
        self.assertEqual(text.status_code, 200)
        self.assertEqual(text.content, fr.release_text("esp32s3", "0.3.0", len(image), sha, rel["signature"]))
        self.assertTrue(text.headers["content-type"].startswith("text/plain"))
        img = self.client.get(f"/api/v1/firmware/{rel['id']}/image")
        self.assertEqual((img.status_code, img.content, img.headers["content-length"]),
                         (200, image, str(len(image))))
        self.assertEqual(self.client.get("/api/v1/firmware/0123456789abcdef/image").status_code, 404)
        self.assertEqual(self.client.get("/api/v1/firmware/nothex/release").status_code, 404)
        # Kept on disk, private.
        self.assertEqual(oct((Path(self.tmp.name) / "firmware" / f"{sha}.bin").stat().st_mode & 0o777), "0o600")
        self.assertEqual(self.upload(image, "0.3.0").status_code, 409)  # already here
        self.assertEqual(self.client.delete(f"/api/v1/firmware/{rel['id']}", headers=GM).status_code, 200)
        self.assertEqual(self.client.get(f"/api/v1/firmware/{rel['id']}/release").status_code, 404)
        self.assertEqual(self.client.get("/api/v1/firmware", headers=GM).json()["releases"], [])

    def test_upload_refusals(self) -> None:
        image = box_image("0.3.0")
        cases = [
            ("another version than signed", self.upload(image, "0.3.1", sign(image, "0.3.0")), 400),
            ("another key", self.upload(image, "0.3.0", sign(image, "0.3.0", seed=OTHER["seed"])), 400),
            ("signed for another platform", self.upload(image, "0.3.0", sign(image, "0.3.0", "esp32")), 400),
            ("not a box platform", self.upload(image, "0.3.0", platform="linux"), 400),
            ("the image says another version", self.upload(box_image("0.2.9"), "0.3.0"), 400),
            ("a bench build", self.upload(box_image("0.3.0", variant="box-bench"), "0.3.0"), 400),
            ("not an image", self.upload(b"\x00" * 4096, "0.3.0"), 400),
            ("too big", self.upload(box_image("0.3.0", size=0x200001), "0.3.0"), 413),
            ("bad version", self.upload(image, "0.3", sign(image, "0.3")), 400),
            ("bad signature", self.upload(image, "0.3.0", "AAAA"), 400),
        ]
        for name, r, code in cases:
            with self.subTest(name):
                self.assertEqual(r.status_code, code, r.text)
        self.assertEqual(self.client.get("/api/v1/firmware", headers=GM).json()["releases"], [])
        # The GM token only.
        self.assertEqual(self.client.get("/api/v1/firmware", headers=READ).status_code, 403)
        r = self.client.post("/api/v1/firmware", content=image, headers=READ,
                             params={"platform": "esp32s3", "version": "0.3.0", "signature": sign(image, "0.3.0")})
        self.assertEqual(r.status_code, 403)

    def test_at_most_four(self) -> None:
        for i in range(MAX_RELEASES):
            self.assertEqual(self.upload(box_image(f"0.3.{i}"), f"0.3.{i}").status_code, 201)
        self.assertEqual(self.upload(box_image("0.4.0"), "0.4.0").status_code, 409)
        versions = [x["version"] for x in self.client.get("/api/v1/firmware", headers=GM).json()["releases"]]
        self.assertEqual(versions, ["0.3.3", "0.3.2", "0.3.1", "0.3.0"])

    def test_a_bench_controller_takes_bench_images(self) -> None:
        self.fw.variants = ("box-bench",)  # [firmware] variants = ["box-bench"]: a test on the desk
        self.assertEqual(self.upload(box_image("0.3.0", variant="box-bench"), "0.3.0").status_code, 201)
        r = self.upload(box_image("0.3.1"), "0.3.1")
        self.assertEqual(r.status_code, 400)
        self.assertIn("box-bench", r.json()["detail"])

    def test_a_withdrawn_key_withdraws_its_releases(self) -> None:
        rel = self.upload(box_image("0.3.0"), "0.3.0").json()
        self.fw.keys = [OTHER["public_key_b64"]]  # the release key was replaced in the settings
        listed = self.client.get("/api/v1/firmware", headers=GM).json()["releases"]
        self.assertEqual((listed[0]["verified"], listed[0]["key_id"]), (False, None))
        self.assertEqual(self.client.get(f"/api/v1/firmware/{rel['id']}/release").status_code, 404)
        self.assertEqual(self.client.get(f"/api/v1/firmware/{rel['id']}/image").status_code, 404)


class NoKeyTests(FirmwareCase):
    keys: list[str] = []

    def test_no_key_no_release(self) -> None:
        r = self.upload(box_image("0.3.0"), "0.3.0")
        self.assertEqual(r.status_code, 409)
        self.assertIn("release_keys", r.json()["detail"])


class UpdateTests(FirmwareCase):
    def setUp(self) -> None:
        super().setUp()
        self.rel = self.upload(box_image("0.3.0"), "0.3.0").json()

    def test_the_whole_way(self) -> None:
        game = self.new_game()
        self.hello(game, 4, "0.2.0")
        r = self.client.post(f"/api/v1/firmware/{self.rel['id']}/install", json={"nodes": [4]}, headers=GM)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["results"], [{"node_id": 4, "result": "sent"}])
        # CMD update (opcode 9) to box 4 alone, with the release's id and version.
        self.assertEqual(self.update_cmds(), [{"cmd": 9, "params": {"id": self.rel["id"], "version": "0.3.0"},
                                               "dest": 4}])
        updates = self.client.get("/api/v1/firmware", headers=GM).json()["updates"]
        self.assertEqual((updates[0]["node_id"], updates[0]["state"], updates[0]["from_version"]), (4, "sent", "0.2.0"))
        # The game may not start while the update is on its way.
        r = self.client.post(f"/api/v1/games/{game['id']}/start", headers=GM)
        self.assertEqual(r.status_code, 409)
        self.assertIn("firmware", r.json()["detail"])
        # The box reports, signed with the game key; then its HELLO shows the new version.
        self.assertEqual(self.report(game, 4, self.rel["id"], "installed", "0.3.0").json(), {"accepted": True})
        self.assertEqual(self.fw.updates()[0]["state"], "installed")
        self.hello(game, 4, "0.3.0", seq=1)
        self.assertEqual(self.fw.updates()[0]["state"], "done")
        self.assertTrue(any(m.get("type") == "firmware" for m in self.messages))
        self.assertEqual(self.client.post(f"/api/v1/games/{game['id']}/start", headers=GM).status_code, 200)
        # Never during a game.
        self.hello(game, 5, "0.2.0")
        r = self.client.post(f"/api/v1/firmware/{self.rel['id']}/install", json={"nodes": "all"}, headers=GM)
        self.assertEqual(r.status_code, 409)
        self.assertIn("never during", r.json()["detail"])
        self.assertEqual(len(self.update_cmds()), 1)

    def test_who_gets_it(self) -> None:
        game = self.new_game()
        self.hello(game, 4, "0.2.0")
        self.hello(game, 5, "0.3.0")                 # already there
        self.hello(game, 6, "0.2.0", platform=2)     # not an ESP32-S3 box
        self.hello(game, 7, "0.2.0", tier=2)         # a phone (proxy tier)
        self.hello(game, 8, "0.4.0")                 # newer: never downgraded
        self.hello(game, 9, "host")                  # a version of another form
        r = self.client.post(f"/api/v1/firmware/{self.rel['id']}/install", json={"nodes": "all"}, headers=GM)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual({x["node_id"]: x["result"] for x in r.json()["results"]},
                         {4: "sent", 5: "not_newer", 6: "wrong_platform", 7: "wrong_tier", 8: "not_newer",
                          9: "unknown_version"})
        self.assertEqual([c["dest"] for c in self.update_cmds()], [4])
        # Again: box 4's update is on its way.
        r = self.client.post(f"/api/v1/firmware/{self.rel['id']}/install", json={"nodes": [4]}, headers=GM)
        self.assertEqual(r.status_code, 409)
        self.assertIn("in_progress", r.json()["detail"])
        # A box of the game that was never heard, a box not in the game.
        r = self.client.post(f"/api/v1/firmware/{self.rel['id']}/install", json={"nodes": [40]}, headers=GM)
        self.assertEqual(r.status_code, 409)
        for bad in ({"nodes": []}, {"nodes": "some"}, {"nodes": [True]}, {}):
            with self.subTest(bad=bad):
                r = self.client.post(f"/api/v1/firmware/{self.rel['id']}/install", json=bad, headers=GM)
                self.assertEqual(r.status_code, 400)
        self.assertEqual(self.client.post("/api/v1/firmware/0123456789abcdef/install", json={"nodes": "all"},
                                          headers=GM).status_code, 404)

    def test_refused_without_a_live_ready_game_or_https(self) -> None:
        r = self.client.post(f"/api/v1/firmware/{self.rel['id']}/install", json={"nodes": "all"}, headers=GM)
        self.assertEqual(r.status_code, 409)
        game = self.new_game()
        self.hello(game, 4, "0.2.0")
        self.ctrl.ca_sha256 = None  # no HTTPS: the boxes could not pin the field CA
        r = self.client.post(f"/api/v1/firmware/{self.rel['id']}/install", json={"nodes": "all"}, headers=GM)
        self.assertEqual(r.status_code, 409)
        self.assertIn("HTTPS", r.json()["detail"])
        self.ctrl.ca_sha256 = b"\xca" * 32
        self.client.post(f"/api/v1/games/{game['id']}/start", headers=GM)
        self.client.post(f"/api/v1/games/{game['id']}/pause", json={}, headers=GM)
        r = self.client.post(f"/api/v1/firmware/{self.rel['id']}/install", json={"nodes": "all"}, headers=GM)
        self.assertEqual(r.status_code, 409)  # paused is still a game being played
        self.assertEqual(self.update_cmds(), [])
        self.assertEqual(self.client.post(f"/api/v1/firmware/{self.rel['id']}/install", json={"nodes": "all"},
                                          headers=READ).status_code, 403)

    def test_failures_rollback_timeout_cancel(self) -> None:
        game = self.new_game()
        for n in (4, 5, 6):
            self.hello(game, n, "0.2.0")
        self.client.post(f"/api/v1/firmware/{self.rel['id']}/install", json={"nodes": "all"}, headers=GM)
        # Box 4: the signature did not verify on the box.
        self.assertEqual(self.report(game, 4, self.rel["id"], "bad_signature", "0.2.0").json(), {"accepted": True})
        # Box 5: installed, but its HELLO comes back with the old version: rolled back.
        self.report(game, 5, self.rel["id"], "installed", "0.3.0")
        self.hello(game, 5, "0.2.0", seq=1)
        states = {u["node_id"]: (u["state"], u["reason"]) for u in self.fw.updates()}
        self.assertEqual(states[4], ("failed", "bad_signature"))
        self.assertEqual(states[5], ("rolled_back", "self_test"))
        self.assertEqual(states[6], ("sent", None))
        # Box 6 says nothing for update_timeout_s.
        self.clock.t += 601
        self.assertEqual({u["node_id"]: u["state"] for u in self.fw.updates()}[6], "timeout")
        self.assertIsNone(self.fw.busy())
        # Reports that do not count.
        body = fr.report_body(game["id"], 6, self.rel["id"], "installed", "0.3.0")
        r = self.client.post("/api/v1/firmware/report", content=body, headers={"X-Atalaia-Mac": "00" * 32})
        self.assertEqual(r.status_code, 400)  # not the game key's MAC
        r = self.client.post("/api/v1/firmware/report", content=body)
        self.assertEqual(r.status_code, 400)
        r = self.report(game, 6, self.rel["id"], "installed", "0.3.0", key=b"\x00" * 16)
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/v1/firmware/report", content=b"hello", headers={"X-Atalaia-Mac": "00" * 32})
        self.assertEqual(r.status_code, 400)
        other = fr.report_body(game["id"] + 1, 6, self.rel["id"], "installed", "0.3.0")
        r = self.client.post("/api/v1/firmware/report", content=other,
                             headers={"X-Atalaia-Mac": fr.report_mac(b"\x00" * 16, other)})
        self.assertEqual(r.status_code, 409)  # not the live game
        self.assertEqual(self.report(game, 7, self.rel["id"], "installed", "0.3.0").json(), {"accepted": False})
        # Cancel: the game may start.
        self.hello(game, 4, "0.2.0", seq=2)
        self.client.post(f"/api/v1/firmware/{self.rel['id']}/install", json={"nodes": [4]}, headers=GM)
        self.assertIsNotNone(self.fw.busy())
        self.assertEqual(self.client.delete("/api/v1/firmware/updates", headers=GM).json(), {"cancelled": [4]})
        self.assertIsNone(self.fw.busy())
        self.assertEqual(self.client.post(f"/api/v1/games/{game['id']}/start", headers=GM).status_code, 200)

    def test_radio_down(self) -> None:
        game = self.new_game()
        self.hello(game, 4, "0.2.0")
        self.modem.state = "down"
        r = self.client.post(f"/api/v1/firmware/{self.rel['id']}/install", json={"nodes": "all"}, headers=GM)
        self.assertEqual(r.json()["results"], [{"node_id": 4, "result": "radio"},
                                               {"node_id": 5, "result": "unknown"},  # joined, never heard
                                               {"node_id": 6, "result": "unknown"}])
        self.assertEqual(self.fw.updates(), [])


class ToolTests(unittest.TestCase):
    """tools/firmware_release.py: the key ceremony's commands, and a release the controller accepts."""

    def run_tool(self, *args: str, env: dict | None = None):
        import os  # noqa: PLC0415
        import subprocess  # noqa: PLC0415
        import sys  # noqa: PLC0415

        return subprocess.run([sys.executable, str(REPO / "tools" / "firmware_release.py"), *args],
                              capture_output=True, text=True, timeout=60, env={**os.environ, **(env or {})})

    def test_keygen_sign_verify(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            key = Path(tmp) / "keys" / "release.pem"
            r = self.run_tool("keygen", "--out", str(key), env={"ATALAIA_RELEASE_KEY_PASSPHRASE": "correct horse"})
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(oct(key.stat().st_mode & 0o777), "0o600")
            self.assertIn(b"ENCRYPTED", key.read_bytes())
            b64 = next(line.split()[-1] for line in r.stdout.splitlines() if line.startswith("public key (base64)"))
            hexkey = next(line.split()[-1] for line in r.stdout.splitlines() if line.startswith("public key (hex)"))
            self.assertIn(f'CONFIG_ATALAIA_OTA_RELEASE_KEYS="{hexkey}"', r.stdout)
            self.assertEqual(base64.b64decode(b64).hex(), hexkey)
            # Never overwritten, never inside the repository.
            self.assertNotEqual(self.run_tool("keygen", "--out", str(key), "--unencrypted").returncode, 0)
            inside = REPO / "firmware" / "esp32" / "release-key.pem"
            r = self.run_tool("keygen", "--out", str(inside), "--unencrypted")
            self.assertNotEqual(r.returncode, 0)
            self.assertFalse(inside.exists())
            # Sign an image; the release verifies, and the controller takes it.
            image = Path(tmp) / "atalaia_esp32.bin"
            image.write_bytes(box_image("0.3.0"))
            env = {"ATALAIA_RELEASE_KEY_PASSPHRASE": "correct horse"}
            r = self.run_tool("sign", str(image), "--key", str(key), env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            release = json.loads((Path(tmp) / "atalaia_esp32.bin.release.json").read_text())
            self.assertEqual((release["platform"], release["version"], release["variant"], release["board"],
                              release["key_id"]), ("esp32s3", "0.3.0", "box", "heltec_v4_3", fr.key_id(b64)))
            self.assertEqual(fr.signer([b64], "esp32s3", "0.3.0", release["size"], release["sha256"],
                                       release["signature"]), fr.key_id(b64))
            rel = self.run_tool("verify", str(image), str(Path(tmp) / "atalaia_esp32.bin.release.json"),
                                "--keys", hexkey)
            self.assertEqual(rel.returncode, 0, rel.stdout)
            wrong = self.run_tool("verify", str(image), str(Path(tmp) / "atalaia_esp32.bin.release.json"),
                                  "--keys", OTHER["public_key_b64"])
            self.assertEqual(wrong.returncode, 1)
            with tempfile.TemporaryDirectory() as db:
                store = Store(str(Path(db) / "c.db"))
                ctrl = Controller(config(db), store, modem=FakeModem(), core=CORE)
                fw = FirmwareUpdates(ctrl, Path(db) / "fw", [b64])
                self.assertTrue(fw.add(image.read_bytes(), release["platform"], release["version"],
                                       release["signature"])["verified"])
                ctrl.stop()
                store.close()
            # A wrong passphrase, a version the image does not say, a key inside the repository.
            self.assertNotEqual(self.run_tool("sign", str(image), "--key", str(key),
                                              env={"ATALAIA_RELEASE_KEY_PASSPHRASE": "wrong"}).returncode, 0)
            r = self.run_tool("sign", str(image), "--key", str(key), "--version", "0.3.1", env=env)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("the image says", r.stderr)
            r = self.run_tool("sign", str(image), "--key", str(REPO / "README.md"))
            self.assertIn("inside the repository", r.stderr)
            (Path(tmp) / "junk.bin").write_bytes(b"\x00" * 400)
            self.assertNotEqual(self.run_tool("sign", str(Path(tmp) / "junk.bin"), "--key", str(key),
                                              env=env).returncode, 0)


class ConfigTests(unittest.TestCase):
    def test_release_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config(tmp, firmware_release_keys=[SIGNING["public_key_b64"], OTHER["public_key_b64"]])
            for bad in (["AAAA"], [SIGNING["public_key_b64"][:-2]], [SIGNING["public_key_b64"]] * 9):
                with self.subTest(bad=bad), self.assertRaises(ConfigError):
                    config(tmp, firmware_release_keys=bad)
            with self.assertRaises(ConfigError):
                config(tmp, firmware_update_timeout_s=5)
            for bad in ([], ["Box"], ["box_bench"], ["a" * 12]):
                with self.subTest(variants=bad), self.assertRaises(ConfigError):
                    config(tmp, firmware_variants=bad)

    def test_from_the_environment(self) -> None:
        from atalaia_controller.config import load_config  # noqa: PLC0415

        env = {"ATALAIA_FIRMWARE_RELEASE_KEYS": f"{SIGNING['public_key_b64']},{OTHER['public_key_b64']}"}
        self.assertEqual(load_config(None, env).firmware_release_keys,
                         [SIGNING["public_key_b64"], OTHER["public_key_b64"]])


if __name__ == "__main__":
    unittest.main()
