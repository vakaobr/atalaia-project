# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Registration and the game-day sync on PostgreSQL 16 (ADR-P4-11; plan phase 16, decisions S16-*).

Registering with pre-declared replicas, the ticket (only its hash kept), the window and the places,
changing and cancelling, the staff's list; claims of a phone's player id confirmed by the controller;
the schedule, roster and claims the controller pulls (every answer checked with the controller's own
``sync_format.ANSWERS``); a game linked to its scheduled game; the outcomes pushed back; and the
personal data rules for all of it.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from atalaia_controller import checkin_ticket, sync_format

from atalaia_server import personal_data
from atalaia_server.models import ScheduledGame

from .base import PASSWORD
from .test_sync import GAME, META, SyncTestCase, envelope

UTC = timezone.utc
REPLICA = "8a1f0c2e-7b3d-4c5e-8f9a-0b1c2d3e4f50"


def hour(hours: float) -> datetime:
    return datetime.now(UTC).replace(microsecond=0) + timedelta(hours=hours)


def secret() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode("ascii")


class RegistrationCase(SyncTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.player_id, self.player_name, _ = await self.make_user("joana")
        self.player = await self.auth("joana")
        await self.fetch("UPDATE fields SET public_page = true")  # the app's lookup by slug needs it (SRV-6)

    async def game(self, field_id: Optional[uuid.UUID] = None, status: str = "published", starts: float = 48,
                   window: bool = True, **values: Any) -> ScheduledGame:
        values.setdefault("teams", ["red", "blue"])
        if window:
            values.setdefault("registration_opens_at", hour(-24))
            values.setdefault("registration_closes_at", hour(starts - 2))
        async with self.app.state.sessionmaker() as db:
            game = ScheduledGame(field_id=field_id or self.field_id, title="Domingo no bosque", starts_at=hour(starts),
                                 ends_at=hour(starts + 4), status=status, **values)
            db.add(game)
            await db.commit()
            await db.refresh(game)
            return game

    def path(self, game: ScheduledGame) -> str:
        return f"/api/v1/fields/{game.field_id}/scheduled-games/{game.id}/registrations"

    async def register(self, game: ScheduledGame, headers: Optional[dict[str, str]] = None, expect: int = 201,
                       **body: Any) -> dict[str, Any]:
        r = await self.client.post(self.path(game), json=body, headers=headers or self.player)
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    async def staff(self, role: str = "admin") -> dict[str, str]:
        role_id = {"gm": 5, "admin": 7, "marshal": 4}[role]
        user_id, name, totp_secret = await self.make_user(with_totp=True)
        await self.fetch("INSERT INTO user_field_roles (user_id, field_id, role_id) VALUES ($1, $2, $3)",
                         user_id, self.field_id, role_id)
        return await self.auth(name, secret=totp_secret)

    async def pull(self, path: str, key: Optional[str] = None, expect: int = 200) -> dict[str, Any]:
        r = await self.client.get(path, headers=self.headers(key))
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()


class RegisterTests(RegistrationCase):
    async def test_register_with_replicas_and_a_ticket(self) -> None:
        game = await self.game(federation="required")
        r = await self.client.post(self.path(game), json={"replicas": [{"type": "aeg", "class": "rifle"}]},
                                   headers=self.player)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "federation_number_required"))
        out = await self.register(game, display_name=" Falcão ", team_preference="red", federation_number="FPA-1",
                                  replicas=[{"type": "aeg", "class": "rifle", "make_model": "Tokyo Marui M4"},
                                            {"type": "sniper", "class": "sniper"}])
        self.assertEqual((out["display_name"], out["team_preference"], out["federation_number"], out["status"]),
                         ("Falcão", "red", "FPA-1", "registered"))
        self.assertRegex(out["player_id"], r"^p-[a-z2-7]{12}$")
        self.assertEqual([(d["type"], d["class"], d["state"]) for d in out["replicas"]],
                         [("aeg", "rifle", None), ("sniper", "sniper", None)])
        # The ticket: shown this once, only its SHA-256 kept, and the printable text decodes to it.
        raw = checkin_ticket.secret_from_text(out["ticket"])
        ticket = checkin_ticket.parse(out["ticket_text"])
        self.assertEqual(ticket, {"registration_id": out["id"], "player_id": out["player_id"], "secret": raw})
        row = (await self.fetch("SELECT ticket_hash, user_id FROM game_registrations"))[0]
        self.assertEqual(row["ticket_hash"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(row["user_id"], self.player_id)
        link = await self.fetch("SELECT player_id, user_id FROM field_player_ids")
        self.assertEqual([tuple(x) for x in link], [(out["player_id"], self.player_id)])
        mine = (await self.client.get("/api/v1/me/registrations", headers=self.player)).json()
        self.assertEqual(len(mine), 1)
        self.assertNotIn("ticket", mine[0])
        self.assertNotIn(row["ticket_hash"], json.dumps(mine))
        self.assertEqual((mine[0]["has_ticket"], mine[0]["game"]["title"], mine[0]["field"]["slug"]),
                         (True, "Domingo no bosque", "campo"))
        audit = await self.fetch("SELECT details FROM audit_log WHERE action = 'registration_create'")
        self.assertNotIn("Falcão", audit[0]["details"])

    async def test_one_registration_per_account_and_cancel(self) -> None:
        game = await self.game()
        first = await self.register(game)
        self.assertEqual(first["display_name"], "joana")  # the username by default
        r = await self.client.post(self.path(game), json={}, headers=self.player)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "already_registered"))
        r = await self.client.delete(f"/api/v1/me/registrations/{first['id']}", headers=self.player)
        self.assertEqual(r.status_code, 204)
        again = await self.register(game)
        self.assertEqual((again["id"], again["player_id"]), (first["id"], first["player_id"]))
        self.assertNotEqual(again["ticket"], first["ticket"])

    async def test_the_window_and_the_places(self) -> None:
        cases = {"closed": await self.game(registration_opens_at=hour(-30), registration_closes_at=hour(-1)),
                 "not_yet": await self.game(registration_opens_at=hour(2)),
                 "no_window": await self.game(window=False),
                 "cancelled": await self.game(status="cancelled")}
        for name, game in cases.items():
            with self.subTest(name):
                r = await self.client.post(self.path(game), json={}, headers=self.player)
                self.assertEqual((r.status_code, r.json()["detail"]), (409, "registration_closed"))
        draft = await self.game(status="draft")
        r = await self.client.post(self.path(draft), json={}, headers=self.player)
        self.assertEqual((r.status_code, r.json()["detail"]), (404, "scheduled_game_not_found"))
        r = await self.client.post(self.path(draft), json={})
        self.assertEqual(r.status_code, 401)
        full = await self.game(max_players=1)
        await self.register(full)
        _, _, _ = await self.make_user("rui")
        r = await self.client.post(self.path(full), json={}, headers=await self.auth("rui"))
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "game_full"))

    async def test_replica_rules(self) -> None:
        game = await self.game()
        bad = {"replica_class_invalid": [{"type": "aeg", "class": "laser"}],
               "replica_type_invalid": [{"type": "railgun", "class": "rifle"}],
               "replica_unknown": [{"replica_id": REPLICA}],
               "replicas_invalid": [{"type": "aeg", "class": "rifle", "state": "passed"}]}
        for code, replicas in bad.items():
            with self.subTest(code):
                r = await self.client.post(self.path(game), json={"replicas": replicas}, headers=self.player)
                self.assertEqual(r.status_code, 422 if code == "replicas_invalid" else 400, r.text)
                if code != "replicas_invalid":
                    self.assertEqual(r.json()["detail"], code)
        await self.fetch("UPDATE fields SET max_replicas = 2")
        r = await self.client.post(self.path(game), json={"replicas": [{"type": "aeg", "class": "rifle"}] * 3},
                                   headers=self.player)
        self.assertEqual(r.json()["detail"], "too_many_replicas")
        r = await self.client.post(self.path(game), json={"team_preference": "green"}, headers=self.player)
        self.assertEqual(r.json()["detail"], "team_preference_invalid")
        no = await self.game(predeclare_replicas=False)
        r = await self.client.post(self.path(no), json={"replicas": [{"type": "aeg", "class": "rifle"}]},
                                   headers=self.player)
        self.assertEqual(r.json()["detail"], "replicas_not_asked")
        # One of the player's own replicas in the field's registry: its type and class are the registry's.
        first = await self.register(game)
        await self.fetch("INSERT INTO replicas (field_id, replica_id, owner_player_id, replica_type, replica_class, "
                         "make_model) VALUES ($1, $2, $3, 'dmr', 'dmr', 'SR-25')", self.field_id, uuid.UUID(REPLICA),
                         first["player_id"])
        r = await self.client.patch(f"/api/v1/me/registrations/{first['id']}",
                                    json={"replicas": [{"replica_id": REPLICA, "type": "aeg", "class": "rifle"}]},
                                    headers=self.player)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([(d["replica_id"], d["type"], d["class"], d["make_model"]) for d in r.json()["replicas"]],
                         [(REPLICA, "dmr", "dmr", "SR-25")])

    async def test_change_until_the_window_closes_and_a_new_ticket(self) -> None:
        game = await self.game()
        reg = await self.register(game)
        r = await self.client.patch(f"/api/v1/me/registrations/{reg['id']}",
                                    json={"display_name": "Coruja", "team_preference": "blue"}, headers=self.player)
        self.assertEqual((r.status_code, r.json()["display_name"], r.json()["team_preference"]),
                         (200, "Coruja", "blue"))
        r = await self.client.post(f"/api/v1/me/registrations/{reg['id']}/ticket", headers=self.player)
        self.assertEqual(r.status_code, 200)
        new = checkin_ticket.secret_from_text(r.json()["ticket"])
        row = (await self.fetch("SELECT ticket_hash FROM game_registrations"))[0]
        self.assertEqual(row[0], hashlib.sha256(new).hexdigest())
        await self.fetch("UPDATE scheduled_games SET registration_closes_at = now() - interval '1 minute'")
        r = await self.client.patch(f"/api/v1/me/registrations/{reg['id']}", json={"display_name": "X"},
                                    headers=self.player)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "registration_closed"))
        r = await self.client.delete(f"/api/v1/me/registrations/{reg['id']}", headers=self.player)
        self.assertEqual(r.status_code, 409)
        # Staff still can, until the game starts.
        admin = await self.staff("admin")
        r = await self.client.patch(f"{self.path(game)}/{reg['id']}", json={"display_name": "Mocho"}, headers=admin)
        self.assertEqual((r.status_code, r.json()["display_name"]), (200, "Mocho"))
        _, _, _ = await self.make_user("other")
        r = await self.client.patch(f"/api/v1/me/registrations/{reg['id']}", json={"display_name": "Hack"},
                                    headers=await self.auth("other"))
        self.assertEqual(r.status_code, 404)

    async def test_the_staff_list(self) -> None:
        game = await self.game(max_players=10)
        await self.register(game, display_name="Falcão")
        r = await self.client.get(self.path(game), headers=self.player)
        self.assertEqual(r.status_code, 403)
        gm = await self.staff("gm")
        r = await self.client.get(self.path(game), headers=gm)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual((body["counts"], [x["display_name"] for x in body["registrations"]]),
                         ({"registered": 1}, ["Falcão"]))
        reg_id = body["registrations"][0]["id"]
        r = await self.client.delete(f"{self.path(game)}/{reg_id}", headers=gm)
        self.assertEqual(r.status_code, 204)
        listed = await self.client.get(f"/api/v1/fields/{self.field_id}/scheduled-games/{game.id}", headers=gm)
        self.assertEqual((listed.json()["registered"], listed.json()["places_left"]), (0, 10))

    async def test_the_field_rules(self) -> None:
        admin = await self.staff("admin")
        for body, code in (({"limit_template": "atlantis"}, "limit_template_invalid"),
                           ({"max_replicas": 21}, "max_replicas_invalid"), ({"max_replicas": 0}, "max_replicas_invalid")):
            r = await self.client.patch(f"/api/v1/fields/{self.field_id}", json=body, headers=admin)
            self.assertEqual((r.status_code, r.json()["detail"]), (400, code))
        r = await self.client.patch(f"/api/v1/fields/{self.field_id}",
                                    json={"limit_template": "germany", "max_replicas": 3}, headers=admin)
        self.assertEqual((r.json()["limit_template"], r.json()["max_replicas"]), ("germany", 3))
        game = await self.game()
        r = await self.client.post(self.path(game), json={"replicas": [{"type": "aeg", "class": "cqb"}]},
                                   headers=self.player)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "replica_class_invalid"))  # Portugal's, not Germany's
        await self.register(game, replicas=[{"type": "gbb", "class": "semi"}])


