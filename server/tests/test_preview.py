# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A preview deployment (decisions PV-*): the banner, noindex, the landing page, the feedback form with its
guards and limits, the administrators' side of it, the retention of what visitors wrote, the demo data and the
test accounts the operator makes.

    python3 tools/docker_server.py test tests.test_preview
"""

from __future__ import annotations

import argparse
import io
import json
import re
import stat
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

from atalaia_server import cli, demo_data, personal_data, sync, totp
from atalaia_server.config import ConfigError, Settings
from atalaia_server.models import Controller, Game
from atalaia_server.ratelimit import Limits
from atalaia_server.web import preview_texts
from atalaia_server.web.staff_i18n import STRINGS as STAFF

from .base import SECRET_KEY, AppTestCase

HEADERS = {"Content-Type": "application/x-www-form-urlencoded"}


class PreviewCase(AppTestCase):
    preview = True

    def settings(self) -> Settings:
        s = super().settings()
        return Settings(allow_signup_without_notice=True, database_url=s.database_url, secret_key=s.secret_key, metrics_token=s.metrics_token,
                        db_timeout_s=2.0, purge_hour=None, preview=self.preview)

    def at(self, seconds: float) -> None:
        """The app's clock (the form's token reads it) at ``seconds``."""
        self.app.state.clock = lambda: seconds

    async def form(self, path: str = "/feedback", **params: str) -> tuple[str, str]:
        """GETs the form; returns its HTML and its token."""
        r = await self.client.get(path, params=params)
        self.assertEqual(r.status_code, 200, r.text)
        token = re.search(r'name="t" value="([^"]+)"', r.text)
        return r.text, token.group(1) if token else ""

    async def send(self, token: str, expect: int = 303, headers: Optional[dict[str, str]] = None, **fields: str) -> Any:
        body = {"t": token, "lang": "en", "from": "", "kind": "good", "who": "", "message": "Nice scoreboard",
                "contact": "", "website": "", **fields}
        r = await self.client.post("/feedback", content=urlencode(body), headers={**HEADERS, **(headers or {})})
        self.assertEqual(r.status_code, expect, r.text)
        return r

    async def rows(self) -> list[Any]:
        return await self.fetch("SELECT * FROM preview_feedback ORDER BY created_at")

    async def admin(self) -> dict[str, str]:
        _, name, secret = await self.make_user(server_admin=True)
        return await self.auth(name, secret=secret)


class NormalServerTests(PreviewCase):
    preview = False

    async def test_nothing_changes_without_the_setting(self) -> None:
        for path in ("/", "/feedback", "/robots.txt", "/staff/feedback"):
            self.assertEqual((await self.client.get(path)).status_code, 404, path)
        self.assertEqual((await self.client.post("/feedback", content="x", headers=HEADERS)).status_code, 404)
        r = await self.client.get("/api/v1/health")
        self.assertNotIn("x-robots-tag", r.headers)
        r = await self.client.get("/staff/login")
        self.assertNotIn("preview-banner", r.text)
        self.assertEqual((await self.client.get("/api/v1/admin/feedback")).status_code, 404)


class BannerTests(PreviewCase):
    async def test_the_banner_noindex_and_robots(self) -> None:
        for path, lang in (("/staff/login?lang=en", "en"), ("/staff/login?lang=pt", "pt"), ("/feedback?lang=de", "de"),
                           ("/?lang=zh-tw", "zh-tw"), ("/f/nada/", "pt")):
            with self.subTest(path=path):
                r = await self.client.get(path)
                self.assertIn('class="preview-banner"', r.text)
                self.assertIn(preview_texts.STRINGS[lang]["banner_text"].split(",")[0].replace("&", "&amp;"), r.text)
                self.assertEqual(r.headers["x-robots-tag"], "noindex, nofollow, noarchive")
        r = await self.client.get("/staff/login?lang=en")
        self.assertIn('href="/feedback?lang=en&amp;from=/staff/login"', r.text)
        for path in ("/api/v1/health", "/robots.txt", "/static/field.css", "/nada"):
            self.assertEqual((await self.client.get(path)).headers["x-robots-tag"], "noindex, nofollow, noarchive", path)
        r = await self.client.get("/")  # what Caddy adds in production, since a preview has none
        for name in ("permissions-policy", "cross-origin-opener-policy", "x-permitted-cross-domain-policy"[:-1] + "ies",
                     "strict-transport-security", "content-security-policy", "x-frame-options"):
            self.assertIn(name, r.headers)
        r = await self.client.get("/robots.txt")
        self.assertEqual((r.status_code, r.text), (200, "User-agent: *\nDisallow: /\n"))

    async def test_the_preview_cannot_be_hosted(self) -> None:
        with self.assertRaises(ConfigError):
            Settings(allow_signup_without_notice=True, database_url=self.database_url, secret_key=SECRET_KEY, hosted=True, hosted_domain="hub.example.pt",
                     preview=True)
        env = {"ATALAIA_DATABASE_URL": self.database_url, "ATALAIA_SECRET_KEY": SECRET_KEY}
        self.assertFalse(Settings.from_env(env).preview)
        self.assertTrue(Settings.from_env({**env, "ATALAIA_PREVIEW": "on"}).preview)
        with self.assertRaises(ConfigError):
            Settings.from_env({**env, "ATALAIA_PREVIEW": "yes"})

    async def test_language_choice(self) -> None:
        self.assertEqual(preview_texts.choose(None, "de-DE,de;q=0.9,en;q=0.5"), ("de", False))
        self.assertEqual(preview_texts.choose(None, "zh-TW,zh;q=0.9"), ("zh-tw", False))
        self.assertEqual(preview_texts.choose(None, "fr"), ("pt", False))
        self.assertEqual(preview_texts.choose("en", "de"), ("en", True))
        self.assertEqual(set(preview_texts.STRINGS), set(preview_texts.LANGUAGES))
        keys = set(preview_texts.STRINGS["en"])
        for lang, texts in preview_texts.STRINGS.items():
            self.assertEqual(set(texts), keys, lang)
            for key, value in texts.items():
                want = set(re.findall(r"\{(\w+)\}", preview_texts.STRINGS["en"][key]))
                self.assertEqual(set(re.findall(r"\{(\w+)\}", value)), want, (lang, key))

    async def test_the_landing_page_in_every_language(self) -> None:
        for lang in preview_texts.LANGUAGES:
            with self.subTest(lang=lang):
                r = await self.client.get("/", params={"lang": lang})
                self.assertEqual(r.status_code, 200)
                self.assertIn(preview_texts.STRINGS[lang]["landing_title"], r.text)
                self.assertIn(f"/f/{demo_data.FIELD_SLUG}/", r.text)
                self.assertIn(f"/feedback?lang={lang}", r.text)
        r = await self.client.get("/", params={"lang": "de"})
        self.assertIn(f"/f/{demo_data.FIELD_SLUG}/?lang=de", r.text)  # the field pages have German too


class FeedbackTests(PreviewCase):
    async def test_a_message_is_stored_without_anything_about_the_visitor(self) -> None:
        self.at(1000)
        html, token = await self.form(**{"from": "/f/campo-demo/"})
        self.assertIn('value="/f/campo-demo/"', html)
        self.at(1010)
        r = await self.send(token, kind="usability", who="organiser", message="Two lines\nof <b>text</b>",
                            contact="rita@example.pt", **{"from": "/f/campo-demo/", "lang": "de"})
        self.assertEqual(r.headers["location"], "/feedback?lang=de&sent=1&from=/f/campo-demo/")
        row, = await self.rows()
        self.assertEqual((row["kind"], row["who"], row["message"], row["contact"], row["page"], row["lang"],
                          row["status"]),
                         ("usability", "organiser", "Two lines\nof <b>text</b>", "rita@example.pt", "/f/campo-demo/",
                          "de", "new"))
        self.assertEqual(set(row.keys()), {"id", "kind", "who", "message", "contact", "page", "lang", "status",
                                           "created_at", "updated_at"})
        audit = await self.fetch("SELECT ip_address, user_id, details FROM audit_log WHERE action = 'preview_feedback'")
        self.assertEqual((audit[0]["ip_address"], audit[0]["user_id"]), (None, None))
        self.assertNotIn("Two lines", audit[0]["details"])
        thanks = await self.client.get(r.headers["location"])
        self.assertIn(preview_texts.STRINGS["de"]["fb_done"], thanks.text)
        self.assertEqual(thanks.headers["cache-control"], "no-store")

    async def test_every_language_renders_the_form_and_accepts_it(self) -> None:
        t = 2000.0
        for lang in preview_texts.LANGUAGES:
            with self.subTest(lang=lang):
                self.at(t)
                html, token = await self.form(lang=lang)
                self.assertIn(preview_texts.STRINGS[lang]["fb_title"], html)
                for kind in ("good", "usability", "change", "bug", "other"):
                    self.assertIn(f'value="{kind}"', html)
                self.assertIn('maxlength="2000"', html)
                self.assertIn('name="website"', html)
                t += 10
                self.at(t)
                await self.send(token, lang=lang, message=f"ok {lang}")
        self.assertEqual([r["lang"] for r in await self.rows()], list(preview_texts.LANGUAGES))

    async def test_the_token_is_signed_and_timed(self) -> None:
        self.at(5000)
        _, token = await self.form()
        for why, tok, now in (("too early", token, 5001), ("missing", "", 5010), ("forged", "5000.deadbeef", 5010),
                              ("tampered time", "5001." + token.split(".")[1], 5010),
                              ("too old", token, 5000 + 2 * 3600 + 1)):
            with self.subTest(why=why):
                self.at(now)
                r = await self.send(tok, expect=400, message="keep this text")
                self.assertIn("keep this text", r.text)  # the visitor's text comes back with a new form
                self.assertIn(preview_texts.STRINGS["en"]["fb_expired"], r.text)
        self.assertEqual(await self.rows(), [])
        self.at(5010)
        await self.send(token)
        self.assertEqual(len(await self.rows()), 1)

    async def test_only_from_this_site(self) -> None:
        self.at(100)
        _, token = await self.form()
        self.at(110)
        for headers in ({"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"},
                        {"Origin": "https://evil.example"}, {"Origin": "null"}):
            with self.subTest(headers=headers):
                await self.send(token, expect=403, headers=headers)
        r = await self.client.post("/feedback", content=json.dumps({"t": token}),
                                   headers={"Content-Type": "application/json"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(await self.rows(), [])
        await self.send(token, headers={"Sec-Fetch-Site": "same-origin", "Origin": "https://server.test"})
        self.assertEqual(len(await self.rows()), 1)

    async def test_the_honeypot_thanks_the_bot_and_stores_nothing(self) -> None:
        self.at(100)
        _, token = await self.form()
        self.at(110)
        r = await self.send(token, website="http://spam.example")
        self.assertIn("sent=1", r.headers["location"])
        self.assertEqual(await self.rows(), [])

    async def test_what_is_refused(self) -> None:
        self.at(100)
        _, token = await self.form()
        self.at(110)
        for why, fields in (("no kind", {"kind": ""}), ("unknown kind", {"kind": "praise"}),
                            ("unknown who", {"who": "robot"}), ("empty", {"message": "   "}),
                            ("too long", {"message": "x" * 2001}), ("control", {"message": "a\x00b"}),
                            ("long contact", {"contact": "c" * 201}), ("contact lines", {"contact": "a\nb"})):
            with self.subTest(why=why):
                r = await self.send(token, expect=400, **fields)
                self.assertIn("2000", r.text)
        r = await self.client.post("/feedback", content="m=" + "x" * 20000, headers=HEADERS)
        self.assertEqual(r.status_code, 413)
        self.assertEqual(await self.rows(), [])
        await self.send(token, message="é" * 2000, contact="c" * 200)  # the limits are in characters
        self.assertEqual(len((await self.rows())[0]["message"]), 2000)

    async def test_the_limits(self) -> None:
        self.app.state.limits = Limits(clock=lambda: 0.0)
        self.at(100)
        _, token = await self.form()
        self.at(110)
        for _ in range(5):
            await self.send(token)
        r = await self.send(token, expect=429)
        self.assertIn("retry-after", r.headers)
        self.assertEqual(len(await self.rows()), 5)
        # All together: 300 a day, whoever sends.
        self.app.state.limits = Limits(clock=lambda: 0.0)
        for i in range(300):
            self.app.state.limits.feedback_total.hit("all")
        await self.send(token, expect=429)

    async def test_the_form_counts_towards_the_request_limit(self) -> None:
        from atalaia_server.ratelimit import RequestLimit  # noqa: PLC0415

        self.app.state.limits = Limits()
        self.app.state.limits.requests = RequestLimit(2, 60)
        for _ in range(2):
            self.assertEqual((await self.client.get("/feedback")).status_code, 200)
        self.assertEqual((await self.client.get("/feedback")).status_code, 429)

    async def test_a_from_path_is_only_a_plain_path(self) -> None:
        for bad in ("//evil.example", "https://evil.example", "/a?b=c", '/"><script>', "/" + "a" * 200):
            with self.subTest(bad=bad):
                html, _ = await self.form(**{"from": bad})
                self.assertNotIn("evil", html)
                self.assertNotIn("<script>", html)
                self.assertIn('name="from" value=""', html)


class AdminTests(PreviewCase):
    async def add(self, n: int = 3) -> None:
        for i in range(n):
            await self.fetch("INSERT INTO preview_feedback (kind, message, lang, created_at) VALUES "
                             "('change', $1, 'en', now() - make_interval(mins => $2))", f"message {i}", i)

    async def test_only_a_server_administrator_reads_it(self) -> None:
        await self.add()
        self.assertEqual((await self.client.get("/api/v1/admin/feedback")).status_code, 401)
        _, name, _ = await self.make_user()
        user = await self.auth(name)
        self.assertEqual((await self.client.get("/api/v1/admin/feedback", headers=user)).status_code, 403)
        for method in ("patch", "delete"):
            r = await getattr(self.client, method)("/api/v1/admin/feedback/00000000-0000-4000-8000-000000000000",
                                                    headers=user, **({"json": {"status": "seen"}} if method == "patch" else {}))
            self.assertEqual(r.status_code, 403)

    async def test_list_state_and_delete(self) -> None:
        await self.add()
        admin = await self.admin()
        r = await self.client.get("/api/v1/admin/feedback", headers=admin)
        body = r.json()
        self.assertEqual(r.headers["cache-control"], "no-store")
        self.assertEqual(body["counts"], {"new": 3, "seen": 0, "done": 0})
        self.assertEqual([f["message"] for f in body["feedback"]], ["message 0", "message 1", "message 2"])
        first = body["feedback"][0]["id"]
        r = await self.client.patch(f"/api/v1/admin/feedback/{first}", json={"status": "seen"}, headers=admin)
        self.assertEqual(r.json()["status"], "seen")
        self.assertEqual((await self.client.patch(f"/api/v1/admin/feedback/{first}", json={"status": "lost"},
                                                  headers=admin)).status_code, 400)
        r = await self.client.get("/api/v1/admin/feedback", params={"status": "seen"}, headers=admin)
        self.assertEqual([f["id"] for f in r.json()["feedback"]], [first])
        self.assertEqual((await self.client.get("/api/v1/admin/feedback", params={"status": "x"},
                                                headers=admin)).status_code, 400)
        self.assertEqual(len((await self.client.get("/api/v1/admin/feedback", params={"status": "all", "limit": "2"},
                                                    headers=admin)).json()["feedback"]), 2)
        self.assertEqual((await self.client.delete(f"/api/v1/admin/feedback/{first}", headers=admin)).status_code, 204)
        self.assertEqual((await self.client.delete(f"/api/v1/admin/feedback/{first}", headers=admin)).status_code, 404)
        self.assertEqual(len(await self.rows()), 2)

    async def test_the_staff_page_and_its_texts(self) -> None:
        r = await self.client.get("/staff/feedback?lang=en")
        self.assertEqual(r.status_code, 200)
        self.assertIn(STAFF["en"]["feedback_title"], r.text)
        self.assertIn('src="/static/staff/feedback.js"', r.text)
        home = await self.client.get("/staff/")
        self.assertIn('data-preview="1"', home.text)

    async def test_retention(self) -> None:
        await self.fetch("INSERT INTO preview_feedback (kind, message, contact, lang, created_at) VALUES "
                         "('good', 'new', 'a@example.pt', 'en', now()), "
                         "('good', 'old contact', 'b@example.pt', 'en', now() - interval '91 days'), "
                         "('good', 'ancient', 'c@example.pt', 'en', now() - interval '366 days')")
        async with self.app.state.sessionmaker() as db:
            counts = await personal_data.purge(db)
        self.assertEqual((counts["feedback_contacts"], counts["preview_feedback"]), (2, 1))  # the 366-day-old one is past both
        rows = {r["message"]: r["contact"] for r in await self.rows()}
        self.assertEqual(rows, {"new": "a@example.pt", "old contact": None})


class DemoTests(PreviewCase):
    async def load(self, now: Optional[datetime] = None) -> dict[str, Any]:
        async with self.app.state.sessionmaker() as db:
            return await demo_data.load(db, now)

    async def test_load_is_idempotent(self) -> None:
        now = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
        first = await self.load(now)
        self.assertEqual(first["field"], "created")
        self.assertEqual(set(first["games"].values()), {"created"})
        snapshot = {t: (await self.fetch(f"SELECT count(*) FROM {t}"))[0][0] for t in
                    ("fields", "clubs", "scheduled_games", "games", "game_events", "game_score_samples",
                     "game_node_scores", "game_nodes", "game_registrations", "field_presets", "field_scenarios")}
        self.assertEqual((snapshot["fields"], snapshot["clubs"], snapshot["games"], snapshot["scheduled_games"]),
                         (1, 2, 3, 5))
        self.assertGreater(snapshot["game_events"], 40)
        marker = await self.fetch("SELECT id, updated_at FROM scheduled_games ORDER BY id")
        again = await self.load(now)
        self.assertEqual(again["field"], "kept")
        self.assertEqual(set(again["games"].values()), {"kept"})
        for t, n in snapshot.items():
            self.assertEqual((await self.fetch(f"SELECT count(*) FROM {t}"))[0][0], n, t)
        # Nothing changed, so nothing was written (the caches stay valid): the done game moves with the clock only.
        after = await self.fetch("SELECT id, updated_at FROM scheduled_games ORDER BY id")
        changed = [a["id"] for a, b in zip(after, marker) if a["updated_at"] != b["updated_at"]]
        self.assertEqual(changed, [])

    async def test_what_a_visitor_sees(self) -> None:
        await self.load()
        slug = demo_data.FIELD_SLUG
        r = await self.client.get(f"/f/{slug}/?lang=pt")
        self.assertEqual(r.status_code, 200)
        for title in ("Domínio da Serra", "Bomba na Fábrica", "Noite de Último Elemento", "Treino de sábado"):
            self.assertIn(title, r.text)
        self.assertIn("Cancelado", r.text)
        self.assertIn('class="preview-banner"', r.text)
        feed = (await self.client.get(f"/f/{slug}/games.json")).json()
        self.assertEqual(len(feed["games"]), 5)  # the four to come and last Saturday's
        dom = next(g for g in feed["games"] if g["title"] == "Domínio da Serra" and g["status"] != "completed")
        self.assertTrue(dom["registration"]["open"])
        self.assertEqual(dom["registration"]["places_left"], 24 - 9)
        ics = await self.client.get(f"/f/{slug}/games.ics")
        self.assertIn("BEGIN:VEVENT", ics.text)
        page = await self.client.get(dom["url"].replace("https://server.test", "") + "/register?lang=en")
        self.assertEqual(page.status_code, 200)
        board = await self.client.get(f"/f/{slug}/scoreboard?lang=pt")
        self.assertIn("Corvos da Serra", board.text)
        self.assertIn("Raposas do Vale", board.text)
        self.assertIn("terminado", board.text)
        data = (await self.client.get(f"/f/{slug}/scoreboard.json")).json()
        scores = {t["team"]: t["score"] for t in data["game"]["teams"]}
        self.assertEqual(data["game"]["state"], "ended")
        self.assertGreater(min(scores.values()), 300)
        self.assertEqual(data["game"]["winner"], max(scores, key=lambda k: scores[k]))
        club = await self.client.get(f"/c/{demo_data.CLUB_SLUG}/")
        self.assertIn("Corvos da Serra", club.text)
        self.assertEqual((await self.client.get(f"/c/{demo_data.CLUB2_SLUG}/report")).status_code, 200)

    async def test_the_demo_stays_alive(self) -> None:
        now = datetime.now(timezone.utc)
        await self.load(now)
        again = await self.load(now + timedelta(hours=30))
        self.assertEqual(again["games"], {"a": "shifted", "b": "shifted", "c": "shifted"})
        data = (await self.client.get(f"/f/{demo_data.FIELD_SLUG}/scoreboard.json")).json()
        self.assertIsNotNone(data["game"])  # still the newest finished game, ended 25 minutes before the "now"
        ahead = datetime.fromisoformat(data["game"]["ended_at"]) - datetime.now(timezone.utc)
        self.assertLess(abs(ahead - (timedelta(hours=30) - demo_data.NEWEST_ENDED_AGO)), timedelta(minutes=5))
        # Samples and events moved with their game.
        late = await self.fetch("SELECT count(*) FROM game_events e JOIN games g ON g.id = e.game "
                                "WHERE e.received_at > g.ended_at + interval '1 minute'")
        self.assertEqual(late[0][0], 0)

    async def test_the_games_look_like_a_controller_synced_them(self) -> None:
        await self.load()
        admin = await self.admin()
        field_id = demo_data.demo_id("field")
        history = await self.client.get(f"/api/v1/fields/{field_id}/history", headers=admin)
        self.assertEqual(history.status_code, 200, history.text)
        games = history.json()["games"]
        self.assertEqual(len(games), 3)
        a = next(g for g in games if g["name"] == "Domínio da Serra, manhã")
        timeline = await self.client.get(f"/api/v1/games/{a['id']}/timeline", headers=admin)
        points = timeline.json()["points"]
        self.assertGreater(len(points), 10)
        last = points[-1]["totals"]
        self.assertEqual(last, {t["team"]: t["score"] for t in a["teams"]})
        log = (await self.client.get(f"/api/v1/games/{a['id']}/log", headers=admin)).json()
        self.assertIn("zone.captured", log["types"])
        self.assertEqual(log["types"]["game.end"], 1)
        devices = await self.client.get(f"/api/v1/fields/{field_id}/devices", headers=admin)
        self.assertEqual(devices.status_code, 200, devices.text)
        self.assertIn("battery_low", devices.text)
        presets = (await self.client.get(f"/api/v1/fields/{field_id}/presets", headers=admin)).json()
        self.assertEqual(len(presets), 2)

    async def test_only_invented_names(self) -> None:
        """Every name the loader writes is on this list; adding one means looking at it."""
        await self.load()
        names = {r[0] for r in await self.fetch(
            "SELECT name FROM fields UNION SELECT name FROM clubs UNION SELECT short_name FROM clubs "
            "UNION SELECT title FROM scheduled_games UNION SELECT name FROM games UNION SELECT name FROM game_nodes "
            "UNION SELECT display_name FROM game_registrations UNION SELECT name FROM field_presets")}
        allowed = re.compile(r"(Campo Demo da Serra Azul|Corvos( da Serra)?|Raposas( do Vale)?|Domínio da Serra.*|"
                             r"Bomba na Fábrica.*|Noite de Último Elemento|Treino de sábado|Caixa \w+|"
                             r"(" + "|".join(demo_data.CALLSIGNS) + r") \d+|Domínio, 90 minutos|Bomba, ronda curta)")
        self.assertEqual(sorted(n for n in names if n and not allowed.fullmatch(n)), [])

    async def test_reset_keeps_accounts_feedback_and_roles(self) -> None:
        await self.load()
        async with self.app.state.sessionmaker() as db:
            await demo_data.make_account(db, self.app.state.keys, "v1", "tester", demo_data.new_password(),
                                         totp.new_secret(), role="gm")
            await db.commit()
        await self.fetch("INSERT INTO preview_feedback (kind, message, lang) VALUES ('good', 'x', 'en')")
        await self.fetch("UPDATE scheduled_games SET title = 'Vandalised'")
        await self.fetch("DELETE FROM game_events")
        async with self.app.state.sessionmaker() as db:
            done = await demo_data.reset(db)
        self.assertEqual(done["roles_restored"], 1)
        self.assertEqual((await self.fetch("SELECT count(*) FROM scheduled_games WHERE title = 'Vandalised'"))[0][0], 0)
        self.assertGreater((await self.fetch("SELECT count(*) FROM game_events"))[0][0], 40)
        self.assertEqual((await self.fetch("SELECT count(*) FROM preview_feedback"))[0][0], 1)
        roles = await self.fetch("SELECT r.name FROM user_field_roles u JOIN roles r ON r.id = u.role_id")
        self.assertEqual([r[0] for r in roles], ["gm"])


class DemoLiveTests(PreviewCase):
    """The live demo's side on the site server (decisions DEMO-*): its own field, the API key for the simulated
    controller, the clean-up of old games, and the landing page's link to it."""

    DEMO_URL = "https://demo.example.org"

    def settings(self) -> Settings:
        s = super().settings()
        return Settings(allow_signup_without_notice=True, database_url=s.database_url, secret_key=s.secret_key, metrics_token=s.metrics_token,
                        db_timeout_s=2.0, purge_hour=None, preview=True, preview_demo_url=self.DEMO_URL + "/")

    async def live(self, key_file: Optional[Path] = None, **kw: Any) -> dict[str, Any]:
        async with self.app.state.sessionmaker() as db:
            return await demo_data.live(db, key_file, **kw)

    async def caller(self, key: str) -> Any:
        async with self.app.state.sessionmaker() as db:
            return await sync.authenticate(db, key)

    async def add_games(self, field_id: Any, n: int, now: datetime) -> None:
        async with self.app.state.sessionmaker() as db:
            for i in range(n):
                db.add(Game(field_id=field_id, game_id=100 + i, game_seed=7 + i, name=f"Demonstração {i}",
                            mode_id="org.atalaia.domination", teams=["red", "blue"], state="ended",
                            controller_created_at=now - timedelta(minutes=5 * i)))
            await db.commit()

    async def test_the_field_its_key_and_its_public_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            key_file = Path(tmp) / "sync-key"
            first = await self.live(key_file)
            self.assertEqual((first["field"], first["key"]), ("created", "made"))
            self.assertEqual(stat.S_IMODE(key_file.stat().st_mode), 0o600)
            key = key_file.read_text().strip()
            caller = await self.caller(key)
            self.assertEqual(caller.field_id, demo_data.demo_id("live-field"))
            # Again: nothing changes, the same key stays.
            again = await self.live(key_file)
            self.assertEqual((again["field"], again["key"]), ("kept", "kept"))
            self.assertEqual(key_file.read_text().strip(), key)
            # The file is lost (a new volume): a new key, and the old one is revoked.
            key_file.unlink()
            third = await self.live(key_file)
            self.assertEqual(third["key"], "made")
            self.assertIsNone(await self.caller(key))
            self.assertIsNotNone(await self.caller(key_file.read_text().strip()))
            live_keys = await self.fetch("SELECT revoked_at FROM field_api_keys ORDER BY created_at")
            self.assertEqual([r[0] is not None for r in live_keys], [True, False])
        r = await self.client.get(f"/f/{demo_data.LIVE_SLUG}/?lang=pt")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Campo Demo ao Vivo", r.text)
        self.assertEqual((await self.client.get(f"/f/{demo_data.LIVE_SLUG}/scoreboard.json")).status_code, 200)

    async def test_without_a_key_file_no_key_is_made(self) -> None:
        done = await self.live(None)
        self.assertNotIn("key", done)
        self.assertEqual((await self.fetch("SELECT count(*) FROM field_api_keys"))[0][0], 0)

    async def test_old_games_and_controllers_are_deleted_and_the_made_up_field_is_left_alone(self) -> None:
        now = datetime.now(timezone.utc)
        async with self.app.state.sessionmaker() as db:
            await demo_data.load(db, now)
        await self.live()
        field_id = demo_data.demo_id("live-field")
        await self.add_games(field_id, 15, now)
        async with self.app.state.sessionmaker() as db:
            db.add(Controller(field_id=field_id, controller_id=demo_data.demo_id("c-old"), version="x",
                              last_seen_at=now - timedelta(hours=7)))
            db.add(Controller(field_id=field_id, controller_id=demo_data.demo_id("c-now"), version="x", last_seen_at=now))
            await db.commit()
        done = await self.live(keep=5)
        self.assertEqual(done["deleted_games"], 10)
        kept = await self.fetch("SELECT name FROM games WHERE field_id = $1 ORDER BY controller_created_at DESC", field_id)
        self.assertEqual([r[0] for r in kept], [f"Demonstração {i}" for i in range(5)])
        controllers = await self.fetch("SELECT controller_id FROM controllers WHERE field_id = $1", field_id)
        self.assertEqual([r[0] for r in controllers], [demo_data.demo_id("c-now")])
        made_up = await self.fetch("SELECT count(*) FROM games WHERE field_id = $1", demo_data.demo_id("field"))
        self.assertEqual(made_up[0][0], 3)
        # `load` in its turn never touches the live field's games.
        async with self.app.state.sessionmaker() as db:
            await demo_data.load(db, now + timedelta(hours=1))
        self.assertEqual((await self.fetch("SELECT count(*) FROM games WHERE field_id = $1", field_id))[0][0], 5)

    async def test_reset_deletes_the_games_and_keeps_the_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            key_file = Path(tmp) / "sync-key"
            await self.live(key_file)
            await self.add_games(demo_data.demo_id("live-field"), 3, datetime.now(timezone.utc))
            done = await self.live(key_file, reset=True)
            self.assertEqual((done["deleted_games"], done["key"]), (3, "kept"))
            self.assertIsNotNone(await self.caller(key_file.read_text().strip()))
            self.assertEqual((await self.fetch("SELECT count(*) FROM games"))[0][0], 0)

    async def test_the_command_prints_no_secret(self) -> None:
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            key_file = Path(tmp) / "sync-key"
            args = argparse.Namespace(action="live", key_out=str(key_file), keep=12, reset=False)
            await cli.run_demo(self.settings(), args, out)
            self.assertNotIn(key_file.read_text().strip(), out.getvalue())
            self.assertIn("key=made", out.getvalue())

    async def test_the_landing_page_links_to_the_demo_in_every_language(self) -> None:
        for lang in ("pt", "en", "de", "zh-tw"):
            r = await self.client.get("/", params={"lang": lang})
            self.assertEqual(r.status_code, 200)
            self.assertIn(f'href="{self.DEMO_URL}/?lang={lang}"', r.text, lang)
            self.assertIn(f"/f/{demo_data.LIVE_SLUG}/", r.text, lang)
            self.assertIn(preview_texts.STRINGS[lang]["not_here_text_demo"], r.text.replace("&#x27;", "'"), lang)
        for lang, texts in preview_texts.STRINGS.items():
            for key in ("li_demo", "li_demo_d", "li_live", "li_live_d", "not_here_text_demo"):
                self.assertTrue(texts[key].strip(), (lang, key))


