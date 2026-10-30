# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The registration import and the CSV export on PostgreSQL 16 (ADR-P4-12; plan phase 17, decisions F20, S17-*).

A dry run that writes nothing, the real import, idempotent re-import by (source, external_ref), row-level
refusals next to rows that go in, the limits, the staff rules, the roster an imported registration goes in,
the export (formula-safe, imports back unchanged), the guest purge, and what the audit log holds. The format's
own checks are ``tests.test_import_format`` (no database).
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Optional

from atalaia_controller import sync_format

from atalaia_server import import_format, personal_data
from atalaia_server.models import ScheduledGame

from .test_registrations import RegistrationCase

CSV = ("Nome completo,display_name,external_ref,Email,team_preference,federation_number,replicas\r\n"
       "Ana Maria Silva,Ana,ref-1,ana@example.pt,red,FPA-1,aeg:rifle:Tokyo Marui M4\r\n"
       "Bruno Costa,Bruno,ref-2,bruno@example.pt,blue,,gbb:rifle|sniper:sniper\r\n"
       "Carla,Carla,,carla@example.pt,,,\r\n")


class ImportCase(RegistrationCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.admin = await self.staff("admin")

    def import_path(self, game: ScheduledGame) -> str:
        return self.path(game) + "/import"

    async def run_import(self, game: ScheduledGame, data: Any, source: str = "plataforma", dry_run: bool = False,
                         media: str = "text/csv", expect: int = 200, headers: Optional[dict[str, str]] = None,
                         confirmed: bool = True) -> dict[str, Any]:
        body = data if isinstance(data, bytes) else (data.encode("utf-8") if isinstance(data, str)
                                                     else json.dumps(data).encode())
        params = {"source": source, "dry_run": str(dry_run).lower()}
        if confirmed:
            params["basis_confirmed"] = "true"
        r = await self.client.post(self.import_path(game), content=body, params=params,
                                   headers={**(headers or self.admin), "Content-Type": media})
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    async def regs(self, game: ScheduledGame) -> list[Any]:
        return await self.fetch("SELECT * FROM game_registrations WHERE scheduled_game = $1 ORDER BY created_at, id",
                                game.id)


class ImportTests(ImportCase):
    async def test_membership_columns_import_update_and_export(self) -> None:
        """The APD and expiry columns (protocol/apd.md): stored, changed by a later file, dropped when the game
        asks for no membership, and written back by the export."""
        game = await self.game(federation="optional")
        data = ("display_name,external_ref,federation_number,apd_id,membership_expires\n"
                "Ana,r1,FPA-1,x-clube,2027-03-01\nBea,r2,FPA-2,,\nCris,r3,,FPA,\n")
        out = await self.run_import(game, data)
        self.assertEqual([(r["result"], r.get("code")) for r in out["results"]],
                         [("created", None), ("created", None), ("refused", "apd_id_invalid")])
        rows = await self.regs(game)
        self.assertEqual([(r["apd_id"], str(r["membership_expires"])) for r in rows],
                         [("x-clube", "2027-03-01"), (None, "None")])
        again = await self.run_import(game, data.replace("FPA,", ","))
        self.assertEqual([r["result"] for r in again["results"][:2]], ["unchanged", "unchanged"])
        out = await self.run_import(game, "display_name,external_ref,apd_id,membership_expires\n"
                                          "Ana,r1,,2028-01-31\nBea,r2,x-clube,\n")
        self.assertEqual([r["changed"] for r in out["results"]],
                         [["apd_id", "membership_expires"], ["apd_id"]])
        rows = await self.regs(game)
        self.assertEqual([(r["apd_id"], str(r["membership_expires"]), r["federation_number"]) for r in rows[:2]],
                         [(None, "2028-01-31", "FPA-1"), ("x-clube", "None", "FPA-2")])
        r = await self.client.get(self.path(game) + ".csv", headers=self.admin)
        lines = r.text.lstrip("\ufeff").splitlines()  # the export starts with a byte order mark
        self.assertTrue(lines[0].startswith("display_name,external_ref,team_preference,federation_number,"
                                            "apd_id,membership_expires,replicas,"))
        self.assertTrue(lines[1].startswith("Ana,r1,,FPA-1,,2028-01-31,,"), lines[1])
        # A game that asks for no membership drops all three.
        off = await self.game(federation="off")
        out = await self.run_import(off, data)
        self.assertEqual(out["results"][0]["warnings"],
                         ["federation_number_dropped", "apd_id_dropped", "membership_expires_dropped"])

    async def test_dry_run_then_import_then_again(self) -> None:
        game = await self.game(federation="optional")
        preview = await self.run_import(game, CSV, dry_run=True, confirmed=False)
        self.assertEqual(preview["counts"], {"created": 3, "updated": 0, "unchanged": 0, "skipped": 0, "refused": 0})
        self.assertEqual(preview["not_imported_columns"], ["Nome completo", "Email"])
        self.assertEqual(preview["columns"], ["display_name", "external_ref", "team_preference",
                                              "federation_number", "replicas"])
        self.assertEqual([r["result"] for r in preview["results"]], ["created"] * 3)
        self.assertEqual(preview["results"][2]["warnings"], ["no_external_ref"])
        self.assertNotIn("registration_id", preview["results"][0])
        self.assertEqual(await self.regs(game), [])  # a dry run writes nothing
        self.assertEqual(await self.fetch("SELECT * FROM audit_log WHERE action = 'registration_import'"), [])
        text = json.dumps(preview)
        for private in ("ana@example.pt", "Ana Maria Silva", "Bruno Costa"):
            self.assertNotIn(private, text)

        await self.run_import(game, CSV, confirmed=False, expect=400)  # the field must confirm its basis
        first = await self.run_import(game, CSV)
        self.assertEqual(first["counts"]["created"], 3)
        rows = await self.regs(game)
        self.assertEqual([(r["display_name"], r["external_ref"], r["source"], r["user_id"], r["ticket_hash"],
                           r["status"]) for r in rows],
                         [("Ana", "ref-1", "plataforma", None, None, "registered"),
                          ("Bruno", "ref-2", "plataforma", None, None, "registered"),
                          ("Carla", None, "plataforma", None, None, "registered")])
        self.assertEqual((rows[0]["team_preference"], rows[0]["federation_number"]), ("red", "FPA-1"))
        for r in rows:
            self.assertRegex(r["player_id"], r"^p-[a-z2-7]{12}$")
        self.assertEqual(len({r["player_id"] for r in rows}), 3)
        reps = await self.fetch("SELECT replica_type, replica_class, make_model FROM registration_replicas "
                                "ORDER BY registration, position")
        self.assertEqual(len(reps), 3)
        # Nothing of the ignored columns was stored anywhere.
        dump = json.dumps([dict(r) for r in await self.fetch("SELECT * FROM game_registrations")], default=str)
        dump += json.dumps([dict(r) for r in await self.fetch("SELECT * FROM audit_log")], default=str)
        for private in ("ana@example.pt", "Ana Maria Silva", "bruno@example.pt"):
            self.assertNotIn(private, dump)
        audit = (await self.fetch("SELECT details FROM audit_log WHERE action = 'registration_import'"))[0]["details"]
        audit = json.loads(audit) if isinstance(audit, str) else audit
        self.assertEqual((audit["source"], audit["counts"]["created"], audit["not_imported_columns"]),
                         ("plataforma", 3, ["Nome completo", "Email"]))

        # The same export again: nothing changes, except the row without a reference, added again.
        again = await self.run_import(game, CSV)
        self.assertEqual([r["result"] for r in again["results"]], ["unchanged", "unchanged", "created"])
        self.assertEqual(again["results"][0]["registration_id"], str(rows[0]["id"]))
        self.assertEqual(len(await self.regs(game)), 4)
        same = await self.fetch("SELECT declaration_id FROM registration_replicas ORDER BY declaration_id")
        self.assertEqual(len(same), 3)  # unchanged replicas keep their declaration ids

        # An updated export: Ana changes team and replicas, Bruno is gone (listed, not cancelled).
        updated = ("display_name,external_ref,team_preference,replicas\n"
                   "Ana,ref-1,blue,dmr:dmr\n")
        out = await self.run_import(game, updated)
        self.assertEqual(out["results"][0]["changed"], ["team_preference", "replicas"])
        self.assertEqual(out["missing"], {"count": 1, "external_refs": ["ref-2"]})
        ana = (await self.regs(game))[0]
        self.assertEqual((ana["team_preference"], ana["federation_number"]), ("blue", "FPA-1"))  # no column: kept
        self.assertEqual([tuple(r) for r in await self.fetch(
            "SELECT replica_type, replica_class FROM registration_replicas WHERE registration = $1", ana["id"])],
            [("dmr", "dmr")])
        bruno = (await self.regs(game))[1]
        self.assertEqual(bruno["status"], "registered")

        # Another source with the same references makes other registrations.
        other = await self.run_import(game, "display_name,external_ref\nAna,ref-1\n", source="outra")
        self.assertEqual(other["counts"]["created"], 1)
        self.assertEqual(other["results"][0]["warnings"], ["same_name"])

    async def test_row_errors_next_to_rows_that_go_in(self) -> None:
        game = await self.game(federation="required", max_players=3)
        await self.register(game, federation_number="FPA-0")  # one place taken on the site
        data = [
            {"display_name": "Ana", "external_ref": "1", "federation_number": "FPA-1"},
            {"display_name": "Bea", "external_ref": "2"},
            {"display_name": "Cris", "external_ref": "1", "federation_number": "FPA-3"},
            {"display_name": "Dina", "external_ref": "4", "federation_number": "FPA-4", "team_preference": "green"},
            {"display_name": "Eva", "external_ref": "5", "federation_number": "FPA-5",
             "replicas": [{"type": "aeg", "class": "minigun"}]},
            {"display_name": "Fá", "external_ref": "6", "federation_number": "FPA-6"},
            {"display_name": "Gil", "external_ref": "7", "federation_number": "FPA-7"},
        ]
        out = await self.run_import(game, data, media="application/json; charset=utf-8")
        self.assertEqual([(r["row"], r["result"], r.get("code")) for r in out["results"]], [
            (1, "created", None), (2, "refused", "federation_number_required"), (3, "refused", "external_ref_twice"),
            (4, "refused", "team_preference_invalid"), (5, "refused", "replica_class_invalid"),
            (6, "created", None), (7, "refused", "game_full")])
        self.assertEqual(len(await self.regs(game)), 3)
        feed = await self.client.get(f"/api/v1/fields/{self.field_id}/scheduled-games/{game.id}", headers=self.admin)
        self.assertEqual(feed.json()["places_left"], 0)

    async def test_cancelled_ones_are_skipped(self) -> None:
        game = await self.game()
        await self.run_import(game, "display_name,external_ref\nAna,1\n")
        reg = (await self.regs(game))[0]
        r = await self.client.delete(self.path(game) + f"/{reg['id']}", headers=self.admin)
        self.assertEqual(r.status_code, 204)
        out = await self.run_import(game, "display_name,external_ref\nAna,1\n")
        self.assertEqual((out["results"][0]["result"], out["results"][0]["code"]), ("skipped", "cancelled"))
        self.assertEqual((await self.regs(game))[0]["status"], "cancelled")

    async def test_the_file_and_the_request(self) -> None:
        game = await self.game()
        await self.run_import(game, "x", media="text/plain", expect=415)
        await self.run_import(game, "x", media="text/csv; charset=latin-1", expect=415)
        bad = await self.run_import(game, 'display_name\n"Ana\n', expect=400)
        self.assertEqual(bad["detail"], "csv_invalid")
        self.assertEqual((await self.run_import(game, "nome\nAna\n", expect=400))["detail"],
                         "display_name_column_missing")
        self.assertEqual((await self.run_import(game, b"display_name\n" + b"A" * import_format.MAX_BYTES,
                                                expect=413))["detail"], "too_large")
        for source in ("site", "Plataforma", "a b"):
            with self.subTest(source=source):
                self.assertEqual((await self.run_import(game, CSV, source=source, expect=400))["detail"],
                                 "source_invalid")
        self.assertEqual(await self.regs(game), [])

    async def test_who_and_when(self) -> None:
        game = await self.game()
        await self.run_import(game, CSV, headers=self.player, expect=403)  # a player is not the field's staff
        marshal = await self.staff("marshal")
        await self.run_import(game, CSV, headers=marshal, expect=403)
        gm = await self.staff("gm")
        await self.run_import(game, CSV, headers=gm, dry_run=True)
        draft = await self.game(status="draft")
        await self.run_import(draft, CSV, expect=404)
        started = await self.game(starts=-1)
        self.assertEqual((await self.run_import(started, CSV, expect=409))["detail"], "game_started")
        cancelled = await self.game(status="cancelled", cancelled_reason="Chuva")
        self.assertEqual((await self.run_import(cancelled, CSV, expect=409))["detail"], "game_cancelled")
        closed = await self.game(window=False)
        self.assertEqual((await self.run_import(closed, CSV))["counts"]["created"], 3)  # no window needed: staff
        other, _ = await self.make_field("arena")
        r = await self.client.post(f"/api/v1/fields/{other}/scheduled-games/{game.id}/registrations/import",
                                   params={"source": "x", "dry_run": "true"}, content=b"display_name\nA\n",
                                   headers={**self.admin, "Content-Type": "text/csv"})
        self.assertEqual(r.status_code, 403)

    async def test_imported_ones_in_the_roster_without_a_ticket(self) -> None:
        game = await self.game(federation="optional")
        await self.run_import(game, CSV)
        answer = await self.pull(f"/api/v1/sync/roster?scheduled_game_id={game.id}")
        sync_format.check_roster(json.loads(json.dumps(answer)))
        names = {r["display_name"]: r for r in answer["registrations"]}
        self.assertEqual(set(names), {"Ana", "Bruno", "Carla"})
        self.assertNotIn("ticket_sha256", names["Ana"])
        self.assertEqual(names["Ana"]["federation_number"], "FPA-1")
        self.assertEqual([(d["type"], d["class"], d["make_model"]) for d in names["Ana"]["replicas"]],
                         [("aeg", "rifle", "Tokyo Marui M4")])
        staff = (await self.client.get(self.path(game), headers=self.admin)).json()
        self.assertEqual(sorted((r["source"], r["external_ref"] or "") for r in staff["registrations"]),
                         [("plataforma", ""), ("plataforma", "ref-1"), ("plataforma", "ref-2")])


class ExportTests(ImportCase):
    async def test_export_is_safe_and_imports_back(self) -> None:
        game = await self.game(federation="optional")
        await self.register(game, display_name="=cmd|' /C calc'!A0", federation_number="+351")
        await self.run_import(game, "display_name,external_ref,replicas\n@Lobo,-9,aeg:rifle:=M4\n")
        r = await self.client.get(self.path(game) + ".csv", headers=self.admin)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "text/csv; charset=utf-8")
        self.assertIn("attachment", r.headers["content-disposition"])
        self.assertTrue(r.content.startswith(b"\xef\xbb\xbf"))
        text = r.content.decode("utf-8-sig")
        for line in text.splitlines()[1:]:
            for cell in line.split(","):
                self.assertFalse(cell[:1] in "=+-@" and cell, cell)
        self.assertIn("'=cmd|' /C calc'!A0", text)
        self.assertIn("'@Lobo,'-9,", text)
        # The export imports back into another game: the same values, the site's own row as a guest of "export".
        copy = await self.game()
        out = await self.run_import(copy, r.content, source="export")
        self.assertEqual(out["counts"]["created"], 2)
        self.assertEqual(out["not_imported_columns"], ["registration_id", "player_id", "status", "source"])
        names = sorted(r["display_name"] for r in await self.regs(copy))
        self.assertEqual(names, ["=cmd|' /C calc'!A0", "@Lobo"])
        self.assertEqual((await self.client.get(self.path(game) + ".csv", headers=self.player)).status_code, 403)
        self.assertEqual(len(await self.fetch("SELECT * FROM audit_log WHERE action = 'registration_export'")), 1)


