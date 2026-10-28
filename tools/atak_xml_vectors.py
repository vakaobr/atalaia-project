#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes protocol/vectors/atak_xml.json, the ATAK emitter's known answers.

    python3 tools/atak_xml_vectors.py           write the file
    python3 tools/atak_xml_vectors.py --check   fail if it is stale

Every answer is what the Pi controller's emitter (controller/atalaia_controller/atak.py) gives for
the inputs, so the Android field controller's port (app/lib/controller/controller_atak.dart, PE24
slice S7) is checked byte for byte against it (app/test/controller/controller_atak_test.dart): the
text cleaning (xml_text), the time and number formats, the colours and ATAK teams, the extraction
parameter, the endpoints and the [atak] settings, and whole events as ElementTree serialises them
(attribute order, escaping, the "<x />" form), tricky inputs included: quotes, ampersands, control
characters, lone surrogates, long and Unicode names, every map feature kind. The facts about CoT
itself are protocol/vectors/cot.json's, copied from their sources; this file only pins the two
implementations to each other. Needs Python 3.12 (CI's; the controller needs 3.11's tomllib, and
3.12's sum() of floats may differ from 3.11's in the last bit of a feature's lat and lon) and nothing
beyond the standard library.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "controller"))
sys.path.insert(0, str(REPO / "simulator"))

from atalaia_controller import atak  # noqa: E402
from atalaia_controller import georef as georefmod  # noqa: E402

OUT = REPO / "protocol" / "vectors" / "atak_xml.json"

HOSTILE = "</remarks><x a=\"1\">&amp; '\"\x01\x1b\ud800￾\n\tCaixa"
# Python's str.split() whitespace that survives the XML 1.0 filter.
PY_SPACES = "\t\n\r \x85\xa0            " \
            "    　"
TL = {"x": 0.0, "y": 0.0, "lat": 38.7240, "lon": -9.1420}
BR = {"x": 1.0, "y": 1.0, "lat": 38.7200, "lon": -9.1360}
ROTATED = [{"x": 0, "y": 0, "lat": 38.7210, "lon": -9.1400}, {"x": 1, "y": 0, "lat": 38.7230, "lon": -9.1380},
           {"x": 0, "y": 1, "lat": 38.7195, "lon": -9.1385}]


def xml_text_cases() -> list[dict[str, Any]]:
    inputs: list[tuple[str, int, Optional[int]]] = [
        ("a" * 100, 48, None),
        ("\x00\x08\x0b\x0c\x1f", 10, None),
        ("emoji \U0001F600 ok", 20, None),
        (HOSTILE, 48, 160),
        ("Atalaia: " + HOSTILE, 160, 320),
        ('"' * 10, 48, 30),
        ("'" * 10, 48, 30),
        ("&" * 60, 48, 160),
        ("<>" * 40, 48, 160),
        ("\U0001F600" * 100, 48, 160),
        ("€" * 100, 160, 320),
        ("a b " * 50, 160, 192),
        ("ab" + " " * 10 + "&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&", 48, 30),
        ("x" * 95 + " &", 160, 96),
        ("  lead  and   trail  ", 48, None),
        ("tab\tnew\nline\rcr\x0bvt\x0cff\x1cfs", 48, None),
        ("sp" + PY_SPACES + "aces", 48, None),
        ("zero​width᠎mongolian﻿bom", 48, None),
        ("lone \ud800 high \udfff low 😀 pair", 48, None),
        ("bad ￾￿  private \U0010ffff top", 48, None),
        ("\x7f del \x80 c1 \x9f", 48, None),
        ("Falcão Caçador Équipa", 48, 160),
        ("الفريق 紅隊 дружина", 48, 96),
        ("", 48, 160),
        ("   ", 48, 160),
        ("abc", 0, None),
        ("abcdef", 3, 2),
        ("a" * 47 + "\U0001F600" + "b", 48, 160),
    ]
    return [{"value": v, "limit": lim, "max_bytes": mb, "out": atak.xml_text(v, lim, mb)} for v, lim, mb in inputs]


