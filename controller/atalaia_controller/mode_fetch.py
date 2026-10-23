# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Missing modes sent to boxes from the GM console (phase 5 plan phase 13a, decisions P5B-8 to
P5B-17 and P5D-*; protocol/mode-packages.md, "Fetching missing modes").

A box that answered an invite with *no mode* lacks a part of the game's mode. The GM invites it
again with **join key 16** (``fetch_modes``): the box then takes the join *fetching*, joins the
field Wi-Fi and, over HTTPS pinned to the field CA (join keys 13 and 14, as a firmware update),
fetches each part it lacks from this controller, checks it with the mode keys built into its own
firmware (``[modes] box_keys`` lists them here, so the controller offers only what boxes will
take), loads it in its sandbox, keeps it, reports, and only then says HELLO. Never over LoRa, and
only between games: the packages are served only while the live game is ready, and the start
guard waits while fetches are on their way (``[modes] fetch_timeout_s``; the GM may stop waiting).

A HELLO ends a fetch only when the controller holds HTTPS reports that the box keeps every part it
was offered (decisions P5D-14 to P5D-18): a box whose fetch failed where it could not report over
HTTPS says HELLO too, to send ``node.modes_failed`` in the game, and then leaves the join. A HELLO
without those reports leaves the fetch on its way (``hello_seen``) until that event, the missing
report, or the timeout (reason ``report_lost``); ``node.modes_failed`` is taken even after a fetch
ended in its HELLO (every part in, yet the composed game does not load on the box).

Served without a token, for the boxes: ``GET /api/v1/mode-packages/{id}/release`` (the signed
manifest and signature, exactly as signed) and ``.../package`` (the archive, exactly as signed),
only for a part of the live game's mode the controller offers; ``POST /api/v1/mode-packages/report``
(an HMAC-SHA256 with the game key, as a firmware report). A failure the box cannot report over
HTTPS comes as the event ``node.modes_failed`` over LoRa.

**Join key 17** (``forget_modes``): the GM marks a box in the *Boxes* tab, and its next invite
makes it forget every package it fetched (the mark goes once that box says HELLO in that game).

