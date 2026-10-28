# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The demo's game master and players: plays one game after another on the demo field, through the controller's
own HTTP API and the simulated boxes' buttons, the way people at a field would.

One cycle: a new Domination game, the three simulated boxes joined with the controller's join cards, twelve
players checked in under made-up callsigns (six a team, declaring a replica each), a marshal's signed chrono
readings (one replica over its class limit, as happens), the game started, boxes held by one team or the other
for a few minutes while the players walk between them and report their positions, the game ended, the final
score left on show, and again. Everything it writes is invented; it never reads or keeps anything about a real
person. The pace is set by DEMO_LOBBY_S, DEMO_GAME_S and DEMO_PAUSE_S.
"""

from __future__ import annotations

import base64
import json
import logging
import math
import os
import random
import secrets
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib import error, request

import fieldmap
from air import HostBox

log = logging.getLogger("demo.director")

# Made-up callsigns: animals, plants and weather, not names of people. A test checks the list stays free of
# anything that looks like a person's name.
CALLSIGNS = ("Falcão", "Lince", "Sombra", "Brasa", "Corça", "Pardal", "Tojo", "Névoa", "Seixo", "Giesta", "Urze",
             "Cardo", "Gralha", "Sobreiro", "Rouxinol", "Folhelho", "Lontra", "Bruma", "Carvalho", "Orvalho",
             "Zimbro", "Estorninho", "Salgueiro", "Trovoada")
MARSHAL_NAME = "Arbitragem Demo"
TEAMS = ("red", "blue")
BOX_NAMES = ("alpha", "bravo", "charlie")
MODE_ID = "org.atalaia.domination"
PARAMS = {"capture_hold_ms": 2000, "tick_s": 5, "points_per_tick": 1}
LIMIT_J = 1.14        # the class limit of the "portugal" template's rifle; one reading goes over it
ALPHABET = "abcdefghijklmnopqrstuvwxyz234567"


def env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


class Restart(Exception):
    """The field has played enough games: it is time to start over (a fresh controller database)."""


class ApiError(Exception):
    def __init__(self, status: int, text: str) -> None:
        super().__init__(f"{status}: {text[:200]}")
        self.status = status


class Api:
    """The controller's REST API on this machine, with the GM token unless a call names another token."""

    def __init__(self, base: str, gm_token: str) -> None:
        self.base = base.rstrip("/")
        self.gm = gm_token

    def call(self, method: str, path: str, body: Any = None, token: Optional[str] = None, raw: Optional[bytes] = None,
             ctype: str = "application/json") -> Any:
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = request.Request(self.base + path, data=data, method=method)
        req.add_header("Authorization", "Bearer " + (token or self.gm))
        if data is not None:
            req.add_header("Content-Type", ctype)
        try:
            with request.urlopen(req, timeout=20) as resp:
                text = resp.read()
        except error.HTTPError as exc:
            raise ApiError(exc.code, exc.read().decode("utf-8", "replace")) from None
        return json.loads(text) if text else None


def new_identity() -> tuple[str, str]:
    return ("p-" + "".join(secrets.choice(ALPHABET) for _ in range(12)),
            base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode("ascii"))


class Player:
    def __init__(self, name: str, team: str, home: tuple[float, float], rng: random.Random) -> None:
        self.name, self.team = name, team
        self.pid, self.secret = new_identity()
        self.token = ""
        self.x, self.y = home[0] + rng.uniform(-0.04, 0.04), home[1] + rng.uniform(-0.04, 0.04)
        self.target = (self.x, self.y)
        self.replica_id = str(uuid.uuid4())
        self.speed = rng.uniform(0.0025, 0.0045)  # of the plan per second: 1 to 2 m/s on the 360 m plan

    def step(self, dt: float, rng: random.Random) -> None:
        dx, dy = self.target[0] - self.x, self.target[1] - self.y
        dist = math.hypot(dx, dy)
        if dist < 0.03:
            return
        move = min(dist, self.speed * dt)
        self.x += dx / dist * move + rng.uniform(-0.0015, 0.0015)
        self.y += dy / dist * move + rng.uniform(-0.0015, 0.0015)
        self.x, self.y = min(0.98, max(0.02, self.x)), min(0.98, max(0.02, self.y))


