# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The field's scenario library and game presets (plan phase 20; ADR-P4-6 as amended, P4R7, P4R9).

A manifest is checked with the controller's own compiler and validator and its compiled ``field.lua`` loaded
in the image's core (P4R9); each save is a revision; the field's controllers pull the library with
``GET /api/v1/sync/presets`` (checked with ``sync_format.ANSWERS``) and each manifest with
``GET /api/v1/sync/scenarios/{id}``. End to end: the real controller engine, a primary and a standby, pull the
same library from the site server under uvicorn and install it, so the standby has the scenario (M8-3).

    python3 tools/docker_server.py test tests.test_scenarios_api
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
import uuid
from typing import Any, Optional

from atalaia_controller import scenario_service, sync_format
from atalaia_controller.config import Config
from atalaia_controller.engine import Controller
from atalaia_controller.store import Store
from atalaia_controller.sync_client import SyncClient
from atalaia_server import sync
from atalaia_server.services import library

from .base import AppTestCase, TempDatabase
from .test_sync_e2e import CORE, REPO, SiteServer

SCENARIO = "org.test.two"
OBJECTIVES = "org.atalaia.objectives"
MANIFEST = """\
id: org.test.two
version: 1
name: Two objectives
lang: en
teams: [red, blue]
squads: 2
i18n: { pt: { name: Dois objetivos } }
nodes:
  bridge: { role: objective }
  vault: { role: objective }
objectives:
  - id: bridge
    name: Take the bridge
    i18n: { pt: { name: Tomar a ponte } }
    type: capture_and_hold
    target: bridge
    effect: { points: 50 }
  - id: vault
    name: Open the vault
    type: enter_code
    assignee: { team: red, squad: 1 }
    target: vault
    params: { code: "4711" }
    visibility: hidden
    depends_on: [bridge]
    effect: { points: 100 }
"""
BAD = MANIFEST.replace("depends_on: [bridge]", "depends_on: [nowhere]")


