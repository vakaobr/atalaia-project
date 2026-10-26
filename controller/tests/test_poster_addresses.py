# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which addresses the check-in poster lists and the certificate covers (decisions check-R8, check-R9):
the shared cases of protocol/vectors/checkin.json ("poster_addresses", also run by the app's Dart), and
the controller's use of them: a stale configured address is dropped and warned about, a current one is
listed, a name stays, a saved poster is re-derived at start, and the certificate covers the poster.

    cd controller && python -m unittest discover -s tests
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401  (puts the controller on the path)
from support import CORE, config

from cryptography import x509

from atalaia_controller import tls
from atalaia_controller.addresses import FieldAddresses, url_host
from atalaia_controller.main import build

VECTORS = json.loads((Path(__file__).resolve().parents[2] / "protocol" / "vectors" / "checkin.json")
                     .read_text(encoding="utf-8"))["poster_addresses"]["cases"]

PI = ["localhost", "127.0.0.1", "pi", "pi.local", "10.42.0.1"]
ON = ["10.42.0.1", "127.0.0.1"]


def addresses(**kw) -> FieldAddresses:
    base = {"found": PI, "interfaces": ON, "container": False}
    base.update(kw)
    return FieldAddresses(**base)


class SharedCases(unittest.TestCase):
    def test_vectors(self) -> None:
        self.assertGreaterEqual(len(VECTORS), 10)
        for c in VECTORS:
            with self.subTest(c["name"]):
                i, want = c["input"], c["expected"]
                plan = FieldAddresses(tls_names=i["tls_names"], found=i["found"], interfaces=i["interfaces"],
                                      tls_port=i["tls_port"], container=i["container"]
                                      ).plan(i["saved_urls"], i["checkin_urls"])
                self.assertEqual(plan.poster, want["poster"])
                self.assertEqual(plan.dropped, want["dropped"])
                self.assertEqual(sorted(plan.san), want["san"])
                # check-R9: the certificate covers every host on the poster.
                self.assertLessEqual({url_host(u) for u in plan.poster}, set(plan.san))


class PlanTests(unittest.TestCase):
    def test_stale_dropped_current_present_name_kept(self) -> None:
        plan = addresses(tls_names=["192.168.1.50", "campo.lan", "10.42.0.1"]).plan()
        self.assertEqual(plan.poster, ["https://campo.lan:8443", "https://10.42.0.1:8443", "https://pi:8443"])
        self.assertEqual(plan.dropped, ["192.168.1.50"])
        self.assertNotIn("192.168.1.50", plan.san)
        self.assertIn("campo.lan", plan.san)

    def test_interface_addresses_is_a_list_of_ips(self) -> None:
        from atalaia_controller.addresses import interface_addresses  # noqa: PLC0415
        import ipaddress  # noqa: PLC0415

        for a in interface_addresses():
            ipaddress.ip_address(a)


class ControllerTests(unittest.TestCase):
    """main.build with the host's addresses given: the poster, the saved poster and the certificate."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.bundles = []

    def tearDown(self) -> None:
        for b in self.bundles:
            b.controller.stop()
            b.store.close()
        self.tmp.cleanup()

    def open(self, addrs: FieldAddresses, **cfg):
        c = config(self.tmp.name, **cfg)
        b = build(c, core=CORE, load_core_lib=False, addresses=addrs)
        self.bundles.append(b)
        return b

    def cert_names(self) -> set[str]:
        pem = (Path(self.tmp.name) / "tls" / "server.pem").read_bytes()
        san = x509.load_pem_x509_certificate(pem).extensions.get_extension_for_class(
            x509.SubjectAlternativeName).value
        return {str(i) for i in san.get_values_for_type(x509.IPAddress)} | set(san.get_values_for_type(x509.DNSName))

    def test_stale_configured_address_is_dropped_and_warned_about(self) -> None:
        with self.assertLogs("atalaia.addresses", "WARNING") as logs:
            b = self.open(addresses(tls_names=["192.168.1.50", "10.42.0.1"]), tls_names=["192.168.1.50", "10.42.0.1"])
        self.assertTrue(any("192.168.1.50" in line for line in logs.output), logs.output)
        urls = b.controller.checkin.poster()["urls"]
        self.assertEqual(urls[0], "https://10.42.0.1:8443")
        self.assertNotIn("https://192.168.1.50:8443", urls)
        self.assertEqual(b.controller.link_urls, urls)
        self.assertNotIn("192.168.1.50", self.cert_names())
        self.assertTrue({"10.42.0.1", "pi", "pi.local"} <= self.cert_names())

    def test_current_address_and_hostname_are_listed(self) -> None:
        b = self.open(addresses(tls_names=["campo.lan", "10.42.0.1"]), tls_names=["campo.lan", "10.42.0.1"])
        self.assertEqual(b.controller.checkin.poster()["urls"],
                         ["https://campo.lan:8443", "https://10.42.0.1:8443", "https://pi:8443"])
        self.assertIn("campo.lan", self.cert_names())

    def test_saved_poster_is_rederived_on_start(self) -> None:
        b = self.open(addresses(tls_names=["10.42.0.1"]), tls_names=["10.42.0.1"])
        svc = b.controller.checkin
        # The GM pinned the poster to two addresses and a name, and chose its other fields.
        svc.store.set_setting("checkin.poster", json.dumps({
            "urls": ["https://192.168.1.50:8443", "https://campo.lan:8443"], "wifi_ssid": "CAMPO",
            "game_id": 7, "field_name": "Campo Norte"}))
        b.controller.stop()
        b.store.close()
        self.bundles.clear()
        with self.assertLogs("atalaia.addresses", "WARNING") as logs:
            b = self.open(addresses(tls_names=["10.42.0.1"]), tls_names=["10.42.0.1"])
        self.assertTrue(any("192.168.1.50" in line for line in logs.output))
        p = b.controller.checkin.poster()
        self.assertEqual(p["urls"], ["https://campo.lan:8443"])                  # the name stays, the stale one goes
        self.assertEqual((p["wifi_ssid"], p["game_id"], p["field_name"]), ("CAMPO", 7, "Campo Norte"))
        saved = json.loads(b.store.get_setting("checkin.poster"))
        self.assertEqual(saved["urls"], ["https://campo.lan:8443"])              # dropped from the setting too
        self.assertIn("campo.lan", self.cert_names())                            # the certificate covers it
        # Only stale addresses saved: the poster is the default again; the other fields are kept.
        b.controller.checkin.store.set_setting("checkin.poster", json.dumps(
            {"urls": ["https://192.168.1.50:8443"], "game_id": 7}))
        b.controller.stop()
        b.store.close()
        self.bundles.clear()
        b = self.open(addresses(tls_names=["10.42.0.1"]), tls_names=["10.42.0.1"])
        p = b.controller.checkin.poster()
        self.assertEqual(p["urls"][0], "https://10.42.0.1:8443")
        self.assertEqual(p["game_id"], 7)
        self.assertNotIn("urls", json.loads(b.store.get_setting("checkin.poster")))

    def test_checkin_urls_in_config(self) -> None:
        """[checkin] urls: an IP not on an interface is dropped and warned about, a name stays."""
        with self.assertLogs("atalaia.addresses", "WARNING") as logs:
            b = self.open(addresses(), checkin_urls=["https://172.16.9.9:8443", "https://campo.lan"])
        self.assertTrue(any("172.16.9.9" in line for line in logs.output))
        self.assertEqual(b.controller.checkin.poster()["urls"], ["https://campo.lan"])
        self.assertIn("campo.lan", self.cert_names())

    def test_put_poster_with_a_stale_address(self) -> None:
        b = self.open(addresses())
        svc = b.controller.checkin
        with self.assertLogs("atalaia.addresses", "WARNING"):
            out = svc.set_poster({"urls": ["https://192.168.1.50:8443", "https://10.42.0.1:8443"], "game_id": 3})
        self.assertEqual(out["urls"], ["https://10.42.0.1:8443"])
        self.assertEqual(json.loads(svc.store.get_setting("checkin.poster"))["urls"], ["https://10.42.0.1:8443"])
        out = svc.set_poster({"urls": ["https://192.168.1.50:8443"]})   # nothing current left: the default
        self.assertEqual(out["urls"][0], "https://pi:8443")
        self.assertNotIn("urls", json.loads(svc.store.get_setting("checkin.poster")))

    def test_container_keeps_configured_addresses(self) -> None:
        b = self.open(addresses(tls_names=["192.168.1.50"], container=True), tls_names=["192.168.1.50"])
        self.assertEqual(b.controller.checkin.poster()["urls"], ["https://192.168.1.50:8443"])


if __name__ == "__main__":
    unittest.main()
