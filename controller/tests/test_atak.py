# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The ATAK / CoT emitter and the field image's georeference (ADR-P4-7 as amended, P4R18; plan phase 9).

Every CoT event is checked against protocol/vectors/cot.json, whose facts are copied from the
published CoT schema, the TAK CoT definitions and the TAK protocol (each with its source), not
from the emitter. The georeference's known answers come from their sources too: Wikipedia's
"World file" worked example, and geometry (an affine map keeps midpoints and parallelograms).

    cd controller && python -m unittest tests.test_atak
"""

from __future__ import annotations

import json
import math
import re
import socket
import struct
import threading
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Optional

from p3support import GM, READ, P3Case, bearer
from support import config, free_port, wait_for

from atalaia_controller import atak, georef, sync_format
from atalaia_controller.config import ConfigError, load_config
from atalaia_controller.georef import ControlPoint, Georef, GeorefError, fit_affine

COT = json.loads((Path(__file__).resolve().parents[2] / "protocol" / "vectors" / "cot.json").read_text("utf-8"))
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32  # the field image is stored as uploaded
# Two opposite corners of a north-up image near Lisbon.
TL = {"x": 0.0, "y": 0.0, "lat": 38.7240, "lon": -9.1420}
BR = {"x": 1.0, "y": 1.0, "lat": 38.7200, "lon": -9.1360}
HOSTILE = "</remarks><x a=\"1\">&amp; '\"\x01\x1b\ud800\ufffe\n\tCaixa"
HOSTILE_NODE = HOSTILE.replace("\ud800", "")  # a box's name comes from its HELLO: valid UTF-8


def cp(x: float, y: float, lat: float, lon: float) -> ControlPoint:
    return ControlPoint(x, y, lat, lon)


class Receiver:
    """A UDP socket on the loopback that keeps every datagram."""

    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.05)
        self.port = self.sock.getsockname()[1]

    def drain(self, wait: float = 0.3) -> list[bytes]:
        out = []
        end = 0.0
        import time  # noqa: PLC0415

        end = time.monotonic() + wait
        while time.monotonic() < end:
            try:
                out.append(self.sock.recv(65535))
                end = time.monotonic() + 0.1
            except socket.timeout:
                if out:
                    break
        return out

    def close(self) -> None:
        self.sock.close()


class TcpReceiver:
    """A staff ATAK device on the loopback: keeps the bytes of each connection."""

    def __init__(self) -> None:
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(8)
        self.port = self.srv.getsockname()[1]
        self.connections: list[bytes] = []
        self._stop = False
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        self.srv.settimeout(0.1)
        while not self._stop:
            try:
                conn, _ = self.srv.accept()
            except (socket.timeout, OSError):
                continue
            with conn:
                conn.settimeout(2)
                data = b""
                while True:
                    chunk = conn.recv(65535)
                    if not chunk:
                        break
                    data += chunk
            self.connections.append(data)

    def close(self) -> None:
        self._stop = True
        self.thread.join(2)
        self.srv.close()


def split_stream(data: bytes) -> list[bytes]:
    """TAK Protocol version 0 on TCP: events broken apart right after each "</event>" (cot.json transport)."""
    text = data.decode("utf-8")
    parts = text.split("</event>")
    assert parts[-1] == "", "nothing may follow the last </event>"
    return [(p + "</event>").encode("utf-8") for p in parts[:-1]]


class CotChecks(unittest.TestCase):
    """The CoT schema's rules, from cot.json (a helper: its subclasses hold the tests)."""

    TIME_RE = re.compile(COT["time"]["pattern"])

    def check_event(self, data: bytes) -> ET.Element:
        self.assertLessEqual(len(data), atak.DATAGRAM_MAX)
        text = data.decode("utf-8")
        decl, newline, body = text.partition("\n")
        self.assertTrue(decl.startswith("<?xml ") and decl.endswith("?>"), decl)  # cot.json transport
        self.assertEqual(newline, "\n")
        self.assertTrue(body.startswith("<event ") and body.endswith("</event>"), body[-40:])
        root = ET.fromstring(data)
        self.assertEqual(root.tag, "event")
        ev = COT["event"]
        self.assertLessEqual(set(ev["required_attributes"]), set(root.attrib))
        self.assertEqual(root.get("version"), ev["version"])
        self.assertRegex(root.get("type"), "^(?:" + ev["type_pattern"] + ")$")
        self.assertRegex(root.get("how"), "^(?:" + ev["how_pattern"] + ")$")
        for name in ("time", "start", "stale"):
            self.assertRegex(root.get(name), self.TIME_RE)
        self.assertEqual(sorted(c.tag for c in root), sorted(ev["children"]))
        point = root.find("point")
        self.assertLessEqual(set(COT["point"]["required_attributes"]), set(point.attrib))
        lat, lon = float(point.get("lat")), float(point.get("lon"))
        self.assertTrue(COT["point"]["lat_range"][0] <= lat <= COT["point"]["lat_range"][1])
        self.assertTrue(COT["point"]["lon_range"][0] <= lon <= COT["point"]["lon_range"][1])
        for name in ("hae", "ce", "le"):
            float(point.get(name))
        details = COT["details"]
        for child in root.find("detail"):
            spec = details.get(child.tag)
            self.assertIsNotNone(spec, f"a detail the TAK definitions do not have: {child.tag}")
            self.assertLessEqual(set(spec.get("required", [])), set(child.attrib), child.tag)
            for name in spec.get("integer", []):
                if name in child.attrib:
                    v = int(child.get(name))
                    self.assertTrue(-(1 << 31) <= v < (1 << 31))
            if child.tag == "__group":
                self.assertIn(child.get("name"), COT["teams"]["names"])
                self.assertIn(child.get("role"), COT["teams"]["roles"])
        return root


