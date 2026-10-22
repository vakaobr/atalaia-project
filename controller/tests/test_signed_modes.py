# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Signed mode packages in the controller (phase 5 plan phase 6, decisions P5C-17 to P5C-21).

The GM uploads a signed package or installs one from the field's registry index (a file
for an offline field, or https:// with a fake fetch here); each is verified with the
controller's own mode keys (protocol/mode-packages.md), fails closed, is installed
through the upload checks and kept with its archive and release (store schema 10). The
modes list shows who signed it, whether the project reviewed it, and whether its key is
still trusted.
"""

from __future__ import annotations

import base64
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any

from p3support import GM, READ, P3Case
from support import CORE, config

from atalaia_controller import mode_package as mp
from atalaia_controller.config import ConfigError
from atalaia_controller.store import SCHEMA_VERSION, Store

REPO = Path(__file__).resolve().parents[2]
VECTORS = json.loads((REPO / "protocol" / "vectors" / "mode_package.json").read_text(encoding="utf-8"))
KEY = VECTORS["signing_key"]
OTHER = VECTORS["other_key"]


def private(seed_hex: str):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(seed_hex))


SIGNING, OTHER_SIGNING = private(KEY["seed"]), private(OTHER["seed"])

# REUSE-IgnoreStart
MANIFEST = """# SPDX-FileCopyrightText: 2026 Example Club
# SPDX-License-Identifier: MIT
id: {id}
version: {version}
license: MIT
min_tier: reduced
kind: mode
name: Tagger
description: A box that counts presses.
roles:
  zone: {{ requires: [team_input] }}
