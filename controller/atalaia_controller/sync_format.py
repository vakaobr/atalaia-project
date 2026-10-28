# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The controller sync's request bodies (protocol/sync.md): one checker for both sides.

The field controller's sync client (``sync_client.py``) checks every event
before it sends it, and the site server checks every body it receives, with
the same functions, against the same shared vectors
(``protocol/vectors/sync.json``). Plain Python with no third-party imports,
so it runs on the controller's Raspberry Pi OS packages, in the site
server's image and in tools/check.sh (decisions P4R16, P4R17).

Each ``check_*`` function takes the parsed JSON body and returns it
normalised (unknown keys in a node's ``info`` dropped, defaults filled in);
anything else raises ``SyncFormatError`` with a short code and the path of
the first value that is wrong (``events[3].data``), which the site server
returns in its 400 answer.

What never travels (ADR-P4-3's amendment, P4R25): positions (an event whose
data carries a coordinate is refused), tokens and keys (there is no field
for them), check-in names (likewise). Event types are checked by their
form, not against today's list, so a newer controller's events still reach
an older site server.

The field's chrono registry (plan phase 14; ADR-P4-5 as amended, P4R14,
P4R15) travels in three bodies that belong to the field, not to one game,
so they carry no ``game``: the marshals' public keys with their periods
(``check_marshals``; never a private key), the replica registry
(``check_replicas``) and the signed readings with the controller's series
and outcomes (``check_chrono``). A reading's ``record`` is the signed
record's JSON text exactly as the controller stored it: this module checks
only its size; the site server verifies each record on its own with
``chrono.py`` and keeps the ones that fail apart, so one bad record never
refuses a batch.

Game day (plan phase 16; ADR-P4-11): two more bodies the controller pushes,
``check_checkins`` (a scheduled game's registrations' outcomes, after the game:
no names) and ``check_claims`` (its verdicts on accounts' claims of player ids:
no hashes), and the answers of the three endpoints it pulls, in ``ANSWERS``
(``check_schedule``, ``check_roster``, ``check_claims_list``), which the site
server's tests check its own answers with.

Branding (plan phase 18; P4R19): the answer of ``GET /api/v1/sync/field``, the field's branding and
saved teams with their images by SHA-256 (``check_field``, in ``ANSWERS`` too).

The remote GM (plan phase 19; P4R12): the stream's own messages, in ``STREAM``: the controller's ``hello``,
``live`` (its live game: never a position) and ``command.result``, and the site server's ``command``, one
of ``REMOTE_COMMANDS`` (start, pause, resume, end, a GM message, a declared mode command) and nothing else.

The scenario library (plan phase 20): the answers of ``GET /api/v1/sync/presets`` (the field's scenarios by
id, revision and SHA-256, and its game presets: ``check_presets``) and ``GET /api/v1/sync/scenarios/{id}``
(one manifest, its SHA-256 checked: ``check_scenario``), in ``ANSWERS``.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import math
import re
import uuid
import xml.etree.ElementTree as ET
from typing import Any

from . import apd as apdfmt
from . import chrono, images

SYNC_VERSION = 1
MAX_EVENTS = 500            # events per batch
MAX_SOURCES = 1024          # score counter sources per snapshot
MAX_NODES = 512             # nodes per snapshot
MAX_EVENT_DATA = 1024       # bytes of an event's data, as compact JSON
MAX_PARAMS = 8192           # bytes of a game's params, as compact JSON
MAX_BODY = 1024 * 1024      # bytes of a request body
MAX_MARSHALS = 512          # marshal keys per body
MAX_REPLICAS = 500          # replicas per body
MAX_READINGS = 500          # chrono readings per body
MAX_RECORD = 4096           # bytes of a reading's signed record (its JSON text, UTF-8)
TEAM_MAX = 23               # bytes of a team name (the core's ATALAIA_TEAM_NAME_MAX - 1)
TEAMS_MAX = 8
STATES = ("ready", "running", "paused", "ended")
PRIORITIES = ("telemetry", "normal", "critical")
U16 = 0xFFFF
U32 = 0xFFFFFFFF
COUNTER_MAX = 2**31 - 1
TIME_MAX = 2**34            # seconds since 1970: far beyond any real clock

# A standard event name (zone.captured) or a custom one (x.club.name); under 48 bytes (EVENT_TYPE_MAX).
EVENT_TYPE = re.compile(r"[a-z][a-z0-9_]*(\.[a-z0-9][a-z0-9_-]*)+")
EVENT_TYPE_MAX = 47
# A score counter's source: a node's counters (node-3) or one run of a controller's field
# script, qualified by that controller's node id in the game (field-2@0), so two controllers'
# runs never share a key (decision S13-3).
SOURCE = re.compile(r"node-(\d{1,5})|field-(\d{1,6})@(\d{1,5})")
MODE_ID = re.compile(r"[a-z0-9][a-z0-9._+-]{0,127}")
VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+_-]{0,31}")
CREST_ID = re.compile(r"[0-9a-f]{64}")
DATA_KEY = re.compile(r"[a-z][a-z0-9_]{0,31}")
# Keys that would carry a position (P4R25): refused anywhere in an event's data.
POSITION_KEYS = frozenset({"lat", "lon", "lng", "latitude", "longitude", "alt", "altitude", "position",
                           "positions", "gps", "coords", "coordinates", "x", "y"})
# The chrono registry (plan phase 14): as protocol/checkin.md and app/lib/chrono/replica.dart have them.
REPLICA_TYPES = ("aeg", "gbb", "hpa", "bolt_action", "dmr", "sniper", "pistol", "shotgun")
REPLICA_CLASS = re.compile(r"[a-z0-9_]{1,32}")
TAG_NFC = re.compile(r"[0-9A-F]{2}(:[0-9A-F]{2}){3}((:[0-9A-F]{2}){3}){0,2}")
TAG_QR = re.compile(r"[\x21-\x7e]{1,64}")
OUTCOMES = ("pass", "fail", "warn", "unjudged")  # a series' result (checkin.py's _judge)
PUBLIC_KEY_B64 = 44  # 32 bytes in standard base64 with padding
# What a node's info may carry to the site server; anything else is dropped.
NODE_INFO = {
    "owner": "team?", "phase": "int?", "battery_pct": "int?", "rssi": "int?", "snr": "num?", "epoch": "int?",
    "platform": "text?", "fw_version": "text?", "core_version": "text?", "tier": "text?",
    "capabilities": "texts?", "game_time_ms": "int?",
}


class SyncFormatError(ValueError):
    """A body that does not follow protocol/sync.md: ``code`` and the ``path`` of the value."""

    def __init__(self, code: str, path: str = "") -> None:
        super().__init__(f"{code} at {path or 'the body'}")
        self.code = code
        self.path = path


def _fail(code: str, path: str) -> None:
    raise SyncFormatError(code, path)


