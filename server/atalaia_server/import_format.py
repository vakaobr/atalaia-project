# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The registration import's format: reading a CSV or JSON list and checking each row (ADR-P4-12;
plan phase 17, decisions F20, S17-*). Plain Python, no database: also run by tools/check.sh.

**What is read.** A CSV file (RFC 4180, UTF-8, a header row; a UTF-8 byte order mark is allowed) or a
JSON array of objects, with only these names (``COLUMNS``):

    display_name       required, 1-32 characters, one line
    external_ref       the other platform's registration id (1-128 characters); recommended: rows
                       update by (source, external_ref), rows without it are added each time
    team_preference    one of the game's teams, or empty
    federation_number  1-32 characters; required, optional or dropped as the game says
    replicas           JSON: an array of {type, class, make_model?};
                       CSV: entries separated by "|", each "type:class[:make_model]"

Any other column (an email, a phone number, a birth date) is **not read**: its name is listed in the
preview as not imported, and its values never leave this module. Header names are matched without
case and surrounding spaces. A file is refused whole (``FileError``) when it is not what it says
(not UTF-8, bad quoting, not a JSON array, a column twice, no ``display_name`` column, too big); a row is
refused on its own (``RowError``, with a code) when one of its values is not valid.

**Limits.** At most ``MAX_BYTES`` (1 MiB) and ``MAX_ROWS`` (5,000, the controller's roster bound) rows.

**Exports.** ``csv_safe`` and ``csv_unsafe`` keep spreadsheets from reading a cell as a formula (the
controller's check-in export does the same): a value that starts with ``=``, ``+``, ``-``, ``@``, a tab
or a carriage return is written with a leading ``'``, and the import takes that ``'`` off again, so an
exported list imports back unchanged.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from atalaia_controller import sync_format

COLUMNS = ("display_name", "external_ref", "team_preference", "federation_number", "replicas")
MAX_BYTES = 1024 * 1024
MAX_ROWS = sync_format.MAX_ROSTER
NAME_MAX = 32
REF_MAX = 128
TEAM_MAX = 32
FEDERATION_MAX = 32
MAKE_MODEL_MAX = 64
MAX_REPLICAS = 20               # the controller's bound for [checkin] max_replicas
MAX_IGNORED = 50                # ignored column names listed in a preview
REPLICA_TYPES = sync_format.REPLICA_TYPES
FORMULA_START = "=+-@\t\r"
SOURCE = re.compile(r"[a-z0-9][a-z0-9._-]{0,31}")
RESERVED_SOURCES = frozenset({"site"})  # the site's own registrations (S16-1)


class FileError(ValueError):
    """The whole file is refused: ``code`` is the API's ``detail``; ``line`` where it went wrong, if known."""

    def __init__(self, code: str, line: Optional[int] = None) -> None:
        super().__init__(code)
        self.code, self.line = code, line


class RowError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class RawRow:
    """One row as read: ``values`` holds only the listed columns that were present, as strings (or None);
    ``replicas`` the raw entries (CSV: the column's text; JSON: the array)."""

    number: int                 # CSV: the record's number with the header as 1; JSON: the item's index from 1
    values: dict[str, Any]
    error: Optional[str] = None  # a row that could not even be read (a JSON item that is not an object)


@dataclass
class Parsed:
    format: str                  # "csv" or "json"
    columns: tuple[str, ...]     # the listed columns the file has
    ignored: list[str]           # the other columns' names, as in the file (at most MAX_IGNORED)
    ignored_more: int            # how many more were not listed
    rows: list[RawRow]


@dataclass(frozen=True)
class Rules:
    """What the scheduled game and its field accept (services/registration.py's rules)."""

    teams: tuple[str, ...]
    federation: str              # off, optional, required
    predeclare_replicas: bool
    classes: tuple[str, ...]     # the field's limit template's classes
    max_replicas: int


@dataclass
class Row:
    """A checked row: the values to store, which columns the file had (an update changes only those),
    and warnings."""

    number: int
    display_name: str
    external_ref: Optional[str]
    team_preference: Optional[str]
    federation_number: Optional[str]
    replicas: Optional[list[dict[str, Optional[str]]]]  # None: no replicas column in the file
    present: frozenset[str]
    warnings: list[str] = field(default_factory=list)


# --- formula injection --------------------------------------------------------------------

def csv_safe(value: Optional[str]) -> str:
    """A cell for an exported CSV: a leading ``'`` when a spreadsheet would read it as a formula."""
    if not value:
        return ""
    return "'" + value if value[0] in FORMULA_START else value


def csv_unsafe(value: str) -> str:
    """The import's inverse of ``csv_safe``: ``'=1`` reads as ``=1``; any other ``'`` stays."""
    if len(value) >= 2 and value[0] == "'" and value[1] in FORMULA_START:
        return value[1:]
    return value


# --- reading ------------------------------------------------------------------------------

def check_source(value: Any) -> str:
    """The import's source label (the platform's name, say): 1-32 of a-z, 0-9 and ``. _ -``, not ``site``."""
    if not isinstance(value, str) or not SOURCE.fullmatch(value) or value in RESERVED_SOURCES:
        raise FileError("source_invalid")
    return value


def _decode(data: bytes) -> str:
    if len(data) > MAX_BYTES:
        raise FileError("too_large")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise FileError("encoding_invalid") from None
    if text.startswith("﻿"):
        text = text[1:]
    if "\x00" in text:
        raise FileError("encoding_invalid")
    return text


def _split_columns(names: Iterable[str]) -> tuple[dict[str, int], list[str]]:
    known: dict[str, int] = {}
    ignored: list[str] = []
    for index, raw in enumerate(names):
        name = raw.strip().lower()
        if name in COLUMNS:
            if name in known:
                raise FileError("column_twice")
            known[name] = index
        else:
            ignored.append(raw.strip() or f"(column {index + 1})")
    if "display_name" not in known:
        raise FileError("display_name_column_missing")
    return known, ignored


def parse_csv(data: bytes) -> Parsed:
    text = _decode(data)
    reader = csv.reader(io.StringIO(text, newline=""), dialect="excel", strict=True)
    try:
        header = next(reader, None)
        if header is None:
            raise FileError("empty")
        known, ignored = _split_columns(header)
        rows: list[RawRow] = []
        number = 1
        for record in reader:
            number += 1
            if not record or record == [""]:  # a blank line
                continue
            if len(rows) >= MAX_ROWS:
                raise FileError("too_many_rows")
            if len(record) != len(header):
                rows.append(RawRow(number, {}, "row_length"))
                continue
            rows.append(RawRow(number, {name: csv_unsafe(record[i]) for name, i in known.items()}))
    except csv.Error:
        raise FileError("csv_invalid", reader.line_num) from None
    return Parsed("csv", tuple(c for c in COLUMNS if c in known), ignored[:MAX_IGNORED],
                  max(len(ignored) - MAX_IGNORED, 0), rows)


def _no_twice(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise FileError("json_invalid")
        out[key] = value
    return out


def _no_constant(name: str) -> Any:
    raise ValueError(f"{name} is not JSON")  # NaN, Infinity: Python's json reads them, RFC 8259 does not


def parse_json(data: bytes) -> Parsed:
    text = _decode(data)
    try:
        items = json.loads(text, object_pairs_hook=_no_twice, parse_constant=_no_constant)
    except (ValueError, RecursionError):
        raise FileError("json_invalid") from None
    if not isinstance(items, list):
        raise FileError("json_invalid")
    if len(items) > MAX_ROWS:
        raise FileError("too_many_rows")
    seen: dict[str, None] = {}
    ignored: dict[str, None] = {}
    rows: list[RawRow] = []
    for number, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            rows.append(RawRow(number, {}, "row_not_object"))
            continue
        values: dict[str, Any] = {}
        for key, value in item.items():
            name = key.strip().lower()
            if name in COLUMNS:
                if name in values:
                    rows.append(RawRow(number, {}, "column_twice"))
                    break
                values[name] = value
                seen[name] = None
            else:
                ignored[key.strip() or "(empty)"] = None
        else:
            rows.append(RawRow(number, values))
    names = list(ignored)
    return Parsed("json", tuple(c for c in COLUMNS if c in seen), names[:MAX_IGNORED],
                  max(len(names) - MAX_IGNORED, 0), rows)


def parse(data: bytes, fmt: str) -> Parsed:
    if fmt == "csv":
        return parse_csv(data)
    if fmt == "json":
        return parse_json(data)
    raise FileError("format_invalid")


# --- checking a row -----------------------------------------------------------------------

def _printable(value: str) -> bool:
    return all(not (ord(c) < 0x20 or 0x7F <= ord(c) <= 0x9F or 0xD800 <= ord(c) <= 0xDFFF) for c in value)


def _text(value: Any, code: str, limit: int, integers: bool = False) -> Optional[str]:
    """One line of 1..limit characters (trimmed), or None for empty; JSON integers too when ``integers``."""
    if value is None:
        return None
    if integers and isinstance(value, int) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str):
        raise RowError(code)
    text = value.strip()
    if not text:
        return None
    if len(text) > limit or not _printable(text):
        raise RowError(code)
    return text


def _replica_entries(value: Any) -> list[dict[str, Any]]:
    """The replicas column as entries {type, class, make_model}: a JSON array of objects, or the CSV
    text ``type:class[:make_model]|...`` (a make and model may hold ``:``; it cannot hold ``|``)."""
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        out = []
        for part in text.split("|"):
            pieces = part.strip().split(":", 2)
            if len(pieces) < 2:
                raise RowError("replicas_invalid")
            out.append({"type": pieces[0].strip().lower(), "class": pieces[1].strip(),
                        "make_model": pieces[2] if len(pieces) == 3 else None})
        return out
    if isinstance(value, list):
        for entry in value:
            if not isinstance(entry, dict) or set(entry) - {"type", "class", "make_model"}:
                raise RowError("replicas_invalid")
        return value
    raise RowError("replicas_invalid")


def check_replicas(value: Any, rules: Rules) -> list[dict[str, Optional[str]]]:
    entries = _replica_entries(value)
    if entries and not rules.predeclare_replicas:
        raise RowError("replicas_not_asked")
    if len(entries) > min(rules.max_replicas, MAX_REPLICAS):
        raise RowError("too_many_replicas")
    out = []
    for entry in entries:
        kind, cls = entry.get("type"), entry.get("class")
        if not isinstance(kind, str) or kind not in REPLICA_TYPES:
            raise RowError("replica_type_invalid")
        if not isinstance(cls, str) or cls not in rules.classes:
            raise RowError("replica_class_invalid")
        out.append({"type": kind, "class": cls,
                    "make_model": _text(entry.get("make_model"), "make_model_invalid", MAKE_MODEL_MAX)})
    return out


def check_row(raw: RawRow, rules: Rules) -> Row:
    """A row as it would be stored, or ``RowError``: the same limits as a registration on the site
    (services/registration.py) and the controller's check-in."""
    if raw.error:
        raise RowError(raw.error)
    v = raw.values
    name = _text(v.get("display_name"), "display_name_invalid", NAME_MAX)
    if name is None:
        raise RowError("display_name_invalid")
    ref = _text(v.get("external_ref"), "external_ref_invalid", REF_MAX, integers=True)
    team = _text(v.get("team_preference"), "team_preference_invalid", TEAM_MAX)
    if team is not None and team not in rules.teams:
        raise RowError("team_preference_invalid")
    number = _text(v.get("federation_number"), "federation_number_invalid", FEDERATION_MAX, integers=True)
    warnings = []
    if rules.federation == "off":
        if number is not None:
            warnings.append("federation_number_dropped")  # the game asks for none: not kept
        number = None
    elif rules.federation == "required" and number is None:
        raise RowError("federation_number_required")
    replicas = check_replicas(v.get("replicas"), rules) if "replicas" in v else None
    if ref is None:
        warnings.append("no_external_ref")
    return Row(raw.number, name, ref, team, number, replicas, frozenset(v), warnings)


# --- the export ---------------------------------------------------------------------------

EXPORT_COLUMNS = ("display_name", "external_ref", "team_preference", "federation_number", "replicas",
                  "registration_id", "player_id", "status", "source")


def replicas_text(replicas: Iterable[dict[str, Optional[str]]]) -> str:
    """The CSV form of the replicas column (``|`` in a make and model is written as ``/``)."""
    parts = []
    for r in replicas:
        part = f"{r['type']}:{r['class']}"
        if r.get("make_model"):
            part += ":" + str(r["make_model"]).replace("|", "/")
        parts.append(part)
    return "|".join(parts)


def export_csv(rows: Iterable[dict[str, Any]]) -> str:
    """The game's registrations as CSV (RFC 4180, CRLF), in the import's columns first, every text cell
    safe for spreadsheets."""
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    w.writerow(EXPORT_COLUMNS)
    for r in rows:
        w.writerow([csv_safe(r.get("display_name")), csv_safe(r.get("external_ref")),
                    csv_safe(r.get("team_preference")), csv_safe(r.get("federation_number")),
                    csv_safe(replicas_text(r.get("replicas") or ())), r.get("registration_id") or "",
                    r.get("player_id") or "", r.get("status") or "", csv_safe(r.get("source"))])
    return out.getvalue()
