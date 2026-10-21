# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The site server sync client (ADR-P4-3 as amended, protocol/sync.md) against a small site server
in this process: no PostgreSQL (the real one: server/tests/test_sync_e2e.py).

The cursor, a replay after a restart or a lost answer, the backoff, the
offline-first rule (the game never waits for the network), refusals,
redirects, TLS with a pinned CA, the settings and the sync-key command, the
field's chrono registry (marshal keys with their periods, replicas, signed
readings; plan phase 14), and that nothing private is in any request body,
checked field by field.

    cd controller && python -m unittest discover -s tests
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import ssl
import tempfile
import threading
import unittest
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional

from support import CORE, config, wait_for

from p3support import GM, T0, Marshal, P3Case, bearer, declaration

from atalaia_controller import sync_format, tls as tlsmod
from atalaia_controller.config import ConfigError, load_config
from atalaia_controller.engine import Controller
from atalaia_controller.main import sync_key
from atalaia_controller.store import Store
from atalaia_controller.sync_client import SyncClient, api_key_ok, key_fingerprint, url_problem

KEY = "k" * 43
logging.getLogger("atalaia.sync").setLevel(logging.CRITICAL)  # the tests provoke its warnings
DOMINATION = "org.atalaia.domination"


class FakeSite:
    """A site server's sync endpoints in memory, with the real merge rules and switches for failures."""

    def __init__(self, tls_files: Optional[tuple[str, str]] = None) -> None:
        self.requests: list[tuple[str, dict[str, str], dict[str, Any]]] = []
        self.games: dict[tuple[int, int], dict[str, Any]] = {}
        self.events: dict[tuple[int, int], dict[tuple, dict[str, Any]]] = {}
        self.counters: dict[tuple[int, int], dict[str, dict[str, int]]] = {}
        self.fail: list[tuple[int, dict[str, Any], dict[str, str]]] = []  # answers to give first
        self.lose: Optional[str] = None  # store the next body of this kind, then answer 500 (a lost answer)
        self.redirect_to: Optional[str] = None
        self.reject: Optional[str] = None  # refuse the next body of this kind with a 400
        self.marshals: dict[tuple[str, str], dict[str, Any]] = {}
        self.replicas: dict[str, dict[str, Any]] = {}
        self.readings: list[dict[str, Any]] = []
        self.refuse_readings: set[str] = set()  # reading ids to answer as kept apart
        self.lock = threading.Lock()
        site = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def do_POST(self) -> None:  # noqa: N802
                raw = self.rfile.read(int(self.headers.get("content-length") or 0))
                status, answer, headers = site.handle(self.path, dict(self.headers), raw)
                data = json.dumps(answer).encode()
                self.send_response(status)
                for k, v in {"Content-Type": "application/json", "Content-Length": str(len(data)), **headers}.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        if tls_files:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(*tls_files)
            self.httpd.socket = ctx.wrap_socket(self.httpd.socket, server_side=True)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        scheme = "https" if tls_files else "http"
        host = "localhost" if tls_files else "127.0.0.1"
        self.url = f"{scheme}://{host}:{self.httpd.server_address[1]}"

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def handle(self, path: str, headers: dict[str, str], raw: bytes) -> tuple[int, dict[str, Any], dict[str, str]]:
        with self.lock:
            body = json.loads(raw)
            self.requests.append((path, headers, body))
            if self.redirect_to:
                return 307, {}, {"Location": self.redirect_to + path}
            if headers.get("Authorization") != f"Bearer {KEY}":
                return 401, {"detail": "invalid_api_key"}, {}
            if self.fail:
                return self.fail.pop(0)
            kind = path.rsplit("/", 1)[-1]
            if self.reject == kind:
                self.reject = None
                return 400, {"detail": "invalid_body", "error": "bad_source", "path": "counters.x"}, {}
            try:
                body = sync_format.CHECKS[kind](body)
            except sync_format.SyncFormatError as exc:
                return 400, {"detail": "invalid_body", "error": exc.code, "path": exc.path}, {}
            if kind not in sync_format.GAME_KINDS:
                return 200, self.registry(kind, body), {}
            game = sync_format.game_key(body)
            if kind != "games" and game not in self.games:
                return 404, {"detail": "game_not_found"}, {}
            if kind == "games":
                self.games[game] = body["meta"]
                answer: dict[str, Any] = {"game": f"g-{game[0]}", "created": True, "state": body["meta"]["state"]}
            elif kind == "events":
                log = self.events.setdefault(game, {})
                inserted = 0
                for ev in body["events"]:
                    k = (ev["node"], ev["seq"], ev["t"], ev["type"])
                    if k not in log:
                        log[k] = ev
                        inserted += 1
                answer = {"acked_id": body["events"][-1]["id"], "inserted": inserted,
                          "duplicates": len(body["events"]) - inserted}
            elif kind == "scores":
                self.counters[game] = sync_format.merge_counters(self.counters.get(game, {}), body["counters"])
                answer = {"totals": self.totals(game), "updated": 0}
            else:
                answer = {"nodes": len(body["nodes"])}
            if self.lose == kind:
                self.lose = None
                return 500, {"detail": "internal"}, {}
            return 200, answer, {}

    def registry(self, kind: str, body: dict[str, Any]) -> dict[str, Any]:
        if kind == "marshals":
            for m in body["marshals"]:
                self.marshals[(m["marshal_id"], m["public_key"])] = m
            return {"marshals": len(body["marshals"]), "added": 0}
        if kind == "replicas":
            for r in body["replicas"]:
                self.replicas[r["replica_id"]] = r
            return {"replicas": len(body["replicas"])}
        refused = []
        for i, entry in enumerate(body["readings"]):
            rid = json.loads(entry["record"])["reading_id"]
            if rid in self.refuse_readings:
                refused.append({"index": i, "reading_id": rid, "reason": "signature", "detail": "x"})
            else:
                self.readings.append(entry)
        return {"accepted": len(body["readings"]) - len(refused), "duplicates": 0, "refused": refused,
                "violations": 0}

    def totals(self, game: tuple[int, int]) -> dict[str, int]:
        deltas = [(e["data"]["team"], e["data"]["amount"]) for e in self.events.get(game, {}).values()
                  if e["type"] == "score.delta"]
        return sync_format.totals(self.games[game]["teams"], self.counters.get(game, {}), deltas)

    def paths(self) -> list[str]:
        return [p.rsplit("/", 1)[-1] for p, _, _ in self.requests]


class SyncCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.site = FakeSite()
        self.cfg = config(self.tmp.name, sync_enabled=True, sync_url=self.site.url, sync_api_key=KEY,
                          sync_timeout_s=3.0)
        self.store = Store(self.cfg.db_path)
        self.ctrl = Controller(self.cfg, self.store, core=CORE)

    def tearDown(self) -> None:
        self.ctrl.stop()
        self.store.close()
        self.site.close()
        self.tmp.cleanup()

    def client(self, **kw: Any) -> SyncClient:
        return SyncClient(self.cfg, self.store, **kw)

    def play(self, end: bool = True, captures: int = 3) -> int:
        gid = self.ctrl.create_game({"name": "Domingo", "mode_id": DOMINATION, "teams": ["red", "blue"],
                                     "assignments": {"3": "zone"}})["id"]
        self.ctrl.start_game(gid, force=True)
        fc = self.ctrl.fc
        for seq in range(1, captures + 1):
            self.ctrl._on_event({"node": 3, "seq": seq, "t": seq * 1000, "type": "zone.captured", "team": "red",
                                 "squad": 0, "prio": "normal", "data": {"zone": "alpha"}, "epoch": 1, "pkt_seq": seq})
        fc.merge_scores(3, {1: 100})
        self.ctrl._on_node(fc.nodes[3], "state")
        self.ctrl.adjust_score(gid, "red", -30, "penalty")
        if end:
            self.ctrl.end_game(gid)
        return gid

    def seed(self, gid: int) -> int:
        return self.store.game(gid)["game_seed"]


