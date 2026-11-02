# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Merging two accounts in a hosted hub (decision LG-11): inside one field's schema, as that field's own database role
(S21-13), and never touching another field's accounts.

    python3 tools/docker_server.py test tests.test_account_merge_hosted
"""

from __future__ import annotations

import secrets
import uuid

from sqlalchemy import select

from atalaia_server import personal_data, tenancy
from atalaia_server.api import account_merge
from atalaia_server.models import NoticeRecord, Passkey, User, UserFieldRole, UserIdentity

from .test_tenants import ROLE, HubCase


class HostedMergeTests(HubCase):
    async def make(self, tenant: tenancy.Tenant, name: str, provider: str, subject: str) -> uuid.UUID:
        with tenancy.use(tenant):
            async with self.app.state.sessionmaker() as db:
                user = User(username=name)
                db.add(user)
                await db.flush()
                db.add(UserIdentity(user_id=user.id, provider=provider, subject=subject))
                await db.commit()
                return user.id

    async def test_a_merge_runs_in_one_field_as_its_own_role_and_touches_no_other(self) -> None:
        a = await self.make(self.ta, "uma", "google", "g-1")
        b = await self.make(self.ta, "outra", "microsoft", "m-1")
        other_a = await self.make(self.tb, "uma", "google", "g-b1")  # the same names, in the other field
        other_b = await self.make(self.tb, "outra", "microsoft", "m-b1")
        with tenancy.use(self.ta):
            async with self.app.state.sessionmaker() as db:
                db.add_all([UserFieldRole(user_id=a, field_id=self.ta.field_id, role_id=ROLE["player"]),
                            UserFieldRole(user_id=b, field_id=self.ta.field_id, role_id=ROLE["player"]),
                            UserFieldRole(user_id=b, field_id=self.ta.field_id, role_id=6),
                            NoticeRecord(user_id=b, notice_version="v1", kind="signup"),
                            Passkey(user_id=b, credential_id=secrets.token_bytes(16), public_key=b"k", name="k",
                                    rp_id="campo-a.test")])
                await db.commit()
        with tenancy.use(self.ta):
            async with self.app.state.sessionmaker() as db:
                users = {u.id: u for u in await db.scalars(select(User).where(User.id.in_([a, b])).with_for_update())}
                self.assertIsNone(await account_merge.blocked_by(db, users[a], users[b]))
                moved = await account_merge.merge_into(db, users[a], users[b])
                await db.commit()
        for key in ("user_identities", "user_field_roles", "notice_records", "passkeys"):
            self.assertIn(key, moved)
        rows = await self.sql(self.ta, "SELECT provider FROM user_identities WHERE user_id = $1 ORDER BY provider", a)
        self.assertEqual([r[0] for r in rows], ["google", "microsoft"])
        roles = await self.sql(self.ta, "SELECT role_id FROM user_field_roles WHERE user_id = $1 ORDER BY role_id", a)
        self.assertEqual([r[0] for r in roles], [ROLE["player"], 6])
        retired = (await self.sql(self.ta, "SELECT username, password_hash FROM users WHERE id = $1", b))[0]
        self.assertTrue(retired[0].startswith(personal_data.ERASED_PREFIX))
        self.assertEqual(retired[1], personal_data.ERASED_PASSWORD)
        # The other field's two accounts are as they were.
        same = await self.sql(self.tb, "SELECT username FROM users ORDER BY username")
        self.assertEqual([r[0] for r in same], ["outra", "uma"])
        self.assertEqual((await self.sql(self.tb, "SELECT count(*) FROM user_identities WHERE user_id = ANY($1)",
                                         [other_a, other_b]))[0][0], 2)
