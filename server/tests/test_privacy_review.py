# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The GDPR review's code part (decisions SR-70 to SR-89): the audit log's addresses (PRIV-6), inactive accounts
(PRIV-7), the copies other fields' controllers pulled (PRIV-5), the erasure ledger a restore applies again (PRIV-4)
and the repeat-offender notice and the ban's end (PRIV-2)."""

from __future__ import annotations

import dataclasses
import io
import json
import os
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from unittest import mock

from atalaia_controller import sync_format
from atalaia_server import erasure_ledger, erasure_replay, personal_data
from atalaia_server.config import ConfigError, RetentionPolicy, Settings

from .base import PASSWORD, SECRET_KEY
from .test_chrono import REPLICA, T, ChronoCase, Marshal, field_body, reading
from .test_personal_data import PersonalDataTestCase, bearer

URL = "postgresql+asyncpg://u:p@h:5432/d"
NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


class PolicyConfigTests(unittest.TestCase):
    def settings(self, **env: str) -> Settings:
        return Settings.from_env({"ATALAIA_DATABASE_URL": URL, "ATALAIA_SECRET_KEY": SECRET_KEY, **env})

    def test_the_defaults(self) -> None:
        """180 days of addresses, 24 months of inactivity then 30 days of grace, and no ledger file unless one is named."""
        s = self.settings()
        self.assertEqual((s.retention.audit_ip_days, s.retention.inactive_months, s.retention.inactive_grace_days),
                         (180, 24, 30))
        self.assertIsNone(s.erasure_ledger)

    def test_each_one_is_configurable_and_checked(self) -> None:
        s = self.settings(ATALAIA_AUDIT_IP_DAYS="90", ATALAIA_INACTIVE_ACCOUNT_MONTHS="36",
                          ATALAIA_INACTIVE_GRACE_DAYS="60", ATALAIA_ERASURE_LEDGER="/ledger/erasures.jsonl")
        self.assertEqual((s.retention.audit_ip_days, s.retention.inactive_months, s.retention.inactive_grace_days,
                          s.erasure_ledger), (90, 36, 60, "/ledger/erasures.jsonl"))
        self.assertIsNone(self.settings(ATALAIA_INACTIVE_ACCOUNT_MONTHS="off").retention.inactive_months)
        for name, value in (("ATALAIA_AUDIT_IP_DAYS", "89"), ("ATALAIA_AUDIT_IP_DAYS", "366"),
                            ("ATALAIA_INACTIVE_ACCOUNT_MONTHS", "11"), ("ATALAIA_INACTIVE_ACCOUNT_MONTHS", "soon"),
                            ("ATALAIA_INACTIVE_GRACE_DAYS", "6")):
            with self.subTest(name=name, value=value), self.assertRaises(ConfigError):
                self.settings(**{name: value})
        with self.assertRaises(ConfigError):
            RetentionPolicy(audit_ip_days=30)


class LedgerFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "erasures.jsonl")

    def test_an_entry_holds_hashes_and_nothing_else(self) -> None:
        user, field = uuid.uuid4(), uuid.uuid4()
        entries = [erasure_ledger.account_entry(user, None, NOW),
                   erasure_ledger.player_entry(field, "p-abcdefghijkl", "campo", chrono=True, identity=False, at=NOW)]
        self.assertTrue(erasure_ledger.append(self.path, entries))
        text = open(self.path, encoding="utf-8").read()
        for secret in (str(user), "p-abcdefghijkl"):
            self.assertNotIn(secret, text)
        self.assertEqual(set(entries[0]), {"v", "kind", "tenant", "hash", "at"})
        self.assertEqual(set(entries[1]), {"v", "kind", "tenant", "field", "hash", "chrono", "identity", "at"})
        self.assertEqual(oct(os.stat(self.path).st_mode & 0o777), "0o600")
        read, bad = erasure_ledger.read(self.path)
        self.assertEqual((read, bad), (entries, 0))
        self.assertEqual(entries[0]["hash"], erasure_ledger.hash_account(user))
        self.assertNotEqual(erasure_ledger.hash_player(field, "p-abcdefghijkl"),
                            erasure_ledger.hash_player(uuid.uuid4(), "p-abcdefghijkl"))  # per field

    def test_it_is_append_only_and_skips_what_it_cannot_read(self) -> None:
        a, b = erasure_ledger.account_entry(uuid.uuid4(), None, NOW), erasure_ledger.account_entry(uuid.uuid4(), "x", NOW)
        erasure_ledger.append(self.path, [a])
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write("not json\n" + json.dumps({"v": 2, "kind": "account", "hash": "0" * 64}) + "\n\n")
        erasure_ledger.append(self.path, [b])
        self.assertEqual(erasure_ledger.read(self.path), ([a, b], 2))
        self.assertEqual(erasure_ledger.read(os.path.join(self.dir.name, "missing")), ([], 0))

    def test_off_and_a_failed_write(self) -> None:
        entry = erasure_ledger.account_entry(uuid.uuid4(), None, NOW)
        self.assertFalse(erasure_ledger.append(None, [entry]))  # no ledger: nothing written, nothing raised
        self.assertFalse(erasure_ledger.append(os.path.join(self.dir.name, "no", "such", "dir", "l"), [entry]))

    def test_merge_adds_only_what_is_missing(self) -> None:
        a, b = erasure_ledger.account_entry(uuid.uuid4(), None, NOW), erasure_ledger.account_entry(uuid.uuid4(), None, NOW)
        erasure_ledger.append(self.path, [a])
        lines = [json.dumps(a), json.dumps(b), "garbage", ""]
        self.assertEqual(erasure_ledger.merge(self.path, lines), (1, 1))
        self.assertEqual(erasure_ledger.merge(self.path, lines), (0, 1))
        self.assertEqual(erasure_ledger.read(self.path)[0], [a, b])

    def test_the_export_and_import_commands(self) -> None:
        a = erasure_ledger.account_entry(uuid.uuid4(), None, NOW)
        erasure_ledger.append(self.path, [a])
        out = io.StringIO()
        with mock.patch.dict(os.environ, {erasure_ledger.ENV: self.path}), mock.patch("sys.stdout", out):
            self.assertEqual(erasure_ledger.main(["x", "export"]), 0)
        self.assertEqual([json.loads(line) for line in out.getvalue().splitlines()], [a])
        other = os.path.join(self.dir.name, "other.jsonl")
        with mock.patch.dict(os.environ, {erasure_ledger.ENV: other}), mock.patch("sys.stdin", io.StringIO(out.getvalue())):
            self.assertEqual(erasure_ledger.main(["x", "import"]), 0)
        self.assertEqual(erasure_ledger.read(other)[0], [a])
        with mock.patch.dict(os.environ, {erasure_ledger.ENV: ""}):
            self.assertEqual(erasure_ledger.main(["x", "export"]), 2)


class AuditAddressTests(PersonalDataTestCase):
    async def test_addresses_go_after_the_period_and_the_rows_stay(self) -> None:
        """PRIV-6: an audit row keeps its network address for ``audit_ip_days`` (180 by default), then only the address goes."""
        for action, days in (("old", 200), ("recent", 100), ("ancient", 1096)):
            await self.fetch("INSERT INTO audit_log (action, ip_address, created_at) VALUES ($1, '203.0.113.9', $2)",
                             action, NOW - timedelta(days=days))
        async with self.app.state.sessionmaker() as db:
            counts = await personal_data.purge(db, NOW)
        self.assertEqual((counts["audit_addresses"], counts["audit_log"]), (2, 1))  # 'ancient' loses it, then goes whole
        rows = {r["action"]: r["ip"] for r in await self.fetch(
            "SELECT action, host(ip_address) AS ip FROM audit_log WHERE action IN ('old', 'recent', 'ancient')")}
        self.assertEqual(rows, {"old": None, "recent": "203.0.113.9"})
        async with self.app.state.sessionmaker() as db:  # the shortest period an operator may set
            counts = await personal_data.purge(db, NOW, policy=RetentionPolicy(audit_ip_days=90))
        self.assertEqual(counts["audit_addresses"], 1)
        rows = {r["action"]: r["ip"] for r in await self.fetch(
            "SELECT action, host(ip_address) AS ip FROM audit_log WHERE action IN ('old', 'recent')")}
        self.assertEqual(rows, {"old": None, "recent": None})