def remarks_cases() -> list[list[Any]]:
    """node_remarks(owner_display, level_label, active) -> text (decision PD-MODE-16)."""
    args = [("", None, False), ("Lobos (blue)", None, False), ("", None, True), ("red", None, True),
            ("red", "Cave", False), ("", "Ground floor", True), ("red", "Cave", True)]
    return [[a[0], a[1], a[2], atak.node_remarks(*a)] for a in args]


def remarks_grid_cases() -> list[list[Any]]:
    """node_remarks(owner_display, level_label, active, grid_cell) -> text (PKE-2: the grid cell, "grid C4")."""
    args = [("red", None, False, "C4"), ("", "Cave", True, "AB12"), ("red", None, False, None),
            ("", None, False, ""), ("Lobos (blue)", "Ground floor", False, "A1")]
    return [[a[0], a[1], a[2], a[3], atak.node_remarks(*a)] for a in args]


def number_cases() -> dict[str, Any]:
    times = [0.0, 1e9, 1e9 + 0.0005, 1e9 + 0.0015, 1e9 + 0.9995, 1e9 + 0.9999996, 1608148774.91,
             1608148774.913, 1609620003.841, 1798761599.999, 1700000000.123456, 951782400.5, 4102444800.0,
             1e9 - 1.0, 1e9 + 59.999]
    degs = [0.0, -0.0, 38.7, -9.1, 38.72200005, 38.00390625, -9.00390625, 0.00390625, -1e-9, 89.99999995,
            -179.99999995, 180.0, -90.0, 38.85606343062312, -77.0563755018233, 1e-7, 5e-8, 1.5e-7, 2.5e-7]
    metres = [None, 0.0, -0.0, -5.0, 6.0, 40.0, 25.0, 0.05, 0.15, 0.25, 0.35, 2.25, 1e6, 123456789.95,
              9999999.0, 1e-9]
    return {
        "cot_time": [[t, atak.cot_time(t)] for t in times],
        "deg": [[v, atak._deg(v)] for v in degs],
        "metres": [[v, atak._metres(v)] for v in metres],
        "fixed0": [[v, f"{v:.0f}"] for v in (0.5, 1.5, 2.5, 25.0, 40.0, 39.5, 40.5, 1999.5, 0.49999999999999994)],
    }


def colour_cases() -> dict[str, Any]:
    teams = ["red", "blue", "wolves", "bears"]
    names = [None, "", "red", "Red", "RED", "vermelha", "Vermelho", "azul", "blue", "green", "verde", "yellow",
             "amarela", "orange", "laranja", "purple", "roxa", "black", "preto", "white", "branca", "wolves",
             "bears", "lions", "eagles!", "dark_green", "dark-green", "Dark Green", "darkgreen", "dark blue",
             "magenta", "maroon", "cyan", "teal", "brown", "Azul", "blacK", "Équipa", "\U0001F600x"]
    return {
        "teams": teams,
        "team_colour": [[n, atak.team_colour(n, teams)] for n in names],
        "atak_team": [[n, atak.atak_team(n)] for n in names],
        "argb_of": [[rgb, a, atak.argb_of(rgb, a)] for rgb, a in ((0xD7263D, 0xFF), (0xD7263D, 0x60),
                                                                   (0xFFFFFF, 0x00), (0x14B8A6, 0x7F),
                                                                   (0x14B8A6, 0x80), (0x1FFFFFF, 0x1FF), (0, 0))],
        "kml_colour": [[v, atak.kml_colour(v)] for v in (-1, -65536, -16777216, 0, 0x60D7263D, -2681795,
                                                           atak.argb_of(0x14B8A6, 0x60))],
        "feature_colour": [[f, atak.feature_colour(f, teams)] for f in (
            {"type": "safe_zone"}, {"type": "respawn", "team": "blue"}, {"type": "hq", "team": "wolves"},
            {"type": "parking"}, {"type": "first_aid"}, {"type": "objective", "team": None},
            {"type": "other"}, {"type": "boundary"}, {"type": "nonsense"}, {"type": "hq", "team": "lions"})],
    }


