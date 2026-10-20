# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""SQLite store: games, presets, mode packages, node registry, event log (ADR-P2-9).

The events table is the merged log. Its UNIQUE key makes storing an event
idempotent, so flood copies and replays after a partition or a reboot are
dropped by INSERT OR IGNORE. A box restarts its event seq at 1 after a
reboot, so the key is (game, node, seq, game time, type), not
(game, node, seq) as first sketched in ADR-P2-9.

Schema 2 (plan phase E) adds each game's radio identity (this controller's
node id, the channel and the relay clamp, and whether the game was joined
as a standby controller), the field image and the node positions on it.
A schema 1 file is upgraded in place.

Schema 3 (phase 3, plan phase E; ADR-P3-13) adds field check-in: the
per-game player-token keys (the controller's own, decision B8: they never
leave this file), the field's player identities (an id and the SHA-256 of
its secret), check-ins with their few personal fields, the per-game replica
declarations, the field's replica registry, the signed chrono readings,
the marshals' public keys, and the players' latest positions (deleted when
the game ends, ADR-P3-6). The file is created with mode 0600, and so are
SQLite's WAL and shared-memory files next to it, because it holds tokens,
token keys and (with persist_game_key) game keys.

Schema 4 adds field and team branding (decisions BR1-BR24): the uploaded
images (the field's logo and wallpaper and the teams' crests, stored once
by the SHA-256 of their checked bytes), the saved team presets, and each
game's team display names and crests (games.team_info_json).