def _obj(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail("not_an_object", path)
    return value


def _keys(value: dict[str, Any], path: str, required: tuple[str, ...], optional: tuple[str, ...] = ()) -> None:
    for key in required:
        if key not in value:
            _fail("missing", f"{path}.{key}" if path else key)
    for key in value:
        if key not in required and key not in optional:
            _fail("unknown_field", f"{path}.{key}" if path else str(key))


def _int(value: Any, path: str, lo: int, hi: int, null: bool = False) -> Any:
    if value is None and null:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        _fail("not_an_integer", path)
    if not lo <= value <= hi:
        _fail("out_of_range", path)
    return value


def _num(value: Any, path: str, lo: float, hi: float, null: bool = False) -> Any:
    if value is None and null:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        _fail("not_a_number", path)
    if not lo <= value <= hi:
        _fail("out_of_range", path)
    return value


def _text(value: Any, path: str, max_len: int, null: bool = False, pattern: Any = None) -> Any:
    if value is None and null:
        return None
    if not isinstance(value, str) or not value:
        _fail("not_a_text", path)
    if len(value) > max_len or any(ord(c) < 0x20 or 0x7F <= ord(c) <= 0x9F for c in value):
        _fail("bad_text", path)
    if pattern is not None and not pattern.fullmatch(value):
        _fail("bad_text", path)
    return value


def _team(value: Any, path: str, null: bool = False) -> Any:
    if value is None and null:
        return None
    _text(value, path, TEAM_MAX)
    if len(value.encode("utf-8")) > TEAM_MAX:
        _fail("bad_text", path)
    return value


def _json_size(value: Any) -> int:
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def _envelope(body: Any, extra: tuple[str, ...], game: bool = True) -> dict[str, Any]:
    """The common part: ``game`` only in the bodies about one game (not the field's chrono registry)."""
    body = _obj(body, "")
    _keys(body, "", ("sync_version", "controller", *(("game",) if game else ()), *extra))
    if body["sync_version"] != SYNC_VERSION or isinstance(body["sync_version"], bool):
        _fail("unsupported_version", "sync_version")
    ctrl = _obj(body["controller"], "controller")
    _keys(ctrl, "controller", ("id", "version"))
    if not isinstance(ctrl["id"], str):
        _fail("not_a_uuid", "controller.id")
    try:
        parsed = uuid.UUID(ctrl["id"])
    except ValueError:
        parsed = None
    if parsed is None or str(parsed) != ctrl["id"]:
        _fail("not_a_uuid", "controller.id")  # the canonical lower-case form only
    _text(ctrl["version"], "controller.version", 32, pattern=VERSION)
    if not game:
        return body
    ident = _obj(body["game"], "game")
    _keys(ident, "game", ("game_id", "game_seed"))
    _int(ident["game_id"], "game.game_id", 0, U16)
    _int(ident["game_seed"], "game.game_seed", 0, U32)
    return body


def game_key(body: dict[str, Any]) -> tuple[int, int]:
    """The (game_id, game_seed) a checked body is about (P4R11)."""
    return body["game"]["game_id"], body["game"]["game_seed"]


# --- POST /api/v1/sync/games -----------------------------------------------------------

def check_game(body: Any) -> dict[str, Any]:
    body = _envelope(body, ("meta",))
    meta = _obj(body["meta"], "meta")
    _keys(meta, "meta", ("name", "mode_id", "teams", "state", "created_at"),
          ("team_info", "params", "squads", "duration_ms", "node_id", "joined", "started_at", "ended_at",
           "scheduled_game_id"))
    _text(meta["name"], "meta.name", 64)
    _text(meta["mode_id"], "meta.mode_id", 128, pattern=MODE_ID)
    teams = meta["teams"]
    if not isinstance(teams, list) or not 1 <= len(teams) <= TEAMS_MAX:
        _fail("bad_teams", "meta.teams")
    for i, team in enumerate(teams):
        _team(team, f"meta.teams[{i}]")
    if len(set(teams)) != len(teams):
        _fail("bad_teams", "meta.teams")
    info = _obj(meta.setdefault("team_info", {}), "meta.team_info")
    for team, entry in info.items():
        path = f"meta.team_info.{team}"
        if team not in teams:
            _fail("unknown_team", path)
        entry = _obj(entry, path)
        _keys(entry, path, (), ("display_name", "crest_id"))
        _text(entry.get("display_name"), f"{path}.display_name", 32, null=True)
        _text(entry.get("crest_id"), f"{path}.crest_id", 64, null=True, pattern=CREST_ID)
    params = _obj(meta.setdefault("params", {}), "meta.params")
    if _json_size(params) > MAX_PARAMS:
        _fail("too_large", "meta.params")
    _int(meta.setdefault("squads", 0), "meta.squads", 0, 16)
    _int(meta.setdefault("duration_ms", 0), "meta.duration_ms", 0, U32)
    if meta["state"] not in STATES:
        _fail("bad_state", "meta.state")
    _int(meta.setdefault("node_id", None), "meta.node_id", 0, U16 - 1, null=True)
    if not isinstance(meta.setdefault("joined", False), bool):
        _fail("not_a_boolean", "meta.joined")
    _num(meta["created_at"], "meta.created_at", 0, TIME_MAX)
    _num(meta.setdefault("started_at", None), "meta.started_at", 0, TIME_MAX, null=True)
    _num(meta.setdefault("ended_at", None), "meta.ended_at", 0, TIME_MAX, null=True)
    # The site server's scheduled game this game was made from (plan phase 16), if any.
    _text(meta.setdefault("scheduled_game_id", None), "meta.scheduled_game_id", 36, null=True,
          pattern=chrono.UUID_RE)
    return body


# --- POST /api/v1/sync/events ------------------------------------------------------------

def _data(value: Any, path: str, depth: int = 0) -> None:
    if isinstance(value, dict):
        if depth >= 2:
            _fail("too_deep", path)
        for key, item in value.items():
            if not isinstance(key, str) or not DATA_KEY.fullmatch(key):
                _fail("bad_key", f"{path}.{key}")
            if key in POSITION_KEYS:
                _fail("position_not_allowed", f"{path}.{key}")
            _data(item, f"{path}.{key}", depth + 1)
    elif isinstance(value, list):
        if depth >= 2 or len(value) > 32:
            _fail("too_deep", path)
        for i, item in enumerate(value):
            _data(item, f"{path}[{i}]", depth + 1)
    elif isinstance(value, float):
        if not math.isfinite(value):
            _fail("not_a_number", path)
    elif value is not None and not isinstance(value, (str, int)):
        _fail("bad_value", path)  # bool is an int


def check_event(ev: Any, path: str = "event") -> dict[str, Any]:
    """One event as the controller's log holds it (store.events), with its ``id`` in that log."""
    ev = _obj(ev, path)
    _keys(ev, path, ("id", "node", "seq", "t", "type", "prio"), ("team", "squad", "data", "epoch", "pkt_seq"))
    _int(ev["id"], f"{path}.id", 1, 2**63 - 1)
    _int(ev["node"], f"{path}.node", 0, U16)
    _int(ev["seq"], f"{path}.seq", 0, U16)
    _int(ev["t"], f"{path}.t", 0, U32)
    _text(ev["type"], f"{path}.type", EVENT_TYPE_MAX, pattern=EVENT_TYPE)
    if ev["prio"] not in PRIORITIES:
        _fail("bad_priority", f"{path}.prio")
    _team(ev.setdefault("team", None), f"{path}.team", null=True)
    _int(ev.setdefault("squad", None), f"{path}.squad", 0, 255, null=True)
    data = _obj(ev.setdefault("data", {}), f"{path}.data")
    _data(data, f"{path}.data")
    if _json_size(data) > MAX_EVENT_DATA:
        _fail("too_large", f"{path}.data")
    _int(ev.setdefault("epoch", None), f"{path}.epoch", 0, U16, null=True)
    _int(ev.setdefault("pkt_seq", None), f"{path}.pkt_seq", 0, U16, null=True)
    if ev["type"] == "score.delta":
        # A GM's adjustment (P4R10): the site server adds these amounts to the counters' sum.
        _int(data.get("amount"), f"{path}.data.amount", -1_000_000, 1_000_000)
        team = data.get("team", ev["team"])
        _team(team, f"{path}.data.team")
        if ev["team"] is not None and ev["team"] != team:
            _fail("team_mismatch", f"{path}.team")
    return ev


def check_events(body: Any) -> dict[str, Any]:
    body = _envelope(body, ("after_id", "events"))
    after = _int(body["after_id"], "after_id", 0, 2**63 - 1)
    events = body["events"]
    if not isinstance(events, list) or not 1 <= len(events) <= MAX_EVENTS:
        _fail("bad_batch_size", "events")
    last = after
    for i, ev in enumerate(events):
        check_event(ev, f"events[{i}]")
        if ev["id"] <= last:
            _fail("ids_not_increasing", f"events[{i}].id")
        last = ev["id"]
    return body


# --- POST /api/v1/sync/scores ------------------------------------------------------------

def check_scores(body: Any) -> dict[str, Any]:
    body = _envelope(body, ("counters",))
    counters = _obj(body["counters"], "counters")
    if len(counters) > MAX_SOURCES:
        _fail("too_large", "counters")
    for source, teams in counters.items():
        path = f"counters.{source}"
        if not isinstance(source, str) or not SOURCE.fullmatch(source):
            _fail("bad_source", path)
        teams = _obj(teams, path)
        if len(teams) > TEAMS_MAX:
            _fail("bad_teams", path)
        for team, value in teams.items():
            _team(team, f"{path}.{team}")
            _int(value, f"{path}.{team}", 0, COUNTER_MAX)
    return body


# --- POST /api/v1/sync/nodes -------------------------------------------------------------

def _info_value(kind: str, value: Any, path: str) -> Any:
    if value is None:
        return None
    if kind == "team?":
        return _team(value, path)
    if kind == "int?":
        return _int(value, path, -(2**31), 2**32)
    if kind == "num?":
        return _num(value, path, -1e9, 1e9)
    if kind == "text?":
        if isinstance(value, int) and not isinstance(value, bool):
            value = str(value)
        return _text(value, path, 32)
    if not isinstance(value, list) or len(value) > 32:  # texts?
        _fail("bad_value", path)
    return [_text(v, f"{path}[{i}]", 32) for i, v in enumerate(value)]


def check_nodes(body: Any) -> dict[str, Any]:
    body = _envelope(body, ("nodes",))
    _node_list(body["nodes"], "nodes")
    return body


def _node_list(nodes: Any, where: str) -> None:
    if not isinstance(nodes, list) or len(nodes) > MAX_NODES:
        _fail("bad_batch_size", where)
    seen = set()
    for i, node in enumerate(nodes):
        path = f"{where}[{i}]"
        node = _obj(node, path)
        _keys(node, path, ("node_id", "name", "role", "last_seen"), ("info",))
        _int(node["node_id"], f"{path}.node_id", 0, U16)
        if node["node_id"] in seen:
            _fail("duplicate_node", f"{path}.node_id")
        seen.add(node["node_id"])
        _text(node["name"], f"{path}.name", 32)
        _text(node["role"], f"{path}.role", 32)
        _num(node["last_seen"], f"{path}.last_seen", 0, TIME_MAX)
        info = _obj(node.get("info", {}), f"{path}.info")
        node["info"] = {k: _info_value(NODE_INFO[k], v, f"{path}.info.{k}")
                        for k, v in info.items() if k in NODE_INFO}


# --- the chrono registry (plan phase 14) -------------------------------------------------

def _name(value: Any, path: str) -> str:
    """A marshal's name as chrono-record.md has marshal_name: 1-64 characters, no control characters."""
    if not isinstance(value, str) or not 1 <= len(value) <= chrono.NAME_MAX or not chrono._text_ok(value):
        _fail("bad_text", path)
    return value


def public_key_bytes(value: Any, path: str = "public_key") -> bytes:
    """An Ed25519 public key as the sync sends it: 32 bytes in standard base64 with padding."""
    import base64  # noqa: PLC0415
    import binascii  # noqa: PLC0415

    if not isinstance(value, str) or len(value) != PUBLIC_KEY_B64:
        _fail("bad_public_key", path)
    try:
        raw = base64.b64decode(value.encode("ascii"), validate=True)
    except (binascii.Error, UnicodeEncodeError):
        _fail("bad_public_key", path)
    if len(raw) != 32 or base64.b64encode(raw).decode("ascii") != value:
        _fail("bad_public_key", path)
    return raw


def check_marshal(entry: Any, path: str = "marshal") -> dict[str, Any]:
    """One marshal key: ``{marshal_id, name, public_key, registered_at, player_id?, replaced_at?}``.
    ``replaced_at`` null (or absent) is the marshal's current key on the sending controller."""
    entry = _obj(entry, path)
    _keys(entry, path, ("marshal_id", "name", "public_key", "registered_at"), ("player_id", "replaced_at"))
    _text(entry["marshal_id"], f"{path}.marshal_id", 64, pattern=chrono.ID_RE)
    _name(entry["name"], f"{path}.name")
    public_key_bytes(entry["public_key"], f"{path}.public_key")
    _text(entry.setdefault("player_id", None), f"{path}.player_id", 64, null=True, pattern=chrono.ID_RE)
    _num(entry["registered_at"], f"{path}.registered_at", 0, TIME_MAX)
    _num(entry.setdefault("replaced_at", None), f"{path}.replaced_at", 0, TIME_MAX, null=True)
    if entry["replaced_at"] is not None and entry["replaced_at"] < entry["registered_at"]:
        _fail("bad_period", f"{path}.replaced_at")
    return entry


def check_marshals(body: Any) -> dict[str, Any]:
    body = _envelope(body, ("marshals",), game=False)
    marshals = body["marshals"]
    if not isinstance(marshals, list) or not 1 <= len(marshals) <= MAX_MARSHALS:
        _fail("bad_batch_size", "marshals")
    seen: set[tuple[str, str]] = set()
    current: set[str] = set()
    for i, entry in enumerate(marshals):
        path = f"marshals[{i}]"
        check_marshal(entry, path)
        key = (entry["marshal_id"], entry["public_key"])
        if key in seen:
            _fail("duplicate_key", f"{path}.public_key")
        seen.add(key)
        if entry["replaced_at"] is None:
            if entry["marshal_id"] in current:
                _fail("two_current_keys", f"{path}.replaced_at")
            current.add(entry["marshal_id"])
    return body


def check_replica(entry: Any, path: str = "replica") -> dict[str, Any]:
    """One replica of the field's registry, as app/lib/chrono/replica.dart writes it."""
    entry = _obj(entry, path)
    _keys(entry, path, ("replica_id", "owner_player_id", "type", "class"),
          ("make_model", "registered_at", "tag_type", "tag_uid"))
    _text(entry["replica_id"], f"{path}.replica_id", 36, pattern=chrono.UUID_RE)
    _text(entry["owner_player_id"], f"{path}.owner_player_id", 64, pattern=chrono.ID_RE)
    if entry["type"] not in REPLICA_TYPES:
        _fail("bad_type", f"{path}.type")
    _text(entry["class"], f"{path}.class", 32, pattern=REPLICA_CLASS)
    mm = entry.setdefault("make_model", None)
    if mm is not None:
        _name(mm, f"{path}.make_model")
    registered = entry.setdefault("registered_at", None)
    if registered is not None:
        _text(registered, f"{path}.registered_at", 20, pattern=chrono.TIME_RE)
    tag_type, tag_uid = entry.setdefault("tag_type", None), entry.setdefault("tag_uid", None)
    if (tag_type is None) != (tag_uid is None):
        _fail("bad_tag", f"{path}.tag_uid")
    if tag_type is not None:
        if tag_type not in ("nfc", "qr"):
            _fail("bad_tag", f"{path}.tag_type")
        if not isinstance(tag_uid, str) or not (TAG_NFC if tag_type == "nfc" else TAG_QR).fullmatch(tag_uid):
            _fail("bad_tag", f"{path}.tag_uid")
    return entry


def check_replicas(body: Any) -> dict[str, Any]:
    body = _envelope(body, ("replicas",), game=False)
    replicas = body["replicas"]
    if not isinstance(replicas, list) or not 1 <= len(replicas) <= MAX_REPLICAS:
        _fail("bad_batch_size", "replicas")
    seen: set[str] = set()
    for i, entry in enumerate(replicas):
        check_replica(entry, f"replicas[{i}]")
        if entry["replica_id"] in seen:
            _fail("duplicate_replica", f"replicas[{i}].replica_id")
        seen.add(entry["replica_id"])
    return body


def check_reading(entry: Any, path: str = "reading") -> dict[str, Any]:
    """One stored reading: ``{record, series_id, outcome, received_at, game_seed?}``. ``record`` is the
    signed record's JSON text as the controller stored it; its content is the site server's to verify
    (chrono.py), not this check's."""
    entry = _obj(entry, path)
    _keys(entry, path, ("record", "series_id", "outcome", "received_at"), ("game_seed",))
    record = entry["record"]
    if not isinstance(record, str) or not record:
        _fail("not_a_text", f"{path}.record")
    if len(record.encode("utf-8", "surrogatepass")) > MAX_RECORD:
        _fail("too_large", f"{path}.record")
    _text(entry["series_id"], f"{path}.series_id", 36, pattern=chrono.UUID_RE)
    if entry["outcome"] is not None and entry["outcome"] not in OUTCOMES:
        _fail("bad_outcome", f"{path}.outcome")
    _num(entry["received_at"], f"{path}.received_at", 0, TIME_MAX)
    _int(entry.setdefault("game_seed", None), f"{path}.game_seed", 0, U32, null=True)
    return entry


def check_chrono(body: Any) -> dict[str, Any]:
    body = _envelope(body, ("readings",), game=False)
    readings = body["readings"]
    if not isinstance(readings, list) or not 1 <= len(readings) <= MAX_READINGS:
        _fail("bad_batch_size", "readings")
    for i, entry in enumerate(readings):
        check_reading(entry, f"readings[{i}]")
    return body


# --- registration and game-day sync (plan phase 16; ADR-P4-11) ---------------------------
#
# The controller pulls (GET) the field's schedule, the roster of each scheduled game it made a game
# from, and the accounts' claims of player ids; it pushes (POST) each registration's outcome after
# the game and its verdict on each claim. The answers it pulls are checked here too, by the
# controller before it uses them and by the site server's tests before they are sent.

MAX_SCHEDULE = 200          # scheduled games in one schedule answer
MAX_ROSTER = 5000           # registrations in one roster answer or check-ins body (the controller's max_players)
MAX_SHARED = 100            # other fields' records of one player in a shared-chrono answer (the newest)
MAX_CLAIMS = 500           # player id claims per answer or body
MAX_DECLARATIONS = 20       # a registration's pre-declared replicas (the controller's max_replicas bound)
SCHEDULED_STATES = ("published", "in_progress", "completed", "cancelled")
ROSTER_STATES = ("published", "in_progress", "completed", "cancelled")
OUTCOMES_CHECKIN = ("checked_in", "no_show")
DECLARATION_STATES = ("pending", "passed", "refused", "withdrawn")
CLAIM_RESULTS = ("confirmed", "refused", "unknown")
PLAYER_ID = re.compile(r"p-[a-z2-7]{12}")
SHA256_HEX = re.compile(r"[0-9a-f]{64}")
SCHEDULE_TEAM_MAX = 32       # a scheduled game's team names (the site server's limit; a controller game: 23 bytes)


def _uuid(value: Any, path: str, null: bool = False) -> Any:
    return _text(value, path, 36, null=null, pattern=chrono.UUID_RE)


def _bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        _fail("not_a_boolean", path)
    return value


def _list(value: Any, path: str, hi: int, lo: int = 0) -> list[Any]:
    if not isinstance(value, list) or not lo <= len(value) <= hi:
        _fail("bad_batch_size", path)
    return value


def _answer_envelope(body: Any, required: tuple[str, ...], optional: tuple[str, ...] = ()) -> dict[str, Any]:
    body = _obj(body, "")
    _keys(body, "", ("sync_version", *required), optional)
    if body["sync_version"] != SYNC_VERSION or isinstance(body["sync_version"], bool):
        _fail("unsupported_version", "sync_version")
    return body


def check_schedule(body: Any) -> dict[str, Any]:
    """GET /api/v1/sync/schedule's answer: the field's published scheduled games of the coming days."""
    body = _answer_envelope(body, ("games",))
    seen: set[str] = set()
    for i, g in enumerate(_list(body["games"], "games", MAX_SCHEDULE)):
        path = f"games[{i}]"
        g = _obj(g, path)
        _keys(g, path, ("scheduled_game_id", "title", "starts_at", "ends_at", "status", "teams", "federation",
                        "predeclare_replicas", "registered"), ("mode_id", "max_players", "location"))
        _uuid(g["scheduled_game_id"], f"{path}.scheduled_game_id")
        if g["scheduled_game_id"] in seen:
            _fail("duplicate_game", f"{path}.scheduled_game_id")
        seen.add(g["scheduled_game_id"])
        _text(g["title"], f"{path}.title", 256)
        _num(g["starts_at"], f"{path}.starts_at", 0, TIME_MAX)
        _num(g["ends_at"], f"{path}.ends_at", 0, TIME_MAX)
        if g["ends_at"] <= g["starts_at"]:
            _fail("bad_period", f"{path}.ends_at")
        if g["status"] not in SCHEDULED_STATES:
            _fail("bad_state", f"{path}.status")
        teams = _list(g["teams"], f"{path}.teams", 16)
        for j, team in enumerate(teams):
            _text(team, f"{path}.teams[{j}]", SCHEDULE_TEAM_MAX)
        if len(set(teams)) != len(teams):
            _fail("bad_teams", f"{path}.teams")
        if g["federation"] not in ("off", "optional", "required"):
            _fail("bad_value", f"{path}.federation")
        _bool(g["predeclare_replicas"], f"{path}.predeclare_replicas")
        _int(g["registered"], f"{path}.registered", 0, 10000)
        _text(g.setdefault("mode_id", None), f"{path}.mode_id", 128, null=True, pattern=MODE_ID)
        _int(g.setdefault("max_players", None), f"{path}.max_players", 1, 10000, null=True)
        _text(g.setdefault("location", None), f"{path}.location", 512, null=True)
    return body


def check_declaration(d: Any, path: str) -> dict[str, Any]:
    """A pre-declared replica in a roster, as protocol/checkin.md's declarations (no state)."""
    d = _obj(d, path)
    _keys(d, path, ("declaration_id", "type", "class"), ("replica_id", "make_model"))
    _uuid(d["declaration_id"], f"{path}.declaration_id")
    _uuid(d.setdefault("replica_id", None), f"{path}.replica_id", null=True)
    if d["type"] not in REPLICA_TYPES:
        _fail("bad_type", f"{path}.type")
    _text(d["class"], f"{path}.class", 32, pattern=REPLICA_CLASS)
    mm = d.setdefault("make_model", None)
    if mm is not None:
        _name(mm, f"{path}.make_model")
    return d


def check_apd_rule(value: Any, path: str) -> dict[str, Any]:
    """An APD rule (protocol/apd.md), normalised; null is the default rule."""
    try:
        return apdfmt.check_rule(value)
    except apdfmt.ApdError:
        _fail("bad_apd_rule", path)
        raise  # unreachable: _fail raises


def check_roster(body: Any) -> dict[str, Any]:
    """GET /api/v1/sync/roster's answer: a scheduled game's live registrations, with what the check-in
    list needs and nothing more (ADR-P4-11): the player's id at the field, the display name, the team
    preference, the federation number only when the game asks for one, the ticket's SHA-256 and the
    pre-declared replicas."""
    body = _answer_envelope(body, ("scheduled_game_id", "status", "federation", "registrations"), ("apd",))
    _uuid(body["scheduled_game_id"], "scheduled_game_id")
    rule = check_apd_rule(body.get("apd"), "apd")
    if "apd" in body:
        body["apd"] = rule
    asked = body["federation"] != "off" or rule["register"] or rule["checkin"]
    if body["status"] not in ROSTER_STATES:
        _fail("bad_state", "status")
    if body["federation"] not in ("off", "optional", "required"):
        _fail("bad_value", "federation")
    regs, players, decls = set(), set(), set()
    for i, r in enumerate(_list(body["registrations"], "registrations", MAX_ROSTER)):
        path = f"registrations[{i}]"
        r = _obj(r, path)
        _keys(r, path, ("registration_id", "player_id", "display_name", "replicas"),
              ("team_preference", "federation_number", "ticket_sha256", "apd_id", "membership_expires"))
        _uuid(r["registration_id"], f"{path}.registration_id")
        _text(r["player_id"], f"{path}.player_id", 14, pattern=PLAYER_ID)
        if r["registration_id"] in regs or r["player_id"] in players:
            _fail("duplicate_registration", path)
        regs.add(r["registration_id"])
        players.add(r["player_id"])
        _text(r["display_name"], f"{path}.display_name", 32)
        _text(r.setdefault("team_preference", None), f"{path}.team_preference", SCHEDULE_TEAM_MAX, null=True)
        fed = _text(r.setdefault("federation_number", None), f"{path}.federation_number", 32, null=True)
        if fed is not None and not asked:
            _fail("not_asked", f"{path}.federation_number")
        try:
            apdfmt.check_membership({"apd": r.get("apd_id"), "expires": r.get("membership_expires")})
        except apdfmt.ApdError:
            _fail("bad_membership", f"{path}.apd_id")
        if (r.get("apd_id") is not None or r.get("membership_expires") is not None) and not asked:
            _fail("not_asked", f"{path}.apd_id")
        _text(r.setdefault("ticket_sha256", None), f"{path}.ticket_sha256", 64, null=True, pattern=SHA256_HEX)
        for j, d in enumerate(_list(r["replicas"], f"{path}.replicas", MAX_DECLARATIONS)):
            check_declaration(d, f"{path}.replicas[{j}]")
            if d["declaration_id"] in decls:
                _fail("duplicate_declaration", f"{path}.replicas[{j}].declaration_id")
            decls.add(d["declaration_id"])
    return body


def check_shared_chrono(body: Any) -> dict[str, Any]:
    """GET /api/v1/sync/chrono's answer (S14-5): other fields' signed chrono records of the players on a
    scheduled game's roster, only the ones their person consented to share between that field and this one.
    Per player id of this field (each once): 1 to ``MAX_SHARED`` readings, each the signed record as text
    (``MAX_RECORD`` bytes, verified by the controller with the key given: chrono.py), the name of the field
    it was made at (1-128) and the marshal's public key (32 bytes in standard base64). A record once."""
    body = _answer_envelope(body, ("scheduled_game_id", "players"))
    _uuid(body["scheduled_game_id"], "scheduled_game_id")
    players, records = set(), set()
    for i, p in enumerate(_list(body["players"], "players", MAX_ROSTER)):
        path = f"players[{i}]"
        p = _obj(p, path)
        _keys(p, path, ("player_id", "readings"))
        _text(p["player_id"], f"{path}.player_id", 14, pattern=PLAYER_ID)
        if p["player_id"] in players:
            _fail("duplicate_player", path)
        players.add(p["player_id"])
        for j, r in enumerate(_list(p["readings"], f"{path}.readings", MAX_SHARED, 1)):
            rpath = f"{path}.readings[{j}]"
            r = _obj(r, rpath)
            _keys(r, rpath, ("field", "record", "public_key"))
            _text(r["field"], f"{rpath}.field", 128)
            record = r["record"]
            if not isinstance(record, str) or not record:
                _fail("not_a_text", f"{rpath}.record")
            if len(record.encode("utf-8", "surrogatepass")) > MAX_RECORD:
                _fail("too_large", f"{rpath}.record")
            public_key_bytes(r["public_key"], f"{rpath}.public_key")
            if record in records:
                _fail("duplicate_reading", rpath)
            records.add(record)
    return body


def check_claims_list(body: Any) -> dict[str, Any]:
    """GET /api/v1/sync/claims's answer: accounts that claim a player id of this field, each with the
    SHA-256 of the secret their phone holds; the controller compares it with its own (protocol/checkin.md)."""
    body = _answer_envelope(body, ("claims",))
    seen: set[str] = set()
    for i, c in enumerate(_list(body["claims"], "claims", MAX_CLAIMS)):
        path = f"claims[{i}]"
        c = _obj(c, path)
        _keys(c, path, ("claim_id", "player_id", "secret_sha256"))
        _uuid(c["claim_id"], f"{path}.claim_id")
        if c["claim_id"] in seen:
            _fail("duplicate_claim", f"{path}.claim_id")
        seen.add(c["claim_id"])
        _text(c["player_id"], f"{path}.player_id", 14, pattern=PLAYER_ID)
        _text(c["secret_sha256"], f"{path}.secret_sha256", 64, pattern=SHA256_HEX)
    return body


def check_checkins(body: Any) -> dict[str, Any]:
    """POST /api/v1/sync/checkins: after a game made from a scheduled game, each registration's outcome
    and its declarations' final states, and how many walked in (a count only). No names, no federation
    numbers. ``ticket_sha256`` only for a registration the controller did not have in a roster (the app
    sent its registration id and ticket at check-in): the site server compares it with its own."""
    body = _envelope(body, ("scheduled_game_id", "registrations", "walkins"))
    _uuid(body["scheduled_game_id"], "scheduled_game_id")
    _int(body["walkins"], "walkins", 0, 100000)
    seen: set[str] = set()
    for i, r in enumerate(_list(body["registrations"], "registrations", MAX_ROSTER)):
        path = f"registrations[{i}]"
        r = _obj(r, path)
        _keys(r, path, ("registration_id", "player_id", "outcome", "declarations"), ("ticket_sha256",))
        _uuid(r["registration_id"], f"{path}.registration_id")
        if r["registration_id"] in seen:
            _fail("duplicate_registration", f"{path}.registration_id")
        seen.add(r["registration_id"])
        _text(r["player_id"], f"{path}.player_id", 14, pattern=PLAYER_ID)
        if r["outcome"] not in OUTCOMES_CHECKIN:
            _fail("bad_outcome", f"{path}.outcome")
        _text(r.setdefault("ticket_sha256", None), f"{path}.ticket_sha256", 64, null=True, pattern=SHA256_HEX)
        decls = set()
        for j, d in enumerate(_list(r["declarations"], f"{path}.declarations", MAX_DECLARATIONS)):
            dpath = f"{path}.declarations[{j}]"
            d = _obj(d, dpath)
            _keys(d, dpath, ("declaration_id", "state"), ("reading_id",))
            _uuid(d["declaration_id"], f"{dpath}.declaration_id")
            if d["declaration_id"] in decls:
                _fail("duplicate_declaration", f"{dpath}.declaration_id")
            decls.add(d["declaration_id"])
            if d["state"] not in DECLARATION_STATES:
                _fail("bad_state", f"{dpath}.state")
            _uuid(d.setdefault("reading_id", None), f"{dpath}.reading_id", null=True)
    return body


def check_claims(body: Any) -> dict[str, Any]:
    """POST /api/v1/sync/claims: the controller's verdict on each claim it was given: ``confirmed`` (it
    knows the player id with that secret's hash), ``refused`` (it knows the id with another secret, or
    with none: a player checked in by hand) or ``unknown`` (it never saw the id; the claim waits)."""
    body = _envelope(body, ("results",), game=False)
    seen: set[str] = set()
    for i, r in enumerate(_list(body["results"], "results", MAX_CLAIMS, lo=1)):
        path = f"results[{i}]"
        r = _obj(r, path)
        _keys(r, path, ("claim_id", "result"))
        _uuid(r["claim_id"], f"{path}.claim_id")
        if r["claim_id"] in seen:
            _fail("duplicate_claim", f"{path}.claim_id")
        seen.add(r["claim_id"])
        if r["result"] not in CLAIM_RESULTS:
            _fail("bad_value", f"{path}.result")
    return body


# --- branding and saved teams (plan phase 18; P4R19) -----------------------------------------
#
# With ``[sync] branding = "site"`` the controller pulls its field's branding and saved teams
# (``GET /api/v1/sync/field``) and each image it does not have yet by its SHA-256
# (``GET /api/v1/sync/images/{sha256}``), which it checks again with ``images.py`` and the same limits.

MAX_SYNC_TEAMS = 200        # saved teams in one field answer
FIELD_NAME_MAX = 48         # the poster's field name (checkin_poster.FIELD_NAME_MAX, branding.FIELD_NAME_MAX)
TEAM_DISPLAY_MAX = 32       # a team's display name (engine.TEAM_DISPLAY_MAX)
ACCENT = re.compile(r"#[0-9a-f]{6}")
CLUB_SLUG = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,126}[a-z0-9])?")