def extraction_cases() -> list[list[Any]]:
    values: list[Any] = ["38.722345,-9.139312", " +38.7 , -9.1 ", "38.7", "91,0", "0,-181", "1;2", None, 3,
                         "1,2" + " " * 30, "90,180", "-90,-180", "90.0000001,0", "38,-9", "+-38.7,9",
                         "38.,9", ".5,9", "38.7,-9.1\n", "\t38.7, -9.1　", "123,4", "12,1234",
                         "٣٨.٧,-٩.١", "３８,９", "38.7,-9.1" + " " * 19,
                         "38.7,-9.1" + " " * 20, "1e1,2", "0x1,2", "38.7 ,, -9.1", True]
    out = []
    for v in values:
        got = atak.parse_extraction(v)
        out.append([v, list(got) if got is not None else None])
    return out


def endpoint_cases() -> list[dict[str, Any]]:
    texts = [("10.42.0.5:4242", None), ("10.42.0.6", 4242), ("10.42.0.6", None), ("[fd00::7]:4243", 4242),
             ("[::1]", 4242), ("atak.local:6969", None), ("a b:1", 4242), ("host:0", None), ("host:65535", None),
             ("host:65536", None), ("host:123456", None), ("[ff02::1]:6969", None), ("239.2.3.1:6969", None),
             ("", 4242), ("[]:1", None), ("[1.2.3.4]:5", None), ("h_o:1", None), ("x" * 253, 1), ("x" * 254, 1),
             ("host:", 4242), (":4242", None), ("host:00080", None), ("té.pt:1", None)]
    out = []
    for text, default in texts:
        try:
            host, port = atak.parse_endpoint(text, default)
            out.append({"text": text, "default_port": default, "host": host, "port": port})
        except atak.AtakConfigError:
            out.append({"text": text, "default_port": default, "error": True})
    return out


class _Cfg:
    def __init__(self, multicast: str, staff: list[str], interval: float) -> None:
        self.atak_multicast = multicast
        self.atak_staff_endpoints = staff
        self.atak_interval_s = interval


def config_cases() -> list[dict[str, Any]]:
    cases = [("239.2.3.1:6969", [], 30.0), ("239.2.3.1", [], 30.0), ("0.0.0.0:6969", [], 30.0),
             ("atak.local:6969", [], 30.0), ("239.2.3.1:70000", [], 30.0), ("[ff02::1]:6969", [], 30.0),
             ("239.2.3.1:6969", [], 0.5), ("239.2.3.1:6969", [], 1.0), ("239.2.3.1:6969", [], 3600.0),
             ("239.2.3.1:6969", [], 3600.5), ("", [], 30.0), ("127.0.0.1:5000", [], 30.0),
             ("255.255.255.255:6969", [], 30.0), ("255.255.255.254:6969", [], 30.0), ("01.2.3.4:6969", [], 30.0),
             ("1.2.3:6969", [], 30.0), ("256.1.1.1:6969", [], 30.0), ("[1.2.3.4]:6969", [], 30.0),
             ("[zz::1]:6969", [], 30.0), ("239.2.3.1:6969", ["a b:1"], 30.0),
             ("239.2.3.1:6969", [f"10.0.0.{i}" for i in range(9)], 30.0),
             ("239.2.3.1:6969", [f"10.0.0.{i}" for i in range(8)], 30.0),
             ("239.2.3.1:6969", ["10.42.0.5:4242", "10.42.0.6", "[fd00::7]:4243"], 10.0)]
    out = []
    for mc, staff, interval in cases:
        try:
            atak.check_config(_Cfg(mc, staff, interval))  # type: ignore[arg-type]
            ok = True
        except atak.AtakConfigError:
            ok = False
        out.append({"multicast": mc, "staff_endpoints": staff, "interval_s": interval, "ok": ok})
    return out


