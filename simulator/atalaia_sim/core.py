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

from .protocol import EVENT_TYPE_MAX, PRIORITIES

PRIO_NAMES = {v: k for k, v in PRIORITIES.items()}
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
_FIELD_STATE_FN = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p)
_ALLOC_FN = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t)

# atalaia_field_ops_t (core/include/atalaia/field_ops.h). nodes() returns a
# malloc'd string the core frees, and owner() a string the core copies at
# once, so both are declared as void pointers and filled in by hand.
_FIELD_NODES_FN = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p)
_FIELD_OWNER_FN = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint16)
_FIELD_SEND_FN = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_uint16, ctypes.c_char_p, ctypes.c_char_p)


class _Callbacks(ctypes.Structure):
    # Must match atalaia_node_callbacks_t field for field.
    _fields_ = [
        ("event", _EVENT_FN),
        ("command", _COMMAND_FN),
        ("log", _LOG_FN),
        ("field_state", _FIELD_STATE_FN),
        ("user", ctypes.c_void_p),
    ]


class _FieldOps(ctypes.Structure):
    _fields_ = [
        ("nodes", _FIELD_NODES_FN),
        ("owner", _FIELD_OWNER_FN),
        ("send", _FIELD_SEND_FN),
    ]


class _Config(ctypes.Structure):
    # Must match atalaia_node_config_t field for field.
    _fields_ = [
        ("node_id", ctypes.c_uint16),
        ("game_seed", ctypes.c_uint32),
        ("mem_limit", ctypes.c_size_t),
        ("instr_limit", ctypes.c_uint32),
        ("callbacks", _Callbacks),
        ("alloc", _ALLOC_FN),
        ("alloc_ud", ctypes.c_void_p),
        ("field_ops", ctypes.POINTER(_FieldOps)),
    ]


def _libc_malloc():
    """The C library's malloc, for strings the core will free()."""
    try:
        libc = ctypes.CDLL(None) if sys.platform != "win32" else ctypes.cdll.msvcrt
        malloc = libc.malloc
    except (OSError, AttributeError):
        return None
    malloc.restype = ctypes.c_void_p
    malloc.argtypes = [ctypes.c_size_t]
    return malloc


_MALLOC = _libc_malloc()


@dataclass
class FieldOps:
    """Controller callbacks behind field.* in a field script (ADR-P2-14).

    nodes(role) returns a list of node descriptors (dicts), owner(node_id)
    the owning team name or None, send(node_id, cmd, params) True when the
    command was queued. on_state(key, value) is called when the script
    writes state.field.
    """

    nodes: Callable[[Optional[str]], list[dict[str, Any]]]
    owner: Callable[[int], Optional[str]]
    send: Callable[[int, str, dict[str, Any]], bool]
    on_state: Optional[Callable[[str, Any], None]] = None


def _library_names() -> list[str]:
    if sys.platform == "win32":
        return ["atalaia_core.dll", "libatalaia_core.dll"]
    if sys.platform == "darwin":
        return ["libatalaia_core.dylib"]
    return ["libatalaia_core.so"]


class LibraryNotFound(FileNotFoundError):
    pass


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
    raise LibraryNotFound(
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
    squad: int
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
        field_ops: Optional[FieldOps] = None,
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
        self._field = field_ops
        self._owner_buf = ctypes.create_string_buffer(1)

        cfg = _Config()
        cfg.node_id = node_id
        cfg.game_seed = game_seed & 0xFFFFFFFF
        cfg.mem_limit = mem_limit
        cfg.instr_limit = instr_limit
        cfg.callbacks.event = self._cb_event
        cfg.callbacks.command = self._cb_command
        cfg.callbacks.log = self._cb_log
        if field_ops is not None:
            # A controller node: field.* is available and state.field is writable.
            self._cb_field_state = _FIELD_STATE_FN(self._field_state)
            self._cb_nodes = _FIELD_NODES_FN(self._field_nodes)
            self._cb_owner = _FIELD_OWNER_FN(self._field_owner)
            self._cb_send = _FIELD_SEND_FN(self._field_send)
            self._ops = _FieldOps(self._cb_nodes, self._cb_owner, self._cb_send)
            cfg.callbacks.field_state = self._cb_field_state
            cfg.field_ops = ctypes.pointer(self._ops)
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
            squad=ev.squad,
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

    def _field_state(self, _user, key, value_json) -> None:
        if self._field is not None and self._field.on_state is not None:
            self._field.on_state(key.decode(), json.loads(value_json.decode()))

    def _field_nodes(self, _user, role) -> Optional[int]:
        if _MALLOC is None or self._field is None:
            return None  # the core treats NULL as an empty list
        nodes = self._field.nodes(role.decode() if role else None)
        data = json.dumps(nodes).encode() + bytes(1)
        ptr = _MALLOC(len(data))
        if not ptr:
            return None
        ctypes.memmove(ptr, data, len(data))
        return ptr

    def _field_owner(self, _user, node_id) -> Optional[int]:
        team = self._field.owner(int(node_id)) if self._field is not None else None
        if team is None:
            return None
        # Kept alive until the next call; the core copies it at once.
        self._owner_buf = ctypes.create_string_buffer(team.encode())
        return ctypes.addressof(self._owner_buf)

    def _field_send(self, _user, node_id, cmd, params) -> bool:
        if self._field is None:
            return False
        args = json.loads(params.decode()) if params else {}
        return bool(self._field.send(int(node_id), cmd.decode(), args))

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