def check_image_ref(value: Any, path: str, kind: str) -> Any:
    """An image as the field answer names it: its SHA-256, type, size in pixels and bytes, within the limits
    ``images.py`` sets for its kind (logo, wallpaper, crest); or null."""
    if value is None:
        return None
    ref = _obj(value, path)
    _keys(ref, path, ("sha256", "content_type", "width", "height", "bytes"))
    _text(ref["sha256"], f"{path}.sha256", 64, pattern=SHA256_HEX)
    if ref["content_type"] not in images.TYPES:
        _fail("bad_type", f"{path}.content_type")
    lim = images.KINDS[kind]
    _int(ref["width"], f"{path}.width", lim.min_side, lim.max_side)
    _int(ref["height"], f"{path}.height", lim.min_side, lim.max_side)
    _int(ref["bytes"], f"{path}.bytes", 1, lim.max_bytes)
    return ref


LIMIT_ID = re.compile(r"[a-z0-9_]{1,32}")  # a limit template's id: its file name in app/lib/chrono/limit_templates
MAX_LIMIT_CLASSES = 64
LIMIT_CLASS_MAX = 32       # characters of a class's name
LIMIT_NAME_MAX = 64
LIMIT_STATUSES = ("verified", "unverified")  # the template file's status
LIMIT_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")  # its verified_date
FIRE_MODES = ("full_auto", "semi_only", "bolt_only")
FEDERATION_LABEL_MAX = 16  # checkin.federation_label
MAX_REPLICAS_MAX = 20      # checkin.max_replicas


