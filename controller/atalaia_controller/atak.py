# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Cursor on Target (CoT) for ATAK: the field's props on a map (ADR-P4-7 as amended, P4R18).

Off by default (``[atak] enabled = false``). When on, the controller in
charge of the live game sends one CoT ``<event>`` per box that has a
place on the georeferenced field image (georef.py), coloured by its
owner, and one for a VIP / Payload extraction zone:

- over **UDP** to ``[atak] multicast`` (ATAK's mesh default
  ``239.2.3.1:6969``, TTL 1 so it stays on the field's network; a
  unicast address works too), one event per datagram, every
  ``interval_s`` and **at once** when a box changes owner
  (``zone.captured``, ``zone.neutralized``, its STATE), moves on the
  image, or the georeference or the game changes; when the game ends,
  every marker is dropped;
- **player positions never go to multicast** (anyone on the field Wi-Fi
  can read it). With ``players = true`` they go only to the staff ATAK
  devices listed in ``staff_endpoints`` (TCP, "host:port", ATAK's
  point-to-point port is 4242), which see every player as marshals and
  the GM do (positions.py): GPS reports only, by pseudonymous player id,
  never by name (decision M9-6);
- on a multi-story field (field_levels.py) each box is placed by its
  level's georeference (its own control points, else level 0's) and its
  ``<remarks>`` end with the level's name; a player's, only when the phone
  said its level (decisions ML-6, ML-7). The point's ``hae`` stays unknown;
- with ``[atak] remote = true`` (off by default; Phase 4 follow-up,
  decisions FU5-*), the same props and zones to the site server, as ``cot``
  messages on the sync's stream that the controller opens itself
  (``remote_gm.py``), which relays them to the field's enrolled ATAK devices
  over TLS with client certificates; player positions go there only with
  ``remote_players = true`` too, and the site server sends them only to a
  certificate allowed to see them (P4R18);
- the field's map features (map_features.py, decisions MF-11 to MF-13), placed by their level's
  georeference: a point as a spot marker, a circle as an ATAK drawn circle (``u-d-c-c``, its
  radius in the ``<shape><ellipse>``), a polygon as a closed drawn shape (``u-d-f``, its corners as
  ``<link point>``, the first again at the end; the field boundary, MF-23, the same without a
  fill). Only those for everyone go to multicast; the staff
  devices get them all (a team's and the organisers' too: the feed is not per team); the remote
  relay gets the points and circles for everyone, a circle as a spot marker with its radius as
  ``ce`` (the extraction zone's form), never a polygon (the relay's narrow form, sync_format.py).

The format is the CoT base event schema, version 2.0 (MITRE, "CoT
Base-Event Schema (PUBLIC RELEASE).xsd", in the ATAK-CIV repository's
``takcot/mitre/``) with the TAK detail elements of ``takcot/xsd/details/``
and the examples of ``takcot/examples/``; the transport is TAK Protocol
version 0 (``commoncommo/core/impl/protobuf/protocol.txt``: one XML event
per UDP datagram; on TCP, events one after another, each with its XML
declaration and a newline, nothing after ``</event>``). The type strings
and their sources are in ``protocol/vectors/cot.json`` and the tests.

