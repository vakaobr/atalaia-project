# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A controller with a wrong wall clock (a Pi 4 has no real-time clock): the guard, the GM's forward-only
correction, the retention purge that waits, certificates that stay valid, durations that do not care.

    cd controller && python -m unittest discover -s tests
"""

from __future__ import annotations

import calendar
import datetime
import os
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from support import CORE, config
from atalaia_controller import tls, wallclock
from atalaia_controller.api import create_app
from atalaia_controller.engine import Controller
from atalaia_controller.store import Store
from atalaia_controller.ws import Hub
from atalaia_controller.api import Auth

REL = wallclock.RELEASE_DATE
DAY = 86400


class FakeTime:
    """time.time() and time.monotonic() the test moves: the wall clock apart from the monotonic one."""

    def __init__(self, wall: float) -> None:
        self.wall, self.mono = wall, 1000.0

    def time(self) -> float:
        return self.wall

    def monotonic(self) -> float:
        return self.mono

    def advance(self, s: float) -> None:
        self.wall += s
        self.mono += s


class GuardCase(unittest.TestCase):
    def setUp(self) -> None:
        wallclock.reset()
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.tmp.name, "c.db"))
        self.ft = FakeTime(REL + 10 * DAY)
        p = mock.patch("time.time", self.ft.time)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(wallclock.reset)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.store.close)
        self.guard = wallclock.ClockGuard(self.store, mono=self.ft.monotonic)

    def test_release_date_is_sane(self):
        self.assertLessEqual(REL, time.time())
        changelog = (Path(__file__).resolve().parents[2] / "CHANGELOG.md").read_text(encoding="utf-8")
        dates = re.findall(r"^## .*?(\d{4})-(\d{2})-(\d{2})", changelog, re.M)
        if dates:  # not older than the newest dated release heading
            newest = max(calendar.timegm((int(y), int(m), int(d), 0, 0, 0)) for y, m, d in dates)
            self.assertGreaterEqual(REL, newest - 40 * DAY)

    def test_plausible_clock_is_ok_and_remembered(self):
        self.guard.start()
        self.assertTrue(self.guard.status()["ok"])
        self.assertAlmostEqual(self.guard.high_water(), self.ft.wall, delta=1)
        self.assertTrue(self.guard.purge_allowed())

    def test_1970_is_wrong(self):
        self.ft.wall = 5.0
        self.guard.start()
        s = self.guard.status()
        self.assertFalse(s["ok"])
        self.assertEqual(s["reason"], "before_release")
        self.assertFalse(self.guard.purge_allowed())
        self.assertTrue(s["purge_held"])

    def test_days_behind_is_caught_by_the_high_water_mark(self):
        self.guard.start()
        self.ft.advance(2 * DAY)
        self.guard.tick()  # stored: the controller saw this time
        self.ft.wall -= 3 * DAY  # a power cycle: the clock comes up at an old time
        fresh = wallclock.ClockGuard(self.store, mono=self.ft.monotonic)
        s = fresh.status()
        self.assertFalse(s["ok"])
        self.assertEqual(s["reason"], "behind_records")

    def test_newest_record_in_the_store_counts(self):
        with mock.patch.object(Store, "newest_wall_time", return_value=REL + 50 * DAY):
            fresh = wallclock.ClockGuard(self.store, mono=self.ft.monotonic)
            self.assertFalse(fresh.status()["ok"])

    def test_set_moves_forward_only_and_never_below_the_floor(self):
        self.ft.wall = 5.0
        self.guard.start()
        with self.assertRaises(wallclock.ClockError) as e:
            self.guard.set(REL - 5 * DAY)  # this device's clock is wrong too
        self.assertEqual(e.exception.code, "below_floor")
        for bad in (True, "x", None, float("nan")):
            with self.assertRaises(wallclock.ClockError) as e:
                self.guard.set(bad)
            self.assertEqual(e.exception.code, "invalid")
        with self.assertRaises(wallclock.ClockError) as e:
            self.guard.set(REL + 10 * 365 * DAY)
        self.assertEqual(e.exception.code, "too_far")
        s = self.guard.set(REL + 3 * DAY)
        self.assertTrue(s["ok"])
        self.assertAlmostEqual(wallclock.now(), REL + 3 * DAY, delta=2)
        self.assertTrue(self.guard.purge_allowed())
        # The correction follows the system clock, which goes on.
        self.ft.advance(100)
        self.assertAlmostEqual(wallclock.now(), REL + 3 * DAY + 100, delta=2)

    def test_backwards_is_refused_so_expired_tokens_stay_expired(self):
        self.guard.start()
        before = wallclock.now()
        with self.assertRaises(wallclock.ClockError) as e:
            self.guard.set(before - 3600)  # under what the controller has seen
        self.assertEqual(e.exception.code, "below_floor")
        self.guard._hw = 0.0  # even with nothing seen before: not backwards
        with self.assertRaises(wallclock.ClockError) as e:
            self.guard.set(before - 3600)
        self.assertEqual(e.exception.code, "backwards")
        self.assertEqual(wallclock.offset(), 0.0)
        # A small forward step from a plausible clock is fine; a month is not.
        self.guard.set(before + 3600)
        with self.assertRaises(wallclock.ClockError) as e:
            self.guard.set(wallclock.now() + 30 * DAY)
        self.assertEqual(e.exception.code, "too_far")

    def test_a_forward_jump_holds_the_purge_and_is_reported(self):
        self.guard.start()
        self.guard.tick()
        self.ft.wall += 400 * DAY  # NTP, or a wrong clock coming right the other way
        self.guard.tick()
        s = self.guard.status()
        self.assertGreater(s["last_jump"]["seconds"], 300 * DAY)
        self.assertFalse(self.guard.purge_allowed())
        self.ft.mono += wallclock.PURGE_HOLD_S + 1
        self.ft.wall += wallclock.PURGE_HOLD_S + 1
        self.assertTrue(self.guard.purge_allowed())

    def test_a_small_correction_is_a_jump_but_holds_nothing(self):
        self.guard.start()
        self.ft.wall += 90
        self.guard.tick()
        self.assertIsNotNone(self.guard.status()["last_jump"])
        self.assertTrue(self.guard.purge_allowed())


class ControllerClockCase(unittest.TestCase):
    def setUp(self) -> None:
        wallclock.reset()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(wallclock.reset)
        cfg = config(self.tmp.name)
        self.ctrl = Controller(cfg, Store(cfg.db_path), core=CORE)
        self.client = TestClient(create_app(self.ctrl, Hub(), Auth(cfg.gm_token, cfg.read_token)))
        self.gm = {"Authorization": f"Bearer {cfg.gm_token}"}
        self.read = {"Authorization": f"Bearer {cfg.read_token}"}

    def test_status_carries_the_clock_and_the_api_sets_it_for_a_gm_only(self):
        self.assertTrue(self.client.get("/api/v1/controller", headers=self.read).json()["clock"]["ok"])
        self.assertTrue(self.client.get("/api/v1/clock", headers=self.read).json()["ok"])
        self.assertEqual(self.client.put("/api/v1/clock", json={"epoch": time.time() + 5}).status_code, 401)
        self.assertEqual(self.client.put("/api/v1/clock", headers=self.read,
                                         json={"epoch": time.time() + 5}).status_code, 403)
        r = self.client.put("/api/v1/clock", headers=self.gm, json={"epoch": time.time() - 3600})
        self.assertEqual(r.status_code, 409)
        self.assertIn(r.json()["code"], ("backwards", "below_floor"))
        self.assertEqual(self.client.put("/api/v1/clock", headers=self.gm, json={"epoch": "now"}).status_code, 400)

    def test_wrong_clock_in_the_status_and_a_set_from_the_gm_device(self):
        with mock.patch("time.time", return_value=100.0):
            self.ctrl.clock_guard._hw = None
            st = self.client.get("/api/v1/controller", headers=self.read).json()["clock"]
            self.assertFalse(st["ok"])
            r = self.client.put("/api/v1/clock", headers=self.gm, json={"epoch": REL + 2 * DAY})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertTrue(r.json()["ok"])
            self.assertGreater(wallclock.now(), REL + DAY)

    def test_durations_do_not_use_the_wall_clock(self):
        t0 = self.ctrl.now_ms()
        with mock.patch("time.time", return_value=5.0):  # a clock that jumped back to 1970
            t1 = self.ctrl.now_ms()
        self.assertGreaterEqual(t1, t0)
        self.assertLess(t1 - t0, 5000)


class WrongClockUsersCase(unittest.TestCase):
    def setUp(self) -> None:
        wallclock.reset()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        cfg = config(self.tmp.name)
        self.store = Store(cfg.db_path)
        self.ctrl = Controller(cfg, self.store, core=CORE)

    def test_pod_revs_stay_above_what_a_pod_holds_when_the_clock_comes_up_at_1970(self):
        from atalaia_controller.pod_config import PodConfig
        first = PodConfig(self.ctrl, clock=lambda: 2_000_000_000.0)._next_rev(3)
        later = PodConfig(self.ctrl, clock=lambda: 5.0)  # after a restart with a wrong clock
        self.assertGreater(later._next_rev(3), first)
        self.assertGreater(later._next_rev(4), first)

    def test_nothing_is_purged_while_the_clock_is_wrong(self):
        from atalaia_controller.checkin import Checkin
        svc = Checkin(self.ctrl)
        with mock.patch.object(self.ctrl.clock_guard, "purge_allowed", return_value=False):
            self.assertIsNone(svc.purge(force=True))
        self.assertIsNotNone(svc.purge(force=True))

    def test_a_visibility_grant_runs_on_the_monotonic_clock(self):
        from atalaia_controller.positions import Positions
        mono = [100.0]
        wall = [REL + 5 * DAY]
        pos = Positions(self.ctrl, wall=lambda: wall[0], mono=lambda: mono[0])
        with pos._lock:
            pos.grants[(1, "red", "blue")] = mono[0] + 60
        wall[0] += 10 * DAY  # NTP corrects the wall clock by days: the grant has 60 s to run
        pos.tick()
        self.assertIn((1, "red", "blue"), pos.grants)
        mono[0] += 61
        pos.tick()
        self.assertNotIn((1, "red", "blue"), pos.grants)


class TlsWrongClockCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, "tls")

    def _validity(self, path):
        from cryptography import x509
        cert = x509.load_pem_x509_certificate(Path(path).read_bytes())
        nb = getattr(cert, "not_valid_before_utc", None) or cert.not_valid_before.replace(tzinfo=datetime.timezone.utc)
        return nb, tls._not_after(cert)

    def test_a_1970_clock_makes_certificates_a_phone_with_the_right_time_accepts(self):
        epoch = datetime.datetime(1970, 1, 2, tzinfo=datetime.timezone.utc)
        t = tls.ensure(self.dir, ["10.0.2.2"], now=epoch)
        today = datetime.datetime.now(datetime.timezone.utc)
        for path in (t.server_cert, Path(self.dir) / "ca.pem"):
            nb, na = self._validity(path)
            self.assertLessEqual(nb, today)
            self.assertGreater(na, today + datetime.timedelta(days=300))

    def test_days_behind_is_backdated_not_future(self):
        behind = datetime.datetime.fromtimestamp(REL, datetime.timezone.utc) - datetime.timedelta(days=4)
        t = tls.ensure(self.dir, ["10.0.2.2"], now=behind)
        nb, _ = self._validity(t.server_cert)
        self.assertLess(nb, datetime.datetime.fromtimestamp(REL, datetime.timezone.utc))

    def test_a_ca_made_at_1970_is_replaced(self):
        # Made by an older controller, with the clock at 1970: expired in 1980.
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
        d = Path(self.dir)
        d.mkdir(parents=True)
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "old")])
        old = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(1).not_valid_before(old).not_valid_after(old + datetime.timedelta(days=3653))
                .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True).sign(key, hashes.SHA256()))
        pem = serialization.Encoding.PEM
        (d / "ca.key").write_bytes(key.private_bytes(pem, serialization.PrivateFormat.PKCS8,
                                                      serialization.NoEncryption()))
        (d / "ca.pem").write_bytes(cert.public_bytes(pem))
        t = tls.ensure(self.dir, ["10.0.2.2"])
        _, na = self._validity(d / "ca.pem")
        self.assertGreater(na, datetime.datetime.now(datetime.timezone.utc))
        self.assertNotEqual(t.ca_pem, cert.public_bytes(pem))


if __name__ == "__main__":
    unittest.main()