class CotVectorTests(CotChecks):
    """cot.json itself, the TAK examples and the emitter's building blocks (once, not per subclass)."""

    def test_time_pattern_accepts_the_schema_examples(self):
        for t in COT["time"]["valid"]:
            self.assertRegex(t, self.TIME_RE)
        self.assertRegex(atak.cot_time(1608148774.91), self.TIME_RE)
        self.assertEqual(atak.cot_time(1608148774.91), "2020-12-16T19:59:34.910Z")  # takcot example's time

    def test_type_strings_are_the_sources(self):
        types = COT["types"]
        for name in (atak.TYPE_PROP, atak.TYPE_ZONE_POINT, atak.TYPE_PLAYER):
            self.assertIn(name, types)
            self.assertNotIn("not used", types[name]["use"])
            self.assertIn(name.replace("a-f-", "a-.-"), types[name]["source"])
        self.assertIn(atak.TYPE_PLAYER.split("-")[1], COT["affiliations"])
        for how in (atak.HOW_IMAGE, atak.HOW_PASTED, atak.HOW_GPS):
            self.assertIn(how, COT["how"])
        self.assertIn(atak.GROUP_ROLE, COT["teams"]["roles"])
        self.assertEqual(list(atak.ATAK_TEAMS), COT["teams"]["names"])
        self.assertEqual(atak.DEFAULT_MULTICAST, COT["transport"]["multicast"])
        self.assertEqual(atak.DEFAULT_STAFF_PORT, COT["transport"]["staff_port"])
        self.assertEqual(atak.UNKNOWN, COT["point"]["unknown_value"])

    def test_argb_as_in_the_tak_examples(self):
        for ex in COT["argb_examples"]:
            self.assertEqual(f"{ex['argb'] & 0xFFFFFF:06x}", ex["rgb"])
        self.assertEqual(atak.team_colour(None, []), -1)
        red = atak.team_colour("red", ["red", "blue"])
        self.assertEqual(red & 0xFFFFFFFF, 0xFFD7263D)  # the console's red, opaque
        self.assertEqual(atak.team_colour("vermelha", []), red)
        self.assertEqual(atak.atak_team("blue"), "Blue")
        self.assertEqual(atak.atak_team("Azul"), "Blue")
        self.assertEqual(atak.atak_team("dark_green"), "Dark Green")
        self.assertIsNone(atak.atak_team("wolves"))
        self.assertIsNone(atak.atak_team("black"))  # ATAK has no black team

    def test_the_tak_examples_pass_the_rules(self):
        # The vectors' rules hold for the published samples: they are not shaped to the emitter.
        for s in COT["samples"]:
            with self.subTest(s["name"]):
                ev, point = s["event"], s["point"]
                self.assertLessEqual(set(COT["event"]["required_attributes"]), set(ev))
                self.assertEqual(ev["version"], COT["event"]["version"])
                self.assertRegex(ev["type"], "^(?:" + COT["event"]["type_pattern"] + ")$")
                self.assertRegex(ev["how"], "^(?:" + COT["event"]["how_pattern"] + ")$")
                for name in ("time", "start", "stale"):
                    self.assertRegex(ev[name], self.TIME_RE)
                self.assertLessEqual(set(COT["point"]["required_attributes"]), set(point))
                self.assertEqual(point["hae"], COT["point"]["unknown_value"])
                for tag, attrs in s["detail"].items():
                    self.assertLessEqual(set(COT["details"][tag].get("required", [])), set(attrs), tag)

    def test_the_emitter_rebuilds_the_tak_examples(self):
        # Known answers: an event made from a sample's values gives back the sample's text.
        def epoch(text: str) -> float:
            import datetime  # noqa: PLC0415

            return datetime.datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%f%z").timestamp()

        for s in COT["samples"]:
            with self.subTest(s["name"]):
                ev, point, det = s["event"], s["point"], s["detail"]
                argb = int(det["color"]["argb"])
                data = atak.event_xml(uid=ev["uid"], cot_type=ev["type"], how=ev["how"], lat=float(point["lat"]),
                                      lon=float(point["lon"]), now=epoch(ev["time"]), start=epoch(ev["start"]),
                                      stale=epoch(ev["stale"]),
                                      detail=atak.marker_detail(det["contact"]["callsign"], "", argb))
                root = self.check_event(data)
                self.assertEqual(dict(root.attrib), ev)
                for name in ("hae", "ce", "le"):
                    self.assertEqual(root.find("point").get(name), point[name])
                for name in ("lat", "lon"):
                    self.assertAlmostEqual(float(root.find("point").get(name)), float(point[name]), places=7)
                self.assertEqual(root.find("detail/contact").attrib, det["contact"])
                self.assertEqual(root.find("detail/color").attrib, det["color"])
                if ev["type"] == atak.TYPE_PROP:
                    self.assertEqual(root.find("detail/usericon").attrib, det["usericon"])


class XmlSafetyTests(CotChecks):
    def test_hostile_text_is_escaped_and_cleaned(self):
        data = atak.event_xml(uid="atalaia.f.node.4", cot_type=atak.TYPE_PROP, how=atak.HOW_IMAGE, lat=38.7,
                              lon=-9.1, now=1e9, start=1e9, stale=1e9 + 60,
                              detail=atak.marker_detail(HOSTILE, "Atalaia: " + HOSTILE, -1))
        root = self.check_event(data)
        callsign = root.find("detail/contact").get("callsign")
        self.assertEqual(callsign, "</remarks><x a=\"1\">&amp; '\" Caixa")  # controls dropped, kept as text
        self.assertEqual(root.find("detail/remarks").text, "Atalaia: </remarks><x a=\"1\">&amp; '\" Caixa")
        self.assertIsNone(root.find(".//x"))
        self.assertEqual(len(root.find("detail")), 4)
        self.assertNotIn(b"\x01", data)
        self.assertNotIn(b"<x ", data)

    def test_xml_text_limits(self):
        self.assertEqual(atak.xml_text("a" * 100, 48), "a" * 48)
        self.assertEqual(atak.xml_text("\x00\x08\x0b\x0c\x1f", 10), "")
        self.assertEqual(atak.xml_text("emoji \U0001F600 ok", 20), "emoji \U0001F600 ok")

    def test_the_largest_event_fits_one_datagram(self):
        # Texts that grow most when escaped or encoded; check_event asserts DATAGRAM_MAX.
        for ch in ("<", "&", '"', "'", "\U0001F600", "\u20ac", "a"):
            with self.subTest(ch=ch):
                data = atak.event_xml(uid="atalaia." + "f" * 64 + ".node.65534", cot_type=atak.TYPE_PROP,
                                      how=atak.HOW_IMAGE, lat=-89.1234567, lon=-179.1234567, now=1e9, start=1e9,
                                      stale=1e9 + 7200, ce=1e6,
                                      detail=atak.marker_detail(ch * 100, ch * 400, -16777216, 100, "Dark Green"))
                root = self.check_event(data)
                self.assertTrue(root.find("detail/remarks").text.startswith(ch))
        self.assertEqual(atak.xml_text('"' * 10, 48, 30), '"' * 5)

    def test_point_out_of_range_is_refused(self):
        for lat, lon in ((91, 0), (0, 181), (math.nan, 0), (0, math.inf)):
            with self.assertRaises(ValueError):
                atak.event_xml(uid="u", cot_type="b-m-p-s-m", how="h-e", lat=lat, lon=lon, now=0, start=0, stale=1)

    def test_drop_has_stale_before_start(self):
        root = self.check_event(atak.drop_xml("atalaia.f.node.4", atak.TYPE_PROP, 38.7, -9.1, 1e9))
        self.assertLess(root.get("stale"), root.get("start"))

    def test_extraction_parameter(self):
        self.assertEqual(atak.parse_extraction("38.722345,-9.139312"), (38.722345, -9.139312))
        self.assertEqual(atak.parse_extraction(" +38.7 , -9.1 "), (38.7, -9.1))
        for bad in ("38.7", "91,0", "0,-181", "1;2", None, 3, "1,2" + " " * 30):
            self.assertIsNone(atak.parse_extraction(bad))


