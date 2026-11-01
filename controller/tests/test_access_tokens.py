# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Short-lived, scoped, revocable access tokens (access_tokens.py): the API, the scope rules on every route
(the list is built from the router, so a new route is covered with no change here), expiry on the
controller's wall clock, revocation, hashing, the audit log, the CLI and the plain-HTTP guard.

    cd controller && python -m unittest tests.test_access_tokens
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import re
import tempfile
import unittest
from unittest import mock

from fastapi.routing import APIRoute, APIWebSocketRoute
from fastapi.testclient import TestClient

from p3support import https_app
from support import CORE, config
from atalaia_controller import access_tokens as acc
from atalaia_controller import main as mainmod
from atalaia_controller.addresses import FieldAddresses
from atalaia_controller.main import build

GM = {"Authorization": "Bearer gm-secret"}
READ = {"Authorization": "Bearer read-secret"}
DOMINATION = "org.atalaia.domination"
GATE_TEXTS = ("limited to game", "main GM token only")


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class Clock:
    def __init__(self, t: float = 1_800_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class TokenCase(unittest.TestCase):
    """The whole controller from main.build() (check-in, positions...): every route is really served."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = config(self.tmp.name, tls_names=["10.0.2.2"])
        addrs = FieldAddresses.current(self.cfg.tls_names, self.cfg.tls_port, extra_interfaces=self.cfg.tls_names)
        self.bundle = build(self.cfg, core=CORE, load_core_lib=False, addresses=addrs)
        self.ctrl, self.store, self.app = self.bundle.controller, self.bundle.store, self.bundle.app
        self.clock = Clock()
        self.ctrl.access_tokens._wall = self.clock  # the controller's wall clock, moved by the tests
        self.client = TestClient(https_app(self.app), base_url="https://testserver")  # tokens go over HTTPS (guard.py)

    def tearDown(self):
        self.client.close()
        if self.bundle.atak is not None:
            self.bundle.atak.stop()
        self.ctrl.stop()
        self.store.close()
        self.tmp.cleanup()

    def make(self, **body) -> dict:
        body = {"label": "test", "scope": "read", **body}
        r = self.client.post("/api/v1/tokens", json=body, headers=GM)
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def new_game(self) -> int:
        r = self.client.post("/api/v1/games", json={"name": "Sunday", "mode_id": DOMINATION,
                                                     "teams": ["red", "blue"], "assignments": {"4": "zone"}},
                             headers=GM)
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["id"]


class LifecycleTests(TokenCase):
    def test_create_list_revoke(self):
        made = self.make(label="Referee Ana", scope="gm", ttl_s=3600)
        self.assertTrue(re.fullmatch(r"atk_[0-9a-f]{8}\.[A-Za-z0-9_-]{43}", made["token"]))
        self.assertEqual((made["scope"], made["label"], made["expires_at"]), ("gm", "Referee Ana", self.clock.t + 3600))
        listed = self.client.get("/api/v1/tokens", headers=GM).json()
        self.assertEqual([t["id"] for t in listed["tokens"]], [made["id"]])
        self.assertNotIn(made["token"].split(".")[1], str(listed))  # never shown again
        self.assertEqual(listed["tokens"][0]["status"], "active")
        self.assertEqual(self.client.get("/api/v1/whoami", headers=bearer(made["token"])).status_code, 200)
        r = self.client.delete(f"/api/v1/tokens/{made['id']}", headers=GM)
        self.assertEqual((r.status_code, r.json()["status"]), (200, "revoked"))
        self.assertEqual(self.client.get("/api/v1/whoami", headers=bearer(made["token"])).status_code, 401)
        self.assertEqual(self.client.delete("/api/v1/tokens/ffffffff", headers=GM).status_code, 404)

    def test_default_and_maximum_lifetime(self):
        self.assertEqual(self.make()["expires_at"], self.clock.t + 8 * 3600)
        self.assertEqual(self.make(ttl_s=7 * 86400)["expires_at"], self.clock.t + 7 * 86400)
        for bad in (7 * 86400 + 1, 59, 0, -5, "8h", True, None):
            r = self.client.post("/api/v1/tokens", json={"label": "x", "scope": "read", "ttl_s": bad}, headers=GM)
            self.assertEqual(r.status_code, 400, bad)

    def test_validation(self):
        post = lambda body: self.client.post("/api/v1/tokens", json=body, headers=GM).status_code  # noqa: E731
        self.assertEqual(post({"scope": "read"}), 400)
        self.assertEqual(post({"label": "", "scope": "read"}), 400)
        self.assertEqual(post({"label": "x" * 61, "scope": "read"}), 400)
        self.assertEqual(post({"label": "a\x00b", "scope": "read"}), 400)
        self.assertEqual(post({"label": "x", "scope": "root"}), 400)
        self.assertEqual(post({"label": "x", "scope": "read", "extra": 1}), 400)
        self.assertEqual(post({"label": "x", "scope": "read", "game_id": 99}), 404)
        self.assertEqual(post({"label": "x", "scope": "marshals", "game_id": 1}), 400)
        self.assertEqual(self.client.post("/api/v1/tokens", json=[], headers=GM).status_code, 400)
        # a label's newlines cannot forge an audit or log line
        made = self.make(label="a\nb\tc")
        self.assertEqual(made["label"], "a b c")

    def test_at_most_fifty_active(self):
        for i in range(acc.MAX_ACTIVE):
            self.make(label=f"t{i}")
        r = self.client.post("/api/v1/tokens", json={"label": "one more", "scope": "read"}, headers=GM)
        self.assertEqual(r.status_code, 409)

    def test_only_the_hash_is_stored(self):
        made = self.make()
        secret = made["token"].split(".")[1]
        row = self.store.access_token(made["id"])
        self.assertEqual(row["secret_hash"], hashlib.sha256(secret.encode()).hexdigest())
        dump = "".join(self.store._db.iterdump())  # the whole database, as text
        self.assertNotIn(secret, dump)
        self.assertNotIn(made["token"], dump)

    def test_expiry_on_the_controllers_clock_and_purge(self):
        made = self.make(ttl_s=120)
        tok = bearer(made["token"])
        self.clock.t += 119
        self.assertEqual(self.client.get("/api/v1/whoami", headers=tok).status_code, 200)
        self.clock.t += 2
        self.assertEqual(self.client.get("/api/v1/whoami", headers=tok).status_code, 401)
        self.assertEqual(self.client.get("/api/v1/tokens", headers=GM).json()["tokens"][0]["status"], "expired")
        self.clock.t += acc.PURGE_GRACE_S + 1
        self.ctrl.tick()
        self.assertEqual(self.client.get("/api/v1/tokens", headers=GM).json()["tokens"], [])

    def test_a_clock_set_back_refuses_the_token(self):
        made = self.make()
        self.clock.t -= 3600
        self.assertEqual(self.client.get("/api/v1/whoami", headers=bearer(made["token"])).status_code, 401)
        self.clock.t += 3600
        self.assertEqual(self.client.get("/api/v1/whoami", headers=bearer(made["token"])).status_code, 200)

    def test_wrong_tokens(self):
        made = self.make()
        id_, secret = made["token"][4:].split(".")
        for bad in (f"atk_{id_}.{'A' * 43}", f"atk_00000000.{secret}", f"atk_{id_}.{secret}x", f"atk_{id_}",
                    "atk_", made["token"].upper(), made["token"][:-1]):
            self.assertEqual(self.client.get("/api/v1/whoami", headers=bearer(bad)).status_code, 401, bad)
        # the GM and read tokens are unchanged
        self.assertEqual(self.client.get("/api/v1/whoami", headers=GM).json()["role"], "gm")
        self.assertEqual(self.client.get("/api/v1/whoami", headers=READ).json()["role"], "read")

    def test_failed_tokens_are_rate_limited_per_address(self):
        good = self.make()
        for _ in range(acc.FAILS_PER_MINUTE):
            self.assertEqual(self.client.get("/api/v1/whoami", headers=bearer("atk_00000000." + "A" * 43)).status_code, 401)
        self.assertEqual(self.client.get("/api/v1/whoami", headers=bearer("atk_00000000." + "A" * 43)).status_code, 429)
        self.assertEqual(self.client.get("/api/v1/whoami", headers=bearer(good["token"])).status_code, 429)
        self.assertEqual(self.client.get("/api/v1/whoami", headers=GM).status_code, 200)  # the main tokens: unchanged

    def test_whoami(self):
        self.assertTrue(self.client.get("/api/v1/whoami", headers=GM).json()["access_tokens"])
        self.assertNotIn("access_tokens", self.client.get("/api/v1/whoami", headers=READ).json())
        made = self.make(scope="gm", label="ref")
        who = self.client.get("/api/v1/whoami", headers=bearer(made["token"])).json()
        self.assertEqual(who["role"], "gm")
        self.assertNotIn("access_tokens", who)
        self.assertEqual(who["token"]["scope"], "gm")


class AuditTests(TokenCase):
    def test_audit_has_creation_use_and_revocation_and_use_is_rate_limited(self):
        made = self.make(label="ref")
        tok = bearer(made["token"])
        for _ in range(5):
            self.client.get("/api/v1/whoami", headers=tok)
        self.client.post("/api/v1/games", json={}, headers=tok)  # a read token: refused by the route, still a "use"
        self.client.delete(f"/api/v1/tokens/{made['id']}", headers=GM)
        kinds = [a["kind"] for a in self.client.get("/api/v1/tokens/audit", headers=GM).json()["audit"]]
        self.assertEqual(sorted(kinds), ["created", "revoked", "used"])
        self.clock.t += acc.USE_LOG_EVERY_S + 1
        again = self.make(label="two")
        self.client.get("/api/v1/whoami", headers=bearer(again["token"]))
        self.client.get("/api/v1/whoami", headers=bearer(again["token"]))
        used = [a for a in self.store.token_audit() if a["kind"] == "used" and a["token_id"] == again["id"]]
        self.assertEqual(len(used), 1)
        self.assertNotIn(again["token"], str(self.store.token_audit()))

    def test_last_used_is_listed(self):
        made = self.make()
        self.assertIsNone(self.client.get("/api/v1/tokens", headers=GM).json()["tokens"][0]["last_used_at"])
        self.clock.t += 5
        self.client.get("/api/v1/whoami", headers=bearer(made["token"]))
        row = self.client.get("/api/v1/tokens", headers=GM).json()["tokens"][0]
        self.assertEqual(row["last_used_at"], self.clock.t)
        self.assertTrue(row["last_used_from"])

    def test_a_refused_request_is_audited(self):
        game = self.new_game()
        made = self.make(scope="gm", game_id=game)
        r = self.client.post("/api/v1/games", json={}, headers=bearer(made["token"]))
        self.assertEqual(r.status_code, 403)
        self.assertIn("refused", [a["kind"] for a in self.store.token_audit()])


class ScopeTests(TokenCase):
    """What each scope may do, route by route, from the router's own list."""

    DEPS = {"require_gm", "require_main_gm", "require_console", "require_read", "require_player"}
    def routes(self):
        out = []
        for route in self.app.routes:
            if isinstance(route, APIWebSocketRoute):
                continue
            if not isinstance(route, APIRoute):
                continue
            levels = self._levels(route.dependant)
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                out.append((method, route.path, levels))
        return out

    def _levels(self, dependant) -> set:
        found = set()
        for d in dependant.dependencies:
            name = getattr(d.call, "__name__", "")
            if name in self.DEPS:
                found.add(name)
            found |= self._levels(d)
        return found

    @staticmethod
    def fill(path: str, game_id: int = 1) -> str:
        return re.sub(r"\{(\w+)\}", lambda m: str(game_id) if m.group(1) == "game_id" else "1", path)

    def call(self, method: str, path: str, headers: dict):
        kwargs = {"headers": headers}
        if method in ("POST", "PUT", "PATCH"):
            kwargs["content"] = b"[]"  # a body no handler takes as an object: nothing is changed
            kwargs["headers"] = {**headers, "Content-Type": "application/json"}
        return self.client.request(method, path, **kwargs)

    def test_the_gate_is_in_front_of_every_route(self):
        gate = self.app.state.gate
        self.assertIn(gate, [d.dependency for d in self.app.router.dependencies])
        for route in self.app.routes:
            if isinstance(route, (APIRoute, APIWebSocketRoute)):
                self.assertIn(gate, [d.call for d in route.dependant.dependencies], route.path)

    def test_every_route_is_classified(self):
        routes = self.routes()
        self.assertGreater(len(routes), 150)
        public = {(m, p) for m, p, levels in routes if not levels}
        self.assertEqual(public, self.PUBLIC, "a route with no token check was added or removed: look at it")

    # Routes that ask for no GM, read or console token: public pages, a box's or a check-in's own credentials.
    # A new one fails test_every_route_is_classified until it is looked at and added here.
    PUBLIC = {
        ("GET", "/healthz"), ("GET", "/"), ("GET", "/console"), ("GET", "/scoreboard"),
        ("GET", "/api/v1/controller/https"), ("GET", "/api/v1/controller/ca"), ("GET", "/api/v1/checkin"),
        ("GET", "/api/v1/games/{game_id}/teams"), ("POST", "/api/v1/checkin"),
        ("GET", "/api/v1/field/branding"), ("GET", "/api/v1/field/branding/{slot}"), ("GET", "/api/v1/crests/{crest_id}"),
        ("GET", "/api/v1/firmware/{release_id}/image"), ("GET", "/api/v1/firmware/{release_id}/release"),
        ("POST", "/api/v1/firmware/report"),
        ("GET", "/api/v1/mode-packages/{mode_id}/package"), ("GET", "/api/v1/mode-packages/{mode_id}/release"),
        ("POST", "/api/v1/mode-packages/report"),
    }

    def test_read_scope_is_the_read_token_on_every_route(self):
        game = self.new_game()
        made = self.make(scope="read")
        for method, path, levels in self.routes():
            url = self.fill(path, game)
            if path.startswith("/api/v1/tokens"):
                self.assertEqual(self.call(method, url, bearer(made["token"])).status_code, 403, (method, path))
                continue
            if "require_gm" in levels:
                got = self.call(method, url, bearer(made["token"]))
                want = self.call(method, url, READ)
                self.assertEqual((got.status_code, want.status_code), (403, 403), (method, path))
            elif method == "GET" and "require_player" not in levels:
                got, want = self.call(method, url, bearer(made["token"])), self.call(method, url, READ)
                self.assertEqual(got.status_code, want.status_code, (method, path))

    def test_gm_scope_is_the_gm_token_except_the_tokens_routes(self):
        game = self.new_game()
        made = self.make(scope="gm")
        for method, path, levels in self.routes():
            url = self.fill(path, game)
            got = self.call(method, url, bearer(made["token"]))
            if path.startswith("/api/v1/tokens"):
                self.assertEqual(got.status_code, 403, (method, path))
                continue
            self.assertNotEqual(got.status_code, 401, (method, path))
            if got.status_code == 403:
                detail = got.json().get("detail", "") if "json" in got.headers.get("content-type", "") else ""
                self.assertNotIn("GM token", detail, (method, path))
                for text in GATE_TEXTS:
                    self.assertNotIn(text, detail, (method, path))
            if "require_gm" in levels and got.status_code == 403:
                self.fail(f"{method} {path}: a GM-scope token was refused")

    def test_marshals_scope_is_read_plus_the_marshal_routes_only(self):
        game = self.new_game()
        made = self.make(scope="marshals")
        tok = bearer(made["token"])
        grants = acc.GRANTS["marshals"]
        seen = set()
        for method, path, levels in self.routes():
            if "require_gm" not in levels and "require_main_gm" not in levels:
                continue
            got = self.call(method, self.fill(path, game), tok)
            if (method, path) in grants:
                seen.add((method, path))
                self.assertNotIn(got.status_code, (401, 403), (method, path))
            else:
                self.assertEqual(got.status_code, 403, (method, path))
        self.assertEqual(seen, set(grants))  # the grants name routes that exist
        # and it does the job it is for
        r = self.client.post("/api/v1/marshals", json={"marshal_id": "ios-test", "name": "iOS test"}, headers=tok)
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual([m["marshal_id"] for m in self.client.get("/api/v1/marshals", headers=tok).json()], ["ios-test"])
        self.assertEqual(self.client.delete("/api/v1/marshals/ios-test", headers=tok).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/games", headers=tok).status_code, 200)

    def test_game_limit_on_every_route(self):
        one = self.new_game()
        self.client.post(f"/api/v1/games/{one}/end", headers=GM)
        two = self.new_game()
        for scope in ("gm", "read"):
            made = self.make(scope=scope, game_id=one)
            tok = bearer(made["token"])
            for method, path, levels in self.routes():
                if path.startswith("/api/v1/tokens"):
                    continue
                names_game = "{game_id}" in path
                other = self.call(method, self.fill(path, two), tok)
                same = self.call(method, self.fill(path, one), tok)
                limited = lambda r: r.status_code == 403 and "limited to game" in r.text  # noqa: E731
                if names_game:
                    self.assertTrue(limited(other), (scope, method, path, other.status_code))
                    self.assertFalse(limited(same), (scope, method, path))
                elif method == "GET":
                    self.assertFalse(limited(same), (scope, method, path))
                else:
                    self.assertTrue(limited(same), (scope, method, path, same.status_code))

    def test_a_token_cannot_make_tokens(self):
        for scope in acc.SCOPES:
            made = self.make(scope=scope)
            tok = bearer(made["token"])
            self.assertEqual(self.client.post("/api/v1/tokens", json={"label": "x", "scope": "read"}, headers=tok).status_code, 403)
            self.assertEqual(self.client.get("/api/v1/tokens", headers=tok).status_code, 403)
            self.assertEqual(self.client.get("/api/v1/tokens/audit", headers=tok).status_code, 403)
            self.assertEqual(self.client.delete(f"/api/v1/tokens/{made['id']}", headers=tok).status_code, 403)
        self.assertEqual(self.client.post("/api/v1/tokens", json={"label": "x", "scope": "read"}, headers=READ).status_code, 403)
        self.assertEqual(self.client.post("/api/v1/tokens", json={"label": "x", "scope": "read"}).status_code, 401)

    def test_the_policy_functions(self):
        self.assertEqual(acc.effective_role("marshals", "POST", "/api/v1/marshals"), "gm")
        self.assertEqual(acc.effective_role("marshals", "POST", "/api/v1/games"), "read")
        self.assertEqual(acc.effective_role("read", "POST", "/api/v1/marshals"), "read")
        self.assertEqual(acc.ceiling_role("marshals"), "gm")
        self.assertEqual(acc.ceiling_role("read"), "read")
        self.assertIsNotNone(acc.denial({"game_id": 3}, "POST", "/api/v1/games", {}))
        self.assertIsNotNone(acc.denial({"game_id": 3}, "GET", "/api/v1/games/{game_id}", {"game_id": "4"}))
        self.assertIsNone(acc.denial({"game_id": 3}, "GET", "/api/v1/games", {}))
        self.assertIsNone(acc.denial({"game_id": None}, "POST", "/api/v1/games", {}))


class StreamTests(TokenCase):
    def test_stream_accepts_a_token_and_ends_when_it_is_revoked(self):
        made = self.make(scope="read")
        with mock.patch.object(acc, "STREAM_RECHECK_S", 0.05):
            with self.client.websocket_connect("/api/v1/stream", headers=bearer(made["token"])) as ws:
                self.assertIn(ws.receive_json()["type"], ("hello", "snapshot"))
                self.client.delete(f"/api/v1/tokens/{made['id']}", headers=GM)
                with self.assertRaises(Exception) as ctx:
                    for _ in range(100):
                        ws.receive_json()
                self.assertEqual(getattr(ctx.exception, "code", None), 4401)

    def test_stream_refuses_an_expired_or_unknown_token(self):
        made = self.make(ttl_s=60)
        self.clock.t += 61
        for tok in (made["token"], "atk_00000000." + "A" * 43):
            with self.assertRaises(Exception):
                with self.client.websocket_connect("/api/v1/stream", headers=bearer(tok)) as ws:
                    ws.receive_json()

    def test_game_limited_token_may_follow_the_stream(self):
        game = self.new_game()
        made = self.make(scope="read", game_id=game)
        with self.client.websocket_connect("/api/v1/stream", headers=bearer(made["token"])) as ws:
            self.assertIn(ws.receive_json()["type"], ("hello", "snapshot"))


def from_address(app, host, base_url):
    """A TestClient whose requests come from ``host`` (this Starlette's TestClient has no ``client`` option)."""
    async def shim(scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            scope = {**scope, "client": (host, 5000)}
        await app(scope, receive, send)
    return TestClient(shim, base_url=base_url)


class GuardTests(TokenCase):

    def test_over_plain_http_only_a_read_scope_token_reads(self):
        remote = from_address(self.app, "192.168.1.50", "http://testserver")
        read = self.make(scope="read")["token"]
        gm = self.make(scope="gm")["token"]
        marshals = self.make(scope="marshals")["token"]
        self.assertEqual(remote.get("/api/v1/whoami", headers=bearer(read)).status_code, 200)
        self.assertEqual(remote.post("/api/v1/games", json={}, headers=bearer(read)).status_code, 403)
        for tok in (gm, marshals):
            r = remote.get("/api/v1/whoami", headers=bearer(tok))
            self.assertEqual((r.status_code, r.json().get("https_port")), (403, 8443))
        local = from_address(self.app, "127.0.0.1", "http://testserver")
        self.assertEqual(local.get("/api/v1/whoami", headers=bearer(gm)).status_code, 200)
        remote.close()
        local.close()


class CliTests(TokenCase):
    def run_cli(self, **kw):
        args = argparse.Namespace(**{"create": None, "list": False, "revoke": None, "scope": "read", "ttl": "8h",
                                     "game": None, **kw})
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                mock.patch.object(mainmod.time, "time", self.clock):
            code = mainmod.access_token_command(self.store, args)
        return code, out.getvalue(), err.getvalue()

    def test_create_list_revoke(self):
        code, out, _ = self.run_cli(create="CI run", scope="marshals", ttl="2h")
        self.assertEqual(code, 0)
        token = re.search(r"token:\s+(atk_\S+)", out).group(1)
        tid = re.search(r"id:\s+(\w{8})", out).group(1)
        self.assertEqual(self.store.access_token(tid)["scope"], "marshals")
        # the token made on the command line is the controller's token (same store)
        self.assertEqual(self.client.get("/api/v1/whoami", headers=bearer(token)).status_code, 200)
        code, out, _ = self.run_cli(list=True)
        self.assertIn("CI run", out)
        self.assertNotIn(token, out)
        code, out, _ = self.run_cli(revoke=tid)
        self.assertIn("revoked", out)
        self.assertEqual(self.client.get("/api/v1/whoami", headers=bearer(token)).status_code, 401)
        self.assertEqual(self.run_cli(revoke="deadbeef")[0], 2)
        self.assertEqual(self.run_cli(create="x", ttl="9d")[0], 2)
        self.assertEqual(self.run_cli(create="x", ttl="soon")[0], 2)

    def test_ttl_text(self):
        self.assertEqual([mainmod.parse_ttl(t) for t in ("90", "90s", "30m", "8h", "2d")], [90, 90, 1800, 28800, 172800])
        with self.assertRaises(ValueError):
            mainmod.parse_ttl("h")


if __name__ == "__main__":
    unittest.main()