class LibraryCase(AppTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.field_id = await self.make_field("campo")
        self.key = sync.new_key()
        await self.fetch("INSERT INTO field_api_keys (field_id, key_sha256) VALUES ($1, $2)", self.field_id,
                         sync.key_hash(self.key))
        self.gm = await self.staff("gm")

    async def make_field(self, slug: str) -> uuid.UUID:
        return (await self.fetch("INSERT INTO fields (name, slug) VALUES ($1, $2) RETURNING id", slug.title(),
                                 slug))[0][0]

    async def staff(self, role: str, field_id: Optional[uuid.UUID] = None, totp: bool = True) -> dict[str, str]:
        user_id, name, secret = await self.make_user(with_totp=totp)
        await self.fetch("INSERT INTO user_field_roles (user_id, field_id, role_id) VALUES ($1, $2, $3)",
                         user_id, field_id or self.field_id, {"player": 1, "marshal": 4, "gm": 5, "admin": 7}[role])
        return await self.auth(name, secret=secret)

    def url(self, path: str = "", field: Optional[uuid.UUID] = None) -> str:
        return f"/api/v1/fields/{field or self.field_id}{path}"

    async def save(self, text: str, expect: int = 201, headers: Optional[dict[str, str]] = None) -> Any:
        r = await self.client.post(self.url("/scenarios"), json={"manifest": text}, headers=headers or self.gm)
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    async def pull(self, path: str, key: Optional[str] = None, expect: int = 200) -> Any:
        r = await self.client.get(f"/api/v1/sync/{path}", headers={"Authorization": f"Bearer {key or self.key}"})
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()


class CheckTests(LibraryCase):
    async def test_check_lists_every_problem(self) -> None:
        r = await self.client.post(self.url("/scenarios/check"), json={"manifest": MANIFEST}, headers=self.gm)
        out = r.json()
        self.assertEqual((out["ok"], out["problems"], out["scenario_id"], out["checked_in_core"],
                          out["saved_revision"]), (True, [], SCENARIO, True, None))
        self.assertEqual([n["name"] for n in out["nodes"]], ["bridge", "vault"])
        out = (await self.client.post(self.url("/scenarios/check"), json={"manifest": BAD}, headers=self.gm)).json()
        self.assertFalse(out["ok"])
        self.assertIn("objectives[1].depends_on[0]", [p["path"] for p in out["problems"]])
        out = (await self.client.post(self.url("/scenarios/check"), json={"manifest": "- not a map"},
                                      headers=self.gm)).json()
        self.assertEqual([p["code"] for p in out["problems"]], ["bad_manifest"])
        self.assertEqual(await self.count(), 0)  # a check stores nothing

    async def test_without_the_core_a_manifest_is_checked_but_not_saved(self) -> None:
        self.app.state.core_holder = library.CoreHolder(tried=True, error="not built")
        out = (await self.client.post(self.url("/scenarios/check"), json={"manifest": MANIFEST},
                                      headers=self.gm)).json()
        self.assertEqual((out["ok"], out["checked_in_core"], out["problems"]), (False, False, []))
        self.assertEqual((await self.save(MANIFEST, expect=503))["detail"], "core_unavailable")

    async def count(self) -> int:
        return (await self.fetch("SELECT count(*) FROM field_scenarios"))[0][0]


class LibraryTests(LibraryCase):
    async def test_save_revise_read_and_archive(self) -> None:
        first = await self.save(MANIFEST)
        self.assertEqual((first["scenario_id"], first["revision"], first["version"], first["outcome"]),
                         (SCENARIO, 1, "1", "created"))
        self.assertEqual((await self.save(MANIFEST, expect=200))["outcome"], "unchanged")
        second = await self.save(MANIFEST.replace("version: 1", "version: 2"), expect=200)
        self.assertEqual((second["revision"], second["version"], second["outcome"]), (2, "2", "revised"))
        refused = await self.save(BAD, expect=400)
        self.assertEqual(refused["detail"], "scenario_refused")
        self.assertIn("objectives[1].depends_on[0]", [p["path"] for p in refused["problems"]])

        listing = (await self.client.get(self.url("/scenarios"), headers=self.gm)).json()
        self.assertEqual([(s["scenario_id"], s["revision"], s["archived"]) for s in listing], [(SCENARIO, 2, False)])
        detail = (await self.client.get(self.url(f"/scenarios/{SCENARIO}"), headers=self.gm)).json()
        self.assertEqual(detail["manifest"], MANIFEST.replace("version: 1", "version: 2"))
        self.assertEqual(set(detail["files"]), {"mode.yaml", "field.lua"})
        self.assertIn('"4711"', detail["files"]["field.lua"])
        self.assertEqual([r["revision"] for r in detail["revisions"]], [2, 1])
        old = (await self.client.get(self.url(f"/scenarios/{SCENARIO}/revisions/1"), headers=self.gm)).json()
        self.assertEqual(old["manifest"], MANIFEST)
        r = await self.client.get(self.url(f"/scenarios/{SCENARIO}/revisions/9"), headers=self.gm)
        self.assertEqual(r.status_code, 404)

        r = await self.client.delete(self.url(f"/scenarios/{SCENARIO}"), headers=self.gm)
        self.assertEqual(r.status_code, 204)
        self.assertEqual((await self.client.get(self.url("/scenarios"), headers=self.gm)).json(), [])
        archived = (await self.client.get(self.url("/scenarios?archived=true"), headers=self.gm)).json()
        self.assertEqual([s["archived"] for s in archived], [True])
        self.assertEqual((await self.pull("presets"))["scenarios"], [])
        await self.pull(f"scenarios/{SCENARIO}", expect=404)
        restored = await self.save(MANIFEST, expect=200)
        self.assertEqual((restored["revision"], restored["outcome"]), (3, "restored"))

        actions = [r["action"] for r in await self.fetch("SELECT action, details FROM audit_log "
                                                         "WHERE action LIKE 'scenario_%' ORDER BY id")]
        self.assertEqual(actions, ["scenario_created", "scenario_revised", "scenario_archived", "scenario_restored"])
        details = await self.fetch("SELECT details FROM audit_log WHERE action LIKE 'scenario_%'")
        self.assertNotIn("4711", json.dumps([d["details"] for d in details]))  # never the manifest

    async def test_who_may_use_the_library(self) -> None:
        await self.save(MANIFEST)
        other = await self.make_field("arena")
        admin = await self.staff("admin")
        self.assertEqual((await self.client.get(self.url("/scenarios"), headers=admin)).status_code, 200)
        for headers, why in ((await self.staff("marshal"), "marshal"),
                             (await self.staff("player", totp=False), "player"),
                             (await self.staff("gm", other), "another field's gm")):
            with self.subTest(who=why):
                for method, path in (("GET", "/scenarios"), ("GET", f"/scenarios/{SCENARIO}"),
                                     ("POST", "/scenarios/check"), ("POST", "/scenarios"), ("GET", "/presets")):
                    r = await self.client.request(method, self.url(path), headers=headers,
                                                  json={"manifest": MANIFEST} if method == "POST" else None)
                    self.assertEqual(r.status_code, 403, (method, path))
        # A gm without the TOTP step in this session does not count as one.
        await self.fetch("UPDATE sessions SET mfa = false")
        r = await self.client.get(self.url("/scenarios"), headers=self.gm)
        self.assertEqual(r.status_code, 403)
        self.assertEqual((await self.client.get(self.url(f"/scenarios/{SCENARIO}", other),
                                                headers=await self.staff("gm", other))).status_code, 404)

    async def test_the_sync_answers(self) -> None:
        await self.save(MANIFEST)
        other_field = await self.make_field("arena")
        other_key = sync.new_key()
        await self.fetch("INSERT INTO field_api_keys (field_id, key_sha256) VALUES ($1, $2)", other_field,
                         sync.key_hash(other_key))
        r = await self.client.post(self.url("/presets"), headers=self.gm,
                                   json={"name": "Domingo", "mode_id": f"{SCENARIO}+{OBJECTIVES}", "params": {}})
        self.assertEqual(r.status_code, 201, r.text)
        answer = await self.pull("presets")
        sync_format.check_presets(json.loads(json.dumps(answer)))  # the controller's own check
        self.assertEqual([(s["scenario_id"], s["revision"], s["sha256"]) for s in answer["scenarios"]],
                         [(SCENARIO, 1, library.manifest_sha256(MANIFEST))])
        self.assertEqual([p["name"] for p in answer["presets"]], ["Domingo"])
        one = await self.pull(f"scenarios/{SCENARIO}")
        sync_format.check_scenario(dict(one))
        self.assertEqual(one["manifest"], MANIFEST)
        # Another field's controllers see none of it.
        self.assertEqual(await self.pull("presets", other_key), {"sync_version": 1, "scenarios": [], "presets": []})
        await self.pull(f"scenarios/{SCENARIO}", other_key, expect=404)
        r = await self.client.get("/api/v1/sync/presets")
        self.assertEqual(r.status_code, 401)


class PresetTests(LibraryCase):
    async def test_presets(self) -> None:
        r = await self.client.post(self.url("/presets"), headers=self.gm, json={
            "name": "Bomba curta", "mode_id": "org.atalaia.bomb", "params": {"fuse_s": 45}})
        self.assertEqual(r.status_code, 201, r.text)
        preset = r.json()
        r = await self.client.post(self.url("/presets"), headers=self.gm, json={
            "name": "Bomba curta", "mode_id": "org.atalaia.bomb"})
        self.assertEqual(r.status_code, 409)
        for body, detail in (({"name": " x", "mode_id": "org.atalaia.bomb"}, "invalid_name"),
                             ({"name": "x", "mode_id": "Org.Bomb"}, "invalid_mode_id"),
                             ({"name": "x", "mode_id": "org.atalaia.bomb", "params": [1]}, "invalid_params"),
                             ({"name": "x", "mode_id": "org.atalaia.bomb", "colour": "red"}, "unknown_field")):
            with self.subTest(detail=detail):
                r = await self.client.post(self.url("/presets"), headers=self.gm, json=body)
                self.assertEqual((r.status_code, r.json()["detail"]), (400, detail))
        r = await self.client.put(self.url(f"/presets/{preset['id']}"), headers=self.gm, json={
            "name": "Bomba longa", "mode_id": "org.atalaia.bomb", "params": {"fuse_s": 90}})
        self.assertEqual((r.status_code, r.json()["params"]), (200, {"fuse_s": 90}))
        listing = (await self.client.get(self.url("/presets"), headers=self.gm)).json()
        self.assertEqual([p["name"] for p in listing], ["Bomba longa"])
        self.assertEqual((await self.client.delete(self.url(f"/presets/{preset['id']}"),
                                                   headers=self.gm)).status_code, 204)
        self.assertEqual((await self.client.delete(self.url(f"/presets/{preset['id']}"),
                                                   headers=self.gm)).status_code, 404)
        actions = [r["action"] for r in await self.fetch("SELECT action FROM audit_log WHERE action LIKE 'preset_%' "
                                                         "ORDER BY id")]
        self.assertEqual(actions, ["preset_create", "preset_update", "preset_delete"])


class LibraryEndToEndTests(unittest.TestCase):
    """The real controller: a primary and a standby pull the field's library from the real site server."""

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
        self.field = self.db.fetch("INSERT INTO fields (name, slug) VALUES ('Campo', 'campo') RETURNING id")[0][0]
        self.key = sync.new_key()
        self.db.fetch("INSERT INTO field_api_keys (field_id, key_sha256) VALUES ($1, $2)", self.field,
                      sync.key_hash(self.key))

    def tearDown(self) -> None:
        self.site.__exit__(None, None, None)
        self.db.fetch("TRUNCATE fields RESTART IDENTITY CASCADE")
        self.tmp.cleanup()

    def controller(self, name: str) -> tuple[Controller, SyncClient]:
        cfg = Config(db_path=os.path.join(self.tmp.name, f"{name}.db"), mqtt_enabled=False,
                     modes_dirs=[str(REPO / "modes")], sync_enabled=True, sync_url=self.site.url,
                     sync_api_key=self.key, sync_timeout_s=5.0)
        cfg.validate()
        store = Store(cfg.db_path)
        self.addCleanup(store.close)
        ctrl = Controller(cfg, store, core=CORE)
        self.addCleanup(ctrl.stop)
        return ctrl, SyncClient(cfg, store, controller=ctrl)

    def store_scenario(self, text: str) -> None:
        """What POST .../scenarios stores, written straight to the database (the API is tested above)."""
        sid = self.db.fetch("INSERT INTO field_scenarios (field_id, scenario_id, revision) VALUES ($1, $2, 1) "
                            "ON CONFLICT (field_id, scenario_id) DO UPDATE SET revision = field_scenarios.revision + 1 "
                            "RETURNING id, revision", self.field, SCENARIO)[0]
        self.db.fetch("INSERT INTO field_scenario_revisions (scenario, revision, version, name, manifest, "
                      "manifest_sha256) VALUES ($1, $2, '1', 'Two', $3, $4)", sid[0], sid[1], text,
                      library.manifest_sha256(text))

    def test_the_primary_and_the_standby_install_the_same_library(self) -> None:
        self.store_scenario(MANIFEST)
        self.db.fetch("INSERT INTO field_presets (field_id, name, mode_id, params) VALUES ($1, 'Domingo', $2, '{}'), "
                      "($1, 'Domínio rápido', 'org.atalaia.domination', '{\"tick_s\": 5}')", self.field,
                      f"{SCENARIO}+{OBJECTIVES}")
        nodes = [self.controller("primary"), self.controller("standby")]
        for ctrl, client in nodes:
            self.assertTrue(client.run_once(), client.last_error)
            self.assertEqual([s["id"] for s in scenario_service.listing(ctrl)], [SCENARIO])
            self.assertIsNotNone(ctrl.modes.get(f"{SCENARIO}+{OBJECTIVES}"))  # what a join for it needs
            presets = {p["name"]: p for p in ctrl.store.presets()}
            self.assertEqual((presets["Domingo"]["mode_id"], presets["Domínio rápido"]["params"]),
                             (f"{SCENARIO}+{OBJECTIVES}", {"tick_s": 5}))
            self.assertIsNone(client.status()["library"]["error"])
        # A new revision reaches both; nothing else is fetched again.
        self.store_scenario(MANIFEST.replace("version: 1", "version: 2"))
        for ctrl, client in nodes:
            self.assertTrue(client.run_once(), client.last_error)
            self.assertEqual([s["version"] for s in scenario_service.listing(ctrl)], ["2"])
            self.assertEqual(client.status()["library"]["scenarios_installed"], 2)

    def test_a_scenario_archived_and_a_preset_deleted_on_the_site_go_from_the_controllers(self) -> None:
        """Decision S20-8: the site's answer no longer lists them, so the next sync removes them."""
        self.store_scenario(MANIFEST)
        self.db.fetch("INSERT INTO field_presets (field_id, name, mode_id, params) VALUES ($1, 'Domingo', $2, '{}'), "
                      "($1, 'Domínio rápido', 'org.atalaia.domination', '{}')", self.field, f"{SCENARIO}+{OBJECTIVES}")
        ctrl, client = self.controller("primary")
        self.assertTrue(client.run_once(), client.last_error)
        ctrl.store.save_preset("Do GM", "org.atalaia.domination", {})
        self.db.fetch("UPDATE field_scenarios SET archived_at = now() WHERE field_id = $1", self.field)
        self.db.fetch("DELETE FROM field_presets WHERE name = 'Domingo'")
        self.assertTrue(client.run_once(), client.last_error)
        self.assertEqual(scenario_service.listing(ctrl), [])
        self.assertEqual(sorted(p["name"] for p in ctrl.store.presets()), ["Do GM", "Domínio rápido"])
        library_status = client.status()["library"]
        self.assertEqual((library_status["scenarios_removed"], library_status["presets_removed"]), (1, 1))
        # Restored on the site (saved again): the controller installs it again.
        self.db.fetch("UPDATE field_scenarios SET archived_at = NULL WHERE field_id = $1", self.field)
        self.assertTrue(client.run_once(), client.last_error)
        self.assertEqual([s["id"] for s in scenario_service.listing(ctrl)], [SCENARIO])


if __name__ == "__main__":
    unittest.main()
