# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The field's scenario library from the site server on the controller (phase 4, plan phase 20).

With ``[sync] library = true`` (the default) the sync client pulls ``GET /api/v1/sync/presets``, fetches each
scenario whose manifest it has not installed from the site yet and installs it with ``scenario_service.install``
(compiled, its field.lua loaded in the core again: P4R9), then saves the field's presets once their modes are
here. Every controller of the field does it, so a standby has the scenario a join names (decision M8-3).
Against an in-memory site server whose answers pass ``sync_format.ANSWERS`` (the real one:
server/tests/test_scenarios_api.py).

    cd controller && python -m unittest discover -s tests
"""

from __future__ import annotations

import copy
import hashlib
import logging
import tempfile
import unittest
from typing import Any, Optional

from fastapi.testclient import TestClient

from support import CORE, FakeModem, config
from test_scenario_api import GM, JOIN_KEY, MANIFEST, OBJECTIVES, SCENARIO
from atalaia_controller import scenario_service, sync_format
from atalaia_controller.api import Auth, create_app
from atalaia_controller.engine import Controller
from atalaia_controller.store import Store
from atalaia_controller.sync_client import SyncClient, SyncError
from atalaia_controller.ws import Hub

logging.getLogger("atalaia.sync").setLevel(logging.CRITICAL)
DOMINATION = "org.atalaia.domination"


class FakeLibrary:
    """``GET /api/v1/sync/presets`` and ``/api/v1/sync/scenarios/{id}`` in memory (game day: nothing)."""

    def __init__(self) -> None:
        self.manifests: dict[str, tuple[int, str]] = {}  # scenario id -> (revision, text)
        self.presets: list[dict[str, Any]] = []
        self.gets: list[str] = []
        self.missing = False
        self.corrupt = False

    def put(self, text: str, scenario_id: str = SCENARIO) -> None:
        revision = self.manifests.get(scenario_id, (0, ""))[0] + 1
        self.manifests[scenario_id] = (revision, text)

    def preset(self, name: str, mode_id: str, params: Optional[dict[str, Any]] = None) -> None:
        self.presets.append({"preset_id": f"0192f3a4-0000-7000-8000-{len(self.presets) + 1:012d}", "name": name,
                             "mode_id": mode_id, "params": params or {}})

    @staticmethod
    def sha(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def get(self, path: str) -> dict[str, Any]:
        self.gets.append(path)
        if path == "/api/v1/sync/presets":
            if self.missing:
                raise SyncError("Not Found", 404)
            answer = {"sync_version": 1, "presets": copy.deepcopy(self.presets),
                      "scenarios": [{"scenario_id": sid, "revision": rev, "version": "1", "name": "Two",
                                     "sha256": self.sha(text)} for sid, (rev, text) in sorted(self.manifests.items())]}
            return sync_format.check_presets(answer)
        if path.startswith("/api/v1/sync/scenarios/"):
            sid = path.rsplit("/", 1)[1]
            if sid not in self.manifests:
                raise SyncError("scenario_not_found", 404)
            rev, text = self.manifests[sid]
            return {"sync_version": 1, "scenario_id": sid, "revision": rev,
                    "sha256": self.sha(text) if not self.corrupt else "0" * 64, "manifest": text}
        if path.startswith("/api/v1/sync/schedule"):
            return {"sync_version": 1, "games": []}
        return {"sync_version": 1, "claims": []}

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """The pushes of a game, acknowledged as the site server does (protocol/sync.md)."""
        if path.endswith("/events"):
            return {"acked_id": body["events"][-1]["id"], "inserted": len(body["events"]), "duplicates": 0}
        return {}

    def fetched(self) -> list[str]:
        return [p for p in self.gets if p.startswith("/api/v1/sync/scenarios/")]


class Node:
    """One field controller (the primary, or a standby) with its API and its sync client."""

    def __init__(self, case: unittest.TestCase, site: FakeLibrary, **cfg: Any) -> None:
        tmp = tempfile.TemporaryDirectory()
        case.addCleanup(tmp.cleanup)
        self.cfg = config(tmp.name, **cfg)
        self.store = Store(self.cfg.db_path)
        case.addCleanup(self.store.close)
        self.ctrl = Controller(self.cfg, self.store, modem=FakeModem(), core=CORE, join_key=JOIN_KEY)
        case.addCleanup(self.ctrl.stop)
        self.client = TestClient(create_app(self.ctrl, Hub(), Auth(self.cfg.gm_token, self.cfg.read_token)))
        case.addCleanup(self.client.close)
        self.sync = SyncClient(self.cfg, self.store, api_key="k" * 43, transport=site, controller=self.ctrl)
        self.ctrl.sync = self.sync

    def cycle(self) -> dict[str, Any]:
        assert self.sync.run_once(), self.sync.last_error
        return self.sync.status()["library"]

    def scenarios(self) -> dict[str, str]:
        return {s["id"]: s["version"] for s in scenario_service.listing(self.ctrl)}

    def presets(self) -> dict[str, dict[str, Any]]:
        return {p["name"]: p for p in self.store.presets()}


@unittest.skipIf(CORE is None, "the shared core library is not built")
class LibraryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.site = FakeLibrary()
        self.site.put(MANIFEST)
        self.site.preset("Domingo: dois objetivos", f"{SCENARIO}+{OBJECTIVES}")
        self.site.preset("Domínio rápido", DOMINATION, {"tick_s": 5})

    def test_every_controller_of_the_field_installs_the_library(self) -> None:
        primary, standby = Node(self, self.site), Node(self, self.site)
        for node in (primary, standby):
            status = node.cycle()
            self.assertEqual(node.scenarios(), {SCENARIO: "1"})
            self.assertEqual(node.presets()["Domínio rápido"]["params"], {"tick_s": 5})
            self.assertEqual(node.presets()["Domingo: dois objetivos"]["mode_id"], f"{SCENARIO}+{OBJECTIVES}")
            self.assertEqual((status["supported"], status["error"], status["scenarios_installed"]), (True, None, 1))
            self.assertEqual(status["from_site"]["scenarios"], [SCENARIO])
            # The manifest is kept beside the package, as an install from the console keeps it (M8-2).
            self.assertEqual(node.client.get(f"/api/v1/scenarios/{SCENARIO}", headers=GM).json()["manifest_text"],
                             MANIFEST)
        self.assertEqual(len(self.site.fetched()), 2)  # once per controller

    def test_a_standby_joins_a_scenario_game_with_nothing_carried_by_hand(self) -> None:
        """M8-3: the standby got the scenario from the site, so the primary's join text just works."""
        primary, standby = Node(self, self.site), Node(self, self.site)
        primary.cycle()
        r = primary.client.post("/api/v1/games", headers=GM, json={
            "name": "Two", "mode_id": SCENARIO, "modifiers": [OBJECTIVES], "teams": ["red", "blue"], "squads": 2})
        self.assertEqual(r.status_code, 201, r.text)
        text = primary.client.post("/api/v1/join", headers=GM, json={"kind": "controller"}).json()["text"]
        r = standby.client.post("/api/v1/controller/join", headers=GM, json={"text": text})
        self.assertEqual(r.status_code, 409)  # before its first sync, as before (M6-1)
        standby.cycle()
        r = standby.client.post("/api/v1/controller/join", headers=GM, json={"text": text})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()["mode_id"], f"{SCENARIO}+{OBJECTIVES}")

    def test_a_manifest_is_fetched_only_when_it_changes(self) -> None:
        node = Node(self, self.site)
        node.cycle()
        node.cycle()
        self.assertEqual(len(self.site.fetched()), 1)
        self.site.put(MANIFEST.replace("version: 1", "version: 2"))
        node.cycle()
        self.assertEqual((len(self.site.fetched()), node.scenarios()), (2, {SCENARIO: "2"}))
        # A local install of the same id is the GM's until the site changes it again.
        r = node.client.post("/api/v1/scenarios", headers=GM, json={"manifest": MANIFEST.replace("version: 1",
                                                                                                 "version: 7")})
        self.assertEqual(r.status_code, 201, r.text)
        node.cycle()
        self.assertEqual(node.scenarios(), {SCENARIO: "7"})

    def test_a_refused_manifest_is_not_fetched_again_until_it_changes(self) -> None:
        self.site.put(MANIFEST.replace("depends_on: [bridge]", "depends_on: [nowhere]"))
        node = Node(self, self.site)
        status = node.cycle()
        self.assertEqual(node.scenarios(), {})
        self.assertIn(f"{SCENARIO}: refused", status["error"])
        self.assertIn("mode org.test.two+org.atalaia.objectives", status["error"])  # its preset waits
        self.assertIn(SCENARIO, status["from_site"]["refused"])
        node.cycle()
        self.assertEqual(len(self.site.fetched()), 1)
        self.site.put(MANIFEST)
        status = node.cycle()
        self.assertEqual((node.scenarios(), status["error"], status["from_site"]["refused"]),
                         ({SCENARIO: "1"}, None, []))
        self.assertIn("Domingo: dois objetivos", node.presets())

    def test_the_live_game_keeps_its_scenario_until_it_ends(self) -> None:
        node = Node(self, self.site)
        node.cycle()
        r = node.client.post("/api/v1/games", headers=GM, json={
            "name": "Two", "mode_id": SCENARIO, "modifiers": [OBJECTIVES], "teams": ["red", "blue"], "squads": 2})
        gid = r.json()["id"]
        self.site.put(MANIFEST.replace("version: 1", "version: 2"))
        status = node.cycle()
        self.assertIn("end it before you replace the scenario", status["error"])
        self.assertEqual(node.scenarios(), {SCENARIO: "1"})
        self.assertNotIn(SCENARIO, status["from_site"]["refused"])  # tried again next cycle
        node.client.post(f"/api/v1/games/{gid}/start", headers=GM)
        self.assertEqual(node.client.post(f"/api/v1/games/{gid}/end", headers=GM).status_code, 200)
        node.cycle()
        self.assertEqual(node.scenarios(), {SCENARIO: "2"})

    def test_presets_need_their_mode_and_fitting_parameters(self) -> None:
        self.site.preset("Sem modo", "org.club.unknown")
        self.site.preset("Domínio errado", DOMINATION, {"tick_s": 0})
        node = Node(self, self.site)
        status = node.cycle()
        self.assertEqual(set(node.presets()), {"Domingo: dois objetivos", "Domínio rápido"})
        self.assertIn("preset Sem modo: mode org.club.unknown is not installed here", status["error"])
        self.assertIn("preset Domínio errado:", status["error"])
        # A site preset replaces a GM preset of the same name only when the site's changes.
        node.client.post("/api/v1/presets", headers=GM, json={"name": "Domínio rápido", "mode_id": DOMINATION,
                                                              "params": {"tick_s": 9}})
        node.cycle()
        self.assertEqual(node.presets()["Domínio rápido"]["params"], {"tick_s": 9})
        self.site.presets[1]["params"] = {"tick_s": 6}
        node.cycle()
        self.assertEqual(node.presets()["Domínio rápido"]["params"], {"tick_s": 6})

    def test_off_old_server_and_bad_answers(self) -> None:
        off = Node(self, self.site, sync_library=False)
        off.cycle()
        self.assertEqual((off.scenarios(), self.site.gets.count("/api/v1/sync/presets")), ({}, 0))
        self.assertFalse(off.sync.status()["library"]["enabled"])
        self.site.missing = True
        old = Node(self, self.site)
        self.assertFalse(old.cycle()["supported"])  # skipped quietly: the cycle still succeeds
        self.site.missing, self.site.corrupt = False, True
        bad = Node(self, self.site)
        self.assertFalse(bad.sync.run_once())
        self.assertEqual((bad.sync.last_error, bad.scenarios()), ("bad_answer", {}))


if __name__ == "__main__":
    unittest.main()
