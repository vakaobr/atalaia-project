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
"""

from __future__ import annotations

import json
import math
import re
import uuid
from typing import Any

from . import chrono

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
    nodes = body["nodes"]
    if not isinstance(nodes, list) or len(nodes) > MAX_NODES:
        _fail("bad_batch_size", "nodes")
    seen = set()
    for i, node in enumerate(nodes):
        path = f"nodes[{i}]"
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
    return body


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
MAX_CLAIMS = 500            # player id claims per answer or body
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


def _answer_envelope(body: Any, required: tuple[str, ...]) -> dict[str, Any]:
    body = _obj(body, "")
    _keys(body, "", ("sync_version", *required))
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


def check_roster(body: Any) -> dict[str, Any]:
    """GET /api/v1/sync/roster's answer: a scheduled game's live registrations, with what the check-in
    list needs and nothing more (ADR-P4-11): the player's id at the field, the display name, the team
    preference, the federation number only when the game asks for one, the ticket's SHA-256 and the
    pre-declared replicas."""
    body = _answer_envelope(body, ("scheduled_game_id", "status", "federation", "registrations"))
    _uuid(body["scheduled_game_id"], "scheduled_game_id")
    if body["status"] not in ROSTER_STATES:
        _fail("bad_state", "status")
    if body["federation"] not in ("off", "optional", "required"):
        _fail("bad_value", "federation")
    regs, players, decls = set(), set(), set()
    for i, r in enumerate(_list(body["registrations"], "registrations", MAX_ROSTER)):
        path = f"registrations[{i}]"
        r = _obj(r, path)
        _keys(r, path, ("registration_id", "player_id", "display_name", "replicas"),
              ("team_preference", "federation_number", "ticket_sha256"))
        _uuid(r["registration_id"], f"{path}.registration_id")
        _text(r["player_id"], f"{path}.player_id", 14, pattern=PLAYER_ID)
        if r["registration_id"] in regs or r["player_id"] in players:
            _fail("duplicate_registration", path)
        regs.add(r["registration_id"])
        players.add(r["player_id"])
        _text(r["display_name"], f"{path}.display_name", 32)
        _text(r.setdefault("team_preference", None), f"{path}.team_preference", SCHEDULE_TEAM_MAX, null=True)
        fed = _text(r.setdefault("federation_number", None), f"{path}.federation_number", 32, null=True)
        if fed is not None and body["federation"] == "off":
            _fail("not_asked", f"{path}.federation_number")
        _text(r.setdefault("ticket_sha256", None), f"{path}.ticket_sha256", 64, null=True, pattern=SHA256_HEX)
        for j, d in enumerate(_list(r["replicas"], f"{path}.replicas", MAX_DECLARATIONS)):
            check_declaration(d, f"{path}.replicas[{j}]")
            if d["declaration_id"] in decls:
                _fail("duplicate_declaration", f"{path}.replicas[{j}].declaration_id")
            decls.add(d["declaration_id"])
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


CHECKS = {"games": check_game, "events": check_events, "scores": check_scores, "nodes": check_nodes,
          "marshals": check_marshals, "replicas": check_replicas, "chrono": check_chrono,
          "checkins": check_checkins, "claims": check_claims}
GAME_KINDS = ("games", "events", "scores", "nodes", "checkins")  # the bodies about one game; the rest are the field's
# The answers of the GET endpoints the controller pulls (plan phase 16).
ANSWERS = {"schedule": check_schedule, "roster": check_roster, "claims": check_claims_list}


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