The XML is built with ``xml.etree.ElementTree``, never by pasting text:
node names and team display names come from users, so they are escaped
by the serializer, characters XML 1.0 does not allow are dropped and
lengths are capped (``xml_text``).
"""

from __future__ import annotations

import datetime
import ipaddress
import logging
import math
import re
import socket
import threading
import time
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING, Any, Callable, Iterable, Optional

from . import field_levels as levelsmod
from . import georef as georefmod
from . import map_features as mapmod

if TYPE_CHECKING:
    from .config import Config
    from .engine import Controller

log = logging.getLogger("atalaia.atak")

DEFAULT_MULTICAST = "239.2.3.1:6969"  # ATAK's SA multicast group (ADR-P4-7)
DEFAULT_STAFF_PORT = 4242             # ATAK's TCP point-to-point input (ADR-P4-7)
STAFF_ENDPOINTS_MAX = 8
XML_DECL = "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>\n"  # as in takcot/examples
DATAGRAM_MAX = 1400                   # bytes: one event per datagram, under a Wi-Fi MTU
CALLSIGN_MAX = 48
REMARKS_MAX = 160
# Each text's size once escaped and in UTF-8 is capped too, so the largest event (about 630 bytes
# without them) stays under DATAGRAM_MAX whatever the characters ('"' is 6 bytes as &quot;).
CALLSIGN_BYTES = 160
REMARKS_BYTES = 320
SHAPE_CALLSIGN_BYTES = 96            # a drawn shape's (map features, MF-11): its corners take the room
SHAPE_REMARKS_BYTES = 192
_ESCAPED = {"&": 5, "<": 4, ">": 4, '"': 6, "'": 6}
TCP_TIMEOUT_S = 2.0
UNKNOWN = "9999999.0"                 # hae, ce and le not known (takcot/examples use this value)

# Type strings (cot.json cites each one's source; tests check them there).
TYPE_PROP = "b-m-p-s-m"      # a spot map marker, coloured (takcot/examples "Marker - Spot.cot")
TYPE_ZONE_POINT = "b-m-p-s-m"
TYPE_PLAYER = "a-f-G-U-C"    # atoms, friend, ground, unit, combat (CoTtypes.xml "Gnd/Combat")
# How: h-e "human entered, estimated" for a box the GM placed on the image; h-p "cut and paste"
# for an extraction zone pasted from a map app (decision M5-3); m-g "machine, GPS" for a phone's fix.
HOW_IMAGE, HOW_PASTED, HOW_GPS = "h-e", "h-p", "m-g"
GROUP_ROLE = "Team Member"   # __group role (takcot/xsd/details/__group.xsd: name and role required)
# Map features' shapes (MF-11): ATAK's drawn circle and free-form shape (takcot/examples "Drawing Shapes -
# Circle.cot" and "Drawing Shapes - Free Form.cot"; cot.json).
TYPE_CIRCLE = "u-d-c-c"
TYPE_POLYGON = "u-d-f"
STYLE_LINK_TYPE = "b-x-KmlStyle"  # the circle's style link (the circle example; takcot/xsd/details/shape.xsd)
STROKE_WEIGHT = "3.0"
FILL_ALPHA = 0x60            # a translucent fill, the plan's features over the map (the examples use 0x96)
# What ATAK shows for a map feature (English, as the extraction zone's "Extraction") and its colour when
# it has no team, as the console's (console/src/components/map-features.js FEATURE_COLOURS).
FEATURE_NAMES = {"safe_zone": "Safe zone", "respawn": "Respawn", "hq": "HQ", "parking": "Parking",
                 "first_aid": "First aid", "objective": "Objective", "other": "Feature",
                 "boundary": "Field boundary"}
FEATURE_COLOURS = {"safe_zone": 0x14B8A6, "respawn": 0x6C757D, "hq": 0x6C757D, "parking": 0x546E7A,
                   "first_aid": 0xE91E63, "objective": 0xF59E0B, "other": 0x94A3B8, "boundary": 0x84CC16}
# The field boundary (MF-23) is an outline: a closed shape whose fill is fully transparent, so the
# field inside it stays readable on the map.
BOUNDARY_FILL_ALPHA = 0x00

# Team colours as the console shows them (console/src/ui.js TEAM_COLOURS and PALETTE), and the
# ATAK team for each (ATAK's 14 team colours; decision M9-5). A team that is no colour gets the
# console's palette by its place in the game, and no ATAK team.
_COLOURS = {
    "red": 0xD7263D, "blue": 0x1B6EE0, "green": 0x2A9D4B, "yellow": 0xE8B400, "orange": 0xEF7D1A,
    "purple": 0x8E44AD, "black": 0x333333, "white": 0xBBBBBB,
}
_ALIASES = {"vermelho": "red", "vermelha": "red", "azul": "blue", "verde": "green", "amarelo": "yellow",
            "amarela": "yellow", "laranja": "orange", "roxo": "purple", "roxa": "purple", "preto": "black",
            "preta": "black", "branco": "white", "branca": "white"}
_PALETTE = (0xD7263D, 0x1B6EE0, 0x2A9D4B, 0xE8B400, 0x8E44AD, 0xEF7D1A, 0x16A2B8, 0x6C757D)
ATAK_TEAMS = ("White", "Yellow", "Orange", "Magenta", "Red", "Maroon", "Purple", "Dark Blue", "Blue", "Cyan",
              "Teal", "Green", "Dark Green", "Brown")
_ATAK_TEAM = {t.lower().replace(" ", ""): t for t in ATAK_TEAMS}
NEUTRAL_ARGB = -1  # white (takcot/examples "Marker - 2525.cot": color argb='-1')

_XML_BAD = re.compile("[^\u0009\u000a\u000d\u0020-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")
_EXTRACTION_RE = re.compile(r"\s*\+?(-?\d{1,2}(?:\.\d+)?)\s*,\s*\+?(-?\d{1,3}(?:\.\d+)?)\s*")


class AtakConfigError(ValueError):
    pass


# --- text and values -----------------------------------------------------------------------


def xml_text(value: Any, limit: int, max_bytes: Optional[int] = None) -> str:
    """User text made safe for an XML 1.0 attribute or element: characters XML does not allow
    (controls, lone surrogates, U+FFFE/U+FFFF) dropped, whitespace runs folded, at most
    ``limit`` characters and, escaped as in an attribute and in UTF-8, at most ``max_bytes``
    bytes. Escaping is the serializer's job (ElementTree)."""
    text = _XML_BAD.sub("", str(value))
    text = " ".join(text.split())[:limit]
    if max_bytes is not None:
        size = 0
        for i, ch in enumerate(text):
            size += _ESCAPED.get(ch) or len(ch.encode("utf-8"))
            if size > max_bytes:
                return text[:i].rstrip()
    return text


