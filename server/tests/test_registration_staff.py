# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What staff do with a registration beyond changing and withdrawing it, and the roster pull's record
(Phase 4 follow-up FU7, decisions FU7-*) on PostgreSQL 16.

Marking a registration paid (a note: who and when, no payment), a no-show after the game (the controller's
outcomes are never undone here), restoring a withdrawn registration while the game has not started and a place is
left, moving a registration to another published game of the field that has not started (the person, the
replicas and the ticket stay; the target's places, federation rule and one-registration-per-person hold), the
replicas edited by staff, and when a controller last pulled a game's roster. The roles, the audit log (never a
name), the personal-data rules, and the codes the staff page has words for.

    python3 tools/docker_server.py test tests.test_registration_staff
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from atalaia_controller import checkin_ticket

from atalaia_server import personal_data

from .base import PASSWORD
from .test_registrations import RegistrationCase, hour
from .test_sync import META, envelope


class StaffRegistrationCase(RegistrationCase):
    secrets: dict[str, str]

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.secrets = {}

    async def titled(self, title: str, **values: Any) -> Any:
        """A published game with this title (``game`` names every game the same)."""
        game = await self.game(**values)
        await self.fetch("UPDATE scheduled_games SET title = $1 WHERE id = $2", title, game.id)
        return game

    async def staff_named(self, role: str = "gm") -> tuple[dict[str, str], str]:
        role_id = {"gm": 5, "admin": 7, "marshal": 4}[role]
        user_id, name, totp_secret = await self.make_user(with_totp=True)
        await self.fetch("INSERT INTO user_field_roles (user_id, field_id, role_id) VALUES ($1, $2, $3)",
                         user_id, self.field_id, role_id)
        self.secrets[name] = totp_secret
        return await self.auth(name, secret=totp_secret), name

    def reg_url(self, game: Any, reg: dict[str, Any] | str | uuid.UUID, rest: str = "") -> str:
        reg_id = reg if isinstance(reg, str) else str(reg) if isinstance(reg, uuid.UUID) else reg["id"]
        return f"{self.path(game)}/{reg_id}{rest}"

    async def listed(self, game: Any, headers: dict[str, str]) -> dict[str, Any]:
        r = await self.client.get(self.path(game), headers=headers)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    async def direct(self, game: Any, name: str = "Rui", player_id: str = "p-aaaaaaaaaaaa", status: str = "registered",
                     user_id: Any = None) -> str:
        """A registration made in the database (a started game takes no online registration)."""
        row = await self.fetch(
            "INSERT INTO game_registrations (scheduled_game, field_id, user_id, player_id, display_name, status) "
            "VALUES ($1, $2, $3, $4, $5, $6) RETURNING id", game.id, game.field_id, user_id, player_id, name, status)
        return str(row[0][0])

    async def audit(self, action: str) -> list[dict[str, Any]]:
        rows = await self.fetch("SELECT details FROM audit_log WHERE action = $1 ORDER BY id", action)
        return [json.loads(r["details"]) if isinstance(r["details"], str) else dict(r["details"]) for r in rows]