class ClaimTests(RegistrationCase):
    async def test_a_claim_confirmed_by_the_controller(self) -> None:
        phone_secret = secret()
        body = {"field_id": str(self.field_id), "player_id": "p-abcdefgh2345", "player_secret": phone_secret}
        r = await self.client.post("/api/v1/me/player-ids", json=body, headers=self.player)
        self.assertEqual((r.status_code, r.json()["status"]), (202, "pending"), r.text)
        claim_id = r.json()["id"]
        stored = (await self.fetch("SELECT secret_sha256 FROM player_id_claims"))[0][0]
        want = hashlib.sha256(checkin_ticket.secret_from_text(phone_secret)).hexdigest()
        self.assertEqual(stored, want)
        self.assertNotIn(phone_secret, json.dumps([dict(x) for x in await self.fetch("SELECT * FROM player_id_claims")],
                                                  default=str))
        pulled = await self.pull("/api/v1/sync/claims")
        sync_format.check_claims_list(pulled)
        self.assertEqual(pulled["claims"], [{"claim_id": claim_id, "player_id": "p-abcdefgh2345",
                                             "secret_sha256": want}])
        answer = await self.post("claims", {"sync_version": 1, "controller": envelope()["controller"],
                                            "results": [{"claim_id": claim_id, "result": "unknown"}]})
        self.assertEqual(answer, {"confirmed": 0, "refused": 0, "pending": 1})
        answer = await self.post("claims", {"sync_version": 1, "controller": envelope()["controller"],
                                            "results": [{"claim_id": claim_id, "result": "confirmed"}]})
        self.assertEqual(answer["confirmed"], 1)
        mine = (await self.client.get("/api/v1/me/player-ids", headers=self.player)).json()
        self.assertEqual([p["player_id"] for p in mine["player_ids"]], ["p-abcdefgh2345"])
        self.assertEqual(mine["claims"][0]["status"], "confirmed")
        self.assertEqual((await self.pull("/api/v1/sync/claims"))["claims"], [])
        # The account now registers with the adopted id.
        game = await self.game()
        self.assertEqual((await self.register(game))["player_id"], "p-abcdefgh2345")
        # Nobody else can claim it, and the account cannot claim a second one here.
        _, _, _ = await self.make_user("rui")
        r = await self.client.post("/api/v1/me/player-ids", json=body, headers=await self.auth("rui"))
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "player_id_taken"))
        r = await self.client.post("/api/v1/me/player-ids", json={**body, "player_id": "p-zzzzzzzzzzzz"},
                                   headers=self.player)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "player_id_exists"))

    async def test_refused_and_bad_claims(self) -> None:
        body = {"field_id": str(self.field_id), "player_id": "p-abcdefgh2345", "player_secret": secret()}
        for over, code in (({"player_id": "p-17"}, "player_id_invalid"),
                           ({"player_secret": "A" * 43 + "="}, "player_secret_invalid")):
            r = await self.client.post("/api/v1/me/player-ids", json={**body, **over}, headers=self.player)
            self.assertEqual((r.status_code, r.json()["detail"]), (400, code))
        claim_id = (await self.client.post("/api/v1/me/player-ids", json=body, headers=self.player)).json()["id"]
        other_field, other_key = await self.make_field("arena")
        self.assertEqual((await self.pull("/api/v1/sync/claims", other_key))["claims"], [])
        answer = await self.post("claims", {"sync_version": 1, "controller": envelope()["controller"],
                                            "results": [{"claim_id": claim_id, "result": "confirmed"}]}, other_key)
        self.assertEqual(answer, {"confirmed": 0, "refused": 0, "pending": 0})  # another field's claim: ignored
        answer = await self.post("claims", {"sync_version": 1, "controller": envelope()["controller"],
                                            "results": [{"claim_id": claim_id, "result": "refused"}]})
        self.assertEqual(answer["refused"], 1)
        self.assertEqual(await self.count("field_player_ids"), 0)


