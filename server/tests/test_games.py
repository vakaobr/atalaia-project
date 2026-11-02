# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Game history (plan phase 20): the list with filters, the score timeline derived from the per-node
counters, the event log by type and time, what staff and spectators see (a delay while the game is live,
no secrets, no telemetry, no player ids), the field's settings, the public scoreboard, the per-field
retention and the person's game history in access, export and erasure (ADR-P4-8).

    python3 tools/docker_server.py test tests.test_games
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from atalaia_server import personal_data

from .test_sync import GAME, SyncTestCase, adjustment, envelope, event

ROLE = {"player": 1, "marshal": 4, "gm": 5, "spectator": 6, "admin": 7}
PRIVILEGED = {"marshal", "gm", "admin"}
OTHER_GAME = {"game_id": 77, "game_seed": 1}
PLAYER = "p-aaaabbbbcccc"
SOMEONE = "p-ddddeeeeffff"


class HistoryCase(SyncTestCase):
    async def role(self, role: str, field_id: Optional[uuid.UUID] = None) -> tuple[uuid.UUID, dict[str, str]]:
        user_id, name, secret = await self.make_user(with_totp=role in PRIVILEGED)
        await self.fetch("INSERT INTO user_field_roles (user_id, field_id, role_id) VALUES ($1, $2, $3)",
                         user_id, field_id or self.field_id, ROLE[role])
        return user_id, await self.auth(name, secret=secret)

    async def scores(self, counters: dict[str, dict[str, int]], game: Optional[dict[str, int]] = None) -> None:
        await self.post("scores", envelope(game=game, counters=counters))

    async def get(self, path: str, headers: dict[str, str], expect: int = 200, **params: Any) -> Any:
        r = await self.client.get(path, headers=headers, params=params)
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    async def backdate(self, minutes: int) -> None:
        """Everything received so far arrived ``minutes`` ago."""
        for table in ("game_score_samples", "game_events"):
            await self.fetch(f"UPDATE {table} SET received_at = received_at - make_interval(mins => $1)", minutes)

    async def put_settings(self, headers: dict[str, str], expect: int = 200, **body: Any) -> Any:
        r = await self.client.put(f"/api/v1/fields/{self.field_id}/history/settings", json=body, headers=headers)
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()


class HistoryListTests(HistoryCase):
    async def test_the_list_filters_and_who_may_read_it(self) -> None:
        ended = await self.make_game(state="ended", ended_at=1792003700.0)
        await self.events([event(1, etype="game.end", data={"reason": "time", "winner": "red"})])
        await self.scores({"node-3": {"red": 40}, "node-4": {"blue": 10}})
        live = await self.make_game(game=OTHER_GAME, mode_id="org.atalaia.bomb", created_at=1792100000.0,
                                    started_at=1792100100.0)
        _, player = await self.role("player")
        _, stranger = await self.role("player", (await self.make_field("arena"))[0])
        path = f"/api/v1/fields/{self.field_id}/history"
        body = await self.get(path, player)
        self.assertEqual([g["id"] for g in body["games"]], [live, ended])  # newest first
        first = body["games"][1]
        self.assertEqual((first["state"], first["winner"], [(t["team"], t["score"]) for t in first["teams"]]),
                         ("ended", "red", [("red", 40), ("blue", 10)]))
        self.assertNotIn("params", first)
        self.assertEqual([g["id"] for g in (await self.get(path, player, state="ended"))["games"]], [ended])
        self.assertEqual([g["id"] for g in (await self.get(path, player, mode="org.atalaia.bomb"))["games"]], [live])
        since = datetime.fromtimestamp(1792050000, tz=timezone.utc).isoformat()
        self.assertEqual([g["id"] for g in (await self.get(path, player, since=since))["games"]], [live])
        page = await self.get(path, player, limit=1)
        self.assertEqual(([g["id"] for g in page["games"]], page["next_before"] is not None), ([live], True))
        page = await self.get(path, player, limit=1, before=page["next_before"])
        self.assertEqual([g["id"] for g in page["games"]], [ended])
        await self.get(path, player, expect=400, state="archived")
        await self.get(path, stranger, expect=403)
        await self.get(f"/api/v1/games/{ended}/timeline", stranger, expect=403)
        await self.get(f"/api/v1/games/{ended}/log", stranger, expect=403)


