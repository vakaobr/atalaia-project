# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The I/O pod's settings, pushed over the radio (protocol/pod-config.md, decision PODC).

An I/O pod (ADR-P3-3) lends its buttons, ring, sound and radio to the phone it is linked to; until
now its settings (the buttons' colours, the ring's brightness, the volume, the enclosure switch)
were Kconfig, fixed when the firmware was built. The GM sets them in the console and the controller
sends them to the pod as CMD pod (opcode 10, RFC 0001 Amendment 17): a sealed game packet like every
other CMD, to the node id of the phone the pod serves. The pod's radio opens it with the game key,
takes the settings, keeps them in its flash and says so with an event on the phone, which sends it
over the radio as ``node.setup_applied`` (``kind`` ``pod_config``, ``rev``): the ACK machinery the
boxes' setups use (decision PKB). Until that event arrives the controller sends the command again
(after 8, 16, 32, 64 and 128 s, five times at most), then says the pod did not answer: no pod on
that phone, a pod firmware older than this, a radio out of reach, or a rev the pod already passed.

Only before a game starts (or after it ended): a button changing colour mid-game would be the
players' surprise. The pushes live in memory; the pod's flash holds the truth.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable, Optional

from .engine import Conflict, Controller, ControllerError, NotFound, Unavailable

log = logging.getLogger("atalaia.pod_config")

VERSION = 1
CMD_POD = 10  # atalaia_sim.field_controller.CMD_POD
CMD_PARAMS_MAX = 127
COLOURS = ("red", "blue", "green", "yellow", "orange", "purple", "white", "pink", "cyan")
BUTTONS = 4
KEYS = ("btn", "bright", "vol", "tamper", "reset")
KIND = "pod_config"  # node.setup_applied's kind
RESEND_S = (8, 16, 32, 64, 128)  # the waits after each sending; the last wait ends the tries
PLATFORM_ANDROID = 3  # HELLO's platform: a phone, the only node an I/O pod serves
IDLE_STATES = ("ready", "ended")


def _uint(v: Any, name: str, lo: int, hi: int) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise ControllerError(f"{name}: a whole number from {lo} to {hi}")
    return v


def check_params(params: Any) -> dict[str, Any]:
    """The command's params checked as the pod checks them (pod_settings.c): the exact keys,
    ranges and colours, ``v`` 1 and ``rev`` 1 to 2**32-1. Returns them; ControllerError otherwise."""
    if not isinstance(params, dict):
        raise ControllerError("the settings must be a map")
    unknown = sorted(set(params) - {"v", "rev", *KEYS})
    if unknown:
        raise ControllerError(f"unknown setting: {', '.join(map(str, unknown))} (one of {', '.join(KEYS)})")
    if params.get("v") != VERSION or isinstance(params.get("v"), bool):
        raise ControllerError(f"v: {VERSION}")
    _uint(params.get("rev"), "rev", 1, 0xFFFFFFFF)
    if "btn" in params:
        btn = params["btn"]
        if not isinstance(btn, list) or len(btn) != BUTTONS or \
                not all(isinstance(c, str) and (c == "" or c in COLOURS) for c in btn):
            raise ControllerError(f"btn: {BUTTONS} colours, each empty (the game's N-th team) or one of "
                                  f"{', '.join(COLOURS)}")
    for key in ("bright", "vol"):
        if key in params:
            _uint(params[key], key, 0, 100)
    for key in ("tamper", "reset"):
        if key in params and not isinstance(params[key], bool):
            raise ControllerError(f"{key}: true or false")
    size = len(json.dumps(params, separators=(",", ":")).encode())
    if size > CMD_PARAMS_MAX:
        raise ControllerError(f"the settings are {size} bytes; at most {CMD_PARAMS_MAX} fit in a CMD")
    return params


def params_from_body(body: Any, rev: int) -> dict[str, Any]:
    """What the GM sent (some of btn, bright, vol, tamper, reset, rev) as the command's params."""
    if not isinstance(body, dict):
        raise ControllerError("the body must be a map")
    unknown = sorted(set(body) - {"rev", *KEYS})
    if unknown:
        raise ControllerError(f"unknown setting: {', '.join(map(str, unknown))} (one of {', '.join(KEYS)})")
    params: dict[str, Any] = {"v": VERSION, "rev": body.get("rev", rev)}
    params.update({k: body[k] for k in KEYS if k in body})
    if not any(k in body for k in KEYS):
        raise ControllerError(f"nothing to set: give at least one of {', '.join(KEYS)}")
    return check_params(params)


class PodSettingsModel:
    """The pod's side, as pod_settings.c does it: the reference the shared vectors are made with."""

    def __init__(self) -> None:
        self.rev = 0
        self.set: dict[str, Any] = {}

    def handle(self, params: Any) -> str:
        """applied, same, stale or refused (pod_config_result_t)."""
        try:
            p = check_params(params)
        except ControllerError:
            return "refused"
        if p["rev"] < self.rev:
            return "stale"
        if p["rev"] == self.rev:
            return "same"
        if p.get("reset"):
            self.set = {}
        self.rev = p["rev"]
        self.set.update({k: p[k] for k in ("btn", "bright", "vol", "tamper") if k in p})
        return "applied"

    def stored(self) -> str:
        """The stored form (pod_settings_to_json): keys in this order."""
        out: dict[str, Any] = {"v": VERSION, "rev": self.rev}
        out.update({k: self.set[k] for k in ("btn", "bright", "vol", "tamper") if k in self.set})
        return json.dumps(out, separators=(",", ":"))


