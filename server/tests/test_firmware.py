# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The firmware catalogue's signing rules (plan phase 19), with no database: also run by tools/check.sh.

The Ed25519 check is tested with RFC 8032's own test vectors (section 7.1, as
``protocol/vectors/chrono_record.json`` quotes them), then the catalogue's
manifest, key ids, versions and platforms. The API on PostgreSQL:
``test_devices.py``.
"""

from __future__ import annotations

import base64
import json
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from atalaia_server import firmware

REPO = Path(__file__).resolve().parents[2]
RFC8032 = json.loads((REPO / "protocol" / "vectors" / "chrono_record.json").read_text(encoding="utf-8"))["rfc8032"]


class SignatureTests(unittest.TestCase):
    def test_rfc_8032_vectors(self) -> None:
        for v in RFC8032:
            with self.subTest(v["name"]):
                key, msg, sig = (bytes.fromhex(v[k]) for k in ("public_key", "message", "signature"))
                self.assertTrue(firmware.verify_signature(key, msg, sig))
                self.assertFalse(firmware.verify_signature(key, msg + b"x", sig))
                self.assertFalse(firmware.verify_signature(key, msg, bytes([sig[0] ^ 1]) + sig[1:]))
        self.assertFalse(firmware.verify_signature(b"\x00" * 31, b"", b"\x00" * 64))

    def test_the_manifest_is_what_is_signed(self) -> None:
        self.assertEqual(firmware.manifest("esp32s3", "0.4.0", 1572864, "ab" * 32),
                         b"atalaia-firmware-release-v1\nplatform=esp32s3\nversion=0.4.0\nsize=1572864\n"
                         b"sha256=" + b"ab" * 32 + b"\n")
        private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(RFC8032[0]["seed"]))
        public = base64.b64encode(bytes.fromhex(RFC8032[0]["public_key"])).decode()
        sig = base64.b64encode(private.sign(firmware.manifest("esp32s3", "0.4.0", 10, "ab" * 32))).decode()
        self.assertEqual(firmware.signer([public], "esp32s3", "0.4.0", 10, "ab" * 32, sig), firmware.key_id(public))
        for changed in (("esp32", "0.4.0", 10, "ab" * 32), ("esp32s3", "0.4.1", 10, "ab" * 32),
                        ("esp32s3", "0.4.0", 11, "ab" * 32), ("esp32s3", "0.4.0", 10, "cd" * 32)):
            with self.subTest(changed=changed):
                self.assertIsNone(firmware.signer([public], *changed, sig))
        self.assertIsNone(firmware.signer([], "esp32s3", "0.4.0", 10, "ab" * 32, sig))  # no key: nothing verifies
        self.assertEqual(len(firmware.key_id(public)), 16)

    def test_entries(self) -> None:
        good = {"platform": "esp32s3", "version": "0.4.0", "size": 10, "sha256": "ab" * 32,
                "signature": base64.b64encode(b"\x00" * 64).decode()}
        firmware.check_entry(dict(good))
        for change, code in (({"platform": "ESP32S3"}, "bad_platform"), ({"version": "0.4"}, "bad_version"),
                             ({"size": 0}, "bad_size"), ({"size": True}, "bad_size"),
                             ({"size": firmware.MAX_SIZE + 1}, "bad_size"), ({"sha256": "ab" * 31}, "bad_sha256"),
                             ({"signature": "AAAA"}, "bad_signature")):
            with self.subTest(change=change):
                with self.assertRaises(firmware.FirmwareError) as caught:
                    firmware.check_entry({**good, **change})
                self.assertEqual(caught.exception.code, code)


class VersionTests(unittest.TestCase):
    def test_order(self) -> None:
        versions = ["0.10.0", "0.9.9", "1.0.0-rc.2", "1.0.0", "1.0.0-rc.10", "0.4.0"]
        ordered = sorted(versions, key=firmware.version_key)
        self.assertEqual(ordered, ["0.4.0", "0.9.9", "0.10.0", "1.0.0-rc.2", "1.0.0-rc.10", "1.0.0"])
        for bad in ("1.0", "v1.0.0", "1.0.0-", "1.0.0+build", "", "12345.0.0", "1.0.0-rc..1"):
            self.assertIsNone(firmware.version_key(bad), bad)

    def test_platforms(self) -> None:
        self.assertEqual([firmware.platform_name(v) for v in ("0", "1", 2, "android", "9", None, True, "esp8266")],
                         ["esp32", "esp32s3", "linux", "android", None, None, None, None])


if __name__ == "__main__":
    unittest.main()