def check_field_settings(value: Any, path: str = "settings") -> Any:
    """The field's check-in rules as the site server keeps them (decision S16-6, BR24): the federation label
    (null: the controller keeps its own), the replicas a player may declare, and the limit template whole (its
    classes with their energy limit), so a controller needs no copy of the template's file. ``null``: the
    site server did not send them."""
    if value is None:
        return None
    st = _obj(value, path)
    _keys(st, path, ("federation_label", "max_replicas", "limit_template"))
    label = _text(st["federation_label"], f"{path}.federation_label", FEDERATION_LABEL_MAX, null=True)
    if label is not None and label != label.strip():
        _fail("bad_text", f"{path}.federation_label")
    _int(st["max_replicas"], f"{path}.max_replicas", 1, MAX_REPLICAS_MAX)
    lt = _obj(st["limit_template"], f"{path}.limit_template")
    lpath = f"{path}.limit_template"
    _keys(lt, lpath, ("id", "name", "classes"), ("status", "verified_date"))
    _text(lt["id"], f"{lpath}.id", 32, pattern=LIMIT_ID)
    status = lt.setdefault("status", None)
    if status is not None and status not in LIMIT_STATUSES:
        _fail("bad_value", f"{lpath}.status")
    verified_date = _text(lt.setdefault("verified_date", None), f"{lpath}.verified_date", 10, null=True,
                          pattern=LIMIT_DATE)
    if status == "verified" and verified_date is None:  # the app's own rule for a verified template
        _fail("bad_value", f"{lpath}.verified_date")
    _text(lt["name"], f"{lpath}.name", LIMIT_NAME_MAX)
    classes = _obj(lt["classes"], f"{lpath}.classes")
    if not 1 <= len(classes) <= MAX_LIMIT_CLASSES:
        _fail("bad_batch_size", f"{lpath}.classes")
    for name, spec in classes.items():
        cpath = f"{lpath}.classes.{name}"
        _text(name, cpath, LIMIT_CLASS_MAX, pattern=REPLICA_CLASS)
        spec = _obj(spec, cpath)
        _keys(spec, cpath, ("max_energy_j", "med_m", "fire_mode"))
        if _num(spec["max_energy_j"], f"{cpath}.max_energy_j", 0, 100) <= 0:
            _fail("out_of_range", f"{cpath}.max_energy_j")
        _int(spec["med_m"], f"{cpath}.med_m", 0, 500, null=True)
        if spec["fire_mode"] not in FIRE_MODES:
            _fail("bad_value", f"{cpath}.fire_mode")
    return st