class GameDaySyncTests(RegistrationCase):
    async def test_the_schedule(self) -> None:
        soon = await self.game(max_players=60, mode_id="org.atalaia.domination", location_text="Pinhal")
        await self.register(soon)
        await self.game(status="draft")
        await self.game(status="cancelled")
        await self.game(starts=24 * 20)  # beyond 14 days
        await self.game(starts=-10, window=False)  # already over
        running = await self.game(status="in_progress", starts=-1, window=False)
        other, _ = await self.make_field("arena")
        await self.game(field_id=other)
        r = await self.client.get("/api/v1/sync/schedule")
        self.assertEqual(r.status_code, 401)
        answer = await self.pull("/api/v1/sync/schedule")
        sync_format.check_schedule(json.loads(json.dumps(answer)))
        self.assertEqual([g["scheduled_game_id"] for g in answer["games"]], [str(running.id), str(soon.id)])
        entry = answer["games"][1]
        self.assertEqual((entry["registered"], entry["max_players"], entry["mode_id"], entry["location"],
                          entry["starts_at"]), (1, 60, "org.atalaia.domination", "Pinhal", soon.starts_at.timestamp()))
        self.assertEqual(len((await self.pull("/api/v1/sync/schedule?days=60"))["games"]), 3)
        for bad in ("0", "61", "x"):
            await self.pull(f"/api/v1/sync/schedule?days={bad}", expect=400)

    async def test_the_roster(self) -> None:
        game = await self.game(federation="off")
        reg = await self.register(game, display_name="Falcão", team_preference="red", federation_number="12",
                                  replicas=[{"type": "aeg", "class": "rifle", "make_model": "M4"}])
        _, _, _ = await self.make_user("rui", password=PASSWORD)
        rui = await self.auth("rui")
        gone = await self.register(game, headers=rui)
        await self.client.delete(f"/api/v1/me/registrations/{gone['id']}", headers=rui)
        answer = await self.pull(f"/api/v1/sync/roster?scheduled_game_id={game.id}")
        sync_format.check_roster(json.loads(json.dumps(answer)))
        ticket = checkin_ticket.secret_from_text(reg["ticket"])
        self.assertEqual(answer["registrations"], [{
            "registration_id": reg["id"], "player_id": reg["player_id"], "display_name": "Falcão",
            "team_preference": "red", "ticket_sha256": hashlib.sha256(ticket).hexdigest(),
            "replicas": [{"declaration_id": reg["replicas"][0]["declaration_id"], "type": "aeg", "class": "rifle",
                          "make_model": "M4"}]}])  # no federation number: the game asks for none
        # The random ids and the hash can hold "rui" by chance (p-fwfrui4yfcxl did): search the rest.
        ids = ("registration_id", "player_id", "declaration_id", "ticket_sha256", "scheduled_game_id")
        text = json.dumps(answer, default=str)
        for k in ids:
            for value in re.findall(rf'"{k}": "([^"]*)"', text):
                text = text.replace(value, "")
        for private in ("joana", "rui", reg["ticket"]):
            self.assertNotIn(private, text)
        other, other_key = await self.make_field("arena")
        await self.pull(f"/api/v1/sync/roster?scheduled_game_id={game.id}", other_key, expect=404)
        await self.pull(f"/api/v1/sync/roster?scheduled_game_id={uuid.uuid4()}", expect=404)
        await self.pull("/api/v1/sync/roster?scheduled_game_id=nope", expect=400)
        asked = await self.game(federation="required")
        await self.register(asked, federation_number="FPA-9")
        answer = await self.pull(f"/api/v1/sync/roster?scheduled_game_id={asked.id}")
        self.assertEqual(answer["registrations"][0]["federation_number"], "FPA-9")

    async def test_a_game_made_from_the_schedule_and_its_outcomes(self) -> None:
        game = await self.game(starts=1, registration_closes_at=hour(0.5))
        first = await self.register(game, replicas=[{"type": "aeg", "class": "rifle"}])
        _, _, _ = await self.make_user("rui")
        second = await self.register(game, headers=await self.auth("rui"))
        _, _, _ = await self.make_user("ana")
        third = await self.register(game, headers=await self.auth("ana"))
        meta = {**META, "state": "ready", "started_at": None, "scheduled_game_id": str(game.id)}
        answer = await self.post("games", envelope(meta=meta))
        self.assertTrue(answer["scheduled"])
        row = (await self.fetch("SELECT status, controller_game FROM scheduled_games"))[0]
        self.assertEqual((row["status"], str(row["controller_game"])), ("published", answer["game"]))
        await self.post("games", envelope(meta={**meta, "state": "running", "started_at": 1792000100.0}))
        self.assertEqual((await self.fetch("SELECT status FROM scheduled_games"))[0][0], "in_progress")
        await self.post("games", envelope(meta={**meta, "state": "ended", "started_at": 1792000100.0,
                                                "ended_at": 1792003700.0}))
        self.assertEqual((await self.fetch("SELECT status FROM scheduled_games"))[0][0], "completed")
        other, other_key = await self.make_field("arena")
        answer = await self.post("games", envelope(meta=meta), other_key)
        self.assertFalse(answer["scheduled"])  # another field's scheduled game: not linked

        decl = first["replicas"][0]["declaration_id"]
        reading = str(uuid.uuid4())
        third_secret = checkin_ticket.secret_from_text(third["ticket"])
        body = envelope(scheduled_game_id=str(game.id), walkins=2, registrations=[
            {"registration_id": first["id"], "player_id": first["player_id"], "outcome": "checked_in",
             "declarations": [{"declaration_id": decl, "state": "passed", "reading_id": reading},
                              {"declaration_id": str(uuid.uuid4()), "state": "pending"}]},
            {"registration_id": second["id"], "player_id": "p-zzzzzzzzzzzz", "outcome": "checked_in",
             "declarations": []},  # not the registration's player id: ignored
            {"registration_id": third["id"], "player_id": "p-zzzzzzzzzzzz", "outcome": "checked_in",
             "ticket_sha256": hashlib.sha256(third_secret).hexdigest(), "declarations": []}])
        answer = await self.post("checkins", body)
        self.assertEqual(answer, {"linked": True, "applied": 2, "ignored": 1, "declarations": 1})
        rows = {r["id"]: r for r in await self.fetch("SELECT id, status, outcome_at FROM game_registrations")}
        self.assertEqual([rows[uuid.UUID(x["id"])]["status"] for x in (first, second, third)],
                         ["checked_in", "registered", "checked_in"])
        state = await self.fetch("SELECT state, reading_id FROM registration_replicas")
        self.assertEqual((state[0]["state"], str(state[0]["reading_id"])), ("passed", reading))
        self.assertEqual((await self.fetch("SELECT walkins FROM scheduled_games"))[0][0], 2)
        mine = (await self.client.get("/api/v1/me/registrations", headers=self.player)).json()
        self.assertEqual((mine[0]["status"], mine[0]["replicas"][0]["state"]), ("checked_in", "passed"))
        # A wrong ticket proves nothing.
        body["registrations"] = [{"registration_id": second["id"], "player_id": second["player_id"],
                                  "outcome": "no_show", "ticket_sha256": "00" * 32, "declarations": []}]
        self.assertEqual((await self.post("checkins", body))["ignored"], 1)
        body["scheduled_game_id"] = str(uuid.uuid4())
        self.assertEqual((await self.post("checkins", body))["linked"], False)
        await self.post("checkins", envelope(game={"game_id": 7, "game_seed": 7}, scheduled_game_id=str(game.id),
                                             walkins=0, registrations=[]), expect=404)

    async def test_the_number_is_erased_when_the_outcome_arrives_or_the_game_ends(self) -> None:
        """The card is compared at the field (protocol/apd.md "The card check"): the site server drops its copy of
        the number with the outcome, or at game end for those the outcome did not cover; the APD and the expiry
        stay to the 30 days."""
        game = await self.game(starts=1, registration_closes_at=hour(0.5), federation="optional")
        first = await self.register(game, federation_number="FPA-1")
        _, _, _ = await self.make_user("rui")
        second = await self.register(game, headers=await self.auth("rui"), federation_number="FPA-2")
        meta = {**META, "state": "running", "started_at": 1792000100.0, "scheduled_game_id": str(game.id)}
        await self.post("games", envelope(meta=meta))

        async def numbers():
            rows = await self.fetch("SELECT id, federation_number FROM game_registrations")
            return {str(r["id"]): r["federation_number"] for r in rows}

        self.assertEqual(sorted((await numbers()).values()), ["FPA-1", "FPA-2"])  # the roster still needs them
        body = envelope(scheduled_game_id=str(game.id), walkins=0, registrations=[
            {"registration_id": first["id"], "player_id": first["player_id"], "outcome": "checked_in",
             "declarations": []}])
        self.assertEqual((await self.post("checkins", body))["applied"], 1)
        got = await numbers()
        self.assertEqual((got[first["id"]], got[second["id"]]), (None, "FPA-2"))
        await self.post("games", envelope(meta={**meta, "state": "ended", "ended_at": 1792003700.0}))
        self.assertEqual(set((await numbers()).values()), {None})