class PaymentTests(StaffRegistrationCase):
    async def test_staff_note_who_paid_and_a_player_sees_only_that_it_is_paid(self) -> None:
        game = await self.game()
        reg = await self.register(game, display_name="Falcão")
        url = self.reg_url(game, reg, "/payment")
        self.assertEqual((reg["paid"], reg["paid_at"]), (False, None))
        for role in ("player", "marshal"):
            headers = self.player if role == "player" else (await self.staff_named("marshal"))[0]
            r = await self.client.put(url, json={"paid": True}, headers=headers)
            self.assertEqual(r.status_code, 403, role)
        self.assertEqual((await self.client.put(url, json={"paid": True})).status_code, 401)
        gm, gm_name = await self.staff_named("gm")
        self.assertEqual((await self.client.put(url, json={}, headers=gm)).status_code, 422)
        self.assertEqual((await self.client.put(url, json={"paid": True, "x": 1}, headers=gm)).status_code, 422)
        r = await self.client.put(url, json={"paid": True}, headers=gm)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual((body["paid"], body["paid_by"]), (True, gm_name))
        self.assertIsNotNone(body["paid_at"])
        listed = (await self.listed(game, gm))["registrations"][0]
        self.assertEqual((listed["paid"], listed["paid_by"], listed["paid_at"]), (True, gm_name, body["paid_at"]))
        # The player sees that it is paid and when, not which member of staff marked it.
        mine = (await self.client.get("/api/v1/me/registrations", headers=self.player)).json()[0]
        self.assertEqual((mine["paid"], mine["paid_at"]), (True, body["paid_at"]))
        self.assertNotIn("paid_by", mine)
        self.assertNotIn(gm_name, json.dumps(mine))
        # Again: nothing changes, and nothing more is logged.
        again = await self.client.put(url, json={"paid": True}, headers=gm)
        self.assertEqual(again.json()["paid_at"], body["paid_at"])
        self.assertEqual(await self.audit("registration_paid"), [{"field_id": str(self.field_id), "paid": True}])
        r = await self.client.put(url, json={"paid": False}, headers=gm)
        self.assertEqual((r.json()["paid"], r.json()["paid_by"], r.json()["paid_at"]), (False, None, None))
        self.assertEqual(len(await self.audit("registration_paid")), 2)
        self.assertNotIn("Falcão", json.dumps(await self.audit("registration_paid")))

    async def test_a_withdrawn_registration_or_a_cancelled_game_is_not_marked_paid(self) -> None:
        game = await self.game()
        reg = await self.register(game)
        gm, _ = await self.staff_named("gm")
        url = self.reg_url(game, reg, "/payment")
        self.assertEqual((await self.client.put(url, json={"paid": True}, headers=gm)).status_code, 200)
        self.assertEqual((await self.client.delete(self.reg_url(game, reg), headers=gm)).status_code, 204)
        # The note can still be cleared on a withdrawn registration, not made.
        self.assertEqual((await self.client.put(url, json={"paid": False}, headers=gm)).json()["paid"], False)
        r = await self.client.put(url, json={"paid": True}, headers=gm)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "registration_withdrawn"))
        other = await self.game()
        second = await self.register(other)
        admin, _ = await self.staff_named("admin")
        cancel = await self.client.post(f"/api/v1/fields/{self.field_id}/scheduled-games/{other.id}/cancel",
                                        json={"reason": "Chuva"}, headers=admin)
        self.assertEqual(cancel.status_code, 200, cancel.text)
        r = await self.client.put(self.reg_url(other, second, "/payment"), json={"paid": True}, headers=gm)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "game_cancelled"))

    async def test_a_paid_mark_outlives_the_staff_account_without_its_name_and_is_in_the_players_data(self) -> None:
        game = await self.game()
        reg = await self.register(game)
        gm, gm_name = await self.staff_named("gm")
        paid = await self.client.put(self.reg_url(game, reg, "/payment"), json={"paid": True}, headers=gm)
        data = (await self.client.get("/api/v1/me/data", headers=self.player)).json()
        self.assertEqual(data["registrations"][0]["paid_at"], paid.json()["paid_at"])
        self.assertNotIn(gm_name, json.dumps(data["registrations"]))
        row = (await self.fetch("SELECT paid_by FROM game_registrations"))[0]
        self.assertIsNotNone(row["paid_by"])
        r = await self.client.request("DELETE", "/api/v1/me", headers=gm,
                                      json={"password": PASSWORD, "code": self.code(self.secrets[gm_name])})
        self.assertEqual(r.status_code, 204, r.text)
        row = (await self.fetch("SELECT paid_by, paid_at FROM game_registrations"))[0]
        self.assertEqual((row["paid_by"], row["paid_at"] is not None), (None, True))  # the note stays, unlinked


