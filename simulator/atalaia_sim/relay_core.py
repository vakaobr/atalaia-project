# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The core's relay rules (core/include/atalaia/flood.h, ack.h), driven from Python.

RFC 0001 Amendment 13 (decision SL-16) moved the "A+backoff" rules the relay study modelled into
the real core, where the Field Box's ``field_link.c`` calls them. The study's harness
(``relay_study.py``) has a ``core_rules`` policy flag that makes every box use *this* class instead
of its own model of the rules, so the study can be re-run against the code that ships and the two
sets of numbers put side by side (``docs/review/relay-study-results.md``). The box's entropy is the
engine's seeded ``random.Random`` (the firmware's is ``shell.random``).
"""

from __future__ import annotations

import ctypes
import random
from pathlib import Path
from typing import Optional

from .core import find_library

SLOTS = 8
NEIGHBOURS = 64
PATHS = 32

# kinds of frame (atalaia_relay_kind_t)
ASKS_ACK, ACK, OTHER = 0, 1, 2
SKIP, NO_SLOT = -1, -2

_RAND_FN = ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.c_void_p)


class _Neighbour(ctypes.Structure):
    _fields_ = [("source", ctypes.c_uint16), ("heard_ms", ctypes.c_uint32)]


class _Path(ctypes.Structure):
    _fields_ = [("node", ctypes.c_uint16), ("at_ms", ctypes.c_uint32)]


class _Slot(ctypes.Structure):
    _fields_ = [("used", ctypes.c_bool), ("wait_ack", ctypes.c_bool), ("source", ctypes.c_uint16),
                ("seq", ctypes.c_uint16), ("due_ms", ctypes.c_uint32)]


class _Relay(ctypes.Structure):
    # Must match atalaia_relay_t field for field (checked by tests/test_relay_core.py).
    _fields_ = [("rand", _RAND_FN), ("rand_ctx", ctypes.c_void_p), ("neighbours", _Neighbour * NEIGHBOURS),
                ("paths", _Path * PATHS), ("slots", _Slot * SLOTS)]


_LIBS: dict[str, ctypes.CDLL] = {}


def load(lib: Optional[str] = None) -> ctypes.CDLL:
    path = str(Path(find_library(lib)))
    if path not in _LIBS:
        d = ctypes.CDLL(path)
        r = ctypes.POINTER(_Relay)
        d.atalaia_relay_init.argtypes = [r, _RAND_FN, ctypes.c_void_p]
        d.atalaia_relay_init.restype = None
        d.atalaia_relay_heard.argtypes = [r, ctypes.c_uint16, ctypes.c_uint32]
        d.atalaia_relay_heard.restype = None
        d.atalaia_relay_neighbours.argtypes = [r, ctypes.c_uint32]
        d.atalaia_relay_neighbours.restype = ctypes.c_uint32
        d.atalaia_relay_plan.argtypes = [r, ctypes.c_int, ctypes.c_uint16, ctypes.c_uint16, ctypes.c_uint16,
                                         ctypes.c_uint32]
        d.atalaia_relay_plan.restype = ctypes.c_int
        d.atalaia_relay_ack_heard.argtypes = [r, ctypes.c_uint16, ctypes.c_uint16, ctypes.c_char_p,
                                              ctypes.c_size_t]
        d.atalaia_relay_ack_heard.restype = ctypes.c_size_t
        d.atalaia_relay_take_due.argtypes = [r, ctypes.c_uint32]
        d.atalaia_relay_take_due.restype = ctypes.c_int
        d.atalaia_relay_pending.argtypes = [r]
        d.atalaia_relay_pending.restype = ctypes.c_size_t
        d.atalaia_retry_gap_ms.argtypes = [ctypes.c_uint, ctypes.c_uint32]
        d.atalaia_retry_gap_ms.restype = ctypes.c_uint32
        _LIBS[path] = d
    return _LIBS[path]


class CoreRelay:
    """One box's relay state, in the core's own struct."""

    def __init__(self, rng: random.Random, lib: Optional[str] = None) -> None:
        self._lib = load(lib)
        self._rng = rng
        self._cb = _RAND_FN(lambda _ctx: self._rng.getrandbits(32))  # kept alive with the object
        self.state = _Relay()
        self._lib.atalaia_relay_init(ctypes.byref(self.state), self._cb, None)

    def heard(self, source: int, now_ms: int) -> None:
        self._lib.atalaia_relay_heard(ctypes.byref(self.state), source, now_ms)

    def neighbours(self, now_ms: int) -> int:
        return self._lib.atalaia_relay_neighbours(ctypes.byref(self.state), now_ms)

    def plan(self, kind: int, source: int, seq: int, ack_node: int, now_ms: int) -> int:
        return self._lib.atalaia_relay_plan(ctypes.byref(self.state), kind, source, seq & 0xFFFF, ack_node,
                                            now_ms)

    def due_ms(self, slot: int) -> int:
        return self.state.slots[slot].due_ms

    def ack_heard(self, ack_node: int, contig: int, above: set[int]) -> int:
        """The controller's ACK: ``contig`` the highest contiguous seq (-1: none), ``above`` the seqs
        named by its bitmap."""
        bitmap = bytearray(32)
        for q in above:
            n = q - contig - 1
            if 0 <= n < 256:
                bitmap[n // 8] |= 1 << (n % 8)
        used = max((i // 8 + 1 for i in (q - contig - 1 for q in above) if 0 <= i < 256), default=0)
        return self._lib.atalaia_relay_ack_heard(ctypes.byref(self.state), ack_node,
                                                 0xFFFF if contig < 0 else contig, bytes(bitmap[:used]), used)

    def take_due(self, now_ms: int) -> int:
        return self._lib.atalaia_relay_take_due(ctypes.byref(self.state), now_ms)

    def pending(self) -> int:
        return self._lib.atalaia_relay_pending(ctypes.byref(self.state))

    def retry_gap_ms(self, sends_so_far: int) -> int:
        return self._lib.atalaia_retry_gap_ms(sends_so_far, self._rng.getrandbits(32))