class CursorTests(SyncCase):
    def test_a_game_in_id_order_with_its_cursor(self) -> None:
        gid = self.play()
        client = self.client()
        self.assertTrue(client.run_once(), client.last_error)
        self.assertEqual(self.site.paths(), ["games", "events", "scores", "nodes"])
        sent = self.site.requests[1][2]
        ids = [e["id"] for e in sent["events"]]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(sent["after_id"], 0)
        state = self.store.sync_state(gid, self.seed(gid))
        self.assertEqual(state["acked_id"], ids[-1])
        self.assertTrue(state["final"])
        game = (gid, self.seed(gid))
        self.assertEqual(len(self.site.events[game]), self.store.count_events(gid))
        self.assertEqual(self.site.totals(game), self.ctrl.score(gid)["teams"])
        self.assertEqual(self.site.totals(game), {"red": 70, "blue": 0})
        self.assertEqual(self.site.games[game]["state"], "ended")

    def test_a_restart_sends_nothing_again(self) -> None:
        self.play()
        self.assertTrue(self.client().run_once())
        n = len(self.site.requests)
        restarted = self.client()
        self.assertTrue(restarted.run_once())
        self.assertEqual((len(self.site.requests), restarted.requests), (n, 0))

    def test_only_the_new_events_of_a_live_game(self) -> None:
        gid = self.play(end=False)
        client = self.client()
        client.run_once()
        first = self.store.sync_state(gid, self.seed(gid))["acked_id"]
        self.assertFalse(self.store.sync_state(gid, self.seed(gid))["final"])
        self.ctrl._on_event({"node": 3, "seq": 9, "t": 9000, "type": "zone.captured", "team": "blue", "squad": 0,
                             "prio": "normal", "data": {"zone": "alpha"}, "epoch": 1, "pkt_seq": 9})
        self.site.requests.clear()
        client.run_once()
        self.assertEqual(self.site.paths(), ["events"])  # metadata, counters and nodes did not change
        body = self.site.requests[0][2]
        self.assertEqual((body["after_id"], [e["seq"] for e in body["events"]]), (first, [9]))

    def test_a_lost_answer_is_sent_again_and_counted_twice_nowhere(self) -> None:
        gid = self.play()
        self.site.lose = "events"  # the batch is stored, its answer lost
        client = self.client()
        self.assertFalse(client.run_once())
        self.assertEqual(self.store.sync_state(gid, self.seed(gid))["acked_id"], 0)
        self.assertTrue(client.run_once())
        game = (gid, self.seed(gid))
        self.assertEqual(len(self.site.events[game]), self.store.count_events(gid))
        self.assertEqual(self.site.totals(game), {"red": 70, "blue": 0})
        batches = [b for p, _, b in self.site.requests if p.endswith("/events")]
        self.assertEqual(len(batches), 2)
        self.assertEqual(batches[0]["events"], batches[1]["events"])

    def test_big_logs_go_in_batches(self) -> None:
        gid = self.play(captures=sync_format.MAX_EVENTS + 20)
        self.assertTrue(self.client().run_once())
        batches = [b for p, _, b in self.site.requests if p.endswith("/events")]
        self.assertEqual([len(b["events"]) for b in batches], [500, self.store.count_events(gid) - 500])
        self.assertEqual(batches[1]["after_id"], batches[0]["events"][-1]["id"])

    def test_a_game_the_site_server_lost_is_sent_again(self) -> None:
        gid = self.play(end=False)
        client = self.client()
        client.run_once()
        self.site.games.clear()
        self.ctrl._on_event({"node": 3, "seq": 20, "t": 20000, "type": "zone.captured", "team": "red", "squad": 0,
                             "prio": "normal", "data": {}, "epoch": 1, "pkt_seq": 20})
        self.site.requests.clear()
        self.assertTrue(client.run_once())
        self.assertEqual(self.site.paths(), ["events", "games", "events"])
        self.assertIn((gid, self.seed(gid)), self.site.games)

    def test_an_event_out_of_form_is_skipped_not_stuck(self) -> None:
        gid = self.play(end=False)
        self.store.insert_event(gid, {"node": 3, "seq": 50, "t": 50, "type": "zone.captured", "prio": "normal",
                                      "data": {"lat": 38.7}})
        self.store.insert_event(gid, {"node": 3, "seq": 51, "t": 51, "type": "zone.captured", "prio": "normal",
                                      "data": {}})
        client = self.client()
        self.assertTrue(client.run_once())
        state = self.store.sync_state(gid, self.seed(gid))
        self.assertEqual(state["skipped"], 1)
        sent = [e for _, _, b in self.site.requests for e in b.get("events", [])]
        self.assertIn(51, [e["seq"] for e in sent])
        self.assertNotIn(50, [e["seq"] for e in sent])
        self.assertEqual(client.status()["pending_events"], 0)

    def test_a_refused_body_does_not_hold_up_the_rest(self) -> None:
        first = self.play()
        second = self.play()
        self.site.reject = "scores"  # the first game's counters
        client = self.client()
        self.assertTrue(client.run_once())
        state = self.store.sync_state(first, self.seed(first))
        self.assertIn("bad_source", state["last_error"] or "")
        self.assertFalse(state["final"])
        self.assertIn((second, self.seed(second)), self.site.counters)
        self.site.requests.clear()
        self.assertTrue(client.run_once())  # the same counters are not sent again until they change
        self.assertEqual(self.site.requests, [])
        self.assertNotIn((first, self.seed(first)), self.site.counters)
        self.assertIn("bad_source", self.store.sync_state(first, self.seed(first))["last_error"] or "")


