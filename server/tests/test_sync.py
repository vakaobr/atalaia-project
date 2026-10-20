# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The controller sync's endpoints on PostgreSQL 16 (ADR-P4-3 as amended, protocol/sync.md).

API keys (SHA-256 only, two live during a rotation), the batches (replays,
duplicates, out-of-order batches, a standby controller's copy), the score
merge with a negative GM adjustment (P4R10), game identity (P4R11), the
shared vectors, per-game roles and the games API.
"""

from __future__ import annotations

import copy
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any, Optional

from atalaia_server import sync
from atalaia_server.models import Field, FieldApiKey

from .base import AppTestCase

REPO = Path(__file__).resolve().parents[2]
VECTORS = json.loads((REPO / "protocol" / "vectors" / "sync.json").read_text(encoding="utf-8"))
CONTROLLER = "0192f3a4-5b6c-7d8e-9f01-23456789abcd"
STANDBY = "0192f3a4-5b6c-7d8e-9f01-000000000007"
GAME = {"game_id": 4242, "game_seed": 3735928559}
META = {"name": "Domingo", "mode_id": "org.atalaia.domination", "teams": ["red", "blue"], "state": "running",
        "created_at": 1792000000.0, "started_at": 1792000100.0}


def envelope(controller: str = CONTROLLER, game: Optional[dict[str, int]] = None, **body: Any) -> dict[str, Any]:
    return {"sync_version": 1, "controller": {"id": controller, "version": "0.1.0"}, "game": dict(game or GAME), **body}


def event(eid: int, node: int = 3, seq: Optional[int] = None, t: Optional[int] = None, etype: str = "zone.captured",
          team: Optional[str] = "red", data: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    return {"id": eid, "node": node, "seq": eid if seq is None else seq, "t": eid * 1000 if t is None else t,
            "type": etype, "team": team, "prio": "normal", "data": data if data is not None else {"zone": "alpha"}}


def adjustment(eid: int, team: str, amount: int, seq: Optional[int] = None) -> dict[str, Any]:
    return event(eid, node=0, seq=seq, etype="score.delta", team=team,
                 data={"team": team, "amount": amount, "reason": "gm"})


class SyncTestCase(AppTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.field_id, self.key = await self.make_field("campo")

    async def make_field(self, slug: str) -> tuple[uuid.UUID, str]:
        """A field and one live API key, written straight to the database."""
        key = sync.new_key()
        async with self.app.state.sessionmaker() as db:
            field = Field(name=slug.title(), slug=slug)
            db.add(field)
            await db.flush()
            db.add(FieldApiKey(field_id=field.id, key_sha256=sync.key_hash(key)))
            await db.commit()
            return field.id, key

    def headers(self, key: Optional[str] = None) -> dict[str, str]:
        return {"Authorization": f"Bearer {key or self.key}"}

    async def post(self, kind: str, body: Any, key: Optional[str] = None, expect: int = 200) -> dict[str, Any]:
        r = await self.client.post(f"/api/v1/sync/{kind}", json=body, headers=self.headers(key))
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    async def make_game(self, key: Optional[str] = None, game: Optional[dict[str, int]] = None,
                        controller: str = CONTROLLER, **meta: Any) -> str:
        answer = await self.post("games", envelope(controller, game, meta={**META, **meta}), key)
        return answer["game"]

    async def events(self, events: list[dict[str, Any]], after: int = 0, controller: str = CONTROLLER,
                     key: Optional[str] = None, expect: int = 200) -> dict[str, Any]:
        return await self.post("events", envelope(controller, after_id=after, events=events), key, expect)

    async def game_rows(self) -> list[Any]:
        return await self.fetch("SELECT * FROM games ORDER BY created_at")

    async def count(self, table: str) -> int:
        return (await self.fetch(f"SELECT count(*) FROM {table}"))[0][0]

    async def admin_headers(self) -> dict[str, str]:
        _, name, secret = await self.make_user(server_admin=True)
        return await self.auth(name, secret=secret)


class ApiKeyTests(SyncTestCase):
    async def test_a_key_is_needed(self) -> None:
        body = envelope(meta=META)
        for headers, why in (({}, "missing"), ({"Authorization": "Bearer " + "A" * 43}, "wrong"),
                             ({"Authorization": f"Basic {self.key}"}, "not bearer"),
                             ({"Authorization": "Bearer " + self.key[:-1]}, "truncated")):
            with self.subTest(why=why):
                r = await self.client.post("/api/v1/sync/games", json=body, headers=headers)
                self.assertEqual((r.status_code, r.json()), (401, {"detail": "invalid_api_key"}))
        self.assertEqual(await self.count("games"), 0)
        await self.make_game()
        self.assertEqual(await self.count("games"), 1)

    async def test_only_the_hash_is_kept(self) -> None:
        rows = await self.fetch("SELECT key_sha256, last_used_at FROM field_api_keys")
        self.assertEqual(rows[0]["key_sha256"], hashlib.sha256(self.key.encode()).hexdigest())
        self.assertIsNone(rows[0]["last_used_at"])
        await self.make_game()
        rows = await self.fetch("SELECT key_sha256, last_used_at FROM field_api_keys")
        self.assertIsNotNone(rows[0]["last_used_at"])
        dump = json.dumps([dict(r) for r in await self.fetch("SELECT * FROM field_api_keys")], default=str)
        self.assertNotIn(self.key, dump)

    async def test_rotation_through_the_api(self) -> None:
        admin = await self.admin_headers()
        url = f"/api/v1/fields/{self.field_id}/sync-keys"
        r = await self.client.post(url, json={"label": "novo Pi"}, headers=admin)
        self.assertEqual(r.status_code, 201, r.text)
        new = r.json()
        self.assertEqual(len(new["key"]), 43)
        self.assertEqual(new["fingerprint"], hashlib.sha256(new["key"].encode()).hexdigest()[:8])
        # Two live keys: both work while the new one is installed; a third is refused.
        await self.make_game(key=self.key)
        await self.make_game(key=new["key"], game={"game_id": 1, "game_seed": 1})
        r = await self.client.post(url, headers=admin)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "too_many_keys"))
        listed = (await self.client.get(url, headers=admin)).json()
        self.assertEqual(len(listed), 2)
        self.assertNotIn("key", listed[0])
        self.assertNotIn(new["key"], json.dumps(listed))
        old = next(k for k in listed if k["id"] != new["id"])
        r = await self.client.delete(f"{url}/{old['id']}", headers=admin)
        self.assertEqual(r.status_code, 204)
        await self.post("games", envelope(meta=META), key=self.key, expect=401)
        await self.make_game(key=new["key"])
        r = await self.client.delete(f"{url}/{old['id']}", headers=admin)
        self.assertEqual(r.status_code, 404)  # already revoked
        actions = [r["action"] for r in await self.fetch("SELECT action FROM audit_log ORDER BY id")
                   if r["action"].startswith("sync_key")]
        self.assertEqual(actions, ["sync_key_create", "sync_key_revoke"])
        details = json.dumps([r["details"] for r in await self.fetch("SELECT details FROM audit_log")])
        self.assertNotIn(new["key"], details)

    async def test_only_the_fields_admin_manages_keys(self) -> None:
        url = f"/api/v1/fields/{self.field_id}/sync-keys"
        _, gm_name, gm_secret = await self.make_user(with_totp=True)
        admin = await self.admin_headers()
        r = await self.client.put(f"/api/v1/fields/{self.field_id}/roles", json={"username": gm_name, "role": "gm"},
                                  headers=admin)
        self.assertEqual(r.status_code, 201, r.text)
        gm = await self.auth(gm_name, secret=gm_secret)
        for method in ("post", "get"):
            r = await getattr(self.client, method)(url, headers=gm)
            self.assertEqual(r.status_code, 403, method)
        r = await self.client.get(url)
        self.assertEqual(r.status_code, 401)

    async def test_a_key_is_for_its_field_only(self) -> None:
        """The same (game_id, game_seed) under another field's key is another field's game."""
        other_field, other_key = await self.make_field("arena")
        a = await self.make_game()
        b = await self.make_game(key=other_key)
        self.assertNotEqual(a, b)
        rows = await self.game_rows()
        self.assertEqual({r["field_id"] for r in rows}, {self.field_id, other_field})


class EventBatchTests(SyncTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.game = await self.make_game()

    async def test_a_batch_and_the_same_batch_again(self) -> None:
        batch = [event(i) for i in range(1, 6)]
        self.assertEqual(await self.events(batch), {"acked_id": 5, "inserted": 5, "duplicates": 0})
        self.assertEqual(await self.events(batch), {"acked_id": 5, "inserted": 0, "duplicates": 5})
        self.assertEqual(await self.count("game_events"), 5)

    async def test_out_of_order_and_overlapping_batches(self) -> None:
        """A later batch first, then an earlier one, then one that overlaps both: the same log."""
        self.assertEqual((await self.events([event(i) for i in range(6, 11)], after=5))["inserted"], 5)
        self.assertEqual((await self.events([event(i) for i in range(1, 6)]))["inserted"], 5)
        answer = await self.events([event(i) for i in range(4, 13)], after=3)
        self.assertEqual(answer, {"acked_id": 12, "inserted": 2, "duplicates": 7})
        rows = await self.fetch("SELECT seq FROM game_events ORDER BY game_time_ms")
        self.assertEqual([r[0] for r in rows], list(range(1, 13)))

    async def test_the_key_is_the_controllers(self) -> None:
        """A box that rebooted restarts its seq at 1: same seq, other game time, a new event."""
        await self.events([event(1, seq=1, t=1000)])
        answer = await self.events([event(2, seq=1, t=90_000)], after=1)
        self.assertEqual(answer["inserted"], 1)
        # The same event twice in one batch (a merged standby log) is one row.
        answer = await self.events([event(3, seq=5, t=5000), event(4, seq=5, t=5000)], after=2)
        self.assertEqual((answer["inserted"], answer["duplicates"]), (1, 1))

    async def test_a_standby_controllers_copy_lands_in_the_same_game(self) -> None:
        """The standby has its own controller id and its own event ids; the events are the same."""
        await self.events([event(i) for i in range(1, 4)])
        await self.make_game(controller=STANDBY, joined=True, node_id=7)
        copy_ = [{**event(i), "id": 100 + i} for i in range(1, 5)]  # one more than the primary sent
        answer = await self.events(copy_, after=100, controller=STANDBY)
        self.assertEqual(answer, {"acked_id": 104, "inserted": 1, "duplicates": 3})
        self.assertEqual(await self.count("games"), 1)
        self.assertEqual({r[0] for r in await self.fetch("SELECT controller_id FROM controllers")},
                         {uuid.UUID(CONTROLLER), uuid.UUID(STANDBY)})

    async def test_events_need_their_game(self) -> None:
        r = await self.client.post("/api/v1/sync/events", headers=self.headers(), json=envelope(
            game={"game_id": 9, "game_seed": 9}, after_id=0, events=[event(1)]))
        self.assertEqual((r.status_code, r.json()), (404, {"detail": "game_not_found"}))

    async def test_a_bad_batch_stores_nothing(self) -> None:
        batch = [event(1), event(2, data={"zone": "alpha", "lat": 38.7})]
        r = await self.client.post("/api/v1/sync/events", headers=self.headers(),
                                   json=envelope(after_id=0, events=batch))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json(), {"detail": "invalid_body", "error": "position_not_allowed",
                                    "path": "events[1].data.lat"})
        self.assertEqual(await self.count("game_events"), 0)
        r = await self.client.post("/api/v1/sync/events", headers={**self.headers(), "Content-Type": "application/json"},
                                   content=b"{not json")
        self.assertEqual(r.json()["error"], "not_json")
        r = await self.client.post("/api/v1/sync/events", headers=self.headers(),
                                   content=b"x" * (1024 * 1024 + 1))
        self.assertEqual((r.status_code, r.json()["detail"]), (413, "body_too_large"))

    async def test_game_end_event_ends_the_game(self) -> None:
        await self.events([event(1, node=0, etype="game.end", team=None, data={"winner": "red"})])
        self.assertEqual((await self.game_rows())[0]["state"], "ended")


class ScoreTests(SyncTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.game = await self.make_game()

    async def scores(self, counters: dict[str, dict[str, int]], expect: int = 200, **kw: Any) -> dict[str, Any]:
        return await self.post("scores", envelope(counters=counters, **kw), expect=expect)

    async def game_view(self) -> dict[str, Any]:
        r = await self.client.get(f"/api/v1/games/{self.game}", headers=await self.admin_headers())
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    async def test_a_negative_adjustment_lowers_the_total(self) -> None:
        self.assertEqual((await self.scores({"node-3": {"red": 100}, "node-4": {"blue": 60}}))["totals"],
                         {"red": 100, "blue": 60})
        await self.events([adjustment(1, "red", -50), adjustment(2, "blue", 10)])
        answer = await self.scores({"node-3": {"red": 100}})
        self.assertEqual(answer, {"totals": {"red": 50, "blue": 70}, "updated": 0})
        # Replaying the adjustment does not apply it twice.
        await self.events([adjustment(1, "red", -50)])
        self.assertEqual((await self.game_view())["totals"], {"red": 50, "blue": 70})

    async def test_counters_merge_by_maximum(self) -> None:
        await self.scores({"node-3": {"red": 40}})
        answer = await self.scores({"node-3": {"red": 25, "blue": 5}})  # an older, late snapshot
        self.assertEqual(answer, {"totals": {"red": 40, "blue": 5}, "updated": 1})
        rows = await self.fetch("SELECT source, team, value FROM game_node_scores ORDER BY team")
        self.assertEqual([tuple(r) for r in rows], [("node-3", "blue", 5), ("node-3", "red", 40)])

    async def test_the_merge_vectors(self) -> None:
        for i, case in enumerate(VECTORS["merge"]):
            with self.subTest(case=case["name"]):
                game = {"game_id": 100 + i, "game_seed": 7}
                gid = await self.make_game(game=game, teams=case["teams"])
                for snapshot in case["snapshots"]:
                    await self.post("scores", envelope(game=game, counters=snapshot))
                if case["deltas"]:
                    await self.post("events", envelope(game=game, after_id=0, events=[
                        adjustment(n + 1, team, amount) for n, (team, amount) in enumerate(case["deltas"])]))
                r = await self.client.get(f"/api/v1/games/{gid}", headers=await self.admin_headers())
                self.assertEqual(r.json()["counters"], case["counters"])
                self.assertEqual(r.json()["totals"], case["totals"])

    async def test_refusals(self) -> None:
        r = await self.client.post("/api/v1/sync/scores", headers=self.headers(),
                                   json=envelope(counters={"node-3": {"green": 5}}))
        self.assertEqual(r.json(), {"detail": "invalid_body", "error": "unknown_team", "path": "counters.node-3.green"})
        await self.post("scores", envelope(game={"game_id": 1, "game_seed": 2}, counters={}), expect=404)


class GameIdentityTests(SyncTestCase):
    async def test_a_reused_game_id_is_a_new_game(self) -> None:
        """The 16-bit game_id comes round again months later, with another seed (P4R11)."""
        a = await self.make_game(game={"game_id": 7, "game_seed": 1111})
        b = await self.make_game(game={"game_id": 7, "game_seed": 2222})
        self.assertNotEqual(a, b)
        self.assertEqual(await self.make_game(game={"game_id": 7, "game_seed": 1111}), a)

    async def test_created_once_then_updated(self) -> None:
        first = await self.post("games", envelope(meta={**META, "state": "ready"}))
        self.assertTrue(first["created"])
        again = await self.post("games", envelope(meta={**META, "name": "Domingo 2"}))
        self.assertEqual((again["game"], again["created"], again["state"]), (first["game"], False, "running"))
        self.assertEqual((await self.game_rows())[0]["name"], "Domingo 2")

    async def test_the_state_only_moves_forward(self) -> None:
        for sent, kept in (("ready", "ready"), ("running", "running"), ("ready", "running"), ("paused", "paused"),
                           ("running", "running"), ("ended", "ended"), ("running", "ended"), ("ready", "ended")):
            with self.subTest(sent=sent):
                answer = await self.post("games", envelope(meta={**META, "state": sent, "ended_at": None}))
                self.assertEqual(answer["state"], kept)

    async def test_times_merge(self) -> None:
        await self.make_game(started_at=1792000200.0, ended_at=1792003000.0, state="ended")
        await self.make_game(controller=STANDBY, started_at=1792000100.0, ended_at=1792002000.0, state="ended")
        row = (await self.game_rows())[0]
        self.assertEqual((row["started_at"].timestamp(), row["ended_at"].timestamp()), (1792000100.0, 1792003000.0))

    async def test_a_standby_that_leaves_does_not_end_the_game(self) -> None:
        await self.make_game()
        answer = await self.post("games", envelope(STANDBY, meta={**META, "joined": True, "state": "ended",
                                                                  "ended_at": 1792001000.0}))
        self.assertEqual(answer["state"], "running")
        self.assertIsNone((await self.game_rows())[0]["ended_at"])
        await self.post("games", envelope(meta={**META, "state": "ended", "ended_at": 1792002000.0}))
        self.assertEqual((await self.game_rows())[0]["state"], "ended")


class NodeTests(SyncTestCase):
    async def test_the_latest_report_wins_and_only_listed_info_is_kept(self) -> None:
        gid = await self.make_game()
        node = {"node_id": 3, "name": "node-3", "role": "zone", "last_seen": 1792000500.0,
                "info": {"battery_pct": 70, "owner": "red", "note": "dropped"}}
        await self.post("nodes", envelope(nodes=[node]))
        await self.post("nodes", envelope(STANDBY, nodes=[{**node, "last_seen": 1792000400.0,
                                                           "info": {"battery_pct": 90}}]))
        rows = await self.fetch("SELECT game, info, last_seen_at FROM game_nodes")
        self.assertEqual(json.loads(rows[0]["info"]), {"battery_pct": 70, "owner": "red"})
        self.assertEqual(str(rows[0]["game"]), gid)


class VectorTests(SyncTestCase):
    """Every shared vector through the HTTP endpoints: the same verdicts as the controller's checks."""

    async def test_valid_bodies_are_accepted(self) -> None:
        for vector in VECTORS["valid"]:
            with self.subTest(vector=vector["name"]):
                body = copy.deepcopy(vector["body"])
                if vector["kind"] in ("events", "scores", "nodes", "checkins"):
                    await self.post("games", envelope(game=body["game"], meta=META))
                answer = await self.post(vector["kind"], body)
                if vector["kind"] == "chrono":  # its records verify with the marshals vector's key
                    self.assertEqual((answer["accepted"], answer["refused"]), (len(body["readings"]), []))
        nodes = await self.fetch("SELECT node_id, info FROM game_nodes")
        want = next(v for v in VECTORS["valid"] if v["name"] == "nodes_unknown_info_dropped")["info"]
        self.assertEqual({str(r["node_id"]): json.loads(r["info"]) for r in nodes}, want)

    async def test_invalid_bodies_are_refused(self) -> None:
        await self.post("games", envelope(meta=META))
        for vector in VECTORS["invalid"]:
            with self.subTest(vector=vector["name"]):
                r = await self.client.post(f"/api/v1/sync/{vector['kind']}", json=vector["body"],
                                           headers=self.headers())
                self.assertEqual(r.status_code, 400, r.text)
                self.assertEqual(r.json(), {"detail": "invalid_body", "error": vector["error"],
                                            "path": vector["path"]})
        self.assertEqual(await self.count("game_events"), 0)
        self.assertEqual(await self.count("game_node_scores"), 0)
        for table in ("marshal_keys", "replicas", "chrono_readings", "chrono_rejects", "field_player_ids"):
            self.assertEqual(await self.count(table), 0, table)


class GamesApiTests(SyncTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.game = await self.make_game(params={"arming_code": "4711"})
        await self.events([event(1), adjustment(2, "red", -5)])
        self.admin = await self.admin_headers()

    async def user_with(self, role: Optional[str] = None, on: str = "field",
                        with_totp: bool = False) -> dict[str, str]:
        _, name, secret = await self.make_user(with_totp=with_totp)
        if role:
            url = (f"/api/v1/fields/{self.field_id}/roles" if on == "field" else f"/api/v1/games/{self.game}/roles")
            r = await self.client.put(url, json={"username": name, "role": role}, headers=self.admin)
            self.assertEqual(r.status_code, 201, r.text)
        return await self.auth(name, secret=secret)

    async def test_who_sees_what(self) -> None:
        nobody = await self.user_with()
        player = await self.user_with("player")
        gm = await self.user_with("gm", with_totp=True)
        r = await self.client.get(f"/api/v1/fields/{self.field_id}/games", headers=nobody)
        self.assertEqual(r.status_code, 403)
        listed = (await self.client.get(f"/api/v1/fields/{self.field_id}/games", headers=player)).json()
        self.assertEqual([g["id"] for g in listed], [self.game])
        seen = (await self.client.get(f"/api/v1/games/{self.game}", headers=player)).json()
        self.assertNotIn("params", seen)  # a Bomb's codes are the GM's
        self.assertEqual(seen["totals"], {"red": -5, "blue": 0})
        self.assertEqual((await self.client.get(f"/api/v1/games/{self.game}", headers=gm)).json()["params"],
                         {"arming_code": "4711"})
        r = await self.client.get(f"/api/v1/games/{self.game}/events", headers=player)
        self.assertEqual(r.status_code, 403)
        events = (await self.client.get(f"/api/v1/games/{self.game}/events", headers=gm)).json()
        self.assertEqual([e["type"] for e in events["events"]], ["zone.captured", "score.delta"])
        page = (await self.client.get(f"/api/v1/games/{self.game}/events?after=0&limit=1", headers=gm)).json()
        self.assertEqual(len(page["events"]), 1)
        self.assertEqual(page["next"], page["events"][0]["id"])

    async def test_per_game_roles(self) -> None:
        marshal = await self.user_with("marshal", on="game", with_totp=True)
        self.assertEqual((await self.client.get(f"/api/v1/games/{self.game}/events", headers=marshal)).status_code,
                         200)
        r = await self.client.get(f"/api/v1/fields/{self.field_id}/games", headers=marshal)
        self.assertEqual(r.status_code, 403)  # a role on one game is not a role on the field
        _, name, _ = await self.make_user()
        r = await self.client.put(f"/api/v1/games/{self.game}/roles", json={"username": name, "role": "marshal"},
                                  headers=self.admin)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "totp_required"))
        roles = (await self.client.get(f"/api/v1/games/{self.game}/roles", headers=self.admin)).json()
        self.assertEqual([r["role"] for r in roles], ["marshal"])
        r = await self.client.delete(f"/api/v1/games/{self.game}/roles/{roles[0]['user_id']}/marshal",
                                     headers=self.admin)
        self.assertEqual(r.status_code, 204)
        self.assertEqual((await self.client.get(f"/api/v1/games/{self.game}/events", headers=marshal)).status_code,
                         403)
        actions = [r["action"] for r in await self.fetch("SELECT action FROM audit_log WHERE action LIKE 'game_role%'")]
        self.assertEqual(actions, ["game_role_grant", "game_role_revoke"])

    async def test_metrics_count_the_sync(self) -> None:
        body = (await self.client.get("/api/v1/metrics", headers=self.admin)).json()
        self.assertEqual((body["games_total"], body["game_events_total"], body["controllers_total"]), (1, 2, 1))
