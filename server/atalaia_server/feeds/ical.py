# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""An iCalendar writer (RFC 5545) for a field's games (ADR-P4-12, decision F18).

    GET /f/<slug>/games.ics            every published game of the field
    GET /f/<slug>/games/<id>.ics       one game

One ``VCALENDAR`` (``VERSION:2.0``, ``PRODID:-//Atalaia//Site server//EN``) with one
``VEVENT`` per game:

- ``UID``: the scheduled game's UUID ``@`` the site's host name, never reused;
- ``DTSTAMP`` and ``LAST-MODIFIED``: when the game was last changed. With no ``METHOD``
  property, ``DTSTAMP`` is "the date and time that the information associated with the
  calendar component was last revised" (RFC 5545 section 3.8.7.2), so the same game gives the
  same bytes until it changes and the ETag stays put;
- ``DTSTART`` and ``DTEND`` in UTC (the ``Z`` form, section 3.3.5), so no ``VTIMEZONE``;
- ``SUMMARY``, ``DESCRIPTION`` (plain text, with the game page's address), ``LOCATION`` when
  there is one, ``URL``, ``STATUS`` (``CONFIRMED`` or ``CANCELLED``), ``SEQUENCE``.

Content lines end in CRLF and are folded at 75 octets (section 3.1) without splitting a UTF-8
sequence; TEXT values escape backslash, semicolon, comma and newline (section 3.3.11) and lose
other control characters, which TEXT cannot hold. Plain Python (no third-party import).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional, Sequence

from . import FeedField, FeedGame

PRODID = "-//Atalaia//Site server//EN"
MEDIA_TYPE = "text/calendar; charset=utf-8"
CRLF = "\r\n"
LINE_OCTETS = 75  # excluding the CRLF (RFC 5545 section 3.1)


def escape_text(value: str) -> str:
    """A TEXT value (RFC 5545 section 3.3.11): ``\\`` ``;`` ``,`` escaped with a backslash, a line
    break (CRLF, CR or LF) as ``\\n``; a colon is not escaped; other control characters (which
    TSAFE-CHAR excludes) are dropped, HTAB kept."""
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
    return "".join(c for c in value if c == "\t" or not (ord(c) < 0x20 or ord(c) == 0x7F))


def utc(value: datetime) -> str:
    """A DATE-TIME in UTC (RFC 5545 section 3.3.5, form #2): ``19980119T070000Z``. Needs an aware
    time; seconds are the finest unit, so fractions are dropped."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("a time zone-aware datetime is needed")
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def fold(line: str) -> str:
    """One content line folded (RFC 5545 section 3.1): at most 75 octets per physical line, each
    continuation starting with one space, never inside a UTF-8 multi-octet sequence."""
    data = line.encode("utf-8")
    if len(data) <= LINE_OCTETS:
        return line
    parts: list[bytes] = []
    start, room = 0, LINE_OCTETS
    while len(data) - start > room:
        end = start + room
        while data[end] & 0xC0 == 0x80:  # a continuation octet: split before its sequence starts
            end -= 1
        parts.append(data[start:end])
        start, room = end, LINE_OCTETS - 1  # the leading space counts
    parts.append(data[start:])
    return (CRLF + " ").join(p.decode("utf-8") for p in parts)


def unfold(text: str) -> str:
    """Unfolding (RFC 5545 section 3.1): every CRLF followed by one space or tab is removed."""
    return text.replace(CRLF + " ", "").replace(CRLF + "\t", "")


def content_line(name: str, value: str, params: Sequence[tuple[str, str]] = ()) -> str:
    """``name *(";" param) ":" value``, folded, without the final CRLF. ``value`` is already in its
    value type's form (``escape_text`` for TEXT); a parameter value with ``:``, ``;`` or ``,`` is
    quoted (section 3.2), and one with a double quote or a control character is refused."""
    out = name.upper()
    for pname, pvalue in params:
        if '"' in pvalue or any(ord(c) < 0x20 and c != "\t" for c in pvalue):
            raise ValueError(f"parameter {pname} cannot hold {pvalue!r}")
        if any(c in pvalue for c in ":;,"):
            pvalue = f'"{pvalue}"'
        out += f";{pname.upper()}={pvalue}"
    return fold(f"{out}:{value}")


def _description(game: FeedGame, f: FeedField) -> str:
    parts = [game.description.strip()] if game.description and game.description.strip() else []
    if game.status == "cancelled" and game.cancelled_reason:
        parts.append(f"Cancelled / Cancelado: {game.cancelled_reason}")
    parts.append(game.page_url(f))
    return "\n\n".join(parts)


def event_lines(game: FeedGame, f: FeedField) -> list[str]:
    """The ``VEVENT`` of one game, as folded content lines."""
    stamp = utc(game.updated_at)
    lines = [
        "BEGIN:VEVENT",
        content_line("UID", f"{game.id}@{f.host}"),
        content_line("DTSTAMP", stamp),
        content_line("DTSTART", utc(game.starts_at)),
        content_line("DTEND", utc(game.ends_at)),
        content_line("SUMMARY", escape_text(game.title)),
        content_line("DESCRIPTION", escape_text(_description(game, f))),
    ]
    if game.location:
        lines.append(content_line("LOCATION", escape_text(game.location)))
    lines += [
        content_line("URL", game.page_url(f)),
        content_line("STATUS", "CANCELLED" if game.status == "cancelled" else "CONFIRMED"),
        content_line("SEQUENCE", str(game.sequence)),
        content_line("LAST-MODIFIED", stamp),
        "END:VEVENT",
    ]
    return lines


def calendar(f: FeedField, games: Iterable[FeedGame], name: Optional[str] = None) -> str:
    """The whole ``text/calendar`` body, CRLF line ends included. ``name`` (the calendar's name,
    RFC 7986's ``NAME`` and the common ``X-WR-CALNAME``) defaults to the field's name."""
    title = escape_text(name or f.name)
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", content_line("PRODID", PRODID),
             content_line("NAME", title), content_line("X-WR-CALNAME", title)]
    for game in games:
        lines += event_lines(game, f)
    lines.append("END:VCALENDAR")
    return CRLF.join(lines) + CRLF