class RegistryTests(SyncCase):
    """The field's chrono registry: keys before readings, each item once, a rotation with its periods."""

    def setUp(self) -> None:
        super().setUp()
        self.marshal = Marshal("m-ana", "Ana")
        self.replica = "8a1f0c2e-7b3d-4c5e-8f9a-0b1c2d3e4f50"

    def register(self, marshal: Marshal, at: float) -> None:
        import base64  # noqa: PLC0415

        self.store.put_marshal(marshal.marshal_id, marshal.name, base64.b64decode(marshal.public_b64), "p-ana", at)

    def readings(self, n: int = 3, outcome: str = "pass", at: float = T0 + 60,
                 marshal: Optional[Marshal] = None) -> list[dict[str, Any]]:
        series = (marshal or self.marshal).series(self.replica, "p-rita", [100.0 + i for i in range(n)])
        sid = str(uuid.uuid4())
        for rec in series:
            self.store.add_reading(rec, sid, outcome, at)
        return series

    def kinds(self) -> list[str]:
        return [k for k in self.site.paths() if k in ("marshals", "replicas", "chrono")]

    def test_keys_then_replicas_then_readings_once(self) -> None:
        self.register(self.marshal, T0)
        self.store.put_replica({"replica_id": self.replica, "owner_player_id": "p-rita", "type": "aeg",
                                "class": "rifle", "make_model": "M4", "tag_type": "nfc",
                                "tag_uid": "04:A2:B3:C4"}, T0)
        sent = self.readings()
        client = self.client()
        self.assertTrue(client.run_once(), client.last_error)
        self.assertEqual(self.kinds(), ["marshals", "replicas", "chrono"])
        self.assertEqual(len(self.site.readings), 3)
        # The record goes as the text the controller stored, untouched.
        stored = {r["reading_id"]: r["record"] for r in self.store.readings(replica_id=self.replica)}
        for entry in self.site.readings:
            record = json.loads(entry["record"])
            self.assertEqual(record, stored[record["reading_id"]])
            self.assertEqual((entry["outcome"], entry["received_at"]), ("pass", T0 + 60))
        self.assertEqual({json.loads(e["record"])["reading_id"] for e in self.site.readings},
                         {r["reading_id"] for r in sent})
        self.assertEqual(client.status()["pending_readings"], 0)
        self.site.requests.clear()
        self.assertTrue(self.client().run_once())  # a restart: nothing again
        self.assertEqual(self.kinds(), [])
        self.readings(n=1)
        self.assertTrue(client.run_once())
        self.assertEqual(self.kinds(), ["chrono"])
        self.assertEqual(len(self.site.requests[-1][2]["readings"]), 1)

    def test_a_rotated_key_keeps_its_period(self) -> None:
        import base64  # noqa: PLC0415

        self.register(self.marshal, T0)
        old = self.readings(at=T0 + 10)
        client = self.client()
        self.assertTrue(client.run_once())
        self.assertEqual([m["replaced_at"] for m in self.site.marshals.values()], [None])
        new = Marshal("m-ana", "Ana")  # a lost phone: a new key for the same marshal
        self.register(new, T0 + 100)
        self.readings(at=T0 + 200, marshal=new)
        self.site.requests.clear()
        self.assertTrue(client.run_once())
        bodies = [b for p, _, b in self.site.requests if p.endswith("/marshals")]
        self.assertEqual(len(bodies), 1)
        self.assertEqual(len(bodies[0]["marshals"]), 2)  # the old key changed (its end), the new one is new
        periods = {k: (m["registered_at"], m["replaced_at"]) for (_, k), m in self.site.marshals.items()}
        self.assertEqual(periods, {self.marshal.public_b64: (T0, T0 + 100), new.public_b64: (T0 + 100, None)})
        self.assertEqual(len(self.site.readings), 6)
        self.assertTrue(old)
        # The same key registered again keeps its first registration: earlier readings stay in its period.
        self.store.put_marshal("m-ana", "Ana Silva", base64.b64decode(new.public_b64), "p-ana", T0 + 500)
        self.assertEqual(self.store.marshal("m-ana")["registered_at"], T0 + 100)
        self.assertEqual(self.store.marshal("m-ana")["name"], "Ana Silva")

    def test_readings_the_site_server_keeps_apart_are_logged_not_resent(self) -> None:
        self.register(self.marshal, T0)
        sent = self.readings()
        self.site.refuse_readings = {sent[1]["reading_id"]}
        client = self.client()
        self.assertTrue(client.run_once())
        self.assertEqual((client.refused_readings, client.status()["pending_readings"]), (1, 0))

    def test_a_refused_body_does_not_hold_up_the_rest(self) -> None:
        self.register(self.marshal, T0)
        self.readings()
        self.site.reject = "marshals"
        client = self.client()
        self.assertTrue(client.run_once())
        self.assertIn("/api/v1/sync/marshals", client.status()["registry_error"])
        self.assertEqual(len(self.site.readings), 3)

    def test_network_errors_keep_everything_for_later(self) -> None:
        self.register(self.marshal, T0)
        self.readings()
        self.site.fail = [(503, {"detail": "unavailable"}, {})]
        client = self.client()
        self.assertFalse(client.run_once())
        self.assertEqual(client.status()["pending_readings"], 3)
        self.assertTrue(client.run_once())
        self.assertEqual(len(self.site.readings), 3)

    def test_big_registries_go_in_batches(self) -> None:
        self.register(self.marshal, T0)
        self.readings(n=sync_format.MAX_READINGS + 5)
        self.assertTrue(self.client().run_once())
        batches = [len(b["readings"]) for p, _, b in self.site.requests if p.endswith("/chrono")]
        self.assertEqual(batches, [sync_format.MAX_READINGS, 5])

    def test_resend_and_purge(self) -> None:
        self.register(self.marshal, T0)
        self.readings()
        client = self.client()
        self.assertTrue(client.run_once())
        self.store.reset_sync_state()
        self.site.requests.clear()
        self.assertTrue(client.run_once())
        self.assertEqual(self.kinds(), ["marshals", "chrono"])
        # Readings deleted (retention, erasure) take their sync bookkeeping with them.
        self.assertEqual(self.store.delete_readings(player_id="p-rita"), 3)
        self.assertEqual(self.store.sync_items("reading"), {})

    def test_the_game_seed_goes_with_a_readings_game(self) -> None:
        gid = self.ctrl.create_game({"name": "x", "mode_id": DOMINATION})["id"]
        self.register(self.marshal, T0)
        rec = self.marshal.reading(self.replica, "p-rita", 100.0, game_id=gid)
        self.store.add_reading(rec, "0f6e5d4c-3b2a-4198-8776-655443322110", "pass", T0)
        self.assertTrue(self.client().run_once())
        self.assertEqual(self.site.readings[0]["game_seed"], self.seed(gid))