class GeorefKnownAnswers(unittest.TestCase):
    def test_world_file_worked_example(self):
        # Wikipedia, "World file": falknermap.jgw for an 800 x 600 image is 32.0, 0.0, 0.0, -32.0,
        # 691200.0, 4576000.0 (A, D, B, E, C, F; x' = Ax + By + C, y' = Dx + Ey + F), and the
        # light at x = 171, y = 343 pixels is at "x1 = 696672 meters Easting", "y1 = 4565024
        # meters Northing". Three corners of the image as control points must give that answer.
        A, D, B, E, C, F = 32.0, 0.0, 0.0, -32.0, 691200.0, 4576000.0
        src = [(0.0, 0.0), (799.0, 0.0), (0.0, 599.0), (799.0, 599.0)]
        dst = [(A * x + B * y + C, D * x + E * y + F) for x, y in src]
        m = fit_affine(src[:3], dst[:3])
        east, north = m.apply(171, 343)
        self.assertAlmostEqual(east, 696672.0, places=6)
        self.assertAlmostEqual(north, 4565024.0, places=6)
        m4 = fit_affine(src, dst)  # least squares with four points: the same exact map
        for got, want in zip((m4.a, m4.d, m4.b, m4.e, m4.c, m4.f), (A, D, B, E, C, F)):
            self.assertAlmostEqual(got, want, places=6)

    def test_centre_is_the_middle_of_two_corners(self):
        # The plan's test: an image position of 0.5, 0.5 lands in the middle of the two corners.
        g = Georef([cp(**TL), cp(**BR)])
        self.assertEqual(g.kind, "corners")
        lat, lon = g.to_latlon(0.5, 0.5)
        self.assertAlmostEqual(lat, (TL["lat"] + BR["lat"]) / 2, places=10)
        self.assertAlmostEqual(lon, (TL["lon"] + BR["lon"]) / 2, places=10)
        self.assertAlmostEqual(g.to_latlon(0, 0)[0], TL["lat"], places=10)
        self.assertAlmostEqual(g.to_latlon(1, 1)[1], BR["lon"], places=10)
        corners = g.to_api()["corners"]
        self.assertAlmostEqual(corners["top_right"]["lat"], TL["lat"], places=10)
        self.assertAlmostEqual(corners["top_right"]["lon"], BR["lon"], places=10)

    def test_any_two_points_with_different_x_and_y(self):
        # Points inside the image: linear interpolation, so the corners extrapolate the same line.
        g = Georef([cp(0.25, 0.2, 38.0, -9.0), cp(0.75, 0.6, 37.99, -8.99)])
        lat, lon = g.to_latlon(0.5, 0.4)
        self.assertAlmostEqual(lat, 37.995, places=10)
        self.assertAlmostEqual(lon, -8.995, places=10)
        lat, lon = g.to_latlon(0.0, 0.0)
        self.assertAlmostEqual(lat, 38.005, places=10)
        self.assertAlmostEqual(lon, -9.005, places=10)

    def test_parallelogram_rule_for_a_rotated_image(self):
        # An affine map keeps parallelograms: the fourth corner is P(1,0) + P(0,1) - P(0,0), in the
        # local plane, where the fit is made; at a field's size that is the same in degrees to 1e-7.
        pts = [cp(0, 0, 38.7210, -9.1400), cp(1, 0, 38.7230, -9.1380), cp(0, 1, 38.7195, -9.1385)]
        g = Georef(pts)
        self.assertEqual(g.kind, "affine")
        lat, lon = g.to_latlon(1, 1)
        self.assertAlmostEqual(lat, 38.7230 + 38.7195 - 38.7210, places=7)
        self.assertAlmostEqual(lon, -9.1380 + -9.1385 - -9.1400, places=7)
        mid = g.to_latlon(0.5, 0.5)  # the middle of the diagonal
        self.assertAlmostEqual(mid[0], (38.7230 + 38.7195) / 2, places=7)
        self.assertAlmostEqual(mid[1], (-9.1380 + -9.1385) / 2, places=7)
        self.assertAlmostEqual(g.residual_m, 0.0, places=6)

    def test_four_points_report_their_residual(self):
        pts = [cp(**TL), cp(1, 0, 38.7240, -9.1360), cp(**BR), cp(0, 1, 38.7200, -9.1420)]
        self.assertLess(Georef(pts).residual_m, 0.01)
        off = pts[:3] + [cp(0, 1, 38.7200, -9.1418)]  # one point 17 m off
        g = Georef(off)
        self.assertGreater(g.residual_m, 3.0)
        way_off = pts[:3] + [cp(0, 1, 38.7230, -9.1420)]  # 110 m off: not one flat image
        with self.assertRaises(GeorefError):
            Georef(way_off)

    def test_degenerate_points_are_errors(self):
        cases = {
            "same x": [cp(0.5, 0, 38.72, -9.14), cp(0.5, 1, 38.71, -9.13)],
            "same y": [cp(0, 0.5, 38.72, -9.14), cp(1, 0.5, 38.71, -9.13)],
            "same latitude": [cp(0, 0, 38.72, -9.14), cp(1, 1, 38.72, -9.13)],
            "same longitude": [cp(0, 0, 38.72, -9.14), cp(1, 1, 38.71, -9.14)],
            "same place on the image": [cp(0.5, 0.5, 38.72, -9.14), cp(0.51, 0.5, 38.71, -9.13), cp(0, 1, 38.7, -9.1)],
            "collinear on the image": [cp(0, 0, 38.72, -9.14), cp(0.5, 0.5, 38.71, -9.13), cp(1, 1, 38.70, -9.12)],
            "collinear on the ground": [cp(0, 0, 38.72, -9.14), cp(1, 0, 38.71, -9.13), cp(0, 1, 38.70, -9.12)],
            "mirrored": [cp(0, 0, 38.72, -9.13), cp(1, 1, 38.71, -9.14)],  # east to the left of the image
            "lat and lon swapped": [cp(0, 0, -9.1420, 38.7240), cp(1, 0, -9.1360, 38.7240),
                                    cp(0, 1, -9.1420, 38.7200)],
            "too big": [cp(0, 0, 38.9, -9.4), cp(1, 1, 38.5, -9.0)],
            "across the 180th meridian": [cp(0, 0, 0.0, 179.99), cp(1, 1, -0.01, -179.99)],
        }
        for name, pts in cases.items():
            with self.subTest(name), self.assertRaises(GeorefError):
                Georef(pts)

    def test_bad_input_is_refused(self):
        for raw in (None, [], [TL], [TL] * 9, [TL, {"x": 1, "y": 1, "lat": 38.7}],
                    [TL, {**BR, "x": True}], [TL, {**BR, "lat": "38.7"}], [TL, {**BR, "lat": math.nan}],
                    [TL, {**BR, "x": 1.5}], [TL, {**BR, "lat": 89.0}], [TL, {**BR, "extra": 1}]):
            with self.subTest(raw=raw), self.assertRaises(GeorefError):
                georef.check_points(raw)


