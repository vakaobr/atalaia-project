# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""APD membership at registration (protocol/apd.md, decisions APD-*): the project's list, the field's rule, a
player declaring an APD, a number and an expiry, the staff's verdict, the roster and the field answer the controller
pulls, and the personal data rules for the new fields (retention, export, erasure)."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from atalaia_controller import apd as apd_core, sync_format

from atalaia_server import personal_data

from .base import PASSWORD
from .test_registrations import RegistrationCase, hour

ROOT = Path(__file__).resolve().parents[2]
OWN = {"id": "x-clube-norte", "name": "Clube Norte, APD", "short_name": "Norte", "website": "https://clube.example/"}


class ApdCase(RegistrationCase):
    async def rule(self, rule: dict[str, Any], expect: int = 200) -> dict[str, str]:
        admin = await self.staff("admin")
        r = await self.client.patch(f"/api/v1/fields/{self.field_id}", json={"apd": rule}, headers=admin)
        self.assertEqual(r.status_code, expect, r.text)
        self.last = r.json()
        return admin


class ListAndRuleTests(ApdCase):
    async def test_the_project_list_is_public_and_the_files_agree(self) -> None:
        r = await self.client.get("/api/v1/apds")
        self.assertEqual(r.status_code, 200)
        shipped = json.loads((ROOT / "registry" / "apds" / "apds.json").read_text(encoding="utf-8"))
        self.assertEqual(r.json(), {"format": 1, "apds": [{k: v for k, v in e.items() if k != "source"}
                                                          for e in shipped["apds"]]})
        self.assertTrue(all(e["country"] == "PT" for e in r.json()["apds"]))
        r = await self.client.get("/api/v1/apds?country=ES")  # one country's entries
        self.assertEqual(r.json(), {"format": 1, "apds": []})
        r = await self.client.get("/api/v1/apds?country=PT")
        self.assertEqual(len(r.json()["apds"]), len(shipped["apds"]))
        r = await self.client.get("/api/v1/apds?country=pt")
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "country_invalid"))
        copy = Path(__file__).resolve().parents[1] / "atalaia_server" / "data" / "apds.json"
        self.assertEqual(copy.read_bytes(), (ROOT / "registry" / "apds" / "apds.json").read_bytes())

    async def test_the_field_rule_is_set_by_its_admin_and_validated(self) -> None:
        await self.rule({"checkin": True, "expiry": True, "accepted": ["apd-a"], "custom": [OWN]})
        shown = self.last
        gm = await self.staff("gm")
        r = await self.client.patch(f"/api/v1/fields/{self.field_id}", json={"apd": {"checkin": False}}, headers=gm)
        self.assertEqual(r.status_code, 403)  # only the admin
        for bad in ({"accepted": []}, {"extra": 1}, {"checkin": "yes"}, {"custom": [dict(OWN, id="apd-b")]}):
            await self.rule(bad, expect=400)
        self.assertEqual(shown["apd"], {"accepted": ["apd-a"], "register": False, "checkin": True, "expiry": True,
                                        "custom": [OWN]})
        audit = await self.fetch("SELECT details FROM audit_log WHERE action = 'field_update'")
        self.assertNotIn("Clube Norte", json.dumps([dict(a) for a in audit], default=str))
        await self.rule({})  # back to the default
        self.assertEqual(self.last["apd"], apd_core.default_rule())

    async def test_the_field_answer_carries_the_rule(self) -> None:
        await self.rule({"register": True, "accepted": ["apd-a"], "custom": [OWN]})
        plain = await self.pull("/api/v1/sync/field")
        self.assertNotIn("settings", plain)  # unchanged without the query: an older controller checks it strictly
        self.assertNotIn("apd", plain["field"])
        answer = await self.pull("/api/v1/sync/field?settings=1")
        sync_format.check_field(json.loads(json.dumps(answer)))
        self.assertEqual(answer["settings"]["apd"]["accepted"], ["apd-a"])
        self.assertTrue(answer["settings"]["apd"]["register"])
        await self.rule({})
        answer = await self.pull("/api/v1/sync/field?settings=1")
        self.assertEqual(answer["settings"]["apd"], apd_core.default_rule())

    async def test_the_games_for_the_app_carry_the_rule(self) -> None:
        await self.rule({"checkin": True})
        r = await self.client.get("/api/v1/fields-by-slug/campo", headers=self.player)
        self.assertEqual(r.json()["field"]["apd"]["checkin"], True)