class NoShowTests(StaffRegistrationCase):
    async def test_after_the_game_for_a_registered_player_only(self) -> None:
        gm, gm_name = await self.staff_named("gm")
        upcoming = await self.game()
        reg = await self.register(upcoming)
        url = self.reg_url(upcoming, reg, "/no-show")
        r = await self.client.put(url, json={"no_show": True}, headers=gm)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "game_not_over"))
        for headers in (self.player, (await self.staff_named("marshal"))[0]):
            self.assertEqual((await self.client.put(url, json={"no_show": True}, headers=headers)).status_code, 403)
        past = await self.game(starts=-6, window=False)  # ended two hours ago
        mine = await self.direct(past)
        url = self.reg_url(past, mine, "/no-show")
        r = await self.client.put(url, json={"no_show": True}, headers=gm)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["status"], r.json()["no_show_by_staff"]), ("no_show", True))
        self.assertIsNotNone(r.json()["outcome_at"])
        self.assertEqual((await self.listed(past, gm))["counts"], {"no_show": 1})
        self.assertEqual(await self.audit("registration_no_show"), [{"field_id": str(self.field_id), "no_show": True}])
        # Again: nothing changes. Taking the mark back is the staff's own mark only.
        r = await self.client.put(url, json={"no_show": True}, headers=gm)
        self.assertEqual(r.json()["status"], "no_show")
        self.assertEqual(len(await self.audit("registration_no_show")), 1)
        r = await self.client.put(url, json={"no_show": False}, headers=gm)
        self.assertEqual((r.json()["status"], r.json()["outcome_at"], r.json()["no_show_by_staff"]),
                         ("registered", None, False))
        # What the controller reported is not the staff's to undo, and a player it checked in is not marked.
        await self.fetch("UPDATE game_registrations SET status = 'no_show', outcome_at = now() WHERE id = $1",
                         uuid.UUID(mine))
        r = await self.client.put(url, json={"no_show": False}, headers=gm)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "outcome_from_controller"))
        await self.fetch("UPDATE game_registrations SET status = 'checked_in' WHERE id = $1", uuid.UUID(mine))
        r = await self.client.put(url, json={"no_show": True}, headers=gm)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "not_registered"))
        withdrawn = await self.direct(past, name="Ana", player_id="p-bbbbbbbbbbbb", status="cancelled")
        r = await self.client.put(self.reg_url(past, withdrawn, "/no-show"), json={"no_show": True}, headers=gm)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "not_registered"))
        self.assertNotIn(gm_name, json.dumps(await self.audit("registration_no_show")))

    async def test_the_controllers_outcome_replaces_the_mark(self) -> None:
        """Check-in stays the controller's: its push after the game wins over what staff marked."""
        gm, _ = await self.staff_named("gm")
        game = await self.game(starts=-6, window=False)
        reg = await self.direct(game)
        meta = {**META, "state": "ended", "started_at": 1792000100.0, "ended_at": 1792003700.0,
                "scheduled_game_id": str(game.id)}
        await self.post("games", envelope(meta=meta))
        r = await self.client.put(self.reg_url(game, reg, "/no-show"), json={"no_show": True}, headers=gm)
        self.assertEqual(r.json()["status"], "no_show")
        pushed = await self.post("checkins", envelope(scheduled_game_id=str(game.id), walkins=0, registrations=[
            {"registration_id": reg, "player_id": "p-aaaaaaaaaaaa", "outcome": "checked_in", "declarations": []}]))
        self.assertEqual(pushed["applied"], 1)
        row = (await self.fetch("SELECT status, outcome_by FROM game_registrations"))[0]
        self.assertEqual((row["status"], row["outcome_by"]), ("checked_in", None))
        self.assertEqual((await self.client.put(self.reg_url(game, reg, "/no-show"), json={"no_show": True},
                                                headers=gm)).json()["detail"], "not_registered")


