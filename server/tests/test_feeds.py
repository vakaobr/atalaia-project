# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The iCalendar writer and the JSON feed, with no database (also run by tools/check.sh).

The iCalendar checks use RFC 5545's own examples, copied from the RFC's text (the RFC Editor's
rfc5545.txt, SHA-256 c256f809479d98aa23d71bbd1658b3800ea9f13f41ca56e59c8d2de1b31cbfcb), with the
RFC's page indentation removed and each folded line's continuation kept as the RFC prints it:
the folding example of section 3.1, the TEXT examples of sections 3.3.11, 3.8.1.5 and 3.8.1.7,
the UTC DATE-TIME of section 3.3.5 and the VEVENT of section 4. The JSON feed is checked against
``server/schemas/games-feed-v1.schema.json`` with a small validator of the keywords the schema
uses (it refuses any other keyword, so the schema cannot silently outgrow it).
"""

from __future__ import annotations

import json
import re
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atalaia_server.feeds import FeedField, FeedGame, ical, json_feed  # noqa: E402

SCHEMA = Path(__file__).resolve().parents[1] / "schemas" / "games-feed-v1.schema.json"
CRLF = "\r\n"
UTC = timezone.utc

# RFC 5545 section 3.1 (page 9): a long line and one way to fold it.
RFC_LONG_LINE = "DESCRIPTION:This is a long description that exists on a long line."
RFC_FOLDED = CRLF.join([
    "DESCRIPTION:This is a lo",
    " ng description",
    "  that exists on a long line.",
])
# Section 3.3.11: a multiple-line TEXT value and its representation.
RFC_TEXT_VALUE = "Project XYZ Final Review\nConference Room - 3B\nCome Prepared."
RFC_TEXT_ESCAPED = r"Project XYZ Final Review\nConference Room - 3B\nCome Prepared."
# Section 3.8.1.5: DESCRIPTION, folded.
RFC_DESCRIPTION = CRLF.join([
    'DESCRIPTION:Meeting to provide technical review for "Phoenix"',
    r"  design.\nHappy Face Conference Room. Phoenix design team",
    r"  MUST attend this meeting.\nRSVP to team leader.",
])
# Section 3.8.1.7: LOCATION, with a comma, and with a quoted parameter (folded).
RFC_LOCATION = r"LOCATION:Conference Room - F123\, Bldg. 002"
RFC_LOCATION_ALTREP = CRLF.join([
    'LOCATION;ALTREP="http://xyzcorp.com/conf-rooms/f123.vcf":',
    r" Conference Room - F123\, Bldg. 002",
])
# Section 3.3.5: "January 19, 1998, at 0700 UTC".
RFC_UTC = "19980119T070000Z"
# Section 4: the first example, a three-day conference.
RFC_SECTION_4 = CRLF.join([
    "BEGIN:VCALENDAR",
    "PRODID:-//xyz Corp//NONSGML PDA Calendar Version 1.0//EN",
    "VERSION:2.0",
    "BEGIN:VEVENT",
    "DTSTAMP:19960704T120000Z",
    "UID:uid1@example.com",
    "ORGANIZER:mailto:jsmith@example.com",
    "DTSTART:19960918T143000Z",
    "DTEND:19960920T220000Z",
    "STATUS:CONFIRMED",
    "CATEGORIES:CONFERENCE",
    "SUMMARY:Networld+Interop Conference",
    "DESCRIPTION:Networld+Interop Conference",
    r"  and Exhibit\nAtlanta World Congress Center\n",
    r" Atlanta\, Georgia",
    "END:VEVENT",
    "END:VCALENDAR",
]) + CRLF

FIELD = FeedField(slug="campo-tejo", name="Campo Tejo", timezone="Europe/Lisbon", base_url="https://campo.example.pt",
                  host="campo.example.pt", description="Mata, 12 ha.", address="Estrada da Mata, Lisboa",
                  federation_label="FPA")
GAME_ID = uuid.UUID("0192f6a0-0000-7000-8000-000000000001")


def game(**over: Any) -> FeedGame:
    values: dict[str, Any] = dict(
        id=GAME_ID, title="Domingo no bosque", starts_at=datetime(2026, 11, 8, 9, 0, tzinfo=UTC),
        ends_at=datetime(2026, 11, 8, 13, 0, tzinfo=UTC), status="published",
        updated_at=datetime(2026, 10, 20, 10, 30, 15, 123456, tzinfo=UTC), sequence=0,
        description="Jogo de domínio.", location="Estrada da Mata, Lisboa", mode_id="org.atalaia.domination",
        teams=("red", "blue"), max_players=60, places_left=60,
        registration_opens_at=datetime(2026, 10, 25, 9, 0, tzinfo=UTC),
        registration_closes_at=datetime(2026, 11, 7, 20, 0, tzinfo=UTC), federation="required")
    values.update(over)
    return FeedGame(**values)


def physical_lines(body: str) -> list[str]:
    assert body.endswith(CRLF)
    return body[:-2].split(CRLF)


class RfcExampleTests(unittest.TestCase):
    """The writer against RFC 5545's own examples."""

    def test_unfolding_the_rfc_example(self) -> None:
        self.assertEqual(ical.unfold(RFC_FOLDED), RFC_LONG_LINE)
        self.assertEqual(ical.unfold(RFC_DESCRIPTION),
                         'DESCRIPTION:Meeting to provide technical review for "Phoenix" design.\\nHappy Face '
                         "Conference Room. Phoenix design team MUST attend this meeting.\\nRSVP to team leader.")

    def test_text_escaping_as_the_rfc_shows(self) -> None:
        self.assertEqual(ical.escape_text(RFC_TEXT_VALUE), RFC_TEXT_ESCAPED)
        self.assertEqual(ical.content_line("LOCATION", ical.escape_text("Conference Room - F123, Bldg. 002")),
                         RFC_LOCATION)
        phoenix = ('Meeting to provide technical review for "Phoenix" design.\nHappy Face Conference Room. '
                   "Phoenix design team MUST attend this meeting.\nRSVP to team leader.")
        line = ical.content_line("DESCRIPTION", ical.escape_text(phoenix))
        self.assertEqual(ical.unfold(line), ical.unfold(RFC_DESCRIPTION))  # same content line, folded our way

    def test_a_quoted_parameter(self) -> None:
        line = ical.content_line("LOCATION", ical.escape_text("Conference Room - F123, Bldg. 002"),
                                 [("ALTREP", "http://xyzcorp.com/conf-rooms/f123.vcf")])
        self.assertEqual(ical.unfold(line), ical.unfold(RFC_LOCATION_ALTREP))
        with self.assertRaises(ValueError):
            ical.content_line("X-TEST", "v", [("P", 'a"b')])

    def test_utc_date_time(self) -> None:
        self.assertEqual(ical.utc(datetime(1998, 1, 19, 7, 0, tzinfo=UTC)), RFC_UTC)
        lisbon_summer = timezone(timedelta(hours=1))
        self.assertEqual(ical.utc(datetime(1998, 1, 19, 8, 0, 0, 999999, tzinfo=lisbon_summer)), RFC_UTC)
        with self.assertRaises(ValueError):
            ical.utc(datetime(1998, 1, 19, 7, 0))  # a floating time is never written

    def test_the_section_4_event(self) -> None:
        """Our VEVENT for the RFC's conference holds every content line of the RFC's own, except the
        two properties a field's game never has (ORGANIZER, CATEGORIES)."""
        f = FeedField(slug="x", name="xyz", timezone="UTC", base_url="https://example.com", host="example.com")
        g = FeedGame(id=uuid.uuid4(), title="Networld+Interop Conference",
                     starts_at=datetime(1996, 9, 18, 14, 30, tzinfo=UTC),
                     ends_at=datetime(1996, 9, 20, 22, 0, tzinfo=UTC), status="published",
                     updated_at=datetime(1996, 7, 4, 12, 0, tzinfo=UTC))
        ours = ical.event_lines(g, f)
        ours_unfolded = {ical.unfold(line) for line in ours}
        rfc = ical.unfold(RFC_SECTION_4).split(CRLF)
        rfc_event = rfc[rfc.index("BEGIN:VEVENT"):rfc.index("END:VEVENT") + 1]
        expected = [line for line in rfc_event if not line.startswith(("ORGANIZER:", "CATEGORIES:", "UID:",
                                                                       "DESCRIPTION:"))]
        for line in expected:
            with self.subTest(line=line):
                self.assertIn(line, ours_unfolded)
        # The description is ours (it carries the game's page); the RFC's escapes the same way.
        rfc_description = next(line for line in rfc_event if line.startswith("DESCRIPTION:"))
        self.assertEqual(rfc_description, ical.content_line(
            "DESCRIPTION", ical.escape_text("Networld+Interop Conference and Exhibit\nAtlanta World Congress Center\n"
                                            "Atlanta, Georgia")).replace(CRLF + " ", ""))
        self.assertIn(f"UID:{g.id}@example.com", ours_unfolded)

    def test_the_rfc_calendar_reads_back_with_our_unfolding(self) -> None:
        lines = ical.unfold(RFC_SECTION_4).split(CRLF)
        self.assertEqual(lines[0], "BEGIN:VCALENDAR")
        self.assertEqual(lines[-1], "")  # the body ends with CRLF
        self.assertIn("DESCRIPTION:Networld+Interop Conference and Exhibit\\nAtlanta World Congress Center\\n"
                      "Atlanta\\, Georgia", lines)