class InactiveAccountTests(PersonalDataTestCase):
    async def inactive(self, days: int = 800, **kw: Any) -> uuid.UUID:
        user_id, _, _ = await self.make_user(**kw)
        await self.fetch("UPDATE users SET created_at = $2 WHERE id = $1", user_id, NOW - timedelta(days=days))
        return user_id

    async def purge(self, when: datetime, policy: RetentionPolicy = RetentionPolicy()) -> tuple[dict[str, int], list[uuid.UUID]]:
        gone: list[uuid.UUID] = []
        async with self.app.state.sessionmaker() as db:
            return await personal_data.purge(db, when, policy=policy, anonymised=gone), gone

    async def state(self, user_id: uuid.UUID) -> Any:
        return (await self.fetch("SELECT username, inactivity_warned_at, email FROM users WHERE id = $1", user_id))[0]

    async def test_warned_first_anonymised_after_the_grace(self) -> None:
        """PRIV-7: 24 months without activity: a warning; still inactive 30 days later: anonymised, like an erasure."""
        user_id = await self.inactive()
        fresh, _, _ = await self.make_user()  # created just now: not touched
        counts, gone = await self.purge(NOW)
        self.assertEqual((counts["inactive_warned"], counts["inactive_anonymised"], gone), (1, 0, []))
        self.assertIsNotNone((await self.state(user_id))["inactivity_warned_at"])
        self.assertIsNone((await self.state(fresh))["inactivity_warned_at"])
        counts, gone = await self.purge(NOW + timedelta(days=29))  # inside the grace
        self.assertEqual((counts["inactive_warned"], counts["inactive_anonymised"], gone), (0, 0, []))
        counts, gone = await self.purge(NOW + timedelta(days=31))
        self.assertEqual((counts["inactive_anonymised"], gone), (1, [user_id]))
        self.assertEqual(counts["anonymised_users"], 1)  # nothing refers to the emptied row: RET-9 removes it at once
        self.assertEqual(await self.fetch("SELECT 1 FROM users WHERE id = $1", user_id), [])
        reasons = [json.loads(r["details"])["reason"] for r in await self.audit("gdpr_erasure")]
        self.assertEqual(reasons, ["inactivity"])
        self.assertTrue((await self.state(fresh))["username"].startswith("user-"))

    async def test_a_return_clears_the_warning(self) -> None:
        user_id = await self.inactive()
        await self.purge(NOW)
        await self.fetch("UPDATE users SET last_login_at = $2 WHERE id = $1", user_id, NOW + timedelta(days=5))
        counts, gone = await self.purge(NOW + timedelta(days=40))
        self.assertEqual((counts["inactive_cleared"], counts["inactive_anonymised"], gone), (1, 0, []))
        self.assertIsNone((await self.state(user_id))["inactivity_warned_at"])

    async def test_other_signs_of_life_count(self) -> None:
        """A session, a passkey or a social login is activity (sessions go 30 days after they end; these do not)."""
        by_session = await self.inactive()
        await self.fetch("INSERT INTO sessions (user_id, expires_at, created_at) VALUES ($1, $2, $3)",
                         by_session, NOW + timedelta(days=5), NOW - timedelta(days=2))
        by_identity = await self.inactive()
        await self.fetch("INSERT INTO user_identities (user_id, provider, subject, last_login_at) "
                         "VALUES ($1, 'google', 's', $2)", by_identity, NOW - timedelta(days=30))
        counts, _ = await self.purge(NOW)
        self.assertEqual(counts["inactive_warned"], 0)

    async def test_staff_and_the_server_administrator_are_left_alone(self) -> None:
        staff = await self.inactive()
        await self.fetch("INSERT INTO user_field_roles (user_id, field_id, role_id) VALUES ($1, $2, 1)",
                         staff, await self.field())
        admin = await self.inactive(server_admin=True)
        counts, _ = await self.purge(NOW)
        self.assertEqual(counts["inactive_warned"], 0)
        self.assertIsNone((await self.state(staff))["inactivity_warned_at"])
        self.assertIsNone((await self.state(admin))["inactivity_warned_at"])

    async def test_off_and_the_period_is_configurable(self) -> None:
        user_id = await self.inactive(days=400)
        counts, _ = await self.purge(NOW, RetentionPolicy(inactive_months=None))
        self.assertEqual(counts["inactive_warned"], 0)
        counts, _ = await self.purge(NOW)  # 24 months: 400 days is not enough
        self.assertEqual(counts["inactive_warned"], 0)
        counts, _ = await self.purge(NOW, RetentionPolicy(inactive_months=12))
        self.assertEqual(counts["inactive_warned"], 1)
        counts, gone = await self.purge(NOW + timedelta(days=8), RetentionPolicy(inactive_months=12, inactive_grace_days=7))
        self.assertEqual(gone, [user_id])

    async def test_the_account_shows_the_warning(self) -> None:
        """The server cannot send mail: the account page and ``GET /api/v1/me`` say so when the person comes back."""
        user_id, name, _ = await self.make_user()
        headers = await self.auth(name)
        self.assertIsNone((await self.client.get("/api/v1/me", headers=headers)).json()["inactivity"])
        await self.fetch("UPDATE users SET inactivity_warned_at = $2 WHERE id = $1", user_id, NOW)
        body = (await self.client.get("/api/v1/me", headers=headers)).json()
        self.assertEqual(body["inactivity"], {"warned_at": NOW.isoformat(),
                                              "anonymise_after": (NOW + timedelta(days=30)).isoformat()})
        data = (await self.client.get("/api/v1/me/data", headers=headers)).json()
        self.assertEqual(data["user"]["inactivity_warned_at"], NOW.isoformat())

    async def test_the_purge_task_and_command_enter_them_in_the_ledger(self) -> None:
        user_id = await self.inactive()
        await self.fetch("UPDATE users SET inactivity_warned_at = $2 WHERE id = $1", user_id, NOW - timedelta(days=40))
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "erasures.jsonl")
            await personal_data._purge_one(self.app.state.sessionmaker, None, RetentionPolicy(), path)
            entries, _ = erasure_ledger.read(path)
        self.assertEqual([(e["kind"], e["hash"]) for e in entries], [("account", erasure_ledger.hash_account(user_id))])


