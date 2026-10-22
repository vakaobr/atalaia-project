# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Game-day sync on the controller (ADR-P4-11; phase 4, plan phase 16): the schedule, games made from it,
the roster as expected check-ins until the game starts, arrivals with the registration's ticket (the app's
check-in, a marshal's scan, a tick by name), walk-ins, the outcomes pushed back once, and the answers to
accounts' claims of player ids. Against an in-memory site server that checks every body and answer with
``sync_format`` (no PostgreSQL; the real one: server/tests/test_sync_e2e.py).

    cd controller && python -m unittest discover -s tests
"""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import logging
import os
import sqlite3
import tempfile
import time
import unittest
import uuid
from typing import Any, Optional

from p3support import GM, T0, P3Case, bearer, declaration, new_identity

from atalaia_controller import checkin_ticket, sync_format
from atalaia_controller.store import Store
from atalaia_controller.sync_client import SyncClient, SyncError

logging.getLogger("atalaia.sync").setLevel(logging.CRITICAL)
SCHEDULED = "0192f3a4-0000-7000-8000-00000000a001"


def ticket() -> tuple[bytes, str, str]:
    """A ticket secret, as the app sends it, and its SHA-256 as the roster carries it."""
    raw = os.urandom(32)
    return raw, checkin_ticket.secret_text(raw), hashlib.sha256(raw).hexdigest()


class FakeSite:
    """The site server's game-day endpoints in memory; every body and answer through the shared checks."""

    def __init__(self) -> None:
        self.schedule = [{"scheduled_game_id": SCHEDULED, "title": "Domingo de manhã no pinhal", "starts_at": T0 + 3600,
                          "ends_at": T0 + 3600 * 5, "status": "published", "mode_id": "org.atalaia.domination",
                          "teams": ["red", "blue"], "max_players": 60, "federation": "optional",
                          "predeclare_replicas": True, "registered": 0}]
        self.rosters: dict[str, list[dict[str, Any]]] = {SCHEDULED: []}
        self.claims: list[dict[str, Any]] = []
        self.posts: list[tuple[str, dict[str, Any]]] = []
        self.gets: list[str] = []
        self.games: dict[tuple[int, int], dict[str, Any]] = {}
        self.unsupported = False

    def get(self, path: str) -> dict[str, Any]:
        self.gets.append(path)
        if self.unsupported:
            raise SyncError("Not Found", 404)
        if path.startswith("/api/v1/sync/schedule"):
            answer = {"sync_version": 1, "games": copy.deepcopy(self.schedule)}
            kind = "schedule"
        elif path.startswith("/api/v1/sync/roster"):
            sid = path.rsplit("=", 1)[1]
            if sid not in self.rosters:
                raise SyncError("scheduled_game_not_found", 404)
            answer = {"sync_version": 1, "scheduled_game_id": sid, "status": "published", "federation": "optional",
                      "registrations": copy.deepcopy(self.rosters[sid])}
            kind = "roster"
        else:
            answer = {"sync_version": 1, "claims": copy.deepcopy(self.claims)}
            kind = "claims"
        sync_format.ANSWERS[kind](copy.deepcopy(answer))  # what a real site server sends passes this
        return answer

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        kind = path.rsplit("/", 1)[-1]
        body = sync_format.CHECKS[kind](json.loads(json.dumps(body)))
        self.posts.append((kind, body))
        if kind == "games":
            self.games[sync_format.game_key(body)] = body["meta"]
            return {"game": "g", "created": True, "state": body["meta"]["state"]}
        if kind in ("events",):
            return {"acked_id": body["events"][-1]["id"], "inserted": 0, "duplicates": 0}
        if kind == "chrono":
            return {"accepted": len(body["readings"]), "duplicates": 0, "refused": [], "violations": 0}
        return {}

    def bodies(self, kind: str) -> list[dict[str, Any]]:
        return [b for k, b in self.posts if k == kind]