class FoldingTests(unittest.TestCase):
    def test_short_lines_stay(self) -> None:
        self.assertEqual(ical.fold("SUMMARY:x"), "SUMMARY:x")
        line = "X:" + "a" * 73
        self.assertEqual(len(line.encode()), 75)
        self.assertEqual(ical.fold(line), line)

    def test_the_rfc_long_line(self) -> None:
        folded = ical.fold(RFC_LONG_LINE * 3)
        for part in folded.split(CRLF):
            self.assertLessEqual(len(part.encode("utf-8")), 75)
        self.assertTrue(all(p.startswith(" ") for p in folded.split(CRLF)[1:]))
        self.assertEqual(ical.unfold(folded), RFC_LONG_LINE * 3)

    def test_never_inside_a_utf8_sequence(self) -> None:
        for prefix in range(0, 8):
            for text in ("ção" * 40, "€" * 60, "🎯" * 40, "Último Elemento — marshal, equipa e squad " * 4):
                line = "DESCRIPTION:" + "x" * prefix + text
                with self.subTest(prefix=prefix, text=text[:6]):
                    folded = ical.fold(line)
                    for part in folded.split(CRLF):
                        self.assertLessEqual(len(part.encode("utf-8")), 75)
                        part.encode("utf-8").decode("utf-8")  # every physical line is whole UTF-8
                    self.assertEqual(ical.unfold(folded), line)

    def test_text_values(self) -> None:
        self.assertEqual(ical.escape_text("a\\b;c,d:e"), "a\\\\b\\;c\\,d:e")  # a colon is not escaped
        self.assertEqual(ical.escape_text("one\r\ntwo\rthree\nfour"), "one\\ntwo\\nthree\\nfour")
        self.assertEqual(ical.escape_text("bell\x07 tab\t del\x7f"), "bell tab\t del")