class RestoreTests(StaffRegistrationCase):
    async def test_a_withdrawn_registration_comes_back_without_a_ticket(self) -> None:
        game = await self.game(max_players=2, teams=["red", "blue"])
        reg = await self.register(game, display_name="Falcão", team_preference="red")
        gm, _ = await self.staff_named("gm")
        url = self.reg_url(game, reg, "/restore")
        r = await self.client.post(url, headers=gm)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "not_withdrawn"))
        self.assertEqual((await self.client.delete(self.reg_url(game, reg), headers=gm)).status_code, 204)
        for headers in (self.player, (await self.staff_named("marshal"))[0]):
            self.assertEqual((await self.client.post(url, headers=headers)).status_code, 403)
        self.assertEqual((await self.client.post(url)).status_code, 401)
        r = await self.client.post(url, headers=gm)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual((body["status"], body["has_ticket"], body["cancelled_at"], body["changed"],
                          body["display_name"], body["team_preference"]), ("registered", False, None, [], "Falcão", "red"))
        self.assertEqual(await self.audit("registration_restore"), [{"field_id": str(self.field_id), "changed": []}])
        # It is in the roster (without a ticket) and counts toward the places; the player asks for a new ticket.
        roster = await self.pull(f"/api/v1/sync/roster?scheduled_game_id={game.id}")
        self.assertEqual([("display_name" in e, "ticket_sha256" in e) for e in roster["registrations"]], [(True, False)])
        r = await self.client.post(f"/api/v1/me/registrations/{reg['id']}/ticket", headers=self.player)
        self.assertEqual((r.status_code, r.json()["has_ticket"]), (200, True))
        self.assertEqual((await self.client.get(f"/api/v1/fields/{self.field_id}/scheduled-games/{game.id}",
                                                headers=gm)).json()["registered"], 1)

    async def test_the_places_the_start_and_an_erased_registration(self) -> None:
        gm, _ = await self.staff_named("gm")
        game = await self.game(max_players=1)
        reg = await self.register(game)
        await self.client.delete(self.reg_url(game, reg), headers=gm)
        _, _, _ = await self.make_user("rui")
        await self.register(game, headers=await self.auth("rui"))
        r = await self.client.post(self.reg_url(game, reg, "/restore"), headers=gm)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "game_full"))
        started = await self.game(starts=-1, window=False)
        old = await self.direct(started, status="cancelled")
        r = await self.client.post(self.reg_url(started, old, "/restore"), headers=gm)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "game_started"))
        open_game = await self.game()
        erased = await self.direct(open_game, name="Ana", player_id="p-cccccccccccc", status="cancelled")
        await self.fetch("UPDATE game_registrations SET display_name = NULL WHERE id = $1", uuid.UUID(erased))
        r = await self.client.post(self.reg_url(open_game, erased, "/restore"), headers=gm)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "registration_erased"))
        r = await self.client.post(self.reg_url(open_game, uuid.uuid4(), "/restore"), headers=gm)
        self.assertEqual((r.status_code, r.json()["detail"]), (404, "registration_not_found"))

    async def test_the_games_rules_apply_again(self) -> None:
        """The federation number is needed when the game now requires it, dropped when it no longer asks, and a
        team the game no longer has is cleared."""
        gm, _ = await self.staff_named("gm")
        game = await self.game(federation="optional", teams=["red", "blue"])
        reg = await self.register(game, team_preference="red", federation_number="FPA-1")
        await self.client.delete(self.reg_url(game, reg), headers=gm)
        await self.fetch("UPDATE scheduled_games SET federation = 'off', teams = '[\"blue\"]'")
        r = await self.client.post(self.reg_url(game, reg, "/restore"), headers=gm)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["federation_number"], r.json()["team_preference"], sorted(r.json()["changed"])),
                         (None, None, ["federation_number", "team_preference"]))
        await self.client.delete(self.reg_url(game, reg), headers=gm)
        await self.fetch("UPDATE scheduled_games SET federation = 'required'")
        r = await self.client.post(self.reg_url(game, reg, "/restore"), headers=gm)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "federation_number_required"))
        self.assertEqual((await self.fetch("SELECT status FROM game_registrations"))[0][0], "cancelled")