class GameSeedTests(HistoryCase):
    async def test_only_staff_see_the_game_seed(self) -> None:
        """LIVE2-2: the seed (a game's id towards its controller) is not for players or spectators."""
        game = await self.make_game()
        seed = GAME["game_seed"]
        lists = (f"/api/v1/fields/{self.field_id}/games", f"/api/v1/fields/{self.field_id}/history")
        one = f"/api/v1/games/{game}"
        for role, sees in (("player", False), ("spectator", False), ("marshal", True), ("gm", True), ("admin", True)):
            _, headers = await self.role(role)
            body = await self.get(lists[0], headers)
            self.assertEqual(body[0].get("game_seed"), seed if sees else None, role)
            self.assertEqual(self.dig_seed(await self.get(lists[1], headers)), seed if sees else None, role)
            self.assertEqual((await self.get(one, headers)).get("game_seed"), seed if sees else None, role)
        user_id, name, secret = await self.make_user(with_totp=True)  # a game role of marshal alone shows it on the game
        await self.fetch("INSERT INTO user_game_roles (user_id, game, role_id) VALUES ($1, $2, $3)", user_id,
                         uuid.UUID(game), ROLE["marshal"])
        self.assertEqual((await self.get(one, await self.auth(name, secret=secret))).get("game_seed"), seed)

    @staticmethod
    def dig_seed(body: Any) -> Any:
        return body["games"][0].get("game_seed")


class TimelineTests(HistoryCase):
    async def test_the_timeline_follows_the_counters_and_the_adjustments(self) -> None:
        game = await self.make_game()
        await self.scores({"node-3": {"red": 10}})
        await self.backdate(3)
        await self.scores({"node-3": {"red": 30}, "node-4": {"blue": 5}})
        await self.scores({"node-3": {"red": 20}})  # lower: counters only grow, nothing is sampled
        await self.backdate(2)
        await self.events([adjustment(1, "red", -5)])
        _, gm = await self.role("gm")
        body = await self.get(f"/api/v1/games/{game}/timeline", gm)
        self.assertIsNone(body["delayed_until"])
        totals = [p["totals"] for p in body["points"]]
        self.assertEqual(totals, [{"red": 0, "blue": 0}, {"red": 10, "blue": 0}, {"red": 30, "blue": 5},
                                  {"red": 25, "blue": 5}])
        times = [p["t"] for p in body["points"]]
        self.assertEqual(times, sorted(times))
        # The last point is the game's totals, as the sync derives them (P4R10).
        detail = await self.get(f"/api/v1/games/{game}", gm)
        self.assertEqual(detail["totals"], totals[-1])
        self.assertEqual([(t["team"], t["score"]) for t in body["game"]["teams"]], [("red", 25), ("blue", 5)])
        self.assertEqual(await self.count("game_score_samples"), 3)


    async def test_points_are_in_game_time_and_pauses_do_not_count(self) -> None:
        """PKC-2: ``t`` is game time; the arrival time stays in ``at``. A delta carries its own game time; a counter's
        rise is placed from the arrival times and game times of the event batches around it."""
        start = 1792000100  # META's started_at
        game = await self.make_game()
        await self.events([event(1, t=60_000)])                     # arrives 60 s in, game time 60 s
        await self.events([event(2, t=70_000)], after=1)            # arrives 120 s in, game time 70 s: paused 50 s
        await self.scores({"node-3": {"red": 10}})
        await self.events([adjustment(3, "red", 4)], after=2)       # its own game time: 3 s
        await self.scores({"node-3": {"red": 20}})
        for seq, wall in ((1, 60), (2, 120), (3, 125)):
            await self.fetch("UPDATE game_events SET received_at = to_timestamp($1) WHERE seq = $2", start + wall, seq)
        for value, wall in ((10, 120), (20, 300)):
            await self.fetch("UPDATE game_score_samples SET received_at = to_timestamp($1) WHERE value = $2",
                             start + wall, value)
        _, gm = await self.role("gm")
        body = await self.get(f"/api/v1/games/{game}/timeline", gm)
        self.assertEqual(body["game"]["field_id"], str(self.field_id))
        self.assertEqual([(p["t"], p["totals"]["red"]) for p in body["points"]],
                         [(0, 0), (70, 10), (70, 14), (250, 24)])  # 70 s of game by 120 s of waiting; 250 = 70 + 180
        arrivals = [datetime.fromisoformat(p["at"]).timestamp() - start for p in body["points"]]
        self.assertEqual(arrivals, [0, 120, 125, 300])

    async def test_the_game_clock(self) -> None:
        from atalaia_server.services.history import game_clock

        start = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)

        def at(seconds: float) -> datetime:
            return start + timedelta(seconds=seconds)

        clock = game_clock(start, [(at(120), 70_000), (at(60), 60_000), (at(125), 3_000)])
        self.assertEqual([round(clock(at(s)), 1) for s in (-5, 0, 30, 60, 90, 120, 200)],
                         [0.0, 0.0, 30.0, 60.0, 65.0, 70.0, 150.0])  # the anchor that goes back in game time is left out
        self.assertEqual(game_clock(start, [])(at(42)), 42.0)  # no events: the arrival time, as before


