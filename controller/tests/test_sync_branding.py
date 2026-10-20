# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Branding from the site server on the controller (P4R19; phase 4, plan phase 18).

With ``[sync] branding = "site"`` the sync client pulls the field's branding and saved teams, fetches each
image it does not have by its SHA-256, checks it again with ``images.py`` (the same limits as an upload to
the console) and ``Branding.apply_site`` makes the field's branding and the site's team presets match; the
console can then change neither (409), only its own presets. Against an in-memory site server whose answers
pass ``sync_format.check_field`` (the real one: server/tests/test_branding_sync.py).

    cd controller && python -m unittest discover -s tests
"""

from __future__ import annotations

import copy
import hashlib
import logging
from pathlib import Path
from typing import Any, Optional

from p3support import GM, P3Case

from atalaia_controller import images, sync_format
from atalaia_controller.config import ConfigError
from atalaia_controller.sync_client import SyncClient, SyncError
from support import config

logging.getLogger("atalaia.sync").setLevel(logging.CRITICAL)
logging.getLogger("atalaia.branding").setLevel(logging.CRITICAL)
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "branding"
TYPES = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}


def stored(name: str, kind: str) -> tuple[bytes, dict[str, Any]]:
    """A fixture as the site server stores it (checked, stripped) and its reference in the answer."""
    ctype = TYPES[name.rsplit(".", 1)[1]]
    checked = images.check((FIXTURES / name).read_bytes(), ctype, images.KINDS[kind])
    return checked.data, {"sha256": hashlib.sha256(checked.data).hexdigest(), "content_type": ctype,
                          "width": checked.width, "height": checked.height, "bytes": len(checked.data)}


class FakeSite:
    """``GET /api/v1/sync/field`` and ``/api/v1/sync/images/{sha256}`` in memory (game day: nothing)."""

    def __init__(self) -> None:
        self.field: dict[str, Any] = {"field_name": None, "accent": None, "logo": None, "wallpaper": None}
        self.teams: list[dict[str, Any]] = []
        self.images: dict[str, bytes] = {}
        self.gets: list[str] = []
        self.no_branding = False

    def add(self, name: str, kind: str) -> dict[str, Any]:
        data, ref = stored(name, kind)
        self.images[ref["sha256"]] = data
        return ref

    def get(self, path: str) -> dict[str, Any]:
        self.gets.append(path)
        if path == "/api/v1/sync/field":
            if self.no_branding:
                raise SyncError("Not Found", 404)
            answer = {"sync_version": 1, "field": copy.deepcopy(self.field), "teams": copy.deepcopy(self.teams)}
            sync_format.check_field(copy.deepcopy(answer))
            return answer
        if path.startswith("/api/v1/sync/schedule"):
            return {"sync_version": 1, "games": []}
        return {"sync_version": 1, "claims": []}

    def get_bytes(self, path: str, limit: int) -> bytes:
        self.gets.append(path)
        sha = path.rsplit("/", 1)[1]
        if sha not in self.images:
            raise SyncError("image_not_found", 404)
        data = self.images[sha]
        if len(data) > limit:
            raise SyncError("too_large")
        return data

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return {}


def team(team_id: str, name: str, colour: Optional[str] = None, crest: Optional[dict[str, Any]] = None,
         club: Optional[dict[str, str]] = None) -> dict[str, Any]:
    return {"team_id": f"0192f3a4-0000-7000-8000-{team_id:0>12}", "name": name, "colour": colour, "crest": crest,
            "club": club}


class SiteBrandingCase(P3Case):
    cfg_overrides = {"sync_url": "https://site.example.org", "sync_enabled": True, "sync_branding": "site"}

    def setUp(self) -> None:
        super().setUp()
        self.site = FakeSite()
        self.brand = self.ctrl.branding
        self.sync = SyncClient(self.cfg, self.bundle.store, api_key="k" * 43, transport=self.site,
                               checkin=self.svc, branding=self.brand)

    def cycle(self) -> None:
        self.assertTrue(self.sync.run_once(), self.sync.last_error)

    def presets(self) -> dict[str, dict[str, Any]]:
        return {p["name"]: p for p in self.client.get("/api/v1/team-presets", headers=GM).json()}


class SiteBrandingTests(SiteBrandingCase):
    def test_the_site_branding_is_applied(self) -> None:
        logo = self.site.add("logo.png", "logo")
        wall = self.site.add("wallpaper.webp", "wallpaper")
        red = self.site.add("crest-red.png", "crest")
        self.site.field.update(field_name="Campo do Pinhal", accent="#1e6b3a", logo=logo, wallpaper=wall)
        self.site.teams = [team("1", "Lobos", "red", red, {"slug": "lobos", "name": "Lobos do Pinhal"}),
                           team("2", "Corvos")]
        self.cycle()
        view = self.client.get("/api/v1/field/branding").json()
        self.assertEqual((view["field_name"], view["accent"], view["logo"]["id"], view["wallpaper"]["id"]),
                         ("Campo do Pinhal", "#1e6b3a", logo["sha256"], wall["sha256"]))
        self.assertEqual(self.client.get("/api/v1/field/branding/logo").content, self.site.images[logo["sha256"]])
        self.assertEqual(self.svc.poster_fields()["field_name"], "Campo do Pinhal")  # one name (BR4)
        presets = self.presets()
        self.assertEqual((presets["Lobos"]["colour"], presets["Lobos"]["crest_id"], presets["Lobos"]["source"]),
                         ("red", red["sha256"], "site"))
        crest = self.client.get(presets["Lobos"]["crest_url"])
        self.assertEqual(hashlib.sha256(crest.content).hexdigest(), red["sha256"])
        self.assertIsNone(presets["Corvos"]["crest_id"])
        self.assertEqual(self.sync.status()["branding"]["images_fetched"], 3)
        # Nothing new: no image is fetched again.
        fetched = len(self.site.gets)
        self.cycle()
        self.assertEqual([p for p in self.site.gets[fetched:] if "/images/" in p], [])
        # The site renames a team, changes its crest and drops the other; the old crest goes after its grace.
        blue = self.site.add("crest-blue.webp", "crest")
        self.site.teams = [team("1", "Lobos B", "red", blue)]
        self.site.field.update(accent=None, wallpaper=None)
        self.cycle()
        presets = self.presets()
        self.assertEqual(list(presets), ["Lobos B"])
        self.assertEqual(presets["Lobos B"]["crest_id"], blue["sha256"])
        view = self.client.get("/api/v1/field/branding").json()
        self.assertEqual((view["accent"], view["wallpaper"]), (None, None))
        self.assertIsNotNone(self.bundle.store.image(red["sha256"], with_data=False))  # still in its grace day
        self.assertIsNone(self.bundle.store.image(wall["sha256"], with_data=False))

    def test_the_console_cannot_change_what_the_site_sets(self) -> None:
        self.site.teams = [team("1", "Lobos", "red")]
        self.cycle()
        r = self.client.put("/api/v1/field/branding", json={"accent": "#123456"}, headers=GM)
        self.assertEqual(r.status_code, 409, r.text)
        data, ref = stored("logo.png", "logo")
        r = self.client.put("/api/v1/field/branding/logo", content=data, headers={**GM, "Content-Type": "image/png"})
        self.assertEqual(r.status_code, 409)
        lobos = self.presets()["Lobos"]
        r = self.client.put(f"/api/v1/team-presets/{lobos['id']}", json={"colour": "blue"}, headers=GM)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.client.delete(f"/api/v1/team-presets/{lobos['id']}", headers=GM).status_code, 409)
        # The GM's own presets are still the GM's; one with a site team's name becomes the site's.
        r = self.client.post("/api/v1/team-presets", json={"name": "Convidados"}, headers=GM)
        self.assertEqual(r.status_code, 201, r.text)
        self.site.teams.append(team("2", "Convidados", "green"))
        self.cycle()
        presets = self.presets()
        guests = presets["Convidados"]
        self.assertEqual((guests["id"], guests["colour"], guests["source"]), (r.json()["id"], "green", "site"))
        del ref

    def test_a_bad_image_is_refused_and_the_rest_applied(self) -> None:
        red = self.site.add("crest-red.png", "crest")
        blue = self.site.add("crest-blue.webp", "crest")
        self.site.images[red["sha256"]] = (FIXTURES / "crest-blue.webp").read_bytes()  # not what the hash says
        raw = (FIXTURES / "logo.png").read_bytes()  # with its metadata: not as the site server stores images
        logo = {"sha256": hashlib.sha256(raw).hexdigest(), "content_type": "image/png", "width": 256, "height": 128,
                "bytes": len(raw)}
        self.site.images[logo["sha256"]] = raw
        self.site.field["logo"] = logo
        self.site.teams = [team("1", "Lobos", "red", red), team("2", "Corvos", "blue", blue)]
        self.cycle()
        presets = self.presets()
        self.assertIsNone(presets["Lobos"]["crest_id"])  # the team is there, without the crest that failed
        self.assertEqual(presets["Corvos"]["crest_id"], blue["sha256"])
        self.assertIsNone(self.client.get("/api/v1/field/branding").json()["logo"])
        self.assertIsNone(self.bundle.store.image(red["sha256"], with_data=False))
        self.assertEqual(self.sync.status()["branding"]["error"], "2 images not fetched yet")
        # Fixed on the site: the next cycle fetches it.
        self.site.images[red["sha256"]] = stored("crest-red.png", "crest")[0]
        self.cycle()
        self.assertEqual(self.presets()["Lobos"]["crest_id"], red["sha256"])

    def test_an_older_site_server_is_skipped(self) -> None:
        self.site.no_branding = True
        self.cycle()
        self.assertFalse(self.sync.status()["branding"]["supported"])
        self.assertEqual(self.presets(), {})


class LocalBrandingTests(SiteBrandingCase):
    cfg_overrides = {"sync_url": "https://site.example.org", "sync_enabled": True}

    def test_local_pulls_nothing_and_the_console_keeps_its_branding(self) -> None:
        self.cycle()
        self.assertNotIn("/api/v1/sync/field", self.site.gets)
        r = self.client.put("/api/v1/field/branding", json={"accent": "#123456"}, headers=GM)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.sync.status()["branding"]["source"], "local")

    def test_the_setting(self) -> None:
        with self.assertRaisesRegex(ConfigError, "sync.branding"):
            config(self.tmp.name, sync_branding="cloud")
        self.assertEqual(config(self.tmp.name, sync_branding="site").sync_branding, "site")
