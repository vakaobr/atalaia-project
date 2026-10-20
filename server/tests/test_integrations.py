# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Platform adapters (ADR-P4-12; plan phase 17, decisions F21, F22, S17-*).

The registry's rules for an adapter (a stated basis, known capabilities), the encrypted configuration
(sealed to its field and adapter), and on PostgreSQL 16 the per-field links (off by default, admin only,
secrets never shown again), publishing, updating and cancelling a game through the test adapter, a
platform's registrations through the import's rules, failures and time-outs that fail only their call,
and the audit log of every call. No adapter for a named platform exists (F22).
"""

from __future__ import annotations

import dataclasses
import json
import unittest
import uuid
from typing import Any

from atalaia_server import integrations
from atalaia_server.config import Settings
from atalaia_server.integrations.base import ImportedRegistration, ImportedReplica
from atalaia_server.tokens import Keys

from .test_registration_import import ImportCase


class RegistryTests(unittest.TestCase):
    def test_what_an_adapter_needs_to_be_offered(self) -> None:
        good = integrations.TestAdapter()
        registry = integrations.Registry([good])
        self.assertIs(registry.get("test"), good)
        self.assertEqual([a.id for a in registry.all()], ["test"])
        with self.assertRaisesRegex(ValueError, "twice"):
            registry.register(integrations.TestAdapter())
        for change, message in (({"basis": "  "}, "documented API or agreement"),
                                ({"capabilities": frozenset({"scrape"})}, "capabilities"),
                                ({"capabilities": frozenset()}, "capabilities"),
                                ({"id": "site"}, "not valid"), ({"id": "Bad Id"}, "not valid"),
                                ({"secret_keys": frozenset({"password"})}, "secret keys")):
            adapter = integrations.TestAdapter()
            for key, value in change.items():
                setattr(adapter, key, value)
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, message):
                integrations.Registry([adapter])
        with self.assertRaisesRegex(ValueError, "not a PlatformAdapter"):
            integrations.Registry([object()])  # type: ignore[list-item]

    def test_offered_only_when_asked(self) -> None:
        self.assertEqual(integrations.default_registry(False).all(), [])
        self.assertEqual([a.id for a in integrations.default_registry(True).all()], ["test"])

    def test_no_adapter_for_a_named_platform(self) -> None:
        # F22: no adapter without the platform's API documentation or an agreement (none for jogarairsoft.pt).
        from pathlib import Path
        names = {p.stem for p in Path(integrations.__file__).parent.glob("*.py")}
        self.assertEqual(names, {"__init__", "base", "testing"})

    def test_the_config_box(self) -> None:
        box = integrations.ConfigBox(Keys("k" * 40).platform_config)
        field, other = uuid.uuid4(), uuid.uuid4()
        sealed = box.seal(field, "test", {"account": "a", "token": "segredo"})
        self.assertNotIn(b"segredo", sealed)
        self.assertEqual(box.open(field, "test", sealed), {"account": "a", "token": "segredo"})
        self.assertIsNone(box.open(other, "test", sealed))   # copied to another field's row
        self.assertIsNone(box.open(field, "other", sealed))
        self.assertIsNone(integrations.ConfigBox(Keys("j" * 40).platform_config).open(field, "test", sealed))
        self.assertIsNone(box.open(field, "test", None))
        self.assertNotEqual(Keys("k" * 40).platform_config, Keys("k" * 40).totp_seed)


class IntegrationCase(ImportCase):
    def settings(self) -> Settings:
        return dataclasses.replace(super().settings(), test_adapter=True)

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.platform = self.app.state.adapters.get("test").platform

    def link_path(self, adapter: str = "test") -> str:
        return f"/api/v1/fields/{self.field_id}/integrations/{adapter}"

    def game_path(self, game: Any, what: str = "push", adapter: str = "test") -> str:
        return f"/api/v1/fields/{self.field_id}/scheduled-games/{game.id}/integrations/{adapter}/{what}"

    async def enable(self) -> None:
        r = await self.client.put(self.link_path(), json={"enabled": True,
                                                          "config": {"account": "campo", "token": "s3gredo"}},
                                  headers=self.admin)
        self.assertEqual(r.status_code, 200, r.text)

    async def calls(self) -> list[dict[str, Any]]:
        rows = await self.fetch("SELECT details FROM audit_log WHERE action = 'integration_call' ORDER BY id")
        return [json.loads(r["details"]) if isinstance(r["details"], str) else r["details"] for r in rows]


class LinkTests(IntegrationCase):
    async def test_off_by_default_admin_only_secrets_never_shown(self) -> None:
        adapters = (await self.client.get("/api/v1/integrations/adapters", headers=self.player)).json()
        self.assertEqual([(a["id"], a["secret_keys"]) for a in adapters], [("test", ["token"])])
        self.assertIn("decision S17-6", adapters[0]["basis"])
        self.assertEqual((await self.client.get(f"/api/v1/fields/{self.field_id}/integrations",
                                                headers=self.admin)).json(), [])
        gm = await self.staff("gm")
        for headers in (self.player, gm):
            r = await self.client.put(self.link_path(), json={"enabled": True}, headers=headers)
            self.assertEqual(r.status_code, 403)
        r = await self.client.put(self.link_path(), json={"enabled": True}, headers=self.admin)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "config_missing"))
        r = await self.client.put(self.link_path(), json={"config": {"account": "campo"}}, headers=self.admin)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "config_invalid"))
        r = await self.client.put(self.link_path("nope"), json={"enabled": False}, headers=self.admin)
        self.assertEqual((r.status_code, r.json()["detail"]), (404, "adapter_unknown"))
        r = await self.client.put(self.link_path(), json={"config": {"account": "campo", "token": "s3gredo"}},
                                  headers=self.admin)
        self.assertEqual(r.status_code, 200)
        link = r.json()
        self.assertEqual((link["enabled"], link["configured"], link["config"]),
                         (False, True, {"account": "campo", "token": "set"}))  # configured, still off
        await self.enable()
        listed = (await self.client.get(f"/api/v1/fields/{self.field_id}/integrations", headers=self.admin)).json()
        self.assertEqual(listed[0]["enabled"], True)
        stored = (await self.fetch("SELECT config_enc FROM platform_links"))[0][0]
        self.assertNotIn(b"s3gredo", bytes(stored))
        everything = json.dumps([dict(r) for r in await self.fetch("SELECT details FROM audit_log")], default=str)
        self.assertNotIn("s3gredo", everything + json.dumps(listed))
        r = await self.client.delete(self.link_path(), headers=self.admin)
        self.assertEqual(r.status_code, 204)
        self.assertEqual(await self.count("platform_links"), 0)

    async def test_a_server_without_the_test_adapter(self) -> None:
        self.app.state.adapters = integrations.default_registry(False)
        self.assertEqual((await self.client.get("/api/v1/integrations/adapters", headers=self.player)).json(), [])
        r = await self.client.put(self.link_path(), json={"enabled": False}, headers=self.admin)
        self.assertEqual(r.status_code, 404)


class CallTests(IntegrationCase):
    async def test_publish_update_cancel(self) -> None:
        game = await self.game()
        r = await self.client.post(self.game_path(game), headers=self.admin)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "integration_disabled"))
        await self.enable()
        draft = await self.game(status="draft")
        r = await self.client.post(self.game_path(draft), headers=self.admin)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "game_not_published"))
        gm = await self.staff("gm")
        self.assertEqual((await self.client.post(self.game_path(game), headers=gm)).status_code, 403)

        await self.register(game, display_name="Falcão")
        r = await self.client.post(self.game_path(game), headers=self.admin)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["operation"], r.json()["external_ref"], r.json()["last_error"]),
                         ("publish", "test-1", None))
        sent = self.platform.events["test-1"]["game"]
        self.assertEqual((sent.title, sent.places_left, sent.url),
                         ("Domingo no bosque", None, f"https://server.test/f/campo/games/{game.id}"))
        self.assertNotIn("Falcão", repr(sent))  # what an adapter is given holds no person
        self.assertNotIn("joana", repr(sent))
        r = await self.client.post(self.game_path(game), headers=self.admin)
        self.assertEqual(r.json()["operation"], "update")
        await self.fetch("UPDATE scheduled_games SET status = 'cancelled', cancelled_reason = 'Chuva' WHERE id = $1",
                         game.id)
        r = await self.client.post(self.game_path(game), headers=self.admin)
        self.assertEqual((r.json()["operation"], r.json()["cancelled"]), ("cancel", True))
        self.assertTrue(self.platform.events["test-1"]["cancelled"])
        r = await self.client.post(self.game_path(game), headers=self.admin)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "already_cancelled"))
        self.assertEqual([(c["operation"], c["result"]) for c in await self.calls()],
                         [("publish", "ok"), ("update", "ok"), ("cancel", "ok")])
        links = (await self.client.get(f"/api/v1/fields/{self.field_id}/scheduled-games/{game.id}/integrations",
                                       headers=gm)).json()
        self.assertEqual([(g["adapter_id"], g["external_ref"], g["cancelled"]) for g in links],
                         [("test", "test-1", True)])

    async def test_a_failing_or_slow_platform_fails_only_its_call(self) -> None:
        game = await self.game()
        await self.enable()
        self.platform.fail.add("publish")
        r = await self.client.post(self.game_path(game), headers=self.admin)
        self.assertEqual((r.status_code, r.json()["last_error"], r.json()["external_ref"]),
                         (502, "platform_unavailable", None))
        self.platform.fail.clear()
        self.platform.hang.add("publish")
        old = integrations.CALL_TIMEOUT_S
        integrations.CALL_TIMEOUT_S = 0.2
        try:
            r = await self.client.post(self.game_path(game), headers=self.admin)
        finally:
            integrations.CALL_TIMEOUT_S = old
        self.assertEqual((r.status_code, r.json()["last_error"]), (502, "timeout"))
        self.platform.hang.clear()
        # Scheduling, registering and the controller's roster never wait for the platform.
        self.platform.fail.update({"publish", "update", "cancel", "registrations"})
        await self.register(game)
        r = await self.client.patch(f"/api/v1/fields/{self.field_id}/scheduled-games/{game.id}",
                                    json={"title": "Outro"}, headers=self.admin)
        self.assertEqual(r.status_code, 200)
        await self.pull(f"/api/v1/sync/roster?scheduled_game_id={game.id}")
        self.platform.fail.clear()
        r = await self.client.post(self.game_path(game), headers=self.admin)
        self.assertEqual((r.status_code, r.json()["last_error"]), (200, None))
        self.assertEqual([c["result"] for c in await self.calls()], ["platform_unavailable", "timeout", "ok"])

    async def test_a_platforms_registrations_through_the_import(self) -> None:
        game = await self.game(federation="optional")
        await self.enable()
        r = await self.client.post(self.game_path(game, "registrations"), params={"dry_run": "true"},
                                   headers=self.admin)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "not_published_there"))
        await self.client.post(self.game_path(game), headers=self.admin)
        self.platform.registrations["test-1"] = [
            ImportedRegistration("Ana", "e-1", "red", "FPA-1", (ImportedReplica("aeg", "rifle", "M4"),)),
            ImportedRegistration("Bea", "e-2", "green"),
            ImportedRegistration("", "e-3"),
        ]
        preview = (await self.client.post(self.game_path(game, "registrations"), params={"dry_run": "true"},
                                          headers=self.admin)).json()
        self.assertEqual([(x["result"], x.get("code")) for x in preview["results"]],
                         [("created", None), ("refused", "team_preference_invalid"),
                          ("refused", "display_name_invalid")])
        self.assertEqual(await self.regs(game), [])
        r = await self.client.post(self.game_path(game, "registrations"), headers=self.admin)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "basis_not_confirmed"))
        gm = await self.staff("gm")
        out = (await self.client.post(self.game_path(game, "registrations"), params={"basis_confirmed": "true"},
                                      headers=gm)).json()
        self.assertEqual(out["counts"]["created"], 1)
        again = (await self.client.post(self.game_path(game, "registrations"), params={"basis_confirmed": "true"},
                                        headers=gm)).json()
        self.assertEqual(again["counts"]["unchanged"], 1)
        rows = await self.regs(game)
        self.assertEqual([(r["display_name"], r["source"], r["external_ref"], r["user_id"]) for r in rows],
                         [("Ana", "test", "e-1", None)])
        self.platform.fail.add("registrations")
        r = await self.client.post(self.game_path(game, "registrations"), params={"basis_confirmed": "true"},
                                   headers=gm)
        self.assertEqual((r.status_code, r.json()["detail"]), (502, "platform_unavailable"))
        self.assertEqual([(c["operation"], c["result"]) for c in await self.calls()],
                         [("publish", "ok"), ("registrations", "ok"), ("registrations", "ok"),
                          ("registrations", "ok"), ("registrations", "platform_unavailable")])
        imports = await self.fetch("SELECT count(*) FROM audit_log WHERE action = 'registration_import'")
        self.assertEqual(imports[0][0], 2)