def check_field(body: Any) -> dict[str, Any]:
    """GET /api/v1/sync/field's answer: the field's branding (name, accent, logo, wallpaper) and its saved teams
    (a display name, the colour they usually play, a crest, the club they are), images by SHA-256; and, only
    when the controller asked for them (``?settings=1``) and the site server knows them, the field's check-in
    ``settings`` (absent otherwise)."""
    body = _answer_envelope(body, ("field", "teams"), ("settings",))
    check_field_settings(body.get("settings"))
    f = _obj(body["field"], "field")
    _keys(f, "field", (), ("field_name", "accent", "logo", "wallpaper", "apd"))
    if "apd" in f:
        f["apd"] = check_apd_rule(f["apd"], "field.apd")
    name = _text(f.setdefault("field_name", None), "field.field_name", FIELD_NAME_MAX, null=True)
    if name is not None and name != name.strip():
        _fail("bad_text", "field.field_name")
    _text(f.setdefault("accent", None), "field.accent", 7, null=True, pattern=ACCENT)
    for slot in ("logo", "wallpaper"):
        check_image_ref(f.setdefault(slot, None), f"field.{slot}", slot)
    ids: set[str] = set()
    names: set[str] = set()
    for i, t in enumerate(_list(body["teams"], "teams", MAX_SYNC_TEAMS)):
        path = f"teams[{i}]"
        t = _obj(t, path)
        _keys(t, path, ("team_id", "name"), ("colour", "crest", "club"))
        _uuid(t["team_id"], f"{path}.team_id")
        if t["team_id"] in ids:
            _fail("duplicate_team", f"{path}.team_id")
        ids.add(t["team_id"])
        _text(t["name"], f"{path}.name", TEAM_DISPLAY_MAX)
        if t["name"] != t["name"].strip():
            _fail("bad_text", f"{path}.name")
        if t["name"] in names:
            _fail("duplicate_team", f"{path}.name")
        names.add(t["name"])
        colour = _team(t.setdefault("colour", None), f"{path}.colour", null=True)
        if colour is not None and " " in colour:
            _fail("bad_text", f"{path}.colour")
        check_image_ref(t.setdefault("crest", None), f"{path}.crest", "crest")
        club = t.setdefault("club", None)
        if club is not None:
            club = _obj(club, f"{path}.club")
            _keys(club, f"{path}.club", ("slug", "name"))
            _text(club["slug"], f"{path}.club.slug", 128, pattern=CLUB_SLUG)
            _text(club["name"], f"{path}.club.name", 128)
    return body


