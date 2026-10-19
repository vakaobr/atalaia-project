# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Account passwords: Argon2id and the password policy (ADR-P4-2).

Hashes are Argon2id with ADR-P4-2's parameters (OWASP's: 3 passes over 64 MiB,
4 lanes, a 16-byte salt, a 32-byte tag), in the PHC string form that
argon2-cffi writes (``$argon2id$v=19$m=65536,t=3,p=4$...``). A hash made with
other parameters still verifies and is replaced at the next login
(``needs_rehash``).

The policy follows NIST SP 800-63B (section 5.1.1.2): at least 10 characters,
at most 1024, no character-class rules, not one of the most common breached
passwords and not the username. Passwords are normalised to Unicode NFKC
before they are checked and hashed, so the same password typed on two
keyboards gives the same hash.

Hashing costs 64 MiB and tens of milliseconds of CPU, so it runs in a worker
thread (argon2-cffi releases the GIL) and at most ``MAX_PARALLEL_HASHES`` run
at once: a burst of logins waits instead of taking the server's memory.
"""

from __future__ import annotations

import asyncio
import threading
import unicodedata
from pathlib import Path
from typing import Optional

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

TIME_COST = 3
MEMORY_COST_KIB = 65536
PARALLELISM = 4
HASH_LEN = 32
SALT_LEN = 16

MIN_LENGTH = 10
MAX_LENGTH = 1024
MAX_PARALLEL_HASHES = 2

# The UK NCSC's list of the 100,000 passwords seen most often in breaches (from
# Have I Been Pwned), as published in SecLists; README.md has its source and hash.
BREACHED_LIST = Path(__file__).resolve().parent / "data" / "breached-passwords.txt"

HASHER = PasswordHasher(time_cost=TIME_COST, memory_cost=MEMORY_COST_KIB, parallelism=PARALLELISM,
                        hash_len=HASH_LEN, salt_len=SALT_LEN, type=Type.ID)

_breached: Optional[frozenset[str]] = None
_breached_lock = threading.Lock()
_dummy_hash: Optional[str] = None
# A thread semaphore, taken in the worker thread: it works whatever event loop calls (tests run many).
_slots = threading.BoundedSemaphore(MAX_PARALLEL_HASHES)


def normalise(password: str) -> str:
    return unicodedata.normalize("NFKC", password)


def breached_passwords() -> frozenset[str]:
    """The breached list, lower-cased, only the entries long enough to pass the length rule."""
    global _breached
    with _breached_lock:
        if _breached is None:
            words = BREACHED_LIST.read_text(encoding="utf-8").splitlines()
            _breached = frozenset(w.lower() for w in (normalise(w) for w in words) if len(w) >= MIN_LENGTH)
        return _breached


def policy_problem(password: str, username: Optional[str] = None) -> Optional[str]:
    """None when the password may be used, else the reason as a code for the API."""
    pw = normalise(password)
    if len(pw) < MIN_LENGTH:
        return "password_too_short"
    if len(pw) > MAX_LENGTH:
        return "password_too_long"
    if username and pw.casefold() == username.casefold():
        return "password_is_username"
    if pw.lower() in breached_passwords():
        return "password_breached"
    return None


def hash_password_sync(password: str) -> str:
    return HASHER.hash(normalise(password))


def verify_password_sync(stored_hash: str, password: str) -> bool:
    """True when the password matches; False for a wrong one or a hash that is not Argon2 (e.g. erased)."""
    try:
        return HASHER.verify(stored_hash, normalise(password))
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    try:
        return HASHER.check_needs_rehash(stored_hash)
    except (InvalidHashError, ValueError):
        return True


def _limited(fn, *args):  # type: ignore[no-untyped-def]
    with _slots:
        return fn(*args)


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(_limited, hash_password_sync, password)


async def verify_password(stored_hash: Optional[str], password: str) -> bool:
    """Verifies in a worker thread. With no hash (no such user) a dummy hash is checked instead,
    so the answer takes as long and the response time does not tell which usernames exist."""
    global _dummy_hash
    if stored_hash is None:
        if _dummy_hash is None:
            _dummy_hash = await asyncio.to_thread(_limited, hash_password_sync, "atalaia dummy password, never valid")
        await asyncio.to_thread(_limited, verify_password_sync, _dummy_hash, password)
        return False
    return await asyncio.to_thread(_limited, verify_password_sync, stored_hash, password)