Schema 5 (phase 4, plan phase 13; ADR-P4-3's amendment, decision P4R11) adds
``sync_state``: per game, the last ``events.id`` the site server acknowledged
(the sync client's push cursor) and the hashes of the game's metadata, score
counters and nodes as last sent, so a cycle sends only what changed.

Schema 6 (phase 4, plan phase 14; ADR-P4-5 as amended, decision P4R14) adds
``marshal_key_history``: a marshal's earlier public keys with the time each
was replaced, so readings signed before a key rotation still verify on the
site server (``marshal_keys`` keeps one current key per marshal, as before);
and ``sync_items``: what the sync client last sent of the field's chrono
registry (each marshal key's and replica's hash, each reading's id), so a
cycle sends only what is new or changed.

Schema 7 (phase 4, plan phase 16; ADR-P4-11) adds game-day sync with a site server:
``schedule_games`` (the field's published games as last pulled), ``schedule_links`` (which
controller game was made from which scheduled game, and its roster's last pull), and on
``checkins`` the registration a check-in belongs to (``registration_id``, the SHA-256 of its
ticket, ``from_roster``) next to a new status, ``expected``: a registered player who has not
arrived yet. A schema 6 file is upgraded in place.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

SCHEMA_VERSION = 7
FIELD_IMAGE_MAX = 4 * 1024 * 1024  # bytes

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS modes (
    id           TEXT PRIMARY KEY,
    version      TEXT NOT NULL,
    files_json   TEXT NOT NULL,
    installed_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS presets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    mode_id     TEXT NOT NULL,
    params_json TEXT NOT NULL,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS games (
    id               INTEGER PRIMARY KEY,          -- the 16-bit game_id on the radio
    name             TEXT NOT NULL,
    mode_id          TEXT NOT NULL,
    preset_id        INTEGER,
    teams_json       TEXT NOT NULL,
    params_json      TEXT NOT NULL,
    assignments_json TEXT NOT NULL,
    duration_ms      INTEGER NOT NULL,
    game_seed        INTEGER NOT NULL,
    state            TEXT NOT NULL,                -- ready, running, paused, ended
    term             INTEGER NOT NULL DEFAULT 1,
    game_key         BLOB,                         -- only with persist_game_key
    created_at       REAL NOT NULL,
    started_at       REAL,
    ended_at         REAL
);
CREATE TABLE IF NOT EXISTS nodes (
    game_id    INTEGER NOT NULL,
    node_id    INTEGER NOT NULL,
    name       TEXT NOT NULL,
    role       TEXT NOT NULL,
    info_json  TEXT NOT NULL,
    last_seen  REAL NOT NULL,
    PRIMARY KEY (game_id, node_id)
);
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id     INTEGER NOT NULL,
    node_id     INTEGER NOT NULL,
    seq         INTEGER NOT NULL,
    game_time   INTEGER NOT NULL,
    type        TEXT NOT NULL,
    team        TEXT,
    squad       INTEGER,
    priority    TEXT NOT NULL,
    data_json   TEXT NOT NULL,
    epoch       INTEGER,
    pkt_seq     INTEGER,
    received_at REAL NOT NULL,
    UNIQUE (game_id, node_id, seq, game_time, type)
);
CREATE INDEX IF NOT EXISTS idx_events_game_time ON events (game_id, game_time);
CREATE TABLE IF NOT EXISTS scores (
    game_id INTEGER NOT NULL,
    team    TEXT NOT NULL,
    score   INTEGER NOT NULL,
    PRIMARY KEY (game_id, team)
);
CREATE TABLE IF NOT EXISTS field_image (
    id           INTEGER PRIMARY KEY CHECK (id = 1),   -- one image per field
    content_type TEXT NOT NULL,
    data         BLOB NOT NULL,
    updated_at   REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS positions (
    game_id INTEGER NOT NULL,
    node_id INTEGER NOT NULL,
    x       REAL NOT NULL,                             -- 0..1 across the field image
    y       REAL NOT NULL,                             -- 0..1 down the field image
    PRIMARY KEY (game_id, node_id)
);
CREATE TABLE IF NOT EXISTS token_keys (
    game_id    INTEGER PRIMARY KEY,
    key        BLOB NOT NULL,                          -- 32 random bytes, never sent anywhere
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS field_players (
    player_id      TEXT PRIMARY KEY,                   -- p- and 12 base32 characters
    secret_sha256  BLOB,                               -- NULL: checked in by hand (no app)
    created_at     REAL NOT NULL,
    last_seen_at   REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS checkins (
    game_id           INTEGER NOT NULL,
    player_id         TEXT NOT NULL,
    status            TEXT NOT NULL,                   -- expected (schema 7), pending, checked_in, left, removed
    display_name      TEXT,                            -- personal data: erased after retention
    federation_number TEXT,
    federation_seen   INTEGER NOT NULL DEFAULT 0,
    team_preference   TEXT,
    team              INTEGER NOT NULL DEFAULT 0,      -- 1-based team id, 0 none
    squad             INTEGER NOT NULL DEFAULT 0,
    role              TEXT NOT NULL DEFAULT 'player',
    manual            INTEGER NOT NULL DEFAULT 0,
    notice_version    INTEGER,
    seq               INTEGER NOT NULL,                -- check-in order
    created_at        REAL NOT NULL,
    updated_at        REAL NOT NULL,
    checked_in_at     REAL,
    erased_at         REAL,
    PRIMARY KEY (game_id, player_id)
);
CREATE TABLE IF NOT EXISTS declarations (
    declaration_id TEXT PRIMARY KEY,
    game_id        INTEGER NOT NULL,
    player_id      TEXT NOT NULL,
    replica_id     TEXT,
    type           TEXT NOT NULL,
    class          TEXT NOT NULL,
    make_model     TEXT,
    state          TEXT NOT NULL,                      -- pending, passed, refused, withdrawn
    reading_id     TEXT,
    position       INTEGER NOT NULL,
    created_at     REAL NOT NULL,
    updated_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_declarations_game ON declarations (game_id, player_id);
CREATE TABLE IF NOT EXISTS replicas (
    replica_id      TEXT PRIMARY KEY,
    owner_player_id TEXT NOT NULL,
    data_json       TEXT NOT NULL,
    registered_at   REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS chrono_readings (
    reading_id  TEXT PRIMARY KEY,
    replica_id  TEXT NOT NULL,
    player_id   TEXT NOT NULL,
    marshal_id  TEXT NOT NULL,
    type        TEXT NOT NULL,
    game_id     TEXT,
    timestamp   TEXT NOT NULL,
    record_json TEXT NOT NULL,                         -- the signed record, as received
    series_id   TEXT NOT NULL,
    outcome     TEXT,                                  -- the series' result when it was judged
    received_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_readings_replica ON chrono_readings (replica_id, player_id);
CREATE TABLE IF NOT EXISTS marshal_keys (
    marshal_id    TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    public_key    BLOB NOT NULL,
    player_id     TEXT,
    registered_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS marshal_key_history (
    marshal_id    TEXT NOT NULL,                       -- schema 6: keys a marshal had before the current one
    name          TEXT NOT NULL,
    public_key    BLOB NOT NULL,
    player_id     TEXT,
    registered_at REAL NOT NULL,
    replaced_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_marshal_key_history ON marshal_key_history (marshal_id);
CREATE TABLE IF NOT EXISTS sync_items (
    kind    TEXT NOT NULL,                             -- schema 6: marshal, replica, reading; 7: checkins
    item_id TEXT NOT NULL,
    sha     TEXT NOT NULL,                             -- SHA-256 of what was sent (readings: their id)
    PRIMARY KEY (kind, item_id)
);
CREATE TABLE IF NOT EXISTS images (
    id           TEXT PRIMARY KEY,                     -- SHA-256 of data, hex
    kind         TEXT NOT NULL,                        -- logo, wallpaper, crest (as first uploaded)
    content_type TEXT NOT NULL,
    width        INTEGER NOT NULL,
    height       INTEGER NOT NULL,
    data         BLOB NOT NULL,                        -- checked, metadata stripped (images.py)
    created_at   REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS team_presets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,                  -- the team's display name
    colour      TEXT,                                  -- the colour it usually plays (red, blue...)
    crest_id    TEXT,                                  -- images.id
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sync_state (
    game_id    INTEGER NOT NULL,
    game_seed  INTEGER NOT NULL,
    acked_id   INTEGER NOT NULL DEFAULT 0,             -- the last events.id the site server acknowledged
    meta_sha   TEXT,                                   -- SHA-256 of what was last sent, per kind
    scores_sha TEXT,
    nodes_sha  TEXT,
    skipped    INTEGER NOT NULL DEFAULT 0,             -- events not sent: not in protocol/sync.md's form
    final      INTEGER NOT NULL DEFAULT 0,             -- 1: an ended game, everything acknowledged
    last_ok_at REAL,
    last_error TEXT,
    PRIMARY KEY (game_id, game_seed)
);
CREATE TABLE IF NOT EXISTS schedule_games (
    scheduled_game_id TEXT PRIMARY KEY,                -- schema 7: the site server's scheduled game
    data_json         TEXT NOT NULL,                   -- as GET /api/v1/sync/schedule gave it
    pulled_at         REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS schedule_links (
    game_id           INTEGER NOT NULL,                -- schema 7: a game made from a scheduled game
    game_seed         INTEGER NOT NULL,
    scheduled_game_id TEXT NOT NULL,
    linked_at         REAL NOT NULL,
    roster_pulled_at  REAL,                            -- the last roster applied (until the game starts)
    roster_count      INTEGER,
    roster_error      TEXT,
    PRIMARY KEY (game_id, game_seed)
);
CREATE TABLE IF NOT EXISTS player_positions (
    game_id     INTEGER NOT NULL,
    player_id   TEXT NOT NULL,
    report_json TEXT NOT NULL,
    received_at REAL NOT NULL,
    PRIMARY KEY (game_id, player_id)
);
"""

# Columns added to games in schema 2: (name, declaration).
GAME_COLUMNS_V2 = (
    ("node_id", "INTEGER"),                    # this controller's short id in the game
    ("channel_hz", "INTEGER"),                 # the shared game channel
    ("max_hops", "INTEGER"),                   # the relay clamp
    ("joined", "INTEGER NOT NULL DEFAULT 0"),  # 1: joined as a standby controller
    ("controller_id", "INTEGER"),              # joined game: the controller that made the join
    ("squads", "INTEGER NOT NULL DEFAULT 0"),  # schema 3: squads per team (0: the game has none)
    ("team_info_json", "TEXT"),                # schema 4: {team: {display_name, crest_id}}
)

# Columns added to checkins in schema 7 (plan phase 16): a registration from the site server's roster.
CHECKIN_COLUMNS_V7 = (
    ("registration_id", "TEXT"),                  # the site server's registration (a UUID)
    ("ticket_sha256", "TEXT"),                    # its ticket's SHA-256 (hex): from the roster or the app
    ("from_roster", "INTEGER NOT NULL DEFAULT 0"),  # 1: the roster brought it (the registration is verified)
)

LIVE_STATES = ("ready", "running", "paused")


def _private(path: str) -> None:
    try:
        if os.path.exists(path):
            os.chmod(path, 0o600)
    except OSError:
        pass


class _Result:
    """A statement's rows and row count, read while the store's lock was held."""

    def __init__(self, rows: list, rowcount: int) -> None:
        self._rows = rows
        self.rowcount = rowcount

    def fetchone(self) -> Optional[sqlite3.Row]:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list:
        return self._rows


class Store:
    """Thread-safe: one connection, one lock (the controller is I/O bound)."""

    def __init__(self, path: str) -> None:
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            # Created private before SQLite opens it: its WAL and shm files take its mode.
            os.close(os.open(path, os.O_RDWR | os.O_CREAT, 0o600))
            _private(path)
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL" if path != ":memory:" else "PRAGMA journal_mode=MEMORY")
            self._db.execute("PRAGMA synchronous=FULL")  # events must survive a power cut
            self._db.executescript(SCHEMA)
            have = {r["name"] for r in self._db.execute("PRAGMA table_info(games)").fetchall()}
            for name, decl in GAME_COLUMNS_V2:
                if name not in have:
                    self._db.execute(f"ALTER TABLE games ADD COLUMN {name} {decl}")
            have = {r["name"] for r in self._db.execute("PRAGMA table_info(checkins)").fetchall()}
            for name, decl in CHECKIN_COLUMNS_V7:
                if name not in have:
                    self._db.execute(f"ALTER TABLE checkins ADD COLUMN {name} {decl}")
            self.set_setting("schema_version", str(SCHEMA_VERSION))
        if path != ":memory:":
            for name in (path, path + "-wal", path + "-shm"):
                _private(name)  # tokens, token keys and, if enabled, game keys

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _exec(self, sql: str, args: tuple = ()) -> "_Result":
        # The rows are read while the lock is held: the API's worker threads and
        # the engine's thread share one connection, and sqlite3 shares a cached
        # statement between cursors running the same SQL, so a fetch outside the
        # lock could read another thread's rows (seen as a NULL column).
        with self._lock:
            cur = self._db.execute(sql, args)
            return _Result(cur.fetchall(), cur.rowcount)

    # --- settings -----------------------------------------------------------

    def get_setting(self, key: str) -> Optional[str]:
        row = self._exec("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        self._exec("INSERT INTO settings (key, value) VALUES (?, ?) "
                   "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    def delete_setting(self, key: str) -> None:
        self._exec("DELETE FROM settings WHERE key = ?", (key,))

    def next_tx_epoch(self) -> int:
        """The controller's epoch for this run: stored epoch + 1, written before any TX (ADR-P2-2)."""
        with self._lock:
            current = int(self.get_setting("tx_epoch") or "0")
            if current >= 0xFFFF:
                raise RuntimeError("the controller's nonce epochs are exhausted; reset the store")
            self.set_setting("tx_epoch", str(current + 1))
            return current + 1

    # --- modes --------------------------------------------------------------

    def save_mode(self, mode_id: str, version: str, files: dict[str, str]) -> None:
        self._exec("INSERT INTO modes (id, version, files_json, installed_at) VALUES (?, ?, ?, ?) "
                   "ON CONFLICT(id) DO UPDATE SET version = excluded.version, "
                   "files_json = excluded.files_json, installed_at = excluded.installed_at",
                   (mode_id, version, json.dumps(files), time.time()))

    def modes(self) -> list[dict[str, Any]]:
        rows = self._exec("SELECT * FROM modes ORDER BY id").fetchall()
        return [{"id": r["id"], "version": r["version"], "files": json.loads(r["files_json"])}
                for r in rows]

    # --- presets ------------------------------------------------------------

    def save_preset(self, name: str, mode_id: str, params: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            self._exec("INSERT INTO presets (name, mode_id, params_json, created_at, updated_at) "
                       "VALUES (?, ?, ?, ?, ?) ON CONFLICT(name) DO UPDATE SET "
                       "mode_id = excluded.mode_id, params_json = excluded.params_json, "
                       "updated_at = excluded.updated_at",
                       (name, mode_id, json.dumps(params), now, now))
            row = self._exec("SELECT * FROM presets WHERE name = ?", (name,)).fetchone()
        return self._preset(row)

    @staticmethod
    def _preset(row: sqlite3.Row) -> dict[str, Any]:
        return {"id": row["id"], "name": row["name"], "mode_id": row["mode_id"],
                "params": json.loads(row["params_json"]), "created_at": row["created_at"],
                "updated_at": row["updated_at"]}

    def presets(self) -> list[dict[str, Any]]:
        return [self._preset(r) for r in self._exec("SELECT * FROM presets ORDER BY name").fetchall()]

    def preset(self, preset_id: int) -> Optional[dict[str, Any]]:
        row = self._exec("SELECT * FROM presets WHERE id = ?", (preset_id,)).fetchone()
        return self._preset(row) if row else None

    # --- games --------------------------------------------------------------

    def create_game(self, game: dict[str, Any], key: Optional[bytes]) -> None:
        self._exec(
            "INSERT INTO games (id, name, mode_id, preset_id, teams_json, params_json, "
            "assignments_json, duration_ms, game_seed, state, term, game_key, created_at, "
            "node_id, channel_hz, max_hops, joined, controller_id, squads, team_info_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (game["id"], game["name"], game["mode_id"], game.get("preset_id"),
             json.dumps(game["teams"]), json.dumps(game["params"]),
             json.dumps(game["assignments"]), game["duration_ms"], game["game_seed"],
             game["state"], game.get("term", 1), key, game["created_at"],
             game.get("node_id"), game.get("channel_hz"), game.get("max_hops"),
             1 if game.get("joined") else 0, game.get("controller_id"), int(game.get("squads") or 0),
             json.dumps(game.get("team_info") or {})))

    @staticmethod
    def _game(row: sqlite3.Row) -> dict[str, Any]:
        return {"id": row["id"], "name": row["name"], "mode_id": row["mode_id"],
                "preset_id": row["preset_id"], "teams": json.loads(row["teams_json"]),
                "params": json.loads(row["params_json"]),
                "assignments": json.loads(row["assignments_json"]),
                "duration_ms": row["duration_ms"], "game_seed": row["game_seed"],
                "state": row["state"], "term": row["term"], "created_at": row["created_at"],
                "started_at": row["started_at"], "ended_at": row["ended_at"],
                "node_id": row["node_id"], "channel_hz": row["channel_hz"],
                "max_hops": row["max_hops"], "joined": bool(row["joined"]),
                "controller_id": row["controller_id"], "squads": row["squads"],
                "team_info": json.loads(row["team_info_json"] or "{}")}

    def game(self, game_id: int) -> Optional[dict[str, Any]]:
        row = self._exec("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
        return self._game(row) if row else None

    def game_key(self, game_id: int) -> Optional[bytes]:
        row = self._exec("SELECT game_key FROM games WHERE id = ?", (game_id,)).fetchone()
        return bytes(row["game_key"]) if row and row["game_key"] is not None else None

    def games(self) -> list[dict[str, Any]]:
        return [self._game(r) for r in self._exec("SELECT * FROM games ORDER BY created_at").fetchall()]

    def live_game(self) -> Optional[dict[str, Any]]:
        row = self._exec("SELECT * FROM games WHERE state IN (?, ?, ?) ORDER BY created_at DESC",
                         LIVE_STATES).fetchone()
        return self._game(row) if row else None

    def game_ids(self) -> set[int]:
        return {r["id"] for r in self._exec("SELECT id FROM games").fetchall()}

    def update_game(self, game_id: int, **fields: Any) -> None:
        allowed = {"state", "term", "started_at", "ended_at", "game_key", "assignments", "duration_ms",
                   "team_info"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"cannot update {unknown}")
        if "assignments" in fields:
            fields["assignments_json"] = json.dumps(fields.pop("assignments"))
        if "team_info" in fields:
            fields["team_info_json"] = json.dumps(fields.pop("team_info"))
        sets = ", ".join(f"{k} = ?" for k in fields)
        self._exec(f"UPDATE games SET {sets} WHERE id = ?", (*fields.values(), game_id))

    # --- nodes --------------------------------------------------------------

    def upsert_node(self, game_id: int, node_id: int, name: str, role: str, info: dict[str, Any]) -> None:
        self._exec("INSERT INTO nodes (game_id, node_id, name, role, info_json, last_seen) "
                   "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(game_id, node_id) DO UPDATE SET "
                   "name = excluded.name, role = excluded.role, info_json = excluded.info_json, "
                   "last_seen = excluded.last_seen",
                   (game_id, node_id, name, role, json.dumps(info), time.time()))

    def nodes(self, game_id: int) -> list[dict[str, Any]]:
        rows = self._exec("SELECT * FROM nodes WHERE game_id = ? ORDER BY node_id", (game_id,)).fetchall()
        return [{"node_id": r["node_id"], "name": r["name"], "role": r["role"],
                 "last_seen": r["last_seen"], **json.loads(r["info_json"])} for r in rows]

    # --- events -------------------------------------------------------------

    def insert_event(self, game_id: int, ev: dict[str, Any]) -> bool:
        """Stores one event; False if the log already had it (a replay or a flood copy)."""
        cur = self._exec(
            "INSERT OR IGNORE INTO events (game_id, node_id, seq, game_time, type, team, squad, "
            "priority, data_json, epoch, pkt_seq, received_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (game_id, ev["node"], ev["seq"], ev["t"], ev["type"], ev.get("team"), ev.get("squad"),
             ev.get("prio", "normal"), json.dumps(ev.get("data") or {}), ev.get("epoch"),
             ev.get("pkt_seq"), time.time()))
        return cur.rowcount == 1

    def events(self, game_id: int, since_ms: Optional[int] = None,
               event_type: Optional[str] = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM events WHERE game_id = ?"
        args: list[Any] = [game_id]
        if since_ms is not None:
            sql += " AND game_time >= ?"
            args.append(since_ms)
        if event_type is not None:
            sql += " AND type = ?"
            args.append(event_type)
        sql += " ORDER BY game_time, node_id, seq"
        return [{"node": r["node_id"], "seq": r["seq"], "t": r["game_time"], "type": r["type"],
                 "team": r["team"], "squad": r["squad"], "prio": r["priority"],
                 "data": json.loads(r["data_json"]), "epoch": r["epoch"], "pkt_seq": r["pkt_seq"],
                 "received_at": r["received_at"]}
                for r in self._exec(sql, tuple(args)).fetchall()]

    def events_after(self, game_id: int, after_id: int, limit: int) -> list[dict[str, Any]]:
        """The game's events with an ``events.id`` above ``after_id``, in id order (the sync cursor)."""
        rows = self._exec("SELECT * FROM events WHERE game_id = ? AND id > ? ORDER BY id LIMIT ?",
                          (game_id, after_id, limit)).fetchall()
        return [{"id": r["id"], "node": r["node_id"], "seq": r["seq"], "t": r["game_time"], "type": r["type"],
                 "team": r["team"], "squad": r["squad"], "prio": r["priority"],
                 "data": json.loads(r["data_json"]), "epoch": r["epoch"], "pkt_seq": r["pkt_seq"]}
                for r in rows]

    def count_events_after(self, game_id: int, after_id: int) -> int:
        row = self._exec("SELECT COUNT(*) AS n FROM events WHERE game_id = ? AND id > ?",
                         (game_id, after_id)).fetchone()
        return int(row["n"])

    def count_events(self, game_id: int, event_type: Optional[str] = None) -> int:
        if event_type is None:
            row = self._exec("SELECT COUNT(*) AS n FROM events WHERE game_id = ?", (game_id,)).fetchone()
        else:
            row = self._exec("SELECT COUNT(*) AS n FROM events WHERE game_id = ? AND type = ?",
                             (game_id, event_type)).fetchone()
        return int(row["n"])

    # --- scores -------------------------------------------------------------

    def save_scores(self, game_id: int, totals: dict[str, int]) -> None:
        with self._lock:
            for team, score in totals.items():
                self._exec("INSERT INTO scores (game_id, team, score) VALUES (?, ?, ?) "
                           "ON CONFLICT(game_id, team) DO UPDATE SET score = excluded.score",
                           (game_id, team, int(score)))

    def scores(self, game_id: int) -> dict[str, int]:
        rows = self._exec("SELECT team, score FROM scores WHERE game_id = ?", (game_id,)).fetchall()
        return {r["team"]: r["score"] for r in rows}

    # --- sync state (schema 5, plan phase 13) -------------------------------

    SYNC_FIELDS = ("acked_id", "meta_sha", "scores_sha", "nodes_sha", "skipped", "final", "last_ok_at",
                   "last_error")

    def sync_state(self, game_id: int, game_seed: int) -> dict[str, Any]:
        """What the site server has of a game, as far as this controller knows (all empty at first)."""
        row = self._exec("SELECT * FROM sync_state WHERE game_id = ? AND game_seed = ?",
                         (game_id, game_seed)).fetchone()
        if row is None:
            return {"acked_id": 0, "meta_sha": None, "scores_sha": None, "nodes_sha": None, "skipped": 0,
                    "final": False, "last_ok_at": None, "last_error": None}
        out = {k: row[k] for k in self.SYNC_FIELDS}
        out["final"] = bool(out["final"])
        return out

    def save_sync_state(self, game_id: int, game_seed: int, **fields: Any) -> None:
        unknown = set(fields) - set(self.SYNC_FIELDS)
        if unknown:
            raise ValueError(f"cannot update {unknown}")
        if "final" in fields:
            fields["final"] = 1 if fields["final"] else 0
        with self._lock:
            self._exec("INSERT OR IGNORE INTO sync_state (game_id, game_seed) VALUES (?, ?)", (game_id, game_seed))
            if fields:
                sets = ", ".join(f"{k} = ?" for k in fields)
                self._exec(f"UPDATE sync_state SET {sets} WHERE game_id = ? AND game_seed = ?",
                           (*fields.values(), game_id, game_seed))

    def reset_sync_state(self) -> int:
        """Forgets what was sent (a new site server): everything is sent again, and dropped there as
        duplicates where it is already stored. Returns the number of games forgotten (the field's chrono
        registry is forgotten too, and sent again whole)."""
        with self._lock:
            self._exec("DELETE FROM sync_items")
            return self._exec("DELETE FROM sync_state").rowcount

    # --- the chrono registry's sync (schema 6, plan phase 14) -----------------

    SYNC_KINDS = ("marshal", "replica", "reading", "checkins")  # checkins: per linked game (schema 7)

    def sync_items(self, kind: str) -> dict[str, str]:
        """What was last sent of one kind: {item id: hash}."""
        return {r["item_id"]: r["sha"] for r in self._exec(
            "SELECT item_id, sha FROM sync_items WHERE kind = ?", (kind,)).fetchall()}

    def mark_synced(self, kind: str, items: dict[str, str]) -> None:
        if kind not in self.SYNC_KINDS:
            raise ValueError(f"unknown sync kind {kind!r}")
        with self._lock:
            for item_id, sha in items.items():
                self._exec("INSERT INTO sync_items (kind, item_id, sha) VALUES (?, ?, ?) "
                           "ON CONFLICT(kind, item_id) DO UPDATE SET sha = excluded.sha", (kind, item_id, sha))

    def readings_unsynced(self, limit: int) -> list[dict[str, Any]]:
        """Readings not sent yet, in the order they were stored, with the text of their record."""
        rows = self._exec(
            "SELECT r.* FROM chrono_readings r LEFT JOIN sync_items s ON s.kind = 'reading' "
            "AND s.item_id = r.reading_id WHERE s.item_id IS NULL ORDER BY r.rowid LIMIT ?", (limit,)).fetchall()
        return [{"reading_id": r["reading_id"], "record_json": r["record_json"], "series_id": r["series_id"],
                 "outcome": r["outcome"], "received_at": r["received_at"], "game_id": r["game_id"]} for r in rows]

    def count_readings_unsynced(self) -> int:
        row = self._exec("SELECT count(*) AS n FROM chrono_readings r LEFT JOIN sync_items s ON s.kind = 'reading' "
                         "AND s.item_id = r.reading_id WHERE s.item_id IS NULL").fetchone()
        return int(row["n"])

    def replicas(self) -> list[dict[str, Any]]:
        return [json.loads(r["data_json"]) for r in self._exec(
            "SELECT data_json FROM replicas ORDER BY registered_at, replica_id").fetchall()]

    def marshal_key_history(self) -> list[dict[str, Any]]:
        """Every earlier key of every marshal, oldest first."""
        return [{"marshal_id": r["marshal_id"], "name": r["name"], "public_key": bytes(r["public_key"]),
                 "player_id": r["player_id"], "registered_at": r["registered_at"], "replaced_at": r["replaced_at"]}
                for r in self._exec("SELECT * FROM marshal_key_history ORDER BY replaced_at, marshal_id").fetchall()]

    # --- field image and positions (GM console field view) ------------------

    def set_field_image(self, content_type: str, data: bytes) -> None:
        if len(data) > FIELD_IMAGE_MAX:
            raise ValueError(f"the field image is over {FIELD_IMAGE_MAX} bytes")
        self._exec("INSERT INTO field_image (id, content_type, data, updated_at) VALUES (1, ?, ?, ?) "
                   "ON CONFLICT(id) DO UPDATE SET content_type = excluded.content_type, "
                   "data = excluded.data, updated_at = excluded.updated_at",
                   (content_type, data, time.time()))

    def field_image(self) -> Optional[tuple[str, bytes, float]]:
        row = self._exec("SELECT content_type, data, updated_at FROM field_image WHERE id = 1").fetchone()
        return (row["content_type"], bytes(row["data"]), row["updated_at"]) if row else None

    def delete_field_image(self) -> bool:
        return self._exec("DELETE FROM field_image WHERE id = 1").rowcount == 1

    def set_position(self, game_id: int, node_id: int, x: float, y: float) -> None:
        self._exec("INSERT INTO positions (game_id, node_id, x, y) VALUES (?, ?, ?, ?) "
                   "ON CONFLICT(game_id, node_id) DO UPDATE SET x = excluded.x, y = excluded.y",
                   (game_id, node_id, x, y))

    def positions(self, game_id: int) -> dict[int, dict[str, float]]:
        rows = self._exec("SELECT node_id, x, y FROM positions WHERE game_id = ? ORDER BY node_id",
                          (game_id,)).fetchall()
        return {r["node_id"]: {"x": r["x"], "y": r["y"]} for r in rows}

    # --- branding images and team presets (schema 4, decisions BR1-BR24) ------

    def put_image(self, image_id: str, kind: str, content_type: str, width: int, height: int,
                  data: bytes) -> bool:
        """Stores a checked image once; False if the same bytes were already stored."""
        cur = self._exec("INSERT OR IGNORE INTO images (id, kind, content_type, width, height, data, created_at) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?)", (image_id, kind, content_type, width, height, data,
                                                         time.time()))
        return cur.rowcount == 1

    def image(self, image_id: str, with_data: bool = True) -> Optional[dict[str, Any]]:
        cols = "id, kind, content_type, width, height, created_at, length(data) AS bytes"
        if with_data:
            cols += ", data"
        row = self._exec(f"SELECT {cols} FROM images WHERE id = ?", (image_id,)).fetchone()
        if row is None:
            return None
        out = {k: row[k] for k in ("id", "kind", "content_type", "width", "height", "created_at", "bytes")}
        if with_data:
            out["data"] = bytes(row["data"])
        return out

    def image_ids(self, kind: Optional[str] = None) -> list[dict[str, Any]]:
        sql = "SELECT id, kind, created_at FROM images"
        args: tuple = ()
        if kind is not None:
            sql += " WHERE kind = ?"
            args = (kind,)
        return [{"id": r["id"], "kind": r["kind"], "created_at": r["created_at"]}
                for r in self._exec(sql + " ORDER BY created_at", args).fetchall()]

    def delete_image(self, image_id: str) -> bool:
        return self._exec("DELETE FROM images WHERE id = ?", (image_id,)).rowcount == 1

    def team_info_crests(self) -> set[str]:
        """Every crest a game refers to (ended games included: their results show them)."""
        out: set[str] = set()
        for r in self._exec("SELECT team_info_json FROM games WHERE team_info_json IS NOT NULL").fetchall():
            try:
                info = json.loads(r["team_info_json"])
            except ValueError:
                continue
            for v in info.values() if isinstance(info, dict) else ():
                if isinstance(v, dict) and isinstance(v.get("crest_id"), str):
                    out.add(v["crest_id"])
        return out

    @staticmethod
    def _team_preset(row: sqlite3.Row) -> dict[str, Any]:
        return {"id": row["id"], "name": row["name"], "colour": row["colour"], "crest_id": row["crest_id"],
                "created_at": row["created_at"], "updated_at": row["updated_at"]}

    def team_presets(self) -> list[dict[str, Any]]:
        return [self._team_preset(r) for r in self._exec("SELECT * FROM team_presets ORDER BY name").fetchall()]

    def team_preset(self, preset_id: int) -> Optional[dict[str, Any]]:
        row = self._exec("SELECT * FROM team_presets WHERE id = ?", (preset_id,)).fetchone()
        return self._team_preset(row) if row else None

    def save_team_preset(self, name: str, colour: Optional[str], crest_id: Optional[str],
                         preset_id: Optional[int] = None) -> dict[str, Any]:
        """A new team preset, or (with preset_id) a change to one; a name is unique (ValueError)."""
        now = time.time()
        with self._lock:
            try:
                if preset_id is None:
                    cur = self._db.execute("INSERT INTO team_presets (name, colour, crest_id, created_at, "
                                           "updated_at) VALUES (?, ?, ?, ?, ?)", (name, colour, crest_id, now, now))
                    preset_id = int(cur.lastrowid)
                else:
                    self._db.execute("UPDATE team_presets SET name = ?, colour = ?, crest_id = ?, updated_at = ? "
                                     "WHERE id = ?", (name, colour, crest_id, now, preset_id))
            except sqlite3.IntegrityError:
                raise ValueError(f"a team preset named {name!r} already exists") from None
            row = self._exec("SELECT * FROM team_presets WHERE id = ?", (preset_id,)).fetchone()
        return self._team_preset(row)

    def delete_team_preset(self, preset_id: int) -> bool:
        return self._exec("DELETE FROM team_presets WHERE id = ?", (preset_id,)).rowcount == 1

    # --- field check-in (schema 3, ADR-P3-13) --------------------------------

    def token_key(self, game_id: int, create: bool = False) -> Optional[bytes]:
        """The game's player-token key (decision B8): made once, kept in this file only."""
        with self._lock:
            row = self._exec("SELECT key FROM token_keys WHERE game_id = ?", (game_id,)).fetchone()
            if row is not None:
                return bytes(row["key"])
            if not create:
                return None
            key = os.urandom(32)
            self._exec("INSERT INTO token_keys (game_id, key, created_at) VALUES (?, ?, ?)",
                       (game_id, key, time.time()))
            return key

    def field_player(self, player_id: str) -> Optional[dict[str, Any]]:
        row = self._exec("SELECT * FROM field_players WHERE player_id = ?", (player_id,)).fetchone()
        if row is None:
            return None
        secret = row["secret_sha256"]
        return {"player_id": row["player_id"],
                "secret_sha256": bytes(secret) if secret is not None else None,
                "created_at": row["created_at"], "last_seen_at": row["last_seen_at"]}

    def add_field_player(self, player_id: str, secret_sha256: Optional[bytes], now: float) -> None:
        self._exec("INSERT INTO field_players (player_id, secret_sha256, created_at, last_seen_at) "
                   "VALUES (?, ?, ?, ?)", (player_id, secret_sha256, now, now))

    def touch_field_player(self, player_id: str, now: float) -> None:
        self._exec("UPDATE field_players SET last_seen_at = ? WHERE player_id = ?", (now, player_id))

    CHECKIN_FIELDS = ("status", "display_name", "federation_number", "federation_seen", "team_preference",
                      "team", "squad", "role", "manual", "notice_version", "updated_at", "checked_in_at",
                      "erased_at", "registration_id", "ticket_sha256", "from_roster")

    @staticmethod
    def _checkin(row: sqlite3.Row) -> dict[str, Any]:
        out = {k: row[k] for k in row.keys()}
        out["federation_seen"] = bool(out["federation_seen"])
        out["manual"] = bool(out["manual"])
        out["from_roster"] = bool(out.get("from_roster"))
        return out

    def checkin_by_registration(self, game_id: int, registration_id: str) -> Optional[dict[str, Any]]:
        row = self._exec("SELECT * FROM checkins WHERE game_id = ? AND registration_id = ?",
                         (game_id, registration_id)).fetchone()
        return self._checkin(row) if row else None

    def delete_checkin(self, game_id: int, player_id: str) -> None:
        """An expected check-in whose registration was cancelled (schema 7): it and its declarations go."""
        with self._lock:
            self._exec("DELETE FROM declarations WHERE game_id = ? AND player_id = ?", (game_id, player_id))
            self._exec("DELETE FROM checkins WHERE game_id = ? AND player_id = ?", (game_id, player_id))

    # --- game-day sync (schema 7, plan phase 16) ------------------------------------------

    def set_schedule(self, games: list[dict[str, Any]], now: float) -> None:
        """The field's schedule as just pulled: it replaces the last one."""
        with self._lock:
            self._exec("DELETE FROM schedule_games")
            for g in games:
                self._exec("INSERT INTO schedule_games (scheduled_game_id, data_json, pulled_at) VALUES (?, ?, ?)",
                           (g["scheduled_game_id"], json.dumps(g, sort_keys=True), now))

    def schedule(self) -> list[dict[str, Any]]:
        rows = self._exec("SELECT data_json, pulled_at FROM schedule_games").fetchall()
        out = [{**json.loads(r["data_json"]), "pulled_at": r["pulled_at"]} for r in rows]
        return sorted(out, key=lambda g: (g["starts_at"], g["scheduled_game_id"]))

    def schedule_game(self, scheduled_game_id: str) -> Optional[dict[str, Any]]:
        row = self._exec("SELECT data_json, pulled_at FROM schedule_games WHERE scheduled_game_id = ?",
                         (scheduled_game_id,)).fetchone()
        return {**json.loads(row["data_json"]), "pulled_at": row["pulled_at"]} if row else None

    def link_schedule(self, game_id: int, game_seed: int, scheduled_game_id: str, now: float) -> None:
        self._exec("INSERT INTO schedule_links (game_id, game_seed, scheduled_game_id, linked_at) VALUES (?, ?, ?, ?) "
                   "ON CONFLICT(game_id, game_seed) DO UPDATE SET scheduled_game_id = excluded.scheduled_game_id, "
                   "linked_at = excluded.linked_at, roster_pulled_at = NULL, roster_count = NULL, "
                   "roster_error = NULL", (game_id, game_seed, scheduled_game_id, now))

    def schedule_link(self, game_id: int, game_seed: int) -> Optional[dict[str, Any]]:
        row = self._exec("SELECT * FROM schedule_links WHERE game_id = ? AND game_seed = ?",
                         (game_id, game_seed)).fetchone()
        return {k: row[k] for k in row.keys()} if row else None

    def schedule_links(self) -> list[dict[str, Any]]:
        rows = self._exec("SELECT * FROM schedule_links ORDER BY linked_at").fetchall()
        return [{k: r[k] for k in r.keys()} for r in rows]

    def roster_pulled(self, game_id: int, game_seed: int, now: float, count: Optional[int],
                      error: Optional[str]) -> None:
        if error is None:
            self._exec("UPDATE schedule_links SET roster_pulled_at = ?, roster_count = ?, roster_error = NULL "
                       "WHERE game_id = ? AND game_seed = ?", (now, count, game_id, game_seed))
        else:
            self._exec("UPDATE schedule_links SET roster_error = ? WHERE game_id = ? AND game_seed = ?",
                       (error, game_id, game_seed))

    def checkin(self, game_id: int, player_id: str) -> Optional[dict[str, Any]]:
        row = self._exec("SELECT * FROM checkins WHERE game_id = ? AND player_id = ?",
                         (game_id, player_id)).fetchone()
        return self._checkin(row) if row else None

    def checkins(self, game_id: int) -> list[dict[str, Any]]:
        rows = self._exec("SELECT * FROM checkins WHERE game_id = ? ORDER BY seq", (game_id,)).fetchall()
        return [self._checkin(r) for r in rows]

    def count_checkins(self, game_id: int, statuses: tuple[str, ...] = ("pending", "checked_in")) -> int:
        marks = ", ".join("?" for _ in statuses)
        row = self._exec(f"SELECT COUNT(*) AS n FROM checkins WHERE game_id = ? AND status IN ({marks})",
                         (game_id, *statuses)).fetchone()
        return int(row["n"])

    def add_checkin(self, game_id: int, player_id: str, fields: dict[str, Any], now: float) -> None:
        with self._lock:
            row = self._exec("SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM checkins WHERE game_id = ?",
                             (game_id,)).fetchone()
            cols = {"status": "pending", "team": 0, "squad": 0, "role": "player", "federation_seen": 0,
                    "manual": 0, **fields}
            names = ", ".join(cols)
            marks = ", ".join("?" for _ in cols)
            self._exec(f"INSERT INTO checkins (game_id, player_id, seq, created_at, updated_at, {names}) "
                       f"VALUES (?, ?, ?, ?, ?, {marks})",
                       (game_id, player_id, int(row["n"]), now, now, *cols.values()))

    def update_checkin(self, game_id: int, player_id: str, **fields: Any) -> None:
        unknown = set(fields) - set(self.CHECKIN_FIELDS)
        if unknown:
            raise ValueError(f"cannot update {unknown}")
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        self._exec(f"UPDATE checkins SET {sets} WHERE game_id = ? AND player_id = ?",
                   (*fields.values(), game_id, player_id))

    @staticmethod
    def _declaration(row: sqlite3.Row) -> dict[str, Any]:
        return {k: row[k] for k in row.keys()}

    def declarations(self, game_id: int, player_id: Optional[str] = None) -> list[dict[str, Any]]:
        if player_id is None:
            rows = self._exec("SELECT * FROM declarations WHERE game_id = ? ORDER BY position",
                              (game_id,)).fetchall()
        else:
            rows = self._exec("SELECT * FROM declarations WHERE game_id = ? AND player_id = ? "
                              "ORDER BY position", (game_id, player_id)).fetchall()
        return [self._declaration(r) for r in rows]

    def declaration(self, declaration_id: str) -> Optional[dict[str, Any]]:
        row = self._exec("SELECT * FROM declarations WHERE declaration_id = ?", (declaration_id,)).fetchone()
        return self._declaration(row) if row else None

    def declarations_for_replica(self, replica_id: str, player_id: str) -> list[dict[str, Any]]:
        rows = self._exec("SELECT * FROM declarations WHERE replica_id = ? AND player_id = ? "
                          "ORDER BY created_at", (replica_id, player_id)).fetchall()
        return [self._declaration(r) for r in rows]

    DECLARATION_COLUMNS = ("declaration_id", "game_id", "player_id", "replica_id", "type", "class",
                           "make_model", "state", "reading_id", "position")

    def put_declaration(self, d: dict[str, Any], now: float) -> None:
        cols = self.DECLARATION_COLUMNS
        self._exec(f"INSERT INTO declarations ({', '.join(cols)}, created_at, updated_at) "
                   f"VALUES ({', '.join('?' for _ in cols)}, ?, ?) ON CONFLICT(declaration_id) DO UPDATE SET "
                   "replica_id = excluded.replica_id, type = excluded.type, class = excluded.class, "
                   "make_model = excluded.make_model, state = excluded.state, "
                   "reading_id = excluded.reading_id, position = excluded.position, "
                   "updated_at = excluded.updated_at",
                   (*(d.get(c) for c in cols), now, now))

    def delete_declarations(self, game_id: int, player_id: str) -> None:
        self._exec("DELETE FROM declarations WHERE game_id = ? AND player_id = ?", (game_id, player_id))

    def put_replica(self, replica: dict[str, Any], now: float) -> None:
        self._exec("INSERT INTO replicas (replica_id, owner_player_id, data_json, registered_at) "
                   "VALUES (?, ?, ?, ?) ON CONFLICT(replica_id) DO UPDATE SET "
                   "owner_player_id = excluded.owner_player_id, data_json = excluded.data_json",
                   (replica["replica_id"], replica["owner_player_id"], json.dumps(replica), now))

    def replica(self, replica_id: str) -> Optional[dict[str, Any]]:
        row = self._exec("SELECT data_json FROM replicas WHERE replica_id = ?", (replica_id,)).fetchone()
        return json.loads(row["data_json"]) if row else None

    def add_reading(self, record: dict[str, Any], series_id: str, outcome: Optional[str], now: float) -> bool:
        """Stores a signed reading once (False: its reading_id was already stored)."""
        cur = self._exec(
            "INSERT OR IGNORE INTO chrono_readings (reading_id, replica_id, player_id, marshal_id, type, "
            "game_id, timestamp, record_json, series_id, outcome, received_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (record["reading_id"], record["replica_id"], record["player_id"], record["marshal_id"],
             record["type"], record.get("game_id"), record["timestamp"],
             json.dumps(record, sort_keys=True, ensure_ascii=False), series_id, outcome, now))
        return cur.rowcount == 1

    def readings(self, *, replica_id: Optional[str] = None, player_id: Optional[str] = None,
                 reading_ids: Optional[list[str]] = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM chrono_readings WHERE 1 = 1"
        args: list[Any] = []
        if replica_id is not None:
            sql += " AND replica_id = ?"
            args.append(replica_id)
        if player_id is not None:
            sql += " AND player_id = ?"
            args.append(player_id)
        if reading_ids is not None:
            sql += f" AND reading_id IN ({', '.join('?' for _ in reading_ids) or 'NULL'})"
            args.extend(reading_ids)
        sql += " ORDER BY timestamp, reading_id"
        return [{"reading_id": r["reading_id"], "series_id": r["series_id"], "outcome": r["outcome"],
                 "type": r["type"], "timestamp": r["timestamp"], "received_at": r["received_at"],
                 "record": json.loads(r["record_json"])}
                for r in self._exec(sql, tuple(args)).fetchall()]

    def delete_readings(self, *, player_id: Optional[str] = None, before: Optional[str] = None) -> int:
        with self._lock:
            if player_id is not None:
                n = self._exec("DELETE FROM chrono_readings WHERE player_id = ?", (player_id,)).rowcount
            elif before is not None:
                n = self._exec("DELETE FROM chrono_readings WHERE timestamp < ?", (before,)).rowcount
            else:
                return 0
            if n:
                self._exec("DELETE FROM sync_items WHERE kind = 'reading' AND item_id NOT IN "
                           "(SELECT reading_id FROM chrono_readings)")
            return n

    def delete_marshal_history(self, replaced_before: float) -> int:
        """Earlier marshal keys replaced before then (retention: no reading they signed is left)."""
        return self._exec("DELETE FROM marshal_key_history WHERE replaced_at < ?", (replaced_before,)).rowcount

    def put_marshal(self, marshal_id: str, name: str, public_key: bytes, player_id: Optional[str],
                    now: float) -> None:
        """The marshal's current key; a different key replaces it and the old one goes to
        ``marshal_key_history`` (schema 6), so what it signed still verifies elsewhere."""
        with self._lock:
            old = self.marshal(marshal_id)
            if old is not None and old["public_key"] != bytes(public_key):
                self._exec("INSERT INTO marshal_key_history (marshal_id, name, public_key, player_id, registered_at, "
                           "replaced_at) VALUES (?, ?, ?, ?, ?, ?)", (marshal_id, old["name"], old["public_key"],
                                                                      old["player_id"], old["registered_at"], now))
            self._put_marshal(marshal_id, name, public_key, player_id, now, keep_since=old is not None
                              and old["public_key"] == bytes(public_key))

    def _put_marshal(self, marshal_id: str, name: str, public_key: bytes, player_id: Optional[str], now: float,
                     keep_since: bool) -> None:
        # The same key registered again keeps the time it was first registered: readings it signed
        # before then still fall inside its period on the site server.
        if keep_since:
            self._exec("UPDATE marshal_keys SET name = ?, player_id = ? WHERE marshal_id = ?",
                       (name, player_id, marshal_id))
            return
        self._exec("INSERT INTO marshal_keys (marshal_id, name, public_key, player_id, registered_at) "
                   "VALUES (?, ?, ?, ?, ?) ON CONFLICT(marshal_id) DO UPDATE SET name = excluded.name, "
                   "public_key = excluded.public_key, player_id = excluded.player_id, "
                   "registered_at = excluded.registered_at", (marshal_id, name, public_key, player_id, now))

    def marshal(self, marshal_id: str) -> Optional[dict[str, Any]]:
        row = self._exec("SELECT * FROM marshal_keys WHERE marshal_id = ?", (marshal_id,)).fetchone()
        if row is None:
            return None
        return {"marshal_id": row["marshal_id"], "name": row["name"], "public_key": bytes(row["public_key"]),
                "player_id": row["player_id"], "registered_at": row["registered_at"]}

    def marshals(self) -> list[dict[str, Any]]:
        rows = self._exec("SELECT marshal_id FROM marshal_keys ORDER BY marshal_id").fetchall()
        return [m for m in (self.marshal(r["marshal_id"]) for r in rows) if m]

    def erase_player(self, player_id: str) -> None:
        """A player's field identity, check-ins and declarations (not the readings: chrono erasure)."""
        with self._lock:
            self._exec("DELETE FROM declarations WHERE player_id = ?", (player_id,))
            self._exec("DELETE FROM checkins WHERE player_id = ?", (player_id,))
            self._exec("DELETE FROM player_positions WHERE player_id = ?", (player_id,))
            self._exec("DELETE FROM field_players WHERE player_id = ?", (player_id,))

    def purge_checkins(self, ended_before: float, idle_before: float, now: float) -> dict[str, int]:
        """Retention (ADR-P3-13): personal fields and declarations of games that ended before
        ended_before; field identities not seen since idle_before."""
        with self._lock:
            games = [r["id"] for r in self._exec(
                "SELECT id FROM games WHERE state = 'ended' AND ended_at IS NOT NULL AND ended_at < ?",
                (ended_before,)).fetchall()]
            erased = declarations = 0
            for gid in games:
                erased += self._exec(
                    "UPDATE checkins SET display_name = NULL, federation_number = NULL, "
                    "team_preference = NULL, erased_at = ? WHERE game_id = ? AND erased_at IS NULL",
                    (now, gid)).rowcount
                declarations += self._exec("DELETE FROM declarations WHERE game_id = ?", (gid,)).rowcount
            idle = [r["player_id"] for r in self._exec(
                "SELECT player_id FROM field_players WHERE last_seen_at < ?", (idle_before,)).fetchall()]
            for pid in idle:
                self.erase_player(pid)
            return {"checkins": erased, "declarations": declarations, "identities": len(idle)}

    def set_player_position(self, game_id: int, player_id: str, report: dict[str, Any], now: float) -> None:
        self._exec("INSERT INTO player_positions (game_id, player_id, report_json, received_at) "
                   "VALUES (?, ?, ?, ?) ON CONFLICT(game_id, player_id) DO UPDATE SET "
                   "report_json = excluded.report_json, received_at = excluded.received_at",
                   (game_id, player_id, json.dumps(report), now))

    def player_positions(self, game_id: int) -> dict[str, dict[str, Any]]:
        rows = self._exec("SELECT player_id, report_json FROM player_positions WHERE game_id = ?",
                          (game_id,)).fetchall()
        return {r["player_id"]: json.loads(r["report_json"]) for r in rows}

    def delete_player_positions(self, game_id: int) -> int:
        return self._exec("DELETE FROM player_positions WHERE game_id = ?", (game_id,)).rowcount