The fetches live in memory, as the firmware updates do; what each box keeps (from its last report)
and the boxes marked to forget are in the store's settings.
"""

from __future__ import annotations

import hmac
import json
import logging
import re
import threading
import time
from typing import Any, Callable, Optional

from . import firmware_release as fr
from . import mode_package as mp
from .engine import Conflict, Controller, ControllerError, NotFound

log = logging.getLogger("atalaia.mode_fetch")

ACTIVE = ("sent", "fetching", "installed")  # a fetch on its way: the start guard waits
MODES_FAILED = "node.modes_failed"  # a box's failure said over LoRa (protocol/mode-packages.md)
REASON = re.compile(r"[a-z][a-z_]{0,23}")
REPORT_LOST = "report_lost"  # a HELLO, then neither the missing reports nor node.modes_failed
BOXES_KEPT = 64  # boxes whose fetched modes the store remembers
DEVICE = re.compile(r"[0-9a-f]{16}")
# The states of one of a game's parts, for the offer (what the console shows): a box can be sent
# "offered" parts; "builtin" ones are in its firmware already; the rest say what to do.
GOOD = ("offered", "builtin")


class ModeFetch:
    """The live game's fetches, the offer of its parts, and what boxes keep."""

    def __init__(self, controller: Controller, box_keys: list[str], timeout_s: float = 300.0,
                 clock: Callable[[], float] = time.time) -> None:
        self.controller = controller
        self.box_keys = list(box_keys)
        self.timeout_s = timeout_s
        self.clock = clock
        self._lock = threading.Lock()
        self.attempts: dict[int, dict[str, Any]] = {}  # node id -> the live game's fetch for it
        controller.mode_fetch = self
        controller.start_guards.append(self.busy)
        controller.add_listener(self.on_message)

    # ---- the boxes' keys and the offer ----------------------------------------------------

    def box_key_ids(self) -> list[str]:
        return [fr.key_id(k) for k in self.box_keys]

    def https(self) -> bool:
        c = self.controller
        return c.ca_sha256 is not None and bool(c.link_urls)

    def part(self, mode_id: str, installed: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """One part of a game's mode, and whether a box can be sent it (``state``)."""
        if installed is None:
            installed = {m.id: m for m in self.controller.modes.all()}
        pkg = installed.get(mode_id)
        out: dict[str, Any] = {"id": mode_id, "name": None, "version": None, "kind": None, "min_tier": None,
                               "size": None, "key_id": None, "verified": None}
        if pkg is None:
            return {**out, "state": "missing"}
        out.update(name=pkg.mode.name, version=pkg.mode.version, kind=pkg.kind)
        if pkg.builtin:
            return {**out, "state": "builtin"}
        signed = pkg.signed
        if not signed:
            return {**out, "state": "unsigned"}
        out.update(min_tier=signed.get("min_tier"), size=signed.get("size"), key_id=signed.get("key_id"),
                   verified=signed.get("verified"))
        sm = self.controller.signed_modes
        trust = sm.trust(signed.get("key_id")) if sm is not None else "untrusted"
        if trust != "trusted":
            state = trust  # revoked, untrusted: this controller does not vouch for it any more
        elif signed.get("kind") not in mp.BOX_KINDS:
            state = "kind"
        elif signed.get("key_id") not in self.box_key_ids():
            state = "no_box_key"
        elif not isinstance(signed.get("size"), int) or signed["size"] > mp.BOX_MAX_PACKAGE_BYTES:
            state = "too_big"
        elif self.controller.store.mode_package(mode_id) is None:
            state = "unsigned"
        else:
            state = "offered"
        return {**out, "state": state}

    def offer(self, node_mode_id: str, tier: Optional[int] = None) -> dict[str, Any]:
        """What a box running ``node_mode_id`` (a join's mode_id) can be sent: its parts, and
        ``why`` a fetch cannot help (None: it can). ``tier``: the box's (HELLO's: 0 full, 1 reduced)."""
        installed = {m.id: m for m in self.controller.modes.all()}
        parts = [self.part(p, installed) for p in node_mode_id.split("+")]
        why: Optional[str] = None
        if not self.box_keys:
            why = "no_box_keys"
        elif not self.https():
            why = "no_https"
        elif any(p["state"] not in GOOD for p in parts):
            why = next(p["state"] for p in parts if p["state"] not in GOOD)
        elif all(p["state"] == "builtin" for p in parts):
            why = "firmware"  # every part is built in: the box's firmware is older than this one's
        elif tier == 1 and any(p["state"] == "offered" and p["min_tier"] == "full" for p in parts):
            why = "tier"
        return {"mode_id": node_mode_id, "parts": parts, "ok": why is None, "why": why}

    def refusal(self, node_mode_id: str, tier: Optional[int] = None) -> Optional[str]:
        """Why a join with key 16 for this mode would not help (Controller.issue_join), or None."""
        o = self.offer(node_mode_id, tier)
        if o["ok"]:
            return None
        return {"no_box_keys": "no box mode keys are set ([modes] box_keys): the boxes would take nothing",
                "no_https": "this controller does not serve HTTPS ([api] tls_port): boxes fetch modes only over "
                            "HTTPS pinned to the field CA",
                "firmware": "every part of this mode is built into the firmware: a box without it needs a "
                            "firmware update, not a fetch",
                "tier": "a Reduced box cannot run a part that needs a Full box"}.get(
            o["why"], f"a part of {node_mode_id} cannot be sent to boxes ({o['why']}): upload it as a package signed "
                      "with a key built into the boxes' firmware")

    def roles(self) -> dict[str, Any]:
        """The live game's roles and what a box of each runs, with the offer."""
        c = self.controller
        game = c.game
        if game is None:
            return {}
        try:
            pkg = c.modes.get(game["mode_id"])
        except Exception:  # noqa: BLE001 (parts that do not compose: nothing to offer)
            pkg = None
        if pkg is None:
            return {}
        return {role: self.offer(pkg.mode.node_mode_id(role)) for role in sorted(pkg.mode.roles)}

    # ---- what boxes fetch (no token) --------------------------------------------------------

    def _served(self, mode_id: str) -> tuple[dict[str, Any], bytes]:
        """A part of the live game's mode that boxes may fetch now: its signed release and archive."""
        c = self.controller
        game = c.game
        if game is None or game["state"] != "ready":
            raise Conflict("modes are sent to boxes only between games, while a live game is ready")
        if not isinstance(mode_id, str) or mode_id not in game["mode_id"].split("+"):
            raise NotFound("not a part of the live game's mode")
        part = self.part(mode_id)
        archive = c.store.mode_package(mode_id)
        pkg = next((m for m in c.modes.all() if m.id == mode_id), None)
        if part["state"] != "offered" or archive is None or pkg is None or not pkg.signed:
            raise NotFound(f"{mode_id} is not offered to boxes ({part['state']})")
        return pkg.signed, archive

    def release_text(self, mode_id: str) -> bytes:
        signed, _ = self._served(mode_id)
        return mp.Release(signed["id"], signed["version"], signed["kind"], signed["min_tier"], signed["size"],
                          signed["sha256"], signed["signature"]).text()

    def archive(self, mode_id: str) -> bytes:
        return self._served(mode_id)[1]

    # ---- the fetches ------------------------------------------------------------------------

    def track(self, game_id: int, node_id: int, role: str, mode_id: str, device: Optional[str],
              fetch: bool, forget: bool) -> None:
        """A join with key 16 (or 17) was made for this node (Controller.issue_join)."""
        if not fetch and not forget:
            # A plain join for this node: a fetch made for it before (a failed one) is over.
            with self._lock:
                dropped = self.attempts.pop(node_id, None) is not None
            if dropped:
                self._emit()
            return
        # The parts the box is offered: its HELLO ends the fetch once reports say it keeps them all.
        parts = [p["id"] for p in self.offer(mode_id)["parts"] if p["state"] == "offered"] if fetch else []
        with self._lock:
            now = self.clock()
            self.attempts[node_id] = {
                "node_id": node_id, "game": game_id, "device_id": device, "role": role, "mode_id": mode_id,
                "fetch": fetch, "forget": forget, "state": "sent" if fetch else "forget", "reason": None,
                "mode": None, "installed": [], "parts": parts, "kept": None, "hello_seen": False,
                "sent_at": now, "updated_at": now}
        log.info("game %d: a join for node %d (%s) %s", game_id, node_id, mode_id,
                 "fetches its missing modes" if fetch else "forgets its fetched modes")
        self._emit()

    def _live(self) -> Optional[int]:
        game = self.controller.game
        return game["id"] if game is not None else None

    def _refresh(self) -> None:
        now = self.clock()
        for a in self.attempts.values():
            if a["state"] in ACTIVE and now - a["updated_at"] > self.timeout_s:
                # After its HELLO: it said neither that it keeps every part nor why not (P5D-16).
                a.update(state="timeout", reason=REPORT_LOST if a.get("hello_seen") else None, updated_at=now)

    def _covered(self, a: dict[str, Any], stored: Optional[dict[str, str]] = None) -> bool:
        """Whether HTTPS reports say the box keeps every part it was offered: installed in this
        fetch, or in the ``kept`` of its last report (this fetch's, or ``stored``, from before: a box
        that lacked nothing when the join came fetches nothing and reports nothing)."""
        have = set(a["installed"]) | set(a.get("kept") or {}) | set(stored or {})
        return set(a.get("parts") or ()) <= have

    def _stored_kept(self, device: Optional[str]) -> Optional[dict[str, str]]:
        """What a box keeps, from its last report (the store's ``mode_fetch.boxes``)."""
        if device is None:
            return None
        box = self._load("mode_fetch.boxes", {}).get(device)
        kept = box.get("kept") if isinstance(box, dict) else None
        return kept if isinstance(kept, dict) else None

    def fetches(self) -> list[dict[str, Any]]:
        """The live game's fetches (and forgets), by node id."""
        with self._lock:
            self._refresh()
            live = self._live()
            return [dict(a) for _, a in sorted(self.attempts.items()) if a["game"] == live]

    def busy(self) -> Optional[str]:
        """Why the live game may not start now: boxes still fetching its modes."""
        with self._lock:
            self._refresh()
            live = self._live()
            nodes = sorted(n for n, a in self.attempts.items() if a["game"] == live and a["state"] in ACTIVE)
        if not nodes:
            return None
        return (f"boxes are fetching this game's modes: node(s) {', '.join(map(str, nodes))}; wait for them, or "
                "stop waiting (DELETE /api/v1/mode-fetch) before the game starts")

    def holds(self, node_id: int) -> bool:
        """A node of the live game whose fetch has not ended in its HELLO: not joined yet, even if
        the controller heard it (its HELLO without the reports, its node.modes_failed, before it
        left the join)."""
        with self._lock:
            a = self.attempts.get(node_id)
            return a is not None and a["game"] == self._live() and a["fetch"] and a["state"] != "done"

    def invite_view(self, inv: dict[str, Any]) -> dict[str, Any]:
        """An invite as the GM sees it (reinvite.py): its box's HELLO made it *joined*, but a box
        whose fetch has not ended in that HELLO has not joined: *accepted* while the controller
        waits for its news, *failed* once the fetch failed, timed out or was no longer waited for
        (P5D-17)."""
        if inv.get("status") != "joined":
            return inv
        with self._lock:
            a = self.attempts.get(inv.get("node_id"))
            if a is None or a["game"] != inv.get("game") or not a["fetch"] or a["state"] == "done" or \
                    (a["device_id"] is not None and a["device_id"] != inv.get("device_id")):
                return inv
            state, reason = a["state"], a["reason"]
        if state in ACTIVE:
            return {**inv, "status": "accepted", "detail": None}
        return {**inv, "status": "failed", "detail": f"mode fetch {state}" + (f": {reason}" if reason else "")}

    def cancel(self) -> list[int]:
        """The GM stops waiting for the fetches on their way (the start guard lets the game start)."""
        with self._lock:
            now, live = self.clock(), self._live()
            nodes = [n for n, a in self.attempts.items() if a["game"] == live and a["state"] in ACTIVE]
            for n in nodes:
                self.attempts[n].update(state="cancelled", updated_at=now)
        if nodes:
            log.warning("mode fetches of nodes %s: the GM stopped waiting", nodes)
            self._emit()
        return nodes

    def on_invites(self, invites: list[dict[str, Any]]) -> None:
        """The invites' progress (reinvite.py): a box that accepted a join with key 16 is fetching;
        one that answered anything else, or never, did not take it (``no_mode`` from a box whose
        firmware cannot fetch, or that has no mode key built in)."""
        changed = False
        with self._lock:
            now = self.clock()
            for inv in invites:
                a = self.attempts.get(inv.get("node_id"))
                if a is None or a["game"] != inv.get("game") or a["device_id"] != inv.get("device_id"):
                    continue
                if inv["status"] == "accepted" and a["state"] == "sent":
                    a.update(state="fetching", updated_at=now)
                    changed = True
                elif inv["status"] in ("refused", "failed") and a["state"] in ACTIVE:
                    reason = inv.get("detail") if inv["status"] == "refused" else "no_answer"
                    a.update(state="failed", reason=reason if isinstance(reason, str) and REASON.fullmatch(reason)
                             else "no_answer", updated_at=now)
                    changed = True
        if changed:
            self._emit()

    def report(self, body: bytes, mac: Any) -> dict[str, Any]:
        """A box's report on a part it fetched, authenticated with the live game's key."""
        try:
            r = mp.parse_report(body)
        except mp.PackageError:
            raise ControllerError("not a mode fetch report") from None
        c = self.controller
        try:
            key = c.game_key(r["game"])
        except ControllerError:
            raise Conflict("not this controller's live game") from None
        if not isinstance(mac, str) or not re.fullmatch(r"[0-9a-f]{64}", mac) or \
                not hmac.compare_digest(mp.report_mac(key, body), mac):
            raise ControllerError("the report's MAC does not verify")
        with self._lock:
            a = self.attempts.get(r["node"])
            now = self.clock()
            accepted = a is not None and a["game"] == r["game"] and a["fetch"] and \
                a["state"] in ACTIVE + ("timeout",)
            joined = False
            if accepted:
                assert a is not None
                a["kept"] = dict(r["kept"])
                if r["result"] == "installed":
                    if r["mode"] not in a["installed"]:
                        a["installed"].append(r["mode"])
                    a.update(state="installed", reason=None, mode=r["mode"], updated_at=now)
                    if a["hello_seen"] and self._covered(a):
                        # The report its HELLO waited for, late (the box got no answer in time).
                        a.update(state="done", updated_at=now)
                        joined = True
                else:
                    a.update(state="failed", reason=r["result"], mode=r["mode"], updated_at=now)
            device = a["device_id"] if a is not None else None
        if device is None:
            device = self._device_of(r["node"])
        self._kept(device, r["node"], r["game"], r["kept"])
        log.warning("box %d: mode %s %s%s", r["node"], r["mode"], r["result"],
                    "" if accepted else " (not a fetch this controller is waiting for)")
        self._emit()
        if joined:
            log.info("box %d: its modes are in place (the report came after its HELLO)", r["node"])
            self._joined_changed()
        return {"accepted": accepted}

    def on_failed_over_radio(self, ev: dict[str, Any]) -> None:
        """node.modes_failed: a box says over LoRa (sealed with the game key) that its fetch failed
        where it could not report over HTTPS (no Wi-Fi, the controller unreachable). It comes after
        the box's HELLO (the event needs the game's link, P5E-8), so it is taken while the fetch
        waits after that HELLO, after a timeout or the GM's *stop waiting*, and even after a fetch
        that ended in its HELLO (every part reported installed, yet the composed game does not load
        on the box: ``load``, P5E-10). A fetch that failed already keeps its first reason (P5D-15)."""
        data = ev.get("data") or {}
        node_id, mode_id, reason = ev.get("node"), data.get("mode"), data.get("reason")
        if not isinstance(node_id, int) or not isinstance(reason, str) or not REASON.fullmatch(reason):
            return
        with self._lock:
            a = self.attempts.get(node_id)
            if a is None or a["game"] != self._live() or not a["fetch"] or a["state"] == "failed":
                log.warning("box %d said over the radio that fetching %s failed (%s): not a fetch it was sent",
                            node_id, mode_id, reason)
                return
            heard = a["hello_seen"] or a["state"] == "done"  # its HELLO made the invite "joined"
            a.update(state="failed", reason=reason, mode=mode_id if isinstance(mode_id, str) else None,
                     updated_at=self.clock())
        log.warning("box %d: fetching %s failed: %s (said over the radio)", node_id, mode_id, reason)
        self._emit()
        if heard:
            self._joined_changed()

    def on_message(self, msg: dict[str, Any]) -> None:
        """A HELLO ends a forget, and a fetch whose HTTPS reports say the box keeps every part it
        was offered (P5D-14); node.modes_failed fails a fetch."""
        if msg.get("type") == "event" and isinstance(msg.get("event"), dict) and \
                msg["event"].get("type") == MODES_FAILED:
            self.on_failed_over_radio(msg["event"])
            return
        if msg.get("type") != "node" or msg.get("kind") != "hello" or not isinstance(msg.get("node"), dict):
            return
        node = msg["node"]
        if node.get("node_id") is None:
            return
        node_id = int(node["node_id"])
        with self._lock:
            a = self.attempts.get(node_id)
            # What it kept before this join; not with key 17, which made it forget all of that.
            device = a["device_id"] if a is not None and not a["forget"] else None
        stored = self._stored_kept(device)
        with self._lock:
            a = self.attempts.get(node_id)
            if a is None or a["game"] != msg.get("game") or a["state"] in ("done", "failed") or \
                    (a["fetch"] and a["hello_seen"]):
                return  # a failed fetch stays failed (that box is leaving the join); a HELLO again
            forgot = a["device_id"] if a["forget"] else None  # key 17 is read first, whatever follows
            done = not a["fetch"] or self._covered(a, stored)
            if done:
                a.update(state="done", reason=None, updated_at=self.clock())
            else:
                # A HELLO without a report for every part: the HELLO a box says to tell over the
                # radio that its fetch failed (P5E-8), or one whose last report was lost.
                a.update(hello_seen=True, updated_at=self.clock(),
                         state="fetching" if a["state"] in ACTIVE else a["state"])
            missing = sorted(set(a["parts"]) - set(a["installed"]) - set(a["kept"] or {}) - set(stored or {}))
        if forgot:
            self.set_forget(forgot, False)
        if done:
            log.info("box %s said HELLO: its modes are in place", node_id)
        else:
            log.warning("box %s said HELLO without a report that it keeps %s: not joined until that report, "
                        "its node.modes_failed or the timeout", node_id, ", ".join(missing))
        self._emit()

    def _joined_changed(self) -> None:
        """A box shown as joined by its HELLO has not joined after all, or the other way round:
        the invites and the start check change (the console's dialog and Start)."""
        c = self.controller
        with c._lock:
            if c.reinvite is not None:
                c.reinvite.refresh_invites()
            if c.game is not None and c.game.get("state") == "ready":
                c._emit({"type": "game", "game": c.public_game(c.game)})

    # ---- what boxes keep, and forgetting ----------------------------------------------------

    def _device_of(self, node_id: int) -> Optional[str]:
        fc = self.controller.fc
        node = fc.nodes.get(node_id) if fc is not None else None
        dev = node.hello.get("device_id") if node is not None else None
        return bytes(dev).hex() if isinstance(dev, (bytes, bytearray)) else None

    def _load(self, name: str, default: Any) -> Any:
        raw = self.controller.store.get_setting(name)
        try:
            return json.loads(raw) if raw else default
        except ValueError:
            return default

    def _kept(self, device: Optional[str], node_id: int, game_id: int, kept: dict[str, str]) -> None:
        """What a box keeps, from its last report, by its device id (by node and game without one)."""
        key = device or f"node-{node_id}"
        boxes = self._load("mode_fetch.boxes", {})
        boxes.pop(key, None)
        boxes[key] = {"device_id": device, "node_id": node_id, "game": game_id, "kept": kept,
                      "reported_at": round(self.clock(), 3)}
        while len(boxes) > BOXES_KEPT:
            boxes.pop(next(iter(boxes)))
        self.controller.store.set_setting("mode_fetch.boxes", json.dumps(boxes))

    def forget_marked(self) -> list[str]:
        return sorted(self._load("mode_fetch.forget", []))

    def set_forget(self, device: Any, on: Any) -> dict[str, Any]:
        """Marks a box (its device id) to forget its fetched modes at its next invite (join key 17)."""
        if not isinstance(device, str) or not DEVICE.fullmatch(device):
            raise ControllerError("device_id: 16 lower-case hex digits")
        if not isinstance(on, bool):
            raise ControllerError("forget: true or false")
        marked = set(self.forget_marked())
        if on:
            marked.add(device)
        else:
            marked.discard(device)
        self.controller.store.set_setting("mode_fetch.forget", json.dumps(sorted(marked)))
        if on:
            log.warning("box %s will forget its fetched modes at its next invite", device)
        self._emit()
        return {"device_id": device, "forget": on}

    def boxes(self) -> list[dict[str, Any]]:
        """Each box's fetched modes from its last report, and whether it is marked to forget them."""
        marked = set(self.forget_marked())
        out = [{**b, "forget": b.get("device_id") in marked}
               for b in self._load("mode_fetch.boxes", {}).values()]
        listed = {b.get("device_id") for b in out}
        out += [{"device_id": d, "node_id": None, "game": None, "kept": None, "reported_at": None, "forget": True}
                for d in sorted(marked - listed)]
        return sorted(out, key=lambda b: (b["device_id"] is None, b["device_id"] or "", b["node_id"] or 0))

    # ---- what the console shows -----------------------------------------------------------

    def status(self) -> dict[str, Any]:
        return {"box_keys": self.box_key_ids(), "https": self.https(), "timeout_s": self.timeout_s,
                "max_package_bytes": mp.BOX_MAX_PACKAGE_BYTES, "game": self._live(), "roles": self.roles(),
                "fetches": self.fetches(), "boxes": self.boxes()}

    def _emit(self) -> None:
        self.controller._emit({"type": "mode_fetch", "game": self._live(), "fetches": self.fetches(),
                               "boxes": self.boxes()})
