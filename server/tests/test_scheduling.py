# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Scheduled games on PostgreSQL 16 (ADR-P4-11, plan phase 15, decisions F13, S15-*).

Who may schedule, publish, cancel and delete; the checks on times, windows and texts; the
iCalendar ``SEQUENCE`` raised by the changes that matter to calendars; the field page's
settings; and the personal data hooks (access, export, erasure, the purge).
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from atalaia_server import personal_data, sync
from atalaia_server.models import ScheduledGame

from .base import PASSWORD, AppTestCase
from .test_remote_gm import Stream

UTC = timezone.utc


def iso(value: datetime) -> str:
    return value.isoformat()


def soon(days: float = 10, hours: float = 0) -> datetime:
    base = datetime.now(UTC).replace(microsecond=0, second=0, minute=0) + timedelta(days=days, hours=hours)
    return base


class ScheduleCase(AppTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.field_id = await self.make_field("campo-tejo", "Campo Tejo")
        self.admin_id, self.admin = await self.staff("admin")
        self.gm_id, self.gm = await self.staff("gm")

    async def make_field(self, slug: str, name: str) -> uuid.UUID:
        return (await self.fetch("INSERT INTO fields (name, slug) VALUES ($1, $2) RETURNING id", name, slug))[0][0]

    async def staff(self, role: str, field_id: Optional[uuid.UUID] = None) -> tuple[uuid.UUID, dict[str, str]]:
        """An account with TOTP holding ``role`` on the field, and the headers of a TOTP session."""
        role_id = {"player": 1, "marshal": 4, "gm": 5, "admin": 7}[role]
        user_id, name, secret = await self.make_user(with_totp=role != "player")
        await self.fetch("INSERT INTO user_field_roles (user_id, field_id, role_id) VALUES ($1, $2, $3)",
                         user_id, field_id or self.field_id, role_id)
        return user_id, await self.auth(name, secret=secret)

    def body(self, **over: Any) -> dict[str, Any]:
        start = soon()
        body: dict[str, Any] = {
            "title": "Domingo no bosque", "description": "Jogo de domínio.\nTraz água.",
            "starts_at": iso(start), "ends_at": iso(start + timedelta(hours=4)), "mode_id": "org.atalaia.domination",
            "teams": ["red", "blue"], "max_players": 60, "registration_opens_at": iso(start - timedelta(days=7)),
            "registration_closes_at": iso(start - timedelta(hours=12)), "federation": "optional"}
        body.update(over)
        return body

    def url(self, game: Optional[str] = None, action: str = "", field: Optional[uuid.UUID] = None) -> str:
        out = f"/api/v1/fields/{field or self.field_id}/scheduled-games"
        if game:
            out += f"/{game}"
        if action:
            out += f"/{action}"
        return out

    async def create(self, headers: Optional[dict[str, str]] = None, expect: int = 201, **over: Any) -> dict[str, Any]:
        r = await self.client.post(self.url(), json=self.body(**over), headers=headers or self.gm)
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    async def publish(self, game: str, headers: Optional[dict[str, str]] = None, expect: int = 200) -> dict[str, Any]:
        r = await self.client.post(self.url(game, "publish"), headers=headers or self.admin)
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    async def patch(self, game: str, expect: int = 200, headers: Optional[dict[str, str]] = None,
                    **body: Any) -> dict[str, Any]:
        r = await self.client.patch(self.url(game), json=body, headers=headers or self.gm)
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    async def audit(self, action: str) -> list[Any]:
        return await self.fetch("SELECT user_id, resource_id, details FROM audit_log WHERE action = $1 ORDER BY id",
                                action)


class CreateTests(ScheduleCase):
    async def test_a_draft(self) -> None:
        start = soon().astimezone(timezone(timedelta(hours=1)))  # sent with an offset, kept in UTC
        game = await self.create(starts_at=iso(start), ends_at=iso(start + timedelta(hours=4)))
        self.assertEqual(game["status"], "draft")
        self.assertEqual(datetime.fromisoformat(game["starts_at"]), start)
        self.assertTrue(game["starts_at"].endswith("+00:00"))
        self.assertEqual((game["title"], game["teams"], game["max_players"], game["places_left"]),
                         ("Domingo no bosque", ["red", "blue"], 60, 60))
        self.assertEqual((game["ical_sequence"], game["created_by"], game["registration_state"]),
                         (0, str(self.gm_id), "closed"))  # a draft takes no registration
        self.assertTrue(game["predeclare_replicas"])
        rows = await self.audit("schedule_create")
        self.assertEqual([(r["user_id"], str(r["resource_id"])) for r in rows], [(self.gm_id, game["id"])])

    async def test_refusals(self) -> None:
        start = soon()
        cases = [
            ({"starts_at": "2026-11-08T09:00:00"}, "starts_at_needs_offset"),
            ({"ends_at": iso(start - timedelta(hours=1))}, "times_invalid"),
            ({"ends_at": iso(start + timedelta(days=15))}, "times_invalid"),
            ({"registration_closes_at": iso(start + timedelta(hours=1))}, "registration_window_invalid"),
            ({"registration_opens_at": iso(start - timedelta(hours=6)),
              "registration_closes_at": iso(start - timedelta(hours=12))}, "registration_window_invalid"),
            ({"federation": "sometimes"}, "federation_invalid"),
            ({"title": "   "}, "title_invalid"),
            ({"title": "Jogo\nduas linhas"}, "title_invalid"),
            ({"title": "x" * 257}, "title_invalid"),
            ({"teams": ["red", "red"]}, "teams_invalid"),
            ({"teams": [f"t{i}" for i in range(17)]}, "teams_invalid"),
            ({"max_players": 0}, "max_players_invalid"),
            ({"mode_id": "Not A Mode!"}, "mode_id_invalid"),
            ({"description": "bell\x07"}, "description_invalid"),
        ]
        for over, code in cases:
            with self.subTest(code=code, over=over):
                body = self.body(starts_at=iso(start), ends_at=iso(start + timedelta(hours=4)))
                body.update(over)
                r = await self.client.post(self.url(), json=body, headers=self.gm)
                self.assertEqual((r.status_code, r.json().get("detail")), (400, code), r.text)
        r = await self.client.post(self.url(), json={**self.body(), "secret": 1}, headers=self.gm)
        self.assertEqual(r.status_code, 422)
        self.assertEqual(await self.fetch("SELECT id FROM scheduled_games"), [])

    async def test_who_may(self) -> None:
        _, player = await self.staff("player")
        other_field = await self.make_field("arena", "Arena")
        _, other_admin = await self.staff("admin", other_field)
        _, marshal = await self.staff("marshal")
        for headers, expect in ((player, 403), (other_admin, 403), (marshal, 403), ({}, 401)):
            with self.subTest(expect=expect):
                r = await self.client.post(self.url(), json=self.body(), headers=headers)
                self.assertEqual(r.status_code, expect, r.text)
                r = await self.client.get(self.url(), headers=headers)
                self.assertEqual(r.status_code, expect, r.text)
        await self.create(headers=self.admin)
        r = await self.client.post(self.url(field=uuid.uuid4()), json=self.body(), headers=self.admin)
        self.assertEqual(r.status_code, 403)  # no role on a field that does not exist either

    async def test_admin_and_gm_roles_count_only_with_totp(self) -> None:
        # A gm role on an account logged in without the TOTP step (TOTP turned off by hand) counts for nothing.
        user_id, name, _ = await self.make_user()
        await self.fetch("INSERT INTO user_field_roles (user_id, field_id, role_id) VALUES ($1, $2, 5)",
                         user_id, self.field_id)
        r = await self.client.post(self.url(), json=self.body(), headers=await self.auth(name))
        self.assertEqual(r.status_code, 403)


class LifecycleTests(ScheduleCase):
    async def test_publish_edit_cancel(self) -> None:
        game = await self.create()
        gid = game["id"]
        r = await self.client.post(self.url(gid, "publish"), headers=self.gm)
        self.assertEqual(r.status_code, 403)  # only the admin publishes (F13)
        draft_edit = await self.patch(gid, starts_at=iso(soon(11)), ends_at=iso(soon(11, 4)))
        self.assertEqual(draft_edit["ical_sequence"], 0)  # nobody has a draft in a calendar
        published = await self.publish(gid)
        self.assertEqual((published["status"], published["ical_sequence"]), ("published", 0))
        self.assertIsNotNone(published["published_at"])
        await self.publish(gid, expect=409)
        # A new title is no news for a calendar's SEQUENCE; time and place are.
        self.assertEqual((await self.patch(gid, title="Domingo no pinhal"))["ical_sequence"], 0)
        self.assertEqual((await self.patch(gid, ends_at=iso(soon(11, 5))))["ical_sequence"], 1)
        self.assertEqual((await self.patch(gid, location_text="Portão norte"))["ical_sequence"], 2)
        same = await self.patch(gid, location_text="Portão norte")
        self.assertEqual(same["ical_sequence"], 2)  # nothing changed
        cleared = await self.patch(gid, description=None, mode_id=None)
        self.assertEqual((cleared["description"], cleared["mode_id"]), (None, None))
        await self.patch(gid, expect=400, title=None)
        r = await self.client.request("DELETE", self.url(gid), headers=self.admin)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "not_a_draft"))
        r = await self.client.post(self.url(gid, "cancel"), json={"reason": "Chuva"}, headers=self.gm)
        self.assertEqual(r.status_code, 403)
        r = await self.client.post(self.url(gid, "cancel"), json={"reason": "  "}, headers=self.admin)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "reason_invalid"))
        r = await self.client.post(self.url(gid, "cancel"), json={"reason": "Chuva forte"}, headers=self.admin)
        self.assertEqual(r.status_code, 200, r.text)
        cancelled = r.json()
        self.assertEqual((cancelled["status"], cancelled["cancelled_reason"], cancelled["ical_sequence"]),
                         ("cancelled", "Chuva forte", 3))
        r = await self.client.post(self.url(gid, "cancel"), json={"reason": "again"}, headers=self.admin)
        self.assertEqual(r.status_code, 409)
        await self.patch(gid, expect=409, title="Back on")
        actions = [r["action"] for r in await self.fetch(
            "SELECT action FROM audit_log WHERE resource = 'scheduled_game' ORDER BY id")]
        self.assertEqual(actions, ["schedule_create", "schedule_update", "schedule_publish", "schedule_update",
                                   "schedule_update", "schedule_update", "schedule_update", "schedule_cancel"])
        changed = [r["details"] for r in await self.audit("schedule_update")]
        self.assertEqual(json.loads(changed[1])["changed"], ["title"])

    async def test_a_draft_can_be_deleted(self) -> None:
        game = await self.create()
        _, player = await self.staff("player")
        r = await self.client.request("DELETE", self.url(game["id"]), headers=player)
        self.assertEqual(r.status_code, 403)
        r = await self.client.request("DELETE", self.url(game["id"]), headers=self.gm)
        self.assertEqual(r.status_code, 204)
        r = await self.client.get(self.url(game["id"]), headers=self.gm)
        self.assertEqual(r.status_code, 404)
        self.assertEqual(len(await self.audit("schedule_delete")), 1)

    async def test_a_past_game_is_not_published(self) -> None:
        async with self.app.state.sessionmaker() as db:
            past = ScheduledGame(field_id=self.field_id, title="Ontem", starts_at=soon(-2), ends_at=soon(-2, 3))
            db.add(past)
            await db.commit()
            gid = str(past.id)
        r = await self.client.post(self.url(gid, "publish"), headers=self.admin)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "game_in_the_past"))

    async def test_an_edit_must_keep_the_rules(self) -> None:
        game = await self.create()
        start = datetime.fromisoformat(game["starts_at"])
        r = await self.client.patch(self.url(game["id"]), json={"ends_at": iso(start - timedelta(hours=1))},
                                    headers=self.gm)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "times_invalid"))
        unchanged = (await self.client.get(self.url(game["id"]), headers=self.gm)).json()
        self.assertEqual(unchanged["ends_at"], game["ends_at"])

    async def test_another_fields_game_is_not_found(self) -> None:
        game = await self.create()
        other_field = await self.make_field("arena", "Arena")
        _, other_admin = await self.staff("admin", other_field)
        r = await self.client.get(self.url(game["id"], field=other_field), headers=other_admin)
        self.assertEqual(r.status_code, 404)
        r = await self.client.post(self.url(game["id"], "publish", field=other_field), headers=other_admin)
        self.assertEqual(r.status_code, 404)

    async def test_list(self) -> None:
        first = await self.create(title="Primeiro")
        second = await self.create(title="Segundo", starts_at=iso(soon(20)), ends_at=iso(soon(20, 4)))
        await self.publish(second["id"])
        r = await self.client.get(self.url(), headers=self.gm)
        self.assertEqual([g["title"] for g in r.json()], ["Primeiro", "Segundo"])
        self.assertEqual(r.headers["cache-control"], "no-store")
        r = await self.client.get(self.url(), params={"status": "draft"}, headers=self.gm)
        self.assertEqual([g["id"] for g in r.json()], [first["id"]])
        r = await self.client.get(self.url(), params={"from": iso(soon(15))}, headers=self.gm)
        self.assertEqual([g["id"] for g in r.json()], [second["id"]])
        r = await self.client.get(self.url(), params={"status": "registering"}, headers=self.gm)
        self.assertEqual(r.status_code, 400)  # computed, never stored


