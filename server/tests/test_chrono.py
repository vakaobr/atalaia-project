# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The chrono registry on PostgreSQL 16 (ADR-P4-5 as amended, plan phase 14, P4R14, P4R15).

The shared vectors of ``protocol/vectors/chrono_record.json`` through
``POST /api/v1/sync/chrono`` (every valid one accepted, every invalid one
refused with its reason and kept apart), tampered records, a reading sent
twice and a conflicting one, a rotated and a revoked key, violations, the
staff views and their roles, a marshal's own key, cross-field sharing with
consent, and the personal data hooks: access, export, erasure (the record
stays, the link to the person goes) and the purge.
"""

from __future__ import annotations

import base64
import datetime
import io
import json
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any, Optional

from atalaia_controller import chrono, sync_format
from atalaia_server import personal_data
from atalaia_server.models import Field, FieldPlayerId, GameRegistration, ScheduledGame

from .test_sync import CONTROLLER, GAME, SyncTestCase

REPO = Path(__file__).resolve().parents[2]
VECTORS = json.loads((REPO / "protocol" / "vectors" / "chrono_record.json").read_text(encoding="utf-8"))
TEST_KEY = base64.b64encode(bytes.fromhex(VECTORS["public_key"])).decode()
T0 = 1792000000.0  # the test key's registration on the controller
T = 1792333805.0   # readings received (after every vector's timestamp)
SERIES = "0f6e5d4c-3b2a-4198-8776-655443322110"
REPLICA = "8a1f0c2e-7b3d-4c5e-8f9a-0b1c2d3e4f50"


def field_body(**body: Any) -> dict[str, Any]:
    """A chrono registry body: the common part without a game."""
    return {"sync_version": 1, "controller": {"id": CONTROLLER, "version": "0.1.0"}, **body}


def stamp(t: float) -> str:
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Marshal:
    """A marshal's phone: an Ed25519 key and the signed records it makes (protocol/chrono-record.md)."""

    def __init__(self, marshal_id: str = "m-ana", name: str = "Ana", seed: Optional[bytes] = None) -> None:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization

        self.key = Ed25519PrivateKey.from_private_bytes(seed) if seed else Ed25519PrivateKey.generate()
        self.marshal_id, self.name = marshal_id, name
        raw = self.key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.public = base64.b64encode(raw).decode()

    def sign(self, record: dict[str, Any]) -> dict[str, Any]:
        out = {k: v for k, v in record.items() if k != "signature"}
        out["signature"] = base64.b64encode(self.key.sign(chrono.canonical(out))).decode()
        return out

    def record(self, velocity: float = 100.0, *, player: str = "p-rita", replica: str = REPLICA,
               rtype: str = "checkin", at: float = T - 60, bb: float = 0.2, **extra: Any) -> dict[str, Any]:
        return self.sign({
            "reading_id": str(uuid.uuid4()), "replica_id": replica, "player_id": player, "type": rtype,
            "velocity_mps": velocity, "bb_weight_g": bb,
            "energy_j": chrono.round_half_away(chrono.energy_j(bb, velocity), 3), "chrono_id": "chrono-1",
            "marshal_id": self.marshal_id, "marshal_name": self.name, "field_id": "campo", "timestamp": stamp(at),
            **extra})

    def entry(self, registered: float = T0, replaced: Optional[float] = None) -> dict[str, Any]:
        return {"marshal_id": self.marshal_id, "name": self.name, "public_key": self.public,
                "registered_at": registered, "replaced_at": replaced}


def reading(record: Any, series: str = SERIES, outcome: Optional[str] = "pass", received: float = T,
            **extra: Any) -> dict[str, Any]:
    text = record if isinstance(record, str) else json.dumps(record, ensure_ascii=False)
    return {"record": text, "series_id": series, "outcome": outcome, "received_at": received, **extra}


class ChronoCase(SyncTestCase):
    async def marshals(self, *entries: dict[str, Any], key: Optional[str] = None) -> dict[str, Any]:
        return await self.post("marshals", field_body(marshals=list(entries)), key)

    async def chrono(self, *readings: dict[str, Any], key: Optional[str] = None) -> dict[str, Any]:
        return await self.post("chrono", field_body(readings=list(readings)), key)

    async def vector_key(self, registered: float = T0) -> None:
        await self.marshals({"marshal_id": "m-xyz789", "name": "Jose", "public_key": TEST_KEY,
                             "registered_at": registered})

    async def staff(self, role: str, field_id: Optional[uuid.UUID] = None) -> dict[str, str]:
        """An account with this role on the field (TOTP where the role needs it), logged in."""
        admin = getattr(self, "_admin", None) or await self.admin_headers()
        self._admin = admin
        _, name, secret = await self.make_user(with_totp=role in ("admin", "gm", "marshal"))
        r = await self.client.put(f"/api/v1/fields/{field_id or self.field_id}/roles",
                                  json={"username": name, "role": role}, headers=admin)
        self.assertEqual(r.status_code, 201, r.text)
        return await self.auth(name, secret=secret)

    async def link(self, user_id: uuid.UUID, player_id: str, field_id: Optional[uuid.UUID] = None) -> None:
        """An account holding a field's player id (the adoption itself is plan phase 16's)."""
        async with self.app.state.sessionmaker() as db:
            db.add(FieldPlayerId(field_id=field_id or self.field_id, player_id=player_id, user_id=user_id))
            await db.commit()