class AtakCase(P3Case, CotChecks):
    players = False
    staff = False

    def setUp(self):
        self.udp = Receiver()
        self.tcp = TcpReceiver() if self.staff else None
        self.cfg_overrides = {"atak_enabled": True, "atak_multicast": f"127.0.0.1:{self.udp.port}",
                              "atak_players": self.players,
                              "atak_staff_endpoints": [f"127.0.0.1:{self.tcp.port}"] if self.tcp else []}
        super().setUp()
        self.emitter = self.bundle.atak
        self.emitter._wall = lambda: self.now

    def tearDown(self):
        super().tearDown()
        self.udp.close()
        if self.tcp is not None:
            self.tcp.close()

    def put_image_and_corners(self) -> None:
        r = self.client.put("/api/v1/field/image", headers={**GM, "Content-Type": "image/png"}, content=PNG)
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.put("/api/v1/field/georef", headers=GM, json={"points": [TL, BR]})
        self.assertEqual(r.status_code, 200, r.text)

    def running_game(self, **spec: Any) -> int:
        game = self.new_game(assignments={"4": "zone", "5": "zone"}, **spec)
        r = self.client.post(f"/api/v1/games/{game['id']}/start", headers=GM, json={"force": True})
        self.assertEqual(r.status_code, 200, r.text)
        return game["id"]

    def place(self, gid: int, node: int, x: float, y: float) -> None:
        r = self.client.put(f"/api/v1/games/{gid}/positions/{node}", headers=GM, json={"x": x, "y": y})
        self.assertEqual(r.status_code, 200, r.text)

    def owner(self, node: int, team: int) -> None:
        fc = self.ctrl.fc
        fc.nodes[node].owner_team = team
        self.ctrl._on_node(fc.nodes[node], "state")

    def events_by_uid(self, datagrams: list[bytes]) -> dict[str, ET.Element]:
        return {r.get("uid"): r for r in (self.check_event(d) for d in datagrams)}

    def player(self, gid: int, name: str, team: str, role: str = "player") -> tuple[str, str]:
        me = self.check_in(gid, name=name)
        self.svc.rate.allow = lambda key: True
        self.gm_patch(gid, me["player_id"], team=team, role=role)
        tok = self.client.post("/api/v1/checkin/token", headers=bearer(me["token"])).json()["token"]
        r = self.client.post("/api/v1/positions", headers=bearer(tok),
                             json={"lat": 38.7221, "lon": -9.1391, "accuracy_m": 6.0, "source": "gps", "t": 1})
        self.assertEqual(r.status_code, 200, r.text)
        return me["player_id"], tok