class LedgerCase(ChronoCase):
    def settings(self) -> Settings:
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.ledger = os.path.join(self.folder.name, "erasures.jsonl")
        return dataclasses.replace(super().settings(), erasure_ledger=self.ledger)


class CopyRevocationTests(LedgerCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.arena, self.arena_key = await self.make_field("arena")

    async def schedule(self, key: str, query: str = "?revocations=1") -> dict[str, Any]:
        r = await self.client.get("/api/v1/sync/schedule" + query, headers=self.headers(key))
        self.assertEqual(r.status_code, 200, r.text)
        sync_format.ANSWERS["schedule"](json.loads(r.text))  # what a controller checks it with: it passes
        return r.json()

    async def person(self) -> tuple[uuid.UUID, str]:
        user_id, name, _ = await self.make_user()
        await self.link(user_id, "p-aaaaaaaaaaaa")
        await self.link(user_id, "p-bbbbbbbbbbbb", self.arena)
        return user_id, name

    async def test_an_erasure_tells_every_field_the_person_played_at(self) -> None:
        """PRIV-5: the controllers of both fields drop the copies they pulled for the person's ids at their field."""
        user_id, name = await self.person()
        other_id, _, _ = await self.make_user()
        await self.link(other_id, "p-cccccccccccc")  # someone else, untouched
        headers = await self.auth(name)
        r = await self.client.request("DELETE", "/api/v1/me", json={"password": PASSWORD}, headers=headers)
        self.assertEqual(r.status_code, 204, r.text)
        here = (await self.schedule(self.key))["copies_revoked"]
        there = (await self.schedule(self.arena_key))["copies_revoked"]
        self.assertEqual([(x["player_id"], x["reason"]) for x in here], [("p-aaaaaaaaaaaa", "erasure")])
        self.assertEqual([(x["player_id"], x["reason"]) for x in there], [("p-bbbbbbbbbbbb", "erasure")])
        self.assertIn(here[0]["at"], range(int(datetime.now(timezone.utc).timestamp()) - 60,
                                           int(datetime.now(timezone.utc).timestamp()) + 60))
        # An older controller does not ask for them and gets the answer it always had.
        self.assertNotIn("copies_revoked", (await self.client.get("/api/v1/sync/schedule",
                                                                  headers=self.headers())).json())
        # The ledger has the account, as a hash.
        entries, _ = erasure_ledger.read(self.ledger)
        self.assertEqual([(e["kind"], e["hash"]) for e in entries], [("account", erasure_ledger.hash_account(user_id))])

    async def test_a_chrono_erasure_at_the_home_field_tells_the_others(self) -> None:
        await self.person()
        admin = await self.staff("admin")
        r = await self.client.delete(f"/api/v1/fields/{self.field_id}/chrono/players/p-aaaaaaaaaaaa", headers=admin)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([x["player_id"] for x in (await self.schedule(self.arena_key))["copies_revoked"]],
                         ["p-bbbbbbbbbbbb"])
        self.assertNotIn("copies_revoked", await self.schedule(self.key))
        entries, _ = erasure_ledger.read(self.ledger)
        self.assertEqual([(e["kind"], e["chrono"], e["identity"]) for e in entries], [("player", True, False)])

    async def test_withdrawing_a_consent_and_giving_it_again(self) -> None:
        _, name = await self.person()
        headers = await self.auth(name)
        url = f"/api/v1/me/consents/chrono-sharing/{self.field_id}"
        self.assertEqual((await self.client.put(url, headers=headers)).status_code, 201)
        self.assertEqual((await self.client.delete(url, headers=headers)).status_code, 204)
        # The copies of this field's records are at the other field, keyed by the person's id there.
        self.assertEqual([(x["player_id"], x["reason"]) for x in (await self.schedule(self.arena_key))["copies_revoked"]],
                         [("p-bbbbbbbbbbbb", "withdrawn")])
        self.assertNotIn("copies_revoked", await self.schedule(self.key))
        self.assertEqual((await self.client.put(url, headers=headers)).status_code, 201)
        self.assertNotIn("copies_revoked", await self.schedule(self.arena_key))  # copies pulled from now on stay

    async def test_the_record_goes_after_the_fields_retention(self) -> None:
        await self.person()
        r = await self.client.request("DELETE", "/api/v1/me", json={"password": PASSWORD},
                                      headers=await self.auth((await self.fetch("SELECT username FROM users"))[0][0]))
        self.assertEqual(r.status_code, 204)
        await self.fetch("UPDATE fields SET default_retention_days = 30 WHERE id = $1", self.arena)
        await self.fetch("UPDATE chrono_copy_revocations SET created_at = now() - interval '31 days'")
        self.assertNotIn("copies_revoked", await self.schedule(self.arena_key))  # past 30 days: not carried any more
        self.assertEqual(len(await self.fetch("SELECT 1 FROM chrono_copy_revocations")), 2)
        async with self.app.state.sessionmaker() as db:
            counts = await personal_data.purge(db)
        self.assertEqual(counts["copy_revocations"], 1)  # the arena's, at its 30 days; the 365-day field's stays
        self.assertEqual(len(await self.fetch("SELECT 1 FROM chrono_copy_revocations")), 1)


class LedgerReplayTests(LedgerCase):
    async def test_a_restore_does_not_bring_an_erased_account_back(self) -> None:
        """PRIV-4: the account is erased, then 'restored' from a backup that still holds it; the ledger erases it again."""
        user_id, name, _ = await self.make_user()
        await self.fetch("UPDATE users SET email = 'ana@example.pt' WHERE id = $1", user_id)
        r = await self.client.request("DELETE", "/api/v1/me", json={"password": PASSWORD},
                                      headers=await self.auth(name))
        self.assertEqual(r.status_code, 204, r.text)
        keeper, keeper_name, _ = await self.make_user()  # never erased: must survive the replay
        # What a restore does: the row comes back as the backup had it.
        await self.fetch("UPDATE users SET username = $2, email = 'ana@example.pt', password_hash = 'x' WHERE id = $1",
                         user_id, name)
        entries, _ = erasure_ledger.read(self.ledger)
        async with self.app.state.sessionmaker() as db:
            done = await erasure_replay.apply_entries(db, entries)
            await db.commit()
        self.assertEqual(done["accounts"], 1)
        row = (await self.fetch("SELECT username, email, password_hash FROM users WHERE id = $1", user_id))[0]
        self.assertTrue(row["username"].startswith("deleted-"))
        self.assertEqual((row["email"], row["password_hash"]), (None, personal_data.ERASED_PASSWORD))
        self.assertEqual((await self.fetch("SELECT username FROM users WHERE id = $1", keeper))[0][0], keeper_name)
        async with self.app.state.sessionmaker() as db:  # again: nothing left to do
            self.assertEqual((await erasure_replay.apply_entries(db, entries))["accounts"], 0)

    async def test_a_restore_does_not_bring_back_a_players_chrono_records(self) -> None:
        marshal = Marshal()
        await self.marshals(marshal.entry())
        replica = {"replica_id": REPLICA, "owner_player_id": "p-rita", "type": "sniper", "class": "sniper",
                   "make_model": "VSR-10", "tag_type": "qr", "tag_uid": "ATL-0001"}
        await self.post("replicas", field_body(replicas=[replica]))
        await self.chrono(reading(marshal.record(100.0)))
        admin = await self.staff("admin")
        r = await self.client.delete(f"/api/v1/fields/{self.field_id}/chrono/players/p-rita", headers=admin)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((await self.count("chrono_readings"), await self.count("replicas")), (0, 0))
        await self.marshals(marshal.entry())
        await self.post("replicas", field_body(replicas=[replica]))  # the backup's copy of the player's data
        await self.chrono(reading(marshal.record(100.0)))
        self.assertEqual((await self.count("chrono_readings"), await self.count("replicas")), (1, 1))
        entries, _ = erasure_ledger.read(self.ledger)
        async with self.app.state.sessionmaker() as db:
            done = await erasure_replay.apply_entries(db, entries)
            await db.commit()
        self.assertEqual((done["players"], done["chrono_readings"], done["replicas"]), (1, 1, 1))
        self.assertEqual((await self.count("chrono_readings"), await self.count("replicas")), (0, 0))

    async def test_the_command_and_a_ledger_with_nothing_to_do(self) -> None:
        out = io.StringIO()
        erasure_ledger.append(self.ledger, [erasure_ledger.account_entry(uuid.uuid4(), None)])
        self.assertEqual(sum((await erasure_replay.apply_ledger(self.app.state.settings, out)).values()), 0)
        self.assertIn("1 entries", out.getvalue())


class RepeatRuleTests(LedgerCase):
    """PRIV-2: the repeat-offender notice, the rule on warnings, and the ban's end."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.ana = Marshal()
        await self.marshals(self.ana.entry())
        self.admin = await self.staff("admin")
        self.gm = await self.staff("gm")
        self.url = f"/api/v1/fields/{self.field_id}"

    async def violations(self) -> dict[str, Any]:
        r = await self.client.get(self.url + "/chrono/violations", headers=self.gm)
        return {v["series_id"]: v for v in r.json()}

    async def two(self, first: str) -> list[str]:
        """Two series of one player, the older judged ``first`` ("fail" or "warn"), the newer a fail."""
        series = [str(uuid.uuid4()), str(uuid.uuid4())]
        await self.chrono(reading(self.ana.record(100.0, rtype="spotcheck", at=T - 600), series[0], first, limit_j=1.0))
        await self.chrono(reading(self.ana.record(110.0, rtype="spotcheck", at=T - 300), series[1], "fail", limit_j=1.0))
        return series

    async def test_a_warning_alone_never_makes_a_repeat(self) -> None:
        older, newer = await self.two("warn")
        got = await self.violations()
        self.assertEqual(got[older]["violation_type"], "over_tolerance")
        self.assertEqual((got[older]["repeat_offender"], got[newer]["repeat_offender"]), (False, False))
        # A fixed rule: no setting turns it on, and the field's answer has none.
        r = await self.client.patch(self.url, json={"chrono_warning_counts": True}, headers=self.admin)
        self.assertEqual(r.status_code, 422, r.text)
        self.assertNotIn("chrono_warning_counts",
                         (await self.client.patch(self.url, json={"chrono_ban_days": 30}, headers=self.admin)).json())

    async def test_a_failure_makes_a_repeat_unless_staff_only_warned(self) -> None:
        older, newer = await self.two("fail")
        got = await self.violations()
        self.assertEqual((got[older]["repeat_offender"], got[newer]["repeat_offender"]), (False, True))
        r = await self.client.patch(f"{self.url}/chrono/violations/{got[older]['id']}", json={"outcome": "warning"},
                                    headers=self.gm)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse((await self.violations())[newer]["repeat_offender"])  # staff only warned: it does not count
        r = await self.client.patch(f"{self.url}/chrono/violations/{got[older]['id']}", json={"outcome": "pulled"},
                                    headers=self.gm)
        self.assertTrue((await self.violations())[newer]["repeat_offender"])

    async def test_a_ban_ends(self) -> None:
        older, newer = await self.two("fail")
        violation = (await self.violations())[newer]
        reading_time = (await self.fetch("SELECT r.timestamp FROM chrono_readings r JOIN chrono_violations v "
                                         "ON v.reading = r.id WHERE v.id = $1", uuid.UUID(violation["id"])))[0][0]
        patch = f"{self.url}/chrono/violations/{violation['id']}"
        r = await self.client.patch(patch, json={"outcome": "ban"}, headers=self.gm)
        self.assertEqual(r.status_code, 200, r.text)
        ban = r.json()
        # By default as long as the field keeps the record, and not a day longer: the violation goes with it.
        self.assertEqual(datetime.fromisoformat(ban["ban_expires_at"]), reading_time + timedelta(days=365))
        self.assertTrue(ban["ban_active"])
        # The field sets a shorter ban; a longer one than its chrono retention is refused.
        r = await self.client.patch(self.url, json={"chrono_ban_days": 30}, headers=self.admin)
        self.assertEqual((r.status_code, r.json()["chrono_ban_days"]), (200, 30), r.text)
        self.assertEqual((await self.client.patch(self.url, json={"chrono_ban_days": 366}, headers=self.admin)
                          ).json()["detail"], "chrono_ban_days_invalid")
        ban = (await self.client.patch(patch, json={"outcome": "ban"}, headers=self.gm)).json()
        expires = datetime.fromisoformat(ban["ban_expires_at"])
        self.assertLess(abs((expires - datetime.now(timezone.utc) - timedelta(days=30)).total_seconds()), 120)
        # An ended ban is shown as ended; another outcome has no end.
        await self.fetch("UPDATE chrono_violations SET ban_expires_at = now() - interval '1 day' WHERE id = $1",
                         uuid.UUID(violation["id"]))
        ended = (await self.violations())[newer]
        self.assertEqual((ended["outcome"], ended["ban_active"]), ("ban", False))
        other = (await self.client.patch(patch, json={"outcome": "pulled"}, headers=self.gm)).json()
        self.assertEqual((other["ban_expires_at"], other["ban_active"]), (None, False))
        r = await self.client.patch(self.url, json={"chrono_ban_days": None}, headers=self.admin)
        self.assertIsNone(r.json()["chrono_ban_days"])

    async def test_the_page_is_served_and_says_advisory(self) -> None:
        r = await self.client.get(f"/staff/fields/{self.field_id}/chrono?lang=en")
        self.assertEqual(r.status_code, 200)
        self.assertIn('data-page="chrono"', r.text)
        self.assertIn("only a notice", r.text)
        self.assertIn("no decision rests on it alone", r.text)
        for lang, word in (("pt", "Já houve uma violação anterior"), ("de", "Es gab schon einen früheren Verstoß"),
                           ("zh-tw", "先前已有違規紀錄")):
            with self.subTest(lang=lang):
                self.assertIn(word, (await self.client.get(f"/staff/fields/{self.field_id}/chrono?lang={lang}")).text)


class NoNoticeSignupTests(PersonalDataTestCase):
    """LIVE-2: with no privacy notice published, no new account is made (a consent is to a text); logins go on."""

    allow = False
    notice_dir: Optional[str] = None

    def settings(self) -> Settings:
        return dataclasses.replace(super().settings(), allow_signup_without_notice=self.allow,
                                   privacy_notice_dir=self.notice_dir)

    async def test_registering_is_refused_and_a_login_still_works(self) -> None:
        r = await self.client.post("/api/v1/auth/register", json={"username": "novo", "password": PASSWORD,
                                                                  "consent": True})
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "privacy_notice_unpublished"))
        self.assertEqual(await self.fetch("SELECT 1 FROM users WHERE username = 'novo'"), [])
        _, name, _ = await self.make_user()
        self.assertTrue((await self.login(name))["access_token"])

    async def test_a_published_notice_changes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            version = self.app.state.settings.privacy_notice_version
            with open(os.path.join(folder, f"privacy-notice-en-{version}.md"), "w", encoding="utf-8") as handle:
                handle.write("# Notice\n")
            self.app.state.settings = dataclasses.replace(self.app.state.settings, privacy_notice_dir=folder)
            r = await self.client.post("/api/v1/auth/register", json={"username": "novo", "password": PASSWORD,
                                                                      "consent": True})
            self.assertEqual(r.status_code, 201, r.text)

    async def test_the_setting_allows_it(self) -> None:
        self.app.state.settings = dataclasses.replace(self.app.state.settings, allow_signup_without_notice=True)
        r = await self.client.post("/api/v1/auth/register", json={"username": "novo", "password": PASSWORD,
                                                                  "consent": True})
        self.assertEqual(r.status_code, 201, r.text)

    def test_the_default_is_off(self) -> None:
        env = {"ATALAIA_DATABASE_URL": URL, "ATALAIA_SECRET_KEY": SECRET_KEY}
        self.assertFalse(Settings.from_env(env).allow_signup_without_notice)
        self.assertTrue(Settings.from_env({**env, "ATALAIA_ALLOW_SIGNUP_WITHOUT_NOTICE": "on"}).allow_signup_without_notice)


class NoticeLinkTests(PersonalDataTestCase):
    """LIVE-2: the footers and the login consent link to /privacy only when a notice is published."""

    async def pages(self) -> dict[str, str]:
        out = {}
        for path in ("/staff/login?lang=en", "/staff/login", "/privacy", "/staff/account?lang=en"):
            out[path] = (await self.client.get(path)).text
        return out

    async def test_no_link_without_a_notice_and_a_link_with_one(self) -> None:
        none = await self.pages()
        self.assertNotIn('href="/privacy', none["/staff/login?lang=en"])
        self.assertNotIn('href="/privacy', none["/staff/account?lang=en"])
        self.assertIn("privacy notice", none["/staff/login?lang=en"])  # the plain text stays
        with tempfile.TemporaryDirectory() as folder:
            version = self.app.state.settings.privacy_notice_version
            with open(os.path.join(folder, f"privacy-notice-en-{version}.md"), "w", encoding="utf-8") as handle:
                handle.write("# Notice\n")
            self.app.state.settings = dataclasses.replace(self.app.state.settings, privacy_notice_dir=folder)
            some = await self.pages()
            self.assertIn('<a href="/privacy?lang=en">Privacy notice</a>', some["/staff/account?lang=en"])
            self.assertIn('href="/privacy?lang=en" target="_blank"', some["/staff/login?lang=en"])
            self.assertIn('href="/privacy"', some["/staff/login"])
            self.assertNotIn(' · <a href="/privacy', some["/privacy"])  # not on the notice itself