class GuestDataTests(ImportCase):
    async def test_imported_registrations_go_30_days_after_the_game(self) -> None:
        old = await self.game(starts=-24 * 40, window=False)
        recent = await self.game(starts=-24 * 10, window=False)
        for game in (old, recent):
            for source, pid in (("plataforma", "p-aaaaaaaaaaaa"), ("site", "p-bbbbbbbbbbbb")):
                reg = (await self.fetch(
                    "INSERT INTO game_registrations (scheduled_game, field_id, player_id, display_name, status, "
                    "source, external_ref) VALUES ($1, $2, $3, 'Ana', 'checked_in', $4, $5) RETURNING id",
                    game.id, self.field_id, pid, source, "r1" if source != "site" else None))[0][0]
                await self.fetch("INSERT INTO registration_replicas (registration, declaration_id, replica_type, "
                                 "replica_class, position) VALUES ($1, $2, 'aeg', 'rifle', 0)", reg, uuid.uuid4())
        async with self.app.state.sessionmaker() as db:
            counts = await personal_data.purge(db)
        self.assertEqual(counts["imported_registrations"], 1)
        left = {(r[0], r[1]) for r in await self.fetch("SELECT scheduled_game, source FROM game_registrations")}
        self.assertEqual(left, {(old.id, "site"), (recent.id, "site"), (recent.id, "plataforma")})
        self.assertEqual(await self.count("registration_replicas"), 3)  # the purged one's went with it

    async def test_not_in_anyones_personal_data(self) -> None:
        game = await self.game()
        await self.run_import(game, "display_name,external_ref\nJoana,1\n")  # the player's own name, by chance
        mine = (await self.client.get("/api/v1/me/registrations", headers=self.player)).json()
        self.assertEqual(mine, [])