class EmitterTests(AtakCase):
    def test_props_on_the_georeferenced_image(self):
        self.put_image_and_corners()
        gid = self.running_game()
        self.place(gid, 4, 0.5, 0.5)
        self.place(gid, 5, 0.0, 1.0)
        self.udp.drain(0.05)
        sent = self.emitter.cycle(full=True)
        self.assertEqual(sent["udp"], 2)
        got = self.events_by_uid(self.udp.drain())
        self.assertEqual(set(got), {"atalaia.field.node.4", "atalaia.field.node.5"})
        mid = got["atalaia.field.node.4"]
        self.assertEqual((mid.get("type"), mid.get("how")), ("b-m-p-s-m", "h-e"))
        self.assertAlmostEqual(float(mid.find("point").get("lat")), (TL["lat"] + BR["lat"]) / 2, places=6)
        self.assertAlmostEqual(float(mid.find("point").get("lon")), (TL["lon"] + BR["lon"]) / 2, places=6)
        corner = got["atalaia.field.node.5"].find("point")
        self.assertAlmostEqual(float(corner.get("lat")), BR["lat"], places=6)
        self.assertAlmostEqual(float(corner.get("lon")), TL["lon"], places=6)
        self.assertEqual(mid.find("detail/color").get("argb"), "-1")  # nobody owns it yet
        self.assertIsNone(mid.find("detail/__group"))                 # so no ATAK team
        self.assertEqual(mid.get("start"), mid.get("time"))
        self.assertEqual(mid.get("stale"), atak.cot_time(self.now + 60))  # 2 x interval_s

    def test_the_active_box_says_so_in_its_remarks(self):
        """Decision PD-MODE-16: Progressive Domination's active box shows "active" in ATAK."""
        self.put_image_and_corners()
        gid = self.running_game()
        self.place(gid, 4, 0.5, 0.5)
        self.place(gid, 5, 0.2, 0.2)
        self.emitter.cycle(full=True)
        got = self.events_by_uid(self.udp.drain())
        name4 = got["atalaia.field.node.4"].find("detail/contact").get("callsign")
        self.assertNotIn("active", got["atalaia.field.node.4"].find("detail/remarks").text)

        def say(kind: str, zone: str) -> None:
            self.emitter.on_controller_message({"type": "event", "event": {
                "type": kind, "node": 0, "data": {"zone": zone}}})

        say("progressive.activated", name4)
        self.assertEqual(self.emitter.cycle(full=False)["udp"], 2)  # the old and the new, so all
        got = self.events_by_uid(self.udp.drain())
        self.assertEqual(got["atalaia.field.node.4"].find("detail/remarks").text, "Atalaia: -, active")
        self.assertEqual(got["atalaia.field.node.5"].find("detail/remarks").text, "Atalaia: -")
        say("progressive.completed", name4)
        self.emitter.cycle(full=False)
        got = self.events_by_uid(self.udp.drain())
        self.assertEqual(got["atalaia.field.node.4"].find("detail/remarks").text, "Atalaia: -")
        say("progressive.activated", name4)
        self.emitter.on_controller_message({"type": "game", "game": {"id": gid, "state": "ended"}})
        self.emitter.cycle(full=False)
        self.udp.drain()
        self.assertIsNone(self.emitter._active)  # a game that ended forgets it

    def test_the_grid_cell_is_in_a_marker_remarks(self):
        """PKE-2: with a field grid, a box and a map feature on the plan say their cell ("grid C3") in ATAK;
        without one, nothing changes; changing the grid sends everything again."""
        self.put_image_and_corners()
        gid = self.running_game()
        self.place(gid, 4, 0.5, 0.5)
        self.place(gid, 5, 0.0, 1.0)
        f = self.client.post("/api/v1/field/features", headers=GM, json={
            "type": "first_aid", "shape": "point", "x": 0.9, "y": 0.1, "label": "Posto", "note": "Kit verde"})
        self.assertEqual(f.status_code, 201, f.text)
        self.emitter.cycle(full=True)
        got = self.events_by_uid(self.udp.drain())
        self.assertEqual(got["atalaia.field.node.4"].find("detail/remarks").text, "Atalaia: -")  # no grid yet
        r = self.client.put("/api/v1/field/grid", headers=GM, json={"enabled": True, "rows": 4, "cols": 4})
        self.assertEqual(r.status_code, 200, r.text)
        self.emitter.on_controller_message({"type": "field_grid", "level": 0, "grid": r.json()["grid"]})
        self.assertGreaterEqual(self.emitter.cycle(full=False)["udp"], 3)  # the grid asked for everything again
        got = self.events_by_uid(self.udp.drain())
        self.assertEqual(got["atalaia.field.node.4"].find("detail/remarks").text, "Atalaia: -, grid C3")
        self.assertEqual(got["atalaia.field.node.5"].find("detail/remarks").text, "Atalaia: -, grid D1")  # the bottom edge
        feature = got[f"atalaia.field.feature.{f.json()['id']}"]
        self.assertEqual(feature.find("detail/remarks").text, "Atalaia: First aid, grid A4. Kit verde")

    def test_node_remarks_with_a_grid_cell(self):
        self.assertEqual(atak.node_remarks("red", None, False, "C4"), "Atalaia: red, grid C4")
        self.assertEqual(atak.node_remarks("", "Cave", True, "AB12"), "Atalaia: -, active, Cave, grid AB12")
        self.assertEqual(atak.node_remarks("red", None, False, None), "Atalaia: red")

    def test_node_remarks(self):
        self.assertEqual(atak.node_remarks(""), "Atalaia: -")
        self.assertEqual(atak.node_remarks("red", None, True), "Atalaia: red, active")
        self.assertEqual(atak.node_remarks("", "Cave", True), "Atalaia: -, active, Cave")

    def test_owner_colour_and_a_capture_sent_at_once(self):
        self.put_image_and_corners()
        gid = self.running_game()
        self.place(gid, 4, 0.5, 0.5)
        self.place(gid, 5, 0.2, 0.2)
        self.emitter.cycle(full=True)
        self.udp.drain()
        self.ctrl._on_event({"node": 4, "seq": 1, "t": 1000, "type": "zone.captured", "team": "blue", "squad": 0,
                             "prio": "normal", "data": {"zone": "alpha"}, "epoch": 1, "pkt_seq": 1})
        sent = self.emitter.cycle(full=False)
        self.assertEqual(sent["udp"], 1)  # only the captured box, not the whole picture
        ev = self.events_by_uid(self.udp.drain())["atalaia.field.node.4"]
        self.assertEqual(int(ev.find("detail/color").get("argb")), atak.team_colour("blue", ["red", "blue"]))
        self.assertIn("blue", ev.find("detail/remarks").text)
        # The plan's test: __group from the owner's colour (decision M9-5), next to <color>.
        self.assertEqual(ev.find("detail/__group").attrib, {"name": "Blue", "role": "Team Member"})
        # The box's STATE with the same owner sends nothing more; a new owner does.
        self.owner(4, 2)
        self.assertEqual(self.emitter.cycle(full=False)["udp"], 0)
        self.owner(4, 1)
        self.assertEqual(self.emitter.cycle(full=False)["udp"], 1)
        ev = self.events_by_uid(self.udp.drain())["atalaia.field.node.4"]
        self.assertEqual(int(ev.find("detail/color").get("argb")), atak.team_colour("red", ["red", "blue"]))
        self.assertEqual(ev.find("detail/__group").get("name"), "Red")

    def test_the_worker_sends_a_capture_without_waiting_for_the_interval(self):
        self.put_image_and_corners()
        gid = self.running_game()
        self.place(gid, 4, 0.5, 0.5)
        self.emitter.start()
        try:
            self.assertTrue(wait_for(lambda: self.emitter.stats["udp_events"] >= 1, 3))
            self.udp.drain()
            self.ctrl._on_event({"node": 4, "seq": 1, "t": 1000, "type": "zone.captured", "team": "red", "squad": 0,
                                 "prio": "normal", "data": {"zone": "alpha"}, "epoch": 1, "pkt_seq": 1})
            got = self.udp.drain(2.0)  # interval_s is 30 s: this is the capture
        finally:
            self.emitter.stop()
        ev = self.events_by_uid(got)["atalaia.field.node.4"]
        self.assertEqual(int(ev.find("detail/color").get("argb")), atak.team_colour("red", []))

    def test_stop_closes_the_socket(self):
        self.assertIsNone(self.emitter.udp)  # nothing is opened before the first send
        self.put_image_and_corners()
        gid = self.running_game()
        self.place(gid, 4, 0.5, 0.5)
        self.emitter.cycle(full=True)
        sock = self.emitter.udp.sock
        self.assertNotEqual(sock.fileno(), -1)
        self.emitter.stop()
        self.assertEqual(sock.fileno(), -1)
        self.assertIsNone(self.emitter.udp)
        self.emitter.stop()  # again: nothing to do

    def test_no_georeference_no_markers(self):
        gid = self.running_game()
        self.place(gid, 4, 0.5, 0.5)
        self.assertEqual(self.emitter.cycle(full=True)["udp"], 0)
        self.assertTrue(self.emitter.status()["no_georef"])
        self.put_image_and_corners()
        self.assertEqual(self.emitter.cycle(full=False)["udp"], 1)
        # Deleting the georeference drops what ATAK shows.
        self.assertTrue(self.client.delete("/api/v1/field/georef", headers=GM).json()["deleted"])
        self.udp.drain()
        self.emitter.cycle(full=False)
        (drop,) = self.udp.drain()
        root = self.check_event(drop)
        self.assertLess(root.get("stale"), root.get("start"))

    def test_hostile_node_and_team_names(self):
        self.put_image_and_corners()
        gid = self.running_game()
        self.place(gid, 4, 0.5, 0.5)
        self.ctrl.fc.nodes[4].name = HOSTILE_NODE
        self.ctrl.game["team_info"] = {"red": {"display_name": HOSTILE}}
        self.owner(4, 1)
        self.emitter.cycle(full=True)
        ev = self.events_by_uid(self.udp.drain())["atalaia.field.node.4"]
        self.assertEqual(ev.find("detail/contact").get("callsign"), "</remarks><x a=\"1\">&amp; '\" Caixa")
        self.assertIn("</remarks><x", ev.find("detail/remarks").text)
        self.assertIsNone(ev.find(".//x"))

    def test_game_end_drops_every_marker_and_stops(self):
        self.put_image_and_corners()
        gid = self.running_game()
        self.place(gid, 4, 0.5, 0.5)
        self.emitter.cycle(full=True)
        self.udp.drain()
        self.client.post(f"/api/v1/games/{gid}/end", headers=GM)
        self.emitter.cycle(full=False)
        got = self.events_by_uid(self.udp.drain())
        self.assertEqual(set(got), {"atalaia.field.node.4"})
        self.assertLess(got["atalaia.field.node.4"].get("stale"), got["atalaia.field.node.4"].get("start"))
        self.assertEqual(self.emitter.cycle(full=True)["udp"], 0)

    def test_extraction_zone(self):
        self.put_image_and_corners()
        game = self.new_game(mode_id="org.atalaia.vip_payload", assignments={"4": "checkpoint"},
                             params={"extraction": "38.7215,-9.1390", "radius_m": 40, "vip_team": "blue"})
        self.client.post(f"/api/v1/games/{game['id']}/start", headers=GM, json={"force": True})
        self.emitter.cycle(full=True)
        got = self.events_by_uid(self.udp.drain())
        ev = got[f"atalaia.field.game.{game['id']}.extraction"]
        self.assertEqual((ev.get("type"), ev.get("how")), ("b-m-p-s-m", "h-p"))
        self.assertEqual(ev.find("point").get("ce"), "40.0")  # the zone's radius as ce (cot.json point)
        self.assertEqual(float(ev.find("point").get("lat")), 38.7215)
        self.assertEqual(ev.find("detail/__group").get("name"), "Blue")

    def test_status_endpoint(self):
        r = self.client.get("/api/v1/atak", headers=READ)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["enabled"])
        self.assertEqual(r.json()["multicast"], f"127.0.0.1:{self.udp.port}")