def registration(name: str = "Falcão", ident: Optional[tuple[str, str]] = None, replicas: int = 1,
                 **extra: Any) -> tuple[dict[str, Any], str, bytes]:
    """A roster entry, the app's ticket text and the raw secret."""
    pid = (ident or new_identity())[0]
    raw, text, sha = ticket()
    entry = {"registration_id": str(uuid.uuid4()), "player_id": pid, "display_name": name,
             "ticket_sha256": sha, "replicas": [
                 {"declaration_id": str(uuid.uuid4()), "type": "aeg", "class": "rifle", "make_model": "M4"}
                 for _ in range(replicas)], **extra}
    return entry, text, raw


class GameDayCase(P3Case):
    cfg_overrides = {"federation": "optional", "sync_url": "https://site.example.org"}

    def setUp(self) -> None:
        super().setUp()
        self.site = FakeSite()
        self.sync = SyncClient(self.cfg, self.bundle.store, api_key="k" * 43, transport=self.site,
                               checkin=self.svc, wall=lambda: self.now)
        self.ctrl.sync = self.sync

    def cycle(self) -> None:
        self.assertTrue(self.sync.run_once(), self.sync.last_error)

    def from_schedule(self, **spec: Any) -> dict[str, Any]:
        self.cycle()
        r = self.client.post(f"/api/v1/schedule/{SCHEDULED}/game", json={"assignments": {"4": "zone"}, **spec},
                             headers=GM)
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def app_checkin(self, game_id: int, ident: tuple[str, str], reg: Optional[dict[str, Any]] = None,
                    ticket_text: Optional[str] = None, expect: int = 201, **extra: Any) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if reg is not None:
            body = {"registration_id": reg["registration_id"], "ticket": ticket_text}
        return self.check_in(game_id, ident=ident, expect=expect, **body, **extra)

    def rows(self, game_id: int) -> dict[str, dict[str, Any]]:
        return {r["player_id"]: r for r in self.client.get(f"/api/v1/games/{game_id}/checkins",
                                                           headers=GM).json()["checkins"]}


class ScheduleTests(GameDayCase):
    def test_a_game_made_from_the_schedule(self) -> None:
        self.cycle()
        listed = self.client.get("/api/v1/schedule", headers={"Authorization": "Bearer read-secret"}).json()
        self.assertEqual(([g["scheduled_game_id"] for g in listed["games"]], listed["games"][0]["games"]),
                         ([SCHEDULED], []))
        game = self.from_schedule()
        self.assertEqual((game["name"], game["mode_id"], game["teams"], game["duration_ms"], game["scheduled_game_id"]),
                         ("Domingo de manhã no pinhal", "org.atalaia.domination", ["red", "blue"], 4 * 3600 * 1000,
                          SCHEDULED))
        self.assertEqual(self.client.get("/api/v1/schedule", headers=GM).json()["games"][0]["games"], [game["id"]])
        self.cycle()
        meta = self.site.games[(game["id"], game["game_seed"])]
        self.assertEqual(meta["scheduled_game_id"], SCHEDULED)
        # A name, mode and teams of the GM's own win over the schedule's.
        self.client.post(f"/api/v1/games/{game['id']}/end", json={}, headers=GM)
        other = self.from_schedule(name="Tarde", teams=["green", "gold"])
        self.assertEqual((other["name"], other["teams"]), ("Tarde", ["green", "gold"]))
        r = self.client.post(f"/api/v1/schedule/{uuid.uuid4()}/game", json={}, headers=GM)
        self.assertEqual(r.status_code, 404)
        r = self.client.post(f"/api/v1/schedule/{SCHEDULED}/game", json={},
                             headers={"Authorization": "Bearer read-secret"})
        self.assertEqual(r.status_code, 403)

    def test_teams_that_do_not_fit_the_radio(self) -> None:
        self.site.schedule[0]["teams"] = ["Lobos do Norte da Serra!", "Raposas"]  # 24 bytes: too long for the radio
        self.cycle()
        r = self.client.post(f"/api/v1/schedule/{SCHEDULED}/game", json={}, headers=GM)
        self.assertEqual(r.status_code, 400)
        self.assertIn("give the teams", r.text)

    def test_an_older_site_server(self) -> None:
        self.site.unsupported = True
        self.cycle()  # no game-day endpoints: skipped, the cycle still succeeds
        self.assertFalse(self.sync.status()["game_day"]["supported"])


