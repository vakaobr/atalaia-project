# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Signed mode packages (phase 5 plan phase 4, decisions P5R-7, P5B-10, P5C-8 to P5C-14).

The shared Python (mode_package.py: the signing tool, the controller's import of
signed packages) against protocol/vectors/mode_package.json: RFC 8032's own
vectors, the canonical archive and every archive a reader must refuse (path
traversal, links, folders, other tar dialects, non-canonical forms), signed
manifests and their tampered copies, whole checks with trusted and revoked
keys, the registry index and revocation list. Then the built-in modes as
packages, the size and licence refusals, and tools/mode_package.py's commands.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from atalaia_controller import firmware_release as fr
from atalaia_controller import mode_package as mp
from atalaia_controller.modes import parse_package

REPO = Path(__file__).resolve().parents[2]
VECTORS = json.loads((REPO / "protocol" / "vectors" / "mode_package.json").read_text(encoding="utf-8"))
SCHEMA = REPO / "registry" / "schema"


def private(seed_hex: str):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(seed_hex))


SIGNING = private(VECTORS["signing_key"]["seed"])
KEY = VECTORS["signing_key"]["public_key_b64"]
OTHER_KEY = VECTORS["other_key"]["public_key_b64"]


def release_of(case: dict) -> mp.Release:
    return mp.Release(case["id"], case["version"], case["kind"], case["min_tier"], case["size"], case["sha256"],
                      case["signature"])