class PlayerTests(AtakCase):
    players = True
    staff = True

    def test_players_only_to_staff_endpoints_never_multicast(self):
        self.put_image_and_corners()
        gid = self.running_game()
        self.place(gid, 4, 0.5, 0.5)
        red, _ = self.player(gid, "Falcão", "red")
        vip, _ = self.player(gid, "Mocho", "blue", role="vip")
        self.emitter.cycle(full=True)
        udp = self.events_by_uid(self.udp.drain())
        self.assertEqual(set(udp), {"atalaia.field.node.4"})
        for root in udp.values():
            self.assertNotEqual(root.get("type"), atak.TYPE_PLAYER)
        self.assertTrue(wait_for(lambda: len(self.tcp.connections) == 1, 3))
        tcp = self.events_by_uid(split_stream(self.tcp.connections[0]))
        self.assertEqual(set(tcp), {"atalaia.field.node.4", f"atalaia.field.player.{red}",
                                    f"atalaia.field.player.{vip}"})
        p = tcp[f"atalaia.field.player.{red}"]
        self.assertEqual((p.get("type"), p.get("how")), ("a-f-G-U-C", "m-g"))
        self.assertEqual(p.find("detail/__group").attrib, {"name": "Red", "role": "Team Member"})
        self.assertEqual(p.find("point").get("ce"), "6.0")
        self.assertEqual(p.find("detail/contact").get("callsign"), red)  # never the name (decision M9-6)
        raw = b"".join(self.tcp.connections)
        self.assertNotIn("Falcão".encode(), raw)
        self.assertNotIn(b"Mocho", raw)
        self.assertEqual(tcp[f"atalaia.field.player.{vip}"].find("detail/contact").get("callsign"), f"{vip} VIP")
        # Each event on the stream starts with its XML declaration and a newline (cot.json transport).
        self.assertTrue(self.tcp.connections[0].startswith(b"<?xml "))
        self.assertEqual(self.tcp.connections[0].count(b"?>\n<event "), 3)


class FakeRelay:
    """The site server's stream as the emitter sees it (remote_gm.RemoteGm): push_cot and atak_relay."""

    def __init__(self) -> None:
        self.events: list[bytes] = []
        self.atak_relay = True
        self.on_relay_open: Optional[Any] = None

    def push_cot(self, events: list[bytes]) -> int:
        self.events += events
        return len(events)


class RemoteRelayTests(AtakCase):
    """[atak] remote (Phase 4 follow-up FU5): the same picture to the site server's relay, positions only with
    remote_players, every event in the shared form the site server checks (sync_format.cot_event)."""

    players = True  # [atak] players, for staff endpoints: there are none here, so it sends no position anywhere

    def relay(self, players: bool) -> FakeRelay:
        self.cfg.atak_remote, self.cfg.atak_remote_players = True, players
        fake = FakeRelay()
        self.emitter.remote = fake
        return fake

    def shared(self, events: list[bytes]) -> dict[str, dict[str, Any]]:
        out = {}
        for data in events:
            ev = sync_format.cot_event(data.decode("utf-8"))
            self.assertEqual(ev["xml"].encode("utf-8"), data)  # the site server relays these very bytes
            out[ev["uid"]] = ev
        return out

    def test_props_go_to_the_relay_and_positions_only_with_remote_players(self):
        self.put_image_and_corners()
        gid = self.running_game()
        self.place(gid, 4, 0.5, 0.5)
        self.ctrl.fc.nodes[4].name = HOSTILE_NODE
        red, _ = self.player(gid, "Falcão", "red")
        fake = self.relay(players=False)
        sent = self.emitter.cycle(full=True)
        self.assertEqual(sent["remote"], 1)
        got = self.shared(fake.events)
        self.assertEqual(list(got), ["atalaia.field.node.4"])
        self.assertTrue(got["atalaia.field.node.4"]["map"])
        self.assertEqual(set(self.events_by_uid(self.udp.drain())), {"atalaia.field.node.4"})  # never a player
        fake = self.relay(players=True)
        self.emitter.cycle(full=True)
        got = self.shared(fake.events)
        self.assertEqual(set(got), {"atalaia.field.node.4", f"atalaia.field.player.{red}"})
        self.assertFalse(got[f"atalaia.field.player.{red}"]["map"])  # the site server sends it only where allowed
        self.assertNotIn("Falcão".encode(), b"".join(fake.events))
        self.assertEqual(set(self.events_by_uid(self.udp.drain())), {"atalaia.field.node.4"})
        # The game ends: every marker the relay got is dropped there too, the player's included.
        fake.events.clear()
        self.client.post(f"/api/v1/games/{gid}/end", headers=GM)
        self.emitter.cycle(full=False)
        drops = self.shared(fake.events)
        self.assertEqual(set(drops), {"atalaia.field.node.4", f"atalaia.field.player.{red}"})
        self.assertTrue(all(ev["stale"] < ev["start"] for ev in drops.values()))
        status = self.emitter.status()
        self.assertEqual((status["remote"], status["remote_players"], status["remote_relay"]), (True, True, True))

    def test_extraction_zone_and_a_new_socket_get_everything_again(self):
        self.put_image_and_corners()
        game = self.new_game(mode_id="org.atalaia.vip_payload", assignments={"4": "checkpoint"},
                             params={"extraction": "38.7215,-9.1390", "radius_m": 40, "vip_team": "blue"})
        self.client.post(f"/api/v1/games/{game['id']}/start", headers=GM, json={"force": True})
        self.place(game["id"], 4, 0.2, 0.3)
        fake = self.relay(players=False)
        self.emitter.cycle(full=True)
        self.assertEqual(set(self.shared(fake.events)), {"atalaia.field.node.4",
                                                         f"atalaia.field.game.{game['id']}.extraction"})
        fake.events.clear()
        self.assertEqual(self.emitter.cycle(full=False)["remote"], 0)
        self.emitter.resend_all()  # what the stream does when the site server takes a new socket
        self.assertEqual(self.emitter.cycle(full=False)["remote"], 2)

    def test_off_by_default(self):
        self.assertFalse(self.cfg.atak_remote)
        self.assertIsNone(self.emitter.remote)
        self.put_image_and_corners()
        gid = self.running_game()
        self.place(gid, 4, 0.5, 0.5)
        self.assertEqual(self.emitter.cycle(full=True)["remote"], 0)
        self.assertFalse(self.emitter.status()["remote"])


