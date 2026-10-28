# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A field's branding and saved teams, and their sync to the field's controllers (P4R19; plan phase 18).

On PostgreSQL 16: the field's staff edit its branding and saved teams (a club's team carries the club's
short name and crest), ``GET /api/v1/sync/field`` answers what ``sync_format.check_field`` accepts, and
``GET /api/v1/sync/images/{sha256}`` serves only the field's own images. End to end with the real field
controller (engine, store, branding and sync client over a real socket, as ``test_sync_e2e``): a club's
crest follows its team to a second field's controller, each controller checks every image again with
``images.py``, and a team the site removes goes from the controller.
"""

from __future__ import annotations

import copy
import hashlib
import os
import tempfile
import unittest
import uuid
from typing import Any, Optional

from atalaia_controller import images, sync_format
from atalaia_controller.branding import Branding
from atalaia_controller.config import Config
from atalaia_controller.engine import Conflict, Controller
from atalaia_controller.store import Store
from atalaia_controller.sync_client import SyncClient

from atalaia_server import sync
from atalaia_server.services import registration

from .base import AppTestCase, TempDatabase
from .pngs import png
from .test_remote_gm import Stream
from .test_sync_e2e import CORE, REPO, SiteServer


class FieldBrandingTests(AppTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.field_id = await self.make_field("campo-tejo")
        self.key = sync.new_key()
        await self.fetch("INSERT INTO field_api_keys (field_id, key_sha256) VALUES ($1, $2)", self.field_id,
                         sync.key_hash(self.key))
        self.admin = await self.staff("admin")
        self.gm = await self.staff("gm")

    async def make_field(self, slug: str) -> uuid.UUID:
        return (await self.fetch("INSERT INTO fields (name, slug) VALUES ($1, $2) RETURNING id", slug.title(),
                                 slug))[0][0]

    async def staff(self, role: str, field_id: Optional[uuid.UUID] = None) -> dict[str, str]:
        user_id, name, secret = await self.make_user(with_totp=True)
        await self.fetch("INSERT INTO user_field_roles (user_id, field_id, role_id) VALUES ($1, $2, $3)",
                         user_id, field_id or self.field_id, {"gm": 5, "admin": 7}[role])
        return await self.auth(name, secret=secret)

    def url(self, path: str = "", field: Optional[uuid.UUID] = None) -> str:
        return f"/api/v1/fields/{field or self.field_id}{path}"

    async def put_image(self, path: str, data: bytes, headers: dict[str, str], expect: int = 200) -> Any:
        r = await self.client.put(self.url(path) + "?rights_confirmed=true", content=data,
                                  headers={**headers, "Content-Type": "image/png"})
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    async def club(self, slug: str, public: bool, crest: Optional[bytes] = None,
                   headers: Optional[dict[str, str]] = None) -> str:
        """A club made through the API by ``headers``' account (a new one by default), with a crest."""
        if headers is None:
            _, name, _ = await self.make_user()
            headers = await self.auth(name)
        r = await self.client.post("/api/v1/clubs", json={"name": f"Clube {slug}", "short_name": slug.title(),
                                                          "slug": slug}, headers=headers)
        club = r.json()["id"]
        if public:
            await self.client.patch(f"/api/v1/clubs/{club}", json={"public_page": True}, headers=headers)
        if crest is not None:
            r = await self.client.put(f"/api/v1/clubs/{club}/images/crest?rights_confirmed=true", content=crest,
                                      headers={**headers, "Content-Type": "image/png"})
            self.assertEqual(r.status_code, 200, r.text)
        return club

    async def sync_field(self, key: Optional[str] = None, settings: bool = False) -> dict[str, Any]:
        r = await self.client.get("/api/v1/sync/field" + ("?settings=1" if settings else ""),
                                  headers={"Authorization": f"Bearer {key or self.key}"})
        self.assertEqual(r.status_code, 200, r.text)
        return sync_format.check_field(copy.deepcopy(r.json()))

    async def test_branding(self) -> None:
        self.assertEqual(await self.sync_field(), {"sync_version": 1, "teams": [], "field": {
            "field_name": None, "accent": None, "logo": None, "wallpaper": None}})
        r = await self.client.patch(self.url("/branding"), json={"accent": "#C0FFEE"}, headers=self.gm)
        self.assertEqual(r.status_code, 403)  # the field's admin only
        r = await self.client.patch(self.url("/branding"), json={"accent": "#C0FFEE", "field_name": "Campo Tejo"},
                                    headers=self.admin)
        self.assertEqual((r.json()["accent"], r.json()["field_name"]), ("#c0ffee", "Campo Tejo"))
        for bad in ({"accent": "red"}, {"field_name": "x" * 49}, {"field_name": "a\nb"}):
            r = await self.client.patch(self.url("/branding"), json=bad, headers=self.admin)
            self.assertEqual(r.status_code, 400, bad)
        r = await self.client.put(self.url("/branding/logo"), content=png(64, 32), headers={
            **self.admin, "Content-Type": "image/png"})
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "rights_not_confirmed"))
        out = await self.put_image("/branding/logo", png(64, 32, text=b"exif-like"), self.admin)
        self.assertEqual(out["logo"]["width"], 64)
        await self.put_image("/branding/wallpaper", png(200, 200), self.admin, expect=422)  # under 320 px
        answer = await self.sync_field()
        self.assertEqual(answer["field"]["logo"], out["logo"])
        self.assertEqual(answer["field"]["accent"], "#c0ffee")
        r = await self.client.get(f"/api/v1/sync/images/{out['logo']['sha256']}",
                                  headers={"Authorization": f"Bearer {self.key}"})
        self.assertEqual((r.status_code, r.headers["content-type"]), (200, "image/png"))
        self.assertEqual(hashlib.sha256(r.content).hexdigest(), out["logo"]["sha256"])
        self.assertNotIn(b"exif-like", r.content)

    async def test_the_settings_come_only_to_a_controller_that_asks(self) -> None:
        """BR24: an older controller checks the answer strictly, so the settings are an opt-in (``?settings=1``)."""
        self.assertNotIn("settings", await self.sync_field())
        st = (await self.sync_field(settings=True))["settings"]
        self.assertEqual((st["federation_label"], st["max_replicas"], st["limit_template"]["id"]),
                         (None, 5, "portugal"))
        self.assertEqual(sorted(st["limit_template"]["classes"]), ["cqb", "dmr", "rifle", "sniper"])
        self.assertEqual(st["limit_template"]["classes"]["dmr"], {"max_energy_j": 1.88, "med_m": 20,
                                                                  "fire_mode": "semi_only"})
        r = await self.client.patch(self.url(), json={"limit_template": "uk", "max_replicas": 3,
                                                      "federation_label": "BAA"}, headers=self.admin)
        self.assertEqual(r.status_code, 200, r.text)
        st = (await self.sync_field(settings=True))["settings"]
        self.assertEqual((st["federation_label"], st["max_replicas"], st["limit_template"]["id"]), ("BAA", 3, "uk"))
        self.assertEqual(sorted(st["limit_template"]["classes"]), sorted(registration.classes("uk")))
        self.assertNotIn("settings", await self.sync_field())  # still the old shape without the query

    async def test_the_apd_rule_travels_in_the_settings_and_its_change_sends_a_note(self) -> None:
        """protocol/apd.md: ``settings.apd`` (only with ``?settings=1``), and ``PATCH /fields`` of a rule sends
        ``field.changed`` like the other settings."""
        stream = await self.listen()
        self.assertNotIn("apd", (await self.sync_field())["field"])
        self.assertEqual((await self.sync_field(settings=True))["settings"]["apd"]["checkin"], False)
        rule = {"checkin": True, "expiry": True, "accepted": ["apd-a"]}
        r = await self.client.patch(self.url(), json={"apd": rule}, headers=self.admin)
        self.assertEqual(r.status_code, 200, r.text)
        await self.expect_note(stream, "the APD rule")
        st = (await self.sync_field(settings=True))["settings"]
        self.assertEqual((st["apd"]["accepted"], st["apd"]["checkin"]), (["apd-a"], True))
        await self.client.patch(self.url(), json={"apd": rule}, headers=self.admin)  # no change
        await self.expect_note(stream, "the same rule", notes=0)
        r = await self.client.patch(self.url(), json={"apd": {"nope": 1}}, headers=self.admin)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "apd_rule_invalid"))

    async def test_every_limit_template_passes_the_controllers_check(self) -> None:
        from atalaia_controller import checkin  # noqa: PLC0415

        names = sorted(registration.limit_templates())
        self.assertGreaterEqual(len(names), 4)
        for name in names:
            with self.subTest(template=name):
                body = registration.limit_template_body(name)
                assert body is not None
                st = {"federation_label": None, "max_replicas": 5, "limit_template": body}
                sync_format.check_field_settings(copy.deepcopy(st))
                # The controller's own loader reads the same file into the same classes and limits.
                local = checkin.load_limits(name)
                self.assertEqual({n: c["max_energy_j"] for n, c in local["classes"].items()},
                                 {n: c["max_energy_j"] for n, c in checkin.site_limits(body)["classes"].items()})
        self.assertIsNone(registration.limit_template_body("nope"))
        self.assertIsNone(registration.limit_template_body("../portugal"))

    async def listen(self) -> Stream:
        """A controller of the field connected on the stream (it only said ``hello``)."""
        stream = Stream(self.app, self.key)
        self.addAsyncCleanup(stream.close)
        self.assertEqual((await stream.open())["type"], "websocket.accept")
        await stream.send({"type": "hello", "sync_version": 1, "remote_gm": False,
                           "controller": {"id": "0192f3a4-5b6c-7d8e-9f01-23456789abcd", "version": "0.1.0"}})
        self.assertEqual((await stream.receive())["type"], "hello.ack")
        return stream

    async def expect_note(self, stream: Stream, what: str, notes: int = 1) -> None:
        await self.app.state.remote_hub.settle()
        for _ in range(notes):
            self.assertEqual(await stream.receive(), {"type": "field.changed", "sync_version": 1}, what)
        self.assertEqual(stream.pending(), 0, what)

    async def test_a_change_reaches_the_controllers_on_the_stream(self) -> None:
        """BR24: branding, saved teams, a club's crest and the check-in settings each send ``field.changed``."""
        stream = await self.listen()
        patch = self.client.patch
        r = await patch(self.url("/branding"), json={"accent": "#C0FFEE"}, headers=self.admin)
        self.assertEqual(r.status_code, 200)
        await self.expect_note(stream, "accent")
        await patch(self.url("/branding"), json={"accent": "#c0ffee"}, headers=self.admin)  # no change
        await self.expect_note(stream, "same accent", notes=0)
        await self.put_image("/branding/logo", png(64, 32), self.admin)
        await self.expect_note(stream, "logo")
        await self.client.delete(self.url("/branding/logo"), headers=self.admin)
        await self.expect_note(stream, "logo removed")
        await self.client.delete(self.url("/branding/logo"), headers=self.admin)  # nothing there
        await self.expect_note(stream, "no logo to remove", notes=0)
        club = await self.club("lobos", public=True, crest=png(64, 64, (30, 30, 200)), headers=self.gm)
        r = await self.client.post(self.url("/teams"), json={"club_slug": "lobos", "colour": "red"}, headers=self.gm)
        team = r.json()["team_id"]
        await self.expect_note(stream, "a team")
        await patch(self.url(f"/teams/{team}"), json={"colour": "blue"}, headers=self.gm)
        await self.expect_note(stream, "its colour")
        await self.put_image(f"/teams/{team}/crest", png(48, 48), self.gm)
        await self.expect_note(stream, "its own crest")
        await self.client.delete(self.url(f"/teams/{team}/crest"), headers=self.gm)
        await self.expect_note(stream, "its crest removed")
        # The club's crest and name reach the field because its team carries them.
        r = await self.client.put(f"/api/v1/clubs/{club}/images/crest?rights_confirmed=true", content=png(80, 80),
                                  headers={**self.gm, "Content-Type": "image/png"})
        self.assertEqual(r.status_code, 200, r.text)
        await self.expect_note(stream, "the club's crest")
        await patch(f"/api/v1/clubs/{club}", json={"short_name": "Lobitos"}, headers=self.gm)
        await self.expect_note(stream, "the club's short name")
        await patch(f"/api/v1/clubs/{club}", json={"description": "Só texto"}, headers=self.gm)
        await self.expect_note(stream, "a club description is not sent to controllers", notes=0)
        # The check-in settings change; a field page toggle does not.
        await patch(self.url(), json={"max_replicas": 2}, headers=self.admin)
        await self.expect_note(stream, "max_replicas")
        await patch(self.url(), json={"public_page": True}, headers=self.admin)
        await self.expect_note(stream, "public page", notes=0)
        await self.client.delete(self.url(f"/teams/{team}"), headers=self.gm)
        await self.expect_note(stream, "a team removed")
        r = await self.client.delete(f"/api/v1/clubs/{club}", headers=self.gm)
        self.assertEqual(r.status_code, 204)

    async def test_another_fields_change_does_not_reach_this_stream(self) -> None:
        stream = await self.listen()
        other = await self.make_field("campo-sado")
        admin = await self.staff("admin", other)
        r = await self.client.patch(self.url("/branding", other), json={"accent": "#112233"}, headers=admin)
        self.assertEqual(r.status_code, 200, r.text)
        await self.expect_note(stream, "another field", notes=0)

    async def test_a_gone_controller_does_not_fail_the_change(self) -> None:
        stream = await self.listen()
        assert stream.task is not None
        stream.task.cancel()  # the socket is gone without a disconnect: the link is still registered
        r = await self.client.patch(self.url("/branding"), json={"accent": "#C0FFEE"}, headers=self.admin)
        self.assertEqual(r.status_code, 200, r.text)
        await self.app.state.remote_hub.settle()

    async def test_saved_teams(self) -> None:
        crest = png(64, 64, (30, 30, 200))
        await self.club("lobos", public=True, crest=crest)
        await self.club("corvos", public=False, headers=self.gm)  # the gm's own club, not public
        r = await self.client.post(self.url("/teams"), json={"club_slug": "lobos", "colour": "red"}, headers=self.gm)
        self.assertEqual(r.status_code, 201, r.text)
        lobos = r.json()
        self.assertEqual((lobos["name"], lobos["colour"], lobos["club"]["slug"], lobos["own_name"]),
                         ("Lobos", "red", "lobos", None))
        self.assertEqual(lobos["crest"]["sha256"], hashlib.sha256(images.check(crest, "image/png",
                                                                               images.CREST).data).hexdigest())
        # A club whose page is not public: only one of its members can add it.
        r = await self.client.post(self.url("/teams"), json={"club_slug": "corvos"}, headers=self.admin)
        self.assertEqual(r.status_code, 404)
        r = await self.client.post(self.url("/teams"), json={"club_slug": "corvos"}, headers=self.gm)
        self.assertEqual(r.status_code, 201)
        await self.client.delete(self.url(f"/teams/{r.json()['team_id']}"), headers=self.gm)
        # A team of the field's own, its own crest; names stay unique on the field.
        r = await self.client.post(self.url("/teams"), json={"name": "Lobos"}, headers=self.gm)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "team_name_taken"))
        r = await self.client.post(self.url("/teams"), json={"name": "Javalis", "colour": "blue team"}, headers=self.gm)
        self.assertEqual(r.status_code, 400)  # a colour is a team name as boxes know it: no spaces
        r = await self.client.post(self.url("/teams"), json={}, headers=self.gm)
        self.assertEqual(r.status_code, 400)  # its own team needs a name
        r = await self.client.post(self.url("/teams"), json={"name": "Javalis", "colour": "blue"}, headers=self.gm)
        javalis = r.json()
        own = await self.put_image(f"/teams/{javalis['team_id']}/crest", png(48, 48), self.gm)
        self.assertTrue(own["own_crest"])
        # The club's team with a name of its own.
        r = await self.client.patch(self.url(f"/teams/{lobos['team_id']}"), json={"name": "Lobos B"}, headers=self.gm)
        self.assertEqual(r.json()["name"], "Lobos B")
        answer = await self.sync_field()
        self.assertEqual([(t["name"], t["colour"], (t["club"] or {}).get("slug")) for t in answer["teams"]],
                         [("Lobos B", "red", "lobos"), ("Javalis", "blue", None)])
        # Every image of the answer can be fetched by the field's key; another field's key gets none of them.
        other_id = await self.make_field("campo-norte")
        other_key = sync.new_key()
        await self.fetch("INSERT INTO field_api_keys (field_id, key_sha256) VALUES ($1, $2)", other_id,
                         sync.key_hash(other_key))
        for team in answer["teams"]:
            sha = team["crest"]["sha256"]
            mine = await self.client.get(f"/api/v1/sync/images/{sha}", headers={"Authorization": f"Bearer {self.key}"})
            self.assertEqual(mine.status_code, 200)
            theirs = await self.client.get(f"/api/v1/sync/images/{sha}",
                                           headers={"Authorization": f"Bearer {other_key}"})
            self.assertEqual(theirs.status_code, 404)
        self.assertEqual((await self.client.get(f"/api/v1/sync/images/{'0' * 64}")).status_code, 401)
        self.assertEqual((await self.client.get("/api/v1/sync/field")).status_code, 401)
        # A club renamed to another team's name: the answer keeps the first one (it stays a valid answer).
        await self.client.patch(self.url(f"/teams/{lobos['team_id']}"), json={"name": None}, headers=self.gm)
        await self.client.patch(self.url(f"/teams/{javalis['team_id']}"), json={"name": "Lobos"}, headers=self.gm)
        await self.fetch("UPDATE field_teams SET name = 'Lobos' WHERE id = $1", uuid.UUID(javalis["team_id"]))
        answer = await self.sync_field()
        self.assertEqual([t["name"] for t in answer["teams"]], ["Lobos"])
        r = await self.client.delete(self.url(f"/teams/{javalis['team_id']}"), headers=self.gm)
        self.assertEqual(r.status_code, 204)
        actions = {row["action"] for row in await self.fetch("SELECT action FROM audit_log")}
        self.assertTrue({"field_team_create", "field_team_update", "field_team_crest", "field_team_delete"} <= actions)