class VectorTests(unittest.TestCase):
    def test_rfc8032(self):
        for case in VECTORS["rfc8032"]:
            with self.subTest(case=case["name"]):
                self.assertTrue(fr.verify_signature(bytes.fromhex(case["public_key"]), bytes.fromhex(case["message"]),
                                                    bytes.fromhex(case["signature"])))
                self.assertFalse(fr.verify_signature(bytes.fromhex(case["public_key"]), b"x",
                                                     bytes.fromhex(case["signature"])))

    def test_key_ids(self):
        for name in ("signing_key", "other_key"):
            key = VECTORS[name]
            self.assertEqual(fr.key_id(key["public_key_b64"]), key["key_id"])
            self.assertEqual(base64.b64decode(key["public_key_b64"]).hex(), key["public_key"])

    def test_the_canonical_archive(self):
        a = VECTORS["archive"]
        archive = bytes.fromhex(a["hex"])
        self.assertEqual(mp.pack(a["mode_id"], a["files"]), archive)
        self.assertEqual(mp.unpack(archive), (a["mode_id"], a["files"]))
        self.assertEqual(mp.unpack(archive, a["mode_id"])[1], a["files"])
        self.assertEqual((len(archive), mp.sha256(archive)), (a["size"], a["sha256"]))
        with self.assertRaises(mp.PackageError) as cm:
            mp.unpack(archive, "org.example.other")
        self.assertEqual(cm.exception.code, "mismatch")

    def test_archives_every_reader_refuses(self):
        self.assertGreaterEqual(len(VECTORS["archives_invalid"]), 25)
        for case in VECTORS["archives_invalid"]:
            with self.subTest(case=case["name"]), self.assertRaises(mp.PackageError) as cm:
                mp.unpack(bytes.fromhex(case["hex"]))
            self.assertEqual(cm.exception.code, case["code"], case["name"])

    def test_releases(self):
        for case in VECTORS["releases"]:
            with self.subTest(case=case["name"]):
                release = release_of(case)
                self.assertEqual(release.manifest().decode(), case["manifest"])
                self.assertEqual(release.text().decode(), case["release_text"])
                self.assertEqual(mp.parse_release_text(case["release_text"].encode()), release)
                self.assertEqual(mp.release_from(case), release)
                signed = mp.signer([KEY], release) is not None
                self.assertEqual(signed, case["name"] in ("release", "lies_about_version"))
                self.assertIsNone(mp.signer([OTHER_KEY], release))

    def test_release_texts_a_reader_refuses(self):
        for case in VECTORS["release_texts_invalid"]:
            with self.subTest(case=case["name"]), self.assertRaises(mp.PackageError) as cm:
                mp.parse_release_text(case["text"].encode())
            self.assertEqual(cm.exception.code, "bad_release")

    def test_whole_checks(self):
        releases = {c["name"]: release_of(c) for c in VECTORS["releases"]}
        archives = {"archive": bytes.fromhex(VECTORS["archive"]["hex"]),
                    "tampered": bytes.fromhex(VECTORS["archive"]["tampered_hex"])}
        for case in VECTORS["verify"]:
            with self.subTest(case=case["name"]):
                archive = archives[case.get("archive", "archive")]
                release = releases[case["release"]]
                if case["result"] == "ok":
                    package = mp.verify(archive, release, case["keys"], case["revoked"], case["named_key"])
                    self.assertEqual(package.key_id, VECTORS["signing_key"]["key_id"])
                    self.assertEqual(package.files, VECTORS["archive"]["files"])
                    self.assertEqual(package.license, "MIT")
                else:
                    with self.assertRaises(mp.PackageError) as cm:
                        mp.verify(archive, release, case["keys"], case["revoked"], case["named_key"])
                    self.assertEqual(cm.exception.code, case["result"])

    def test_what_a_box_checks(self):
        """Phase 5 plan phase 13: a box's checks of a release and of the archive it downloaded,
        in its order (the reference for firmware/esp32/main/mode_fetch.c)."""
        valid = bytes.fromhex(VECTORS["archive"]["hex"])
        archives = {"archive": valid, "tampered": bytes.fromhex(VECTORS["archive"]["tampered_hex"]),
                    "truncated": valid[:-512]}
        cases = VECTORS["box_checks"]
        self.assertEqual({c["result"] for c in cases},
                         {"ok", "no_key", "bad_release", "bad_signature", "kind", "tier", "builtin", "too_big",
                          "bad_hash", "bad_archive"})
        for case in cases:
            with self.subTest(case=case["name"]):
                def run():
                    release, who = mp.box_check_release(case["release_text"].encode(), case["wanted_id"],
                                                        case["keys"], case["tier"], case["builtin"])
                    data = archives[case["archive"]] if case["archive"] else bytes.fromhex(case["archive_hex"])
                    return who, mp.box_check_archive(data, release)
                if case["result"] == "ok":
                    who, kept = run()
                    self.assertEqual((who, sorted(kept)), (case["key_id"], case["kept"]))
                    self.assertEqual(kept["node.lua"], VECTORS["archive"]["files"]["node.lua"])
                else:
                    with self.assertRaises(mp.PackageError) as cm:
                        run()
                    self.assertEqual(cm.exception.code, case["result"])
        limits = VECTORS["box_limits"]
        self.assertEqual((limits["max_package_bytes"], limits["max_fetched"], limits["max_fetched_bytes"]),
                         (256 * 1024, 8, 512 * 1024))

    def test_a_boxs_reports(self):
        key = bytes.fromhex(VECTORS["reports"]["game_key"])
        for v in VECTORS["reports"]["valid"]:
            with self.subTest(v["body"]):
                body = mp.report_body(v["game"], v["node"], v["mode"], v["version"], v["result"], v["kept"])
                self.assertEqual(body.decode(), v["body"])
                self.assertEqual(mp.report_mac(key, body), v["mac"])
                got = mp.parse_report(body)
                self.assertEqual((got["game"], got["node"], got["mode"], got["version"], got["result"], got["kept"]),
                                 (v["game"], v["node"], v["mode"], v["version"], v["result"], v["kept"]))
        for v in VECTORS["reports"]["invalid"]:
            with self.subTest(v["name"]), self.assertRaises(mp.PackageError):
                mp.parse_report(v["body"].encode())
        self.assertIn("installed", mp.BOX_RESULTS)
        self.assertEqual(len(set(mp.BOX_RESULTS)), len(mp.BOX_RESULTS))

    def test_the_index_and_revocation_list(self):
        entries = mp.parse_index(VECTORS["index"])
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual((entry.release.id, entry.license, entry.verified, entry.name),
                         ("org.example.relay", "MIT", True, "Relay"))
        self.assertEqual(entry.release, release_of(VECTORS["releases"][0]))
        for case in VECTORS["index_invalid"]:
            with self.subTest(case=case["name"]), self.assertRaises(mp.PackageError) as cm:
                mp.parse_index(case["index"])
            self.assertEqual(cm.exception.code, "bad_index")
        self.assertEqual(mp.parse_revoked(VECTORS["revoked"]), {VECTORS["signing_key"]["key_id"]: "test key"})
        for bad in ({"schema_version": 1}, {"schema_version": 1, "keys": [{"key_id": "x"}]},
                    {"schema_version": 1, "keys": [{"key_id": "0" * 16, "date": "22/10/2026"}]}):
            with self.assertRaises(mp.PackageError):
                mp.parse_revoked(bad)

    def test_schema_files_agree_with_the_code(self):
        """The JSON Schemas (CI's protocol job checks them with check-jsonschema) and their examples
        say what parse_index and parse_revoked say."""
        schema = json.loads((SCHEMA / "index.schema.json").read_text(encoding="utf-8"))
        version = schema["$defs"]["version"]
        self.assertEqual(set(version["required"]), mp.ENTRY_KEYS)
        self.assertEqual(tuple(version["properties"]["kind"]["enum"]), mp.KINDS)
        self.assertEqual(tuple(version["properties"]["min_tier"]["enum"]), mp.TIERS)
        self.assertEqual(tuple(version["properties"]["license"]["enum"]), mp.LICENCES)
        self.assertEqual(version["properties"]["size"]["maximum"], mp.MAX_PACKAGE_BYTES)
        self.assertEqual(json.loads((SCHEMA / "examples" / "index.json").read_text(encoding="utf-8")), VECTORS["index"])
        self.assertEqual(json.loads((SCHEMA / "examples" / "revoked.json").read_text(encoding="utf-8")),
                         VECTORS["revoked"])
        for path in sorted((SCHEMA / "examples" / "invalid").glob("*.json")):
            parse = mp.parse_revoked if path.name.startswith("revoked_") else mp.parse_index
            with self.subTest(example=path.name), self.assertRaises(mp.PackageError):
                parse(json.loads(path.read_text(encoding="utf-8")))


