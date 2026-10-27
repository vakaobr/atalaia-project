# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The staff pages for scheduled games, registrations and the game-day roster (Phase 4 follow-up FU6) on
PostgreSQL 16.

The pages hold no data and call the API (decisions FU2-1, FU2-2), so their role rules are the API's: these
tests state them for the calls the three pages make (who may list, create, edit, publish, cancel, delete, see
names), that no cookie authorises a state-changing call (FU2-3), and that the roster page's rows, made from
the staff list, are the ones ``GET /api/v1/sync/roster`` gives the controller. The pages in four languages,
their scripts and texts are in ``test_staff_pages.py``; in a browser, ``tests_browser/``.

    python3 tools/docker_server.py test tests.test_staff_schedule
"""

from __future__ import annotations

import re
from typing import Any

from .test_registrations import RegistrationCase, hour

PAGES = ("schedule", "schedule/{game}/registrations", "schedule/{game}/roster")


class StaffScheduleTests(RegistrationCase):
    async def role(self, name: str) -> dict[str, str]:
        """A session in the field with this role (TOTP, as the privileged roles need); a player has no TOTP."""
        if name == "player":
            return self.player
        return await self.staff(name)

    def api(self, rest: str = "") -> str:
        return f"/api/v1/fields/{self.field_id}/scheduled-games{rest}"

    def body(self, **values: Any) -> dict[str, Any]:
        return {"title": "Sábado de manhã", "starts_at": hour(72).isoformat(), "ends_at": hour(76).isoformat(),
                "teams": ["red", "blue"], "max_players": 20, "federation": "optional",
                "registration_opens_at": hour(1).isoformat(), "registration_closes_at": hour(70).isoformat(),
                **values}

    async def test_the_pages_are_there_for_anyone_and_name_nothing(self) -> None:
        game = await self.game()
        await self.register(game, display_name="Falcão")
        for rest in PAGES:
            with self.subTest(page=rest):
                r = await self.client.get(f"/staff/fields/{self.field_id}/{rest.format(game=game.id)}")
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.headers["cache-control"], "no-store")
                self.assertNotIn("Domingo no bosque", r.text)
                self.assertNotIn("Falcão", r.text)
                self.assertIn(f'href="/staff/fields/{self.field_id}/schedule"', r.text)  # the navigation
                self.assertIn('data-section="schedule"', r.text)

    async def test_the_roles_of_the_calls_the_schedule_page_makes(self) -> None:
        anonymous = await self.client.get(self.api())
        self.assertEqual(anonymous.status_code, 401)
        for name in ("player", "marshal"):
            with self.subTest(role=name):
                headers = await self.role(name)
                self.assertEqual((await self.client.get(self.api(), headers=headers)).status_code, 403)
                self.assertEqual((await self.client.post(self.api(), json=self.body(), headers=headers)).status_code, 403)
        gm = await self.role("gm")
        admin = await self.role("admin")
        created = await self.client.post(self.api(), json=self.body(), headers=gm)
        self.assertEqual(created.status_code, 201, created.text)
        game = created.json()
        self.assertEqual((game["status"], game["registered"]), ("draft", 0))
        # The GM lists and edits (a PATCH sends every member, as the page does) but does not publish or cancel.
        listed = await self.client.get(self.api(), headers=gm)
        self.assertEqual([g["id"] for g in listed.json()], [game["id"]])
        edited = await self.client.patch(self.api(f"/{game['id']}"), headers=gm,
                                         json=self.body(title="Sábado, depois", description=None, location_text=None,
                                                        mode_id=None, max_players=None))
        self.assertEqual((edited.status_code, edited.json()["title"], edited.json()["max_players"]),
                         (200, "Sábado, depois", None))
        self.assertEqual((await self.client.post(self.api(f"/{game['id']}/publish"), headers=gm)).status_code, 403)
        published = await self.client.post(self.api(f"/{game['id']}/publish"), headers=admin)
        self.assertEqual((published.status_code, published.json()["status"]), (200, "published"))
        cancel = {"reason": "Chuva forte"}
        self.assertEqual((await self.client.post(self.api(f"/{game['id']}/cancel"), json=cancel, headers=gm)).status_code, 403)
        # A published game is not deleted, and its start moves the calendars' sequence (the API's rules).
        self.assertEqual((await self.client.delete(self.api(f"/{game['id']}"), headers=gm)).status_code, 409)
        moved = await self.client.patch(self.api(f"/{game['id']}"), headers=gm, json={"starts_at": hour(73).isoformat()})
        self.assertEqual(moved.json()["ical_sequence"], 1)
        cancelled = await self.client.post(self.api(f"/{game['id']}/cancel"), json=cancel, headers=admin)
        self.assertEqual((cancelled.status_code, cancelled.json()["status"], cancelled.json()["cancelled_reason"]),
                         (200, "cancelled", "Chuva forte"))
        gone = await self.client.patch(self.api(f"/{game['id']}"), json={"title": "x"}, headers=gm)
        self.assertEqual((gone.status_code, gone.json()["detail"]), (409, "not_editable"))
        # The upcoming view asks with ?from=: a game that ended is left out, one that has not is kept.
        old = await self.game(status="published", starts=-30, window=False)
        view = await self.client.get(self.api(), params={"from": hour(0).isoformat()}, headers=gm)
        self.assertNotIn(str(old.id), [g["id"] for g in view.json()])
        self.assertIn(game["id"], [g["id"] for g in view.json()])

    async def test_a_bad_form_is_refused_with_the_apis_codes_the_page_has_words_for(self) -> None:
        from atalaia_server.web.staff_i18n import STRINGS
        gm = await self.role("gm")
        bad = {
            "title_invalid": self.body(title="  "),
            "times_invalid": self.body(ends_at=hour(71).isoformat()),
            "registration_window_invalid": self.body(registration_closes_at=hour(80).isoformat()),
            "teams_invalid": self.body(teams=["red", "red"]),
            "max_players_invalid": self.body(max_players=0),
            "mode_id_invalid": self.body(mode_id="Not A Mode"),
            "federation_invalid": self.body(federation="maybe"),
        }
        for code, body in bad.items():
            with self.subTest(code=code):
                r = await self.client.post(self.api(), json=body, headers=gm)
                self.assertEqual((r.status_code, r.json()["detail"]), (400, code))
                self.assertIn(f"e_{code}", STRINGS["en"])

    async def test_nothing_is_authorised_by_a_cookie(self) -> None:
        """The session's refresh cookie is in the client after a login; no state-changing call of these pages works
        on it (FU2-3): they need the bearer token, which another site cannot read."""
        user_id, name, secret = await self.make_user(with_totp=True)
        await self.fetch("INSERT INTO user_field_roles (user_id, field_id, role_id) VALUES ($1, $2, 7)", user_id,
                         self.field_id)
        await self.login(name, secret=secret)
        self.assertTrue(self.client.cookies)
        game = await self.game(status="draft")
        for method, rest in (("POST", ""), ("PATCH", f"/{game.id}"), ("DELETE", f"/{game.id}"),
                             ("POST", f"/{game.id}/publish"), ("POST", f"/{game.id}/cancel")):
            with self.subTest(call=f"{method} {rest}"):
                r = await self.client.request(method, self.api(rest), json={} if method != "DELETE" else None)
                self.assertEqual(r.status_code, 401)
        r = await self.client.get(self.path(game))
        self.assertEqual(r.status_code, 401)

    async def test_the_registrations_calls_and_what_staff_may_change(self) -> None:
        game = await self.game(federation="optional", max_players=10)
        mine = await self.register(game, display_name="Falcão", team_preference="red")
        for name in ("player", "marshal"):
            with self.subTest(role=name):
                headers = await self.role(name)
                self.assertEqual((await self.client.get(self.path(game), headers=headers)).status_code, 403)
                self.assertEqual((await self.client.patch(f"{self.path(game)}/{mine['id']}", json={"team_preference": "blue"},
                                                          headers=headers)).status_code, 403)
        gm = await self.role("gm")
        r = await self.client.patch(f"{self.path(game)}/{mine['id']}", headers=gm,
                                    json={"display_name": "Falcão 2", "team_preference": "blue", "federation_number": "FPA-1"})
        self.assertEqual((r.status_code, r.json()["team_preference"], r.json()["federation_number"]),
                         (200, "blue", "FPA-1"))
        r = await self.client.patch(f"{self.path(game)}/{mine['id']}", json={"team_preference": None}, headers=gm)
        self.assertEqual((r.status_code, r.json()["team_preference"]), (200, None))
        r = await self.client.patch(f"{self.path(game)}/{mine['id']}", json={"team_preference": "green"}, headers=gm)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "team_preference_invalid"))
        r = await self.client.patch(f"{self.path(game)}/{mine['id']}", json={"display_name": ""}, headers=gm)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "display_name_invalid"))
        r = await self.client.delete(f"{self.path(game)}/{mine['id']}", headers=gm)
        self.assertEqual(r.status_code, 204)
        listed = (await self.client.get(self.path(game), headers=gm)).json()
        self.assertEqual((listed["counts"], listed["registrations"][0]["status"]), ({"cancelled": 1}, "cancelled"))
        r = await self.client.delete(f"{self.path(game)}/{mine['id']}", headers=gm)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "not_registered"))
        # No staff action exists for a started game: the page hides the buttons, the API refuses.
        started = await self.game(starts=-1, window=False)
        other = await self.register_directly(started)
        r = await self.client.delete(f"{self.path(started)}/{other}", headers=gm)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "game_started"))

    async def register_directly(self, game: Any) -> str:
        """A registration made in the database (the window of a started game is closed to the public)."""
        row = await self.fetch(
            "INSERT INTO game_registrations (scheduled_game, field_id, user_id, player_id, display_name, status) "
            "VALUES ($1, $2, $3, 'p-aaaaaaaaaaaa', 'Rui', 'registered') RETURNING id", game.id, game.field_id,
            self.player_id)
        return str(row[0][0])

    async def test_the_roster_page_shows_what_the_controller_pulls(self) -> None:
        """The page builds the roster from the staff list: active registrations with a name, in the order made,
        with the team, the replicas and (when the game asks for it) the federation number, as the sync's roster."""
        game = await self.game(federation="required")
        first = await self.register(game, display_name="Falcão", team_preference="red", federation_number="FPA-9",
                                    replicas=[{"type": "aeg", "class": "rifle", "make_model": "M4"}])
        _, _, _ = await self.make_user("rui")
        rui = await self.auth("rui")
        gone = await self.register(game, headers=rui, federation_number="FPA-1")
        await self.client.delete(f"/api/v1/me/registrations/{gone['id']}", headers=rui)
        _, _, _ = await self.make_user("ana")
        await self.register(game, headers=await self.auth("ana"), display_name="Ana", federation_number="FPA-2")
        gm = await self.role("gm")
        listed = (await self.client.get(self.path(game), headers=gm)).json()
        page_rows = [r for r in listed["registrations"] if r["status"] == "registered" and r["display_name"]]
        pulled = await self.pull(f"/api/v1/sync/roster?scheduled_game_id={game.id}")

        def shape(items: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
            return [(i.get("registration_id") or i["id"], i["player_id"], i["display_name"], i.get("team_preference"),
                     i.get("federation_number"), tuple((d["type"], d["class"], d.get("make_model"))
                                                       for d in i["replicas"])) for i in items]
        self.assertEqual(shape(page_rows), shape(pulled["registrations"]))
        self.assertEqual(len(page_rows), 2)
        self.assertEqual(page_rows[0]["id"], first["id"])
        self.assertTrue(all(r["has_ticket"] for r in page_rows))
        self.assertNotIn("ticket_sha256", str(listed))  # the page never has the hash, only whether there is a ticket
        self.assertFalse(re.search(r"[0-9a-f]{64}", str(listed)))

    async def test_a_game_made_from_the_schedule_shows_its_link_and_walkins(self) -> None:
        game = await self.game()
        gm = await self.role("gm")
        shown = (await self.client.get(self.api(f"/{game.id}"), headers=gm)).json()
        self.assertEqual((shown["controller_game"], shown["walkins"]), (None, None))
        self.assertIn("walkins", (await self.client.get(self.path(game), headers=gm)).json())