class VectorTests(ChronoCase):
    async def test_every_valid_vector_is_accepted_and_kept_verbatim(self) -> None:
        await self.vector_key()
        texts = [json.dumps(v["record"], ensure_ascii=False, indent=1) for v in VECTORS["valid"]]
        answer = await self.chrono(*[reading(t) for t in texts])
        self.assertEqual(answer, {"accepted": 4, "duplicates": 0, "refused": [], "violations": 0})
        rows = await self.fetch("SELECT reading_id, record_json, player_id, energy_j, marshal_id, record_field_id, "
                                "timestamp, series_id, outcome FROM chrono_readings ORDER BY timestamp")
        self.assertEqual(len(rows), 4)
        by_id = {str(r["reading_id"]): r for r in rows}
        for vector, sent in zip(VECTORS["valid"], texts):
            with self.subTest(vector=vector["name"]):
                row = by_id[vector["record"]["reading_id"]]
                self.assertEqual(row["record_json"], sent)  # as received, to the byte
                self.assertEqual((row["player_id"], row["energy_j"], row["marshal_id"], row["record_field_id"]),
                                 (vector["record"]["player_id"], vector["record"]["energy_j"], "m-xyz789",
                                  vector["record"]["field_id"]))
                self.assertEqual(row["timestamp"].strftime("%Y-%m-%dT%H:%M:%SZ"), vector["record"]["timestamp"])
                chrono.parse(row["record_json"], bytes.fromhex(VECTORS["public_key"]))  # anyone can check it

    async def test_every_invalid_vector_is_refused_with_its_reason_and_kept_apart(self) -> None:
        await self.vector_key()
        vectors = VECTORS["invalid"]
        answer = await self.chrono(*[reading(v["record"]) for v in vectors])
        self.assertEqual((answer["accepted"], answer["duplicates"]), (0, 0))
        self.assertEqual([(r["index"], r["reason"]) for r in answer["refused"]],
                         [(i, v["reason"]) for i, v in enumerate(vectors)])
        self.assertEqual(await self.count("chrono_readings"), 0)
        rejects = await self.fetch("SELECT reason, record_text, times FROM chrono_rejects")
        # Two invalid vectors may share a text: each distinct record is kept once.
        texts = {json.dumps(v["record"], ensure_ascii=False) for v in vectors}
        self.assertEqual({r["record_text"] for r in rejects}, texts)
        self.assertEqual({r["reason"] for r in rejects}, {v["reason"] for v in vectors})

    async def test_without_the_marshals_key(self) -> None:
        """A record whose marshal the site server has no key for is kept apart; when the key comes, it is
        checked again, stored, and nothing is left apart. Sent again later, it is a duplicate."""
        record = VECTORS["valid"][0]["record"]
        answer = await self.chrono(reading(record))
        self.assertEqual([r["reason"] for r in answer["refused"]], ["marshal"])
        self.assertEqual(answer["refused"][0]["reading_id"], record["reading_id"])
        self.assertEqual(await self.count("chrono_rejects"), 1)
        late = await self.marshals({"marshal_id": "m-xyz789", "name": "Jose", "public_key": TEST_KEY,
                                    "registered_at": T0})
        self.assertEqual(late["resolved"], 1)
        self.assertEqual((await self.count("chrono_rejects"), await self.count("chrono_readings")), (0, 1))
        self.assertEqual((await self.chrono(reading(record)))["duplicates"], 1)
        # A key that was not valid when the controller got the reading settles nothing.
        other = VECTORS["valid"][3]["record"]
        await self.chrono(reading(other, received=T0 - 10))
        self.assertEqual((await self.marshals({"marshal_id": "m-xyz789", "name": "Jose", "public_key": TEST_KEY,
                                               "registered_at": T0}))["resolved"], 0)
        self.assertEqual(await self.count("chrono_rejects"), 1)