# --- the remote GM on the stream (plan phase 19; P4R12) -------------------------------------
#
# Only with ``[sync] remote_gm = true`` does the controller open ``WS /api/v1/sync/stream`` for the
# remote GM. It sends ``hello`` (whether it takes remote commands), ``live`` (its live game, as the
# console sees it, for a site-server user with the ``gm`` role on the field) and ``command.result``;
# the site server sends ``command``, from the short list below and nothing else. Both sides check
# every message with these functions (``STREAM``), the controller before it acts on a command.

REMOTE_COMMANDS = ("start", "pause", "resume", "end", "message", "mode")
MESSAGE_MAX = 100           # characters of a GM message (the console's limit; the radio's CMD is 127 bytes)
REASON_MAX = 64             # characters of a pause or end reason (the controller's API)
USERNAME_MAX = 64           # the site server's usernames
DETAIL_MAX = 200            # characters of a command result's detail
MISSING_MAX = 16            # roles named in a refused start's ``missing``
ROLE_MAX = 32               # characters of a role's name there (as a live view's node role)
MAX_LIVE_EVENTS = 50        # the live view's latest events
MAX_MODE_COMMANDS = 32
COMMAND_NAME = re.compile(r"[a-z][a-z0-9_]{0,23}")  # a mode command's name (atalaia_sim.mode)
RESULT_CODES = ("done", "remote_gm_off", "invalid", "stale", "not_live", "not_found", "conflict", "unavailable",
                "failed")
TOTAL_MIN, TOTAL_MAX = -(2**40), 2**40  # a live total: counters plus GM adjustments, which may be negative
STALE_S = 60.0              # a command sent longer ago than this (or this far in the future) is refused


def check_hello(body: Any) -> dict[str, Any]:
    """The controller's first message on the stream: whether it takes remote GM commands and, optionally
    (the remote ATAK relay, Phase 4 follow-up FU5), whether it will push its CoT events (``atak``, false
    when absent)."""
    body = _obj(body, "")
    _envelope({k: v for k, v in body.items() if k != "atak"}, ("remote_gm",), game=False)
    _bool(body["remote_gm"], "remote_gm")
    _bool(body.setdefault("atak", False), "atak")
    return body


def check_live(body: Any) -> dict[str, Any]:
    """The controller's live game as its console sees it (null: no live game): never a position, a token,
    a key or a check-in; the nodes and events as the HTTP bodies carry them."""
    body = _envelope(body, ("live",), game=False)
    live = body["live"]
    if live is None:
        return body
    live = _obj(live, "live")
    _keys(live, "live", ("game", "name", "mode_id", "teams", "state", "in_charge", "totals", "nodes", "events"),
          ("game_time_ms", "duration_ms", "mode_commands"))
    ident = _obj(live["game"], "live.game")
    _keys(ident, "live.game", ("game_id", "game_seed"))
    _int(ident["game_id"], "live.game.game_id", 0, U16)
    _int(ident["game_seed"], "live.game.game_seed", 0, U32)
    _text(live["name"], "live.name", 64)
    _text(live["mode_id"], "live.mode_id", 128, pattern=MODE_ID)
    teams = live["teams"]
    if not isinstance(teams, list) or not 1 <= len(teams) <= TEAMS_MAX:
        _fail("bad_teams", "live.teams")
    for i, team in enumerate(teams):
        _team(team, f"live.teams[{i}]")
    if live["state"] not in STATES:
        _fail("bad_state", "live.state")
    _bool(live["in_charge"], "live.in_charge")
    totals = _obj(live["totals"], "live.totals")
    for team, value in totals.items():
        if team not in teams:
            _fail("unknown_team", f"live.totals.{team}")
        _int(value, f"live.totals.{team}", TOTAL_MIN, TOTAL_MAX)
    _int(live.setdefault("game_time_ms", None), "live.game_time_ms", 0, U32, null=True)
    _int(live.setdefault("duration_ms", 0), "live.duration_ms", 0, U32)
    _node_list(live["nodes"], "live.nodes")
    events = _list(live["events"], "live.events", MAX_LIVE_EVENTS)
    for i, ev in enumerate(events):
        check_event(ev, f"live.events[{i}]")
    for i, cmd in enumerate(_list(live.setdefault("mode_commands", []), "live.mode_commands", MAX_MODE_COMMANDS)):
        path = f"live.mode_commands[{i}]"
        cmd = _obj(cmd, path)
        _keys(cmd, path, ("name", "roles"))
        _text(cmd["name"], f"{path}.name", 24, pattern=COMMAND_NAME)
        for j, role in enumerate(_list(cmd["roles"], f"{path}.roles", 16, lo=1)):
            _text(role, f"{path}.roles[{j}]", 32)
    return body


def check_command_params(command: Any, params: Any, path: str = "params") -> dict[str, Any]:
    """A remote command's parameters: an optional ``force`` (boolean, as the console's Start anyway) for start,
    none for resume, an optional reason for pause and end, the
    text of a GM message, the name (and optionally the node: 65535 = every node) of a mode command the
    game's manifests declare (the controller checks that last part against its game)."""
    if command not in REMOTE_COMMANDS:
        _fail("not_allowed", "command")
    params = _obj(params, path)
    if command == "start":
        _keys(params, path, (), ("force",))
        if "force" in params:
            _bool(params["force"], f"{path}.force")
    elif command == "resume":
        _keys(params, path, ())
    elif command in ("pause", "end"):
        _keys(params, path, (), ("reason",))
        reason = params.setdefault("reason", "")
        if reason != "":
            _text(reason, f"{path}.reason", REASON_MAX)
    elif command == "message":
        _keys(params, path, ("text",))
        text = _text(params["text"], f"{path}.text", MESSAGE_MAX)
        if not text.strip():
            _fail("bad_text", f"{path}.text")
    else:  # mode
        _keys(params, path, ("name",), ("node",))
        _text(params["name"], f"{path}.name", 24, pattern=COMMAND_NAME)
        _int(params.setdefault("node", U16), f"{path}.node", 1, U16)
    return params


def check_command(body: Any) -> dict[str, Any]:
    """A remote GM command the site server sends on the stream (without its ``type``): its id, the game it is
    for, the command and its parameters, who asked (the site server's account) and when (the site server's
    clock, seconds since 1970)."""
    body = _obj(body, "")
    _keys(body, "", ("id", "game", "command", "params", "user", "sent_at"))
    _uuid(body["id"], "id")
    ident = _obj(body["game"], "game")
    _keys(ident, "game", ("game_id", "game_seed"))
    _int(ident["game_id"], "game.game_id", 0, U16)
    _int(ident["game_seed"], "game.game_seed", 0, U32)
    if body["command"] not in REMOTE_COMMANDS:
        _fail("not_allowed", "command")
    check_command_params(body["command"], body["params"])
    user = _obj(body["user"], "user")
    _keys(user, "user", ("id", "username"))
    _uuid(user["id"], "user.id")
    _text(user["username"], "user.username", USERNAME_MAX)
    _num(body["sent_at"], "sent_at", 0, TIME_MAX)
    return body


