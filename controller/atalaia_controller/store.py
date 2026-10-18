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
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

SCHEMA_VERSION = 2
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
"""

# Columns added to games in schema 2: (name, declaration).
GAME_COLUMNS_V2 = (
    ("node_id", "INTEGER"),                    # this controller's short id in the game
    ("channel_hz", "INTEGER"),                 # the shared game channel
    ("max_hops", "INTEGER"),                   # the relay clamp
    ("joined", "INTEGER NOT NULL DEFAULT 0"),  # 1: joined as a standby controller
    ("controller_id", "INTEGER"),              # joined game: the controller that made the join
)

LIVE_STATES = ("ready", "running", "paused")


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
            self.set_setting("schema_version", str(SCHEMA_VERSION))
        if path != ":memory:":
            try:
                Path(path).chmod(0o600)  # may hold tokens and, if enabled, a game key
            except OSError:
                pass

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
            "node_id, channel_hz, max_hops, joined, controller_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (game["id"], game["name"], game["mode_id"], game.get("preset_id"),
             json.dumps(game["teams"]), json.dumps(game["params"]),
             json.dumps(game["assignments"]), game["duration_ms"], game["game_seed"],
             game["state"], game.get("term", 1), key, game["created_at"],
             game.get("node_id"), game.get("channel_hz"), game.get("max_hops"),
             1 if game.get("joined") else 0, game.get("controller_id")))

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
                "controller_id": row["controller_id"]}

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
        allowed = {"state", "term", "started_at", "ended_at", "game_key", "assignments", "duration_ms"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"cannot update {unknown}")
        if "assignments" in fields:
            fields["assignments_json"] = json.dumps(fields.pop("assignments"))
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
