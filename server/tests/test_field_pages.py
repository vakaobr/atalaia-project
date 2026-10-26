# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The public field page, the game pages and the feeds on PostgreSQL 16 (ADR-P4-11, ADR-P4-12).

What the public sees and never sees (drafts, other fields, anyone who registered), pt-PT and
English, escaping, the security headers, the iCalendar and JSON feeds with their caching
headers, and the per-address limit. The iCalendar and JSON writers themselves are checked
against RFC 5545 and the schema in ``test_feeds``.
"""

from __future__ import annotations

import dataclasses
import json
import re
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from atalaia_server.config import Settings
from atalaia_server.feeds import ical
from atalaia_server.models import ScheduledGame
from atalaia_server.ratelimit import Limits, RequestLimit
from atalaia_server.security_headers import HEADERS
from atalaia_server.web import i18n

from .base import AppTestCase
from .test_feeds import SCHEMA, SchemaChecker

UTC = timezone.utc
PUBLIC = "https://campo.example.pt"
CRLF = "\r\n"


def hour(days: float, hours: float = 0) -> datetime:
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    return now + timedelta(days=days, hours=hours)


class PagesCase(AppTestCase):
    public_url: Optional[str] = PUBLIC

    def settings(self) -> Settings:
        return dataclasses.replace(super().settings(), public_url=self.public_url)

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.field_id = await self.make_field("campo-tejo", "Campo Tejo", public=True)

    async def make_field(self, slug: str, name: str, public: bool) -> uuid.UUID:
        return (await self.fetch(
            "INSERT INTO fields (name, slug, public_page, description, address_text, federation_label) "
            "VALUES ($1, $2, $3, 'Mata de pinheiros.', 'Estrada da Mata, Lisboa', 'FPA') RETURNING id",
            name, slug, public))[0][0]

    async def game(self, title: str = "Domingo no bosque", status: str = "published", start: Optional[datetime] = None,
                   hours: float = 4, field_id: Optional[uuid.UUID] = None, **values: Any) -> ScheduledGame:
        start = start or hour(10)
        async with self.app.state.sessionmaker() as db:
            game = ScheduledGame(field_id=field_id or self.field_id, title=title, starts_at=start,
                                 ends_at=start + timedelta(hours=hours), status=status, **values)
            db.add(game)
            await db.commit()
            await db.refresh(game)
            return game


class FieldPageTests(PagesCase):
    async def test_the_field_page(self) -> None:
        upcoming = await self.game("Domingo no bosque", start=datetime(2030, 11, 9, 9, 0, tzinfo=UTC))
        await self.game("Cancelado à chuva", status="cancelled", cancelled_reason="Chuva",
                        start=datetime(2030, 11, 16, 9, 0, tzinfo=UTC))
        await self.game("Rascunho secreto", status="draft")
        await self.game("Já foi", start=hour(-3))
        other = await self.make_field("arena", "Arena", public=True)
        await self.game("Jogo da Arena", field_id=other)
        r = await self.client.get("/f/campo-tejo/")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.headers["content-type"], "text/html; charset=utf-8")
        self.assertEqual((r.headers["content-language"], r.headers["vary"]), ("pt", "Accept-Language"))
        page = r.text
        self.assertIn('<html lang="pt">', page)
        self.assertIn("<h1>Campo Tejo</h1>", page)
        self.assertIn("Mata de pinheiros.", page)
        self.assertIn("Estrada da Mata, Lisboa", page)
        self.assertIn("Próximos jogos", page)
        self.assertIn("sábado, 9 de novembro de 2030, 09:00–13:00", page)  # Lisbon is UTC in November
        self.assertIn(f'href="/f/campo-tejo/games/{upcoming.id}"', page)
        self.assertIn("Cancelado à chuva", page)
        self.assertIn('<span class="badge">Cancelado</span>', page)
        for hidden in ("Rascunho secreto", "Já foi", "Jogo da Arena"):
            self.assertNotIn(hidden, page)
        self.assertLess(page.index("Domingo no bosque"), page.index("Cancelado à chuva"))
        self.assertIn('href="/f/campo-tejo/games.ics"', page)
        self.assertIn('href="/f/campo-tejo/games.json"', page)

    async def test_english(self) -> None:
        await self.game(start=datetime(2030, 7, 6, 8, 0, tzinfo=UTC))
        for kwargs in ({"headers": {"Accept-Language": "en-GB,en;q=0.9,pt;q=0.5"}}, {"params": {"lang": "en"}}):
            with self.subTest(**{k: str(v) for k, v in kwargs.items()}):
                r = await self.client.get("/f/campo-tejo/", **kwargs)
                self.assertIn('<html lang="en">', r.text)
                self.assertIn("Upcoming games", r.text)
                self.assertIn("Saturday 6 July 2030, 09:00–13:00", r.text)  # summer time in Lisbon
        r = await self.client.get("/f/campo-tejo/", params={"lang": "en"})
        self.assertRegex(r.text, r'href="/f/campo-tejo/games/[0-9a-f-]{36}\?lang=en"')  # the choice is kept
        self.assertIn('<a lang="pt" hreflang="pt" href="/f/campo-tejo/?lang=pt">Português</a>', r.text)

    async def test_german_and_chinese(self) -> None:
        await self.game(start=datetime(2030, 11, 9, 9, 0, tzinfo=UTC))
        switcher = ('<a lang="pt" hreflang="pt" href="/f/campo-tejo/?lang=pt">Português</a> '
                    '<a lang="en" hreflang="en" href="/f/campo-tejo/?lang=en">English</a> ')
        for kwargs in ({"params": {"lang": "de"}}, {"headers": {"Accept-Language": "de-AT,de;q=0.9,en;q=0.5"}}):
            with self.subTest(**{k: str(v) for k, v in kwargs.items()}):
                r = await self.client.get("/f/campo-tejo/", **kwargs)
                self.assertEqual(r.headers["content-language"], "de")
                self.assertIn('<html lang="de">', r.text)
                self.assertIn("Nächste Spiele", r.text)
                self.assertIn("Samstag, 9. November 2030, 09:00–13:00", r.text)
                self.assertIn(switcher + '<span lang="de" aria-current="true">Deutsch</span> <a lang="zh-Hant-TW" '
                              'hreflang="zh-Hant-TW" href="/f/campo-tejo/?lang=zh-tw">繁體中文（台灣）</a>', r.text)
        for kwargs in ({"params": {"lang": "zh-tw"}}, {"headers": {"Accept-Language": "zh-TW"}},
                       {"headers": {"Accept-Language": "zh-Hant-HK, en;q=0.5"}}):
            with self.subTest(**{k: str(v) for k, v in kwargs.items()}):
                r = await self.client.get("/f/campo-tejo/", **kwargs)
                self.assertEqual(r.headers["content-language"], "zh-Hant-TW")
                self.assertIn('<html lang="zh-Hant-TW">', r.text)
                self.assertIn("近期遊戲", r.text)
                self.assertIn("2030 年 11 月 9 日（星期六）09:00–13:00", r.text)
                self.assertIn(switcher + '<a lang="de" hreflang="de" href="/f/campo-tejo/?lang=de">Deutsch</a> '
                              '<span lang="zh-Hant-TW" aria-current="true">繁體中文（台灣）</span>', r.text)
        r = await self.client.get("/f/campo-tejo/", params={"lang": "zh-tw"})
        self.assertRegex(r.text, r'href="/f/campo-tejo/games/[0-9a-f-]{36}\?lang=zh-tw"')  # the choice is kept
        r = await self.client.get("/f/campo-tejo/", headers={"Accept-Language": "zh-CN, zh;q=0.9"})  # Simplified
        self.assertIn('<html lang="pt">', r.text)

    async def test_no_games(self) -> None:
        r = await self.client.get("/f/campo-tejo/")
        self.assertIn("Ainda não há jogos marcados.", r.text)

    async def test_off_or_missing_is_not_found(self) -> None:
        await self.make_field("privado", "Privado", public=False)
        for path in ("/f/privado/", "/f/nao-existe/", "/f/privado/games.ics", "/f/privado/games.json",
                     f"/f/campo-tejo/games/{uuid.uuid4()}", "/f/campo-tejo/games/nope", "/f/campo-tejo/games/x.ics",
                     f"/f/privado/games/{uuid.uuid4()}.ics"):
            with self.subTest(path=path):
                r = await self.client.get(path)
                self.assertEqual(r.status_code, 404)
                self.assertEqual(r.headers["cache-control"], "no-store")
        r = await self.client.get("/f/nao-existe/")
        self.assertIn("Página não encontrada", r.text)

    async def test_the_redirect(self) -> None:
        r = await self.client.get("/f/campo-tejo", params={"lang": "en"})
        self.assertEqual((r.status_code, r.headers["location"]), (308, "/f/campo-tejo/?lang=en"))
        r = await self.client.get("/f/Not_A_Slug")
        self.assertEqual(r.status_code, 404)

    async def test_security_headers_and_nothing_from_elsewhere(self) -> None:
        game = await self.game(description="Ver https://example.org")
        for path in ("/f/campo-tejo/", f"/f/campo-tejo/games/{game.id}"):
            with self.subTest(path=path):
                r = await self.client.get(path)
                for name, value in HEADERS:
                    self.assertEqual(r.headers[name], value)
                # No script to run, no style or image from another site, no inline style attribute.
                scripts = re.findall(r"<script[^>]*>", r.text)
                self.assertTrue(all(s == '<script type="application/ld+json">' for s in scripts), scripts)
                self.assertNotRegex(r.text, r"\b(src|srcset)=")
                self.assertNotIn("style=", r.text)
                self.assertNotIn("<style", r.text)
                for href in re.findall(r'<link[^>]*href="([^"]+)"', r.text):
                    self.assertTrue(href.startswith("/"), href)
        r = await self.client.get("/static/field.css")
        self.assertEqual((r.status_code, r.headers["content-type"]), (200, "text/css; charset=utf-8"))
        self.assertNotIn("url(", r.text)
        self.assertNotIn("@import", r.text)

    async def test_hostile_text_is_escaped(self) -> None:
        evil = '<script>alert(1)</script>"&'
        game = await self.game(evil, description=f"{evil}\n</script><script>x()</script>", location_text=evil)
        await self.fetch("UPDATE fields SET name = $1, description = $2 WHERE id = $3", evil, evil, self.field_id)
        for path in ("/f/campo-tejo/", f"/f/campo-tejo/games/{game.id}"):
            with self.subTest(path=path):
                r = await self.client.get(path)
                self.assertNotIn("<script>alert", r.text)
                self.assertNotIn("<script>x()", r.text)
                self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;&quot;&amp;", r.text)
        r = await self.client.get(f"/f/campo-tejo/games/{game.id}")
        block = re.search(r'<script type="application/ld\+json">(.*?)</script>', r.text, re.S)
        assert block is not None
        self.assertNotIn("<", block.group(1))
        self.assertEqual(json.loads(block.group(1))["name"], evil)


class GamePageTests(PagesCase):
    async def test_the_game_page(self) -> None:
        start = datetime(2030, 11, 9, 9, 0, tzinfo=UTC)
        game = await self.game(start=start, description="Jogo de domínio.\n\nTraz água.", mode_id="org.atalaia.domination",
                               teams=["red", "blue"], max_players=60, federation="required",
                               registration_opens_at=datetime(2030, 11, 1, 9, 0, tzinfo=UTC),
                               registration_closes_at=datetime(2030, 11, 8, 20, 0, tzinfo=UTC))
        r = await self.client.get(f"/f/campo-tejo/games/{game.id}")
        self.assertEqual(r.status_code, 200, r.text)
        page = r.text
        self.assertIn("<h1>Domingo no bosque</h1>", page)
        self.assertIn("<dt>Quando</dt><dd>sábado, 9 de novembro de 2030, 09:00–13:00 <small>(hora local, "
                      "Europe/Lisbon)</small></dd>", page)
        self.assertIn("<dt>Onde</dt><dd>Estrada da Mata, Lisboa</dd>", page)
        self.assertIn("<dt>Modo</dt><dd><code>org.atalaia.domination</code></dd>", page)
        self.assertIn("<dt>Equipas</dt><dd>red, blue</dd>", page)
        self.assertIn("<dt>Lugares</dt><dd>60</dd>", page)
        self.assertIn("<dt>Inscrições</dt><dd>abrem a sexta-feira, 1 de novembro de 2030, 09:00</dd>", page)
        self.assertIn("<dt>Número de federado (FPA)</dt><dd>obrigatório</dd>", page)
        self.assertIn("<p>Jogo de domínio.</p>\n<p>Traz água.</p>", page)
        self.assertIn(f'href="/f/campo-tejo/games/{game.id}.ics"', page)
        self.assertIn('<p class="back"><a href="/f/campo-tejo/">Todos os jogos de Campo Tejo</a></p>', page)
        ld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S).group(1))
        self.assertEqual(ld, {
            "@context": "https://schema.org", "@type": "Event", "name": "Domingo no bosque",
            "startDate": "2030-11-09T09:00:00+00:00", "endDate": "2030-11-09T13:00:00+00:00",
            "eventStatus": "https://schema.org/EventScheduled",
            "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
            "location": {"@type": "Place", "name": "Campo Tejo", "address": "Estrada da Mata, Lisboa"},
            "url": f"{PUBLIC}/f/campo-tejo/games/{game.id}",
            "organizer": {"@type": "Organization", "name": "Campo Tejo", "url": f"{PUBLIC}/f/campo-tejo/"},
            "description": "Jogo de domínio.\n\nTraz água.", "maximumAttendeeCapacity": 60})

    async def test_the_game_page_in_german_and_chinese(self) -> None:
        game = await self.game(start=datetime(2030, 11, 9, 9, 0, tzinfo=UTC), teams=["red", "blue"],
                               federation="required", registration_opens_at=datetime(2030, 11, 1, 9, 0, tzinfo=UTC))
        de = (await self.client.get(f"/f/campo-tejo/games/{game.id}", params={"lang": "de"})).text
        self.assertIn("<dt>Wann</dt><dd>Samstag, 9. November 2030, 09:00–13:00 <small>(Ortszeit, "
                      "Europe/Lisbon)</small></dd>", de)
        self.assertIn("<dt>Teams</dt><dd>red, blue</dd>", de)
        self.assertIn("<dt>Anmeldung</dt><dd>öffnet am Freitag, 1. November 2030, 09:00</dd>", de)
        self.assertIn("<dt>Verbandsnummer (FPA)</dt><dd>erforderlich</dd>", de)
        zh = (await self.client.get(f"/f/campo-tejo/games/{game.id}", params={"lang": "zh-tw"})).text
        self.assertIn("<dt>時間</dt><dd>2030 年 11 月 9 日（星期六）09:00–13:00<small>（當地時間，"
                      "Europe/Lisbon）</small></dd>", zh)
        self.assertIn("<dt>隊伍</dt><dd>red、blue</dd>", zh)
        self.assertIn("<dt>報名</dt><dd>2030 年 11 月 1 日（星期五）09:00 開放</dd>", zh)
        self.assertIn("<dt>協會會員編號（FPA）</dt><dd>必填</dd>", zh)
        cancelled = await self.game(status="cancelled", cancelled_reason="Chuva forte")
        zh = (await self.client.get(f"/f/campo-tejo/games/{cancelled.id}", params={"lang": "zh-tw"})).text
        self.assertIn("這場遊戲已取消。原因：Chuva forte", zh)
        two_days = await self.game(start=datetime(2030, 11, 9, 9, 0, tzinfo=UTC), hours=33)
        zh = (await self.client.get(f"/f/campo-tejo/games/{two_days.id}", params={"lang": "zh-tw"})).text
        self.assertIn("2030 年 11 月 9 日（星期六）09:00 至 2030 年 11 月 10 日（星期日）18:00", zh)

    async def test_cancelled_and_past(self) -> None:
        cancelled = await self.game(status="cancelled", cancelled_reason="Chuva forte")
        r = await self.client.get(f"/f/campo-tejo/games/{cancelled.id}", params={"lang": "en"})
        self.assertIn("This game has been cancelled. Reason: Chuva forte", r.text)
        self.assertIn('"eventStatus":"https://schema.org/EventCancelled"', r.text)
        past = await self.game(start=hour(-3), hours=2)
        r = await self.client.get(f"/f/campo-tejo/games/{past.id}")
        self.assertIn("Já terminou.", r.text)
        self.assertIn("<dt>Modo</dt><dd>a anunciar</dd>", r.text)
        self.assertIn("<dt>Lugares</dt><dd>sem limite</dd>", r.text)
        draft = await self.game(status="draft")
        r = await self.client.get(f"/f/campo-tejo/games/{draft.id}")
        self.assertEqual(r.status_code, 404)

    async def test_a_two_day_game(self) -> None:
        game = await self.game(start=datetime(2030, 11, 9, 9, 0, tzinfo=UTC), hours=33)
        r = await self.client.get(f"/f/campo-tejo/games/{game.id}", params={"lang": "en"})
        self.assertIn("Saturday 9 November 2030, 09:00 – Sunday 10 November 2030, 18:00", r.text)

    async def test_no_registrant_shown(self) -> None:
        game = await self.game(max_players=40)
        r = await self.client.get(f"/f/campo-tejo/games/{game.id}")
        self.assertNotIn("Inscrever", r.text)  # registration is plan phase 16
        self.assertIn("<dt>Lugares</dt><dd>40</dd>", r.text)


class FeedTests(PagesCase):
    async def test_the_calendar(self) -> None:
        game = await self.game(start=datetime(2030, 11, 9, 9, 0, tzinfo=UTC), description="Traz água; e luvas.")
        cancelled = await self.game("Cancelado", status="cancelled", cancelled_reason="Chuva", ical_sequence=1,
                                    start=hour(-5))
        await self.game("Há muito", start=hour(-40))  # ended over 30 days ago
        await self.game("Rascunho", status="draft")
        r = await self.client.get("/f/campo-tejo/games.ics")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "text/calendar; charset=utf-8")
        self.assertEqual(r.headers["access-control-allow-origin"], "*")
        self.assertEqual(r.headers["cache-control"], "public, max-age=300")
        body = r.content.decode("utf-8")
        self.assertTrue(body.startswith("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"))
        for line in body[:-2].split(CRLF):
            self.assertLessEqual(len(line.encode("utf-8")), 75)
        lines = ical.unfold(body).split(CRLF)
        self.assertEqual(lines.count("BEGIN:VEVENT"), 2)
        self.assertIn(f"UID:{game.id}@campo.example.pt", lines)
        self.assertIn("DTSTART:20301109T090000Z", lines)
        self.assertIn("DTEND:20301109T130000Z", lines)
        self.assertIn(f"URL:{PUBLIC}/f/campo-tejo/games/{game.id}", lines)
        self.assertIn("LOCATION:Estrada da Mata\\, Lisboa", lines)
        self.assertIn(f"UID:{cancelled.id}@campo.example.pt", lines)
        self.assertIn("STATUS:CANCELLED", lines)
        self.assertIn("SEQUENCE:1", lines)
        self.assertNotIn("Há muito", body)
        self.assertNotIn("Rascunho", body)
        self.assertTrue(any(line.startswith("DESCRIPTION:Traz água\\; e luvas.") for line in lines))

    async def test_one_game(self) -> None:
        game = await self.game()
        await self.game("Outro")
        r = await self.client.get(f"/f/campo-tejo/games/{game.id}.ics")
        self.assertEqual(r.status_code, 200)
        lines = ical.unfold(r.text).split(CRLF)
        self.assertEqual(lines.count("BEGIN:VEVENT"), 1)
        self.assertIn("NAME:Campo Tejo: Domingo no bosque", lines)

    async def test_caching(self) -> None:
        await self.game()
        r = await self.client.get("/f/campo-tejo/games.ics")
        etag, modified = r.headers["etag"], r.headers["last-modified"]
        self.assertRegex(etag, r'^"[0-9a-f]{32}"$')
        self.assertRegex(modified, r"^[A-Z][a-z]{2}, \d{2} [A-Z][a-z]{2} \d{4} \d{2}:\d{2}:\d{2} GMT$")
        r = await self.client.get("/f/campo-tejo/games.ics", headers={"If-None-Match": etag})
        self.assertEqual((r.status_code, r.content, r.headers["etag"]), (304, b"", etag))
        r = await self.client.get("/f/campo-tejo/games.ics", headers={"If-None-Match": '"other"'})
        self.assertEqual(r.status_code, 200)
        r = await self.client.get("/f/campo-tejo/games.ics", headers={"If-Modified-Since": modified})
        self.assertEqual(r.status_code, 304)
        r = await self.client.get("/f/campo-tejo/games.ics", headers={"If-Modified-Since": "Mon, 01 Jan 2024 00:00:00 GMT"})
        self.assertEqual(r.status_code, 200)
        # A change gives a new ETag.
        await self.game("Mais um")
        r = await self.client.get("/f/campo-tejo/games.ics", headers={"If-None-Match": etag})
        self.assertEqual(r.status_code, 200)
        self.assertNotEqual(r.headers["etag"], etag)

    async def test_the_json_feed(self) -> None:
        game = await self.game(start=datetime(2030, 11, 9, 9, 0, tzinfo=UTC), max_players=60, federation="optional",
                               registration_opens_at=hour(-1), registration_closes_at=datetime(2030, 11, 8, tzinfo=UTC),
                               mode_id="org.atalaia.domination", teams=["red", "blue"])
        await self.game("Cancelado", status="cancelled", cancelled_reason="Chuva",
                        start=datetime(2030, 12, 7, 9, 0, tzinfo=UTC))
        r = await self.client.get("/f/campo-tejo/games.json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "application/json")
        self.assertEqual(r.headers["access-control-allow-origin"], "*")
        doc = r.json()
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(SchemaChecker(schema).check(doc, schema), [])
        self.assertEqual(doc["field"]["url"], f"{PUBLIC}/f/campo-tejo/")
        g = doc["games"][0]
        self.assertEqual((g["id"], g["starts_at"], g["status"], g["mode"]),
                         (str(game.id), "2030-11-09T09:00:00Z", "published", "org.atalaia.domination"))
        # The window is open and nobody has registered yet (plan phase 16).
        self.assertEqual((g["registration"]["open"], g["registration"]["places_left"]), (True, 60))
        self.assertEqual(g["requirements"], {"federation": "optional", "federation_label": "FPA"})
        self.assertEqual(doc["games"][1]["cancelled_reason"], "Chuva")

    async def test_the_limit_covers_the_public_pages(self) -> None:
        limits = Limits()
        limits.requests = RequestLimit(2, 60)
        self.app.state.limits = limits
        for _ in range(2):
            self.assertEqual((await self.client.get("/f/campo-tejo/games.ics")).status_code, 200)
        r = await self.client.get("/f/campo-tejo/")
        self.assertEqual(r.status_code, 429)
        self.assertIn("retry-after", r.headers)


class LinksWithoutPublicUrlTests(PagesCase):
    public_url = None

    async def test_links_follow_the_request(self) -> None:
        game = await self.game()
        r = await self.client.get("/f/campo-tejo/games.json")
        self.assertEqual(r.json()["games"][0]["url"], f"https://server.test/f/campo-tejo/games/{game.id}")
        r = await self.client.get("/f/campo-tejo/games.ics")
        self.assertIn(f"UID:{game.id}@server.test", ical.unfold(r.text))


class HeadTests(PagesCase):
    """HEAD is GET without the body (RFC 9110 section 9.3.2): calendar clients poll with it (decision S16-10)."""

    async def test_head_answers_like_get(self) -> None:
        game = await self.game()
        for path in ("/f/campo-tejo/", "/f/campo-tejo/games.ics", "/f/campo-tejo/games.json",
                     f"/f/campo-tejo/games/{game.id}", f"/f/campo-tejo/games/{game.id}.ics",
                     f"/f/campo-tejo/games/{game.id}/register", "/static/field.css", "/f/nope/",
                     "/f/nope/games.ics", f"/f/campo-tejo/games/{uuid.uuid4()}"):
            with self.subTest(path=path):
                got = await self.client.get(path)
                head = await self.client.head(path)
                self.assertEqual(head.status_code, got.status_code)
                self.assertNotEqual(head.status_code, 405)
                self.assertEqual(head.content, b"")
                self.assertEqual(int(head.headers.get("content-length", "0")), len(got.content))
                if got.status_code == 404:  # never modified: no Last-Modified to differ by a second (flake fix)
                    self.assertNotIn("last-modified", got.headers)
                    self.assertNotIn("last-modified", head.headers)
                for name in ("etag", "last-modified", "cache-control", "content-type", "access-control-allow-origin",
                             "content-language"):
                    self.assertEqual(head.headers.get(name), got.headers.get(name), name)
                if got.status_code == 200 and "etag" in got.headers:
                    again = await self.client.head(path, headers={"If-None-Match": got.headers["etag"]})
                    self.assertEqual((again.status_code, again.content), (304, b""))
                    since = await self.client.head(path, headers={"If-Modified-Since": got.headers["last-modified"]})
                    self.assertEqual(since.status_code, 304)

    async def test_the_redirect_too(self) -> None:
        r = await self.client.head("/f/campo-tejo")
        self.assertEqual((r.status_code, r.headers["location"]), (308, "/f/campo-tejo/"))


class RegisterButtonTests(PagesCase):
    """The game page offers *Register* only while registration is open and places are left (plan phase 16)."""

    async def open_game(self, **values: Any) -> ScheduledGame:
        return await self.game(registration_opens_at=hour(-1), registration_closes_at=hour(5), **values)

    async def registrations(self, game: ScheduledGame, n: int, status: str = "registered") -> None:
        start = (await self.fetch("SELECT count(*) FROM game_registrations"))[0][0]
        for i in range(start, start + n):
            await self.fetch("INSERT INTO game_registrations (scheduled_game, field_id, player_id, display_name, status) "
                             "VALUES ($1, $2, $3, 'Alguém', $4)", game.id, self.field_id, f"p-{chr(97 + i) * 12}",
                             status)

    async def test_open_with_places(self) -> None:
        game = await self.open_game(max_players=2)
        page = (await self.client.get(f"/f/campo-tejo/games/{game.id}")).text
        self.assertIn(f'<a class="button" href="/f/campo-tejo/games/{game.id}/register">Fazer a inscrição</a>', page)
        self.assertIn("<dt>Lugares</dt><dd>2</dd>", page)
        r = await self.client.get(f"/f/campo-tejo/games/{game.id}/register")
        self.assertEqual(r.status_code, 200)
        self.assertIn("A inscrição faz-se com uma conta neste site, na app Atalaia.", r.text)
        self.assertIn("apaga-os 30 dias depois do jogo", r.text)
        # The link into the app (decision S17-10) and the address to paste there.
        link = "atalaia://register?site=https%3A%2F%2Fcampo.example.pt&amp;field=campo-tejo&amp;game=" + str(game.id)
        self.assertIn(f'<a class="button" href="{link}">Abrir na app Atalaia</a>', r.text)
        self.assertIn(f"<code>https://campo.example.pt/f/campo-tejo/games/{game.id}</code>", r.text)
        self.assertIn("Participante › Inscrições online", r.text)
        en_reg = (await self.client.get(f"/f/campo-tejo/games/{game.id}/register", params={"lang": "en"})).text
        self.assertIn(">Open in the Atalaia app</a>", en_reg)
        self.assertIn("Player › Online registration", en_reg)
        en = (await self.client.get(f"/f/campo-tejo/games/{game.id}", params={"lang": "en"})).text
        self.assertIn(f'href="/f/campo-tejo/games/{game.id}/register?lang=en">Register</a>', en)
        await self.registrations(game, 1)
        await self.registrations(game, 1, "cancelled")  # a cancelled one frees its place
        page = (await self.client.get(f"/f/campo-tejo/games/{game.id}")).text
        self.assertIn("<dt>Lugares</dt><dd>1</dd>", page)
        feed = (await self.client.get("/f/campo-tejo/games.json")).json()["games"][0]["registration"]
        self.assertEqual((feed["open"], feed["places_left"]), (True, 1))

    async def test_full(self) -> None:
        game = await self.open_game(max_players=1)
        first = await self.client.get("/f/campo-tejo/games.json")
        await self.registrations(game, 1)
        page = (await self.client.get(f"/f/campo-tejo/games/{game.id}")).text
        self.assertNotIn('class="button"', page)
        self.assertIn("<dt>Lugares</dt><dd>esgotados</dd>", page)
        r = await self.client.get("/f/campo-tejo/games.json", headers={"If-None-Match": first.headers["etag"]})
        self.assertEqual(r.status_code, 200)  # the places changed: so did the feed
        feed = r.json()["games"][0]["registration"]
        self.assertEqual((feed["open"], feed["places_left"]), (False, 0))
        r = await self.client.get(f"/f/campo-tejo/games/{game.id}/register")
        self.assertIn("ou já não há lugares", r.text)

    async def test_not_open(self) -> None:
        cases = {"no window": await self.game("Sem janela"),
                 "not yet": await self.game("Mais tarde", registration_opens_at=hour(2)),
                 "closed": await self.game("Fechadas", registration_opens_at=hour(-5), registration_closes_at=hour(-1)),
                 "cancelled": await self.game("Cancelado", status="cancelled", cancelled_reason="Chuva",
                                              registration_opens_at=hour(-1))}
        for name, game in cases.items():
            with self.subTest(name):
                page = (await self.client.get(f"/f/campo-tejo/games/{game.id}")).text
                self.assertNotIn('class="button"', page)
                feed = (await self.client.get("/f/campo-tejo/games.json")).json()["games"]
                self.assertFalse(next(g for g in feed if g["id"] == str(game.id))["registration"]["open"])


class LanguageTests(unittest.TestCase):
    def test_choose(self) -> None:
        self.assertEqual(i18n.choose(None, None), ("pt", False))
        self.assertEqual(i18n.choose("en", "pt-PT"), ("en", True))
        self.assertEqual(i18n.choose("fr", "en-US"), ("en", False))
        self.assertEqual(i18n.choose(None, "fr-FR, en;q=0.8, pt;q=0.9"), ("pt", False))
        self.assertEqual(i18n.choose(None, "en;q=0, pt-BR;q=0.1"), ("pt", False))
        self.assertEqual(i18n.choose(None, "fr, it"), ("pt", False))
        self.assertEqual(i18n.choose(None, "EN-gb;q=bad, en"), ("en", False))

    def test_choose_german_and_chinese(self) -> None:
        self.assertEqual(i18n.choose("de", "en"), ("de", True))
        self.assertEqual(i18n.choose("zh-tw", None), ("zh-tw", True))
        self.assertEqual(i18n.choose("zh-TW", "en"), ("en", False))  # ?lang= takes the code exactly
        for header in ("de", "de-DE", "DE-at", "de-CH;q=0.8, en;q=0.5", "fr, de;q=0.9, en;q=0.8"):
            with self.subTest(header=header):
                self.assertEqual(i18n.choose(None, header), ("de", False))
        for header in ("zh-TW", "zh-tw", "zh-Hant", "ZH-HANT", "zh-Hant-TW", "zh-Hant-HK", "zh-HK", "zh-MO",
                       "zh-CN;q=0.5, zh-TW;q=0.9", "zh, zh-TW;q=0.8, en;q=0.7"):
            with self.subTest(header=header):
                self.assertEqual(i18n.choose(None, header), ("zh-tw", False))
        # Simplified Chinese is not zh-tw: the next preference, or pt.
        for header, lang in (("zh", "pt"), ("zh-CN", "pt"), ("zh-Hans", "pt"), ("zh-Hans-CN", "pt"),
                             ("zh-SG", "pt"), ("zh-Hans-TW", "pt"), ("zh-CN, en;q=0.5", "en"),
                             ("zh-CN,zh;q=0.9,de;q=0.8", "de"), ("zh-TW;q=0", "pt")):
            with self.subTest(header=header):
                self.assertEqual(i18n.choose(None, header), (lang, False))

    def test_dates(self) -> None:
        t = datetime(2026, 3, 29, 1, 30, tzinfo=UTC)  # Lisbon moves to summer time at 01:00 UTC that day
        self.assertEqual(i18n.moment(t, "Europe/Lisbon", "pt"), "domingo, 29 de março de 2026, 02:30")
        self.assertEqual(i18n.moment(t, "Europe/Lisbon", "en"), "Sunday 29 March 2026, 02:30")
        self.assertEqual(i18n.moment(t, "Atlantic/Azores", "pt"), "domingo, 29 de março de 2026, 01:30")
        self.assertEqual(i18n.moment(t, "Europe/Lisbon", "de"), "Sonntag, 29. März 2026, 02:30")
        self.assertEqual(i18n.moment(t, "Europe/Lisbon", "zh-tw"), "2026 年 3 月 29 日（星期日）02:30")
        saturday = datetime(2026, 11, 8, 9, 0, tzinfo=UTC)
        self.assertEqual(i18n.date(saturday, "Europe/Lisbon", "de"), "Sonntag, 8. November 2026")
        self.assertEqual(i18n.date(saturday - timedelta(days=1), "Europe/Lisbon", "de"),
                         "Samstag, 7. November 2026")
        self.assertEqual(i18n.date(saturday - timedelta(days=1), "Asia/Taipei", "zh-tw"),
                         "2026 年 11 月 7 日（星期六）")
        end = saturday + timedelta(hours=4)
        self.assertEqual(i18n.span(saturday, end, "Asia/Taipei", "zh-tw"), "2026 年 11 月 8 日（星期日）17:00–21:00")
        self.assertEqual(i18n.span(saturday, end + timedelta(days=1), "Europe/Berlin", "de"),
                         "Sonntag, 8. November 2026, 10:00 – Montag, 9. November 2026, 14:00")

    def test_every_language_has_every_text(self) -> None:
        self.assertEqual(i18n.LANGUAGES, ("pt", "en", "de", "zh-tw"))
        self.assertEqual(set(i18n.LANGUAGE_NAMES), set(i18n.LANGUAGES))
        self.assertEqual(set(i18n.TAGS), set(i18n.LANGUAGES))
        for lang, strings in i18n.STRINGS.items():
            self.assertEqual(set(strings), set(i18n.STRINGS["en"]), lang)
            for key, text in strings.items():  # the same {names}
                self.assertEqual(set(re.findall(r"\{(\w+)\}", text)),
                                 set(re.findall(r"\{(\w+)\}", i18n.STRINGS["en"][key])), (lang, key))

    def test_german_and_chinese_follow_the_glossary(self) -> None:
        de = " ".join(i18n.STRINGS["de"].values())
        for word in ("Ihnen", "Ihre ", "Spieler ", "Spieler:in", "Spieler*in", "SpielerInnen"):  # "du"; neutral
            self.assertNotIn(word, de)
        for key, zh in i18n.STRINGS["zh-tw"].items():
            for letter in ("您", "妳", "他們", "她", "这", "个", "设", "场", "报", "们"):  # formal, gendered, Simplified
                self.assertNotIn(letter, zh, key)
            self.assertNotRegex(zh, r"[一-鿿][A-Za-z0-9]|[A-Za-z0-9][一-鿿]", key)  # a space
            self.assertNotRegex(zh, r"[一-鿿][,.:;!?()]", key)  # full-width punctuation after Han


if __name__ == "__main__":
    unittest.main()
