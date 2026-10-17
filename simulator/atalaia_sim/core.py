# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""ctypes bindings for the shared C core (core/include/atalaia/node.h)."""

from __future__ import annotations

import ctypes
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

EVENT_TYPE_MAX = 48
PRIO_NAMES = {0: "telemetry", 1: "normal", 2: "critical"}
STATUS_NAMES = {0: "empty", 1: "running", 2: "ended", 3: "halted"}


class _Event(ctypes.Structure):
    _fields_ = [
        ("node", ctypes.c_uint16),
        ("seq", ctypes.c_uint16),
        ("t_ms", ctypes.c_uint32),
        ("team", ctypes.c_uint8),
        ("squad", ctypes.c_uint8),
        ("prio", ctypes.c_int),
        ("type", ctypes.c_char * EVENT_TYPE_MAX),
    ]


_EVENT_FN = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.POINTER(_Event), ctypes.c_char_p)
_COMMAND_FN = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p)
_LOG_FN = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_char_p)
_ALLOC_FN = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t)


class _Callbacks(ctypes.Structure):
    _fields_ = [
        ("event", _EVENT_FN),
        ("command", _COMMAND_FN),
        ("log", _LOG_FN),
        ("user", ctypes.c_void_p),
    ]


class _Config(ctypes.Structure):
    _fields_ = [
        ("node_id", ctypes.c_uint16),
        ("game_seed", ctypes.c_uint32),
        ("mem_limit", ctypes.c_size_t),
        ("instr_limit", ctypes.c_uint32),
        ("callbacks", _Callbacks),
        ("alloc", _ALLOC_FN),
        ("alloc_ud", ctypes.c_void_p),
    ]


def _library_names() -> list[str]:
    if sys.platform == "win32":
        return ["atalaia_core.dll", "libatalaia_core.dll"]
    if sys.platform == "darwin":
        return ["libatalaia_core.dylib"]
    return ["libatalaia_core.so"]


def find_library(explicit: Optional[str] = None) -> Path:
    """Finds the shared core: --lib, $ATALAIA_CORE_LIB, then build folders."""
    if explicit:
        return Path(explicit)
    if os.environ.get("ATALAIA_CORE_LIB"):
        return Path(os.environ["ATALAIA_CORE_LIB"])
    repo = Path(__file__).resolve().parents[2]
    for folder in ("build", "build/core", "core/build"):
        for name in _library_names():
            candidate = repo / folder / name
            if candidate.exists():
                return candidate
    raise FileNotFoundError(
        "shared core library not found; build it with\n"
        "  cmake -S core -B build -DATALAIA_SHARED=ON && cmake --build build\n"
        "or pass --lib / set ATALAIA_CORE_LIB"
    )


class Core:
    """The loaded shared library, with argument types declared once."""

    def __init__(self, path: Path):
        self.path = path
        lib = ctypes.CDLL(str(path))
        p = ctypes.c_void_p
        sigs = {
            "atalaia_version": ([], ctypes.c_char_p),
            "atalaia_node_create": ([ctypes.POINTER(_Config)], p),
            "atalaia_node_destroy": ([p], None),
            "atalaia_node_set_teams": ([p, ctypes.POINTER(ctypes.c_char_p), ctypes.c_size_t], ctypes.c_bool),
            "atalaia_node_set_params": ([p, ctypes.c_char_p], ctypes.c_bool),
            "atalaia_node_load": ([p, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p], ctypes.c_bool),
            "atalaia_node_input": ([p, ctypes.c_char_p, ctypes.c_char_p], ctypes.c_bool),
            "atalaia_node_advance": ([p, ctypes.c_uint32], None),
            "atalaia_node_status": ([p], ctypes.c_int),
            "atalaia_node_paused": ([p], ctypes.c_bool),
            "atalaia_node_time": ([p], ctypes.c_uint32),
            "atalaia_node_last_error": ([p], ctypes.c_char_p),
            "atalaia_node_mem_used": ([p], ctypes.c_size_t),
            "atalaia_node_score": ([p], p),
            "atalaia_score_net": ([p, ctypes.c_uint8], ctypes.c_int64),
        }
        for name, (args, res) in sigs.items():
            fn = getattr(lib, name)
            fn.argtypes = args
            fn.restype = res
        self.lib = lib

    @property
    def version(self) -> str:
        return self.lib.atalaia_version().decode()


