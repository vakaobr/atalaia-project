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
  never by name (decision M9-6).

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

from . import georef as georefmod

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
                 udp: Optional[Any] = None, tcp: Optional[Any] = None) -> None:
        self.cfg = cfg
        self.ctrl = controller
        self._wall = wall
        # The UDP socket is opened on the first send and closed by stop() (it is opened again if the
        # emitter sends after that), so building an emitter that never runs leaks nothing.
        self._udp_given = udp
        self.udp: Optional[Any] = udp
        self.tcp = tcp if tcp is not None else (TcpSender(cfg.atak_staff_endpoints)
                                                if cfg.atak_staff_endpoints else None)
        self._lock = threading.Lock()
        self._send_lock = threading.Lock()  # sending and closing the sockets
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._dirty: set[int] = set()
        self._all = True
        self._end: Optional[int] = None          # a game that ended: drop its markers
        self._owner_hint: dict[int, Optional[str]] = {}
        self._sent_owner: dict[int, Optional[str]] = {}
        self._markers: dict[str, tuple[str, float, float]] = {}  # uid -> (type, lat, lon), on UDP
        self._staff_markers: dict[str, tuple[str, float, float]] = {}
        self._next_players = 0.0
        self.stats: dict[str, Any] = {"udp_events": 0, "tcp_events": 0, "errors": 0, "last_error": None,
                                      "last_sent_at": None, "no_georef": False}
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
            if self._players_on():
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
                else:
                    wake = False
            elif kind == "position" and isinstance(msg.get("node_id"), int):
                self._dirty.add(msg["node_id"])
            elif kind == "game":
                game = msg.get("game") or {}
                if game.get("state") == "ended" and isinstance(game.get("id"), int):
                    self._end = game["id"]
                self._all = True
            elif kind in ("field_georef", "field_image"):
                self._all = True
            else:
                wake = False
        if wake:
            self._wake.set()

    def _players_on(self) -> bool:
        return bool(self.cfg.atak_players and self.tcp is not None)

    # --- one cycle -----------------------------------------------------------------------------

    def cycle(self, full: bool = True) -> dict[str, int]:
        """Sends what is due; returns the number of events sent per transport (tests call it)."""
        with self._lock:
            dirty, self._dirty = self._dirty, set()
            everything = full or self._all
            self._all = False
            ended, self._end = self._end, None
            hints = dict(self._owner_hint)
        now = self._wall()
        udp_out: list[bytes] = []
        tcp_out: list[bytes] = []
        if ended is not None:
            udp_out += self._drops(self._markers, now)
            tcp_out += self._drops(self._staff_markers, now)
        game = self._live_game()
        geo = georefmod.load(self.ctrl.store) if game is not None else None
        self.stats["no_georef"] = game is not None and geo is None
        if game is not None and geo is not None:
            props = self._props(game, geo, now, hints, None if everything else dirty)
            udp_out += props
            tcp_out += props
        else:
            # No live game here or no georeference any more: what ATAK shows is no longer true.
            udp_out += self._drops(self._markers, now)
            tcp_out += self._drops(self._staff_markers, now)
        if game is not None and self._players_on() and (everything or now >= self._next_players):
            tcp_out += self._players(game, now)
            self._next_players = now + self._player_interval(game)
        return self._send(udp_out, tcp_out, now)

    def _send(self, udp_out: list[bytes], tcp_out: list[bytes], now: float) -> dict[str, int]:
        out = {"udp": 0, "tcp": 0}
        with self._send_lock:
            udp = self._udp_sender() if udp_out else None
            if udp is not None:
                try:
                    out["udp"] = udp.send(udp_out)
                    self.stats["udp_events"] += out["udp"]
                except OSError as exc:
                    self._error(f"UDP {self.cfg.atak_multicast}: {exc}")
            sent, errors = self.tcp.send(tcp_out) if self.tcp is not None and tcp_out else (0, [])
        if sent or errors:
            out["tcp"] = sent
            self.stats["tcp_events"] += sent
            for e in errors:
                self._error(f"TCP {e}")
        if out["udp"] or out["tcp"]:
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

    def _props(self, game: dict[str, Any], geo: georefmod.Georef, now: float, hints: dict[int, Optional[str]],
               only: Optional[set[int]]) -> list[bytes]:
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
            node = nodes.get(nid, {})
            owner = hints[nid] if nid in hints else node.get("owner")
            lat, lon = geo.to_latlon(place["x"], place["y"])
            uid = self._uid("node", nid)
            name = node.get("name") or f"{nid}"
            remarks = f"Atalaia: {self._display(game, owner)}" if owner else "Atalaia: -"
            data = event_xml(uid=uid, cot_type=TYPE_PROP, how=HOW_IMAGE, lat=lat, lon=lon, now=now, start=now,
                             stale=stale, detail=marker_detail(name, remarks, team_colour(owner, teams),
                                                               node.get("battery_pct"), atak_team(owner)))
            out.append(data)
            self._sent_owner[nid] = owner
            self._markers[uid] = (TYPE_PROP, lat, lon)
            self._staff_markers[uid] = (TYPE_PROP, lat, lon)
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
        self._markers[uid] = (TYPE_ZONE_POINT, where[0], where[1])
        self._staff_markers[uid] = (TYPE_ZONE_POINT, where[0], where[1])
        return [data]

    def _player_interval(self, game: dict[str, Any]) -> float:
        from .positions import Positions  # noqa: PLC0415

        return float(Positions.interval(game))

    def _players(self, game: dict[str, Any], now: float) -> list[bytes]:
        """Staff endpoints only, never UDP: every GPS position of the live game (staff see all)."""
        teams = list(game.get("teams") or [])
        interval = self._player_interval(game)
        out: list[bytes] = []
        for pid, pos in sorted(self.ctrl.store.player_positions(game["id"]).items()):
            if pos.get("source") != "gps" or pos.get("lat") is None or pos.get("lon") is None:
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
            detail.append(_el("remarks", None, xml_text(f"Atalaia: {self._display(game, team) or '-'}, {role}",
                                                         REMARKS_MAX, REMARKS_BYTES)))
            uid = self._uid("player", pid)
            out.append(event_xml(uid=uid, cot_type=TYPE_PLAYER, how=HOW_GPS, lat=float(pos["lat"]),
                                 lon=float(pos["lon"]), now=now, start=min(seen, now), stale=stale,
                                 ce=pos.get("accuracy_m"), detail=detail))
            self._staff_markers[uid] = (TYPE_PLAYER, float(pos["lat"]), float(pos["lon"]))
        return out

    # --- status ----------------------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        return {"enabled": True, "multicast": self.cfg.atak_multicast or None,
                "staff_endpoints": len(self.cfg.atak_staff_endpoints), "players": bool(self.cfg.atak_players),
                "interval_s": self.cfg.atak_interval_s, "markers": len(self._markers), **self.stats}