class DemoUrlTests(PreviewCase):
    async def test_a_preview_without_the_setting_links_nothing(self) -> None:
        r = await self.client.get("/?lang=en")
        self.assertNotIn(demo_data.LIVE_SLUG, r.text)

    def test_the_setting_is_checked(self) -> None:
        base = dict(database_url="postgresql+asyncpg://u:p@h/d", secret_key=SECRET_KEY)
        ok = Settings(**base, preview=True, preview_demo_url="https://demo.example.org/")
        self.assertEqual(ok.preview_demo_url, "https://demo.example.org")
        Settings(**base, preview=True, preview_demo_url="http://127.0.0.1:8001")
        for bad in ("http://demo.example.org", "https://demo.example.org/path", "https://u:p@demo.example.org",
                    "demo.example.org", "https://demo.example.org/?x=1"):
            with self.assertRaises(ConfigError, msg=bad):
                Settings(**base, preview=True, preview_demo_url=bad)
        with self.assertRaises(ConfigError):  # not a preview
            Settings(**base, preview_demo_url="https://demo.example.org")


class AccountTests(PreviewCase):
    async def test_a_generated_administrator_can_log_in_and_nothing_is_printed(self) -> None:
        import io  # noqa: PLC0415
        import os  # noqa: PLC0415
        import stat  # noqa: PLC0415
        import tempfile  # noqa: PLC0415

        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "admin.txt"
            await cli.generate_admin(self.settings(), "preview-admin", None, path, out)
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
            creds = dict(line.split(": ", 1) for line in path.read_text().splitlines() if ": " in line)
            for secret in (creds["password"], creds["totp_secret"]):
                self.assertNotIn(secret, out.getvalue())
            self.assertGreaterEqual(len(creds["password"]), 24)
            with self.assertRaises(cli.CommandError):  # it never overwrites
                await cli.generate_admin(self.settings(), "other", None, path, out)
            t = time.time() + 600
            self.app.state.clock = lambda: t
            body = await self.login("preview-admin", creds["password"], creds["totp_secret"])
            self.assertTrue(body["user"]["server_admin"])

    async def test_a_reviewer_gets_gm_on_the_demo_field(self) -> None:
        import argparse  # noqa: PLC0415
        import io  # noqa: PLC0415
        import tempfile  # noqa: PLC0415

        async with self.app.state.sessionmaker() as db:
            await demo_data.load(db)
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.txt"
            args = argparse.Namespace(action="reviewer", username="Tester-One", out=str(path))
            await cli.run_demo(self.settings(), args, out)
            creds = dict(line.split(": ", 1) for line in path.read_text().splitlines() if ": " in line)
            self.assertNotIn(creds["password"], out.getvalue())
            t = time.time() + 600
            self.app.state.clock = lambda: t
            body = await self.login("tester-one", creds["password"], creds["totp_secret"])
            self.assertTrue(body["mfa"] if "mfa" in body else True)
            headers = {"Authorization": f"Bearer {body['access_token']}"}
            fields = (await self.client.get("/api/v1/fields", headers=headers)).json()
            self.assertEqual([(f["slug"], f["my_roles"]) for f in fields], [(demo_data.FIELD_SLUG, ["gm"])])
            with self.assertRaises(cli.CommandError):
                await cli.run_demo(self.settings(), args, out)


