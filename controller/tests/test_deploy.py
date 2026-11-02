# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The deployment files (security review SC-7 and FLD-5): the systemd unit's hardening and Mosquitto's listeners."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"


def directives(path: Path) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.fullmatch(r"([A-Za-z]+)=(.*)", line.strip())
        if m:
            out.setdefault(m.group(1), []).append(m.group(2))
    return out


class ServiceUnitTests(unittest.TestCase):
    def setUp(self):
        self.unit = directives(DEPLOY / "atalaia-controller.service")

    def test_hardening(self):
        for key, value in (("NoNewPrivileges", "yes"), ("ProtectSystem", "strict"), ("ProtectHome", "yes"),
                           ("PrivateTmp", "yes"), ("DevicePolicy", "closed")):
            self.assertEqual(self.unit.get(key), [value], key)
        self.assertEqual(self.unit["ReadWritePaths"], ["/var/lib/atalaia"])
        self.assertEqual(set(self.unit["RestrictAddressFamilies"][0].split()),
                         {"AF_UNIX", "AF_INET", "AF_INET6", "AF_NETLINK"})

    def test_the_radio_modem_is_still_reachable(self):
        # The serial ports are opened by the user's group, dialout, and allowed through the device policy.
        self.assertEqual(self.unit["Group"], ["dialout"])
        self.assertEqual(set(self.unit["DeviceAllow"]), {"char-ttyACM rw", "char-ttyUSB rw"})

    def test_the_state_folder_is_the_examples_database_folder(self):
        example = (DEPLOY.parent / "controller.example.toml").read_text(encoding="utf-8")
        self.assertIn('db_path = "/var/lib/atalaia/', example)


class MosquittoTests(unittest.TestCase):
    def test_plain_mqtt_is_loopback_only_and_the_field_gets_tls(self):
        plain = (DEPLOY / "mosquitto.conf").read_text(encoding="utf-8")
        self.assertRegex(plain, r"(?m)^listener 1883 127\.0\.0\.1$")
        self.assertNotRegex(plain, r"(?m)^listener 1883\s*$")
        self.assertIn("allow_anonymous false", plain)
        tls = {k: [v.strip()] for k, _, v in (line.partition(" ") for line in
                                              (DEPLOY / "mosquitto-tls.conf").read_text().splitlines()
                                              if line and not line.startswith("#"))}
        self.assertEqual(tls["listener"], ["8883"])
        for key in ("cafile", "certfile", "keyfile"):
            self.assertIn(key, tls)
        self.assertEqual(tls["tls_version"], ["tlsv1.2"])


if __name__ == "__main__":
    unittest.main()
