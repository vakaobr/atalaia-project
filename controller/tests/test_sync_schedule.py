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

from p3support import GM, T0, Marshal, P3Case, bearer, declaration, new_identity

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from atalaia_controller import REPO_ROOT, checkin_binding, checkin_ticket, sync_format
from atalaia_controller.store import SCHEMA_VERSION, Store
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
        self.binding_asked = False  # the last roster pull asked for the binding keys (TKB-2)
        self.no_guests = False  # an older site server: a check-ins body with guests is refused (PWI-*)
        self.shared: list[dict[str, Any]] = []  # other fields' records by player (S14-5)
        self.no_shared_endpoint = False  # an older site server: the roster, but no shared chrono
        self.revoked: list[dict[str, Any]] = []  # the schedule answer's copies_revoked (PRIV-5)

    def get(self, path: str) -> dict[str, Any]:
        self.gets.append(path)
        if self.unsupported:
            raise SyncError("Not Found", 404)
        if path.startswith("/api/v1/sync/schedule"):
            answer = {"sync_version": 1, "games": copy.deepcopy(self.schedule)}
            if self.revoked:
                answer["copies_revoked"] = copy.deepcopy(self.revoked)
            kind = "schedule"
        elif path.startswith("/api/v1/sync/roster"):
            query = dict(q.split("=", 1) for q in path.split("?", 1)[1].split("&"))
            sid = query["scheduled_game_id"]
            self.binding_asked = query.get("binding") == "1"
            if sid not in self.rosters:
                raise SyncError("scheduled_game_not_found", 404)
            answer = {"sync_version": 1, "scheduled_game_id": sid, "status": "published", "federation": "optional",
                      "registrations": copy.deepcopy(self.rosters[sid])}
            kind = "roster"
        elif path.startswith("/api/v1/sync/chrono"):
            sid = path.rsplit("=", 1)[1]
            if self.no_shared_endpoint:
                raise SyncError("Not Found", 404)
            answer = {"sync_version": 1, "scheduled_game_id": sid, "players": copy.deepcopy(self.shared)}
            kind = "shared_chrono"
        else:
            answer = {"sync_version": 1, "claims": copy.deepcopy(self.claims)}
            kind = "claims"
        sync_format.ANSWERS[kind](copy.deepcopy(answer))  # what a real site server sends passes this
        return answer

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        kind = path.rsplit("/", 1)[-1]
        if kind == "checkins" and self.no_guests and "guests" in body:
            raise SyncError("invalid_body", 400, detail={"detail": "invalid_body", "error": "unknown_field",
                                                          "path": "guests"})
        body = sync_format.CHECKS[kind](json.loads(json.dumps(body)))
        self.posts.append((kind, body))
        if kind == "games":
            self.games[sync_format.game_key(body)] = body["meta"]
            return {"game": "g", "created": True, "state": body["meta"]["state"]}
        if kind in ("events",):
            return {"acked_id": body["events"][-1]["id"], "inserted": 0, "duplicates": 0}
        if kind == "chrono":
            return {"accepted": len(body["readings"]), "duplicates": 0, "refused": [], "violations": 0}
        if kind == "checkins":
            return {"linked": True, "applied": len(body["registrations"]), "ignored": 0, "declarations": 0,
                    "guests": len(body.get("guests") or ()), "guests_ignored": 0}
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
                                                      "notice_version": 2, "registration_id": self.reg["registration_id"]})
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

    def scan(self, text: str, headers: dict[str, str], expect: int = 200) -> dict[str, Any]:
        r = self.client.post(f"/api/v1/games/{self.gid}/checkins/ticket", json={"ticket": text}, headers=headers)
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    def printed(self, reg: Optional[dict[str, Any]] = None, raw: Optional[bytes] = None) -> str:
        reg = reg or self.reg
        return checkin_ticket.make({"registration_id": reg["registration_id"], "player_id": reg["player_id"],
                                    "secret": raw if raw is not None else self.raw})

    def test_a_marshal_takes_the_ticket_with_their_own_token(self) -> None:
        """TKT-1 to TKT-3: the marshal's token (staff for its game) takes the ticket; who and when are kept with
        the arrival, in the list and the CSV, and logged without the name; a second scan changes nothing."""
        _, token = self.make_marshal(self.gid)
        marshal_pid = self.svc.resolve(token).player_id
        with self.assertLogs("atalaia", level="INFO") as logs:
            row = self.scan(self.printed(), bearer(token))
        self.assertEqual((row["status"], row["already"], row["display_name"]), ("checked_in", False, "Falcão"))
        self.assertEqual((row["ticket_scanned_by"], row["ticket_scanned_at"]), (marshal_pid, self.now))
        line = next(m for m in logs.output if "ticket check-in" in m)
        self.assertIn(f"{self.reg['player_id']} by {marshal_pid}", line)
        self.assertNotIn("Falcão", "\n".join(logs.output))
        again = self.scan(self.printed(), bearer(token))
        self.assertEqual((again["already"], again["ticket_scanned_at"]), (True, self.now))
        csv_text = self.client.get(f"/api/v1/games/{self.gid}/checkins.csv", headers=GM).content.decode("utf-8-sig")
        header, line1 = csv_text.splitlines()[:2]
        self.assertIn("card_checked_at,ticket_scanned_by,ticket_scanned_at,manual", header)
        self.assertIn(marshal_pid, line1)
        # A newer ticket replaced this one: said with a code the app can tell apart.
        r = self.scan(self.printed(raw=os.urandom(32)), bearer(token), expect=403)
        self.assertTrue(r["detail"].startswith("ticket_not_newest:"), r)
        # Leaving erases who took the ticket with the rest of the row's data.
        self.client.delete(f"/api/v1/games/{self.gid}/checkins/{self.reg['player_id']}", headers=GM)
        stored = self.bundle.store.checkin(self.gid, self.reg["player_id"])
        self.assertEqual((stored["ticket_scanned_by"], stored["ticket_scanned_at"]), (None, None))

    def test_the_card_rule_holds_for_a_marshal_scan(self) -> None:
        """TKT-4: under the APD rule the ticket is not the card: pending until "card seen, matches"."""
        r = self.client.put("/api/v1/checkin/settings", headers=GM,
                            json={"apd": {"accepted": ["fpa"], "checkin": True}})
        self.assertEqual(r.status_code, 200, r.text)
        _, token = self.make_marshal(self.gid)
        row = self.scan(self.printed(), bearer(token))
        self.assertEqual((row["status"], row["already"], row["checked_in_at"]), ("pending", False, None))
        self.assertEqual(self.scan(self.printed(), bearer(token))["already"], True)
        r = self.client.patch(f"/api/v1/games/{self.gid}/checkins/{self.reg['player_id']}", headers=bearer(token),
                              json={"federation_seen": True})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["status"], "checked_in")
        self.assertEqual(r.json()["ticket_scanned_by"], r.json()["card_checked_by"])

    def staff_confirms(self, **apd: Any) -> str:
        """A marshal's token, then the "staff confirms" rule (and the APD rule if given): the marshal is checked
        in first, so the rule does not leave them pending."""
        _, token = self.make_marshal(self.gid)
        body: dict[str, Any] = {"confirm": "staff"}
        if apd:
            body["apd"] = apd
        r = self.client.put("/api/v1/checkin/settings", headers=GM, json=body)
        self.assertEqual(r.status_code, 200, r.text)
        return token

    def scan_with(self, headers: dict[str, str], expect: int = 200, **choice: Any) -> dict[str, Any]:
        r = self.client.post(f"/api/v1/games/{self.gid}/checkins/ticket", json={"ticket": self.printed(), **choice},
                             headers=headers)
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    def test_a_scan_asks_before_confirming_an_app_check_in(self) -> None:
        """TKS-1, TKS-2 (TKT-7 kept): a pending check-in made in the app is not confirmed by the scan alone. The
        answer is a decision with the app's name, when it checked in and the roster's name, and nothing changes;
        the same ticket with "app_checkin": "confirm" is the staff confirmation, recorded as the scan."""
        token = self.staff_confirms()
        marshal_pid = self.svc.resolve(token).player_id
        app_at = self.now
        out = self.app_checkin(self.gid, self.ident, self.reg, self.ticket_text, name="Falcão no telemóvel")
        self.assertEqual(out["status"], "pending")
        self.now += 60
        with self.assertLogs("atalaia", level="INFO") as logs:
            row = self.scan(self.printed(), bearer(token))
        self.assertEqual((row["status"], row["already"], row["confirmed"], row["discarded"]),
                         ("pending", False, False, False))
        self.assertEqual(row["decision"], {"kind": "app_checkin", "name": "Falcão no telemóvel", "at": app_at,
                                           "roster_name": "Falcão", "app_binding": "unbound"})
        self.assertEqual((row["ticket_scanned_by"], row["checked_in_at"]), (None, None))
        self.assertNotIn("Falcão", "\n".join(logs.output))
        self.assertIn("staff to decide (app_checkin)", "\n".join(logs.output))
        # A choice the controller does not know is refused.
        self.scan_with(bearer(token), expect=400, app_checkin="maybe")
        self.scan_with(bearer(token), expect=400, override="yes")
        with self.assertLogs("atalaia", level="INFO") as logs:
            row = self.scan_with(bearer(token), app_checkin="confirm")
        self.assertEqual((row["status"], row["already"], row["confirmed"], row["checked_in_at"]),
                         ("checked_in", False, True, self.now))
        self.assertNotIn("decision", row)
        self.assertEqual((row["ticket_scanned_by"], row["ticket_scanned_at"]), (marshal_pid, self.now))
        self.assertEqual(row["display_name"], "Falcão no telemóvel")
        self.assertFalse(row["apd_override"])
        self.assertIn(f"{self.reg['player_id']} by {marshal_pid}, checked_in (confirmed)",
                      next(m for m in logs.output if "ticket check-in" in m))
        # The app keeps working, and a choice sent again changes nothing.
        self.assertEqual(self.svc.resolve(out["token"]).player_id, self.reg["player_id"])
        again = self.scan_with(bearer(token), app_checkin="discard")
        self.assertEqual((again["status"], again["already"], again["discarded"]), ("checked_in", True, False))

    def test_staff_discard_an_app_check_in_for_the_ticket_holder(self) -> None:
        """TKS-3, TKS-4: staff discard the pending app check-in. What the app sent goes (its name, team preference,
        position sharing), the ticket holder arrives with the roster's name, the app's token stops working and its
        field identity is dropped, so the ticket holder's own app can check in with the ticket."""
        token = self.staff_confirms()
        out = self.app_checkin(self.gid, self.ident, self.reg, self.ticket_text, name="Outro", team_preference="red")
        r = self.client.put("/api/v1/checkin/me/position-sharing", headers=bearer(out["token"]),
                            json={"share_position": True})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("decision", self.scan(self.printed(), bearer(token)))
        with self.assertLogs("atalaia", level="INFO") as logs:
            row = self.scan_with(bearer(token), app_checkin="discard")
        self.assertEqual((row["status"], row["discarded"], row["confirmed"], row["already"]),
                         ("checked_in", True, False, False))
        self.assertEqual((row["display_name"], row["team_preference"], row["position_share"]), ("Falcão", None, False))
        self.assertIn("app check-in discarded", "\n".join(logs.output))
        self.assertNotIn("Outro", "\n".join(logs.output))
        r = self.client.get("/api/v1/checkin/me", headers=bearer(out["token"]))
        self.assertEqual(r.status_code, 401, r.text)
        self.assertIsNone(self.bundle.store.field_player(self.reg["player_id"]))
        # The ticket holder's own phone checks in with the ticket and is bound from then on.
        mine = (self.reg["player_id"], new_identity()[1])
        back = self.app_checkin(self.gid, mine, self.reg, self.ticket_text, expect=200, name="Falcão")
        self.assertEqual(back["status"], "checked_in")
        self.assertEqual(self.client.get("/api/v1/checkin/me", headers=bearer(back["token"])).status_code, 200)
        self.app_checkin(self.gid, self.ident, self.reg, self.ticket_text, expect=409)  # the old phone: no more
        # A later scan sees a check-in staff already matched: nothing to decide.
        again = self.scan(self.printed(), bearer(token))
        self.assertEqual((again["already"], "decision" in again), (True, False))

    def test_a_scan_leaves_the_card_check_to_do(self) -> None:
        """TKT-7 with TKT-4: under the APD rule's card check, a confirmed app check-in's scan is the staff step only;
        the player stays pending until "card seen, matches", and the scan is recorded once."""
        token = self.staff_confirms(accepted=["fpa"], checkin=True)
        marshal_pid = self.svc.resolve(token).player_id
        self.assertEqual(self.app_checkin(self.gid, self.ident, self.reg, self.ticket_text)["status"], "pending")
        self.assertEqual(self.scan(self.printed(), bearer(token))["decision"]["kind"], "app_checkin")
        row = self.scan_with(bearer(token), app_checkin="confirm")
        self.assertEqual((row["status"], row["already"], row["confirmed"], row["checked_in_at"]),
                         ("pending", False, False, None))
        self.assertEqual(row["ticket_scanned_by"], marshal_pid)
        again = self.scan(self.printed(), {**GM})
        self.assertEqual((again["status"], again["already"], again["ticket_scanned_by"]),
                         ("pending", True, marshal_pid))
        r = self.client.patch(f"/api/v1/games/{self.gid}/checkins/{self.reg['player_id']}", headers=bearer(token),
                              json={"federation_seen": True})
        self.assertEqual(r.json()["status"], "checked_in", r.text)
        after = self.scan(self.printed(), bearer(token))
        self.assertEqual((after["status"], after["already"], after["confirmed"]), ("checked_in", True, False))

    def test_a_scan_does_not_override_a_failing_membership(self) -> None:
        """TKS-5: a scan that would confirm over a stored verdict other than valid answers the verdict and changes
        nothing; only "override": true (the marshal's explicit call) confirms, with apd_override recorded."""
        token = self.staff_confirms(accepted=["fpa"], checkin=True)
        self.app_checkin(self.gid, self.ident, self.reg, self.ticket_text)
        # A pending check-in staff already matched with the ticket, whose card check stored "expired".
        self.store_update(card_checked_at=self.now, card_checked_by="gm", apd_verdict="expired",
                          ticket_scanned_at=self.now, ticket_scanned_by="gm")
        row = self.scan(self.printed(), bearer(token))
        self.assertEqual((row["status"], row["already"], row["confirmed"]), ("pending", False, False))
        self.assertEqual(row["decision"], {"kind": "membership", "verdict": "expired"})
        self.assertFalse(row["apd_override"])
        row = self.scan_with(bearer(token), override=True)
        self.assertEqual((row["status"], row["confirmed"], row["apd_override"]), ("checked_in", True, True))

    def store_update(self, **fields: Any) -> None:
        self.bundle.store.update_checkin(self.gid, self.reg["player_id"], **fields)

    def test_a_scan_of_a_confirmed_player_changes_nothing(self) -> None:
        """TKT-7: a player already confirmed (here by hand) is "already"; the scan records nothing."""
        token = self.staff_confirms()
        self.app_checkin(self.gid, self.ident, self.reg, self.ticket_text)
        r = self.client.patch(f"/api/v1/games/{self.gid}/checkins/{self.reg['player_id']}", headers=GM,
                              json={"status": "checked_in"})
        self.assertEqual(r.json()["status"], "checked_in", r.text)
        row = self.scan(self.printed(), bearer(token))
        self.assertEqual((row["status"], row["already"], row["confirmed"]), ("checked_in", True, False))
        self.assertEqual((row["ticket_scanned_by"], row["ticket_scanned_at"]), (None, None))

    def test_who_may_take_a_ticket(self) -> None:
        """TKT-1: staff only. A player's token, the read token and a "marshals" day code (access token) are
        refused; a "gm" day code is staff like the GM token."""
        plain = self.check_in(self.gid, name="Corvo")["token"]
        self.scan(self.printed(), bearer(plain), expect=403)
        self.scan(self.printed(), {"Authorization": "Bearer read-secret"}, expect=403)
        def day_code(scope: str) -> str:
            r = self.client.post("/api/v1/tokens", headers=GM, json={"label": f"desk {scope}", "scope": scope})
            self.assertEqual(r.status_code, 201, r.text)
            return r.json()["token"]
        self.scan(self.printed(), bearer(day_code("marshals")), expect=403)
        self.assertEqual(self.rows(self.gid)[self.reg["player_id"]]["status"], "expected")
        row = self.scan(self.printed(), bearer(day_code("gm")))
        self.assertEqual((row["status"], row["ticket_scanned_by"]), ("checked_in", "gm"))

    def test_tickets_are_rate_limited_per_staff_id(self) -> None:
        """TKT-2: at most max(60, 6 x rate_per_minute) scans a minute per staff id, bad ones included; another
        marshal and the GM keep their own count."""
        _, token = self.make_marshal(self.gid)
        limit = self.svc.ticket_rate.per_minute
        for _ in range(limit):
            self.scan("atalaia:ticket:AA", bearer(token), expect=400)
        r = self.scan(self.printed(), bearer(token), expect=429)
        self.assertIn("too many", r["detail"])
        self.assertEqual(self.scan(self.printed(), GM)["status"], "checked_in")

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


    def _walkins_then_end(self) -> tuple[dict[str, Any], str]:
        """The registered player, a walk-in with a declared replica, a walk-in who left before checking in
        and a marshal who walked in; then the game ends."""
        self.app_checkin(self.gid, self.ident, self.reg, self.ticket_text)
        decl = str(uuid.uuid4())
        walk_in = self.check_in(self.gid, name="Rita Secreta", federation_number="FPA-12345",
                                replicas=[{"declaration_id": decl, "type": "aeg", "class": "rifle",
                                           "make_model": "Tokyo Marui M4"}])
        self.make_marshal(self.gid)
        self.client.post(f"/api/v1/games/{self.gid}/start", headers=GM, json={"force": True})
        self.client.post(f"/api/v1/games/{self.gid}/end", json={}, headers=GM)
        return walk_in, decl

    def test_walkins_go_as_guests_with_push_walkins(self) -> None:
        """Decisions PWI-*: with [sync] push_walkins the walk-ins who are players go as guests, with their
        display name and declarations' states; never a federation number, a make and model or a team."""
        self.cfg.sync_push_walkins = True
        walk_in, decl = self._walkins_then_end()
        self.cycle()
        [body] = self.site.bodies("checkins")
        self.assertEqual(body["walkins"], 2)  # the marshal counts, as before
        self.assertEqual(body["guests"], [{"player_id": walk_in["player_id"], "display_name": "Rita Secreta",
                                           "declarations": [{"declaration_id": decl, "type": "aeg", "class": "rifle",
                                                             "state": "pending", "reading_id": None}]}])
        text = json.dumps(self.site.posts, ensure_ascii=False)
        for private in ("FPA-12345", "Tokyo Marui", "Falcão", self.ticket_text):
            self.assertNotIn(private, text)
        game_day = self.sync.status()["game_day"]
        self.assertEqual(game_day["walkins"], {"push": True, "supported": True, "guests_sent": 1})
        self.cycle()
        self.assertEqual(len(self.site.bodies("checkins")), 1)  # once, until the outcomes change

    def test_walkins_are_a_count_without_push_walkins(self) -> None:
        self._walkins_then_end()
        self.cycle()
        [body] = self.site.bodies("checkins")
        self.assertEqual(body["walkins"], 2)
        self.assertNotIn("guests", body)
        self.assertNotIn("Rita Secreta", json.dumps(self.site.posts, ensure_ascii=False))
        self.assertEqual(self.sync.status()["game_day"]["walkins"], {"push": False, "supported": True,
                                                                     "guests_sent": 0})

    def test_an_older_site_server_gets_the_count(self) -> None:
        """A site server that does not know ``guests`` refuses it: the count goes, and no guests again."""
        self.cfg.sync_push_walkins = True
        self.site.no_guests = True
        self._walkins_then_end()
        with self.assertLogs("atalaia.sync", "WARNING"):
            self.cycle()
        [body] = self.site.bodies("checkins")
        self.assertNotIn("guests", body)
        self.assertEqual(body["walkins"], 2)
        self.assertFalse(self.sync.status()["game_day"]["walkins"]["supported"])
        self.cycle()
        self.assertEqual(len(self.site.bodies("checkins")), 1)