def cot_time(t: float) -> str:
    """CCYY-MM-DDThh:mm:ss.sssZ in UTC (the base event schema's time format, with milliseconds as
    in takcot/examples)."""
    dt = datetime.datetime.fromtimestamp(t, datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _deg(v: float) -> str:
    return f"{v:.7f}"  # about a centimetre


def _metres(v: Optional[float]) -> str:
    return UNKNOWN if v is None else f"{max(0.0, float(v)):.1f}"


def team_colour(team: Optional[str], teams: list[str]) -> int:
    """A team's colour as signed 32-bit ARGB (ATAK's <color argb>), like the console's."""
    if not team:
        return NEUTRAL_ARGB
    key = _ALIASES.get(team.lower(), team.lower())
    rgb = _COLOURS.get(key)
    if rgb is None:
        i = teams.index(team) if team in teams else len(team)
        rgb = _PALETTE[i % len(_PALETTE)]
    argb = 0xFF000000 | rgb
    return argb - (1 << 32)


def argb_of(rgb: int, alpha: int = 0xFF) -> int:
    """An RGB colour and an alpha as signed 32-bit ARGB."""
    v = ((alpha & 0xFF) << 24) | (rgb & 0xFFFFFF)
    return v - (1 << 32) if v >= 1 << 31 else v


def kml_colour(argb: int) -> str:
    """Signed ARGB as KML's aabbggrr (the circle example's <LineStyle><color>ffffffff for argb -1)."""
    v = argb & 0xFFFFFFFF
    a, r, g, b = (v >> 24) & 0xFF, (v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF
    return f"{a:02x}{b:02x}{g:02x}{r:02x}"


def feature_colour(feature: dict[str, Any], teams: list[str]) -> int:
    """A map feature's ARGB: its team's colour, else its type's."""
    team = feature.get("team")
    if team:
        return team_colour(team, teams)
    return argb_of(FEATURE_COLOURS.get(feature.get("type"), FEATURE_COLOURS["other"]))


def atak_team(team: Optional[str]) -> Optional[str]:
    """The ATAK team (``__group name``) for an Atalaia team named after a colour, else None."""
    if not team:
        return None
    key = _ALIASES.get(team.lower(), team.lower()).replace(" ", "").replace("_", "").replace("-", "")
    return _ATAK_TEAM.get(key)


def parse_extraction(value: Any) -> Optional[tuple[float, float]]:
    """VIP / Payload's ``extraction`` parameter, "latitude,longitude" (decision M5-3), or None."""
    if not isinstance(value, str) or len(value) > 28:
        return None
    m = _EXTRACTION_RE.fullmatch(value)
    if not m:
        return None
    lat, lon = float(m.group(1)), float(m.group(2))
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    return lat, lon


# --- events --------------------------------------------------------------------------------


def event_xml(*, uid: str, cot_type: str, how: str, lat: float, lon: float, now: float, start: float,
              stale: float, ce: Optional[float] = None, detail: Iterable[ET.Element] = ()) -> bytes:
    """One CoT event: the XML declaration, a newline and the <event> (TAK Protocol version 0)."""
    if not (math.isfinite(lat) and math.isfinite(lon) and -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        raise ValueError("a CoT point needs a latitude of -90 to 90 and a longitude of -180 to 180")
    ev = ET.Element("event", {"version": "2.0", "uid": uid, "type": cot_type, "time": cot_time(now),
                              "start": cot_time(start), "stale": cot_time(stale), "how": how})
    ET.SubElement(ev, "point", {"lat": _deg(lat), "lon": _deg(lon), "hae": UNKNOWN, "ce": _metres(ce),
                                "le": UNKNOWN})
    det = ET.SubElement(ev, "detail")
    for child in detail:
        det.append(child)
    return (XML_DECL + ET.tostring(ev, encoding="unicode", short_empty_elements=True)).encode("utf-8")


def _el(tag: str, attrs: Optional[dict[str, str]] = None, text: Optional[str] = None) -> ET.Element:
    el = ET.Element(tag, attrs or {})
    if text is not None:
        el.text = text
    return el


def node_remarks(owner_display: str, level_label: Optional[str] = None, active: bool = False) -> str:
    """A box's remarks: its owner (``-`` for none), ``active`` while the mode has made it the box to
    take (Progressive Domination, decision PD-MODE-16), then its level's name on a multi-story field."""
    out = f"Atalaia: {owner_display}" if owner_display else "Atalaia: -"
    if active:
        out += ", active"
    if level_label is not None:
        out += f", {level_label}"
    return out


def marker_detail(callsign: str, remarks: str, argb: int, battery: Optional[int] = None,
                  group: Optional[str] = None) -> list[ET.Element]:
    """A spot marker's details, as in takcot/examples "Marker - Spot.cot": the colour is the owner's
    (``<color>``, what ATAK paints), and an owner named after one of ATAK's team colours is also
    that team (``<__group>``, decision M9-5)."""
    out = [_el("contact", {"callsign": xml_text(callsign, CALLSIGN_MAX, CALLSIGN_BYTES) or "?"}),
           _el("remarks", None, xml_text(remarks, REMARKS_MAX, REMARKS_BYTES)),
           _el("color", {"argb": str(argb)}),
           _el("usericon", {"iconsetpath": f"COT_MAPPING_SPOTMAP/{TYPE_PROP}/{argb}"})]
    if group is not None:
        out.append(_el("__group", {"name": group, "role": GROUP_ROLE}))
    if battery is not None and not isinstance(battery, bool) and isinstance(battery, int) and 0 <= battery <= 100:
        out.insert(0, _el("status", {"battery": str(battery)}))
    return out


def shape_detail(callsign: str, remarks: str, argb: int, fill_alpha: int = FILL_ALPHA) -> list[ET.Element]:
    """A drawn shape's style and names, in the order of takcot/examples "Drawing Shapes - *.cot"; its texts
    have tighter byte caps than a marker's, so a polygon's corners fit the datagram too."""
    return [_el("strokeColor", {"value": str(argb)}), _el("strokeWeight", {"value": STROKE_WEIGHT}),
            _el("fillColor", {"value": str(argb_of(argb, fill_alpha))}),
            _el("contact", {"callsign": xml_text(callsign, CALLSIGN_MAX, SHAPE_CALLSIGN_BYTES) or "?"}),
            _el("remarks", None, xml_text(remarks, REMARKS_MAX, SHAPE_REMARKS_BYTES)),
            _el("labels_on", {"value": "true"})]


def feature_xml(*, uid: str, feature: dict[str, Any], geo: georefmod.Georef, now: float, stale: float,
                callsign: str, remarks: str, argb: int,
                group: Optional[str] = None) -> tuple[bytes, str, float, float]:
    """A map feature's CoT event (MF-11): ``(event, type, lat, lon)``, the point being its pin (a polygon's
    vertex average). A point is a spot marker; a circle ATAK's drawn circle (``<shape><ellipse>``, whose
    major and minor ATAK reads as the radius in metres); a polygon ATAK's drawn shape, closed by giving
    its first corner again at the end, as ATAK writes a closed shape."""
    cx, cy = mapmod.centre(feature)
    lat, lon = geo.to_latlon(cx, cy)
    shape = feature["shape"]
    if shape == "point":
        data = event_xml(uid=uid, cot_type=TYPE_PROP, how=HOW_IMAGE, lat=lat, lon=lon, now=now, start=now,
                         stale=stale, detail=marker_detail(callsign, remarks, argb, group=group))
        return data, TYPE_PROP, lat, lon
    detail: list[ET.Element] = []
    if shape == "circle":
        radius = f"{float(feature['radius_m']):.1f}"
        el = ET.Element("shape")
        ET.SubElement(el, "ellipse", {"major": radius, "minor": radius, "angle": "360"})
        link = ET.SubElement(el, "link", {"uid": f"{uid}.Style", "type": STYLE_LINK_TYPE, "relation": "p-c"})
        style = ET.SubElement(link, "Style")
        line = ET.SubElement(style, "LineStyle")
        ET.SubElement(line, "color").text = kml_colour(argb)
        ET.SubElement(line, "width").text = STROKE_WEIGHT
        poly = ET.SubElement(style, "PolyStyle")
        ET.SubElement(poly, "color").text = kml_colour(argb_of(argb, FILL_ALPHA))
        detail.append(el)
        cot_type = TYPE_CIRCLE
    else:
        corners = [geo.to_latlon(p["x"], p["y"]) for p in feature["points"]]
        for la, lo in [*corners, corners[0]]:
            detail.append(_el("link", {"point": f"{_deg(la)},{_deg(lo)}"}))
        cot_type = TYPE_POLYGON
    fill = BOUNDARY_FILL_ALPHA if feature.get("type") == mapmod.BOUNDARY else FILL_ALPHA
    detail += shape_detail(callsign, remarks, argb, fill)
    data = event_xml(uid=uid, cot_type=cot_type, how=HOW_IMAGE, lat=lat, lon=lon, now=now, start=now, stale=stale,
                     detail=detail)
    return data, cot_type, lat, lon


def drop_xml(uid: str, cot_type: str, lat: float, lon: float, now: float) -> bytes:
    """Removes a marker: its stale time before its start ("By convention, CoT allows the stale time
    to predate the start time ... how CoT indicates 'drop track'", The Developer's Guide to Cursor
    on Target, MITRE, 2005)."""
    return event_xml(uid=uid, cot_type=cot_type, how=HOW_IMAGE, lat=lat, lon=lon, now=now, start=now,
                     stale=now - 1.0)


# --- addresses -------------------------------------------------------------------------------


_ENDPOINT_RE = re.compile(r"\[([0-9A-Fa-f:.]{2,45})\](?::([0-9]{1,5}))?|([A-Za-z0-9.-]{1,253})(?::([0-9]{1,5}))?")


def parse_endpoint(text: Any, default_port: Optional[int] = None) -> tuple[str, int]:
    """"host:port" (an IPv6 address in brackets, "[::1]:4242") as (host, port); without a port,
    ``default_port`` if there is one."""
    m = _ENDPOINT_RE.fullmatch(text) if isinstance(text, str) else None
    if m is None:
        raise AtakConfigError(f"{text!r}: host:port (an IPv6 address in brackets)")
    host = m.group(1) or m.group(3)
    port_text = m.group(2) or m.group(4)
    if port_text is None:
        if default_port is None:
            raise AtakConfigError(f"{text!r}: host:port, with the port")
        return host, default_port
    if not 1 <= int(port_text) <= 65535:
        raise AtakConfigError(f"{text!r}: a port of 1-65535")
    return host, int(port_text)


def check_config(cfg: "Config") -> None:
    if cfg.atak_multicast:
        host, _ = parse_endpoint(cfg.atak_multicast)
        try:
            addr = ipaddress.ip_address(host)
        except ValueError:
            raise AtakConfigError("atak.multicast: an IP address and port, such as 239.2.3.1:6969") from None
        if addr.version != 4 or addr.is_unspecified or str(addr) == "255.255.255.255":
            raise AtakConfigError("atak.multicast: an IPv4 multicast (or unicast) address and port, "
                                  "such as 239.2.3.1:6969")
    if len(cfg.atak_staff_endpoints) > STAFF_ENDPOINTS_MAX:
        raise AtakConfigError(f"atak.staff_endpoints: at most {STAFF_ENDPOINTS_MAX}")
    for ep in cfg.atak_staff_endpoints:
        parse_endpoint(ep, DEFAULT_STAFF_PORT)
    if not 1.0 <= cfg.atak_interval_s <= 3600.0:
        raise AtakConfigError("atak.interval_s must be 1-3600 seconds")


class UdpSender:
    """One CoT event per datagram, to a multicast group (TTL 1: the field's own network) or one host."""

    def __init__(self, target: str) -> None:
        host, port = parse_endpoint(target)
        self.addr = (host, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        if ipaddress.ip_address(host).is_multicast:
            self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)

    def send(self, events: list[bytes]) -> int:
        for data in events:
            self.sock.sendto(data, self.addr)
        return len(events)

    def close(self) -> None:
        self.sock.close()


class TcpSender:
    """Staff ATAK devices: one connection per endpoint and cycle, the events one after another."""

    def __init__(self, endpoints: list[str], timeout: float = TCP_TIMEOUT_S) -> None:
        self.endpoints = [parse_endpoint(e, DEFAULT_STAFF_PORT) for e in endpoints]
        self.timeout = timeout

    def send(self, events: list[bytes]) -> tuple[int, list[str]]:
        sent, errors = 0, []
        if not events:
            return 0, []
        payload = b"".join(events)
        for host, port in self.endpoints:
            try:
                with socket.create_connection((host, port), timeout=self.timeout) as s:
                    s.sendall(payload)
                sent += len(events)
            except OSError as exc:
                errors.append(f"{host}:{port}: {exc}")
        return sent, errors

    def close(self) -> None:
        pass


# --- the emitter -------------------------------------------------------------------------------


class AtakEmitter:
    """Follows the controller's messages and sends the picture over UDP and to staff over TCP."""

    def __init__(self, cfg: "Config", controller: "Controller", *, wall: Callable[[], float] = time.time,
                 udp: Optional[Any] = None, tcp: Optional[Any] = None, remote: Optional[Any] = None) -> None:
        self.cfg = cfg
        self.ctrl = controller
        self._wall = wall
        # The UDP socket is opened on the first send and closed by stop() (it is opened again if the
        # emitter sends after that), so building an emitter that never runs leaks nothing.
        self._udp_given = udp
        self.udp: Optional[Any] = udp
        self.tcp = tcp if tcp is not None else (TcpSender(cfg.atak_staff_endpoints)
                                                if cfg.atak_staff_endpoints else None)
        # The site server's stream (remote_gm.RemoteGm) with [atak] remote = true: push_cot(events) queues the
        # events while the site server relays them; on a new socket it asks for the whole picture again.
        self.remote = remote if cfg.atak_remote else None
        if self.remote is not None:
            self.remote.on_relay_open = self.resend_all
        self._lock = threading.Lock()
        self._send_lock = threading.Lock()  # sending and closing the sockets
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._dirty: set[int] = set()
        self._all = True
        self._end: Optional[int] = None          # a game that ended: drop its markers
        self._owner_hint: dict[int, Optional[str]] = {}
        self._active_game: Any = None
        self._active: Optional[str] = None       # the box a mode has made active, by name (PD-MODE-16)
        self._sent_owner: dict[int, Optional[str]] = {}
        self._markers: dict[str, tuple[str, float, float]] = {}  # uid -> (type, lat, lon), on UDP
        self._staff_markers: dict[str, tuple[str, float, float]] = {}
        self._remote_markers: dict[str, tuple[str, float, float]] = {}
        self._next_players = 0.0
        self.stats: dict[str, Any] = {"udp_events": 0, "tcp_events": 0, "remote_events": 0, "errors": 0,
                                      "last_error": None,
                                      "last_sent_at": None, "no_georef": False, "features": 0}
        controller.atak = self
        controller.add_listener(self.on_controller_message)

    # --- lifecycle ---------------------------------------------------------------------------

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="atak", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        self.close()

    def close(self) -> None:
        """Closes the sockets (stop() does; safe to call again)."""
        with self._send_lock:
            if self.udp is not None:
                self.udp.close()
                self.udp = None
            if self.tcp is not None:
                self.tcp.close()

    def _udp_sender(self) -> Optional[Any]:
        if self.udp is None:
            if self._udp_given is not None:
                self.udp = self._udp_given
            elif self.cfg.atak_multicast:
                self.udp = UdpSender(self.cfg.atak_multicast)
        return self.udp

    def _run(self) -> None:
        next_full = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            full = now >= next_full
            if full:
                next_full = now + self.cfg.atak_interval_s
            try:
                self.cycle(full=full)
            except Exception:
                log.exception("ATAK cycle failed")
            wait = next_full - time.monotonic()
            if self._players_on() or self._remote_players_on():
                wait = min(wait, 1.0)  # player positions go at their own pace (positions.py)
            self._wake.wait(max(0.05, wait))
            self._wake.clear()

    # --- what changed --------------------------------------------------------------------------

    def on_controller_message(self, msg: dict[str, Any]) -> None:
        kind = msg.get("type")
        wake = True
        with self._lock:
            if kind == "node":
                node = msg.get("node") or {}
                nid = node.get("node_id")
                if isinstance(nid, int):
                    self._owner_hint.pop(nid, None)
                    if node.get("owner") != self._sent_owner.get(nid, "?"):
                        self._dirty.add(nid)
                    else:
                        wake = False
            elif kind == "event":
                ev = msg.get("event") or {}
                if ev.get("type") in ("zone.captured", "zone.neutralized") and isinstance(ev.get("node"), int):
                    # Sent at once with the event's team: the box's next STATE confirms it.
                    self._owner_hint[ev["node"]] = ev.get("team") if ev["type"] == "zone.captured" else None
                    self._dirty.add(ev["node"])
                elif ev.get("type") in ("progressive.activated", "progressive.completed"):
                    # The active box changes: the old and the new marker both, so all of them again.
                    zone = (ev.get("data") or {}).get("zone")
                    self._active = zone if ev["type"] == "progressive.activated" and isinstance(zone, str) \
                        and zone else None
                    self._all = True
                else:
                    wake = False
            elif kind == "position" and isinstance(msg.get("node_id"), int):
                self._dirty.add(msg["node_id"])
            elif kind == "game":
                game = msg.get("game") or {}
                if game.get("state") == "ended" and isinstance(game.get("id"), int):
                    self._end = game["id"]
                if game.get("state") == "ended" or game.get("id") != self._active_game:
                    self._active = None
                self._active_game = game.get("id")
                self._all = True
            elif kind in ("field_georef", "field_image", "field_levels", "map_features"):
                self._all = True
            else:
                wake = False
        if wake:
            self._wake.set()

    def _players_on(self) -> bool:
        return bool(self.cfg.atak_players and self.tcp is not None)

    def _remote_players_on(self) -> bool:
        return bool(self.remote is not None and self.cfg.atak_remote_players)

    def resend_all(self) -> None:
        """Everything again at the next cycle (the site server's relay has just taken a new socket)."""
        with self._lock:
            self._all = True
        self._wake.set()

    # --- one cycle -----------------------------------------------------------------------------

    def cycle(self, full: bool = True) -> dict[str, int]:
        """Sends what is due; returns the number of events sent per transport, ``udp``, ``tcp`` and
        ``remote`` (tests call it)."""
        with self._lock:
            dirty, self._dirty = self._dirty, set()
            everything = full or self._all
            self._all = False
            ended, self._end = self._end, None
            hints = dict(self._owner_hint)
            active = self._active
        now = self._wall()
        udp_out: list[bytes] = []
        tcp_out: list[bytes] = []
        remote_out: list[bytes] = []
        if ended is not None:
            udp_out += self._drops(self._markers, now)
            tcp_out += self._drops(self._staff_markers, now)
            remote_out += self._drops(self._remote_markers, now)
        game = self._live_game()
        levels = levelsmod.load(self.ctrl.store)
        geos = {lv: georefmod.for_level(self.ctrl.store, lv) for lv in range(levelsmod.in_use(levels))} \
            if game is not None else {}
        self.stats["no_georef"] = game is not None and not any(geos.values())
        if game is not None and any(geos.values()):
            props = self._props(game, geos, levels, now, hints, None if everything else dirty, active)
            udp_out += props
            tcp_out += props
            if self.remote is not None:
                remote_out += props
            if everything:
                udp_f, tcp_f, remote_f = self._features(game, geos, levels, now)
                udp_out += udp_f
                tcp_out += tcp_f
                remote_out += remote_f
        else:
            # No live game here or no georeference any more: what ATAK shows is no longer true.
            udp_out += self._drops(self._markers, now)
            tcp_out += self._drops(self._staff_markers, now)
            remote_out += self._drops(self._remote_markers, now)
        staff, remote = self._players_on(), self._remote_players_on()
        if game is not None and (staff or remote) and (everything or now >= self._next_players):
            for uid, data, lat, lon in self._players(game, now, geos, levels):
                if staff:
                    tcp_out.append(data)
                    self._staff_markers[uid] = (TYPE_PLAYER, lat, lon)
                if remote:  # never without remote_players (P4R18): the site server filters again
                    remote_out.append(data)
                    self._remote_markers[uid] = (TYPE_PLAYER, lat, lon)
            self._next_players = now + self._player_interval(game)
        return self._send(udp_out, tcp_out, now, remote_out)

    def _send(self, udp_out: list[bytes], tcp_out: list[bytes], now: float,
              remote_out: Optional[list[bytes]] = None) -> dict[str, int]:
        out = {"udp": 0, "tcp": 0, "remote": 0}
        with self._send_lock:
            udp = self._udp_sender() if udp_out else None
            if udp is not None:
                try:
                    out["udp"] = udp.send(udp_out)
                    self.stats["udp_events"] += out["udp"]
                except OSError as exc:
                    self._error(f"UDP {self.cfg.atak_multicast}: {exc}")
            sent, errors = self.tcp.send(tcp_out) if self.tcp is not None and tcp_out else (0, [])
            if self.remote is not None and remote_out:
                out["remote"] = self.remote.push_cot(remote_out)
                self.stats["remote_events"] += out["remote"]
        if sent or errors:
            out["tcp"] = sent
            self.stats["tcp_events"] += sent
            for e in errors:
                self._error(f"TCP {e}")
        if out["udp"] or out["tcp"] or out["remote"]:
            self.stats["last_sent_at"] = now
        return out

    def _error(self, text: str) -> None:
        self.stats["errors"] += 1
        if self.stats["last_error"] != text:
            log.warning("ATAK: %s", text)
        self.stats["last_error"] = text

    def _live_game(self) -> Optional[dict[str, Any]]:
        game, fc = self.ctrl.game, self.ctrl.fc
        if game is None or fc is None or not fc.is_controller or game.get("state") == "ended":
            return None  # a standby controller sends nothing: the one in charge does
        return game

    @staticmethod
    def _drops(markers: dict[str, tuple[str, float, float]], now: float) -> list[bytes]:
        out = [drop_xml(uid, t, lat, lon, now) for uid, (t, lat, lon) in markers.items()]
        markers.clear()
        return out

    def _uid(self, *parts: Any) -> str:
        return ".".join(["atalaia", self.cfg.field_id, *(str(p) for p in parts)])

    def _display(self, game: dict[str, Any], team: Optional[str]) -> str:
        if not team:
            return ""
        info = (game.get("team_info") or {}).get(team) or {}
        name = info.get("display_name")
        return f"{name} ({team})" if isinstance(name, str) and name else team

    def _props(self, game: dict[str, Any], geos: dict[int, Optional[georefmod.Georef]], levels: dict[str, Any],
               now: float, hints: dict[int, Optional[str]], only: Optional[set[int]],
               active: Optional[str] = None) -> list[bytes]:
        """Each placed box on the map by its level's georeference (its own, else level 0's: ML-6); on a
        multi-story field the remarks name its level (ML-7)."""
        stale = now + 2 * self.cfg.atak_interval_s  # ADR-P4-7: start + 2 x the update interval
        teams = list(game.get("teams") or [])
        places = self.ctrl.store.positions(game["id"])
        out: list[bytes] = []
        nodes = {n["node_id"]: n for n in self.ctrl.nodes(game["id"]) if isinstance(n.get("node_id"), int)}
        for nid in sorted(set(nodes) | set(places)):
            if only is not None and nid not in only:
                continue
            place = places.get(nid)
            if place is None:
                continue  # not placed on the image: nowhere to put it
            level = levelsmod.shown(levels, place.get("level"))
            geo = geos.get(level)
            if geo is None:
                continue  # its level has no place on the map
            node = nodes.get(nid, {})
            owner = hints[nid] if nid in hints else node.get("owner")
            lat, lon = geo.to_latlon(place["x"], place["y"])
            uid = self._uid("node", nid)
            name = node.get("name") or f"{nid}"
            remarks = node_remarks(self._display(game, owner) if owner else "",
                                   levelsmod.label(levels, level) if levels["enabled"] else None,
                                   active is not None and name == active)
            data = event_xml(uid=uid, cot_type=TYPE_PROP, how=HOW_IMAGE, lat=lat, lon=lon, now=now, start=now,
                             stale=stale, detail=marker_detail(name, remarks, team_colour(owner, teams),
                                                               node.get("battery_pct"), atak_team(owner)))
            out.append(data)
            self._sent_owner[nid] = owner
            self._mark(uid, TYPE_PROP, lat, lon)
        if only is None:
            out += self._zones(game, now, stale, teams)
        return out

    def _zones(self, game: dict[str, Any], now: float, stale: float, teams: list[str]) -> list[bytes]:
        """VIP / Payload's extraction zone (public, decision M5-1): a marker with the radius as ce."""
        params = game.get("params") or {}
        where = parse_extraction(params.get("extraction"))
        if where is None:
            return []
        radius = params.get("radius_m", 25)
        radius = float(radius) if isinstance(radius, (int, float)) and not isinstance(radius, bool) else 25.0
        team = params.get("vip_team") if isinstance(params.get("vip_team"), str) else None
        uid = self._uid("game", game["id"], "extraction")
        data = event_xml(uid=uid, cot_type=TYPE_ZONE_POINT, how=HOW_PASTED, lat=where[0], lon=where[1], now=now,
                         start=now, stale=stale, ce=radius,
                         detail=marker_detail("Extraction", f"Atalaia: {self._display(game, team) or '-'}, "
                                              f"{radius:.0f} m", team_colour(team, teams), group=atak_team(team)))
        self._mark(uid, TYPE_ZONE_POINT, where[0], where[1])
        return [data]

    def _features(self, game: dict[str, Any], geos: dict[int, Optional[georefmod.Georef]], levels: dict[str, Any],
                  now: float) -> tuple[list[bytes], list[bytes], list[bytes]]:
        """The field's map features on levels in use whose level has a place on the map (MF-11 to MF-13),
        as (multicast, staff, remote) events; a feature that went (deleted, moved off the map, or no longer
        for everyone) is dropped where it was sent."""
        stale = now + 2 * self.cfg.atak_interval_s
        teams = list(game.get("teams") or [])
        prefix = self._uid("feature") + "."
        out: dict[str, list[bytes]] = {"udp": [], "tcp": [], "remote": []}
        sent: dict[str, dict[str, tuple[str, float, float]]] = {"udp": {}, "tcp": {}, "remote": {}}
        for f in mapmod.in_use(self.ctrl.store, levels):
            geo = geos.get(f["level"])
            if geo is None:
                continue  # its level has no place on the map
            uid = prefix + str(f["id"])
            team = f.get("team")
            name = FEATURE_NAMES.get(f["type"], FEATURE_NAMES["other"])
            remarks = f"Atalaia: {name}"
            if team:
                remarks += f", {self._display(game, team)}"
            if f["visibility"] == "team":
                remarks += ", team only"
            elif f["visibility"] == "organisers":
                remarks += ", organisers only"
            if f["shape"] == "circle":
                remarks += f", {float(f['radius_m']):.0f} m"
            if levels["enabled"]:
                remarks += f", {levelsmod.label(levels, f['level'])}"
            if f.get("note"):
                remarks += f". {f['note']}"
            argb = feature_colour(f, teams)
            group = atak_team(team)
            data, kind, lat, lon = feature_xml(uid=uid, feature=f, geo=geo, now=now, stale=stale,
                                               callsign=f["label"] or name, remarks=remarks, argb=argb, group=group)
            out["tcp"].append(data)  # the staff's devices see every feature, as the organisers do (MF-12)
            sent["tcp"][uid] = (kind, lat, lon)
            if f["visibility"] != "everyone":
                continue  # never on the field's Wi-Fi, nor relayed (MF-12)
            out["udp"].append(data)
            sent["udp"][uid] = (kind, lat, lon)
            if self.remote is not None and f["shape"] != "polygon":
                # The relay's narrow form takes spot markers only (sync_format.cot_event; MF-13): a circle
                # goes as its centre with the radius as ce, as the extraction zone does.
                ce = float(f["radius_m"]) if f["shape"] == "circle" else None
                out["remote"].append(event_xml(uid=uid, cot_type=TYPE_PROP, how=HOW_IMAGE, lat=lat, lon=lon,
                                               now=now, start=now, stale=stale, ce=ce,
                                               detail=marker_detail(f["label"] or name, remarks, argb,
                                                                    group=group)))
                sent["remote"][uid] = (TYPE_PROP, lat, lon)
        for key, markers in (("udp", self._markers), ("tcp", self._staff_markers), ("remote", self._remote_markers)):
            for uid in [u for u in markers if u.startswith(prefix) and u not in sent[key]]:
                cot_type, lat, lon = markers.pop(uid)
                out[key].append(drop_xml(uid, cot_type, lat, lon, now))
            markers.update(sent[key])
        self.stats["features"] = len(sent["tcp"])
        return out["udp"], out["tcp"], out["remote"]

    def _mark(self, uid: str, cot_type: str, lat: float, lon: float) -> None:
        """A box or zone sent: every transport that got it drops it at the end."""
        self._markers[uid] = (cot_type, lat, lon)
        self._staff_markers[uid] = (cot_type, lat, lon)
        if self.remote is not None:
            self._remote_markers[uid] = (cot_type, lat, lon)

    def _player_interval(self, game: dict[str, Any]) -> float:
        from .positions import Positions  # noqa: PLC0415

        return float(Positions.interval(game))

    def _players(self, game: dict[str, Any], now: float, geos: Optional[dict[int, Any]] = None,
                 levels: Optional[dict[str, Any]] = None) -> list[tuple[str, bytes, float, float]]:
        """Staff endpoints and the remote relay only, never UDP: every position of the live game that has a
        place (staff see all), as (uid, event, lat, lon). A GPS position is where the phone is; an indoor one
        (``ble``, beacons.py) is the room: its marker sits where the GM placed the beacon on its level's plan
        (by that level's map position, as the boxes), is marked as estimated from the image (``h-e``), and its
        remarks name the room and zone. A beacon not placed on a plan, or on a level without a map position,
        has no place on the map."""
        teams = list(game.get("teams") or [])
        interval = self._player_interval(game)
        levels = levels if levels is not None else levelsmod.load(self.ctrl.store)
        geos = geos if geos is not None else {}
        out: list[tuple[str, bytes, float, float]] = []
        for pid, pos in sorted(self.ctrl.store.player_positions(game["id"]).items()):
            indoor = pos.get("source") == "ble"
            if indoor:
                geo = geos.get(levelsmod.shown(levels, pos.get("level")))
                if geo is None or pos.get("x") is None or pos.get("y") is None:
                    continue
            elif pos.get("source") != "gps" or pos.get("lat") is None or pos.get("lon") is None:
                continue
            seen = float(pos.get("received_at") or now)
            stale = seen + 2 * interval
            if stale <= now:
                continue
            team_id = pos.get("team") or 0
            team = teams[team_id - 1] if isinstance(team_id, int) and 1 <= team_id <= len(teams) else None
            checkin = self.ctrl.store.checkin(game["id"], pid) or {}
            role = checkin.get("role") or "player"
            callsign = f"{pid} VIP" if role == "vip" else pid
            detail = [_el("contact", {"callsign": xml_text(callsign, CALLSIGN_MAX, CALLSIGN_BYTES)})]
            group = atak_team(team)
            if group is not None:
                detail.append(_el("__group", {"name": group, "role": GROUP_ROLE}))
            remarks = f"Atalaia: {self._display(game, team) or '-'}, {role}"
            if levels["enabled"] and isinstance(pos.get("level"), int) and pos["level"] < levelsmod.in_use(levels):
                remarks += f", {levelsmod.label(levels, pos['level'])}"  # ML-7: only a level the phone gave
            if indoor and pos.get("room"):
                remarks += f", {pos['room']}" + (f" ({pos['zone']})" if pos.get("zone") else "")  # BLE-8
            detail.append(_el("remarks", None, xml_text(remarks, REMARKS_MAX, REMARKS_BYTES)))
            uid = self._uid("player", pid)
            if indoor:
                lat, lon = geo.to_latlon(pos["x"], pos["y"])
            else:
                lat, lon = float(pos["lat"]), float(pos["lon"])
            out.append((uid, event_xml(uid=uid, cot_type=TYPE_PLAYER, how=HOW_IMAGE if indoor else HOW_GPS, lat=lat,
                                       lon=lon, now=now, start=min(seen, now), stale=stale,
                                       ce=None if indoor else pos.get("accuracy_m"), detail=detail),
                        lat, lon))
        return out

    # --- status ----------------------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        return {"enabled": True, "multicast": self.cfg.atak_multicast or None,
                "staff_endpoints": len(self.cfg.atak_staff_endpoints), "players": bool(self.cfg.atak_players),
                "interval_s": self.cfg.atak_interval_s, "markers": len(self._markers),
                "remote": self.remote is not None, "remote_players": self._remote_players_on(),
                "remote_relay": bool(self.remote is not None and self.remote.atak_relay), **self.stats}