class TamperTests(ChronoCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.ana = Marshal()
        await self.marshals(self.ana.entry())

    async def test_tampered_records_are_refused(self) -> None:
        good = self.ana.record(104.0)
        cases = {
            "velocity": {**good, "velocity_mps": 90.0, "energy_j": chrono.round_half_away(chrono.energy_j(0.2, 90.0), 3)},
            "player": {**good, "player_id": "p-other"},
            "marshal_name": {**good, "marshal_name": "Outra"},
            "timestamp": {**good, "timestamp": stamp(T - 3600)},
            "signed_elsewhere": Marshal("m-ana", "Ana").sign(good),
            "another_signature": {**good, "signature": self.ana.record(80.0)["signature"]},
        }
        answer = await self.chrono(*[reading(r) for r in cases.values()])
        self.assertEqual([r["reason"] for r in answer["refused"]], ["signature"] * len(cases))
        self.assertEqual(await self.count("chrono_readings"), 0)
        self.assertEqual((await self.chrono(reading(good)))["accepted"], 1)

    async def test_twice_and_a_conflict(self) -> None:
        series = [self.ana.record(v) for v in (100.0, 101.0, 102.0)]
        self.assertEqual((await self.chrono(*[reading(r) for r in series]))["accepted"], 3)
        again = await self.chrono(*[reading(r) for r in series])
        self.assertEqual((again["accepted"], again["duplicates"], again["refused"]), (0, 3, []))
        # The same record in another text (a standby re-serialised it): still a duplicate.
        self.assertEqual((await self.chrono(reading(json.dumps(series[0], indent=2))))["duplicates"], 1)
        # Another genuine record under a stored reading id: kept apart, the stored one untouched.
        clash = self.ana.sign({**series[0], "velocity_mps": 90.0,
                               "energy_j": chrono.round_half_away(chrono.energy_j(0.2, 90.0), 3)})
        answer = await self.chrono(reading(clash))
        self.assertEqual([r["reason"] for r in answer["refused"]], ["conflict"])
        rows = await self.fetch("SELECT velocity_mps FROM chrono_readings WHERE reading_id = $1",
                                uuid.UUID(series[0]["reading_id"]))
        self.assertEqual(rows[0][0], 100.0)
        # The same refusal again counts, not a second row.
        await self.chrono(reading(clash))
        self.assertEqual([tuple(r) for r in await self.fetch("SELECT reason, times FROM chrono_rejects")],
                         [("conflict", 2)])
        self.assertEqual(await self.count("chrono_readings"), 3)

    async def test_a_reading_for_another_field_stays_there(self) -> None:
        """Reading ids are per field: another field's controller cannot claim or block this field's."""
        other_field, other_key = await self.make_field("arena")
        record = self.ana.record()
        await self.marshals(self.ana.entry(), key=other_key)
        self.assertEqual((await self.chrono(reading(record), key=other_key))["accepted"], 1)
        self.assertEqual((await self.chrono(reading(record)))["accepted"], 1)
        rows = await self.fetch("SELECT field_id FROM chrono_readings")
        self.assertEqual({r[0] for r in rows}, {self.field_id, other_field})


class KeyTests(ChronoCase):
    async def test_a_rotated_key(self) -> None:
        """A lost phone: the controller replaced the marshal's key at T0 + 1000. Old readings verify with
        the old key; readings received after the rotation verify only with the new one."""
        old, new = Marshal(), Marshal()
        rotated = T0 + 1000
        answer = await self.marshals(old.entry(T0, rotated), new.entry(rotated))
        self.assertEqual((answer["marshals"], answer["added"]), (2, 2))
        early = old.record(at=T0 + 500)
        late_old = old.record(at=rotated + 10)
        late_new = new.record(at=rotated + 10)
        answer = await self.chrono(reading(early, received=T0 + 600), reading(late_old, received=rotated + 20),
                                   reading(late_new, received=rotated + 20))
        self.assertEqual(answer["accepted"], 2)
        self.assertEqual([(r["index"], r["reason"]) for r in answer["refused"]], [(1, "signature")])
        keys = {r["public_key"]: r["id"] for r in await self.fetch("SELECT id, public_key FROM marshal_keys")}
        used = {str(r["reading_id"]): r["marshal_key"] for r in await self.fetch(
            "SELECT reading_id, marshal_key FROM chrono_readings")}
        self.assertEqual(used[early["reading_id"]], keys[base64.b64decode(old.public)])
        self.assertEqual(used[late_new["reading_id"]], keys[base64.b64decode(new.public)])

    async def test_periods_merge(self) -> None:
        """The same key from two controllers or twice: its earliest start, the last end sent."""
        ana = Marshal()
        await self.marshals(ana.entry(T0 + 100))
        answer = await self.marshals(ana.entry(T0, T0 + 5000))
        self.assertEqual((answer["marshals"], answer["added"]), (1, 0))
        row = (await self.fetch("SELECT valid_from, valid_until, source FROM marshal_keys"))[0]
        self.assertEqual((row[0].timestamp(), row[1].timestamp(), row[2]), (T0, T0 + 5000, "controller"))

    async def test_a_marshal_registers_their_key_and_an_admin_revokes_it(self) -> None:
        ana = Marshal()
        marshal = await self.staff("marshal")
        url = f"/api/v1/fields/{self.field_id}/marshal-keys"
        r = await self.client.post(url, json={"marshal_id": "m-ana", "name": "Ana", "public_key": ana.public},
                                   headers=marshal)
        self.assertEqual(r.status_code, 201, r.text)
        key = r.json()
        self.assertEqual((key["source"], key["linked_account"], key["valid_until"]), ("account", True, None))
        # The controller sends the same key: the account's link stays.
        await self.marshals(ana.entry(T0))
        rows = await self.fetch("SELECT source, user_id IS NOT NULL AS linked FROM marshal_keys")
        self.assertEqual([tuple(r) for r in rows], [("account", True)])
        # Another account cannot take the marshal id; a private key is never accepted.
        other = await self.staff("marshal")
        r = await self.client.post(url, json={"marshal_id": "m-ana", "name": "Ana", "public_key": Marshal().public},
                                   headers=other)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "marshal_id_taken"))
        r = await self.client.post(url, json={"marshal_id": "m-ana", "name": "Ana", "public_key": ana.public,
                                              "private_key": "x"}, headers=marshal)
        self.assertEqual(r.status_code, 422)
        for bad in ("A" * 44, base64.b64encode(bytes(31)).decode(), "not base64!"):
            r = await self.client.post(url, json={"marshal_id": "m-bea", "name": "Bea", "public_key": bad},
                                       headers=marshal)
            self.assertEqual(r.status_code, 400, bad)
        # A gm or a player may not register keys; only the admin revokes.
        gm = await self.staff("gm")
        r = await self.client.post(url, json={"marshal_id": "m-gm", "name": "G", "public_key": Marshal().public},
                                   headers=gm)
        self.assertEqual(r.status_code, 403)
        self.assertEqual((await self.client.delete(f"{url}/{key['id']}", headers=marshal)).status_code, 403)
        listed = (await self.client.get(url, headers=gm)).json()
        self.assertEqual([k["public_key"] for k in listed], [ana.public])
        self.assertNotIn("user_id", listed[0])
        # Good until the revocation (made now, on this server's clock), refused after it.
        now = time.time()
        before = ana.record(at=now - 120)
        self.assertEqual((await self.chrono(reading(before, received=now - 60)))["accepted"], 1)
        r = await self.client.delete(f"{url}/{key['id']}", headers=self._admin)
        self.assertEqual(r.status_code, 204)
        after = ana.record(at=now)
        answer = await self.chrono(reading(after, received=now + 60))
        self.assertEqual([r["reason"] for r in answer["refused"]], ["marshal"])
        actions = [r[0] for r in await self.fetch("SELECT action FROM audit_log WHERE action LIKE 'marshal_key%'")]
        self.assertEqual(actions, ["marshal_key_register", "marshal_key_revoke"])

    async def test_a_new_key_from_the_account_ends_the_old_one(self) -> None:
        marshal = await self.staff("marshal")
        url = f"/api/v1/fields/{self.field_id}/marshal-keys"
        first, second = Marshal(), Marshal()
        for m in (first, second):
            r = await self.client.post(url, json={"marshal_id": "m-ana", "name": "Ana", "public_key": m.public},
                                       headers=marshal)
            self.assertEqual(r.status_code, 201, r.text)
        rows = await self.fetch("SELECT valid_until IS NULL AS current FROM marshal_keys ORDER BY valid_from")
        self.assertEqual([r[0] for r in rows], [False, True])