def folder_files(folder: Path) -> dict[str, str]:
    files = {}
    for path in sorted(folder.rglob("*")):
        rel = path.relative_to(folder).as_posix()
        if path.is_file() and not rel.startswith("tests/"):
            files[rel] = path.read_text(encoding="utf-8")
    return files


class PackageTests(unittest.TestCase):
    def test_every_built_in_mode_packs_and_installs(self):
        for folder in sorted((REPO / "modes").glob("*/mode.yaml")):
            folder = folder.parent
            with self.subTest(mode=folder.name):
                files = folder_files(folder)
                own = mp.manifest_fields(files)
                archive = mp.pack(own["id"], files)
                self.assertEqual(mp.pack(own["id"], dict(reversed(list(files.items())))), archive)  # stable
                root, back = mp.unpack(archive)
                self.assertEqual((root, back), (own["id"], files))
                self.assertEqual(parse_package(back).id, own["id"])  # what the controller takes

    def sign(self, files: dict[str, str], key=SIGNING) -> tuple[bytes, mp.Release]:
        archive = mp.pack("org.club.test", files)
        return archive, mp.sign_release(key, archive)

    def files(self, **manifest) -> dict[str, str]:
        fields = {"id": "org.club.test", "version": "0.1.0", "license": "MIT", "min_tier": "reduced",
                  "roles": "{ zone: {} }", **manifest}
        text = "".join(f"{k}: {v}\n" for k, v in fields.items() if v is not None)
        return {"mode.yaml": text, "node.lua": 'log("hi")\n'}

    def test_signing_reads_the_archives_own_manifest(self):
        archive, release = self.sign(self.files(kind="modifier", min_tier="full"))
        self.assertEqual((release.id, release.version, release.kind, release.min_tier, release.size),
                         ("org.club.test", "0.1.0", "modifier", "full", len(archive)))
        self.assertEqual(mp.verify(archive, release, [KEY]).release, release)
        # No min_tier: reduced (the box checks a script with its own heap, P5B-14).
        archive, release = self.sign(self.files(min_tier=None))
        self.assertEqual(release.min_tier, "reduced")

    def test_licence_refusals(self):
        for licence in ("WTFPL", None, "GPL-2.0-only"):
            with self.subTest(licence=licence), self.assertRaises(mp.PackageError) as cm:
                self.sign(self.files(license=licence))
            self.assertEqual(cm.exception.code, "licence")
        # Signed anyway (by a tool that did not check): the controller still refuses it.
        archive = mp.pack("org.club.test", self.files(license="WTFPL"))
        message = mp.manifest("org.club.test", "0.1.0", "mode", "reduced", len(archive), mp.sha256(archive))
        release = mp.Release("org.club.test", "0.1.0", "mode", "reduced", len(archive), mp.sha256(archive),
                             base64.b64encode(SIGNING.sign(message)).decode())
        with self.assertRaises(mp.PackageError) as cm:
            mp.verify(archive, release, [KEY])
        self.assertEqual(cm.exception.code, "licence")

    def test_size_limits(self):
        files = self.files()
        files["assets/big.txt"] = "x" * (mp.MAX_PACKAGE_BYTES - 5000)
        archive = mp.pack("org.club.test", files)  # just under the limit
        files["assets/big.txt"] += "x" * 6000
        with self.assertRaises(mp.PackageError) as cm:
            mp.pack("org.club.test", files)
        self.assertEqual(cm.exception.code, "too_big")
        release = mp.sign_release(SIGNING, archive)
        with self.assertRaises(mp.PackageError) as cm:  # a box's smaller limit (plan phase 13)
            mp.verify(archive, release, [KEY], limit=256 * 1024)
        self.assertEqual(cm.exception.code, "too_big")
        with self.assertRaises(mp.PackageError) as cm:
            mp.unpack(archive + b"\0" * mp.MAX_PACKAGE_BYTES)
        self.assertEqual(cm.exception.code, "too_big")
        many = {f"assets/f{i}.txt": "x" for i in range(mp.MAX_FILES)} | {"mode.yaml": "id: x\n"}
        with self.assertRaises(mp.PackageError):
            mp.pack("org.club.test", many)

    def test_names_pack_refuses(self):
        for name in ("../evil.lua", "/etc/passwd", "tests/basic.yaml", "assets/../node.lua", "assets/.hidden/x",
                     "assets//x", "NODE.lua", "assets/" + "x" * 90):
            with self.subTest(name=name), self.assertRaises(mp.PackageError):
                mp.pack("org.club.test", {"mode.yaml": "id: x\n", name: "x"})
        for bad_id in ("Org.Club", "club", "org.club.x" + "x" * 60, "../org.x"):
            with self.subTest(id=bad_id), self.assertRaises(mp.PackageError):
                mp.pack(bad_id, {"mode.yaml": "id: x\n"})

    def test_the_manifest_must_be_the_archives(self):
        archive, release = self.sign(self.files())
        for name, value in (("version", "0.2.0"), ("kind", "role"), ("min_tier", "full")):
            changed = mp.Release(**{**release.__dict__, name: value})
            changed = mp.Release(**{**changed.__dict__, "signature": base64.b64encode(
                SIGNING.sign(changed.manifest())).decode()})
            with self.subTest(field=name), self.assertRaises(mp.PackageError) as cm:
                mp.verify(archive, changed, [KEY])
            self.assertEqual(cm.exception.code, "mismatch")
        other = mp.Release(**{**release.__dict__, "id": "org.club.other"})
        other = mp.Release(**{**other.__dict__, "signature": base64.b64encode(SIGNING.sign(other.manifest())).decode()})
        with self.assertRaises(mp.PackageError) as cm:
            mp.verify(archive, other, [KEY])
        self.assertEqual(cm.exception.code, "mismatch")