"""
# REUSE-IgnoreEnd
NODE = 'local s = state.node { presses = 0 }\non("team_input.press", function(e) s.presses = s.presses + 1 end)\n'


def package(mode_id: str = "org.club.tagger", version: str = "0.1.0", node: str = NODE,
            key=SIGNING) -> tuple[bytes, dict[str, Any]]:
    """An archive and its .release.json, as tools/mode_package.py makes them."""
    archive = mp.pack(mode_id, {"mode.yaml": MANIFEST.format(id=mode_id, version=version), "node.lua": node})
    release = mp.sign_release(key, archive)
    public = base64.b64encode(key.public_key().public_bytes_raw()).decode()
    return archive, mp.release_json(release, mp.fr.key_id(public), "MIT")


def query(release: dict[str, Any]) -> dict[str, str]:
    return {k: release[k] for k in ("id", "version", "kind", "min_tier", "signature", "key_id")}


@unittest.skipIf(CORE is None, "needs the shared core library")
class SignedModeTests(P3Case):
    cfg_overrides = {"modes_keys": [KEY["public_key_b64"]]}

    def upload(self, archive: bytes, release: dict[str, Any], expect: int = 201, headers=GM):
        r = self.client.post("/api/v1/mode-packages", params=query(release), content=archive,
                             headers={**headers, "Content-Type": "application/octet-stream"})
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    def installed(self, mode_id: str) -> dict[str, Any]:
        r = self.client.get("/api/v1/modes", headers=GM)
        return next(m for m in r.json() if m["id"] == mode_id)

    def test_an_uploaded_package_is_checked_and_kept(self):
        archive, release = package()
        out = self.upload(archive, release)
        self.assertEqual((out["id"], out["version"]), ("org.club.tagger", "0.1.0"))
        self.assertEqual(out["signed"], {"key_id": KEY["key_id"], "verified": False, "sha256": mp.sha256(archive),
                                         "source": "upload", "license": "MIT", "trust": "trusted"})
        self.assertEqual(self.installed("org.club.tagger")["signed"]["trust"], "trusted")
        self.assertEqual(self.bundle.store.mode_package("org.club.tagger"), archive)  # exactly as signed
        # The mode plays: a game can be made from it.
        r = self.client.post("/api/v1/games", json={"name": "T", "mode_id": "org.club.tagger",
                                                     "teams": ["red", "blue"]}, headers=GM)
        self.assertEqual(r.status_code, 201, r.text)
        # An unsigned upload of the same id replaces it, signature and all.
        files = mp.unpack(archive)[1]
        r = self.client.post("/api/v1/modes", json={"files": files}, headers=GM)
        self.assertEqual(r.status_code, 201, r.text)
        self.assertIsNone(r.json()["signed"])
        self.assertIsNone(self.bundle.store.mode_package("org.club.tagger"))

    def test_refusals_fail_closed(self):
        archive, release = package()
        cases = []
        tampered = bytearray(archive)
        tampered[600] ^= 1
        cases.append(("tampered", bytes(tampered), release, "bad_signature"))
        cases.append(("other_version", archive, {**release, "version": "0.2.0"}, "bad_signature"))
        other_archive, other_release = package(key=OTHER_SIGNING)
        cases.append(("untrusted_key", other_archive, other_release, "no_key"))
        cases.append(("no_signature", archive, {**release, "signature": ""}, "release file"))
        for name, data, rel, why in cases:
            with self.subTest(case=name):
                out = self.upload(data, rel, expect=400)
                self.assertIn(why, out["error"] if "error" in out else json.dumps(out))
        # An archive that leaves its folder, signed by a trusted key: refused all the same.
        traversal = bytes.fromhex(next(c["hex"] for c in VECTORS["archives_invalid"] if c["name"] == "traversal"))
        fields = {"id": "org.example.relay", "version": "1.2.0-rc.1", "kind": "role", "min_tier": "full"}
        signed = mp.Release(**fields, size=len(traversal), sha256=mp.sha256(traversal), signature="")
        signature = base64.b64encode(SIGNING.sign(signed.manifest())).decode()
        out = self.upload(traversal, {**fields, "signature": signature, "key_id": KEY["key_id"]}, expect=400)
        self.assertIn("bad_archive", json.dumps(out))
        # A built-in id, and a script that does not load: the upload's own checks.
        for archive, release in (package("org.atalaia.domination"), package(node="on(\n")):
            with self.subTest(mode=release["id"]):
                self.upload(archive, release, expect=400)
        # Too big, and only for the GM.
        r = self.client.post("/api/v1/mode-packages", params=query(release), content=b"\0" * (mp.MAX_PACKAGE_BYTES + 1),
                             headers={**GM, "Content-Type": "application/octet-stream"})
        self.assertEqual(r.status_code, 413)
        self.upload(*package(), expect=403, headers=READ)
        self.assertEqual(self.client.get("/api/v1/mode-packages", headers=READ).status_code, 403)
        names = [m["id"] for m in self.client.get("/api/v1/modes", headers=GM).json()]
        self.assertNotIn("org.club.tagger", names)
        self.assertNotIn("org.example.relay", names)

    def test_a_revoked_or_removed_key(self):
        archive, release = package()
        self.upload(archive, release)
        self.close_bundle()
        self.cfg.modes_revoked = [KEY["key_id"]]
        self.open_bundle()
        self.assertEqual(self.installed("org.club.tagger")["signed"]["trust"], "revoked")
        archive2, release2 = package(version="0.2.0")
        self.assertIn("revoked", json.dumps(self.upload(archive2, release2, expect=400)))
        self.close_bundle()
        self.cfg.modes_revoked = []
        self.cfg.modes_keys = [OTHER["public_key_b64"]]
        self.open_bundle()
        self.assertEqual(self.installed("org.club.tagger")["signed"]["trust"], "untrusted")
        self.close_bundle()
        self.cfg.modes_keys = []
        self.open_bundle()
        out = self.upload(archive2, release2, expect=400)
        self.assertIn("no mode keys", json.dumps(out))
        status = self.client.get("/api/v1/mode-packages", headers=GM).json()
        self.assertEqual((status["keys"], status["index"]["source"]), ([], None))

    def write_index(self, folder: Path, releases: list[tuple[bytes, dict[str, Any]]], verified: bool = True,
                    revoked: Any = None) -> Path:
        (folder / "packages").mkdir(parents=True, exist_ok=True)
        modes: dict[str, dict[str, Any]] = {}
        for archive, release in releases:
            name = f"{release['id']}-{release['version']}.tar"
            (folder / "packages" / name).write_bytes(archive)
            entry = {k: release[k] for k in ("version", "kind", "min_tier", "size", "sha256", "signature", "key_id",
                                             "license")}
            entry.update({"url": f"packages/{name}", "verified": verified})
            modes.setdefault(release["id"], {"id": release["id"], "name": "Tagger", "versions": []})["versions"].append(entry)
        index = folder / "index.json"
        index.write_text(json.dumps({"schema_version": 1, "modes": list(modes.values())}))
        if revoked is not None:
            (folder / "revoked.json").write_text(json.dumps(revoked))
        return index

    def reopen_with_index(self, index: str) -> None:
        self.close_bundle()
        self.cfg.modes_index = index
        self.open_bundle()

    def test_installing_from_an_index_file(self):
        folder = Path(self.tmp.name) / "registry"
        trusted = package()
        untrusted = package("org.club.other", key=OTHER_SIGNING)
        index = self.write_index(folder, [trusted, untrusted])
        self.reopen_with_index(str(index))
        status = self.client.get("/api/v1/mode-packages", headers=GM).json()
        states = {e["id"]: e["state"] for e in status["index"]["entries"]}
        self.assertEqual(states, {"org.club.tagger": "available", "org.club.other": "no_key"})
        self.assertTrue(status["index"]["entries"][0]["verified"])
        r = self.client.post("/api/v1/mode-packages/install", json={"id": "org.club.tagger", "version": "0.1.0"},
                             headers=GM)
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual((r.json()["signed"]["source"], r.json()["signed"]["verified"]), ("index", True))
        status = self.client.get("/api/v1/mode-packages", headers=GM).json()
        self.assertEqual({e["id"]: e["state"] for e in status["index"]["entries"]}["org.club.tagger"], "installed")
        # Not trusted here, not in the index, a package changed on disk after it was listed.
        for body, why in (({"id": "org.club.other", "version": "0.1.0"}, "no_key"),
                          ({"id": "org.club.tagger", "version": "9.9.9"}, "not in the index")):
            r = self.client.post("/api/v1/mode-packages/install", json=body, headers=GM)
            self.assertEqual(r.status_code, 400, r.text)
            self.assertIn(why, r.text)
        (folder / "packages" / "org.club.tagger-0.1.0.tar").write_bytes(package(version="0.1.0", node=NODE + "\n")[0])
        r = self.client.post("/api/v1/mode-packages/install", json={"id": "org.club.tagger", "version": "0.1.0"},
                             headers=GM)
        self.assertEqual(r.status_code, 400)
        self.assertIn("bad_hash", r.text)

    def test_the_index_revocation_list_and_bad_indexes(self):
        folder = Path(self.tmp.name) / "registry"
        index = self.write_index(folder, [package()],
                                 revoked={"schema_version": 1, "keys": [{"key_id": KEY["key_id"], "reason": "lost"}]})
        self.reopen_with_index(str(index))
        status = self.client.get("/api/v1/mode-packages", headers=GM).json()
        self.assertEqual(status["revoked"], [KEY["key_id"]])
        self.assertEqual(status["index"]["entries"][0]["state"], "revoked")
        r = self.client.post("/api/v1/mode-packages/install", json={"id": "org.club.tagger", "version": "0.1.0"},
                             headers=GM)
        self.assertEqual(r.status_code, 400)
        # A revocation list that does not parse refuses the whole index (fail closed).
        (folder / "revoked.json").write_text("{not json")
        status = self.client.get("/api/v1/mode-packages?refresh=1", headers=GM).json()
        self.assertTrue(status["index"]["error"])
        self.assertEqual(status["index"]["entries"], [])
        (folder / "revoked.json").unlink()
        index.write_text(json.dumps({"schema_version": 1, "modes": [{"id": "org.club.tagger", "name": "x",
                                                                     "versions": [{"version": "0.1.0"}]}]}))
        status = self.client.get("/api/v1/mode-packages?refresh=1", headers=GM).json()
        self.assertIn("bad_index", status["index"]["error"])

    def test_an_https_index(self):
        archive, release = package()
        index = {"schema_version": 1, "modes": [{"id": release["id"], "name": "Tagger", "versions": [{
            **{k: release[k] for k in ("version", "kind", "min_tier", "size", "sha256", "signature", "key_id",
                                       "license")},
            "url": "packages/tagger.tar", "verified": False}]}]}
        served = {"https://registry.example/v1/index.json": json.dumps(index).encode(),
                  "https://registry.example/v1/packages/tagger.tar": archive}
        asked = []

        def fetch(url: str, limit: int) -> bytes:
            from atalaia_controller.signed_modes import FetchError

            asked.append(url)
            if url not in served:
                raise FetchError("404", missing=True)
            return served[url]

        self.reopen_with_index("https://registry.example/v1/index.json")
        self.ctrl.signed_modes.fetch = fetch
        r = self.client.post("/api/v1/mode-packages/install", json={"id": release["id"], "version": "0.1.0"},
                             headers=GM)
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()["signed"]["verified"], False)  # not reviewed by the project
        self.assertIn("https://registry.example/v1/revoked.json", asked)  # looked for, missing: none revoked
        self.assertIn("https://registry.example/v1/packages/tagger.tar", asked)

    def test_the_stream_says_the_modes_changed(self):
        with self.client.websocket_connect("/api/v1/stream?token=gm-secret") as ws:
            seen = []
            while True:
                msg = ws.receive_json()
                if msg.get("type") == "hello":
                    break
            self.upload(*package())
            for _ in range(20):
                msg = ws.receive_json()
                seen.append(msg.get("type"))
                if msg.get("type") == "modes":
                    break
            self.assertIn("modes", seen)


class ConfigAndStoreTests(unittest.TestCase):
    def test_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config(tmp, modes_keys=[KEY["public_key_b64"]], modes_revoked=[OTHER["key_id"]],
                         modes_index="https://registry.example/index.json")
            self.assertEqual(cfg.modes_index, "https://registry.example/index.json")
            for bad in ({"modes_keys": ["not a key"]}, {"modes_revoked": ["XYZ"]},
                        {"modes_index": "http://registry.example/index.json"}, {"modes_index": "ftp://x/i.json"},
                        {"modes_keys": [KEY["public_key_b64"]] * 9}):
                with self.subTest(bad=bad), self.assertRaises(ConfigError):
                    config(tmp, **bad)

    def test_schema_9_is_upgraded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "old.db")
            db = sqlite3.connect(path)
            db.execute("CREATE TABLE modes (id TEXT PRIMARY KEY, version TEXT NOT NULL, files_json TEXT NOT NULL, "
                       "installed_at REAL NOT NULL)")
            db.execute("INSERT INTO modes VALUES ('org.x.y', '1.0.0', '{\"mode.yaml\": \"id: org.x.y\"}', 0)")
            db.commit()
            db.close()
            store = Store(path)
            self.assertEqual(store.modes(), [{"id": "org.x.y", "version": "1.0.0",
                                              "files": {"mode.yaml": "id: org.x.y"}, "signed": None}])
            self.assertEqual(store.get_setting("schema_version"), str(SCHEMA_VERSION))
            self.assertGreaterEqual(SCHEMA_VERSION, 10)  # signed packages came with schema 10
            store.save_mode("org.x.y", "1.0.1", {"mode.yaml": "x"}, {"key_id": "k"}, b"tar")
            self.assertEqual((store.modes()[0]["signed"], store.mode_package("org.x.y")), ({"key_id": "k"}, b"tar"))
            store.close()


if __name__ == "__main__":
    unittest.main()