class PlayersOffTests(AtakCase):
    players = False
    staff = True

    def test_staff_get_props_but_no_players_without_players_true(self):
        self.put_image_and_corners()
        gid = self.running_game()
        self.place(gid, 4, 0.5, 0.5)
        me = self.check_in(gid, name="Falcão")
        self.svc.rate.allow = lambda key: True
        self.gm_patch(gid, me["player_id"], team="red")
        tok = self.client.post("/api/v1/checkin/token", headers=bearer(me["token"])).json()["token"]
        self.client.post("/api/v1/positions", headers=bearer(tok), json={"lat": 38.72, "lon": -9.14, "source": "gps"})
        self.emitter.cycle(full=True)
        self.assertTrue(wait_for(lambda: len(self.tcp.connections) == 1, 3))
        types = {r.get("type") for r in (self.check_event(e) for e in split_stream(self.tcp.connections[0]))}
        self.assertEqual(types, {atak.TYPE_PROP})


class DisabledTests(P3Case):
    def test_nothing_is_sent_while_disabled(self):
        udp = Receiver()
        try:
            self.cfg.atak_multicast = f"127.0.0.1:{udp.port}"  # enabled stays false (the default)
            self.restart()
            self.assertIsNone(self.bundle.atak)
            self.assertIsNone(self.ctrl.atak)
            self.client.put("/api/v1/field/image", headers={**GM, "Content-Type": "image/png"}, content=PNG)
            self.client.put("/api/v1/field/georef", headers=GM, json={"points": [TL, BR]})
            game = self.new_game()
            self.client.post(f"/api/v1/games/{game['id']}/start", headers=GM, json={"force": True})
            self.client.put(f"/api/v1/games/{game['id']}/positions/4", headers=GM, json={"x": 0.5, "y": 0.5})
            with self.client:  # the app's lifespan runs: every service starts, ATAK has none
                self.assertEqual(udp.drain(0.5), [])
            self.assertEqual(self.client.get("/api/v1/atak", headers=READ).json(), {"enabled": False})
        finally:
            udp.close()