class RosterTests(GameDayCase):
    def test_expected_check_ins_until_the_game_starts(self) -> None:
        falcao, _, _ = registration("Falcão", federation_number="FPA-1", team_preference="red")
        coruja, _, _ = registration("Coruja", replicas=2)
        self.site.rosters[SCHEDULED] = [falcao, coruja]
        game = self.from_schedule()
        gid = game["id"]
        self.cycle()
        rows = self.rows(gid)
        self.assertEqual({p: (r["status"], r["display_name"], r["registered"]) for p, r in rows.items()},
                         {falcao["player_id"]: ("expected", "Falcão", True),
                          coruja["player_id"]: ("expected", "Coruja", True)})
        self.assertEqual(rows[falcao["player_id"]]["federation_number"], "FPA-1")
        listing = self.client.get(f"/api/v1/games/{gid}/checkins", headers=GM).json()
        self.assertEqual(listing["registrations"], {"expected": 2, "arrived": 0, "walkins": 0})
        chrono = self.chrono_list(gid)
        self.assertEqual(chrono["counts"]["pending"], 3)  # marshals see the replicas before anyone arrives
        self.assertNotIn("Falcão", self.everything_public(gid))
        # Changes before the start: one cancels, one changes, one more registers.
        later, _, _ = registration("Mocho")
        coruja2 = {**coruja, "display_name": "Coruja Grande", "replicas": coruja["replicas"][:1]}
        self.site.rosters[SCHEDULED] = [coruja2, later]
        self.cycle()
        rows = self.rows(gid)
        self.assertEqual({r["display_name"] for r in rows.values()}, {"Coruja Grande", "Mocho"})
        self.assertEqual(self.chrono_list(gid)["counts"]["pending"], 2)
        # After the start nothing from the site server changes the game.
        r = self.client.post(f"/api/v1/games/{gid}/start", headers=GM, json={"force": True})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["pending_declarations"], 0)  # nobody is at the field yet
        self.site.rosters[SCHEDULED] = []
        self.cycle()
        self.assertEqual(len(self.rows(gid)), 2)

    def test_what_the_check_in_refuses_is_dropped(self) -> None:
        reg, _, _ = registration(replicas=0)
        reg["replicas"] = [{"declaration_id": str(uuid.uuid4()), "type": "aeg", "class": "semi"}]  # Germany's
        reg["team_preference"] = "green"
        self.site.rosters[SCHEDULED] = [reg]
        gid = self.from_schedule()["id"]
        self.cycle()
        row = self.rows(gid)[reg["player_id"]]
        self.assertEqual((row["declarations"], row["team_preference"]), ([], None))