class CrestFollowsTheTeamTests(unittest.TestCase):
    """The real controller: two fields' controllers pull the same club's team, crest and all."""

    db: TempDatabase

    @classmethod
    def setUpClass(cls) -> None:
        cls.db = TempDatabase()
        cls.db.create()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.db.drop()

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.site = SiteServer(self.db.url).__enter__()

    def tearDown(self) -> None:
        self.site.__exit__(None, None, None)
        self.db.fetch("TRUNCATE fields, clubs, branding_images RESTART IDENTITY CASCADE")
        self.tmp.cleanup()

    def image(self, data: bytes, kind: str) -> str:
        checked = images.check(data, "image/png", images.KINDS[kind])
        sha = hashlib.sha256(checked.data).hexdigest()
        self.db.fetch("INSERT INTO branding_images (sha256, content_type, width, height, bytes, data) "
                      "VALUES ($1, $2, $3, $4, $5, $6) ON CONFLICT DO NOTHING", sha, checked.content_type,
                      checked.width, checked.height, len(checked.data), checked.data)
        return sha

    def field(self, slug: str) -> tuple[uuid.UUID, str]:
        field = self.db.fetch("INSERT INTO fields (name, slug) VALUES ($1, $1) RETURNING id", slug)[0][0]
        key = sync.new_key()
        self.db.fetch("INSERT INTO field_api_keys (field_id, key_sha256) VALUES ($1, $2)", field, sync.key_hash(key))
        return field, key

    def controller(self, name: str, key: str, branding: str = "site") -> tuple[Controller, Branding, SyncClient]:
        cfg = Config(db_path=os.path.join(self.tmp.name, f"{name}.db"), mqtt_enabled=False,
                     modes_dirs=[str(REPO / "modes")], sync_enabled=True, sync_url=self.site.url,
                     sync_api_key=key, sync_timeout_s=5.0, sync_branding=branding)
        cfg.validate()
        store = Store(cfg.db_path)
        ctrl = Controller(cfg, store, core=CORE)
        brand = Branding(ctrl)
        return ctrl, brand, SyncClient(cfg, store, branding=brand)

    def test_a_crest_follows_its_team_to_a_second_field(self) -> None:
        crest = self.image(png(96, 96, (200, 120, 0), text=b"made on a phone"), "crest")
        logo = self.image(png(256, 64, (0, 90, 40)), "logo")
        club = self.db.fetch("INSERT INTO clubs (name, short_name, slug, crest_sha256) VALUES "
                             "('Lobos do Pinhal Airsoft Clube', 'Lobos', 'lobos', $1) RETURNING id", crest)[0][0]
        north, north_key = self.field("campo-norte")
        south, south_key = self.field("campo-sul")
        self.db.fetch("UPDATE fields SET accent = '#1e6b3a', logo_sha256 = $2, branding_name = 'Campo Norte' "
                      "WHERE id = $1", north, logo)
        for field, colour in ((north, "red"), (south, "blue")):
            self.db.fetch("INSERT INTO field_teams (field_id, club_id, colour) VALUES ($1, $2, $3)", field, club,
                          colour)
        self.db.fetch("INSERT INTO field_teams (field_id, name) VALUES ($1, 'Corvos')", south)

        n_ctrl, n_brand, n_sync = self.controller("north", north_key)
        s_ctrl, s_brand, s_sync = self.controller("south", south_key)
        for client in (n_sync, s_sync):
            self.assertTrue(client.run_once(), client.last_error)

        n_presets = n_brand.team_presets()
        s_presets = {p["name"]: p for p in s_brand.team_presets()}
        self.assertEqual([(p["name"], p["colour"], p["crest_id"], p["source"]) for p in n_presets],
                         [("Lobos", "red", crest, "site")])
        self.assertEqual((s_presets["Lobos"]["colour"], s_presets["Lobos"]["crest_id"]), ("blue", crest))
        self.assertIsNone(s_presets["Corvos"]["crest_id"])
        # The same checked bytes on both controllers, served as the controller serves an uploaded crest.
        for ctrl in (n_ctrl, s_ctrl):
            img = ctrl.branding.crest(crest)
            self.assertIsNotNone(img)
            self.assertEqual(hashlib.sha256(img["data"]).hexdigest(), crest)
            self.assertNotIn(b"made on a phone", img["data"])
        view = n_brand.view()
        self.assertEqual((view["field_name"], view["accent"], view["logo"]["id"]), ("Campo Norte", "#1e6b3a", logo))
        self.assertIsNone(s_brand.view()["logo"])
        self.assertEqual(n_sync.status()["branding"]["images_fetched"], 2)

        # The site's branding is the field's now: the GM cannot change it, nor the site's presets, here.
        with self.assertRaises(Conflict):
            n_brand.set_field({"accent": "#000000"})
        with self.assertRaises(Conflict):
            n_brand.delete_team_preset(n_presets[0]["id"])
        mine = n_brand.save_team_preset({"name": "Convidados", "colour": "green"})  # one of its own is fine
        # Nothing changed: the next cycle fetches nothing.
        n_sync.run_once()
        self.assertEqual(n_sync.status()["branding"]["images_fetched"], 2)
        # The south field drops the club's team: its controller drops the preset; the GM's own stays at the north.
        self.db.fetch("DELETE FROM field_teams WHERE field_id = $1 AND club_id IS NOT NULL", south)
        self.assertTrue(s_sync.run_once(), s_sync.last_error)
        self.assertEqual([p["name"] for p in s_brand.team_presets()], ["Corvos"])
        self.assertIn(mine["id"], [p["id"] for p in n_brand.team_presets()])

    def test_local_branding_pulls_nothing(self) -> None:
        _, key = self.field("campo")
        _, brand, client = self.controller("local", key, branding="local")
        self.assertTrue(client.run_once(), client.last_error)
        self.assertEqual((client.status()["branding"]["pulled_at"], brand.team_presets()), (None, []))
        brand.set_field({"accent": "#123456"})  # the console's, as before


if __name__ == "__main__":
    unittest.main()