class BindingTests(GameDayCase):
    """TKB-1 to TKB-8: the roster's binding key (asked for with ``binding=1``), the registering phone's proof at
    check-in, and what staff see: bound or unbound. Never a refusal for a missing or wrong proof."""

    def setUp(self) -> None:
        super().setUp()
        self.phone = Ed25519PrivateKey.generate()
        key = base64.b64encode(self.phone.public_key().public_bytes(serialization.Encoding.Raw,
                                                                    serialization.PublicFormat.Raw)).decode()
        self.reg, self.ticket_text, self.raw = registration(binding_key=key)
        self.ident = (self.reg["player_id"], new_identity()[1])
        self.site.rosters[SCHEDULED] = [self.reg]
        self.gid = self.from_schedule()["id"]
        self.cycle()

    def challenge(self) -> str:
        r = self.client.get("/api/v1/checkin/challenge")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["expires_in"], r.headers["cache-control"]), (300, "no-store"))
        return r.json()["challenge"]

    def proof(self, ident: tuple[str, str], key: Optional[Ed25519PrivateKey] = None,
              challenge: Optional[str] = None, game_id: Optional[int] = None) -> dict[str, str]:
        challenge = challenge or self.challenge()
        msg = checkin_binding.message(challenge, game_id or self.gid, self.reg["registration_id"], ident[0],
                                      base64.urlsafe_b64decode(ident[1] + "="))
        sig = (key or self.phone).sign(msg)
        return {"challenge": challenge, "signature": base64.urlsafe_b64encode(sig).decode().rstrip("=")}

    def staff_confirm(self) -> str:
        _, token = self.make_marshal(self.gid)
        r = self.client.put("/api/v1/checkin/settings", json={"confirm": "staff"}, headers=GM)
        self.assertEqual(r.status_code, 200, r.text)
        return token

    def printed(self) -> str:
        return checkin_ticket.make({"registration_id": self.reg["registration_id"], "player_id": self.reg["player_id"],
                                    "secret": self.raw})

    def test_the_roster_carries_the_key_when_asked(self) -> None:
        self.assertTrue(self.site.binding_asked)
        row = self.bundle.store.checkin(self.gid, self.reg["player_id"])
        self.assertEqual(row["binding_key"], self.reg["binding_key"])
        self.assertIsNone(self.rows(self.gid)[self.reg["player_id"]]["app_binding"])  # expected: no app check-in yet

    def test_the_registering_phone_is_bound(self) -> None:
        token = self.staff_confirm()
        with self.assertLogs("atalaia", level="INFO") as logs:
            out = self.app_checkin(self.gid, self.ident, self.reg, self.ticket_text, binding=self.proof(self.ident))
        self.assertEqual((out["status"], out["app_binding"]), ("pending", "bound"))
        self.assertNotIn("did not verify", "\n".join(logs.output))
        self.assertEqual(self.rows(self.gid)[self.reg["player_id"]]["app_binding"], "bound")
        # The marshal still decides (TKS-1 stays): the decision says the registering phone proved it.
        r = self.client.post(f"/api/v1/games/{self.gid}/checkins/ticket", json={"ticket": self.printed()},
                             headers=bearer(token))
        self.assertEqual(r.json()["decision"]["app_binding"], "bound", r.text)
        r = self.client.post(f"/api/v1/games/{self.gid}/checkins/ticket",
                             json={"ticket": self.printed(), "app_checkin": "confirm"}, headers=bearer(token))
        self.assertEqual((r.json()["status"], r.json()["app_binding"]), ("checked_in", "bound"))

    def test_a_copy_of_the_ticket_is_unbound(self) -> None:
        """Another phone with a copy of the ticket: no proof, or a proof with its own key. It checks in as before
        (no flag day), shown as unbound; staff discard it and the registering phone then checks in bound."""
        token = self.staff_confirm()
        thief = (self.reg["player_id"], new_identity()[1])
        out = self.app_checkin(self.gid, thief, self.reg, self.ticket_text,
                               binding=self.proof(thief, key=Ed25519PrivateKey.generate()))
        self.assertEqual(out["app_binding"], "unbound")
        r = self.client.post(f"/api/v1/games/{self.gid}/checkins/ticket", json={"ticket": self.printed()},
                             headers=bearer(token))
        self.assertEqual(r.json()["decision"]["app_binding"], "unbound")
        r = self.client.post(f"/api/v1/games/{self.gid}/checkins/ticket",
                             json={"ticket": self.printed(), "app_checkin": "discard"}, headers=bearer(token))
        self.assertEqual((r.json()["discarded"], r.json()["app_binding"]), (True, None))
        back = self.app_checkin(self.gid, self.ident, self.reg, self.ticket_text, expect=200,
                                binding=self.proof(self.ident))
        self.assertEqual(back["app_binding"], "bound")

    def test_a_proof_for_another_check_in_does_not_bind(self) -> None:
        other = (self.reg["player_id"], new_identity()[1])
        proof = self.proof(other)  # signed for another phone's secret
        out = self.app_checkin(self.gid, self.ident, self.reg, self.ticket_text, binding=proof)
        self.assertEqual(out["app_binding"], "unbound")
        # The phone that holds the identity proves the key later: bound from then on.
        again = self.app_checkin(self.gid, self.ident, self.reg, self.ticket_text, expect=200,
                                 binding=self.proof(self.ident))
        self.assertEqual(again["app_binding"], "bound")

    def test_an_older_app_is_unbound(self) -> None:
        out = self.app_checkin(self.gid, self.ident, self.reg, self.ticket_text)
        self.assertEqual(out["app_binding"], "unbound")

    def test_challenges(self) -> None:
        """A challenge from another controller (or restart), a broken one, a proof without a registration, or a
        proof of the wrong shape."""
        forged = checkin_binding.Challenges(key=os.urandom(32)).issue()
        r = self.client.post("/api/v1/checkin", json={
            "game_id": self.gid, "player_id": self.ident[0], "player_secret": self.ident[1], "display_name": "F",
            "notice_version": 2, "registration_id": self.reg["registration_id"], "ticket": self.ticket_text,
            "binding": self.proof(self.ident, challenge=forged)})
        self.assertEqual(r.status_code, 409, r.text)
        self.assertTrue(r.json()["detail"].startswith("binding_challenge_expired"))
        self.check_in(self.gid, binding=self.proof(self.ident), expect=400)  # a walk-in has nothing to prove
        for bad in ({"challenge": self.challenge()}, {"challenge": "x" * 43, "signature": "A" * 86},
                    {**self.proof(self.ident), "extra": 1}, "proof"):
            self.app_checkin(self.gid, self.ident, self.reg, self.ticket_text, binding=bad,
                             expect=409 if isinstance(bad, dict) and len(bad) == 2 else 400)
        self.assertIsNone(self.bundle.store.checkin(self.gid, self.reg["player_id"])["app_checkin_at"])

    def test_a_challenge_expires(self) -> None:
        clock = [1000.0]
        ch = checkin_binding.Challenges(clock=lambda: clock[0], key=b"k" * 32)
        text = ch.issue()
        self.assertTrue(ch.valid(text))
        clock[0] += 300
        self.assertTrue(ch.valid(text))
        clock[0] += 1
        self.assertFalse(ch.valid(text))
        self.assertFalse(ch.valid(text[:-1] + ("A" if text[-1] != "A" else "B")))

    def test_without_a_key_in_the_roster(self) -> None:
        """A registration made on the web page or by staff (no key): a proof is ignored, the check-in unbound."""
        self.reg.pop("binding_key")
        self.cycle()
        self.assertIsNone(self.bundle.store.checkin(self.gid, self.reg["player_id"])["binding_key"])
        out = self.app_checkin(self.gid, self.ident, self.reg, self.ticket_text, binding=self.proof(self.ident))
        self.assertEqual(out["app_binding"], "unbound")