class ArrivalTests(GameDayCase):
    def setUp(self) -> None:
        super().setUp()
        self.reg, self.ticket_text, self.raw = registration()
        self.ident = (self.reg["player_id"], new_identity()[1])
        self.site.rosters[SCHEDULED] = [self.reg]
        self.gid = self.from_schedule()["id"]
        self.cycle()

    def test_the_app_checks_in_with_the_ticket(self) -> None:
        out = self.app_checkin(self.gid, self.ident, expect=403)  # a site-made id, no ticket: refused
        _, other_text, _ = ticket()
        self.app_checkin(self.gid, self.ident, self.reg, other_text, expect=403)
        self.app_checkin(self.gid, new_identity(), self.reg, self.ticket_text, expect=409)
        r = self.client.post("/api/v1/checkin", json={"game_id": self.gid, "player_id": self.ident[0],
                                                      "player_secret": self.ident[1], "display_name": "F",
                                                      "notice_version": 1, "registration_id": self.reg["registration_id"]})
        self.assertEqual(r.status_code, 400)
        out = self.app_checkin(self.gid, self.ident, self.reg, self.ticket_text)
        self.assertEqual((out["status"], out["token"][:5]), ("checked_in", "apt1."))
        row = self.rows(self.gid)[self.ident[0]]
        self.assertEqual((row["status"], row["federation_number"]), ("checked_in", None))
        self.assertEqual(len(row["declarations"]), 1)  # the pre-declared replica stays
        # The phone's secret is the identity from now on: the same id needs it, not the ticket.
        self.app_checkin(self.gid, self.ident, expect=200)
        listing = self.client.get(f"/api/v1/games/{self.gid}/checkins", headers=GM).json()
        self.assertEqual(listing["registrations"], {"expected": 0, "arrived": 1, "walkins": 0})

    def test_a_marshal_scans_the_printed_ticket(self) -> None:
        text = checkin_ticket.make({"registration_id": self.reg["registration_id"], "player_id": self.reg["player_id"],
                                    "secret": self.raw})
        r = self.client.post(f"/api/v1/games/{self.gid}/checkins/ticket", json={"ticket": text},
                             headers={"Authorization": "Bearer read-secret"})
        self.assertEqual(r.status_code, 403)  # staff only
        r = self.client.post(f"/api/v1/games/{self.gid}/checkins/ticket", json={"ticket": text}, headers=GM)
        self.assertEqual((r.status_code, r.json()["status"]), (200, "checked_in"), r.text)
        again = self.client.post(f"/api/v1/games/{self.gid}/checkins/ticket", json={"ticket": text}, headers=GM)
        self.assertEqual((again.status_code, again.json()["checked_in_at"]), (200, r.json()["checked_in_at"]))
        forged = checkin_ticket.make({"registration_id": self.reg["registration_id"],
                                      "player_id": self.reg["player_id"], "secret": os.urandom(32)})
        r = self.client.post(f"/api/v1/games/{self.gid}/checkins/ticket", json={"ticket": forged}, headers=GM)
        self.assertEqual(r.status_code, 403)
        stranger = checkin_ticket.make({"registration_id": str(uuid.uuid4()), "player_id": "p-abcdefgh2345",
                                        "secret": self.raw})
        r = self.client.post(f"/api/v1/games/{self.gid}/checkins/ticket", json={"ticket": stranger}, headers=GM)
        self.assertEqual(r.status_code, 404)
        r = self.client.post(f"/api/v1/games/{self.gid}/checkins/ticket", json={"ticket": "atalaia:checkin:AA"},
                             headers=GM)
        self.assertEqual(r.status_code, 400)

    def test_ticked_by_name(self) -> None:
        row = self.gm_patch(self.gid, self.reg["player_id"], status="checked_in")
        self.assertEqual(row["status"], "checked_in")

    def test_outcomes_go_back_once_after_the_game(self) -> None:
        self.app_checkin(self.gid, self.ident, self.reg, self.ticket_text)
        no_show, _, _ = registration("Coruja")
        self.site.rosters[SCHEDULED] = [self.reg, no_show]
        self.cycle()
        walk_in = self.check_in(self.gid, name="Rita Secreta")
        # One who registered but this controller never had in a roster: the app's id and ticket are kept.
        late_raw, late_text, late_sha = ticket()
        late_reg = str(uuid.uuid4())
        late = self.check_in(self.gid, name="Atrasada", registration_id=late_reg, ticket=late_text)
        self.client.post(f"/api/v1/games/{self.gid}/start", headers=GM, json={"force": True})
        self.cycle()
        self.assertEqual(self.site.bodies("checkins"), [])  # not before the game has ended
        self.client.post(f"/api/v1/games/{self.gid}/end", json={}, headers=GM)
        self.cycle()
        [body] = self.site.bodies("checkins")
        self.assertEqual((body["scheduled_game_id"], body["walkins"]), (SCHEDULED, 1))
        out = {r["registration_id"]: r for r in body["registrations"]}
        self.assertEqual(out[self.reg["registration_id"]]["outcome"], "checked_in")
        self.assertEqual(out[self.reg["registration_id"]]["declarations"][0]["state"], "pending")
        self.assertEqual(out[no_show["registration_id"]]["outcome"], "no_show")
        self.assertEqual((out[late_reg]["outcome"], out[late_reg]["ticket_sha256"], out[late_reg]["player_id"]),
                         ("checked_in", late_sha, late["player_id"]))
        self.assertIsNone(out[self.reg["registration_id"]].get("ticket_sha256"))  # the roster's: no proof needed
        text = json.dumps(self.site.posts, ensure_ascii=False)
        self.assertEqual(walk_in["status"], "checked_in")  # counted, not named
        for private in ("Falcão", "Coruja", "Rita Secreta", "Atrasada", self.ticket_text, late_text):
            self.assertNotIn(private, text)
        self.cycle()
        self.assertEqual(len(self.site.bodies("checkins")), 1, json.dumps(self.site.bodies("checkins"), indent=0))  # once