@dataclass
class Emitted:
    """An event a node emitted, as the host receives it."""

    node: int
    seq: int
    t_ms: int
    team: int
    prio: str
    type: str
    data: dict[str, Any]


@dataclass
class Command:
    t_ms: int
    target: str
    method: str
    args: list[Any]


class Node:
    """One node runtime in the core, with Python callbacks attached."""

    def __init__(
        self,
        core: Core,
        node_id: int,
        game_seed: int,
        teams: list[str],
        params: dict[str, Any],
        source: str,
        chunk_name: str,
        mem_limit: int = 0,
        instr_limit: int = 0,
        on_event: Optional[Callable[[Emitted], None]] = None,
        on_command: Optional[Callable[[Command], None]] = None,
        on_log: Optional[Callable[[str], None]] = None,
    ):
        self._lib = core.lib
        self.node_id = node_id
        self.teams = list(teams)
        self._on_event = on_event
        self._on_command = on_command
        self._on_log = on_log

        # Keep references so ctypes does not free the callbacks.
        self._cb_event = _EVENT_FN(self._event)
        self._cb_command = _COMMAND_FN(self._command)
        self._cb_log = _LOG_FN(self._log)

        cfg = _Config()
        cfg.node_id = node_id
        cfg.game_seed = game_seed & 0xFFFFFFFF
        cfg.mem_limit = mem_limit
        cfg.instr_limit = instr_limit
        cfg.callbacks.event = self._cb_event
        cfg.callbacks.command = self._cb_command
        cfg.callbacks.log = self._cb_log
        self._handle = self._lib.atalaia_node_create(ctypes.byref(cfg))
        if not self._handle:
            raise MemoryError("atalaia_node_create failed")

        names = (ctypes.c_char_p * len(teams))(*[t.encode() for t in teams])
        if not self._lib.atalaia_node_set_teams(self._handle, names, len(teams)):
            raise ValueError(f"bad teams {teams}: {self.last_error}")
        if not self._lib.atalaia_node_set_params(self._handle, json.dumps(params).encode()):
            raise ValueError(f"bad params: {self.last_error}")
        encoded = source.encode()
        self.loaded = bool(self._lib.atalaia_node_load(self._handle, encoded, len(encoded), chunk_name.encode()))

    def close(self) -> None:
        if self._handle:
            self._lib.atalaia_node_destroy(self._handle)
            self._handle = None

    def __del__(self) -> None:
        self.close()

    # -- callbacks from C --

    def _event(self, _user, ev_ptr, data) -> None:
        ev = ev_ptr.contents
        emitted = Emitted(
            node=ev.node,
            seq=ev.seq,
            t_ms=ev.t_ms,
            team=ev.team,
            prio=PRIO_NAMES.get(ev.prio, str(ev.prio)),
            type=ev.type.decode(),
            data=json.loads(data.decode()) if data else {},
        )
        if self._on_event:
            self._on_event(emitted)

    def _command(self, _user, target, method, args) -> None:
        if self._on_command:
            self._on_command(Command(self.time_ms, target.decode(), method.decode(), json.loads(args.decode())))

    def _log(self, _user, message) -> None:
        if self._on_log:
            self._on_log(message.decode(errors="replace"))

    # -- driving the node --

    def input(self, type_: str, data: Optional[dict[str, Any]] = None) -> bool:
        payload = json.dumps(data).encode() if data is not None else None
        return bool(self._lib.atalaia_node_input(self._handle, type_.encode(), payload))

    def advance(self, now_ms: int) -> None:
        self._lib.atalaia_node_advance(self._handle, now_ms)

    @property
    def status(self) -> str:
        return STATUS_NAMES.get(self._lib.atalaia_node_status(self._handle), "unknown")

    @property
    def paused(self) -> bool:
        return bool(self._lib.atalaia_node_paused(self._handle))

    @property
    def time_ms(self) -> int:
        return int(self._lib.atalaia_node_time(self._handle))

    @property
    def last_error(self) -> str:
        return self._lib.atalaia_node_last_error(self._handle).decode(errors="replace")

    @property
    def mem_used(self) -> int:
        return int(self._lib.atalaia_node_mem_used(self._handle))

    def score(self, team: str) -> int:
        team_id = self.teams.index(team) + 1
        return int(self._lib.atalaia_score_net(self._lib.atalaia_node_score(self._handle), team_id))