def event_cases() -> list[dict[str, Any]]:
    """Whole events: a spot marker's details (marker_detail) or a player's (as the emitter's _players)."""
    specs: list[dict[str, Any]] = [
        {"uid": "atalaia.field.node.4", "type": "b-m-p-s-m", "how": "h-e", "lat": 38.722, "lon": -9.139,
         "now": 1e9, "start": 1e9, "stale": 1e9 + 60, "ce": None,
         "marker": {"callsign": "Caixa 4", "remarks": "Atalaia: -", "argb": -1, "battery": None, "group": None}},
        {"uid": "atalaia.f.node.4", "type": "b-m-p-s-m", "how": "h-e", "lat": 38.7, "lon": -9.1,
         "now": 1e9, "start": 1e9, "stale": 1e9 + 60, "ce": None,
         "marker": {"callsign": HOSTILE, "remarks": "Atalaia: " + HOSTILE, "argb": -1, "battery": None,
                    "group": None}},
        {"uid": "atalaia." + "f" * 64 + ".node.65534", "type": "b-m-p-s-m", "how": "h-e", "lat": -89.1234567,
         "lon": -179.1234567, "now": 1e9, "start": 1e9, "stale": 1e9 + 7200, "ce": 1e6,
         "marker": {"callsign": '"' * 100, "remarks": '"' * 400, "argb": -16777216, "battery": 100,
                    "group": "Dark Green"}},
        {"uid": "atalaia.field.node.7", "type": "b-m-p-s-m", "how": "h-e", "lat": 38.72, "lon": -9.14,
         "now": 1608148774.913, "start": 1608148774.913, "stale": 1608148834.913, "ce": None,
         "marker": {"callsign": "", "remarks": "", "argb": -2681795, "battery": 0, "group": "Red"}},
        {"uid": "atalaia.field.node.8", "type": "b-m-p-s-m", "how": "h-e", "lat": 0.0, "lon": 0.0,
         "now": 1e9, "start": 1e9, "stale": 1e9 + 60, "ce": None,
         "marker": {"callsign": "\U0001F600" * 60, "remarks": "Atalaia: €" * 30, "argb": -15045920,
                    "battery": 101, "group": "Blue"}},
        {"uid": "atalaia.field.node.9", "type": "b-m-p-s-m", "how": "h-e", "lat": 1.0, "lon": 2.0,
         "now": 1e9, "start": 1e9, "stale": 1e9 + 60, "ce": None,
         "marker": {"callsign": "x", "remarks": "Atalaia: blue, L1", "argb": -1, "battery": -1, "group": None}},
        {"uid": "atalaia.field.game.3.extraction", "type": "b-m-p-s-m", "how": "h-p", "lat": 38.7215,
         "lon": -9.139, "now": 1e9, "start": 1e9, "stale": 1e9 + 60, "ce": 40.0,
         "marker": {"callsign": "Extraction", "remarks": "Atalaia: Lobos (blue), 40 m", "argb": -15045920,
                    "battery": None, "group": "Blue"}},
        {"uid": "atalaia.field.player.p-3f9a", "type": "a-f-G-U-C", "how": "m-g", "lat": 38.7221,
         "lon": -9.1391, "now": 1e9 + 5, "start": 1e9 + 3, "stale": 1e9 + 23, "ce": 6.0,
         "player": {"callsign": "p-3f9a VIP", "group": "Red", "remarks": "Atalaia: red, vip, Cave"}},
        {"uid": "atalaia.field.player.p-0001", "type": "a-f-G-U-C", "how": "m-g", "lat": -33.5, "lon": 151.25,
         "now": 1e9, "start": 1e9, "stale": 1e9 + 20, "ce": None,
         "player": {"callsign": "p-0001", "group": None, "remarks": "Atalaia: -, player"}},
        # Attribute escaping beyond what users' texts can reach (a uid's characters are the config's).
        {"uid": "atalaia.<a&b>\"c'\td\ne\rf", "type": "b-m-p-s-m", "how": "h-e", "lat": 10.0, "lon": 20.0,
         "now": 1e9, "start": 1e9, "stale": 1e9 - 1, "ce": None, "detail": "none"},
    ]
    out = []
    for s in specs:
        if "marker" in s:
            m = s["marker"]
            detail = atak.marker_detail(m["callsign"], m["remarks"], m["argb"], m["battery"], m["group"])
        elif "player" in s:
            p = s["player"]
            # As AtakEmitter._players builds it.
            detail = [atak._el("contact", {"callsign": atak.xml_text(p["callsign"], atak.CALLSIGN_MAX,
                                                                      atak.CALLSIGN_BYTES)})]
            if p["group"] is not None:
                detail.append(atak._el("__group", {"name": p["group"], "role": atak.GROUP_ROLE}))
            detail.append(atak._el("remarks", None, atak.xml_text(p["remarks"], atak.REMARKS_MAX,
                                                                  atak.REMARKS_BYTES)))
        else:
            detail = []
        data = atak.event_xml(uid=s["uid"], cot_type=s["type"], how=s["how"], lat=s["lat"], lon=s["lon"],
                              now=s["now"], start=s["start"], stale=s["stale"], ce=s["ce"], detail=detail)
        out.append({**s, "xml": data.decode("utf-8")})
    return out