class CountryTests(ApdCase):
    """Package H (decisions MEM-1 to MEM-6): the field's country picks the wording and the list it offers."""

    async def patch(self, body: dict[str, Any], expect: int = 200) -> dict[str, Any]:
        admin = await self.staff("admin")
        r = await self.client.patch(f"/api/v1/fields/{self.field_id}", json=body, headers=admin)
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    async def test_the_admin_sets_and_clears_the_country(self) -> None:
        self.assertEqual((await self.patch({"country": "es"}))["country"], "ES")  # capitals whatever the case typed
        self.assertEqual((await self.fetch("SELECT country FROM fields"))[0][0], "ES")
        for bad in ("ESP", "E", "1A", "E S"):
            await self.patch({"country": bad}, expect=400)
        self.assertIsNone((await self.patch({"country": None}))["country"])
        self.assertEqual((await self.patch({"country": "pt"}))["country"], "PT")
        self.assertIsNone((await self.patch({"country": ""}))["country"])
        gm = await self.staff("gm")
        r = await self.client.patch(f"/api/v1/fields/{self.field_id}", json={"country": "PT"}, headers=gm)
        self.assertEqual(r.status_code, 403)  # only the admin
        audit = await self.fetch("SELECT details FROM audit_log WHERE action = 'field_update'")
        self.assertIn("ES", json.dumps([dict(a) for a in audit], default=str))

    async def test_the_list_a_field_offers_is_its_countrys_plus_its_own(self) -> None:
        await self.rule({"custom": [OWN]})
        await self.patch({"country": "PT"})
        r = await self.client.get("/api/v1/fields-by-slug/campo", headers=self.player)
        field = r.json()["field"]
        self.assertEqual(field["country"], "PT")
        self.assertEqual([e["id"] for e in field["apds"]], ["ala", "apacorp", "apap"])
        self.assertEqual(field["apd"]["custom"], [OWN])
        await self.patch({"country": "ES"})
        field = (await self.client.get("/api/v1/fields-by-slug/campo", headers=self.player)).json()["field"]
        self.assertEqual((field["country"], field["apds"], field["apd"]["custom"]), ("ES", [], [OWN]))
        await self.patch({"country": None})  # no country: only its own entries
        field = (await self.client.get("/api/v1/fields-by-slug/campo", headers=self.player)).json()["field"]
        self.assertEqual((field["country"], field["apds"]), (None, []))
        game = await self.game()
        staff = await self.staff("gm")
        listed = (await self.client.get(self.path(game), headers=staff)).json()
        self.assertEqual((listed["country"], listed["apds"]), (None, []))
        await self.patch({"country": "PT"})
        listed = (await self.client.get(self.path(game), headers=staff)).json()
        self.assertEqual((listed["country"], len(listed["apds"])), ("PT", 3))

    async def test_the_accepted_rule_is_unchanged_by_the_country(self) -> None:
        await self.rule({"register": True, "accepted": ["apd-a"]})
        await self.patch({"country": "ES"})
        game = await self.game(federation="optional")
        r = await self.client.post(self.path(game), json={"display_name": "Rui", "membership_number": "1",
                                                          "apd_id": "apd-b"}, headers=self.player)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "apd_not_accepted"))
        r = await self.client.post(self.path(game), json={"display_name": "Rui", "membership_number": "1",
                                                          "apd_id": "apd-a"}, headers=self.player)
        self.assertEqual(r.status_code, 201, r.text)

    async def test_the_country_travels_with_the_settings(self) -> None:
        await self.patch({"country": "ES"})
        plain = await self.pull("/api/v1/sync/field")
        self.assertNotIn("country", plain["field"])  # unchanged without the query
        answer = await self.pull("/api/v1/sync/field?settings=1")
        sync_format.check_field(json.loads(json.dumps(answer)))
        self.assertEqual(answer["settings"]["country"], "ES")
        await self.patch({"country": None})
        answer = await self.pull("/api/v1/sync/field?settings=1")
        sync_format.check_field(json.loads(json.dumps(answer)))
        self.assertIsNone(answer["settings"]["country"])

    async def test_the_public_page_words_follow_the_country(self) -> None:
        await self.rule({"register": True, "checkin": True, "custom": [OWN]})
        await self.fetch("UPDATE fields SET public_page = true")
        game = await self.game(federation="off")
        for country, words in (("PT", {"pt": "Filiação numa APD", "en": "APD membership", "de": "APD-Mitgliedschaft",
                                       "zh-tw": "APD 會員資格"}),
                               ("ES", {"pt": "Filiação numa associação", "en": "Association membership",
                                       "de": "Verbandsmitgliedschaft", "zh-tw": "協會會員資格"}),
                               (None, {"en": "Association membership"})):
            await self.fetch("UPDATE fields SET country = $1", country)
            for lang, word in words.items():
                r = await self.client.get(f"/f/campo/games/{game.id}?lang={lang}")
                self.assertEqual(r.status_code, 200, (country, lang))
                self.assertIn(word, r.text)
                if country != "PT" and lang == "en":
                    self.assertIn("any association", r.text)
                    self.assertNotIn("any APD", r.text)