class FieldPageSettingsTests(ScheduleCase):
    async def test_the_field_page_settings(self) -> None:
        url = f"/api/v1/fields/{self.field_id}"
        r = await self.client.patch(url, json={"public_page": True}, headers=self.gm)
        self.assertEqual(r.status_code, 403)  # only the admin
        r = await self.client.patch(url, json={"public_page": True, "description": "Mata de pinheiros.\n\n12 ha.",
                                               "address_text": "Estrada da Mata, Lisboa", "federation_label": "FPA"},
                                    headers=self.admin)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual((body["public_page"], body["address_text"], body["federation_label"]),
                         (True, "Estrada da Mata, Lisboa", "FPA"))
        details = json.loads((await self.audit("field_update"))[0]["details"])
        self.assertEqual(details, {"public_page": True, "description": "set", "address_text": "set",
                                   "federation_label": "set"})
        r = await self.client.patch(url, json={"federation_label": "x" * 17}, headers=self.admin)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "federation_label_invalid"))
        r = await self.client.patch(url, json={"address_text": "a\nb"}, headers=self.admin)
        self.assertEqual(r.status_code, 400)
        r = await self.client.patch(url, json={"federation_label": None, "description": ""}, headers=self.admin)
        self.assertEqual((r.json()["federation_label"], r.json()["description"]), (None, None))

    async def test_a_new_address_changes_the_games_that_show_it(self) -> None:
        shows = await self.create(title="Sem local próprio")
        own = await self.create(title="Com local próprio", location_text="Portão norte")
        draft = await self.create(title="Rascunho")
        for game in (shows, own):
            await self.publish(game["id"])
        r = await self.client.patch(f"/api/v1/fields/{self.field_id}", json={"address_text": "Nova estrada"},
                                    headers=self.admin)
        self.assertEqual(r.status_code, 200, r.text)
        rows = {r["title"]: r["ical_sequence"] for r in await self.fetch("SELECT title, ical_sequence "
                                                                           "FROM scheduled_games")}
        self.assertEqual(rows, {shows["title"]: 1, own["title"]: 0, draft["title"]: 0})