class SpectatorTests(HistoryCase):
    async def test_a_live_game_is_delayed_and_redacted_for_spectators(self) -> None:
        game = await self.make_game()
        await self.scores({"node-3": {"red": 10}})
        await self.events([event(1, t=60_000, data={"zone": "alpha", "previous_team": None}),
                           event(2, t=70_000, etype="player.respawn", data={"player": PLAYER, "lives_left": 2}),
                           event(3, t=80_000, etype="hacking.solved", data={"puzzle": "p1", "code": "4711"}),
                           {**event(4, t=90_000, etype="battery.low", data={"percent": 9}), "prio": "telemetry"}])
        await self.backdate(10)
        await self.scores({"node-3": {"red": 50}})
        await self.events([event(5, t=700_000, data={"zone": "bravo"})], after=4)
        _, spectator = await self.role("spectator")
        _, marshal = await self.role("marshal")
        await self.put_settings((await self.role("admin"))[1], spectator_delay_s=120)

        log = await self.get(f"/api/v1/games/{game}/log", spectator)
        self.assertIsNotNone(log["delayed_until"])
        self.assertEqual([e["type"] for e in log["events"]], ["zone.captured", "player.respawn", "hacking.solved"])
        self.assertEqual(log["events"][1]["data"], {"lives_left": 2})  # no player id
        self.assertEqual(log["events"][2]["data"], {"puzzle": "p1"})  # no code (gm_only)
        self.assertNotIn("epoch", log["events"][0])
        self.assertEqual(log["types"], {"hacking.solved": 1, "player.respawn": 1, "zone.captured": 1})
        self.assertNotIn(PLAYER, json.dumps(log))
        timeline = await self.get(f"/api/v1/games/{game}/timeline", spectator)
        self.assertEqual(timeline["points"][-1]["totals"], {"red": 10, "blue": 0})

        staff = await self.get(f"/api/v1/games/{game}/log", marshal)
        self.assertIsNone(staff["delayed_until"])
        self.assertEqual(len(staff["events"]), 5)
        self.assertEqual(staff["events"][2]["data"]["code"], "4711")
        self.assertEqual(staff["events"][1]["data"]["player"], PLAYER)
        self.assertEqual((await self.get(f"/api/v1/games/{game}/timeline", marshal))["points"][-1]["totals"],
                         {"red": 50, "blue": 0})

        # Once the game has ended there is nothing left to hide behind a delay.
        await self.events([event(6, t=800_000, etype="game.end", data={"reason": "time"})], after=5)
        log = await self.get(f"/api/v1/games/{game}/log", spectator)
        self.assertIsNone(log["delayed_until"])
        self.assertEqual([e["id"] for e in log["events"]], [1, 2, 3, 5, 6])  # never the telemetry
        self.assertEqual((await self.get(f"/api/v1/games/{game}/timeline", spectator))["game"]["winner"], "red")

    async def test_a_game_role_is_enough(self) -> None:
        game = await self.make_game()
        user_id, name, _ = await self.make_user()
        await self.fetch("INSERT INTO user_game_roles (user_id, game, role_id) VALUES ($1, $2, $3)", user_id,
                         uuid.UUID(game), ROLE["spectator"])
        headers = await self.auth(name)
        await self.get(f"/api/v1/games/{game}/timeline", headers)
        await self.get(f"/api/v1/games/{game}/log", headers)
        await self.get(f"/api/v1/fields/{self.field_id}/history", headers, expect=403)  # the field's list: no