class RegisterTests(ApdCase):
    async def test_the_old_federation_number_is_a_membership_number_with_the_apd_unknown(self) -> None:
        game = await self.game(federation="required")
        out = await self.register(game, federation_number="FPA-1")
        self.assertEqual((out["federation_number"], out["membership_number"], out["apd_id"],
                          out["membership_expires"], out["apd_status"]), ("FPA-1", "FPA-1", None, None, None))

    async def test_the_two_names_of_the_number_must_agree(self) -> None:
        game = await self.game(federation="optional")
        r = await self.client.post(self.path(game), json={"federation_number": "1", "membership_number": "2"},
                                   headers=self.player)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "membership_number_conflict"))
        out = await self.register(game, membership_number="7", federation_number="7", apd_id="apd-a",
                                  membership_expires="2031-01-31")
        self.assertEqual((out["federation_number"], out["apd_id"], out["membership_expires"]),
                         ("7", "apd-a", "2031-01-31"))

    async def test_bad_values_are_refused(self) -> None:
        game = await self.game(federation="optional")
        for body, code in (({"apd_id": "APD A"}, "apd_id_invalid"), ({"membership_expires": "31/01/2031"},
                                                                     "membership_expires_invalid"),
                           ({"membership_expires": "2031-02-30"}, "membership_expires_invalid"),
                           ({"membership_number": "x" * 33}, "federation_number_invalid")):
            r = await self.client.post(self.path(game), json=body, headers=self.player)
            self.assertEqual((r.status_code, r.json()["detail"]), (400, code), body)

    async def test_nothing_is_kept_when_neither_the_game_nor_the_field_asks(self) -> None:
        game = await self.game(federation="off")
        out = await self.register(game, membership_number="1", apd_id="apd-a", membership_expires="2031-01-31")
        self.assertEqual((out["federation_number"], out["apd_id"], out["membership_expires"]), (None, None, None))

    async def test_a_register_rule_keeps_the_membership_even_when_the_game_asks_none(self) -> None:
        await self.rule({"register": True})
        game = await self.game(federation="off")
        r = await self.client.post(self.path(game), json={}, headers=self.player)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "membership_missing"))
        out = await self.register(game, membership_number="1")
        self.assertEqual((out["federation_number"], out["apd_status"]), ("1", "valid"))

    async def test_the_register_rule_refuses_what_is_not_accepted_or_expired(self) -> None:
        await self.rule({"register": True, "expiry": True, "accepted": ["apd-a", "x-clube-norte"], "custom": [OWN]})
        game = await self.game(federation="optional", starts=48)
        far = (date.today() + timedelta(days=400)).isoformat()
        for body, code in (({"membership_number": "1", "apd_id": "apd-a"}, "membership_missing"),  # no expiry
                           ({"membership_number": "1", "apd_id": "apd-b", "membership_expires": far},
                            "apd_not_accepted"),
                           ({"membership_number": "1", "membership_expires": far}, "apd_not_accepted"),
                           ({"membership_number": "1", "apd_id": "apd-a",
                             "membership_expires": (date.today() - timedelta(days=1)).isoformat()},
                            "membership_expired")):
            r = await self.client.post(self.path(game), json=body, headers=self.player)
            self.assertEqual((r.status_code, r.json()["detail"]), (400, code), body)
        out = await self.register(game, membership_number="1", apd_id="x-clube-norte", membership_expires=far)
        self.assertEqual((out["apd_id"], out["apd_status"]), ("x-clube-norte", "valid"))

    async def test_the_game_day_decides_the_expiry(self) -> None:
        await self.rule({"register": True, "expiry": True})
        game = await self.game(federation="optional", starts=24 * 20)
        day = game.starts_at.date()
        r = await self.client.post(self.path(game), json={"membership_number": "1", "membership_expires": (
            day - timedelta(days=2)).isoformat()}, headers=self.player)
        self.assertEqual(r.json()["detail"], "membership_expired")
        out = await self.register(game, membership_number="1",
                                  membership_expires=(day + timedelta(days=2)).isoformat())
        self.assertEqual(out["apd_status"], "valid")

    async def test_without_register_the_registration_is_kept_and_staff_see_the_verdict(self) -> None:
        admin = await self.rule({"checkin": True, "expiry": True, "accepted": ["apd-a"]})
        game = await self.game(federation="optional")
        out = await self.register(game, membership_number="1", apd_id="apd-b",
                                  membership_expires="2031-01-31")
        self.assertEqual(out["apd_status"], "not_accepted")
        listed = (await self.client.get(self.path(game), headers=admin)).json()
        self.assertEqual([r["apd_status"] for r in listed["registrations"]], ["not_accepted"])
        self.assertEqual(listed["apd"]["accepted"], ["apd-a"])
        self.assertIn("apds", listed)
        r = await self.client.patch(f"/api/v1/me/registrations/{out['id']}", headers=self.player,
                                    json={"apd_id": "apd-a"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["apd_status"], "valid")

    async def test_the_player_changes_the_membership_and_a_register_rule_still_holds(self) -> None:
        await self.rule({"register": True})
        game = await self.game(federation="optional")
        out = await self.register(game, membership_number="1")
        r = await self.client.patch(f"/api/v1/me/registrations/{out['id']}", json={"federation_number": None},
                                    headers=self.player)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "membership_missing"))

    async def test_staff_are_never_blocked_by_the_register_rule(self) -> None:
        admin = await self.rule({"register": True})
        game = await self.game(federation="optional")
        out = await self.register(game, membership_number="1")
        r = await self.client.patch(f"{self.path(game)}/{out['id']}", json={"federation_number": None}, headers=admin)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["federation_number"], r.json()["apd_status"]), (None, "missing"))

    async def test_the_public_page_names_the_rule(self) -> None:
        await self.rule({"register": True, "checkin": True, "accepted": ["x-clube-norte"], "custom": [OWN]})
        await self.fetch("UPDATE fields SET public_page = true, country = 'PT'")
        game = await self.game(federation="off")
        for lang, word in (("pt", "Filiação numa APD"), ("en", "APD membership"), ("de", "APD-Mitgliedschaft"),
                           ("zh-tw", "APD 會員資格")):
            r = await self.client.get(f"/f/campo/games/{game.id}?lang={lang}")
            self.assertEqual(r.status_code, 200, (lang, r.text[:200]))
            self.assertIn(word, r.text)
            self.assertIn("Clube Norte, APD", r.text)