class ViolationTests(ChronoCase):
    async def test_failed_and_warned_spot_checks(self) -> None:
        ana = Marshal()
        await self.marshals(ana.entry())
        fail = [ana.record(v, rtype="spotcheck") for v in (100.0, 110.0, 105.0)]
        warn = [ana.record(v, rtype="spotcheck", player="p-bea") for v in (101.0,)]
        passed = [ana.record(v, rtype="spotcheck", player="p-caio") for v in (90.0,)]
        refused_checkin = [ana.record(v) for v in (120.0,)]  # a check-in refusal is not a violation
        series = [str(uuid.uuid4()) for _ in range(4)]
        answer = await self.chrono(*[reading(r, series[0], "fail") for r in fail],
                                   *[reading(r, series[1], "warn") for r in warn],
                                   *[reading(r, series[2], "pass") for r in passed],
                                   *[reading(r, series[3], "fail") for r in refused_checkin])
        self.assertEqual((answer["accepted"], answer["violations"]), (6, 2))
        gm = await self.staff("gm")
        url = f"/api/v1/fields/{self.field_id}/chrono/violations"
        listed = (await self.client.get(url, headers=gm)).json()
        by_series = {v["series_id"]: v for v in listed}
        self.assertEqual(set(by_series), {series[0], series[1]})
        top = by_series[series[0]]
        self.assertEqual((top["violation_type"], top["energy_j"], top["player_id"]),
                         ("over_limit", chrono.round_half_away(chrono.energy_j(0.2, 110.0), 3), "p-rita"))
        self.assertEqual(by_series[series[1]]["violation_type"], "over_tolerance")
        marshal = await self.staff("marshal")
        r = await self.client.patch(f"{url}/{top['id']}", json={"outcome": "pulled"}, headers=marshal)
        self.assertEqual(r.status_code, 403)
        r = await self.client.patch(f"{url}/{top['id']}", json={"outcome": "jail"}, headers=gm)
        self.assertEqual(r.status_code, 400)
        r = await self.client.patch(f"{url}/{top['id']}", json={"outcome": "pulled"}, headers=gm)
        self.assertEqual((r.status_code, r.json()["outcome"]), (200, "pulled"))
        still_open = (await self.client.get(url + "?open=true", headers=marshal)).json()
        self.assertEqual([v["series_id"] for v in still_open], [series[1]])

    async def test_the_excess_over_the_class_limit_and_repeat_offenders(self) -> None:
        """PKD-3: the controller sends the class limit with each reading; the violation gets ``limit_j`` and
        ``delta_j`` (the excess of the deciding reading), and a player's later violations at the field are
        flagged ``repeat_offender``, also when the older one arrives later; no limit sent, no ``delta_j``."""
        ana = Marshal()
        await self.marshals(ana.entry())
        series = [str(uuid.uuid4()) for _ in range(3)]
        older = [ana.record(v, rtype="spotcheck", at=T - 600) for v in (100.0, 104.0)]
        newer = [ana.record(v, rtype="spotcheck", at=T - 300) for v in (110.0,)]
        other = [ana.record(v, rtype="spotcheck", player="p-bea") for v in (101.0,)]
        # The newer one first: alone it is no repeat.
        await self.chrono(*[reading(r, series[1], "fail", limit_j=1.0) for r in newer])
        gm = await self.staff("gm")
        url = f"/api/v1/fields/{self.field_id}/chrono/violations"

        async def listed() -> dict[str, Any]:
            return {v["series_id"]: v for v in (await self.client.get(url, headers=gm)).json()}

        got = await listed()
        energy = chrono.round_half_away(chrono.energy_j(0.2, 110.0), 3)
        self.assertEqual((got[series[1]]["limit_j"], got[series[1]]["repeat_offender"]), (1.0, False))
        self.assertAlmostEqual(got[series[1]]["delta_j"], energy - 1.0)
        # The older series comes later (two readings, the second decides): it is the first, the newer a repeat.
        await self.chrono(*[reading(r, series[0], "fail", limit_j=1.0) for r in older])
        await self.chrono(*[reading(r, series[2], "warn") for r in other])  # no limit sent
        got = await listed()
        top = chrono.round_half_away(chrono.energy_j(0.2, 104.0), 3)
        self.assertEqual((got[series[0]]["energy_j"], got[series[0]]["repeat_offender"]), (top, False))
        self.assertAlmostEqual(got[series[0]]["delta_j"], top - 1.0)
        self.assertTrue(got[series[1]]["repeat_offender"])
        self.assertEqual((got[series[2]]["limit_j"], got[series[2]]["delta_j"], got[series[2]]["repeat_offender"]),
                         (None, None, False))  # another player, no limit sent