class LogTests(HistoryCase):
    async def test_by_type_team_and_time(self) -> None:
        game = await self.make_game()
        await self.events([event(i, t=i * 60_000, team="red" if i % 2 else "blue") for i in range(1, 9)]
                          + [event(9, t=30_000, etype="bomb.armed", data={"fuse_s": 40})])
        _, gm = await self.role("gm")
        path = f"/api/v1/games/{game}/log"
        everything = await self.get(path, gm)
        self.assertEqual([e["t"] for e in everything["events"]][:2], [30_000, 60_000])  # by game time
        self.assertEqual(everything["types"], {"bomb.armed": 1, "zone.captured": 8})
        self.assertEqual([e["id"] for e in (await self.get(path, gm, type="bomb.armed"))["events"]], [9])
        self.assertEqual(len((await self.get(path, gm, team="red"))["events"]), 5)
        window = await self.get(path, gm, from_ms=120_000, to_ms=240_000, type="zone.captured,bomb.armed")
        self.assertEqual([e["t"] for e in window["events"]], [120_000, 180_000, 240_000])
        page = await self.get(path, gm, limit=4)
        self.assertEqual(len(page["events"]), 4)
        self.assertIsNotNone(page["next"])


class SettingsTests(HistoryCase):
    async def test_the_settings(self) -> None:
        _, admin = await self.role("admin")
        _, gm = await self.role("gm")
        path = f"/api/v1/fields/{self.field_id}/history/settings"
        self.assertEqual(await self.get(path, gm),
                         {"public_scoreboard": False, "spectator_delay_s": 60, "retention_days": 90})
        await self.put_settings(gm, expect=403, public_scoreboard=True)
        body = await self.put_settings(admin, public_scoreboard=True, spectator_delay_s=0, retention_days=365)
        self.assertEqual(body, {"public_scoreboard": True, "spectator_delay_s": 0, "retention_days": 365})
        for name, value in (("spectator_delay_s", 3601), ("spectator_delay_s", -1), ("retention_days", 731),
                            ("retention_days", 29)):
            with self.subTest(name=name, value=value):
                await self.put_settings(admin, expect=400, **{name: value})
        await self.put_settings(admin, expect=422, colour="red")
        rows = await self.fetch("SELECT details FROM audit_log WHERE action = 'history_settings'")
        self.assertEqual(json.loads(rows[0]["details"]),
                         {"public_scoreboard": True, "spectator_delay_s": 0, "retention_days": 365})


class ScoreboardTests(HistoryCase):
    async def test_the_public_scoreboard(self) -> None:
        for path in ("/f/campo/scoreboard", "/f/campo/scoreboard.json"):
            self.assertEqual((await self.client.get(path)).status_code, 404)  # off by default
        _, admin = await self.role("admin")
        await self.put_settings(admin, public_scoreboard=True)
        empty = (await self.client.get("/f/campo/scoreboard.json")).json()
        self.assertEqual((empty["format"], empty["game"]), ("atalaia.scoreboard", None))

        await self.make_game(team_info={"red": {"display_name": "Lobos"}})
        await self.scores({"node-3": {"red": 10}})
        await self.events([event(1, etype="player.respawn", data={"player": PLAYER, "lives_left": 1})])
        await self.backdate(5)
        await self.scores({"node-3": {"red": 90}})
        board = (await self.client.get("/f/campo/scoreboard.json")).json()
        self.assertEqual(board["delay_s"], 60)
        self.assertEqual([(t["team"], t["display_name"], t["score"]) for t in board["game"]["teams"]],
                         [("red", "Lobos", 10), ("blue", None, 0)])
        self.assertNotIn(PLAYER, json.dumps(board))
        self.assertEqual(set(board["game"]), {"name", "mode_id", "state", "teams", "winner", "started_at", "ended_at"})
        r = await self.client.get("/f/campo/scoreboard?lang=en")
        self.assertEqual(r.status_code, 200)
        self.assertIn('<meta http-equiv="refresh" content="30">', r.text)
        self.assertIn("Lobos", r.text)
        self.assertIn("60 s behind", r.text)
        self.assertNotIn("<script", r.text)
        self.assertEqual((await self.client.head("/f/campo/scoreboard")).status_code, 200)
        pt = await self.client.get("/f/campo/scoreboard", headers={"Accept-Language": "pt-PT"})
        self.assertIn("Marcador: Campo", pt.text)
        de = await self.client.get("/f/campo/scoreboard", headers={"Accept-Language": "de-DE"})
        self.assertIn('<html lang="de">', de.text)
        self.assertIn("Anzeigetafel: Campo", de.text)
        self.assertIn("Punkte 60 s verzögert.", de.text)
        zh = await self.client.get("/f/campo/scoreboard?lang=zh-tw")
        self.assertIn('<html lang="zh-Hant-TW">', zh.text)
        self.assertIn("記分板：Campo", zh.text)
        self.assertIn("分數延遲 60 秒。每 30 秒更新一次。", zh.text)

        await self.events([event(2, etype="game.end", data={"reason": "time"})], after=1)
        board = (await self.client.get("/f/campo/scoreboard.json")).json()
        self.assertEqual((board["game"]["state"], board["game"]["winner"], board["delay_s"]), ("ended", "red", 0))
        self.assertEqual(board["game"]["teams"][0]["score"], 90)
        await self.put_settings(admin, public_scoreboard=False)
        self.assertEqual((await self.client.get("/f/campo/scoreboard.json")).status_code, 404)