class SyncAndDataTests(ApdCase):
    async def test_the_roster_brings_the_membership_and_the_rule(self) -> None:
        await self.rule({"checkin": True, "expiry": True, "custom": [OWN]})
        game = await self.game(federation="off")
        out = await self.register(game, membership_number="FPA-9", apd_id="x-clube-norte",
                                  membership_expires="2031-01-31")
        answer = await self.pull(f"/api/v1/sync/roster?scheduled_game_id={game.id}")
        sync_format.check_roster(json.loads(json.dumps(answer)))
        self.assertEqual(answer["apd"]["checkin"], True)
        reg = answer["registrations"][0]
        self.assertEqual((reg["federation_number"], reg["apd_id"], reg["membership_expires"]),
                         ("FPA-9", "x-clube-norte", "2031-01-31"))
        self.assertEqual(reg["registration_id"], out["id"])

    async def test_without_a_rule_the_roster_is_what_it_was(self) -> None:
        game = await self.game(federation="optional")
        await self.register(game, membership_number="FPA-9", apd_id="apd-a")
        answer = await self.pull(f"/api/v1/sync/roster?scheduled_game_id={game.id}")
        self.assertNotIn("apd", answer)
        reg = answer["registrations"][0]
        self.assertEqual(reg["federation_number"], "FPA-9")
        self.assertIn("apd_id", reg)  # a game that asks for the number shares the APD with it

    async def test_export_erasure_and_retention_cover_the_new_fields(self) -> None:
        await self.rule({"checkin": True})
        upcoming = await self.game(federation="optional")
        out = await self.register(upcoming, membership_number="FPA-9", apd_id="apd-a", membership_expires="2031-01-31")
        data = (await self.client.get("/api/v1/me/data", headers=self.player)).json()
        self.assertEqual((data["registrations"][0]["apd_id"], data["registrations"][0]["membership_expires"],
                          data["registrations"][0]["membership_number"]), ("apd-a", "2031-01-31", "FPA-9"))
        r = await self.client.get("/api/v1/me/export", headers=self.player)
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            self.assertEqual(json.loads(zf.read("export/registrations.json")), data["registrations"])
        # the retention: 30 days after the game, with the number
        old = await self.game(starts=-24 * 40, window=False, federation="optional")
        await self.fetch("INSERT INTO game_registrations (scheduled_game, field_id, player_id, display_name, "
                         "federation_number, apd_id, membership_expires, status) VALUES "
                         "($1, $2, 'p-abcdefgh2345', 'Rui', 'FPA-1', 'apd-a', '2031-01-31', 'checked_in')",
                         old.id, self.field_id)
        async with self.app.state.sessionmaker() as db:
            await personal_data.purge(db)
        rows = {r["scheduled_game"]: tuple(r)[1:] for r in await self.fetch(
            "SELECT scheduled_game, federation_number, apd_id, membership_expires FROM game_registrations")}
        self.assertEqual(rows[old.id], (None, None, None))
        self.assertEqual(rows[upcoming.id][:2], ("FPA-9", "apd-a"))
        # the erasure
        r = await self.client.request("DELETE", "/api/v1/me", json={"password": PASSWORD}, headers=self.player)
        self.assertEqual(r.status_code, 204, r.text)
        row = (await self.fetch("SELECT federation_number, apd_id, membership_expires FROM game_registrations "
                                "WHERE id = $1", __import__("uuid").UUID(out["id"])))[0]
        self.assertEqual(tuple(row), (None, None, None))