class ScheduleDataTests(ScheduleCase):
    """The schedule's personal data: who scheduled a game (``created_by``)."""

    async def test_access_export_erasure(self) -> None:
        game = await self.create()
        r = await self.client.get("/api/v1/me/data", headers=self.gm)
        mine = r.json()["scheduled_games"]
        self.assertEqual([(g["id"], g["field"], g["title"], g["status"]) for g in mine],
                         [(game["id"], "Campo Tejo", "Domingo no bosque", "draft")])
        r = await self.client.get("/api/v1/me/export", headers=self.gm)
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            self.assertEqual(json.loads(zf.read("export/scheduled_games.json")), mine)
            self.assertIn("scheduled_games.json", zf.read("export/README.txt").decode())
        self.assertEqual((await self.client.get("/api/v1/me/data", headers=self.admin)).json()["scheduled_games"], [])
        # Erasure: the game stays the field's, without the link to the account.
        totp_secret = (await self.fetch("SELECT totp_secret_enc FROM users WHERE id = $1", self.gm_id))[0][0]
        code = self.code(self.app.state.seed_box.open(totp_secret))
        r = await self.client.request("DELETE", "/api/v1/me", json={"password": PASSWORD, "code": code},
                                      headers=self.gm)
        self.assertEqual(r.status_code, 204, r.text)
        rows = await self.fetch("SELECT id, created_by FROM scheduled_games")
        self.assertEqual([(str(r["id"]), r["created_by"]) for r in rows], [(game["id"], None)])

    async def test_the_purge(self) -> None:
        now = datetime.now(UTC)
        async with self.app.state.sessionmaker() as db:
            for title, end in (("old", now - timedelta(days=91)), ("recent", now - timedelta(days=89))):
                db.add(ScheduledGame(field_id=self.field_id, title=title, starts_at=end - timedelta(hours=4),
                                     ends_at=end, status="published", created_by=self.gm_id))
            await db.commit()
        async with self.app.state.sessionmaker() as db:
            counts = await personal_data.purge(db, now)
        self.assertEqual(counts["scheduled_games"], 1)
        self.assertEqual([r[0] for r in await self.fetch("SELECT title FROM scheduled_games")], ["recent"])

    async def test_metrics_count_the_schedule(self) -> None:
        await self.create()
        r = await self.client.get("/api/v1/metrics", headers={"Authorization": f"Bearer {self.metrics_token}"})
        body = r.json()
        self.assertEqual((body["scheduled_games_total"], body["public_fields_total"]), (1, 0))