class LanguageCase(AppTestCase):
    """ATALAIA_LANG_FROM_BROWSER and ATALAIA_DEFAULT_LANG (decision PV-9)."""

    from_browser = True
    default_lang = "pt"

    def settings(self) -> Settings:
        s = super().settings()
        return Settings(allow_signup_without_notice=True, database_url=s.database_url, secret_key=s.secret_key, metrics_token=s.metrics_token,
                        db_timeout_s=2.0, purge_hour=None, preview=True, lang_from_browser=self.from_browser,
                        default_lang=self.default_lang)

    async def lang(self, path: str, accept: str = "", client: Any = None) -> tuple[str, Any]:
        headers = {"Accept-Language": accept} if accept else {}
        r = await (client or self.client).get(path, headers=headers)
        return re.search(r'<html lang="([^"]+)"', r.text).group(1), r


class LanguageFromBrowserOnTests(LanguageCase):
    async def test_on_follows_the_browser(self) -> None:
        for path in ("/staff/login", "/f/nada/", "/feedback"):
            self.assertEqual((await self.lang(path, "en-US,en;q=0.9"))[0], "en", path)
            self.assertEqual((await self.lang(path))[0], "pt-PT" if path == "/staff/login" else "pt", path)
        lang, r = await self.lang("/staff/login?lang=pt", "en")
        self.assertEqual(lang, "pt-PT")
        self.assertNotIn("set-cookie", r.headers)  # nothing is remembered: the browser decides each time

    async def test_the_settings(self) -> None:
        with self.assertRaises(ConfigError):
            Settings(allow_signup_without_notice=True, database_url=self.database_url, secret_key=SECRET_KEY, default_lang="fr")
        env = {"ATALAIA_DATABASE_URL": self.database_url, "ATALAIA_SECRET_KEY": SECRET_KEY}
        self.assertTrue(Settings.from_env(env).lang_from_browser)
        self.assertEqual(Settings.from_env(env).default_lang, "pt")
        self.assertFalse(Settings.from_env({**env, "ATALAIA_LANG_FROM_BROWSER": "off"}).lang_from_browser)
        self.assertEqual(Settings.from_env({**env, "ATALAIA_DEFAULT_LANG": "EN"}).default_lang, "en")
        with self.assertRaises(ConfigError):
            Settings.from_env({**env, "ATALAIA_LANG_FROM_BROWSER": "maybe"})