class ToolTests(unittest.TestCase):
    """tools/mode_package.py: pack, keygen, sign, verify and index, as a mode author runs them."""

    def run_tool(self, *args, env=None):
        return subprocess.run([sys.executable, str(REPO / "tools" / "mode_package.py"), *args],
                              capture_output=True, text=True, env={**os.environ, **(env or {})}, timeout=60)

    def test_pack_sign_verify_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            out = self.run_tool("keygen", "--out", str(tmp / "keys" / "mode.pem"), "--unencrypted")
            self.assertEqual(out.returncode, 0, out.stderr)
            public = next(line.split()[-1] for line in out.stdout.splitlines() if line.startswith("public key (base64)"))
            key_id = next(line.split()[-1] for line in out.stdout.splitlines() if line.startswith("key id"))
            self.assertEqual(fr.key_id(public), key_id)
            self.assertIn("[modes]", out.stdout)
            self.assertEqual(os.stat(tmp / "keys" / "mode.pem").st_mode & 0o777, 0o600)
            # Never over an existing key, never inside the repository.
            self.assertNotEqual(self.run_tool("keygen", "--out", str(tmp / "keys" / "mode.pem"),
                                              "--unencrypted").returncode, 0)
            refused = self.run_tool("keygen", "--out", str(REPO / "mode.pem"), "--unencrypted")
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("inside the repository", refused.stderr)
            self.assertFalse((REPO / "mode.pem").exists())

            archive = tmp / "holdall.tar"
            out = self.run_tool("pack", str(REPO / "modes" / "holdall"), "--out", str(archive))
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn("left out: tests/", out.stdout)
            again = tmp / "again.tar"
            self.run_tool("pack", str(REPO / "modes" / "holdall"), "--out", str(again))
            self.assertEqual(archive.read_bytes(), again.read_bytes())

            out = self.run_tool("sign", str(archive), "--key", str(tmp / "keys" / "mode.pem"))
            self.assertEqual(out.returncode, 0, out.stderr)
            release_path = tmp / "holdall.tar.release.json"
            release = json.loads(release_path.read_text())
            self.assertEqual((release["id"], release["key_id"], release["license"], release["format"]),
                             ("org.atalaia.holdall", key_id, "GPL-3.0-or-later", "atalaia-mode-package-v1"))

            ok = self.run_tool("verify", str(archive), str(release_path), "--keys", public)
            self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
            self.assertIn(f"signed by key {key_id}", ok.stdout)
            hex_key = base64.b64decode(public).hex()
            self.assertEqual(self.run_tool("verify", str(archive), str(release_path), "--keys", hex_key).returncode, 0)
            wrong = self.run_tool("verify", str(archive), str(release_path), "--keys", OTHER_KEY)
            self.assertEqual(wrong.returncode, 1)
            self.assertIn("FAIL no_key", wrong.stdout)
            revoked = tmp / "revoked.json"
            revoked.write_text(json.dumps({"schema_version": 1, "keys": [{"key_id": key_id}]}))
            out = self.run_tool("verify", str(archive), str(release_path), "--keys", public, "--revoked", str(revoked))
            self.assertIn("FAIL revoked", out.stdout)
            tampered = tmp / "tampered.tar"
            data = bytearray(archive.read_bytes())
            data[600] ^= 1
            tampered.write_bytes(bytes(data))
            out = self.run_tool("verify", str(tampered), str(release_path), "--keys", public)
            self.assertIn("FAIL bad_hash", out.stdout)

            index = tmp / "index.json"
            out = self.run_tool("index", str(index), str(release_path), "--url", "packages/holdall.tar",
                                "--name", "Hold-All Domination", "--verified")
            self.assertEqual(out.returncode, 0, out.stderr)
            [entry] = mp.parse_index(json.loads(index.read_text()))
            self.assertEqual((entry.release.id, entry.verified, entry.url, entry.key_id),
                             ("org.atalaia.holdall", True, "packages/holdall.tar", key_id))
            bad = self.run_tool("index", str(index), str(release_path), "--url", "http://example.org/x.tar")
            self.assertNotEqual(bad.returncode, 0)
            self.assertEqual(len(mp.parse_index(json.loads(index.read_text()))), 1)  # unchanged

    def test_an_encrypted_key_needs_its_passphrase(self):
        with tempfile.TemporaryDirectory() as tmp:
            pem = Path(tmp) / "mode.pem"
            env = {"ATALAIA_MODE_KEY_PASSPHRASE": "correct horse"}
            self.assertEqual(self.run_tool("keygen", "--out", str(pem), env=env).returncode, 0)
            self.assertIn(b"ENCRYPTED", pem.read_bytes())
            self.assertEqual(self.run_tool("pubkey", "--key", str(pem), env=env).returncode, 0)
            self.assertNotEqual(self.run_tool("pubkey", "--key", str(pem),
                                              env={"ATALAIA_MODE_KEY_PASSPHRASE": "wrong"}).returncode, 0)


if __name__ == "__main__":
    unittest.main()