class BindingVectorTests(unittest.TestCase):
    """protocol/vectors/checkin.json ``binding``: the challenge, the message and the signature both controllers
    check (the Dart side: app/test/protocol/checkin_binding_test.dart)."""

    V = json.loads((REPO_ROOT / "protocol" / "vectors" / "checkin.json").read_text(encoding="utf-8"))["binding"]

    def args(self, case: dict[str, Any]) -> tuple[Any, ...]:
        v = {**self.V, **case}
        secret = base64.urlsafe_b64decode(v["player_secret"] + "=")
        msg = checkin_binding.message(v["challenge"], v["game_id"], v["registration_id"], v["player_id"], secret)
        return v["public_key"], msg, base64.urlsafe_b64decode(v["signature"] + "==")

    def test_valid(self) -> None:
        v = self.V
        key, msg, sig = self.args({})
        self.assertEqual(msg.decode(), v["message"])
        self.assertTrue(checkin_binding.verify(key, msg, sig))
        private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(v["seed"]))
        raw = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.assertEqual(base64.b64encode(raw).decode(), v["public_key"])

    def test_invalid(self) -> None:
        for case in self.V["invalid"]:
            with self.subTest(case["name"]):
                self.assertFalse(checkin_binding.verify(*self.args(case)))

    def test_the_challenge(self) -> None:
        v = self.V
        key = bytes.fromhex(v["challenge_key"])
        for at, ok in ((v["clock"], True), (v["clock"] + v["ttl"], True), (v["clock"] + v["ttl"] + 1, False)):
            self.assertEqual(checkin_binding.Challenges(clock=lambda at=at: at, key=key).valid(v["challenge"]), ok)
        self.assertFalse(checkin_binding.Challenges(clock=lambda: v["clock"], key=bytes(32)).valid(v["challenge"]))


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


