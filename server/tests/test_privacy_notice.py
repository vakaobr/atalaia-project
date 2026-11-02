# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The published privacy notice and showing it again when its version changes (decisions CONS-1 to CONS-6, LEG-*).

    python3 tools/docker_server.py test tests.test_privacy_notice
"""

from __future__ import annotations

import dataclasses
import html
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from atalaia_server import privacy_notice
from atalaia_server.config import ConfigError, Settings
from atalaia_server.web import i18n
from atalaia_server.web.consent_i18n import PUBLIC

from .base import PASSWORD, AppTestCase

V1, V2 = "campo-v1", "campo-v2"
NOTICE_PT = """<!--
SPDX-FileCopyrightText: x
-->

# Aviso de privacidade: Campo Tejo

> **Rascunho.** Texto do campo.

## 1. Quem trata os dados

O responsável é o **Campo Tejo**, [MORADA]. Contacto: [privacidade](mailto:privacidade@campo.example.pt) e
https://campo.example.pt.

- um item
- outro item com `código`
  - um item dentro
  - mais um
1. primeiro
2. segundo

| Dado | Prazo |
| --- | --- |
| Conta | até apagar |

---
Fim <script>alert(1)</script>.
"""
NOTICE_EN = "# Privacy notice\n\nThe operator is **Tejo Field**.\n"


def settings_with(directory: str | None, version: str = V1) -> dict[str, Any]:
    return {"privacy_notice_dir": directory, "privacy_notice_version": version}


class RenderTests(unittest.TestCase):
    def test_the_template_features(self) -> None:
        out = privacy_notice.render(NOTICE_PT)
        self.assertNotIn("SPDX", out)  # the leading comment is dropped
        self.assertIn("<h1>Aviso de privacidade: Campo Tejo</h1>", out)
        self.assertIn("<h2>1. Quem trata os dados</h2>", out)
        self.assertIn("<blockquote><p><strong>Rascunho.</strong> Texto do campo.</p></blockquote>", out)
        self.assertIn("<strong>Campo Tejo</strong>", out)
        self.assertIn('<a href="mailto:privacidade@campo.example.pt" rel="noopener noreferrer">privacidade</a>', out)
        self.assertIn("[MORADA]", out)  # a mark with no (address) stays text
        self.assertIn("<li>um item</li>", out)
        self.assertIn("<li>outro item com <code>código</code>\n<ul><li>um item dentro</li><li>mais um</li></ul></li>", out)
        self.assertIn("<ol><li>primeiro</li><li>segundo</li></ol>", out)
        self.assertIn("<table><thead><tr><th>Dado</th><th>Prazo</th></tr></thead><tbody><tr><td>Conta</td>"
                      "<td>até apagar</td></tr></tbody></table>", out)
        self.assertIn("<hr>", out)

    def test_nothing_the_file_holds_runs(self) -> None:
        out = privacy_notice.render(NOTICE_PT)
        self.assertNotIn("<script", out)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", out)
        for text in ("[x](javascript:alert(1))", "[x](data:text/html,hi)", "[x](//evil.example)", "[x](/relative)"):
            with self.subTest(text=text):
                self.assertNotIn("<a ", privacy_notice.render(text))
        quoted = privacy_notice.render('[a"b](https://example.pt/?q="><img src=x onerror=alert(1)>)')
        self.assertNotIn("<img", quoted)
        self.assertNotIn('"><', quoted)
        self.assertEqual(privacy_notice.render("<b>x</b> & y"), "<p>&lt;b&gt;x&lt;/b&gt; &amp; y</p>")
        self.assertEqual(privacy_notice.render("```\n<i>\n```"), "<pre><code>&lt;i&gt;</code></pre>")


class ConfigTests(unittest.TestCase):
    BASE = {"ATALAIA_DATABASE_URL": "postgresql+asyncpg://a:b@db:5432/a", "ATALAIA_SECRET_KEY": "k" * 43}

    def test_the_folder_is_optional(self) -> None:
        self.assertIsNone(Settings.from_env(self.BASE).privacy_notice_dir)
        self.assertEqual(Settings.from_env({**self.BASE, "ATALAIA_PRIVACY_NOTICE_DIR": " /privacy-notice "})
                         .privacy_notice_dir, "/privacy-notice")
        with self.assertRaisesRegex(ConfigError, "ATALAIA_PRIVACY_NOTICE_DIR"):
            Settings(database_url=self.BASE["ATALAIA_DATABASE_URL"], secret_key="k" * 43, privacy_notice_dir=" ")


class LoadTests(unittest.TestCase):
    def test_the_files_of_the_current_version_only(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            (base / privacy_notice.filename("pt", V1)).write_text(NOTICE_PT, encoding="utf-8")
            (base / privacy_notice.filename("en", V1)).write_text(NOTICE_EN, encoding="utf-8")
            (base / privacy_notice.filename("en", V2)).write_text("# v2\n", encoding="utf-8")
            (base / "privacy-notice-fr-campo-v1.md").write_text("# fr\n", encoding="utf-8")
            (base / "notes.md").write_text("not a notice", encoding="utf-8")
            self.assertEqual(privacy_notice.available(folder, V1), ("pt", "en"))
            self.assertEqual(privacy_notice.available(folder, V2), ("en",))
            self.assertEqual(privacy_notice.available(folder, "nope"), ())
            self.assertEqual(privacy_notice.load(folder, V1, "en").lang, "en")  # type: ignore[union-attr]
            self.assertEqual(privacy_notice.load(folder, V1, "de", "pt").lang, "pt")  # type: ignore[union-attr]
            self.assertEqual(privacy_notice.load(folder, V2, "de", "pt").lang, "en")  # type: ignore[union-attr]
            self.assertIsNone(privacy_notice.load(folder, "nope", "en"))
            self.assertIsNone(privacy_notice.load(None, V1, "en"))
            self.assertIsNone(privacy_notice.load(str(base / "missing"), V1, "en"))

    def test_a_file_that_cannot_be_read_counts_as_absent(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / privacy_notice.filename("pt", V1)).write_bytes(b"\xff\xfe not utf-8")
            (Path(folder) / privacy_notice.filename("en", V1)).write_text(NOTICE_EN, encoding="utf-8")
            with self.assertLogs("atalaia.privacy", "WARNING"):
                notice = privacy_notice.load(folder, V1, "pt", "pt")
            self.assertEqual(notice.lang if notice else None, "en")


class NoticeTestCase(AppTestCase):
    """An app whose notice folder holds a Portuguese and an English notice for V1 and an English one for V2."""

    async def asyncSetUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        base = Path(self.folder.name)
        (base / privacy_notice.filename("pt", V1)).write_text(NOTICE_PT, encoding="utf-8")
        (base / privacy_notice.filename("en", V1)).write_text(NOTICE_EN, encoding="utf-8")
        (base / privacy_notice.filename("en", V2)).write_text("# Privacy notice v2\n\nNew.\n", encoding="utf-8")
        await super().asyncSetUp()

    async def asyncTearDown(self) -> None:
        await super().asyncTearDown()
        self.folder.cleanup()

    def settings(self) -> Settings:
        return dataclasses.replace(super().settings(), **settings_with(self.folder.name))

    def set_version(self, version: str) -> None:
        self.app.state.settings = dataclasses.replace(self.app.state.settings, privacy_notice_version=version)

    async def register(self, username: str = "rita", **extra: Any) -> Any:
        return await self.client.post("/api/v1/auth/register", json={
            "username": username, "password": PASSWORD, "notice_seen": True, "age_confirmed": True, **extra})

    async def me(self, headers: dict[str, str]) -> dict[str, Any]:
        r = await self.client.get("/api/v1/me", headers=headers)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()


class PublishTests(NoticeTestCase):
    async def test_the_json_and_the_language_it_falls_back_to(self) -> None:
        r = await self.client.get("/api/v1/privacy-notice", params={"lang": "en"})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual((body["version"], body["lang"], body["requested_lang"], body["available"]),
                         (V1, "en", "en", ["pt", "en"]))
        self.assertEqual(body["markdown"], NOTICE_EN)
        self.assertEqual(body["html"], privacy_notice.render(NOTICE_EN))
        self.assertEqual(body["url"], "https://server.test/privacy?lang=en")
        self.assertIn("max-age", r.headers["cache-control"])
        # German is asked for and there is none: the default language (pt) is served, and says so.
        body = (await self.client.get("/api/v1/privacy-notice", params={"lang": "de"})).json()
        self.assertEqual((body["lang"], body["requested_lang"]), ("pt", "de"))
        # Accept-Language is followed without ?lang=.
        body = (await self.client.get("/api/v1/privacy-notice", headers={"Accept-Language": "en-GB"})).json()
        self.assertEqual(body["lang"], "en")
        self.assertNotIn("<script", body["html"])

    async def test_it_is_public_and_follows_the_version(self) -> None:
        self.set_version(V2)
        body = (await self.client.get("/api/v1/privacy-notice", params={"lang": "pt"})).json()
        self.assertEqual((body["version"], body["lang"], body["available"]), (V2, "en", ["en"]))
        self.set_version("campo-v3")  # no file for it: not published, whatever older files there are
        r = await self.client.get("/api/v1/privacy-notice")
        self.assertEqual((r.status_code, r.json()["detail"]), (404, "privacy_notice_not_published"))

    async def test_nothing_is_published_without_a_folder(self) -> None:
        self.app.state.settings = dataclasses.replace(self.app.state.settings, privacy_notice_dir=None)
        r = await self.client.get("/api/v1/privacy-notice")
        self.assertEqual((r.status_code, r.json()["detail"]), (404, "privacy_notice_not_published"))
        page = await self.client.get("/privacy", params={"lang": "en"})
        self.assertEqual(page.status_code, 404)
        self.assertIn(html.escape(PUBLIC["en"]["privacy_none"]), page.text)

    async def test_the_page_in_every_language(self) -> None:
        for lang in i18n.LANGUAGES:
            with self.subTest(lang=lang):
                r = await self.client.get("/privacy", params={"lang": lang})
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual(r.headers["content-type"], "text/html; charset=utf-8")
                self.assertIn(f'<html lang="{i18n.TAGS[lang]}">', r.text)
                self.assertIn(PUBLIC[lang]["privacy_version"].format(version=V1), r.text)
                self.assertIn(html.escape(PUBLIC[lang]["privacy_footer"]), r.text)
                self.assertNotIn("<script", r.text)
                self.assertNotIn("javascript:", r.text)
                self.assertIn("script-src 'self'", r.headers["content-security-policy"])
                if lang == "pt":
                    self.assertIn("<h2>1. Quem trata os dados</h2>", r.text)
                    self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", r.text)
                    self.assertNotIn("não existe", r.text)
                elif lang == "en":
                    self.assertIn("<strong>Tejo Field</strong>", r.text)
                else:  # no German or Chinese file: the default language's text, with a line in the page's language
                    self.assertIn('<article class="privacy" lang="pt">', r.text)
                    self.assertIn(html.escape(PUBLIC[lang]["privacy_lang_fallback"].format(
                        requested=i18n.LANGUAGE_NAMES[lang], shown=i18n.LANGUAGE_NAMES["pt"])), r.text)
        head = await self.client.head("/privacy", params={"lang": "en"})
        self.assertEqual(head.status_code, 200)

    async def test_the_page_texts_follow_the_house_rules(self) -> None:
        self.assertEqual(set(PUBLIC), set(i18n.LANGUAGES))
        for lang, texts in PUBLIC.items():
            self.assertEqual(set(texts), set(PUBLIC["en"]), lang)


class NoticeAgainTests(NoticeTestCase):
    """LEG-*: the account rests on the contract (Art. 6(1)(b)). The notice shown at sign-up and later is recorded as
    information given, not as a consent, and nothing about it can be withdrawn."""

    async def test_a_new_account_is_current_and_a_new_version_makes_it_outdated(self) -> None:
        r = await self.register()
        self.assertEqual(r.status_code, 201, r.text)
        headers = await self.auth("rita")
        notice = (await self.me(headers))["notice"]
        self.assertEqual((notice["status"], notice["version"], notice["current_version"], notice["notice_published"]),
                         ("current", V1, V1, True))
        self.assertNotIn("consent", await self.me(headers))
        self.set_version(V2)
        notice = (await self.me(headers))["notice"]
        self.assertEqual((notice["status"], notice["version"], notice["current_version"]), ("outdated", V1, V2))

    async def test_the_notice_shown_again(self) -> None:
        await self.register()
        headers = await self.auth("rita")
        before = (await self.fetch("SELECT gdpr_consent_at FROM users WHERE username = 'rita'"))[0][0]
        self.set_version(V2)
        # The version the person was shown is not the current one: refused, with the code and the current version.
        r = await self.client.post("/api/v1/me/notice", json={"notice_version": V1}, headers=headers)
        self.assertEqual((r.status_code, r.json()), (409, {"detail": "notice_version_changed", "current_version": V2}))
        self.assertEqual((await self.me(headers))["notice"]["status"], "outdated")
        r = await self.client.post("/api/v1/me/notice", json={"notice_version": V2}, headers=headers)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["status"], r.json()["version"]), ("current", V2))
        self.assertEqual((await self.me(headers))["notice"]["status"], "current")
        rows = await self.fetch("SELECT notice_version, kind, age_confirmed FROM notice_records ORDER BY recorded_at")
        self.assertEqual([(r["notice_version"], r["kind"], r["age_confirmed"]) for r in rows],
                         [(V1, "signup", True), (V2, "shown_again", False)])
        after = (await self.fetch("SELECT gdpr_consent_at FROM users WHERE username = 'rita'"))[0][0]
        self.assertGreater(after, before)
        audit = await self.fetch("SELECT details FROM audit_log WHERE action = 'notice_shown_again'")
        self.assertEqual(json.loads(audit[0]["details"]), {"from": V1, "to": V2})
        # Again: nothing changes, nothing is logged twice.
        r = await self.client.post("/api/v1/me/notice", json={"notice_version": V2}, headers=headers)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(await self.fetch("SELECT 1 FROM notice_records")), 2)
        self.assertEqual(len(await self.fetch("SELECT 1 FROM audit_log WHERE action = 'notice_shown_again'")), 1)
        # Nothing here is a consent, and nothing can be withdrawn: no consent rows, no withdraw route.
        self.assertEqual(await self.fetch("SELECT 1 FROM consents"), [])
        self.assertEqual((await self.client.delete("/api/v1/me/notice", headers=headers)).status_code, 405)
        self.assertIn((await self.client.delete("/api/v1/me/consents/account", headers=headers)).status_code, (404, 405))
        # The access answer keeps both records, oldest first.
        data = (await self.client.get("/api/v1/me/data", headers=headers)).json()
        self.assertEqual([(n["notice_version"], n["kind"]) for n in data["notices"]],
                         [(V1, "signup"), (V2, "shown_again")])
        self.assertEqual(data["consents"], [])

    async def test_an_account_with_no_record_is_missing_and_can_acknowledge(self) -> None:
        _, username, _ = await self.make_user("ana")
        headers = await self.auth(username)
        self.assertEqual((await self.me(headers))["notice"]["status"], "missing")
        r = await self.client.post("/api/v1/me/notice", json={"notice_version": V1}, headers=headers)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((await self.me(headers))["notice"]["status"], "current")
        audit = await self.fetch("SELECT details FROM audit_log WHERE action = 'notice_shown_again'")
        self.assertEqual(json.loads(audit[0]["details"])["from"], None)

    async def test_it_needs_a_session_and_a_body(self) -> None:
        r = await self.client.post("/api/v1/me/notice", json={"notice_version": V1})
        self.assertEqual(r.status_code, 401)
        await self.register()
        headers = await self.auth("rita")
        for body in ({}, {"notice_version": V1, "x": 1}, {"notice_version": "x" * 65}):
            r = await self.client.post("/api/v1/me/notice", json=body, headers=headers)
            self.assertEqual(r.status_code, 422, body)

    async def test_registering_names_the_notice_it_showed(self) -> None:
        r = await self.register("old", notice_version=V2)  # the notice changed after the app fetched it
        self.assertEqual((r.status_code, r.json()), (409, {"detail": "notice_version_changed",
                                                           "current_version": V1}))
        self.assertEqual(await self.fetch("SELECT 1 FROM users WHERE username = 'old'"), [])
        r = await self.register("new", notice_version=V1)
        self.assertEqual(r.status_code, 201, r.text)
        r = await self.register("plain")  # the field the existing clients do not send stays optional
        self.assertEqual(r.status_code, 201, r.text)

    async def test_the_notice_state_without_a_published_notice(self) -> None:
        await self.register()
        headers = await self.auth("rita")
        self.set_version("campo-v9")
        notice = (await self.me(headers))["notice"]
        self.assertEqual((notice["status"], notice["notice_published"]), ("outdated", False))


class RetentionColumnTests(AppTestCase):
    async def test_the_per_account_retention_field_is_gone(self) -> None:
        columns = {r["column_name"] for r in await self.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'users'")}
        self.assertNotIn("data_retention_days", columns)
        await self.make_user("rita")
        headers = await self.auth("rita")
        data = (await self.client.get("/api/v1/me/data", headers=headers)).json()
        self.assertNotIn("data_retention_days", data["user"])


if __name__ == "__main__":
    unittest.main()