class Director:
    def __init__(self, api: Api, boxes: list[HostBox], data_dir: Path, seed: Optional[int] = None) -> None:
        self.api = api
        self.boxes = boxes
        self.data = data_dir
        self.rng = random.Random(seed)
        self.lobby_s = env_float("DEMO_LOBBY_S", 25)
        self.game_s = env_float("DEMO_GAME_S", 240)
        self.pause_s = env_float("DEMO_PAUSE_S", 60)
        self.cycle_no = 0
        self.max_games = int(env_float("DEMO_RESTART_AFTER_GAMES", 24))
        self.marshal = self._marshal_identity()

    # --- the marshal: one identity for the field, kept in the data folder ---------------------------------

    def _marshal_identity(self) -> dict[str, Any]:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        path = self.data / "marshal.json"
        if path.exists():
            saved = json.loads(path.read_text())
            return {**saved, "key": Ed25519PrivateKey.from_private_bytes(bytes.fromhex(saved["seed"]))}
        key = Ed25519PrivateKey.generate()
        seed = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                 serialization.NoEncryption()).hex()
        pid, secret = new_identity()
        saved = {"seed": seed, "player_id": pid, "secret": secret, "marshal_id": "m-demo"}
        path.write_text(json.dumps(saved))
        path.chmod(0o600)
        return {**saved, "key": key}

    # --- setting the field up (once per start) --------------------------------------------------------------

    def prepare_field(self) -> None:
        """The plan and its place on the map, so boxes and players are drawn on it; idempotent."""
        self.api.call("PUT", "/api/v1/field/image", raw=fieldmap.plan_png(), ctype="image/png")
        self.api.call("PUT", "/api/v1/field/georef", {"points": fieldmap.georef_points()})
        self.end_stale_games()

    def end_stale_games(self) -> None:
        """A game left running or paused by a restart is ended: a restart never resumes a half-played game."""
        for g in self.api.call("GET", "/api/v1/games") or []:
            if g.get("state") in ("running", "paused", "ready"):
                try:
                    self.api.call("POST", f"/api/v1/games/{g['id']}/end", {})
                    log.info("ended game %s left from before the restart", g["id"])
                except ApiError as exc:
                    log.warning("could not end game %s: %s", g["id"], exc)

    # --- one cycle -------------------------------------------------------------------------------------------

    def run_forever(self) -> None:
        self.prepare_field()
        failures = 0
        while True:
            try:
                if self.max_games and self.cycle_no >= self.max_games:
                    raise Restart(f"{self.cycle_no} games played")
                self.cycle()
                failures = 0
            except Restart:
                raise
            except Exception as exc:  # noqa: BLE001  (a demo that stops is worse than one that skips a game)
                failures += 1
                log.exception("the demo game failed (%d in a row): %s", failures, exc)
                if failures >= 5:
                    raise
                try:
                    self.end_stale_games()
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(15)

    def cycle(self) -> None:
        self.cycle_no += 1
        stamp = datetime.now(timezone.utc).strftime("%H:%M")
        game = self.api.call("POST", "/api/v1/games", {
            "name": f"Demonstração {stamp} (Domínio)", "mode_id": MODE_ID, "teams": list(TEAMS), "squads": 2, "params": PARAMS})
        gid = game["id"]
        log.info("game %d made", gid)
        self.join_boxes(gid)
        self.api.call("POST", f"/api/v1/games/{gid}/checkin/open")
        players = self.check_in_players(gid)
        try:
            self.chrono(gid, players)
        except (ApiError, OSError) as exc:  # the chronograph is a side of the show: the game goes on without it
            log.warning("the chrono readings of game %d were not recorded: %s", gid, exc)
        self.place_boxes(gid)
        self.publish_player(gid, players[0])
        self.sleep(self.lobby_s)
        self.api.call("POST", f"/api/v1/games/{gid}/start", {})
        log.info("game %d started", gid)
        self.play(gid, players)
        self.api.call("POST", f"/api/v1/games/{gid}/end", {})
        self.api.call("POST", f"/api/v1/games/{gid}/checkin/close")
        log.info("game %d ended", gid)
        self.sleep(self.pause_s)

    @staticmethod
    def sleep(seconds: float) -> None:
        time.sleep(max(0.0, seconds))

    def join_boxes(self, gid: int) -> None:
        for box in self.boxes:
            if not box.alive():
                raise RuntimeError(f"the simulated box {box.name} is not running")
            mark = box.mark()
            card = self.api.call("POST", "/api/v1/join", {"role": "zone"})
            box.join(card["text"])
            if not box.wait_for("LOG join: joined", 20, mark):
                raise RuntimeError(f"the simulated box {box.name} did not join game {gid}")

    def place_boxes(self, gid: int) -> None:
        nodes = self.api.call("GET", "/api/v1/nodes") or []
        mine = {n["node_id"] for n in nodes if n.get("game_id") in (None, gid)}
        for node_id, (fx, fy) in zip(sorted(mine)[-len(BOX_NAMES):], fieldmap.ZONES.values()):
            try:
                self.api.call("PUT", f"/api/v1/games/{gid}/positions/{node_id}", {"x": fx, "y": fy})
            except ApiError as exc:
                log.warning("could not place box %s: %s", node_id, exc)

    # --- players ----------------------------------------------------------------------------------------------

    def check_in_players(self, gid: int) -> list[Player]:
        notice = self.api.call("GET", "/api/v1/checkin")["notice"]["version"]
        names = self.rng.sample(CALLSIGNS, 12)
        players: list[Player] = []
        for i, name in enumerate(names):
            team = TEAMS[i % 2]
            players.append(Player(name, team, fieldmap.BASES[team], self.rng))
        # The player the player's view follows is the first one of the red team.
        for i, p in enumerate(players):
            body = {"game_id": gid, "player_id": p.pid, "player_secret": p.secret, "display_name": p.name,
                    "notice_version": notice,
                    "replicas": [{"declaration_id": str(uuid.uuid4()), "replica_id": p.replica_id, "type": "aeg",
                                  "class": "rifle"}]}
            out = self.api.call("POST", "/api/v1/checkin", body, token="x")  # the check-in needs no token
            p.token = out["token"]
            # The first red player is the one the player's view follows: a VIP, who sees the whole team's positions.
            patch = {"team": p.team, "squad": 1 + (i // 2) // 3}
            if i == 0:
                patch["role"] = "vip"
            self.api.call("PATCH", f"/api/v1/games/{gid}/checkins/{p.pid}", patch)
            # a role or team change makes a new token (the old one is stale)
            p.token = self.api.call("POST", "/api/v1/checkin/token", token=p.token)["token"]
        return players

    def chrono(self, gid: int, players: list[Player]) -> None:
        """A marshal (the same one every game) checks in, is put on the field's marshal list with a signing key, and
        uploads a signed reading for each player's replica; one of them is over the class limit."""
        from atalaia_controller import chrono as chronomod

        notice = self.api.call("GET", "/api/v1/checkin")["notice"]["version"]
        m = self.marshal
        first = self.api.call("POST", "/api/v1/checkin", {
            "game_id": gid, "player_id": m["player_id"], "player_secret": m["secret"], "display_name": MARSHAL_NAME,
            "notice_version": notice}, token="x")["token"]
        # Listing the same marshal id again moves it to this game's check-in and gives the role.
        self.api.call("POST", "/api/v1/marshals", {"marshal_id": m["marshal_id"], "name": MARSHAL_NAME,
                                                   "player_id": m["player_id"]})
        token = self.api.call("POST", "/api/v1/checkin/token", token=first)["token"]
        from cryptography.hazmat.primitives import serialization

        public = base64.b64encode(m["key"].public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode("ascii")
        self.api.call("PUT", "/api/v1/checkin/me/marshal-key", {"marshal_id": m["marshal_id"], "name": MARSHAL_NAME,
                                                                "public_key": public}, token=token)
        field_id = self.api.call("GET", "/api/v1/checkin")["field"]["id"]
        readings = []
        over = self.rng.randrange(len(players))
        for i, p in enumerate(players):
            bb = 0.2
            velocity = 109.5 if i == over else self.rng.uniform(84.0, 104.0)
            rec: dict[str, Any] = {
                "reading_id": str(uuid.uuid4()), "replica_id": p.replica_id, "player_id": p.pid, "type": "checkin",
                "velocity_mps": round(velocity, 1), "bb_weight_g": bb, "chrono_id": "chrono-demo",
                "marshal_id": m["marshal_id"], "marshal_name": MARSHAL_NAME, "field_id": field_id,
                "game_id": str(gid), "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
            rec["energy_j"] = chronomod.round_half_away(chronomod.energy_j(bb, rec["velocity_mps"]), 3)
            rec["signature"] = base64.b64encode(m["key"].sign(chronomod.canonical(rec))).decode("ascii")
            readings.append(rec)
        for rec in readings:  # one series (a replica's) a request
            self.api.call("POST", "/api/v1/chrono/readings", {"readings": [rec]}, token=token)

    def publish_player(self, gid: int, player: Player) -> None:
        """Tells the read-only proxy whose view the "player's view" page shows (a file only the proxy reads)."""
        path = self.data / "player.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"game_id": gid, "player_id": player.pid, "token": player.token,
                                   "name": player.name, "team": player.team}))
        tmp.chmod(0o600)
        os.replace(tmp, path)

    # --- the game ----------------------------------------------------------------------------------------------

    def play(self, gid: int, players: list[Player]) -> None:
        start = time.monotonic()
        last_capture = last_report = 0.0
        last = start
        # One team has the better of the first half and the other the second: the lead changes hands.
        while True:
            now = time.monotonic()
            elapsed = now - start
            if elapsed >= self.game_s:
                return
            dt, last = now - last, now
            if elapsed - last_capture >= 4.0:
                last_capture = elapsed
                self.capture(elapsed)
            for p in players:
                if self.rng.random() < 0.05 or math.hypot(p.target[0] - p.x, p.target[1] - p.y) < 0.03:
                    zone = self.rng.choice(list(fieldmap.ZONES.values()))
                    p.target = (zone[0] + self.rng.uniform(-0.05, 0.05), zone[1] + self.rng.uniform(-0.05, 0.05))
                p.step(dt, self.rng)
            if elapsed - last_report >= 6.0:
                last_report = elapsed
                self.report(players)
            time.sleep(1.0)

    def capture(self, elapsed: float) -> None:
        """A team holds a box's button; which team is likelier changes with the game's clock."""
        phase = math.sin(elapsed / max(self.game_s, 1.0) * 2 * math.pi * 1.5)
        team = 0 if self.rng.random() < 0.5 + 0.35 * phase else 1
        box = self.rng.choice(self.boxes)
        box.hold(team + 1, int(PARAMS["capture_hold_ms"]) + 600)

    def report(self, players: list[Player]) -> None:
        for p in players:
            lat, lon = fieldmap.to_latlon(p.x, p.y)
            try:
                self.api.call("POST", "/api/v1/positions", {"lat": lat, "lon": lon, "accuracy_m": 5.0, "source": "gps",
                                                            "t": int(time.time() * 1000)}, token=p.token)
            except ApiError as exc:
                log.warning("position of %s: %s", p.name, exc)
