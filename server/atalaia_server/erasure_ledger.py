# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The erasure ledger (PRIV-4): what was erased, kept outside the database so that a restore does not bring it back.

A restore replaces the database with an older copy, and the copy still holds the accounts and the chrono records
that were erased after it was made (decision S22-7 left it to the operator to repeat them from the audit log, which
the restore replaced too). The ledger is a file the server appends to when an erasure commits, in a Docker volume the
restore does not touch (``ATALAIA_ERASURE_LEDGER``; ``backup.sh`` copies it next to the backups and ``restore.sh``
merges that copy back, for a machine that was lost with its volume). After a restore, ``python -m atalaia_server
erasure-ledger apply`` erases again whatever the restored database still holds of it.

**What is in it: hashes, no personal data.** One JSON line per erasure:

    {"v": 1, "kind": "account", "tenant": null, "hash": "<hex>", "at": "<iso time>"}
    {"v": 1, "kind": "player", "tenant": null, "field": "<field id>", "hash": "<hex>", "chrono": true,
     "identity": false, "at": "<iso time>"}

``hash`` is the SHA-256 of ``atalaia-erasure/1:account:<user id>`` or ``atalaia-erasure/1:player:<field id>/<player id>``:
the random ids a restored database still holds, compared by hash, so the file by itself names nobody and leads to no
row (the ids of the anonymised rows stay in the audit log and the foreign keys either way). ``tenant`` is the field's
slug on a hosted hub (each field is a schema of its own), null on a single-field server. The time is the erasure's.
Nothing else: no name, e-mail address, username, address or reason.

The file is append-only and never pruned by the server: an entry is about 150 bytes, and it is needed for as long as
any backup older than the erasure exists (the operator's ``ATALAIA_BACKUP_DAYS``, and any copy kept off-site).
Writing is best effort after the erasure's commit (the erasure itself already happened): a failure is logged and the
caller carries on. It is never written before the commit, so a rolled-back erasure never leaves an entry that would
erase an account that was not erased.

Plain Python with no third-party imports (the ``export`` and ``import`` commands run in a container with no network and
no database); ``apply`` is in ``cli.py``. ``python -m atalaia_server.erasure_ledger export`` writes the ledger to
standard output, ``import`` merges lines from standard input (those not in the file yet).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

log = logging.getLogger("atalaia.server.ledger")

VERSION = 1
ENV = "ATALAIA_ERASURE_LEDGER"
_LOCK = threading.Lock()


def hash_account(user_id: uuid.UUID) -> str:
    return hashlib.sha256(f"atalaia-erasure/1:account:{user_id}".encode()).hexdigest()


def hash_player(field_id: uuid.UUID, player_id: str) -> str:
    return hashlib.sha256(f"atalaia-erasure/1:player:{field_id}/{player_id}".encode()).hexdigest()


def account_entry(user_id: uuid.UUID, tenant: Optional[str], at: Optional[datetime] = None) -> dict[str, Any]:
    return {"v": VERSION, "kind": "account", "tenant": tenant, "hash": hash_account(user_id), "at": _iso(at)}


def player_entry(field_id: uuid.UUID, player_id: str, tenant: Optional[str], *, chrono: bool, identity: bool,
                 at: Optional[datetime] = None) -> dict[str, Any]:
    return {"v": VERSION, "kind": "player", "tenant": tenant, "field": str(field_id),
            "hash": hash_player(field_id, player_id), "chrono": chrono, "identity": identity, "at": _iso(at)}


def _iso(at: Optional[datetime]) -> str:
    return (at or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _line(entry: dict[str, Any]) -> str:
    return json.dumps(entry, sort_keys=True, separators=(",", ":"))


def valid(entry: Any) -> bool:
    """An entry this version reads: a line another version wrote, or a damaged one, is skipped (and counted)."""
    if not isinstance(entry, dict) or entry.get("v") != VERSION or entry.get("kind") not in ("account", "player"):
        return False
    digest = entry.get("hash")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        return False
    if entry["kind"] == "player":
        try:
            uuid.UUID(entry.get("field", ""))
        except (ValueError, AttributeError, TypeError):
            return False
        if not isinstance(entry.get("chrono"), bool) or not isinstance(entry.get("identity"), bool):
            return False
    return entry.get("tenant") is None or isinstance(entry.get("tenant"), str)


def read(path: str) -> tuple[list[dict[str, Any]], int]:
    """The file's valid entries and how many lines were not (a missing file is an empty ledger)."""
    entries, bad = [], 0
    try:
        with open(path, encoding="utf-8") as handle:
            for text in handle:
                if not text.strip():
                    continue
                try:
                    entry = json.loads(text)
                except ValueError:
                    entry = None
                if valid(entry):
                    entries.append(entry)
                else:
                    bad += 1
    except FileNotFoundError:
        pass
    return entries, bad


def append(path: Optional[str], entries: Iterable[dict[str, Any]]) -> bool:
    """Adds the entries (flushed to disk before it returns). False when the ledger is off or the write failed (logged:
    the erasure already committed, and the next backup's copy of the ledger will not have these)."""
    rows = list(entries)
    if path is None or not rows:
        return path is not None
    try:
        with _LOCK:
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            try:
                os.write(fd, "".join(_line(e) + "\n" for e in rows).encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
        return True
    except OSError:
        log.exception("the erasure ledger %s could not be written: %d erasure(s) are not in it", path, len(rows))
        return False


def merge(path: str, lines: Iterable[str]) -> tuple[int, int]:
    """Adds the valid lines that are not in the file yet; returns (added, skipped as not valid)."""
    have = {_line(e) for e in read(path)[0]}
    added, bad, new = 0, 0, []
    for text in lines:
        if not text.strip():
            continue
        try:
            entry = json.loads(text)
        except ValueError:
            entry = None
        if not valid(entry):
            bad += 1
            continue
        line = _line(entry)
        if line not in have:
            have.add(line)
            new.append(entry)
            added += 1
    if new and not append(path, new):
        raise OSError(f"cannot write {path}")
    return added, bad


def main(argv: list[str]) -> int:
    path = os.environ.get(ENV, "").strip()
    if len(argv) != 2 or argv[1] not in ("export", "import") or not path:
        print(f"usage: {ENV}=FILE python -m atalaia_server.erasure_ledger export|import   (standard output / input)",
              file=sys.stderr)
        return 2
    if argv[1] == "export":
        entries, bad = read(path)
        for entry in entries:
            sys.stdout.write(_line(entry) + "\n")
        if bad:
            print(f"erasure ledger: {bad} line(s) not valid were left out", file=sys.stderr)
        return 0
    try:
        added, bad = merge(path, sys.stdin)
    except OSError as exc:
        print(f"erasure ledger: {exc}", file=sys.stderr)
        return 1
    print(f"erasure ledger: {added} entr{'y' if added == 1 else 'ies'} added, {bad} line(s) not valid left out",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