class BackoffTests(SyncCase):
    def test_intervals_and_doubling(self) -> None:
        client = self.client()
        self.assertEqual(client.next_delay(), 300.0)  # between games
        gid = self.ctrl.create_game({"name": "x", "mode_id": DOMINATION})["id"]
        self.assertEqual(client.next_delay(), 300.0)  # ready, not yet running
        self.ctrl.start_game(gid, force=True)
        delays = []
        for failures in range(6):
            client.failures = failures
            delays.append(client.next_delay())
        self.assertEqual(delays, [30.0, 60.0, 120.0, 240.0, 300.0, 300.0])
        client.failures, client.retry_after = 1, 900.0
        self.assertEqual(client.next_delay(), 900.0)

    def test_refused_key_and_retry_after(self) -> None:
        self.play()
        client = self.client(api_key="x" * 43)
        self.assertFalse(client.run_once())
        self.assertEqual((client.last_error, client.failures), ("invalid_api_key", 1))
        self.site.fail = [(429, {"detail": "too_many_requests"}, {"Retry-After": "120"})]
        good = self.client()
        self.assertFalse(good.run_once())
        self.assertEqual((good.last_error, good.retry_after), ("too_many_requests", 120.0))
        self.assertTrue(good.run_once())
        self.assertEqual((good.failures, good.retry_after, good.last_error), (0, None, None))

    def test_the_game_never_waits_for_the_network(self) -> None:
        """Nothing listens at the address: every engine action returns at once; sync fails fast."""
        self.site.close()
        client = self.client()
        gid = self.play()
        self.assertFalse(client.run_once())
        self.assertEqual(client.last_error, "unreachable")
        self.assertEqual(self.store.game(gid)["state"], "ended")
        self.assertGreater(client.status()["pending_events"], 0)
        self.site = FakeSite()  # tearDown closes it

    def test_the_thread_and_kick(self) -> None:
        client = self.client()
        self.ctrl.add_listener(client.on_controller_message)
        client.start()
        try:
            gid = self.play()  # create, start and end wake the client
            self.assertTrue(wait_for(lambda: self.store.sync_state(gid, self.seed(gid))["final"], timeout=10))
        finally:
            client.stop()
        self.assertIsNone(client._thread)

    def test_kick_waits_while_backing_off(self) -> None:
        client = self.client()
        client.failures = 2
        client.kick()
        self.assertFalse(client._wake.is_set())
        client.failures = 0
        client.kick()
        self.assertTrue(client._wake.is_set())