def check_result(body: Any) -> dict[str, Any]:
    """The controller's answer to a command: ``done`` or why not (``RESULT_CODES``), with a short detail and,
    for a ``start`` refused because roles of the game have no joined node (``conflict``), those roles in
    ``missing`` (RG-1: so the site server's page can offer "Start anyway")."""
    body = _obj(body, "")
    _envelope({k: v for k, v in body.items() if k not in ("detail", "missing")}, ("id", "code"), game=False)
    body.setdefault("detail", None)
    _uuid(body["id"], "id")
    if body["code"] not in RESULT_CODES:
        _fail("bad_value", "code")
    _text(body["detail"], "detail", DETAIL_MAX, null=True)
    if "missing" in body:
        if body["code"] != "conflict":
            _fail("bad_value", "missing")
        for i, role in enumerate(_list(body["missing"], "missing", MISSING_MAX, 1)):
            _text(role, f"missing[{i}]", ROLE_MAX)
    return body


# --- the remote ATAK relay (Phase 4 follow-up, decisions FU5-*) ----------------------------------------
# With ``[atak] remote = true`` the controller pushes the CoT events its emitter makes (atak.py) on the stream,
# ``{"type": "cot", sync_version, controller, events: [XML text, ...]}``, and the site server relays them to
# the field's enrolled ATAK clients (TLS with a client certificate). Each event is one CoT ``<event>`` as
# TAK Protocol version 0 carries it: the XML declaration, a newline, the event. Both sides check every event
# with ``cot_event``: the site server parses only this narrow form (no DOCTYPE, entity, comment, CDATA or
# processing instruction, only ``point`` and ``detail`` under the event, Atalaia's own uids) and forwards its
# own serialisation of it, never the controller's bytes. ``MAP_TYPES`` and ``MAP_HOWS`` are what any enrolled
# client may get (the boxes and the extraction zone: spot markers placed by hand); every other event (a
# player's position, its drop) goes only to a certificate allowed to see positions (P4R18).