class NoteTests(ScheduleCase):
    async def test_a_schedule_change_reaches_the_controllers_on_the_stream(self) -> None:
        """PKD-1: creating, changing, publishing, cancelling and deleting a scheduled game send ``field.changed``
        with ``what: ["schedule"]`` to the field's connected controllers (nothing when nothing changed)."""
        key = sync.new_key()
        await self.fetch("INSERT INTO field_api_keys (field_id, key_sha256) VALUES ($1, $2)", self.field_id,
                         sync.key_hash(key))
        stream = Stream(self.app, key)
        self.addAsyncCleanup(stream.close)
        self.assertEqual((await stream.open())["type"], "websocket.accept")
        await stream.send({"type": "hello", "sync_version": 1, "remote_gm": False,
                           "controller": {"id": "0192f3a4-5b6c-7d8e-9f01-23456789abcd", "version": "0.1.0"}})
        self.assertEqual((await stream.receive())["type"], "hello.ack")

        async def note(what: str, notes: int = 1) -> None:
            await self.app.state.remote_hub.settle()
            for _ in range(notes):
                self.assertEqual(await stream.receive(), {"type": "field.changed", "sync_version": 1,
                                                          "what": ["schedule"]}, what)
            self.assertEqual(stream.pending(), 0, what)

        game = await self.create()
        await note("created")
        await self.patch(game["id"], title="Outro título")
        await note("changed")
        await self.patch(game["id"], title="Outro título")
        await note("the same", notes=0)
        await self.publish(game["id"])
        await note("published")
        r = await self.client.post(self.url(game["id"], "cancel"), json={"reason": "chuva"}, headers=self.admin)
        self.assertEqual(r.status_code, 200, r.text)
        await note("cancelled")
        draft = await self.create()
        await note("another draft")
        r = await self.client.delete(self.url(draft["id"]), headers=self.gm)
        self.assertEqual(r.status_code, 204, r.text)
        await note("deleted")