class TransportTests(SyncCase):
    def test_redirects_are_not_followed(self) -> None:
        other = FakeSite()
        try:
            self.site.redirect_to = other.url
            self.play()
            client = self.client()
            self.assertFalse(client.run_once())
            self.assertEqual(client.last_error, "http_307")
            self.assertEqual(other.requests, [])  # the key never went there
        finally:
            other.close()

    def test_tls_with_the_configured_ca_only(self) -> None:
        field = tlsmod.ensure(os.path.join(self.tmp.name, "tls"), ["localhost"], "Teste")
        ca = os.path.join(self.tmp.name, "ca.pem")
        with open(ca, "wb") as f:
            f.write(field.ca_pem)
        site = FakeSite((str(field.server_cert), str(field.server_key)))
        try:
            self.cfg.sync_url = site.url
            self.play()
            self.assertFalse(self.client().run_once())  # a CA the system does not know: refused
            self.assertEqual(site.games, {})
            self.cfg.sync_ca_file = ca
            client = self.client()
            self.assertTrue(client.run_once(), client.last_error)
            self.assertEqual(len(site.games), 1)
        finally:
            site.close()

    def test_headers(self) -> None:
        self.play()
        self.client().run_once()
        _, headers, body = self.site.requests[0]
        self.assertEqual(headers["Authorization"], f"Bearer {KEY}")
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertTrue(headers["User-Agent"].startswith("atalaia-controller/"))
        self.assertEqual(body["controller"]["id"], self.store.get_setting("sync.controller_id"))


class SettingsTests(unittest.TestCase):
    def test_addresses_and_keys(self) -> None:
        for url, ok in (("https://site.example.org", True), ("https://site.example.org:8443/atalaia", True),
                        ("http://127.0.0.1:8000", True), ("http://localhost", True), ("http://[::1]:80", True),
                        ("http://site.example.org", False), ("ftp://x", False), ("https://u:p@x.org", False),
                        ("https://x.org/?a=1", False), ("https://x.org:99999", False), ("site.example.org", False)):
            with self.subTest(url=url):
                self.assertEqual(url_problem(url) is None, ok)
        self.assertTrue(api_key_ok("a" * 43))
        self.assertFalse(api_key_ok("a" * 42))
        self.assertFalse(api_key_ok("a" * 42 + "="))
        self.assertEqual(key_fingerprint("a" * 43), hashlib.sha256(b"a" * 43).hexdigest()[:8])

    def test_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "c.toml")
            with open(path, "w", encoding="utf-8") as f:
                f.write('[sync]\nenabled = true\nurl = "https://site.example.org"\ninterval_game_s = 10\n')
            cfg = load_config(path, env={"ATALAIA_SYNC_API_KEY": KEY})
            self.assertEqual((cfg.sync_enabled, cfg.sync_url, cfg.sync_api_key, cfg.sync_interval_game_s),
                             (True, "https://site.example.org", KEY, 10.0))
            self.assertFalse(load_config(None, env={}).sync_enabled)  # off by default
            for env, message in (({"ATALAIA_SYNC_ENABLED": "1"}, "needs sync.url"),
                                 ({"ATALAIA_SYNC_URL": "http://site.example.org"}, "https:// is required"),
                                 ({"ATALAIA_SYNC_API_KEY": "short"}, "43 characters"),
                                 ({"ATALAIA_SYNC_INTERVAL_GAME_S": "600"}, "not above"),
                                 ({"ATALAIA_SYNC_TIMEOUT_S": "0"}, "timeout_s")):
                with self.subTest(env=env):
                    with self.assertRaisesRegex(ConfigError, message):
                        load_config(None, env=env)

    def test_the_sync_key_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config(tmp)
            store = Store(cfg.db_path)
            try:
                out = io.StringIO()

                class Stdin(io.StringIO):
                    def isatty(self) -> bool:
                        return False

                import contextlib  # noqa: PLC0415

                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(sync_key(cfg, store, "set", Stdin("not a key\n")), 2)
                    self.assertEqual(sync_key(cfg, store, "set", Stdin(KEY + "\n")), 0)
                    self.assertEqual(sync_key(cfg, store, "status"), 0)
                    store.save_sync_state(1, 2, acked_id=5)
                    self.assertEqual(sync_key(cfg, store, "resend"), 0)
                    self.assertEqual(sync_key(cfg, store, "clear"), 0)
                text = out.getvalue()
                self.assertIn(f"stored the API key {key_fingerprint(KEY)}", text)
                self.assertIn("from the store", text)
                self.assertNotIn(KEY, text)  # never printed
                self.assertEqual(store.sync_state(1, 2)["acked_id"], 0)
                self.assertEqual(SyncClient(cfg, store).key_source, None)
                if os.name == "posix":
                    self.assertEqual(os.stat(cfg.db_path).st_mode & 0o777, 0o600)
            finally:
                store.close()

    def test_the_bundle_wires_it(self) -> None:
        from atalaia_controller.main import build  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            off = build(config(tmp, tls_port=0), core=CORE, load_core_lib=False)
            self.assertIsNone(off.sync)
            self.assertEqual(off.controller.status()["sync"], {"enabled": False})
            off.store.close()
        with tempfile.TemporaryDirectory() as tmp:
            on = build(config(tmp, tls_port=0, sync_enabled=True, sync_url="https://site.example.org",
                              sync_api_key=KEY), core=CORE, load_core_lib=False)
            status = on.controller.status()["sync"]
            self.assertEqual((status["enabled"], status["key"], status["key_fingerprint"], status["pending_events"]),
                             (True, "config", key_fingerprint(KEY), 0))
            on.store.close()