MAX_COT_EVENTS = 100        # events in one cot message
MAX_COT_BYTES = 2048        # bytes of one event's XML (the emitter's are under 1,400: atak.DATAGRAM_MAX)
COT_DECL = "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>\n"  # atak.XML_DECL
COT_UID = re.compile(r"atalaia\.[A-Za-z0-9._:-]{1,120}")
COT_HOW = re.compile(r"[a-z](-[a-z]){0,4}")
COT_TIME = re.compile(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(\.\d{1,6})?Z")
COT_NUMBER = re.compile(r"-?\d{1,9}(\.\d{1,9})?")
MAP_TYPES = ("b-m-p-s-m",)  # a spot marker (atak.TYPE_PROP, TYPE_ZONE_POINT)
MAP_HOWS = ("h-e", "h-p")   # placed on the image by the GM, pasted from a map app (atak.HOW_IMAGE, HOW_PASTED)
COT_TYPES = (*MAP_TYPES, "a-f-G-U-C")  # and a player (atak.TYPE_PLAYER): nothing else is relayed
# The detail elements the emitter writes (atak.marker_detail, AtakEmitter._players), with no children of their own,
# and each one's attributes and text in the forms the emitter gives them (FU5-17): nothing else passes, so no
# ``contact endpoint``, no free ``usericon`` path, no long remark is relayed to the staff's devices.
COT_DETAILS = ("contact", "remarks", "color", "usericon", "__group", "status")
COT_PLAYER_DETAILS = ("contact", "__group", "remarks")  # AtakEmitter._players: no colour, icon or battery
COT_EVENT_ATTRS = ("version", "uid", "type", "how", "time", "start", "stale")  # atak.event_xml's, no others
COT_CALLSIGN_MAX = 48        # atak.CALLSIGN_MAX
COT_REMARKS_MAX = 160        # atak.REMARKS_MAX
COT_REMARKS_PREFIX = "Atalaia: "
COT_ARGB = re.compile(r"-?[0-9]{1,10}")
COT_BATTERY = re.compile(r"100|[1-9]?[0-9]")
COT_ICONSET = "COT_MAPPING_SPOTMAP/b-m-p-s-m/"  # atak.marker_detail: this prefix and the colour's argb
COT_GROUP_ROLE = "Team Member"  # atak.GROUP_ROLE
COT_TEAMS = ("White", "Yellow", "Orange", "Magenta", "Red", "Maroon", "Purple", "Dark Blue", "Blue", "Cyan",
             "Teal", "Green", "Dark Green", "Brown")  # atak.ATAK_TEAMS
_COT_FORBIDDEN = ("<!", "<?", "&#", "]]>")


def _cot_text(value: Any, limit: int) -> bool:
    """A text as ``atak.xml_text`` leaves it: whitespace folded, at most ``limit`` characters."""
    return isinstance(value, str) and len(value) <= limit and value == " ".join(value.split())


def _argb(value: Any) -> bool:
    return isinstance(value, str) and COT_ARGB.fullmatch(value) is not None and -2**31 <= int(value) < 2**31


def _cot_detail(child: ET.Element, kind: str) -> bool:
    """One detail element as the emitter writes it (``atak.marker_detail``, ``AtakEmitter._players``)."""
    a, tag = child.attrib, child.tag
    if tag != "remarks" and child.text:
        return False
    if kind not in MAP_TYPES and tag not in COT_PLAYER_DETAILS:
        return False
    if tag == "contact":
        return set(a) == {"callsign"} and _cot_text(a["callsign"], COT_CALLSIGN_MAX) and a["callsign"] != ""
    if tag == "remarks":
        text = child.text or ""
        return not a and _cot_text(text, COT_REMARKS_MAX) and text.startswith(COT_REMARKS_PREFIX)
    if tag == "color":
        return set(a) == {"argb"} and _argb(a["argb"])
    if tag == "usericon":
        path = a.get("iconsetpath", "")
        return set(a) == {"iconsetpath"} and path.startswith(COT_ICONSET) and _argb(path[len(COT_ICONSET):])
    if tag == "__group":
        return set(a) == {"name", "role"} and a["name"] in COT_TEAMS and a["role"] == COT_GROUP_ROLE
    if tag == "status":
        return set(a) == {"battery"} and COT_BATTERY.fullmatch(a["battery"]) is not None
    return False


def _cot_time(value: Any, path: str) -> float:
    m = COT_TIME.fullmatch(value) if isinstance(value, str) else None
    if m is None:
        _fail("bad_time", path)
    y, mo, d, h, mi, s = (int(g) for g in m.groups()[:6])
    if not (1970 <= y <= 2500 and 1 <= mo <= 12 and 1 <= d <= 31 and h <= 23 and mi <= 59 and s <= 60):
        _fail("bad_time", path)
    return calendar.timegm((y, mo, d, h, mi, s)) + float(m.group(7) or 0)


def cot_event(text: Any, path: str = "event") -> dict[str, Any]:
    """One CoT event as the emitter makes it, checked: ``{uid, type, how, start, stale, map, xml}``, ``map``
    true for what any enrolled ATAK client may see (``MAP_TYPES`` placed by hand), ``xml`` the event
    serialised again by this module (the declaration, a newline, the event)."""
    if not isinstance(text, str) or not text.startswith(COT_DECL):
        _fail("not_cot", path)
    if len(text.encode("utf-8")) > MAX_COT_BYTES:
        _fail("too_large", path)
    body = text[len(COT_DECL):]
    if any(bad in body for bad in _COT_FORBIDDEN):
        _fail("not_cot", path)  # no DOCTYPE, entity, CDATA, comment or second processing instruction
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        _fail("not_cot", path)
    if root.tag != "event" or root.get("version") != "2.0":
        _fail("not_cot", path)
    if set(root.attrib) - set(COT_EVENT_ATTRS):
        _fail("unknown_field", path)
    uid, kind, how = root.get("uid"), root.get("type"), root.get("how")
    if not isinstance(uid, str) or not COT_UID.fullmatch(uid):
        _fail("bad_uid", f"{path}.uid")
    if kind not in COT_TYPES:
        _fail("bad_type", f"{path}.type")
    if not isinstance(how, str) or not COT_HOW.fullmatch(how):
        _fail("bad_how", f"{path}.how")
    _cot_time(root.get("time"), f"{path}.time")
    start = _cot_time(root.get("start"), f"{path}.start")
    stale = _cot_time(root.get("stale"), f"{path}.stale")
    children = list(root)
    if [c.tag for c in children] != ["point", "detail"] or (root.text or "").strip():
        _fail("not_cot", path)
    point = children[0]
    if set(point.attrib) != {"lat", "lon", "hae", "ce", "le"} or len(point):
        _fail("bad_point", f"{path}.point")
    for key in ("lat", "lon", "hae", "ce", "le"):
        if not COT_NUMBER.fullmatch(point.get(key, "")):
            _fail("bad_point", f"{path}.point.{key}")
    if not (-90.0 <= float(point.get("lat")) <= 90.0 and -180.0 <= float(point.get("lon")) <= 180.0):
        _fail("bad_point", f"{path}.point")
    if (children[1].text or "").strip() or children[1].attrib:
        _fail("bad_detail", f"{path}.detail")
    seen: set[str] = set()
    for child in children[1]:
        if child.tag not in COT_DETAILS or len(child) or (child.tail or "").strip() or child.tag in seen:
            _fail("bad_detail", f"{path}.detail")
        seen.add(child.tag)
        if not _cot_detail(child, kind):
            _fail("bad_detail", f"{path}.detail.{child.tag}")
    xml = COT_DECL + ET.tostring(root, encoding="unicode", short_empty_elements=True)
    return {"uid": uid, "type": kind, "how": how, "start": start, "stale": stale,
            "map": kind in MAP_TYPES and how in MAP_HOWS, "xml": xml}


def check_cot(body: Any) -> dict[str, Any]:
    """The controller's CoT events for the remote ATAK relay: 1-100, each checked by ``cot_event``."""
    body = _envelope(body, ("events",), game=False)
    events = _list(body["events"], "events", MAX_COT_EVENTS, lo=1)
    for i, text in enumerate(events):
        cot_event(text, f"events[{i}]")
    return body


# The stream's own messages (``type`` taken out): what the controller sends, and the command it gets.
def check_field_changed(body: Any) -> dict[str, Any]:
    """The site server's note that the field's branding, saved teams or check-in settings changed (it carries
    nothing else): the controller pulls ``GET /api/v1/sync/field`` at once instead of at its next cycle."""
    body = _obj(body, "")
    _keys(body, "", ("sync_version",))
    if body["sync_version"] != SYNC_VERSION or isinstance(body["sync_version"], bool):
        _fail("unsupported_version", "sync_version")
    return body


STREAM = {"hello": check_hello, "live": check_live, "command.result": check_result, "command": check_command,
          "cot": check_cot, "field.changed": check_field_changed}


# --- the scenario library and presets (plan phase 20) -------------------------------------
# The controller pulls the field's library (``GET /api/v1/sync/presets``): each scenario's id, revision and
# the SHA-256 of its manifest, and the field's game presets whole; then each scenario whose manifest it has
# not installed yet (``GET /api/v1/sync/scenarios/{id}``), which it compiles and checks again in its core.

MAX_LIBRARY = 200            # scenarios, and presets, in one presets answer
MANIFEST_MAX = 256 * 1024    # bytes of a manifest (scenarios.manifest.MANIFEST_MAX_BYTES)
PRESET_NAME_MAX = 64         # a controller preset's name (api.py's save_preset)
SCENARIO_ID = re.compile(r"[a-z0-9][a-z0-9_-]*(\.[a-z0-9][a-z0-9_-]*)+")
SCENARIO_ID_MAX = 40         # a scenario's id leads a game's mode id: 63 - len("+org.atalaia.objectives")
REVISION_MAX = 2**31 - 1


def _scenario_ref(s: dict[str, Any], path: str) -> dict[str, Any]:
    def at(key: str) -> str:
        return f"{path}.{key}" if path else key
    _text(s["scenario_id"], at("scenario_id"), SCENARIO_ID_MAX, pattern=SCENARIO_ID)
    _int(s["revision"], at("revision"), 1, REVISION_MAX)
    _text(s["sha256"], at("sha256"), 64, pattern=SHA256_HEX)
    return s


def check_presets(body: Any) -> dict[str, Any]:
    """GET /api/v1/sync/presets' answer: the field's scenarios (id, revision, version, name, the SHA-256 of the
    manifest's UTF-8 text) and its game presets (id, name, mode id, parameters)."""
    body = _answer_envelope(body, ("scenarios", "presets"))
    ids: set[str] = set()
    for i, s in enumerate(_list(body["scenarios"], "scenarios", MAX_LIBRARY)):
        path = f"scenarios[{i}]"
        s = _obj(s, path)
        _keys(s, path, ("scenario_id", "revision", "version", "name", "sha256"))
        _scenario_ref(s, path)
        if s["scenario_id"] in ids:
            _fail("duplicate_scenario", f"{path}.scenario_id")
        ids.add(s["scenario_id"])
        _text(s["version"], f"{path}.version", 32)
        _text(s["name"], f"{path}.name", 128)
    names: set[str] = set()
    presets: set[str] = set()
    for i, p in enumerate(_list(body["presets"], "presets", MAX_LIBRARY)):
        path = f"presets[{i}]"
        p = _obj(p, path)
        _keys(p, path, ("preset_id", "name", "mode_id", "params"))
        _uuid(p["preset_id"], f"{path}.preset_id")
        if p["preset_id"] in presets:
            _fail("duplicate_preset", f"{path}.preset_id")
        presets.add(p["preset_id"])
        _text(p["name"], f"{path}.name", PRESET_NAME_MAX)
        if p["name"] != p["name"].strip():
            _fail("bad_text", f"{path}.name")
        if p["name"] in names:
            _fail("duplicate_preset", f"{path}.name")
        names.add(p["name"])
        _text(p["mode_id"], f"{path}.mode_id", 128, pattern=MODE_ID)
        _obj(p["params"], f"{path}.params")
        if _json_size(p["params"]) > MAX_PARAMS:
            _fail("too_large", f"{path}.params")
    return body


def check_scenario(body: Any) -> dict[str, Any]:
    """GET /api/v1/sync/scenarios/{id}'s answer: the scenario's current manifest, as it was saved (YAML or JSON
    text, at most 256 KiB), whose UTF-8 bytes must hash to ``sha256``."""
    body = _answer_envelope(body, ("scenario_id", "revision", "sha256", "manifest"))
    _scenario_ref(body, "")
    manifest = body["manifest"]
    if not isinstance(manifest, str) or not manifest.strip():
        _fail("not_a_text", "manifest")
    raw = manifest.encode("utf-8", "surrogatepass")
    if len(raw) > MANIFEST_MAX:
        _fail("too_large", "manifest")
    if hashlib.sha256(raw).hexdigest() != body["sha256"]:
        _fail("sha256_mismatch", "sha256")
    return body


def library_removals(state: dict[str, Any], answer: dict[str, Any]) -> dict[str, list[str]]:
    """What the site's library no longer lists (decision S20-8). ``state`` is what the controller installed from
    the site (``{"scenarios": {id: sha256}, "presets": {name: digest}}``), ``answer`` a checked ``presets`` answer.
    A ``presets`` answer is the field's whole library (a check fails past 200, never a part), so a scenario
    archived or a preset deleted on the site is one the state names and the answer does not: ``{"scenarios":
    [ids], "presets": [names]}``, each sorted. Only candidates: the controller keeps what a game uses and what
    the GM replaced (protocol/sync.md)."""
    ids = {s["scenario_id"] for s in answer["scenarios"]}
    names = {p["name"] for p in answer["presets"]}
    return {"scenarios": sorted(i for i in state.get("scenarios") or {} if i not in ids),
            "presets": sorted(n for n in state.get("presets") or {} if n not in names)}


CHECKS = {"games": check_game, "events": check_events, "scores": check_scores, "nodes": check_nodes,
          "marshals": check_marshals, "replicas": check_replicas, "chrono": check_chrono,
          "checkins": check_checkins, "claims": check_claims}
GAME_KINDS = ("games", "events", "scores", "nodes", "checkins")  # the bodies about one game; the rest are the field's
# The answers of the GET endpoints the controller pulls (plan phases 16, 18 and 20).
ANSWERS = {"schedule": check_schedule, "roster": check_roster, "shared_chrono": check_shared_chrono, "claims": check_claims_list, "field": check_field,
           "presets": check_presets, "scenario": check_scenario}


def parse(kind: str, raw: bytes) -> dict[str, Any]:
    """Parses and checks a request body of one kind (games, events, scores, nodes, marshals, replicas,
    chrono, checkins, claims)."""
    if len(raw) > MAX_BODY:
        _fail("too_large", "")
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        _fail("not_json", "")
    return CHECKS[kind](body)


# --- the merge (P4R10) ------------------------------------------------------------------

def merge_counters(stored: dict[str, dict[str, int]], incoming: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
    """Each (source, team) counter keeps the largest value it was ever reported with."""
    out = {s: dict(t) for s, t in stored.items()}
    for source, teams in incoming.items():
        row = out.setdefault(source, {})
        for team, value in teams.items():
            row[team] = max(row.get(team, 0), value)
    return out


def totals(teams: list[str], counters: dict[str, dict[str, int]], deltas: list[tuple[str, int]]) -> dict[str, int]:
    """A game's totals as the controller's FieldController.total_scores makes them: the sum of the
    counters per team plus every GM adjustment (score.delta), which may be negative."""
    out = {t: 0 for t in teams}
    for row in counters.values():
        for team, value in row.items():
            out[team] = out.get(team, 0) + value
    for team, amount in deltas:
        out[team] = out.get(team, 0) + amount
    return out