ARENA = "Arena Norte"
VECTORS = json.loads((REPO_ROOT / "protocol" / "vectors" / "sync.json").read_text(encoding="utf-8"))


class SharedChronoTests(GameDayCase):
    """Other fields' chrono records of the roster's players (decision S14-5): pulled with the roster, kept
    apart, shown as from another field, never judged, counted or pushed back."""

    def setUp(self) -> None:
        super().setUp()
        self.other = Marshal("m-rui", "Rui", field_id="arena")
        self.falcao, _, _ = registration("Falcão")
        self.coruja, _, _ = registration("Coruja")
        self.site.rosters[SCHEDULED] = [self.falcao, self.coruja]
        self.gid = self.from_schedule()["id"]
        self.pid = self.falcao["player_id"]
        self.cycle()  # the roster, and nothing shared yet

    def shared(self, pid: str, *records: dict[str, Any], field: str = ARENA) -> dict[str, Any]:
        return {"player_id": pid, "readings": [{"field": field, "record": json.dumps(r, ensure_ascii=False),
                                                "public_key": self.other.public_b64} for r in records]}

    def record(self, velocity: float = 100.0, pid: str = "p-arenaarena22", **kw: Any) -> dict[str, Any]:
        return self.other.reading(str(uuid.uuid4()), pid, velocity, when=T0 - 7200, **kw)

    def listed(self, pid: Optional[str] = None) -> list[dict[str, Any]]:
        players = {p["player_id"]: p for p in self.chrono_list(self.gid)["players"]}
        return players[pid or self.pid]["shared_readings"]

    def test_the_records_show_marked_and_never_count(self) -> None:
        before = self.chrono_list(self.gid)
        rec = self.record(250.0, rtype="spotcheck")  # far over any limit: would refuse a replica if it counted
        self.site.shared = [self.shared(self.pid, rec)]
        self.cycle()
        shown = self.listed()
        self.assertEqual([(s["reading_id"], s["field"], s["from_other_field"], s["type"], s["energy_j"],
                           s["marshal_name"]) for s in shown],
                         [(rec["reading_id"], ARENA, True, "spotcheck", rec["energy_j"], "Rui")])
        after = self.chrono_list(self.gid)
        self.assertEqual((after["counts"], self.listed(self.coruja["player_id"])), (before["counts"], []))
        self.assertEqual([d["state"] for p in after["players"] for d in p["declarations"]], ["pending", "pending"])
        row = self.rows(self.gid)[self.pid]
        self.assertEqual([s["reading_id"] for s in row["shared_readings"]], [rec["reading_id"]])
        # Not the field's own readings: not in the player's data, not judged, never sent to the site server.
        self.assertEqual(self.client.get(f"/api/v1/players/{self.pid}/chrono", headers=GM).json()["readings"], [])
        self.assertEqual(self.bundle.store.readings(player_id=self.pid), [])
        self.cycle()
        self.assertEqual(self.site.bodies("chrono"), [])
        self.assertEqual(self.sync.status()["game_day"]["shared_chrono"], {"supported": True, "stored": 1})

    def test_the_roster_players_only_and_only_what_verifies(self) -> None:
        good = self.record(100.0)
        tampered = {**self.record(100.0), "velocity_mps": 90.0}  # changed after it was signed
        stranger = self.record(110.0)
        self.site.shared = [self.shared(self.pid, good, tampered),
                            self.shared("p-zzzzzzzzzzzz", stranger)]
        with self.assertLogs("atalaia.sync", level="WARNING") as logs:
            self.cycle()
        self.assertIn("2 records dropped", "\n".join(logs.output))
        self.assertEqual([s["reading_id"] for s in self.listed()], [good["reading_id"]])
        self.assertEqual(self.bundle.store.shared_readings("p-zzzzzzzzzzzz"), [])

    def test_a_local_measurement_is_never_replaced(self) -> None:
        mine = self.record(95.0)
        self.bundle.store.add_reading(mine, str(uuid.uuid4()), "pass", T0)
        other = self.record(98.0)
        self.site.shared = [self.shared(self.pid, mine, other)]
        self.cycle()
        self.assertEqual([s["reading_id"] for s in self.listed()], [other["reading_id"]])
        self.assertEqual([r["reading_id"] for r in self.bundle.store.readings()], [mine["reading_id"]])

    def test_a_withdrawn_consent_takes_the_records_away(self) -> None:
        self.site.shared = [self.shared(self.pid, self.record())]
        self.cycle()
        self.assertEqual(len(self.listed()), 1)
        self.site.shared = []  # the person withdrew, or the field stopped sharing
        self.cycle()
        self.assertEqual(self.listed(), [])
        self.assertEqual(self.bundle.store.shared_readings(self.pid), [])

    def test_nothing_after_the_game_starts(self) -> None:
        self.site.shared = [self.shared(self.pid, self.record())]
        self.cycle()
        self.client.post(f"/api/v1/games/{self.gid}/start", headers=GM, json={"force": True})
        pulls = [g for g in self.site.gets if "/sync/chrono" in g]
        self.site.shared = [self.shared(self.pid, self.record(), self.record(101.0))]
        self.cycle()
        self.assertEqual([g for g in self.site.gets if "/sync/chrono" in g], pulls)  # no new pull
        self.assertEqual(len(self.bundle.store.shared_readings(self.pid)), 1)  # kept as it was

    def test_an_erased_account_takes_the_copies_away_even_after_the_game_starts(self) -> None:
        """PRIV-5 (Art. 17(2)): the schedule answer names the players who erased their account or withdrew a consent;
        their copies go at once, game started or not, and the field's own readings stay."""
        self.site.shared = [self.shared(self.pid, self.record()), self.shared(self.coruja["player_id"], self.record())]
        self.cycle()
        self.client.post(f"/api/v1/games/{self.gid}/start", headers=GM, json={"force": True})
        self.assertEqual(len(self.bundle.store.shared_readings(self.pid)), 1)
        self.assertIn("revocations=1", [g for g in self.site.gets if "/sync/schedule" in g][-1])
        self.site.revoked = [{"player_id": self.pid, "reason": "erasure", "at": int(T0)}]
        self.cycle()
        self.assertEqual(self.bundle.store.shared_readings(self.pid), [])
        self.assertEqual(len(self.bundle.store.shared_readings(self.coruja["player_id"])), 1)  # someone else: kept
        self.cycle()  # the record comes every cycle until the retention ends: nothing more to do
        self.assertEqual(self.bundle.store.shared_readings(self.pid), [])

    def test_an_older_site_server(self) -> None:
        self.site.no_shared_endpoint = True
        self.cycle()  # the roster still applies; the records are skipped quietly
        self.assertEqual(len(self.rows(self.gid)), 2)
        self.assertEqual(self.sync.status()["game_day"]["shared_chrono"]["supported"], False)
        self.assertTrue(self.sync.status()["game_day"]["supported"])

    def test_retention_and_erasure(self) -> None:
        old = self.other.reading(str(uuid.uuid4()), "p-arenaarena22", 100.0, when=T0 - 366 * 86400)
        fresh = self.record()
        self.site.shared = [self.shared(self.pid, old, fresh)]
        self.cycle()
        self.assertEqual([s["reading_id"] for s in self.listed()], [fresh["reading_id"]])  # too old: not kept
        keep = {"field_name": ARENA, "public_key": b"k" * 32, "record_json": json.dumps(fresh)}
        self.bundle.store.set_shared_readings(self.pid, [
            {**keep, "reading_id": "old-one", "timestamp": "2025-01-01T00:00:00Z"},
            {**keep, "reading_id": "new-one", "timestamp": "2027-01-10T00:00:00Z"}], T0)
        self.assertEqual(self.svc.purge(force=True)["shared_readings"], 1)  # the readings' 365 days
        self.assertEqual([r["reading_id"] for r in self.bundle.store.shared_readings(self.pid)], ["new-one"])
        self.client.delete(f"/api/v1/players/{self.pid}/chrono", headers=GM)  # the player's erasure of chrono data
        self.assertEqual(self.bundle.store.shared_readings(self.pid), [])
        self.bundle.store.set_shared_readings(self.pid, [{**keep, "reading_id": "again",
                                                          "timestamp": "2027-01-10T00:00:00Z"}], T0)
        self.client.delete(f"/api/v1/players/{self.pid}", headers=GM)  # and of the whole identity
        self.assertEqual(self.bundle.store.shared_readings(self.pid), [])

    def test_the_shared_vectors(self) -> None:
        """protocol/vectors/sync.json's shared_chrono_apply: what a controller keeps of an answer."""
        records = {v["record"]["reading_id"]: v["record"] for v in json.loads(
            (REPO_ROOT / "protocol" / "vectors" / "chrono_record.json").read_text(encoding="utf-8"))["valid"]}
        store = self.svc.store
        first = VECTORS["shared_chrono_apply"][0]
        for vec in VECTORS["shared_chrono_apply"]:
            with self.subTest(vector=vec["name"]):
                store.delete_readings(before="9999-01-01T00:00:00Z")
                for rid in vec["local_reading_ids"]:
                    store.add_reading(records[rid], str(uuid.uuid4()), "pass", T0)
                if vec.get("after") == "apply_answer_first":  # what an earlier pull left
                    self.svc.apply_shared_chrono(self.gid, first["roster"], sync_format.ANSWERS["shared_chrono"](
                        copy.deepcopy(first["answer"])))
                answer = sync_format.ANSWERS["shared_chrono"](copy.deepcopy(vec["answer"]))
                result = self.svc.apply_shared_chrono(self.gid, vec["roster"], answer)
                self.assertEqual({p: sorted(r["reading_id"] for r in store.shared_readings(p)) for p in vec["roster"]},
                                 {p: sorted(ids) for p, ids in vec["stored"].items()})
                self.assertEqual(result["dropped"], vec["dropped"])


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
                             (None, False, str(SCHEMA_VERSION)))
            self.assertEqual((row["binding_key"], row["app_bound"]), (None, None))  # schema 23 (TKB-4): unbound
            store.close()


if __name__ == "__main__":
    unittest.main()