class StaffViewTests(ChronoCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.ana = Marshal()
        await self.marshals(self.ana.entry())
        await self.post("replicas", field_body(replicas=[{"replica_id": REPLICA, "owner_player_id": "p-rita",
                                                          "type": "sniper", "class": "sniper", "make_model": "VSR-10",
                                                          "tag_type": "qr", "tag_uid": "ATL-0001"}]))
        await self.make_game()
        self.records = [self.ana.record(v, game_id=str(GAME["game_id"])) for v in (100.0, 101.0)]
        await self.chrono(*[reading(r, game_seed=GAME["game_seed"]) for r in self.records])

    async def test_who_sees_the_registry(self) -> None:
        base = f"/api/v1/fields/{self.field_id}"
        player = await self.staff("player")
        marshal = await self.staff("marshal")
        for path in ("/chrono/readings", "/chrono/violations", "/replicas", "/marshal-keys", "/chrono/players/p-rita",
                     "/chrono/rejects"):
            with self.subTest(path=path):
                self.assertEqual((await self.client.get(base + path)).status_code, 401)
                self.assertEqual((await self.client.get(base + path, headers=player)).status_code, 403)
                want = 403 if path == "/chrono/rejects" else 200
                self.assertEqual((await self.client.get(base + path, headers=marshal)).status_code, want)
        page = (await self.client.get(base + "/chrono/readings?player_id=p-rita&limit=1", headers=marshal)).json()
        self.assertEqual(len(page["readings"]), 1)
        rest = (await self.client.get(base + f"/chrono/readings?after={page['next']}", headers=marshal)).json()
        self.assertEqual(len(rest["readings"]), 1)
        one = page["readings"][0]
        self.assertEqual(one["public_key"], self.ana.public)
        chrono.parse(one["record_json"], base64.b64decode(one["public_key"]))
        game = (await self.fetch("SELECT id FROM games"))[0][0]
        self.assertEqual(one["game"], str(game))
        replicas = (await self.client.get(base + "/replicas?owner_player_id=p-rita", headers=marshal)).json()
        self.assertEqual([(r["type"], r["tag_uid"]) for r in replicas], [("sniper", "ATL-0001")])
        # A marshal of one game only does not see the field's registry.
        _, name, secret = await self.make_user(with_totp=True)
        r = await self.client.put(f"/api/v1/games/{game}/roles", json={"username": name, "role": "marshal"},
                                  headers=self._admin)
        self.assertEqual(r.status_code, 201)
        game_marshal = await self.auth(name, secret=secret)
        self.assertEqual((await self.client.get(base + "/chrono/readings", headers=game_marshal)).status_code, 403)

    async def test_metrics(self) -> None:
        body = (await self.client.get("/api/v1/metrics", headers=await self.admin_headers())).json()
        self.assertEqual((body["chrono_readings_total"], body["chrono_rejects_total"]), (2, 0))


class SharingTests(ChronoCase):
    """Cross-field history: only through an account that holds both fields' ids, both fields sharing,
    and the person's consent for both (ADR-P4-5, P4R15). Per-field ids are never matched."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.other_field, self.other_key = await self.make_field("arena")
        self.ana = Marshal()
        await self.marshals(self.ana.entry(), key=self.other_key)
        self.record = self.ana.record(player="p-arena1")
        await self.chrono(reading(self.record), key=self.other_key)
        self.user_id, name, _ = await self.make_user()
        self.person = await self.auth(name)
        await self.link(self.user_id, "p-campo1")
        await self.link(self.user_id, "p-arena1", self.other_field)
        self.gm = await self.staff("gm")

    async def shared(self) -> list[dict[str, Any]]:
        r = await self.client.get(f"/api/v1/fields/{self.field_id}/chrono/players/p-campo1", headers=self.gm)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["shared"]

    async def share(self, field_id: uuid.UUID, on: bool = True) -> None:
        async with self.app.state.sessionmaker() as db:
            field = await db.get(Field, field_id)
            field.chrono_sharing_enabled = on
            await db.commit()

    async def consent(self, field_id: uuid.UUID, give: bool = True) -> int:
        url = f"/api/v1/me/consents/chrono-sharing/{field_id}"
        r = await (self.client.put(url, headers=self.person) if give else self.client.delete(url, headers=self.person))
        return r.status_code

    async def test_both_fields_and_the_person(self) -> None:
        self.assertEqual(await self.shared(), [])
        await self.share(self.field_id)
        await self.share(self.other_field)
        self.assertEqual(await self.shared(), [])  # no consent yet
        self.assertEqual(await self.consent(self.other_field), 201)
        self.assertEqual(await self.consent(self.other_field), 200)  # once
        self.assertEqual(await self.shared(), [])  # not for this field
        self.assertEqual(await self.consent(self.field_id), 201)
        shared = await self.shared()
        self.assertEqual([s["reading_id"] for s in shared], [self.record["reading_id"]])
        self.assertEqual((shared[0]["field"], shared[0]["public_key"]), ("Arena", self.ana.public))
        chrono.parse(shared[0]["record_json"], base64.b64decode(shared[0]["public_key"]))  # checkable here
        self.assertIn("chrono_shared_lookup", [r[0] for r in await self.fetch("SELECT action FROM audit_log")])
        # Withdrawn, or a field that stops sharing: nothing.
        self.assertEqual(await self.consent(self.other_field, give=False), 204)
        self.assertEqual(await self.shared(), [])
        self.assertEqual(await self.consent(self.other_field, give=False), 404)
        await self.consent(self.other_field)
        await self.share(self.other_field, on=False)
        self.assertEqual(await self.shared(), [])
        consents = (await self.client.get("/api/v1/me/data", headers=self.person)).json()["consents"]
        self.assertEqual(sorted((c["purpose"], c["field_id"] is not None, c["withdrawn_at"] is None) for c in consents),
                         [("chrono_sharing", True, False), ("chrono_sharing", True, True),
                          ("chrono_sharing", True, True)])

    async def roster_game(self) -> uuid.UUID:
        """A published scheduled game at this field: the person registered with their id here (a valid
        player id: the sync's format is strict), a guest with no account, and one who cancelled."""
        now = datetime.datetime.now(datetime.timezone.utc)
        async with self.app.state.sessionmaker() as db:
            game = ScheduledGame(field_id=self.field_id, title="Domingo", status="published",
                                 starts_at=now + datetime.timedelta(hours=48), ends_at=now + datetime.timedelta(hours=52))
            db.add(game)
            await db.flush()
            for pid, user, name, status in ((self.mine, self.user_id, "Ana", "registered"),
                                            ("p-guestaaaaaaa", None, "Visitante", "registered"),
                                            ("p-gaveupaaaaaa", None, "Desistente", "cancelled")):
                db.add(GameRegistration(scheduled_game=game.id, field_id=self.field_id, user_id=user, player_id=pid,
                                        display_name=name, status=status))
            db.add(FieldPlayerId(field_id=self.field_id, player_id="p-gaveupaaaaaa", user_id=self.user_id))
            await db.commit()
            return game.id

    async def pulled(self, game: uuid.UUID, key: Optional[str] = None, expect: int = 200) -> dict[str, Any]:
        r = await self.client.get(f"/api/v1/sync/chrono?scheduled_game_id={game}", headers=self.headers(key))
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    async def test_the_controller_pulls_for_the_roster_only(self) -> None:
        """S14-5: the same rules as the staff's lookup, for the players of one scheduled game's roster."""
        self.mine = "p-campoaaaaaaa"
        await self.link(self.user_id, self.mine)
        game = await self.roster_game()
        self.assertEqual((await self.client.get(f"/api/v1/sync/chrono?scheduled_game_id={game}")).status_code, 401)
        await self.pulled(uuid.uuid4(), expect=404)
        await self.pulled("nope", expect=400)  # type: ignore[arg-type]
        await self.pulled(game, self.other_key, expect=404)  # another field's game is not theirs
        answer = await self.pulled(game)
        self.assertEqual(answer, {"sync_version": 1, "scheduled_game_id": str(game), "players": []})  # no sharing
        await self.share(self.field_id)
        await self.share(self.other_field)
        await self.consent(self.other_field)
        self.assertEqual((await self.pulled(game))["players"], [])  # not for this field yet
        await self.consent(self.field_id)
        answer = await self.pulled(game)
        sync_format.ANSWERS["shared_chrono"](json.loads(json.dumps(answer)))
        # The person, once; not the guest, not the one who cancelled, not the id they hold but did not
        # register with (p-campo1): the roster is who the controller asked about.
        [player] = answer["players"]
        self.assertEqual(player["player_id"], self.mine)
        [shared] = player["readings"]
        self.assertEqual((shared["field"], shared["record"], shared["public_key"]),
                         ("Arena", json.dumps(self.record, ensure_ascii=False), self.ana.public))
        chrono.parse(shared["record"], base64.b64decode(shared["public_key"]))  # the controller can check it
        logged = await self.fetch("SELECT details FROM audit_log WHERE action = 'chrono_shared_pull'")
        self.assertEqual([json.loads(r[0]) if isinstance(r[0], str) else r[0] for r in logged],
                         [{"players": 1, "readings": 1}])  # a count, not the player
        self.assertNotIn(self.mine, json.dumps([tuple(r) for r in logged], default=str))
        # Withdrawn for either field, or a field that stops sharing: nothing.
        await self.consent(self.field_id, give=False)
        self.assertEqual((await self.pulled(game))["players"], [])
        await self.consent(self.field_id)
        await self.consent(self.other_field, give=False)
        self.assertEqual((await self.pulled(game))["players"], [])
        await self.consent(self.other_field)
        self.assertEqual(len((await self.pulled(game))["players"]), 1)
        await self.share(self.other_field, on=False)
        self.assertEqual((await self.pulled(game))["players"], [])
        await self.share(self.other_field)
        await self.share(self.field_id, on=False)  # this field must share too
        self.assertEqual((await self.pulled(game))["players"], [])

    async def test_a_single_field_server_has_no_hub_link(self) -> None:
        """SVX-2: the hub-level sharing is hosted mode's; here the account's own links do it."""
        for method, path, body in (("GET", "", None), ("POST", "/code", None), ("POST", "/link", {"code": "ABCD"}),
                                   ("DELETE", "", None)):
            with self.subTest(method=method, path=path):
                r = await self.client.request(method, f"/api/v1/me/hub-share{path}", json=body, headers=self.person)
                self.assertEqual((r.status_code, r.json()["detail"]), (404, "not_hosted") if method != "DELETE"
                                 else (404, "not_hosted"))

    async def test_the_fields_admin_switches_sharing(self) -> None:
        url = f"/api/v1/fields/{self.field_id}"
        r = await self.client.patch(url, json={"chrono_sharing_enabled": True}, headers=self.gm)
        self.assertEqual(r.status_code, 403)
        r = await self.client.patch(url, json={"chrono_sharing_enabled": True}, headers=self._admin)
        self.assertEqual((r.status_code, r.json()["chrono_sharing_enabled"]), (200, True))
        r = await self.client.patch(url, json={"name": "x"}, headers=self._admin)
        self.assertEqual(r.status_code, 422)
        self.assertIn("field_update", [r[0] for r in await self.fetch("SELECT action FROM audit_log")])


class PersonalDataTests(ChronoCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.ana = Marshal()
        await self.marshals(self.ana.entry())
        await self.post("replicas", field_body(replicas=[{"replica_id": REPLICA, "owner_player_id": "p-rita",
                                                          "type": "aeg", "class": "rifle", "make_model": "M4 CQB",
                                                          "tag_type": "nfc", "tag_uid": "04:A2:B3:C4"}]))
        self.records = [self.ana.record(v, rtype="spotcheck") for v in (100.0, 115.0)]
        await self.chrono(*[reading(r, outcome="fail") for r in self.records])
        self.user_id, self.name, _ = await self.make_user()
        self.person = await self.auth(self.name)
        await self.link(self.user_id, "p-rita")

    async def test_access_and_export(self) -> None:
        mine = (await self.client.get("/api/v1/me/chrono", headers=self.person)).json()["fields"]
        self.assertEqual(len(mine), 1)
        self.assertEqual({r["reading_id"] for r in mine[0]["readings"]}, {r["reading_id"] for r in self.records})
        self.assertEqual([r["make_model"] for r in mine[0]["replicas"]], ["M4 CQB"])
        self.assertEqual([v["violation_type"] for v in mine[0]["violations"]], ["over_limit"])
        data = (await self.client.get("/api/v1/me/data", headers=self.person)).json()
        self.assertEqual([p["player_id"] for p in data["player_ids"]], ["p-rita"])
        self.assertEqual(data["chrono_records"], mine)
        r = await self.client.get("/api/v1/me/export", headers=self.person)
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            self.assertEqual(json.loads(zf.read("export/chrono_records.json")), mine)
            self.assertEqual(json.loads(zf.read("export/player_ids.json")), data["player_ids"])
        # Someone else's history is not in it.
        other_id, other, _ = await self.make_user()
        self.assertEqual((await self.client.get("/api/v1/me/chrono", headers=await self.auth(other))).json(),
                         {"fields": []})

    async def test_a_marshals_keys(self) -> None:
        url = f"/api/v1/fields/{self.field_id}/marshal-keys"
        uid, name, secret = await self.make_user(with_totp=True)
        r = await self.client.put(f"/api/v1/fields/{self.field_id}/roles", json={"username": name, "role": "marshal"},
                                  headers=await self.admin_headers())
        self.assertEqual(r.status_code, 201)
        marshal = await self.auth(name, secret=secret)
        r = await self.client.post(url, json={"marshal_id": "m-ana", "name": "Ana", "public_key": self.ana.public},
                                   headers=marshal)
        self.assertEqual(r.status_code, 200, r.text)  # the controller's key, claimed
        data = (await self.client.get("/api/v1/me/data", headers=marshal)).json()
        self.assertEqual([k["public_key"] for k in data["marshal_keys"]], [self.ana.public])
        r = await self.client.request("DELETE", "/api/v1/me", headers=marshal,
                                      json={"password": "correct horse battery staple 42", "code": self.code(secret)})
        self.assertEqual(r.status_code, 204, r.text)
        row = (await self.fetch("SELECT user_id, public_key FROM marshal_keys"))[0]
        self.assertIsNone(row["user_id"])  # unlinked, kept: what it signed still verifies
        for rec in await self.fetch("SELECT record_json FROM chrono_readings"):
            chrono.parse(rec[0], bytes(row["public_key"]))

    async def test_erasure_keeps_the_record_and_drops_the_link(self) -> None:
        before = {r["reading_id"]: r["record_json"] for r in await self.fetch(
            "SELECT reading_id, record_json FROM chrono_readings")}
        r = await self.client.request("DELETE", "/api/v1/me", headers=self.person,
                                      json={"password": "correct horse battery staple 42"})
        self.assertEqual(r.status_code, 204, r.text)
        after = {r["reading_id"]: r["record_json"] for r in await self.fetch(
            "SELECT reading_id, record_json FROM chrono_readings")}
        self.assertEqual(after, before)  # verbatim, signatures intact
        for text in after.values():
            chrono.parse(text, base64.b64decode(self.ana.public))
        self.assertEqual(await self.count("field_player_ids"), 0)
        self.assertEqual(await self.count("chrono_violations"), 1)
        replica = (await self.fetch("SELECT owner_player_id, make_model, tag_type, tag_uid, replica_class "
                                    "FROM replicas"))[0]
        self.assertEqual(tuple(replica), ("p-rita", None, None, None, "rifle"))

    async def test_the_purge(self) -> None:
        now = datetime.datetime.now(datetime.timezone.utc)
        old = Marshal("m-old", "Velho")
        long_ago = (now - datetime.timedelta(days=400)).timestamp()
        await self.marshals(old.entry(long_ago - 100, long_ago + 10))
        await self.post("replicas", field_body(replicas=[{"replica_id": str(uuid.uuid4()), "owner_player_id": "p-x",
                                                          "type": "gbb", "class": "pistol"}]))
        stale = old.record(at=long_ago, player="p-x")
        self.assertEqual((await self.chrono(reading(stale, received=long_ago + 5)))["accepted"], 1)
        await self.fetch("UPDATE replicas SET updated_at = now() - interval '400 days' WHERE owner_player_id = 'p-x'")
        await self.fetch("INSERT INTO chrono_rejects (field_id, record_text, record_sha256, reason, detail, "
                         "first_seen_at) VALUES ($1, '{}', 'x', 'format', 'x', now() - interval '366 days')",
                         self.field_id)
        async with self.app.state.sessionmaker() as db:
            counts = await personal_data.purge(db, now)
        self.assertEqual({k: counts[k] for k in ("chrono_readings", "chrono_rejects", "replicas", "marshal_keys")},
                         {"chrono_readings": 1, "chrono_rejects": 1, "replicas": 1, "marshal_keys": 1})
        self.assertEqual(await self.count("chrono_readings"), 2)  # this year's stay
        self.assertEqual([r[0] for r in await self.fetch("SELECT marshal_id FROM marshal_keys")], ["m-ana"])
        # A field with a longer retention keeps its records longer.
        await self.fetch("UPDATE fields SET default_retention_days = 3650")
        await self.marshals(old.entry(long_ago - 100, long_ago + 10))
        await self.chrono(reading(old.record(at=long_ago, player="p-x"), received=long_ago + 5))
        async with self.app.state.sessionmaker() as db:
            self.assertEqual((await personal_data.purge(db, now))["chrono_readings"], 0)


class FieldErasureTests(ChronoCase):
    async def test_the_fields_admin_erases_a_players_chrono_data(self) -> None:
        """A player asks the field to delete their chrono records: the site server's copy goes too."""
        ana = Marshal()
        await self.marshals(ana.entry())
        await self.post("replicas", field_body(replicas=[{"replica_id": REPLICA, "owner_player_id": "p-rita",
                                                          "type": "aeg", "class": "rifle"}]))
        await self.chrono(*[reading(ana.record(v, rtype="spotcheck"), outcome="fail") for v in (100.0, 120.0)])
        await self.chrono(reading(ana.record(player="p-bea")))
        url = f"/api/v1/fields/{self.field_id}/chrono/players/p-rita"
        gm = await self.staff("gm")
        self.assertEqual((await self.client.delete(url, headers=gm)).status_code, 403)
        r = await self.client.delete(url, headers=self._admin)
        self.assertEqual(r.json(), {"chrono_readings": 2, "chrono_rejects": 0, "replicas": 1})
        self.assertEqual([r[0] for r in await self.fetch("SELECT player_id FROM chrono_readings")], ["p-bea"])
        self.assertEqual(await self.count("chrono_violations"), 0)
        logged = await self.fetch("SELECT details FROM audit_log WHERE action = 'chrono_player_erasure'")
        self.assertNotIn("p-rita", logged[0][0])


class GameLinkTests(ChronoCase):
    async def test_a_reading_names_its_game_when_the_site_server_has_it(self) -> None:
        ana = Marshal()
        await self.marshals(ana.entry())
        unknown = ana.record(game_id="77")
        known = ana.record(game_id=str(GAME["game_id"]))
        gid = await self.make_game()
        await self.chrono(reading(unknown, game_seed=5), reading(known, game_seed=GAME["game_seed"]),
                          reading(ana.record(game_id=str(GAME["game_id"]))))  # no seed: no link
        rows = {str(r["reading_id"]): r["game"] for r in await self.fetch("SELECT reading_id, game FROM chrono_readings")}
        self.assertEqual(rows[known["reading_id"]], uuid.UUID(gid))
        self.assertIsNone(rows[unknown["reading_id"]])
        self.assertEqual(sum(1 for g in rows.values() if g is None), 2)
        # The game goes (its history retention): the reading stays.
        await self.fetch("DELETE FROM games")
        self.assertEqual(await self.count("chrono_readings"), 3)


class StreamTests(ChronoCase):
    async def test_the_registry_on_the_stream(self) -> None:
        """The WebSocket takes the same bodies (plan phase 13's stream, S13-8)."""
        from atalaia_server.api import sync as sync_api

        ana = Marshal()
        caller = sync_api.sync.Caller(field_id=self.field_id, key_id=(await self.fetch(
            "SELECT id FROM field_api_keys"))[0][0])

        class FakeSocket:
            app = self.app

            async def close(self, code: int) -> None:
                raise AssertionError(code)

        ws = FakeSocket()
        answer = await sync_api._message(ws, caller, json.dumps({"type": "marshals", **field_body(
            marshals=[ana.entry()])}))
        self.assertEqual(answer["type"], "marshals.ack")
        answer = await sync_api._message(ws, caller, json.dumps({"type": "chrono", **field_body(
            readings=[reading(ana.record())])}))
        self.assertEqual((answer["type"], answer["accepted"]), ("chrono.ack", 1))