class MoveTests(StaffRegistrationCase):
    async def test_the_person_the_replicas_and_the_ticket_go_with_it(self) -> None:
        source = await self.titled("Sábado", teams=["red", "blue"], federation="optional")
        target = await self.titled("Domingo", starts=72, teams=["red"], federation="optional")
        reg = await self.register(source, display_name="Falcão", team_preference="red", federation_number="FPA-1",
                                  replicas=[{"type": "aeg", "class": "rifle", "make_model": "M4"}])
        gm, _ = await self.staff_named("gm")
        before = await self.fetch("SELECT ticket_hash, player_id, user_id, id FROM game_registrations")
        r = await self.client.post(self.reg_url(source, reg, "/move"), json={"scheduled_game_id": str(target.id)},
                                   headers=gm)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual((body["id"], body["scheduled_game_id"], body["game"]["title"], body["moved_from"],
                          body["changed"], body["has_ticket"]),
                         (reg["id"], str(target.id), "Domingo", str(source.id), [], True))
        self.assertEqual(body["replicas"][0]["declaration_id"], reg["replicas"][0]["declaration_id"])
        after = await self.fetch("SELECT ticket_hash, player_id, user_id, id FROM game_registrations")
        self.assertEqual([tuple(x) for x in before], [tuple(x) for x in after])  # the same person, id and ticket
        # The controller of the target game gets it with the ticket's hash the player already holds.
        secret = checkin_ticket.secret_from_text(reg["ticket"])
        roster = await self.pull(f"/api/v1/sync/roster?scheduled_game_id={target.id}")
        self.assertEqual([(e["registration_id"], e["ticket_sha256"]) for e in roster["registrations"]],
                         [(reg["id"], hashlib.sha256(secret).hexdigest())])
        self.assertEqual((await self.pull(f"/api/v1/sync/roster?scheduled_game_id={source.id}"))["registrations"], [])
        mine = (await self.client.get("/api/v1/me/registrations", headers=self.player)).json()
        self.assertEqual([m["game"]["title"] for m in mine], ["Domingo"])
        counts = await self.client.get(f"/api/v1/fields/{self.field_id}/scheduled-games/{source.id}", headers=gm)
        self.assertEqual(counts.json()["registered"], 0)
        self.assertEqual(await self.audit("registration_move"), [{
            "field_id": str(self.field_id), "from": str(source.id), "to": str(target.id), "changed": []}])

    async def test_the_new_games_rules_fit_the_registration(self) -> None:
        source = await self.game(teams=["red", "blue"], federation="optional")
        target = await self.game(starts=72, teams=["green"], federation="off", predeclare_replicas=False)
        reg = await self.register(source, team_preference="red", federation_number="FPA-1",
                                  replicas=[{"type": "aeg", "class": "rifle"}])
        gm, _ = await self.staff_named("gm")
        r = await self.client.post(self.reg_url(source, reg, "/move"), json={"scheduled_game_id": str(target.id)},
                                   headers=gm)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(sorted(r.json()["changed"]), ["federation_number", "replicas", "team_preference"])
        self.assertEqual((r.json()["team_preference"], r.json()["federation_number"], r.json()["replicas"]),
                         (None, None, []))
        # A target that requires a number refuses a registration without one (the number is added first).
        asking = await self.game(starts=96, federation="required")
        other = await self.game(starts=100, federation="optional")
        second = await self.register(other, headers=self.player)
        r = await self.client.post(self.reg_url(other, second, "/move"), json={"scheduled_game_id": str(asking.id)},
                                   headers=gm)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "federation_number_required"))
        self.assertEqual((await self.client.patch(self.reg_url(other, second), json={"federation_number": "FPA-2"},
                                                  headers=gm)).status_code, 200)
        r = await self.client.post(self.reg_url(other, second, "/move"), json={"scheduled_game_id": str(asking.id)},
                                   headers=gm)
        self.assertEqual((r.status_code, r.json()["federation_number"]), (200, "FPA-2"))

    async def test_where_it_may_go_and_who_may_move_it(self) -> None:
        source = await self.game()
        reg = await self.register(source)
        gm, _ = await self.staff_named("gm")
        url = self.reg_url(source, reg, "/move")

        async def move(target: Any, expect: int, code: str | None = None, headers: Any = None) -> Any:
            r = await self.client.post(url, json={"scheduled_game_id": str(target)}, headers=headers or gm)
            self.assertEqual(r.status_code, expect, r.text)
            if code is not None:
                self.assertEqual(r.json()["detail"], code)
            return r

        for headers in (self.player, (await self.staff_named("marshal"))[0]):
            await move(uuid.uuid4(), 403, headers=headers)
        self.assertEqual((await self.client.post(url, json={"scheduled_game_id": str(uuid.uuid4())})).status_code, 401)
        self.assertEqual((await self.client.post(url, json={}, headers=gm)).status_code, 422)
        await move(source.id, 400, "same_game")
        await move(uuid.uuid4(), 404, "scheduled_game_not_found")
        await move(( await self.game(status="draft", starts=72)).id, 404, "scheduled_game_not_found")
        other_field, _ = await self.make_field("arena")
        elsewhere = await self.game(field_id=other_field, starts=72)
        await move(elsewhere.id, 404, "scheduled_game_not_found")  # another field's game is not found here
        await move((await self.game(starts=-1, window=False)).id, 409, "target_started")
        await move((await self.game(status="in_progress", starts=72, window=False)).id, 409, "target_started")
        await move((await self.game(status="cancelled", starts=72, window=False)).id, 409, "game_cancelled")
        full = await self.game(starts=72, max_players=1)
        _, _, _ = await self.make_user("rui")
        await self.register(full, headers=await self.auth("rui"))
        await move(full.id, 409, "game_full")
        # The same person (their account) already has a registration there, live or withdrawn.
        there = await self.game(starts=80)
        mine = await self.register(there)
        await move(there.id, 409, "already_registered_there")
        await self.client.delete(self.reg_url(there, mine), headers=gm)
        await move(there.id, 409, "already_registered_there")
        self.assertEqual((await self.fetch("SELECT scheduled_game FROM game_registrations WHERE id = $1",
                                           uuid.UUID(reg["id"])))[0][0], source.id)
        # A started source, a withdrawn registration: nothing to move.
        await self.client.delete(url.rsplit("/move", 1)[0], headers=gm)
        await move((await self.game(starts=90)).id, 409, "not_registered")
        started = await self.game(starts=-1, window=False)
        old = await self.direct(started)
        r = await self.client.post(self.reg_url(started, old, "/move"),
                                   json={"scheduled_game_id": str((await self.game(starts=90)).id)}, headers=gm)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "game_started"))

    async def test_an_imported_registration_moves_unless_its_reference_is_there(self) -> None:
        source = await self.game()
        there = await self.game(starts=72)
        free = await self.game(starts=80)
        gm, _ = await self.staff_named("gm")
        csv = "display_name,external_ref\r\nAna,ref-1\r\n"
        for game in (source, there):
            r = await self.client.post(f"{self.path(game)}/import", params={"source": "club", "basis_confirmed": "true"},
                                       content=csv, headers={**gm, "Content-Type": "text/csv"})
            self.assertEqual(r.status_code, 200, r.text)
        ids = [str(r["id"]) for r in await self.fetch("SELECT id FROM game_registrations WHERE scheduled_game = $1",
                                                      source.id)]
        r = await self.client.post(self.reg_url(source, ids[0], "/move"), json={"scheduled_game_id": str(there.id)},
                                   headers=gm)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "already_registered_there"))
        r = await self.client.post(self.reg_url(source, ids[0], "/move"), json={"scheduled_game_id": str(free.id)},
                                   headers=gm)
        self.assertEqual((r.status_code, r.json()["source"], r.json()["external_ref"]), (200, "club", "ref-1"))

    async def test_two_moves_at_once_in_opposite_directions_both_finish(self) -> None:
        import asyncio
        a = await self.titled("A", max_players=2)
        b = await self.titled("B", starts=72, max_players=2)
        first = await self.register(a)
        _, _, _ = await self.make_user("rui")
        second = await self.register(b, headers=await self.auth("rui"))
        gm, _ = await self.staff_named("gm")
        done = await asyncio.gather(
            self.client.post(self.reg_url(a, first, "/move"), json={"scheduled_game_id": str(b.id)}, headers=gm),
            self.client.post(self.reg_url(b, second, "/move"), json={"scheduled_game_id": str(a.id)}, headers=gm))
        self.assertEqual([r.status_code for r in done], [200, 200], [r.text for r in done])