# Keys a request body may have, by where they are (protocol/sync.md); "*" is any key (a team, a source).
ALLOWED = {
    "": {"sync_version", "controller", "game", "meta", "after_id", "events", "counters", "nodes", "marshals",
         "replicas", "readings", "scheduled_game_id", "walkins", "registrations", "results"},
    "controller": {"id", "version"}, "game": {"game_id", "game_seed"},
    "meta": {"name", "mode_id", "teams", "team_info", "params", "squads", "duration_ms", "state", "node_id",
             "joined", "created_at", "started_at", "ended_at", "scheduled_game_id"},
    "meta.team_info": "any",  # team names
    "meta.team_info.*": {"display_name", "crest_id"},
    "events[]": {"id", "node", "seq", "t", "type", "team", "squad", "prio", "data", "epoch", "pkt_seq"},
    "nodes[]": {"node_id", "name", "role", "last_seen", "info"},
    "nodes[].info": set(sync_format.NODE_INFO),
    "marshals[]": {"marshal_id", "name", "public_key", "player_id", "registered_at", "replaced_at"},
    "replicas[]": {"replica_id", "owner_player_id", "type", "class", "make_model", "registered_at", "tag_type",
                   "tag_uid"},
    "readings[]": {"record", "series_id", "outcome", "received_at", "game_seed"},
    # Plan phase 16: outcomes and claim verdicts; never a name, a federation number or a secret's hash.
    "registrations[]": {"registration_id", "player_id", "outcome", "ticket_sha256", "declarations"},
    "registrations[].declarations[]": {"declaration_id", "state", "reading_id"},
    "results[]": {"claim_id", "result"},
}
# The signed record's fields (protocol/chrono-record.md): what a reading's record may carry.
RECORD = {"reading_id", "replica_id", "player_id", "type", "velocity_mps", "bb_weight_g", "energy_j", "chrono_id",
          "marshal_id", "marshal_name", "game_id", "field_id", "timestamp", "ref_reading_id", "signature"}