def refused_points() -> list[list[float]]:
    out = []
    for lat, lon in ((91.0, 0.0), (0.0, 181.0), (-90.0000001, 0.0), (0.0, -180.0000001)):
        try:
            atak.event_xml(uid="u", cot_type="b-m-p-s-m", how="h-e", lat=lat, lon=lon, now=0, start=0, stale=1)
        except ValueError:
            out.append([lat, lon])
    return out


def feature_cases() -> list[dict[str, Any]]:
    features = [
        ({"type": "safe_zone", "shape": "point", "x": 0.5, "y": 0.5, "team": None}, [TL, BR]),
        ({"type": "first_aid", "shape": "point", "x": 0.0, "y": 1.0, "team": None}, ROTATED),
        ({"type": "objective", "shape": "circle", "x": 0.25, "y": 0.75, "radius_m": 40.0, "team": None}, [TL, BR]),
        ({"type": "respawn", "shape": "circle", "x": 0.9, "y": 0.1, "radius_m": 2000.0, "team": "blue"}, ROTATED),
        ({"type": "hq", "shape": "circle", "x": 0.3, "y": 0.3, "radius_m": 1.0, "team": "wolves"}, [TL, BR]),
        ({"type": "parking", "shape": "polygon", "team": None,
          "points": [{"x": 0.1, "y": 0.1}, {"x": 0.4, "y": 0.1}, {"x": 0.25, "y": 0.4}]}, [TL, BR]),
        ({"type": "boundary", "shape": "polygon", "team": None,
          "points": [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 0.0}, {"x": 1.0, "y": 1.0}, {"x": 0.0, "y": 1.0}]},
         ROTATED),
        ({"type": "other", "shape": "polygon", "team": "red",
          "points": [{"x": i / 12, "y": (i * 7 % 12) / 12} for i in range(12)]}, [TL, BR]),
        ({"type": "nonsense", "shape": "point", "x": 1.0, "y": 0.0, "team": None}, [TL, BR]),
    ]
    teams = ["red", "blue", "wolves"]
    texts = [("Primeiros socorros", "Atalaia: First aid"), (HOSTILE, "Atalaia: Feature, " + HOSTILE),
             ("\U0001F600" * 48, "Atalaia: " + '"' * 300), ("", "")]
    out = []
    for i, (f, points) in enumerate(features):
        geo = georefmod.Georef(georefmod.check_points(points))
        callsign, remarks = texts[i % len(texts)]
        argb = atak.feature_colour(f, teams)
        group = atak.atak_team(f.get("team"))
        uid = f"atalaia.field.feature.{i + 1}"
        data, kind, lat, lon = atak.feature_xml(uid=uid, feature=f, geo=geo, now=1e9 + i, stale=1e9 + i + 60,
                                                callsign=callsign, remarks=remarks, argb=argb, group=group)
        out.append({"uid": uid, "feature": f, "georef": points, "now": 1e9 + i, "stale": 1e9 + i + 60,
                    "callsign": callsign, "remarks": remarks, "argb": argb, "group": group, "xml": data.decode("utf-8"),
                    "type": kind, "lat": lat, "lon": lon})
    return out


