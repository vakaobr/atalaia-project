# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Club profiles on PostgreSQL 16 (P4R19; plan phase 18, decisions S18-*).

A club and its members (invited, accepted, the last admin kept), its images checked by the controller's
``images.py`` (the rights reminder, the limits, metadata stripped), its public page off by default, the
report button and the server administrator who hides a page; and club membership as personal data (access,
export, erasure, the purge).
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from atalaia_controller import images

from atalaia_server import personal_data

from .base import AppTestCase
from .pngs import png

UTC = timezone.utc


class ClubCase(AppTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.owner_id, self.owner_name, _ = await self.make_user("rita")
        self.owner = await self.auth("rita")

    async def admin_headers(self) -> dict[str, str]:
        _, name, secret = await self.make_user("root", server_admin=True)
        return await self.auth(name, secret=secret)

    async def create(self, headers: Optional[dict[str, str]] = None, expect: int = 201, **over: Any) -> dict[str, Any]:
        body = {"name": "Lobos do Pinhal Airsoft Clube", "short_name": "Lobos", "slug": "lobos-do-pinhal",
                "description": "Jogamos ao domingo.\n\nNovos membros: bem-vindos.", "colour": "#1E6B3A", **over}
        r = await self.client.post("/api/v1/clubs", json=body, headers=headers or self.owner)
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    async def upload(self, club: str, slot: str, data: bytes, ctype: str = "image/png", expect: int = 200,
                     confirm: bool = True, headers: Optional[dict[str, str]] = None) -> Any:
        query = "?rights_confirmed=true" if confirm else ""
        r = await self.client.put(f"/api/v1/clubs/{club}/images/{slot}{query}", content=data,
                                  headers={**(headers or self.owner), "Content-Type": ctype})
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    async def make_public(self, club: str) -> None:
        r = await self.client.patch(f"/api/v1/clubs/{club}", json={"public_page": True}, headers=self.owner)
        self.assertEqual(r.status_code, 200, r.text)


class ClubTests(ClubCase):
    async def test_create_and_edit(self) -> None:
        club = await self.create()
        self.assertEqual((club["slug"], club["colour"], club["my_role"], club["public_page"], club["hidden"]),
                         ("lobos-do-pinhal", "#1e6b3a", "admin", False, False))
        await self.create(expect=409, name="Outro")  # the slug is taken
        await self.create(expect=400, slug="Lobos")
        await self.create(expect=400, slug="outro", colour="green")
        await self.create(expect=400, slug="outro", short_name="S" * 33)  # a team name on controllers: 32 at most
        r = await self.client.get("/api/v1/clubs", headers=self.owner)
        self.assertEqual([c["slug"] for c in r.json()], ["lobos-do-pinhal"])
        r = await self.client.patch(f"/api/v1/clubs/{club['id']}", json={"short_name": "Lobos PN", "colour": None},
                                    headers=self.owner)
        self.assertEqual((r.json()["short_name"], r.json()["colour"]), ("Lobos PN", None))
        actions = [row["action"] for row in await self.fetch("SELECT action FROM audit_log ORDER BY id")]
        self.assertIn("club_create", actions)
        self.assertIn("club_update", actions)

    async def test_a_private_club_is_its_members_only(self) -> None:
        club = await self.create()
        _, _, _ = await self.make_user("ze")
        ze = await self.auth("ze")
        self.assertEqual((await self.client.get(f"/api/v1/clubs/{club['id']}", headers=ze)).status_code, 404)
        r = await self.client.patch(f"/api/v1/clubs/{club['id']}", json={"name": "X"}, headers=ze)
        self.assertEqual(r.status_code, 404)
        await self.make_public(club["id"])
        self.assertEqual((await self.client.get(f"/api/v1/clubs/{club['id']}", headers=ze)).status_code, 200)
        r = await self.client.patch(f"/api/v1/clubs/{club['id']}", json={"name": "X"}, headers=ze)
        self.assertEqual(r.status_code, 403)
        # A server administrator manages every club.
        root = await self.admin_headers()
        r = await self.client.patch(f"/api/v1/clubs/{club['id']}", json={"name": "Lobos"}, headers=root)
        self.assertEqual((r.status_code, r.json()["name"]), (200, "Lobos"))

    async def test_images_are_checked_with_the_controllers_rules(self) -> None:
        club = (await self.create())["id"]
        crest = png(128, 128, text=b"taken at 38.7N 9.1W")
        await self.upload(club, "crest", crest, confirm=False, expect=400)  # the rights reminder must be confirmed
        out = await self.upload(club, "crest", crest)
        self.assertIn("pt", out["rights_notice"])
        stripped = images.check(crest, "image/png", images.CREST).data
        self.assertNotIn(b"38.7N", stripped)
        self.assertEqual(out["crest"], {"sha256": hashlib.sha256(stripped).hexdigest(), "content_type": "image/png",
                                        "width": 128, "height": 128, "bytes": len(stripped)})
        stored = await self.fetch("SELECT data FROM branding_images WHERE sha256 = $1", out["crest"]["sha256"])
        self.assertEqual(bytes(stored[0]["data"]), stripped)
        await self.upload(club, "crest", b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml", expect=415)
        await self.upload(club, "crest", crest, "image/jpeg", expect=415)  # the file says PNG
        await self.upload(club, "crest", png(8, 8), expect=422)  # under 16 px
        await self.upload(club, "crest", png(1100, 20), expect=422)  # over 1024 px
        await self.upload(club, "crest", b"\x00" * (images.CREST.max_bytes + 1), expect=413)
        await self.upload(club, "logo", png(2048, 512))  # a logo may be 2048 px and 4:1 (8:1 at most)
        await self.upload(club, "banner", crest, expect=404)
        r = await self.client.delete(f"/api/v1/clubs/{club}/images/crest", headers=self.owner)
        self.assertIsNone(r.json()["crest"])

    async def test_members(self) -> None:
        club = (await self.create())["id"]
        ana_id, _, _ = await self.make_user("ana")
        ana = await self.auth("ana")
        r = await self.client.put(f"/api/v1/clubs/{club}/members", json={"username": "Ana"}, headers=self.owner)
        self.assertEqual((r.status_code, r.json()["accepted"]), (201, False))
        # Invited, not yet a member: the club is still not hers to see, nor her name to other members.
        self.assertEqual((await self.client.get(f"/api/v1/clubs/{club}", headers=ana)).status_code, 404)
        mine = (await self.client.get("/api/v1/me/clubs", headers=ana)).json()
        self.assertEqual([(m["slug"], m["accepted"]) for m in mine], [("lobos-do-pinhal", False)])
        r = await self.client.post(f"/api/v1/me/clubs/{club}/accept", headers=ana)
        self.assertTrue(r.json()["accepted"])
        members = (await self.client.get(f"/api/v1/clubs/{club}/members", headers=ana)).json()
        self.assertEqual({(m["username"], m["role"]) for m in members}, {("rita", "admin"), ("ana", "member")})
        # A member cannot invite; the last admin cannot leave or be demoted; a second admin can.
        r = await self.client.put(f"/api/v1/clubs/{club}/members", json={"username": "rita", "role": "member"},
                                  headers=ana)
        self.assertEqual(r.status_code, 403)
        r = await self.client.put(f"/api/v1/clubs/{club}/members", json={"username": "rita", "role": "member"},
                                  headers=self.owner)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "last_admin"))
        r = await self.client.delete(f"/api/v1/clubs/{club}/members/{self.owner_id}", headers=self.owner)
        self.assertEqual(r.status_code, 409)
        r = await self.client.put(f"/api/v1/clubs/{club}/members", json={"username": "ana", "role": "admin"},
                                  headers=self.owner)
        self.assertEqual(r.json()["role"], "admin")
        r = await self.client.delete(f"/api/v1/clubs/{club}/members/{self.owner_id}", headers=self.owner)
        self.assertEqual(r.status_code, 204)
        r = await self.client.delete(f"/api/v1/clubs/{club}/members/{ana_id}", headers=ana)
        self.assertEqual(r.status_code, 409)  # now she is the last admin
        actions = {row["action"] for row in await self.fetch("SELECT action FROM audit_log")}
        self.assertTrue({"club_invite", "club_join", "club_role", "club_leave"} <= actions)

    async def test_delete_takes_the_fields_teams(self) -> None:
        club = (await self.create())["id"]
        field = (await self.fetch("INSERT INTO fields (name, slug) VALUES ('Campo', 'campo') RETURNING id"))[0][0]
        await self.fetch("INSERT INTO field_teams (field_id, club_id) VALUES ($1, $2)", field, club)
        r = await self.client.delete(f"/api/v1/clubs/{club}", headers=self.owner)
        self.assertEqual(r.status_code, 204)
        self.assertEqual((await self.fetch("SELECT count(*) FROM field_teams"))[0][0], 0)