class ReplicaEditTests(StaffRegistrationCase):
    async def test_staff_edit_the_replicas_and_the_unchanged_keep_their_ids(self) -> None:
        game = await self.game()
        reg = await self.register(game, replicas=[{"type": "aeg", "class": "rifle", "make_model": "M4"}])
        gm, _ = await self.staff_named("gm")
        url = self.reg_url(game, reg)
        keep = {"type": "aeg", "class": "rifle", "make_model": "M4"}
        r = await self.client.patch(url, json={"replicas": [keep]}, headers=gm)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["replicas"][0]["declaration_id"], reg["replicas"][0]["declaration_id"])
        self.assertEqual(await self.audit("registration_update"), [])  # nothing changed: nothing logged
        r = await self.client.patch(url, json={"replicas": [keep, {"type": "dmr", "class": "dmr", "make_model": None}]},
                                    headers=gm)
        self.assertEqual(r.status_code, 200, r.text)
        ids = [d["declaration_id"] for d in r.json()["replicas"]]
        self.assertEqual((len(ids), ids[0]), (2, reg["replicas"][0]["declaration_id"]))  # the first kept its id
        self.assertEqual((await self.audit("registration_update"))[0]["changed"], ["replicas"])
        pulled = await self.pull(f"/api/v1/sync/roster?scheduled_game_id={game.id}")
        self.assertEqual([d["declaration_id"] for d in pulled["registrations"][0]["replicas"]], ids)
        r = await self.client.patch(url, json={"replicas": []}, headers=gm)
        self.assertEqual(r.json()["replicas"], [])
        for body, code in (({"replicas": [{"type": "aeg", "class": "nope"}]}, "replica_class_invalid"),
                           ({"replicas": [{"type": "laser", "class": "rifle"}]}, "replica_type_invalid"),
                           ({"replicas": [{"replica_id": str(uuid.uuid4())}]}, "replica_unknown"),
                           ({"replicas": [{"type": "aeg", "class": "rifle"}] * 6}, "too_many_replicas")):
            r = await self.client.patch(url, json=body, headers=gm)
            self.assertEqual((r.status_code, r.json()["detail"]), (400, code), body)
        asks_none = await self.game(starts=72, predeclare_replicas=False)
        other = await self.register(asks_none, headers=self.player)
        r = await self.client.patch(self.reg_url(asks_none, other),
                                    json={"replicas": [{"type": "aeg", "class": "rifle"}]}, headers=gm)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "replicas_not_asked"))