class PodConfig:
    """The GM's pushes of settings to the pods of the live game's phones."""

    def __init__(self, controller: Controller, clock: Callable[[], float] = time.time) -> None:
        self.controller = controller
        self.clock = clock
        self._lock = threading.Lock()
        self.pushes: dict[int, dict[str, Any]] = {}  # node id -> the latest push
        controller.pod_config = self
        controller.add_listener(self.on_message)

    # ---- the GM's side --------------------------------------------------------------------

    def _next_rev(self, node_id: int) -> int:
        """Seconds since 1970, and above the last rev sent to the node: a pod keeps the last rev it
        took in its flash, so a controller that restarted (and forgot) must still go above it."""
        last = self.pushes.get(node_id, {}).get("rev", 0)
        return max(int(self.clock()), last + 1)

    def candidates(self) -> list[dict[str, Any]]:
        """The phones of the live game: the only nodes an I/O pod can serve (their HELLO says
        platform android; whether one has a pod is not in it, the pod's answer tells)."""
        out = []
        for n in self.controller.nodes():
            if n.get("platform") == PLATFORM_ANDROID:
                out.append({"node_id": n["node_id"], "name": n.get("name"), "link": n.get("link")})
        return out

    def push(self, node_id: Any, body: Any) -> dict[str, Any]:
        c = self.controller
        if isinstance(node_id, bool) or not isinstance(node_id, int) or not 1 <= node_id <= 0xFFFE:
            raise ControllerError("node id: 1-65534 (a pod's settings are never broadcast)")
        if c.game is None:
            raise Conflict("no live game: the pod's phone must be joined to one")
        if c.game["state"] not in IDLE_STATES:
            raise Conflict(f"game {c.game['id']} is {c.game['state']}: pod settings only before a game starts "
                           "or after it ended")
        if node_id not in {n["node_id"] for n in self.candidates()}:
            raise NotFound(f"node {node_id} is not a phone of this game (only a phone has an I/O pod)")
        with self._lock:
            params = params_from_body(body, self._next_rev(node_id))
            now = self.clock()
            seq = c.send_pod_config(node_id, params)
            self.pushes[node_id] = {"node_id": node_id, "game": c.game["id"], "rev": params["rev"],
                                    "settings": {k: v for k, v in params.items() if k not in ("v", "rev")},
                                    "state": "sent", "tries": 1, "seq": seq, "sent_at": now,
                                    "updated_at": now, "next_at": now + RESEND_S[0]}
            log.warning("pod settings rev %d sent to node %d: %s", params["rev"], node_id,
                        json.dumps(self.pushes[node_id]["settings"], separators=(",", ":")))
        self._emit()
        return self._public(self.pushes[node_id])

    def status(self) -> dict[str, Any]:
        with self._lock:
            pushes = [self._public(p) for _, p in sorted(self.pushes.items())]
        return {"colours": list(COLOURS), "buttons": BUTTONS, "nodes": self.candidates(), "pushes": pushes}

    def cancel(self) -> list[int]:
        """Stops waiting for the answers (and resending)."""
        with self._lock:
            nodes = [n for n, p in self.pushes.items() if p["state"] == "sent"]
            for n in nodes:
                self.pushes[n].update(state="cancelled", updated_at=self.clock())
        if nodes:
            self._emit()
        return nodes

    @staticmethod
    def _public(p: dict[str, Any]) -> dict[str, Any]:
        return {k: p[k] for k in ("node_id", "rev", "settings", "state", "tries", "sent_at", "updated_at")}

    # ---- answers and resends --------------------------------------------------------------

    def on_message(self, msg: dict[str, Any]) -> None:
        """node.setup_applied (kind pod_config, rev) from the node: the pod took it."""
        if msg.get("type") != "event" or not isinstance(msg.get("event"), dict):
            return
        ev = msg["event"]
        data = ev.get("data") or {}
        if ev.get("type") != "node.setup_applied" or data.get("kind") != KIND:
            return
        with self._lock:
            p = self.pushes.get(ev.get("node"))
            if p is None or p["state"] not in ("sent", "no_answer") or data.get("rev") != p["rev"]:
                return
            p.update(state="applied", updated_at=self.clock())
        log.warning("pod of node %s took settings rev %s", ev.get("node"), data.get("rev"))
        self._emit()

    def tick(self) -> None:
        """The next sending of every push still waiting, or its end."""
        now = self.clock()
        due: list[dict[str, Any]] = []
        changed = False
        with self._lock:
            for p in self.pushes.values():
                if p["state"] != "sent" or now < p["next_at"]:
                    continue
                if p["tries"] > len(RESEND_S):  # the first sending and five repeats are done
                    p.update(state="no_answer", updated_at=now)
                    changed = True
                    log.warning("the pod of node %d did not answer settings rev %d", p["node_id"], p["rev"])
                else:
                    due.append(p)
        for p in due:
            params = {"v": VERSION, "rev": p["rev"], **p["settings"]}
            try:
                seq = self.controller.send_pod_config(p["node_id"], params, resend=True)
            except Unavailable:
                seq = None  # the radio is down: the next wait tries again
            except ControllerError:
                with self._lock:
                    p.update(state="cancelled", updated_at=now)  # the game moved on
                changed = True
                continue
            with self._lock:
                p["tries"] += 1
                p["next_at"] = now + RESEND_S[min(p["tries"] - 1, len(RESEND_S) - 1)]
                if seq is not None:
                    p["seq"] = seq
                    p["sent_at"] = now
        if changed:
            self._emit()

    def _emit(self) -> None:
        self.controller._emit({"type": "pod_config", "pushes": self.status()["pushes"]})