class PublicPageTests(ClubCase):
    async def test_off_by_default_then_on(self) -> None:
        club = await self.create()
        await self.upload(club["id"], "crest", png(64, 64, (10, 20, 30)))
        self.assertEqual((await self.client.get("/c/lobos-do-pinhal/")).status_code, 404)
        self.assertEqual((await self.client.get("/c/lobos-do-pinhal/crest")).status_code, 404)
        await self.make_public(club["id"])
        r = await self.client.get("/c/lobos-do-pinhal/?lang=en")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("Lobos do Pinhal Airsoft Clube", r.text)
        self.assertIn("background: #1e6b3a", r.text)
        self.assertIn('href="/c/lobos-do-pinhal/report?lang=en"', r.text)
        self.assertNotIn("rita", r.text)  # no member is ever named
        self.assertNotIn("<script", r.text)
        for lang, html_lang, report, crest_alt in (("de", "de", "Diese Seite melden", "Wappen von "),
                                                   ("zh-tw", "zh-Hant-TW", "檢舉這個頁面", " 的隊徽")):
            with self.subTest(lang=lang):
                page = await self.client.get("/c/lobos-do-pinhal/", params={"lang": lang})
                self.assertIn(f'<html lang="{html_lang}">', page.text)
                self.assertIn(f'href="/c/lobos-do-pinhal/report?lang={lang}">{report}</a>', page.text)
                self.assertIn(crest_alt, page.text)
                self.assertIn('href="/c/lobos-do-pinhal/?lang=pt">Português</a>', page.text)
        crest = await self.client.get("/c/lobos-do-pinhal/crest")
        self.assertEqual((crest.status_code, crest.headers["content-type"]), (200, "image/png"))
        self.assertEqual(crest.headers["x-content-type-options"], "nosniff")
        again = await self.client.get("/c/lobos-do-pinhal/crest", headers={"If-None-Match": crest.headers["etag"]})
        self.assertEqual(again.status_code, 304)
        self.assertEqual((await self.client.get("/c/lobos-do-pinhal/logo")).status_code, 404)
        self.assertEqual((await self.client.get("/c/lobos-do-pinhal")).status_code, 308)
        self.assertEqual((await self.client.get("/c/Not_A_Slug/")).status_code, 404)

    async def test_report_and_hide(self) -> None:
        club = await self.create()
        await self.make_public(club["id"])
        form = await self.client.get("/c/lobos-do-pinhal/report")
        self.assertEqual(form.status_code, 200)
        self.assertIn('name="reason" value="rights"', form.text)
        r = await self.client.post("/c/lobos-do-pinhal/report", content="reason=rights&text=O+emblema+%C3%A9+nosso",
                                   headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("administração do servidor", r.text)
        r = await self.client.post("/c/lobos-do-pinhal/report", content="reason=spam",
                                   headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(r.status_code, 400)
        # The API, with a login: the account is kept with the report, never an address.
        r = await self.client.post("/api/v1/club-reports", json={"slug": "lobos-do-pinhal", "reason": "offensive"},
                                   headers=self.owner)
        self.assertEqual(r.status_code, 201, r.text)
        rows = await self.fetch("SELECT reason, text, reporter_id FROM club_reports ORDER BY created_at")
        self.assertEqual([(x["reason"], x["text"], x["reporter_id"]) for x in rows],
                         [("rights", "O emblema é nosso", None), ("offensive", None, self.owner_id)])
        self.assertEqual((await self.fetch("SELECT count(*) FROM audit_log WHERE action = 'club_report' "
                                           "AND ip_address IS NOT NULL"))[0][0], 0)
        # Five an hour from one address.
        for _ in range(3):
            await self.client.post("/api/v1/club-reports", json={"slug": "lobos-do-pinhal", "reason": "other"})
        r = await self.client.post("/c/lobos-do-pinhal/report", content="reason=other",
                                   headers={"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(r.status_code, 429)

        self.assertEqual((await self.client.get("/api/v1/admin/club-reports", headers=self.owner)).status_code, 403)
        root = await self.admin_headers()
        reports = (await self.client.get("/api/v1/admin/club-reports", headers=root)).json()
        self.assertEqual(len(reports), 5)
        r = await self.client.put(f"/api/v1/admin/clubs/{club['id']}/hidden", json={"reason": "Emblema de outro clube"},
                                  headers=root)
        self.assertTrue(r.json()["hidden"])
        r = await self.client.patch(f"/api/v1/admin/club-reports/{reports[0]['id']}", json={"status": "actioned"},
                                    headers=root)
        self.assertEqual((r.json()["status"], r.json()["club_hidden"]), ("actioned", True))
        self.assertEqual((await self.client.get("/c/lobos-do-pinhal/")).status_code, 404)
        r = await self.client.post("/api/v1/club-reports", json={"slug": "lobos-do-pinhal", "reason": "other"})
        self.assertEqual(r.status_code, 404)  # a hidden page cannot be reported again
        # The club's own admins still see it, with the reason.
        mine = (await self.client.get(f"/api/v1/clubs/{club['id']}", headers=self.owner)).json()
        self.assertEqual((mine["hidden"], mine["hidden_reason"]), (True, "Emblema de outro clube"))
        await self.client.delete(f"/api/v1/admin/clubs/{club['id']}/hidden", headers=root)
        self.assertEqual((await self.client.get("/c/lobos-do-pinhal/")).status_code, 200)
        actions = {row["action"] for row in await self.fetch("SELECT action FROM audit_log")}
        self.assertTrue({"club_hide", "club_show", "club_report_decide"} <= actions)


class ClubPersonalDataTests(ClubCase):
    async def test_access_export_erasure(self) -> None:
        club = (await self.create())["id"]
        await self.make_public(club)
        ana_id, _, _ = await self.make_user("ana")
        ana = await self.auth("ana")
        await self.client.put(f"/api/v1/clubs/{club}/members", json={"username": "ana"}, headers=self.owner)
        await self.client.post(f"/api/v1/me/clubs/{club}/accept", headers=ana)
        await self.client.post("/api/v1/club-reports", json={"slug": "lobos-do-pinhal", "reason": "other",
                                                             "text": "teste"}, headers=ana)
        data = (await self.client.get("/api/v1/me/data", headers=ana)).json()
        self.assertEqual([(c["slug"], c["role"], c["created_by_you"]) for c in data["clubs"]],
                         [("lobos-do-pinhal", "member", False)])
        self.assertEqual([(r["club"], r["text"]) for r in data["club_reports"]], [("lobos-do-pinhal", "teste")])
        owner = (await self.client.get("/api/v1/me/data", headers=self.owner)).json()
        self.assertTrue(owner["clubs"][0]["created_by_you"])
        r = await self.client.get("/api/v1/me/export", headers=ana)
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            self.assertEqual(json.loads(zf.read("export/clubs.json")), data["clubs"])
            self.assertEqual(json.loads(zf.read("export/club_reports.json")), data["club_reports"])
            self.assertIn("clubs.json", zf.read("export/README.txt").decode())

        async with self.app.state.sessionmaker() as db:
            await personal_data.erase(db, self.owner_id)
            await personal_data.erase(db, ana_id)
            await db.commit()
        self.assertEqual((await self.fetch("SELECT count(*) FROM club_members"))[0][0], 0)
        row = (await self.fetch("SELECT created_by, name FROM clubs"))[0]
        self.assertEqual((row["created_by"], row["name"]), (None, "Lobos do Pinhal Airsoft Clube"))  # the club stays
        self.assertEqual((await self.fetch("SELECT reporter_id FROM club_reports"))[0][0], None)

    async def test_purge(self) -> None:
        club = (await self.create())["id"]
        now = datetime.now(UTC)
        late_id, _, _ = await self.make_user("late")
        recent_id, _, _ = await self.make_user("recent")
        await self.fetch("INSERT INTO club_members (club_id, user_id, created_at) VALUES ($1, $2, $3)",
                         club, late_id, now - timedelta(days=31))
        await self.fetch("INSERT INTO club_members (club_id, user_id, created_at) VALUES ($1, $2, $3)",
                         club, recent_id, now - timedelta(days=29))
        for status, decided in (("dismissed", now - timedelta(days=366)), ("actioned", now - timedelta(days=300)),
                                ("open", None)):
            await self.fetch("INSERT INTO club_reports (club_id, reason, status, decided_at, created_at) VALUES "
                             "($1, 'other', $2, $3, $4)", club, status, decided, now - timedelta(days=400))
        used = await self.upload(club, "crest", png(32, 32))
        await self.client.delete(f"/api/v1/clubs/{club}/images/crest", headers=self.owner)
        await self.upload(club, "crest", png(40, 40))
        await self.fetch("UPDATE branding_images SET created_at = $1", now - timedelta(days=2))
        async with self.app.state.sessionmaker() as db:
            counts = await personal_data.purge(db, now)
        self.assertEqual((counts["club_invitations"], counts["club_reports"], counts["branding_images"]), (1, 1, 1))
        left = {r[0] for r in await self.fetch("SELECT user_id FROM club_members")}
        self.assertEqual(left, {self.owner_id, recent_id})  # an accepted membership stays
        gone = await self.fetch("SELECT count(*) FROM branding_images WHERE sha256 = $1", used["crest"]["sha256"])
        self.assertEqual(gone[0][0], 0)