def drop_cases() -> list[dict[str, Any]]:
    cases = [("atalaia.f.node.4", atak.TYPE_PROP, 38.7, -9.1, 1e9),
             ("atalaia.field.feature.3", atak.TYPE_CIRCLE, 38.722, -9.139, 1e9 + 0.25),
             ("atalaia.field.feature.6", atak.TYPE_POLYGON, -0.5, 179.9999999, 1e9 + 0.0005),
             ("atalaia.field.player.p-1", atak.TYPE_PLAYER, 38.7221, -9.1391, 1700000000.5)]
    return [{"uid": u, "type": t, "lat": la, "lon": lo, "now": n, "xml": atak.drop_xml(u, t, la, lo, n).decode("utf-8")}
            for u, t, la, lo, n in cases]


def build() -> dict[str, Any]:
    return {
        "description": ("Known answers of the Pi controller's ATAK / Cursor on Target emitter "
                        "(controller/atalaia_controller/atak.py), for its port to the Android field controller "
                        "(app/lib/controller/controller_atak.dart, PE24 slice S7), which must give the same text "
                        "byte for byte (app/test/controller/controller_atak_test.dart). xml_text: value, limit, "
                        "max_bytes -> out. numbers: cot_time (seconds -> text), deg (_deg), metres (_metres; null "
                        "is unknown), fixed0 (the remarks' '{:.0f}'). colours: team_colour and atak_team per name "
                        "with the game's teams, argb_of (rgb, alpha), kml_colour, feature_colour. extraction: VIP / "
                        "Payload's parameter -> [lat, lon] or null. endpoints: parse_endpoint (host, port or error). "
                        "config: check_config's verdict. events: event_xml with marker_detail (marker) or a "
                        "player's details as AtakEmitter._players builds them (player), or none; refused_points: "
                        "[lat, lon] event_xml refuses. features: feature_xml (xml, type, lat, lon) for a feature "
                        "on a map position (georef: its control points). drops: drop_xml. node_remarks_grid: [owner display, level label or null, active, grid cell or null, text] of node_remarks with the field grid's cell (PKE-2). node_remarks: [owner display, level label or null, active, text] "
                        "of node_remarks (a box's remarks; active marks the box Progressive Domination has made active, "
                        "PD-MODE-16). Every xml is the XML "
                        "declaration, a newline and the event as xml.etree.ElementTree serialises it. Generated by "
                        "tools/atak_xml_vectors.py from atak.py itself (run it again after changing atak.py; "
                        "--check fails when this file is stale)."),
        "xml_text": xml_text_cases(),
        "numbers": number_cases(),
        "colours": colour_cases(),
        "extraction": extraction_cases(),
        "endpoints": endpoint_cases(),
        "config": config_cases(),
        "node_remarks": remarks_cases(),
        "node_remarks_grid": remarks_grid_cases(),
        "events": event_cases(),
        "refused_points": refused_points(),
        "features": feature_cases(),
        "drops": drop_cases(),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="fail if the file is stale")
    args = ap.parse_args()
    text = json.dumps(build(), indent=2) + "\n"
    if args.check:
        if not OUT.exists() or OUT.read_text() != text:
            print(f"{OUT.relative_to(REPO)} is stale: run python3 tools/atak_xml_vectors.py", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(text)
    print(f"wrote {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
