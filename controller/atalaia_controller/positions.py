# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Player positions and who may see them (ADR-P3-6, constraint 9: server-side filtering only).

Phones report with POST /api/v1/positions (a player token; GPS outdoors, the
strongest BLE beacon indoors). The controller keeps each player's latest
report for the live game only and sends a position to a connection only if
that connection's role may see it:

    player        their own; their squad's too when the game's parameters say squad_visible
    squad_leader  their squad
    vip           their team (the escort)
    marshal, gm   everyone (the GM token too)
    spectator     nobody (the read token is a spectator)

A mode can grant a team a temporary view of another team (a UAV sweep): the
event ``visibility.granted`` (its envelope team sees ``see_team`` for
``duration_s``), ended by ``visibility.expired``, which the controller emits
when the time is up. Reports are taken only from a player who chose to share
(``share_position`` at check-in, off by default, changeable during the game: protocol/checkin.md) and are
dropped when they stop sharing. Positions are deleted when the game ends, and are never
sent on the radio or MQTT. A VIP's GPS reports also go to the game's field.lua
as the input position.fix (decision P4R6, VIP / Payload), and to nothing else.

On a multi-story field (field_levels.py) a report may say the player's level
(``level``, 0-9; null: not known). A report without ``level`` keeps the one
the player last gave in this game, so a phone that asks once ("which floor
are you on?") need not send it every time; never given, the position has no
level (decision ML-5).

A ``ble`` report names the strongest iBeacon the phone hears (``beacon_id``, major:minor) and only a beacon of
the field's registry is accepted (beacons.py, decisions BLE-1 to BLE-9): the stored position then carries the
beacon's ``room``, ``zone`` and ``level`` (the beacon's level is the player's, whatever the report says) and, when
the GM placed the beacon on its plan, its ``x`` and ``y``. A newer report of either source replaces the older one:
a phone indoors sends beacons, outdoors GPS (app/lib/position/position_reporter.dart).
"""

from __future__ import annotations

import math
import re
import threading
import time
from typing import TYPE_CHECKING, Any, Callable, Optional

from . import beacons as beaconsmod
from . import box_beacons as boxbeacons
from .engine import Conflict, ControllerError
from .field_levels import LEVELS_MAX

if TYPE_CHECKING:
    from .checkin import Viewer
    from .engine import Controller

REPORTS_MAX = 5
BEACON_RE = re.compile(r"[0-9]{1,5}:[0-9]{1,5}")
SOURCES = ("gps", "ble")
GRANT_MAX_S = 3600


def _num(name: str, v: Any, lo: float, hi: float, optional: bool = True) -> Optional[float]:
    if v is None and optional:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not lo <= v <= hi:
        raise ControllerError(f"{name}: a number from {lo} to {hi}")
    return float(v)


def check_report(r: Any) -> dict[str, Any]:
    """One position report's own fields (the player, team and squad come from the token)."""
    if not isinstance(r, dict):
        raise ControllerError("a position report is an object")
    allowed = {"lat", "lon", "accuracy_m", "altitude_m", "heading_deg", "speed_mps", "source", "beacon_id",
               "t", "player_id", "team", "squad", "level"}
    unknown = set(r) - allowed
    if unknown:
        raise ControllerError(f"position report: unknown fields {sorted(unknown)}")
    source = r.get("source", "gps")
    if source not in SOURCES:
        raise ControllerError("source: gps or ble")
    out: dict[str, Any] = {"source": source}
    if source == "gps":
        out["lat"] = _num("lat", r.get("lat"), -90, 90, optional=False)
        out["lon"] = _num("lon", r.get("lon"), -180, 180, optional=False)
        out["accuracy_m"] = _num("accuracy_m", r.get("accuracy_m"), 0, 10_000)
        for name, lo, hi in (("altitude_m", -1000, 10_000), ("heading_deg", 0, 360), ("speed_mps", 0, 200)):
            v = _num(name, r.get(name), lo, hi)
            if v is not None:
                out[name] = v
    else:
        bid = r.get("beacon_id")
        if not isinstance(bid, str) or not BEACON_RE.fullmatch(bid) \
                or not all(0 <= int(x) <= 65535 for x in bid.split(":")):
            raise ControllerError("beacon_id: major:minor of the strongest iBeacon")
        out["beacon_id"] = bid
    if "level" in r:
        level = r["level"]
        if level is not None and (isinstance(level, bool) or not isinstance(level, int)
                                  or not 0 <= level < LEVELS_MAX):
            raise ControllerError(f"level: 0 to {LEVELS_MAX - 1}, or null when not known")
        out["level"] = level
    t = r.get("t", 0)
    if isinstance(t, bool) or not isinstance(t, int) or not 0 <= t <= 2**53:
        raise ControllerError("t: milliseconds, an integer")
    out["t"] = t
    return out


class Positions:
    def __init__(self, controller: "Controller", wall: Callable[[], float] = time.time) -> None:
        self.ctrl = controller
        self._wall = wall
        self._lock = threading.Lock()
        # (game, team that sees, team seen) -> expiry (wall seconds)
        self.grants: dict[tuple[int, str, str], float] = {}
        controller.positions = self

    # --- who sees whom -----------------------------------------------------------

    def _squad_visible(self, game_id: int) -> bool:
        game = self.ctrl.store.game(game_id)
        return bool(game and (game.get("params") or {}).get("squad_visible"))

    def _team_name(self, game_id: int, team_id: int) -> Optional[str]:
        game = self.ctrl.store.game(game_id)
        if game and 1 <= team_id <= len(game["teams"]):
            return game["teams"][team_id - 1]
        return None

    def can_see(self, viewer: "Viewer", pos: dict[str, Any]) -> bool:
        if viewer.kind == "gm":
            return True
        if viewer.kind != "player" or viewer.game_id != pos["game_id"]:
            return False
        role = viewer.role
        if role in ("marshal", "gm"):
            return True
        if pos["player_id"] == viewer.player_id:
            return role != "spectator"
        same_team = viewer.team != 0 and pos["team"] == viewer.team
        same_squad = same_team and viewer.squad != 0 and pos["squad"] == viewer.squad
        if role == "squad_leader" and same_squad:
            return True
        if role == "vip" and same_team:
            return True
        if role == "player" and same_squad and self._squad_visible(pos["game_id"]):
            return True
        if role in ("player", "squad_leader", "vip") and viewer.team and pos["team"]:
            mine = self._team_name(pos["game_id"], viewer.team)
            theirs = self._team_name(pos["game_id"], pos["team"])
            exp = self.grants.get((pos["game_id"], mine or "", theirs or ""))
            if exp is not None and exp > self._wall():
                return True
        return False

    def visible(self, viewer: "Viewer", game_id: Optional[int] = None) -> list[dict[str, Any]]:
        if game_id is None:
            game_id = viewer.game_id if viewer.kind == "player" else (
                self.ctrl.game["id"] if self.ctrl.game else None)
        if game_id is None:
            return []
        return [p for p in self.ctrl.store.player_positions(game_id).values() if self.can_see(viewer, p)]

    # --- reports -------------------------------------------------------------------

    def report(self, viewer: "Viewer", body: Any) -> dict[str, Any]:
        if viewer.kind != "player":
            raise ControllerError("positions come from a player's token")
        items = body.get("reports") if isinstance(body, dict) and "reports" in body else [body]
        if not isinstance(items, list) or not 1 <= len(items) <= REPORTS_MAX:
            raise ControllerError(f"reports: 1 to {REPORTS_MAX} position reports")
        checked = [check_report(r) for r in items]
        row = self.ctrl.store.checkin(viewer.game_id, viewer.player_id)
        if row is None or not row.get("position_share"):
            # Sharing is the player's own choice at check-in (an unticked box), changeable any time; declining
            # never blocks the check-in or the game (GDPR Art. 7(4)).
            raise Conflict("position_sharing_off: this player did not choose to share their position")
        for r, raw in zip(checked, items):
            if raw.get("player_id") not in (None, viewer.player_id):
                raise ControllerError("player_id: only your own position")
        game = self.ctrl.store.game(viewer.game_id)
        if game is None or game["state"] not in ("running", "paused") or self.ctrl.game is None \
                or self.ctrl.game["id"] != game["id"]:
            raise Conflict("positions are kept only while the game runs")
        for i, r in enumerate(checked):
            if r["source"] == "ble":
                # A Field Box's own beacon (its place on the field view, box_beacons.py), else a tag of the registry.
                place = boxbeacons.place_of(self.ctrl, r["beacon_id"]) if r["beacon_id"].startswith(
                    f"{beaconsmod.BOX_MAJOR}:") else beaconsmod.place_of(self.ctrl.store, r["beacon_id"])
                if place is None:
                    raise ControllerError(f"beacon_id: {r['beacon_id']} is not a beacon of this field's registry")
                checked[i] = {**r, **place}
        latest = max(checked, key=lambda r: r["t"])
        if "level" not in latest:
            latest = {**latest, **self._last_level(game["id"], viewer.player_id)}
        if latest.get("level", 0) is None:
            latest = {k: v for k, v in latest.items() if k != "level"}  # not known: no level
        pos = {"game_id": game["id"], "player_id": viewer.player_id, "team": viewer.team,
               "squad": viewer.squad, **latest, "received_at": self._wall()}
        self.ctrl.store.set_player_position(game["id"], viewer.player_id, pos, self._wall())
        self.ctrl._emit({"type": "player_position", "game": game["id"], "position": pos, "_position": True})
        if viewer.role == "vip":
            self._to_field(game, viewer, checked)
        return {"stored": len(checked), "interval_s": self.interval(game),
                "ble_interval_s": beaconsmod.interval(game)}

    def _last_level(self, game_id: int, player_id: str) -> dict[str, Any]:
        """The level this player last gave in this game, as ``{"level": n}`` (or nothing)."""
        before = self.ctrl.store.player_positions(game_id).get(player_id) or {}
        return {"level": before["level"]} if isinstance(before.get("level"), int) else {}

    def _to_field(self, game: dict[str, Any], viewer: "Viewer", reports: list[dict[str, Any]]) -> None:
        """A VIP's GPS reports, oldest first, to the game's field.lua as position.fix (decision
        P4R6; VIP / Payload extracts the VIP with them). Indoor (BLE) reports carry no coordinates."""
        team = self._team_name(game["id"], viewer.team)
        for r in sorted((r for r in reports if r["source"] == "gps"), key=lambda r: r["t"]):
            fix: dict[str, Any] = {"player": viewer.player_id, "role": viewer.role, "lat": r["lat"],
                                   "lon": r["lon"], "src": "gps"}
            if team is not None:
                fix["team"] = team
            if r.get("accuracy_m") is not None:
                fix["acc"] = r["accuracy_m"]
            if not self.ctrl.field_position(game["id"], fix):
                return

    @staticmethod
    def interval(game: dict[str, Any]) -> int:
        v = (game.get("params") or {}).get("position_interval_s", 10)
        return int(v) if isinstance(v, int) and 5 <= v <= 60 else 10

    # --- temporary visibility --------------------------------------------------------

    def on_event(self, game_id: int, record: dict[str, Any]) -> None:
        """visibility.granted from a node or field.lua: its team sees see_team for duration_s."""
        if record.get("type") != "visibility.granted":
            return
        data = record.get("data") or {}
        team, see, dur = record.get("team"), data.get("see_team"), data.get("duration_s")
        if not isinstance(team, str) or not isinstance(see, str) or isinstance(dur, bool) \
                or not isinstance(dur, (int, float)) or not 0 < dur <= GRANT_MAX_S:
            return
        with self._lock:
            self.grants[(game_id, team, see)] = self._wall() + float(dur)
        self.ctrl._emit({"type": "positions", "game": game_id, "_positions_refresh": True})

    def tick(self) -> None:
        """Ends grants whose time is up, with visibility.expired from the controller."""
        now = self._wall()
        with self._lock:
            done = [k for k, exp in self.grants.items() if exp <= now]
            for k in done:
                del self.grants[k]
        for game_id, team, see in done:
            fc = self.ctrl.fc
            if fc is not None and self.ctrl.game is not None and self.ctrl.game["id"] == game_id:
                fc.controller_event("visibility.expired", {"see_team": see, "text": "time"}, team=team)
            self.ctrl._emit({"type": "positions", "game": game_id, "_positions_refresh": True})

    def end_game(self, game_id: int) -> None:
        """ADR-P3-6: positions last only as long as the game."""
        with self._lock:
            for k in [k for k in self.grants if k[0] == game_id]:
                del self.grants[k]
        self.ctrl.store.delete_player_positions(game_id)
