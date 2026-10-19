# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Time-ordered UUIDs (version 7, RFC 9562 section 5.7) for user-facing keys (ADR-P4-1).

Python 3.12 has no ``uuid.uuid7``. Layout: 48 bits of Unix time in
milliseconds, the version (7), 12 bits ``rand_a``, the variant (0b10) and 62
bits ``rand_b``. Within one process the keys made in the same millisecond
still sort in creation order: ``rand_a`` then counts up from a random start
(RFC 9562 section 6.2, method 1, a fixed-length dedicated counter); when it
would overflow, the timestamp is moved on by one millisecond.
"""

from __future__ import annotations

import os
import threading
import time
import uuid

_MAX_TS = (1 << 48) - 1
_lock = threading.Lock()
_last_ts = -1
_last_counter = 0


def uuid7_from_parts(unix_ts_ms: int, rand_a: int, rand_b: int) -> uuid.UUID:
    """The UUIDv7 made of these fields (no randomness here; used by uuid7 and the tests)."""
    if not 0 <= unix_ts_ms <= _MAX_TS:
        raise ValueError("unix_ts_ms must fit 48 bits")
    if not 0 <= rand_a < (1 << 12):
        raise ValueError("rand_a must fit 12 bits")
    if not 0 <= rand_b < (1 << 62):
        raise ValueError("rand_b must fit 62 bits")
    value = (unix_ts_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return uuid.UUID(int=value)


def uuid7() -> uuid.UUID:
    """A new UUIDv7, later than every one this process made before."""
    global _last_ts, _last_counter
    rand_b = int.from_bytes(os.urandom(8), "big") >> 2
    with _lock:
        ts = time.time_ns() // 1_000_000
        if ts > _last_ts:
            counter = int.from_bytes(os.urandom(2), "big") >> 5  # 11 bits: room to count up
        else:  # the same millisecond (or the clock went back): count on from the last key
            ts = _last_ts
            counter = _last_counter + 1
            if counter >= (1 << 12):
                ts += 1
                counter = 0
        _last_ts, _last_counter = ts, counter
    return uuid7_from_parts(ts, counter, rand_b)


def uuid7_time_ms(value: uuid.UUID) -> int:
    """The Unix time in milliseconds a UUIDv7 carries."""
    if value.version != 7:
        raise ValueError("not a version 7 UUID")
    return value.int >> 80