class ClaimTests(GameDayCase):
    def test_the_controller_answers_claims(self) -> None:
        game = self.new_game()
        mine = new_identity()
        self.check_in(game["id"], ident=mine)
        hand = self.client.post(f"/api/v1/games/{game['id']}/checkins", json={"display_name": "Sem app"},
                                headers=GM).json()["player_id"]
        sha = lambda s: hashlib.sha256(base64.urlsafe_b64decode(s + "=")).hexdigest()  # noqa: E731
        ids = [str(uuid.uuid4()) for _ in range(4)]
        self.site.claims = [{"claim_id": ids[0], "player_id": mine[0], "secret_sha256": sha(mine[1])},
                            {"claim_id": ids[1], "player_id": mine[0], "secret_sha256": "00" * 32},
                            {"claim_id": ids[2], "player_id": hand, "secret_sha256": "11" * 32},
                            {"claim_id": ids[3], "player_id": "p-abcdefgh2345", "secret_sha256": "22" * 32}]
        self.cycle()
        [body] = self.site.bodies("claims")
        self.assertEqual([r["result"] for r in body["results"]], ["confirmed", "refused", "refused", "unknown"])
        self.assertNotIn(sha(mine[1]), json.dumps(self.site.posts))  # nothing of the hash goes back


class StoreUpgradeTests(unittest.TestCase):
    def test_a_schema_6_file_gets_the_new_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "old.db")
            db = sqlite3.connect(path)
            db.execute("CREATE TABLE checkins (game_id INTEGER NOT NULL, player_id TEXT NOT NULL, status TEXT NOT NULL, "
                       "display_name TEXT, federation_number TEXT, federation_seen INTEGER NOT NULL DEFAULT 0, "
                       "team_preference TEXT, team INTEGER NOT NULL DEFAULT 0, squad INTEGER NOT NULL DEFAULT 0, "
                       "role TEXT NOT NULL DEFAULT 'player', manual INTEGER NOT NULL DEFAULT 0, notice_version INTEGER, "
                       "seq INTEGER NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL, checked_in_at REAL, "
                       "erased_at REAL, PRIMARY KEY (game_id, player_id))")
            db.execute("INSERT INTO checkins (game_id, player_id, status, seq, created_at, updated_at) "
                       "VALUES (1, 'p-abcdefgh2345', 'checked_in', 1, 0, 0)")
            db.commit()
            db.close()
            store = Store(path)
            row = store.checkin(1, "p-abcdefgh2345")
            self.assertEqual((row["registration_id"], row["from_roster"], store.get_setting("schema_version")),
                             (None, False, "9"))
            store.close()


if __name__ == "__main__":
    unittest.main()