class RosterPullTests(StaffRegistrationCase):
    async def test_the_last_pull_is_kept_with_its_key_and_program(self) -> None:
        game = await self.game()
        gm, _ = await self.staff_named("gm")
        url = f"/api/v1/fields/{self.field_id}/scheduled-games/{game.id}"
        shown = (await self.client.get(url, headers=gm)).json()
        self.assertIsNone(shown["roster_pull"])
        await self.fetch("UPDATE field_api_keys SET label = 'Pi do campo'")
        before = (await self.fetch("SELECT updated_at FROM scheduled_games"))[0][0]
        r = await self.client.get(f"/api/v1/sync/roster?scheduled_game_id={game.id}",
                                  headers={**self.headers(), "User-Agent": "atalaia-controller/1.2.3"})
        self.assertEqual(r.status_code, 200)
        shown = (await self.client.get(url, headers=gm)).json()
        fingerprint = hashlib.sha256(self.key.encode()).hexdigest()[:8]
        self.assertEqual({k: v for k, v in shown["roster_pull"].items() if k != "at"},
                         {"key_label": "Pi do campo", "key_fingerprint": fingerprint,
                          "agent": "atalaia-controller/1.2.3"})
        first = shown["roster_pull"]["at"]
        self.assertIsNotNone(first)
        # The pages and feeds' Last-Modified follows what the game shows, not a pull.
        self.assertEqual((await self.fetch("SELECT updated_at FROM scheduled_games"))[0][0], before)
        # A newer pull replaces it (here by a client with another User-Agent).
        await self.client.get(f"/api/v1/sync/roster?scheduled_game_id={game.id}",
                              headers={**self.headers(), "User-Agent": "atalaia-controller/9.9.9"})
        shown = (await self.client.get(url, headers=gm)).json()
        self.assertEqual(shown["roster_pull"]["agent"], "atalaia-controller/9.9.9")
        self.assertGreaterEqual(shown["roster_pull"]["at"], first)
        listed = (await self.client.get(f"/api/v1/fields/{self.field_id}/scheduled-games", headers=gm)).json()
        self.assertEqual(listed[0]["roster_pull"]["key_label"], "Pi do campo")
        # A player never sees it (the game's staff view is the staff's), and a draft has no roster to pull.
        self.assertEqual((await self.client.get(url, headers=self.player)).status_code, 403)
        draft = await self.game(status="draft")
        r = await self.client.get(f"/api/v1/sync/roster?scheduled_game_id={draft.id}", headers=self.headers())
        self.assertEqual(r.status_code, 404)
        self.assertIsNone((await self.client.get(
            f"/api/v1/fields/{self.field_id}/scheduled-games/{draft.id}", headers=gm)).json()["roster_pull"])

    async def test_another_fields_key_records_nothing(self) -> None:
        game = await self.game()
        _, other_key = await self.make_field("arena")
        r = await self.client.get(f"/api/v1/sync/roster?scheduled_game_id={game.id}", headers=self.headers(other_key))
        self.assertEqual(r.status_code, 404)
        self.assertIsNone((await self.fetch("SELECT roster_pulled_at FROM scheduled_games"))[0][0])