class CalendarTests(unittest.TestCase):
    def test_the_calendar(self) -> None:
        body = ical.calendar(FIELD, [game(), game(id=uuid.uuid4(), status="cancelled", sequence=2,
                                                  cancelled_reason="Chuva forte; campo fechado.")])
        self.assertTrue(body.endswith("END:VCALENDAR" + CRLF))
        self.assertNotIn("\n", body.replace(CRLF, ""))  # CRLF line ends only
        for line in physical_lines(body):
            self.assertLessEqual(len(line.encode("utf-8")), 75)
        lines = ical.unfold(body).split(CRLF)
        self.assertEqual(lines[:3], ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Atalaia//Site server//EN"])
        self.assertIn("NAME:Campo Tejo", lines)
        self.assertEqual(lines.count("BEGIN:VEVENT"), 2)
        self.assertNotIn("VTIMEZONE", body)
        first = lines[lines.index("BEGIN:VEVENT"):lines.index("END:VEVENT") + 1]
        self.assertEqual(first, [
            "BEGIN:VEVENT",
            f"UID:{GAME_ID}@campo.example.pt",
            "DTSTAMP:20261020T103015Z",
            "DTSTART:20261108T090000Z",
            "DTEND:20261108T130000Z",
            "SUMMARY:Domingo no bosque",
            f"DESCRIPTION:Jogo de domínio.\\n\\nhttps://campo.example.pt/f/campo-tejo/games/{GAME_ID}",
            "LOCATION:Estrada da Mata\\, Lisboa",
            f"URL:https://campo.example.pt/f/campo-tejo/games/{GAME_ID}",
            "STATUS:CONFIRMED",
            "SEQUENCE:0",
            "LAST-MODIFIED:20261020T103015Z",
            "END:VEVENT",
        ])
        self.assertIn("STATUS:CANCELLED", lines)
        self.assertIn("SEQUENCE:2", lines)
        self.assertTrue(any(line.startswith("DESCRIPTION:Jogo de domínio.\\n\\nCancelled / Cancelado: "
                                            "Chuva forte\\; campo fechado.") for line in lines))

    def test_the_same_games_give_the_same_bytes(self) -> None:
        self.assertEqual(ical.calendar(FIELD, [game()]), ical.calendar(FIELD, [game()]))
        self.assertNotEqual(ical.calendar(FIELD, [game()]), ical.calendar(FIELD, [game(sequence=1)]))

    def test_no_location_no_line(self) -> None:
        lines = ical.unfold(ical.calendar(FIELD, [game(location=None, description=None)])).split(CRLF)
        self.assertFalse(any(line.startswith("LOCATION") for line in lines))
        self.assertIn(f"DESCRIPTION:https://campo.example.pt/f/campo-tejo/games/{GAME_ID}", lines)

    def test_a_hostile_title_stays_one_property(self) -> None:
        body = ical.calendar(FIELD, [game(title="Jogo\r\nEND:VEVENT\r\nBEGIN:VEVENT;x,y")])
        lines = ical.unfold(body).split(CRLF)
        self.assertEqual(lines.count("BEGIN:VEVENT"), 1)
        self.assertIn("SUMMARY:Jogo\\nEND:VEVENT\\nBEGIN:VEVENT\\;x\\,y", lines)


class SchemaChecker:
    """The JSON Schema keywords the feed's schema uses (draft 2020-12), and no others."""

    KNOWN = {"$schema", "title", "description", "type", "required", "properties", "items", "$ref", "$defs",
             "const", "enum", "pattern", "minLength", "maxLength", "minimum", "format", "anyOf"}
    TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}

    def __init__(self, schema: dict[str, Any]) -> None:
        self.root = schema

    def check(self, value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
        unknown = set(schema) - self.KNOWN
        if unknown:
            raise AssertionError(f"the schema uses keywords the test does not check: {sorted(unknown)}")
        if "$ref" in schema:
            node: Any = self.root
            for part in schema["$ref"].lstrip("#/").split("/"):
                node = node[part]
            return self.check(value, node, path)
        errors: list[str] = []
        if "anyOf" in schema and not any(not self.check(value, s, path) for s in schema["anyOf"]):
            errors.append(f"{path}: matches none of anyOf")
        if "type" in schema:
            types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
            if not any(self._is(value, t) for t in types):
                return errors + [f"{path}: not {types}"]
        if "const" in schema and value != schema["const"]:
            errors.append(f"{path}: not {schema['const']!r}")
        if "enum" in schema and value not in schema["enum"]:
            errors.append(f"{path}: not one of {schema['enum']}")
        if isinstance(value, str):
            if "pattern" in schema and not re.search(schema["pattern"], value):
                errors.append(f"{path}: does not match {schema['pattern']}")
            if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", 10 ** 9):
                errors.append(f"{path}: length")
            errors += self._format(value, schema.get("format"), path)
        if isinstance(value, int) and not isinstance(value, bool) and value < schema.get("minimum", -10 ** 18):
            errors.append(f"{path}: below the minimum")
        if isinstance(value, dict):
            for name in schema.get("required", []):
                if name not in value:
                    errors.append(f"{path}: {name} is missing")
            for name, sub in schema.get("properties", {}).items():
                if name in value:
                    errors += self.check(value[name], sub, f"{path}.{name}")
        if isinstance(value, list) and "items" in schema:
            for i, item in enumerate(value):
                errors += self.check(item, schema["items"], f"{path}[{i}]")
        return errors

    def _is(self, value: Any, kind: str) -> bool:
        if kind == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        return isinstance(value, self.TYPES[kind]) and not (kind != "boolean" and isinstance(value, bool))

    @staticmethod
    def _format(value: str, fmt: Any, path: str) -> list[str]:
        try:
            if fmt == "uuid":
                uuid.UUID(value)
            elif fmt == "date-time":
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            elif fmt == "uri" and not re.match(r"^https?://[^\s/]+(/\S*)?$", value):
                raise ValueError(value)
        except ValueError:
            return [f"{path}: not a {fmt}"]
        return []


class JsonFeedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.checker = SchemaChecker(self.schema)

    def test_the_plans_shape(self) -> None:
        doc = json_feed.feed(FIELD, [game()])
        self.assertEqual((doc["format"], doc["version"]), ("atalaia.games", 1))
        self.assertEqual(doc["field"], {"slug": "campo-tejo", "name": "Campo Tejo", "timezone": "Europe/Lisbon",
                                        "url": "https://campo.example.pt/f/campo-tejo/",
                                        "description": "Mata, 12 ha.", "address": "Estrada da Mata, Lisboa"})
        g = doc["games"][0]
        self.assertEqual(g["starts_at"], "2026-11-08T09:00:00Z")
        self.assertEqual(g["updated_at"], "2026-10-20T10:30:15Z")
        self.assertEqual(g["registration"], {"opens_at": "2026-10-25T09:00:00Z", "closes_at": "2026-11-07T20:00:00Z",
                                             "open": False, "max_players": 60, "places_left": 60})
        self.assertEqual(g["requirements"], {"federation": "required", "federation_label": "FPA"})
        self.assertEqual(g["url"], f"https://campo.example.pt/f/campo-tejo/games/{GAME_ID}")
        self.assertEqual(g["ics"], f"https://campo.example.pt/f/campo-tejo/games/{GAME_ID}.ics")
        self.assertEqual(g["mode"], "org.atalaia.domination")

    def test_valid_against_the_schema(self) -> None:
        docs = [
            json_feed.feed(FIELD, []),
            json_feed.feed(FIELD, [game(), game(id=uuid.uuid4(), status="cancelled", cancelled_reason="Chuva",
                                                mode_id=None, max_players=None, places_left=None,
                                                registration_opens_at=None, registration_closes_at=None,
                                                federation="off", description=None, location=None, teams=())]),
        ]
        for doc in docs:
            with self.subTest(games=len(doc["games"])):
                text = json_feed.dumps(doc)
                self.assertEqual(self.checker.check(json.loads(text), self.schema), [])

    def test_the_schema_refuses_what_it_should(self) -> None:
        doc = json.loads(json_feed.dumps(json_feed.feed(FIELD, [game()])))
        bad = json.loads(json.dumps(doc))
        bad["games"][0]["status"] = "draft"
        bad["games"][0]["starts_at"] = "2026-11-08T09:00:00+01:00"
        del bad["games"][0]["registration"]["places_left"]
        errors = self.checker.check(bad, self.schema)
        self.assertEqual(len(errors), 3, errors)

    def test_no_personal_data(self) -> None:
        def keys(value: Any) -> set[str]:
            if isinstance(value, dict):
                return set(value) | {k for v in value.values() for k in keys(v)}
            if isinstance(value, list):
                return {k for v in value for k in keys(v)}
            return set()

        found = keys(json_feed.feed(FIELD, [game()]))
        self.assertEqual(found & {"player_id", "players", "registrations", "registered", "user_id", "username",
                                  "email", "display_name", "federation_number"}, set())

    def test_cancelled_reason_only_when_cancelled(self) -> None:
        self.assertIsNone(json_feed.game_json(game(cancelled_reason="x"), FIELD)["cancelled_reason"])
        self.assertEqual(json_feed.game_json(game(status="cancelled", cancelled_reason="x"), FIELD)["cancelled_reason"],
                         "x")
        self.assertIsNone(json_feed.game_json(game(federation="off"), FIELD)["requirements"]["federation_label"])


if __name__ == "__main__":
    unittest.main()