class GeorefApiTests(P3Case):
    def test_georef_endpoints(self):
        c = self.client
        self.assertEqual(c.get("/api/v1/field/georef", headers=READ).json(), {"georef": None})
        r = c.put("/api/v1/field/georef", headers=GM, json={"points": [TL, BR]})
        self.assertEqual(r.status_code, 409, r.text)  # no image yet
        c.put("/api/v1/field/image", headers={**GM, "Content-Type": "image/png"}, content=PNG)
        self.assertEqual(c.put("/api/v1/field/georef", headers=READ, json={"points": [TL, BR]}).status_code, 403)
        r = c.put("/api/v1/field/georef", headers=GM, json={"points": [TL, {**BR, "x": 0.0}]})
        self.assertEqual(r.status_code, 400)
        self.assertIn("opposite corners", r.json()["detail"])
        self.assertEqual(c.put("/api/v1/field/georef", headers=GM, json={"points": [TL, BR], "x": 1}).status_code, 400)
        r = c.put("/api/v1/field/georef", headers=GM, json={"points": [TL, BR]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["georef"]["kind"], "corners")
        got = c.get("/api/v1/field/georef", headers=READ).json()["georef"]
        self.assertEqual(got["points"], [TL, BR])
        self.assertAlmostEqual(got["corners"]["bottom_left"]["lat"], BR["lat"], places=9)
        # A new image clears the points: they were places on the old one (decision M9-4).
        r = c.put("/api/v1/field/image", headers={**GM, "Content-Type": "image/png"}, content=PNG + b"x")
        self.assertTrue(r.json()["georef_cleared"])
        self.assertEqual(c.get("/api/v1/field/georef", headers=READ).json(), {"georef": None})
        c.put("/api/v1/field/georef", headers=GM, json={"points": [TL, BR]})
        self.assertTrue(c.delete("/api/v1/field/image", headers=GM).json()["deleted"])
        self.assertEqual(c.get("/api/v1/field/georef", headers=READ).json(), {"georef": None})
        self.assertFalse(c.delete("/api/v1/field/georef", headers=GM).json()["deleted"])

    def test_stream_tells_the_console(self):
        self.client.put("/api/v1/field/image", headers={**GM, "Content-Type": "image/png"}, content=PNG)
        with self.client.websocket_connect("/api/v1/stream?token=gm-secret") as ws:
            ws.receive_json()
            self.client.put("/api/v1/field/georef", headers=GM, json={"points": [TL, BR]})
            for _ in range(10):
                msg = ws.receive_json()
                if msg["type"] == "field_georef":
                    break
            self.assertEqual(msg["georef"]["kind"], "corners")


class ConfigTests(unittest.TestCase):
    def test_defaults_and_environment(self):
        cfg = load_config(None, env={})
        self.assertFalse(cfg.atak_enabled)
        self.assertEqual(cfg.atak_multicast, "239.2.3.1:6969")
        self.assertFalse(cfg.atak_players)
        cfg = load_config(None, env={"ATALAIA_ATAK_ENABLED": "1",
                                     "ATALAIA_ATAK_STAFF_ENDPOINTS": "10.42.0.5:4242, 10.42.0.6,[fd00::7]:4243",
                                     "ATALAIA_ATAK_PLAYERS": "true", "ATALAIA_ATAK_INTERVAL_S": "10"})
        self.assertEqual(cfg.atak_staff_endpoints, ["10.42.0.5:4242", "10.42.0.6", "[fd00::7]:4243"])
        self.assertEqual([atak.parse_endpoint(e, 4242) for e in cfg.atak_staff_endpoints],
                         [("10.42.0.5", 4242), ("10.42.0.6", 4242), ("fd00::7", 4243)])
        self.assertTrue(cfg.atak_enabled and cfg.atak_players)

    def test_refused(self):
        for env in ({"ATALAIA_ATAK_MULTICAST": "239.2.3.1"}, {"ATALAIA_ATAK_MULTICAST": "0.0.0.0:6969"},
                    {"ATALAIA_ATAK_MULTICAST": "atak.local:6969"}, {"ATALAIA_ATAK_MULTICAST": "239.2.3.1:70000"},
                    {"ATALAIA_ATAK_MULTICAST": "[ff02::1]:6969"}, {"ATALAIA_ATAK_INTERVAL_S": "0.5"},
                    {"ATALAIA_ATAK_STAFF_ENDPOINTS": "a b:1"},
                    {"ATALAIA_ATAK_STAFF_ENDPOINTS": ",".join(f"10.0.0.{i}" for i in range(9))}):
            with self.subTest(env=env), self.assertRaises(ConfigError):
                load_config(None, env=env)
        cfg = config("/tmp", atak_multicast="")  # no UDP at all is allowed
        self.assertEqual(cfg.atak_multicast, "")


class MulticastLoopbackTest(unittest.TestCase):
    def test_a_member_of_the_group_on_this_host_gets_it(self):
        group, port = "239.2.3.1", free_port(socket.SOCK_DGRAM)
        rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            rx.bind(("", port))
            try:
                rx.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                              struct.pack("4s4s", socket.inet_aton(group), socket.inet_aton("127.0.0.1")))
            except OSError as exc:
                self.skipTest(f"no multicast on the loopback here: {exc}")
            rx.settimeout(2)
            sender = atak.UdpSender(f"{group}:{port}")
            try:
                ttl = sender.sock.getsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL)
                self.assertEqual(ttl, 1)  # the field's own network only
                sender.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton("127.0.0.1"))
                data = atak.drop_xml("atalaia.f.node.1", atak.TYPE_PROP, 38.7, -9.1, 1e9)
                sender.send([data])
                try:
                    got: Optional[bytes] = rx.recv(65535)
                except socket.timeout:
                    self.skipTest("the loopback does not deliver multicast here")
                self.assertEqual(got, data)
            finally:
                sender.close()
        finally:
            rx.close()



class StaffTlsTests(unittest.TestCase):
    """The staff feed over TLS (FLD-5): the CA of the devices' input is the trust anchor."""

    def setUp(self):
        import tempfile  # noqa: PLC0415

        from atalaia_controller import tls  # noqa: PLC0415

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ours = tls.ensure(Path(self.tmp.name) / "a", ["127.0.0.1"])
        self.other = tls.ensure(Path(self.tmp.name) / "b", ["127.0.0.1"])

    def device(self, files, got):
        """A staff device's TLS input on a free port: collects what it is sent."""
        import ssl  # noqa: PLC0415

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(files.server_cert), str(files.server_key))
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(2)
        srv.settimeout(5)
        self.addCleanup(srv.close)

        def run():
            try:
                conn, _ = srv.accept()
                with ctx.wrap_socket(conn, server_side=True) as s:
                    got.append(s.recv(4096))
            except (OSError, ssl.SSLError):
                got.append(b"handshake failed")
        t = threading.Thread(target=run, daemon=True)
        t.start()
        self.addCleanup(t.join, 5)
        return srv.getsockname()[1]

    def cfg(self, ca, **kw):
        return config(self.tmp.name, atak_enabled=True, atak_staff_endpoints=["127.0.0.1"], atak_staff_tls=True,
                      atak_staff_tls_ca=str(ca), **kw)

    def test_events_arrive_over_tls_from_a_device_with_the_pinned_ca(self):
        got: list[bytes] = []
        port = self.device(self.ours, got)
        cfg = self.cfg(self.ours.dir / "ca.pem")
        sender = atak.TcpSender([f"127.0.0.1:{port}"], context=atak.staff_tls_context(cfg))
        self.assertEqual(sender.send([b"<event/>\n"]), (1, []))
        self.assertTrue(wait_for(lambda: got))
        self.assertEqual(got[0], b"<event/>\n")

    def test_a_device_with_another_ca_gets_nothing(self):
        got: list[bytes] = []
        port = self.device(self.other, got)
        cfg = self.cfg(self.ours.dir / "ca.pem")
        sender = atak.TcpSender([f"127.0.0.1:{port}"], context=atak.staff_tls_context(cfg))
        sent, errors = sender.send([b"<event/>\n"])
        self.assertEqual(sent, 0)
        self.assertEqual(len(errors), 1)
        self.assertTrue(wait_for(lambda: got))
        self.assertNotEqual(got[0], b"<event/>\n")

    def test_the_default_port_is_atak_ssl_input(self):
        sender = atak.TcpSender(["10.42.0.5"], context=atak.staff_tls_context(self.cfg(self.ours.dir / "ca.pem")))
        self.assertEqual(sender.endpoints, [("10.42.0.5", 8089)])
        self.assertEqual(atak.TcpSender(["10.42.0.5"]).endpoints, [("10.42.0.5", 4242)])

    def test_config_refuses_tls_without_a_ca_or_a_missing_file(self):
        with self.assertRaises(ConfigError):
            config(self.tmp.name, atak_enabled=True, atak_staff_endpoints=["10.42.0.5"], atak_staff_tls=True)
        with self.assertRaises(ConfigError):
            self.cfg(Path(self.tmp.name) / "nope.pem")
        with self.assertRaises(ConfigError):
            config(self.tmp.name, atak_enabled=True, atak_staff_tls_ca="x.pem")  # a CA without staff_tls
        with self.assertRaises(ConfigError):
            self.cfg(self.ours.dir / "ca.pem", atak_staff_tls_cert="c.pem")  # a certificate without its key


if __name__ == "__main__":
    unittest.main()