class PrivacyTests(P3Case):
    """A real game with check-ins (names, a federation number), positions and tokens: none of it in
    any body sent to the site server."""

    def setUp(self) -> None:
        self.site = FakeSite()
        self.cfg_overrides = {"sync_enabled": True, "sync_url": self.site.url, "sync_api_key": KEY,
                              "federation": "optional"}
        super().setUp()

    def tearDown(self) -> None:
        super().tearDown()
        self.site.close()

    def walk(self, value: Any, path: str, problems: list[str]) -> None:
        if isinstance(value, list):
            for item in value:
                self.walk(item, path + "[]", problems)
            return
        if not isinstance(value, dict) or path.startswith("meta.params") or ".data" in path or path.startswith(
                "counters"):
            return
        allowed = ALLOWED.get(path) or ALLOWED.get(path.rsplit(".", 1)[0] + ".*" if "." in path else "")
        for key, item in value.items():
            if allowed != "any" and (allowed is None or key not in allowed):
                problems.append(f"{path}.{key}" if path else key)
            self.walk(item, f"{path}.{key}" if path else key, problems)

    def test_nothing_private_is_sent(self) -> None:
        game = self.new_game(teams=["red", "blue"], team_info={"red": {"display_name": "Lobos"}})
        gid = game["id"]
        replica = "8a1f0c2e-7b3d-4c5e-8f9a-0b1c2d3e4f50"
        me = self.check_in(gid, name="Rita Secreta", federation_number="FPA-778899",
                           replicas=[declaration(replica, make_model="Tokyo Marui M4")])
        marshal, mtoken = self.make_marshal(gid, Marshal("m-ana", "Ana"))
        series = marshal.series(replica, me["player_id"], [100.0, 101.0], game_id=gid)
        r = self.client.post("/api/v1/chrono/readings", headers=bearer(mtoken), json={
            "readings": series, "replica": {"replica_id": replica, "owner_player_id": me["player_id"], "type": "aeg",
                                            "class": "rifle", "make_model": "Tokyo Marui M4"}})
        self.assertEqual(r.status_code, 200, r.text)
        self.svc.rate.allow = lambda key: True
        self.client.post(f"/api/v1/games/{gid}/start", headers=GM, json={"force": True})
        token = self.client.post("/api/v1/checkin/token", headers=bearer(me["token"])).json()["token"]
        for r in (self.client.post("/api/v1/positions", headers=bearer(token),
                                   json={"lat": 38.123456, "lon": -9.654321, "accuracy_m": 5.0, "source": "gps",
                                         "t": 1}),
                  self.client.put(f"/api/v1/games/{gid}/positions/4", headers=GM, json={"x": 0.4321, "y": 0.8765}),
                  self.client.post(f"/api/v1/games/{gid}/score", headers=GM,
                                   json={"team": "red", "amount": -7, "reason": "x"})):
            self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(self.ctrl.store.player_positions(gid))
        sync = self.bundle.sync
        self.assertTrue(sync.run_once(), sync.last_error)  # during the game
        self.client.post(f"/api/v1/games/{gid}/end", json={}, headers=GM)
        self.assertTrue(sync.run_once(), sync.last_error)  # and after it
        bodies = [body for _, _, body in self.site.requests]
        self.assertTrue(any(b.get("events") for b in bodies))
        text = json.dumps(bodies, ensure_ascii=False)
        secrets_ = ["Rita Secreta", "FPA-778899", "38.123456", "-9.654321", "0.4321", "0.8765", me["token"], token,
                    "gm-secret", "read-secret", KEY, self.ctrl.join_key.hex(), self.svc.ctrl.store.get_setting("join_key")]
        key_rows = self.ctrl.store._exec("SELECT key FROM token_keys").fetchall()
        secrets_ += [bytes(r["key"]).hex() for r in key_rows]
        from cryptography.hazmat.primitives import serialization  # noqa: PLC0415
        import base64  # noqa: PLC0415

        seed = marshal.key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                         serialization.NoEncryption())
        secrets_ += [seed.hex(), base64.b64encode(seed).decode()]  # the marshal's private key: never
        secret_sha = self.ctrl.store._exec("SELECT secret_sha256 FROM field_players").fetchall()
        secrets_ += [bytes(r["secret_sha256"]).hex() for r in secret_sha if r["secret_sha256"]]
        for secret in secrets_:
            if secret:
                with self.subTest(secret=secret[:12]):
                    self.assertNotIn(secret, text)
        problems: list[str] = []
        for body in bodies:
            self.walk(body, "", problems)
        self.assertEqual(problems, [])
        # The chrono registry went too: the signed records with their fields only, verbatim.
        records = [json.loads(e["record"]) for b in bodies for e in b.get("readings", [])]
        self.assertEqual({r["reading_id"] for r in records}, {r["reading_id"] for r in series})
        for record in records:
            self.assertLessEqual(set(record), RECORD)
        self.assertTrue(any(b.get("marshals") for b in bodies))
        self.assertTrue(any(b.get("replicas") for b in bodies))
        # The player appears only by the field's pseudonymous id (P4R25, ADR-P4-8's amendment).
        checkin = [e for b in bodies for e in b.get("events", []) if e["type"] == "player.checkin"]
        self.assertIn({"player": me["player_id"]}, [e["data"] for e in checkin])
        self.assertTrue(all(set(e["data"]) == {"player"} for e in checkin))
        self.assertEqual(self.site.games[(gid, self.ctrl.store.game(gid)["game_seed"])]["team_info"],
                         {"red": {"display_name": "Lobos"}})


if __name__ == "__main__":
    unittest.main()
