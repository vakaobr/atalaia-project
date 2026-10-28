# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""APD membership: the rule, the membership a player declares and the verdict (protocol/apd.md).

Nothing here verifies a membership: the player declares it, the field's rule says what it needs and the
marshal decides. ``protocol/vectors/apd.json`` is run against these functions.
"""

from __future__ import annotations

import datetime
import json
import re
from pathlib import Path
from typing import Any, Optional

DATA = Path(__file__).resolve().parent / "data" / "apds.json"
ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
NUMBER_MAX = 32
ACCEPTED_MAX = 32
CUSTOM_MAX = 16
RULE_KEYS = ("accepted", "register", "checkin", "expiry", "custom")
STATUSES = ("missing", "not_accepted", "expired", "valid")


class ApdError(ValueError):
    """``code`` is ``apd_rule_invalid`` or ``apd_membership_invalid``."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def default_rule() -> dict[str, Any]:
    return {"accepted": None, "register": False, "checkin": False, "expiry": False, "custom": []}


def _printable(text: str) -> bool:
    return all(c.isprintable() for c in text)


def check_entry(e: Any, own: bool = True) -> dict[str, Any]:
    bad = "apd_rule_invalid"
    if not isinstance(e, dict) or set(e) - {"id", "name", "short_name", "website"} \
            or not {"id", "name", "short_name"} <= set(e):
        raise ApdError(bad, "entry")
    ident, name, short, site = e["id"], e["name"], e["short_name"], e.get("website")
    if not isinstance(ident, str) or not ID_RE.fullmatch(ident) or (own and not ident.startswith("x-")):
        raise ApdError(bad, "entry id")
    if not isinstance(name, str) or not 1 <= len(name) <= 96 or not _printable(name):
        raise ApdError(bad, "entry name")
    if not isinstance(short, str) or not 1 <= len(short) <= 16 or not _printable(short):
        raise ApdError(bad, "entry short_name")
    if site is not None and (not isinstance(site, str) or not site.startswith("https://") or len(site) > 128
                             or len(site) <= 8 or re.search(r"\s", site)):
        raise ApdError(bad, "entry website")
    return {"id": ident, "name": name, "short_name": short, "website": site}


def check_rule(value: Any) -> dict[str, Any]:
    """The normalised rule (all five keys) or ``ApdError``."""
    bad = "apd_rule_invalid"
    if value is None:
        return default_rule()
    if not isinstance(value, dict) or set(value) - set(RULE_KEYS):
        raise ApdError(bad, "keys")
    out = default_rule()
    for k in ("register", "checkin", "expiry"):
        if k in value:
            if not isinstance(value[k], bool):
                raise ApdError(bad, k)
            out[k] = value[k]
    acc = value.get("accepted")
    if acc is not None:
        if not isinstance(acc, list) or not 1 <= len(acc) <= ACCEPTED_MAX or len(set(map(str, acc))) != len(acc):
            raise ApdError(bad, "accepted")
        for a in acc:
            if not isinstance(a, str) or not ID_RE.fullmatch(a):
                raise ApdError(bad, "accepted id")
        out["accepted"] = list(acc)
    custom = value.get("custom", [])
    if not isinstance(custom, list) or len(custom) > CUSTOM_MAX:
        raise ApdError(bad, "custom")
    entries = [check_entry(e) for e in custom]
    if len({e["id"] for e in entries}) != len(entries):
        raise ApdError(bad, "custom duplicate")
    out["custom"] = entries
    return out


def check_membership(value: Any) -> dict[str, Any]:
    """``{apd, number, expires}`` with missing keys null, or ``ApdError``."""
    bad = "apd_membership_invalid"
    if not isinstance(value, dict) or set(value) - {"apd", "number", "expires"}:
        raise ApdError(bad, "keys")
    apd, number, expires = value.get("apd"), value.get("number"), value.get("expires")
    if apd is not None and (not isinstance(apd, str) or not ID_RE.fullmatch(apd)):
        raise ApdError(bad, "apd")
    if number is not None and (not isinstance(number, str) or not 1 <= len(number) <= NUMBER_MAX
                               or not _printable(number)):
        raise ApdError(bad, "number")
    if expires is not None:
        if not isinstance(expires, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", expires):
            raise ApdError(bad, "expires")
        try:
            d = datetime.date.fromisoformat(expires)
        except ValueError:
            raise ApdError(bad, "expires") from None
        if not 2000 <= d.year <= 2100:
            raise ApdError(bad, "expires")
    return {"apd": apd, "number": number, "expires": expires}


def status(rule: dict[str, Any], apd: Optional[str], number: Optional[str], expires: Optional[str],
           on: str) -> str:
    """The verdict (missing, not_accepted, expired, valid) for a normalised rule, on the local date ``on``."""
    if not number or (rule["expiry"] and not expires):
        return "missing"
    if rule["accepted"] is not None and (apd is None or apd not in rule["accepted"]):
        return "not_accepted"
    if rule["expiry"] and expires < on:  # type: ignore[operator]
        return "expired"
    return "valid"


def project_list() -> list[dict[str, Any]]:
    """The shipped list's entries (without ``source``)."""
    doc = json.loads(DATA.read_text(encoding="utf-8"))
    return [check_entry(e, own=False) for e in doc["apds"]]


def choices(rule: dict[str, Any]) -> list[dict[str, Any]]:
    """What a player may pick: the project's list, then the rule's own entries."""
    out = project_list()
    ids = {e["id"] for e in out}
    return out + [e for e in rule["custom"] if e["id"] not in ids]