class FieldGamesTests(ImportCase):
    """GET /api/v1/fields-by-slug/{slug}: what the app shows before registering (decisions S16-13, S17-9)."""

    async def test_a_field_without_its_public_page_is_not_found_by_slug(self) -> None:
        """SRV-6: public_page off hides the field and its games from the app's lookup, but not from its own staff."""
        await self.game()
        await self.fetch("UPDATE fields SET public_page = false")
        stranger = self.player  # an account with no role on the field
        r = await self.client.get("/api/v1/fields-by-slug/campo", headers=stranger)
        self.assertEqual((r.status_code, r.json()["detail"]), (404, "field_not_found"))
        self.assertEqual((await self.client.get("/api/v1/fields-by-slug/campo", headers=self.admin)).status_code, 200)
        await self.fetch("UPDATE fields SET public_page = true")
        self.assertEqual((await self.client.get("/api/v1/fields-by-slug/campo", headers=stranger)).status_code, 200)

    async def test_the_fields_games_for_the_app(self) -> None:
        game = await self.game(federation="required", max_players=10, teams=["red", "blue"])
        await self.game(status="draft")
        await self.game(starts=-24 * 3, window=False)  # already ended
        await self.register(game, federation_number="FPA-1", display_name="Falcão")
        r = await self.client.get("/api/v1/fields-by-slug/campo", headers=self.player)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual((body["field"]["id"], body["field"]["slug"], body["field"]["limit_template"],
                          body["field"]["max_replicas"]), (str(self.field_id), "campo", "portugal", 5))
        self.assertIn("rifle", body["field"]["classes"])
        self.assertEqual([g["id"] for g in body["games"]], [str(game.id)])
        g = body["games"][0]
        self.assertEqual((g["registration_state"], g["registration_open"], g["places_left"], g["federation"],
                          g["teams"], g["predeclare_replicas"]), ("open", True, 9, "required", ["red", "blue"], True))
        self.assertNotIn("Falcão", r.text)
        self.assertNotIn("joana", r.text)
        self.assertEqual((await self.client.get("/api/v1/fields-by-slug/campo")).status_code, 401)
        for slug in ("nope", "Campo", "a" * 200):
            with self.subTest(slug=slug):
                self.assertEqual((await self.client.get(f"/api/v1/fields-by-slug/{slug}",
                                                        headers=self.player)).status_code, 404)