class LanguageFromBrowserOffTests(LanguageCase):
    from_browser = False

    async def test_only_an_explicit_choice_counts_and_it_sticks(self) -> None:
        for path in ("/staff/login", "/f/nada/", "/feedback", "/"):
            with self.subTest(path=path):
                lang, r = await self.lang(path, "en-US,en;q=0.9")
                self.assertIn(lang, ("pt", "pt-PT"))
                self.assertNotIn("set-cookie", r.headers)
                self.assertIn("Cookie", r.headers["vary"])
        lang, r = await self.lang("/f/nada/?lang=en", "pt")
        self.assertEqual(lang, "en")
        cookie = r.headers["set-cookie"]
        self.assertTrue(cookie.startswith("lang=en;"), cookie)
        for attr in ("Secure", "SameSite=lax", "Path=/", "HttpOnly"):
            self.assertIn(attr, cookie)
        for path in ("/staff/login", "/f/nada/", "/feedback", "/"):  # the cookie is followed, whatever the browser says
            self.assertEqual((await self.lang(path, "pt"))[0], "en", path)
        self.assertEqual((await self.lang("/feedback?lang=de"))[0], "de")  # a new choice with the switcher
        self.assertEqual((await self.lang("/feedback"))[0], "de")
        self.assertEqual((await self.lang("/f/nada/"))[0], "de")  # the field pages have the four languages too
        # What is not a language is never kept or followed.
        other = self.other_client()
        r = await other.get("/f/nada/?lang=xx")
        self.assertNotIn("set-cookie", r.headers)
        lang, _ = await self.lang("/f/nada/", client=other)
        self.assertEqual(lang, "pt")
        other.cookies.set("lang", "xx")
        self.assertEqual((await self.lang("/f/nada/", client=other))[0], "pt")


class LanguageDefaultEnglishTests(LanguageCase):
    from_browser = False
    default_lang = "en"

    async def test_the_default_can_be_english(self) -> None:
        self.assertEqual((await self.lang("/f/nada/", "pt"))[0], "en")
        self.assertEqual((await self.lang("/feedback", "de"))[0], "en")