class RegistrationPersonalDataTests(RegistrationCase):
    async def test_access_export_and_erasure(self) -> None:
        upcoming = await self.game(federation="optional")
        past = await self.game(starts=-30, window=False)
        reg = await self.register(upcoming, display_name="Falcão", federation_number="FPA-1",
                                  replicas=[{"type": "aeg", "class": "rifle", "make_model": "M4"}])
        await self.fetch("INSERT INTO game_registrations (scheduled_game, field_id, user_id, player_id, display_name, "
                         "status) VALUES ($1, $2, $3, $4, 'Falcão', 'checked_in')", past.id, self.field_id,
                         self.player_id, reg["player_id"])
        await self.client.post("/api/v1/me/player-ids", json={
            "field_id": str((await self.make_field("arena"))[0]), "player_id": "p-abcdefgh2345",
            "player_secret": secret()}, headers=self.player)
        data = (await self.client.get("/api/v1/me/data", headers=self.player)).json()
        self.assertEqual([(r["display_name"], r["status"]) for r in data["registrations"]],
                         [("Falcão", "checked_in"), ("Falcão", "registered")])
        self.assertEqual(data["registrations"][1]["replicas"][0]["make_model"], "M4")
        self.assertEqual([c["status"] for c in data["player_id_claims"]], ["pending"])
        self.assertNotIn("ticket", json.dumps(data["registrations"]))
        r = await self.client.get("/api/v1/me/export", headers=self.player)
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            self.assertEqual(json.loads(zf.read("export/registrations.json")), data["registrations"])
            self.assertEqual(json.loads(zf.read("export/player_id_claims.json")), data["player_id_claims"])
        r = await self.client.request("DELETE", "/api/v1/me", json={"password": PASSWORD}, headers=self.player)
        self.assertEqual(r.status_code, 204, r.text)
        rows = await self.fetch("SELECT scheduled_game, user_id, display_name, federation_number, ticket_hash, status "
                                "FROM game_registrations ORDER BY created_at")
        by_game = {r["scheduled_game"]: r for r in rows}
        self.assertEqual(tuple(by_game[upcoming.id])[1:], (None, None, None, None, "cancelled"))
        self.assertEqual(tuple(by_game[past.id])[1:], (None, None, None, None, "checked_in"))  # the field's history
        self.assertEqual((await self.fetch("SELECT make_model FROM registration_replicas"))[0][0], None)
        self.assertEqual(await self.count("player_id_claims"), 0)
        self.assertEqual(await self.count("field_player_ids"), 0)
        roster = await self.pull(f"/api/v1/sync/roster?scheduled_game_id={upcoming.id}")
        self.assertEqual(roster["registrations"], [])

    async def test_the_purge(self) -> None:
        old = await self.game(starts=-24 * 40, window=False, federation="optional")
        recent = await self.game(starts=-24 * 10, window=False, federation="optional")
        for game in (old, recent):
            await self.fetch("INSERT INTO game_registrations (scheduled_game, field_id, player_id, display_name, "
                             "federation_number, status) VALUES ($1, $2, $3, 'Falcão', 'FPA-1', 'checked_in')",
                             game.id, self.field_id, "p-abcdefgh2345")
        await self.fetch("INSERT INTO player_id_claims (user_id, field_id, player_id, secret_sha256, created_at) "
                         "VALUES ($1, $2, 'p-zzzzzzzzzzzz', $3, now() - interval '31 days')", self.player_id,
                         self.field_id, "00" * 32)
        async with self.app.state.sessionmaker() as db:
            counts = await personal_data.purge(db)
        self.assertEqual((counts["federation_numbers"], counts["player_id_claims"]), (1, 1))
        rows = {r[0]: r[1] for r in await self.fetch("SELECT scheduled_game, federation_number FROM game_registrations")}
        self.assertEqual((rows[old.id], rows[recent.id]), (None, "FPA-1"))