class StaffPageCodesTests(StaffRegistrationCase):
    async def test_every_code_these_calls_answer_has_words_in_every_language(self) -> None:
        from atalaia_server.web.staff_i18n import STRINGS
        codes = ["registration_withdrawn", "game_cancelled", "game_not_over", "outcome_from_controller",
                 "not_withdrawn", "registration_erased", "same_game", "target_started", "already_registered_there",
                 "game_full", "not_registered", "game_started", "federation_number_required", "replicas_invalid",
                 "replicas_not_asked", "too_many_replicas", "replica_unknown", "replica_twice", "replica_type_invalid",
                 "replica_class_invalid", "make_model_invalid", "scheduled_game_not_found", "registration_not_found",
                 # the import's: the whole file, a row, and the request
                 "source_invalid", "too_large", "encoding_invalid", "column_twice", "display_name_column_missing",
                 "empty", "too_many_rows", "csv_invalid", "json_invalid", "format_invalid", "basis_not_confirmed",
                 "unsupported_media_type", "charset_not_utf8", "content_length_invalid", "display_name_invalid",
                 "external_ref_invalid", "external_ref_twice", "team_preference_invalid", "federation_number_invalid",
                 "row_length", "row_not_object", "cancelled"]
        for lang, strings in STRINGS.items():
            for code in codes:
                self.assertIn(f"e_{code}", strings, (lang, code))
        for warning in ("same_name", "no_external_ref", "federation_number_dropped"):
            self.assertIn(f"io_warn_{warning}", STRINGS["en"])
        for result in ("created", "updated", "unchanged", "skipped", "refused"):
            self.assertIn(f"io_res_{result}", STRINGS["en"])

    async def test_the_codes_the_services_raise_are_the_ones_listed(self) -> None:
        """A new code in the service without words on the page would show 'The server refused the request (code)'."""
        import re
        from pathlib import Path
        from atalaia_server.web.staff_i18n import STRINGS
        source = Path(personal_data.__file__).resolve().parent / "services" / "registration.py"
        raised = set(re.findall(r'RegistrationError\("([a-z_]+)"', source.read_text(encoding="utf-8")))
        raised -= {"player_id_unavailable", "player_secret_invalid", "player_id_invalid", "player_id_exists",
                   "player_id_taken", "registration_closed", "already_registered", "display_name_invalid",
                   "team_preference_invalid", "federation_number_invalid", "make_model_invalid"}
        for code in sorted(raised):
            self.assertIn(f"e_{code}", STRINGS["en"], code)