class RetentionTests(HistoryCase):
    async def test_each_field_keeps_its_history_as_long_as_it_says(self) -> None:
        now = datetime.now(timezone.utc)
        other, other_key = await self.make_field("arena")
        await self.make_game()
        await self.make_game(key=other_key)
        await self.fetch("UPDATE games SET state = 'ended', ended_at = $1", now - timedelta(days=40))
        await self.fetch("INSERT INTO field_history_settings (field_id, retention_days) VALUES ($1, 30)", self.field_id)
        await self.scores({"node-3": {"red": 4}})
        async with self.app.state.sessionmaker() as db:
            counts = await personal_data.purge(db, now)
        self.assertEqual(counts["games"], 1)
        left = await self.fetch("SELECT field_id FROM games")
        self.assertEqual([r[0] for r in left], [other])  # 40 days is within the default 90 days
        self.assertEqual(await self.count("game_score_samples"), 0)  # with its game
        # The team results stay (maintainer decision 2026-10-30): totals only, no player, 365 days after the game.
        results = await self.fetch("SELECT field_id, team_totals, winner FROM game_results")
        self.assertEqual([(r["field_id"], json.loads(r["team_totals"]), r["winner"]) for r in results],
                         [(self.field_id, {"red": 4, "blue": 0}, "red")])
        async with self.app.state.sessionmaker() as db:
            counts = await personal_data.purge(db, now + timedelta(days=100))
        self.assertEqual((counts["games"], counts["game_results"], counts["game_results_expired"]), (1, 1, 0))
        async with self.app.state.sessionmaker() as db:
            counts = await personal_data.purge(db, now + timedelta(days=700))
        self.assertEqual((counts["games"], counts["game_results"], counts["game_results_expired"]), (0, 0, 2))
        self.assertEqual(await self.count("game_results"), 0)


class PersonalDataTests(HistoryCase):
    async def test_the_persons_game_history(self) -> None:
        game = await self.make_game()
        await self.make_game(game=OTHER_GAME)
        await self.events([event(1, etype="player.respawn", data={"player": PLAYER, "lives_left": 2}),
                           event(2, etype="player.respawn", data={"player": SOMEONE, "lives_left": 1}),
                           event(3, etype="kill.confirmed", data={"player": SOMEONE, "owner": PLAYER})])
        await self.post("events", envelope(game=OTHER_GAME, after_id=0,
                                           events=[event(1, etype="player.respawn",
                                                         data={"player": SOMEONE, "lives_left": 0})]))
        await self.scores({"node-3": {"red": 12}})
        user_id, name, _ = await self.make_user()
        await self.fetch("INSERT INTO field_player_ids (user_id, field_id, player_id) VALUES ($1, $2, $3)", user_id,
                         self.field_id, PLAYER)
        headers = await self.auth(name)
        data = (await self.client.get("/api/v1/me/data", headers=headers)).json()
        history = data["game_history"]
        self.assertEqual([h["game"] for h in history], [game])
        self.assertEqual((history[0]["player_ids"], history[0]["totals"], history[0]["registered"]),
                         ([PLAYER], {"red": 12, "blue": 0}, False))
        self.assertEqual([e["type"] for e in history[0]["events"]], ["player.respawn", "kill.confirmed"])
        r = await self.client.get("/api/v1/me/export", headers=headers)
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            self.assertEqual(json.loads(zf.read("export/game_history.json")), history)
            self.assertIn("game_history.json", zf.read("export/README.txt").decode("utf-8"))
        # Erasure: the link (the player id) goes; the field's events stay as they were, pseudonymous.
        async with self.app.state.sessionmaker() as db:
            await personal_data.erase(db, user_id)
            await db.commit()
            self.assertEqual(await personal_data.history.player_history(db, user_id), [])
        self.assertEqual(await self.count("game_events"), 4)
