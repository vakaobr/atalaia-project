# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Adopting a box by the code it shows, over the radio (protocol/adoption.md section 7).

An unadopted box shows a 6-digit code and sends OFFER pair frames (type 10, in
the clear) on the default channel, 869.525 MHz. The controller hears them through
its USB modem (FIELD_RX: the modem carries pair frames like field frames) and the
console lists the boxes; the GM picks one and types its code. A run of CPace
(CPACE-X25519-SHA512, atalaia_sim.cpace) with that code follows: START (Ya), the
box's REPLY (Yb and its confirmation), then, only if the box's confirmation
matches, KEY: the controller's confirmation and the field join key and name sealed
with AES-128-CCM under a key derived from the run's ISK; the box adopts the field
by adoption.c's rules and answers DONE (its result and the fingerprint of the key
it now holds, authenticated). A wrong code shows in the box's confirmation and
the run ends there: the join key never leaves without it.

Nonces never depend on a random number generator (decision RJ-15's rule): KEY's
is the pseudonym of a sender id drawn fresh with os.urandom for every run (never
stored), boot 1, count 0; its key is new to every run anyway. The run's scalar,
sid and keys live only in memory and are dropped on every outcome. One run at a
time; three STARTs and three KEYs at most, ten seconds each step. Every run is
logged and recorded with the other adoptions (adoption.py). GM token only.

The modem listens on the field's channel. When that is not 869.525 MHz and no
game is live, "listen" tunes it there for five minutes (and back afterwards);
with a game live on another channel, pairing waits for the game to end.
"""

from __future__ import annotations

import hmac
import logging
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

from atalaia_sim import cpace, eu868
from atalaia_sim import pair_frame as pf

if TYPE_CHECKING:
    from .engine import Controller

log = logging.getLogger("atalaia.adoption")

PAIR_CHANNEL_HZ = eu868.DEFAULT_CHANNEL_HZ  # where an unadopted EU868 box listens (its Kconfig default)
# An unadopted box listens on its region's default channel (Kconfig ATALAIA_RADIO_DEFAULT_CHANNEL_HZ):
# Pairing._pair_hz() is the field region's (RFC 0001 Amendment 12).
OFFER_TTL_MS = 60_000  # a box not heard this long leaves the list (it offers every 15 s or more)
STEP_MS = 10_000  # START -> REPLY, KEY -> DONE
RESEND_MS = 3_000
SENDS_MAX = 3
LISTEN_MS = 300_000  # the modem stays on the pairing channel this long after "listen"


@dataclass
class Run:
    pair_id: bytes
    name: str
    sid: bytes
    ya_secret: bytes
    ya: bytes
    sender: bytes
    started_ms: int
    state: str = "starting"  # starting -> sealing -> done | failed
    detail: str = ""
    result: Optional[str] = None
    keys: Optional[dict[str, bytes]] = None
    frame: bytes = b""
    sends: int = 0
    step_ms: int = 0
    last_send_ms: int = 0
    tx_ids: set[int] = field(default_factory=set)
    ended_ms: Optional[int] = None

    def public(self) -> dict[str, Any]:
        return {"pair_id": self.pair_id.hex(), "name": self.name, "state": self.state, "detail": self.detail,
                "result": self.result, "sends": self.sends}

    def wipe(self) -> None:
        self.ya_secret = b""
        self.keys = None
        self.frame = b""


class Pairing:
    def __init__(self, controller: "Controller") -> None:
        self.ctl = controller
        self.offers: dict[str, dict[str, Any]] = {}
        self.run: Optional[Run] = None
        self.listen_until_ms = 0
        self.retuned = False
        self.ignored = 0

    # --- the radio --------------------------------------------------------------------

    def _modem_ok(self) -> bool:
        modem = self.ctl.modem
        return modem is not None and modem.is_up

    def _send(self, frame: bytes) -> Optional[int]:
        if not self._modem_ok():
            return None
        return self.ctl.modem.send_field(frame)

    def is_ours(self, frame: bytes) -> bool:
        return pf.is_frame(frame)

    def on_frame(self, frame: bytes, rssi: int, snr: int) -> None:
        """A pair frame heard (FIELD_RX)."""
        with self.ctl._lock:
            try:
                msg = pf.decode(frame)
            except pf.PairFrameError:
                self.ignored += 1
                return
            now = self.ctl.now_ms()
            hexid = msg["pair_id"].hex()
            if msg["kind"] == "offer":
                known = self.offers.get(hexid)
                if known is not None and known["name"] != msg["name"]:
                    # A pair id is a box's for its whole pairing: the same id under another name is
                    # someone else's frame. The first name stays; the entry is flagged (AD-26).
                    known["conflict"] = True
                    self.ignored += 1
                    return
                self.offers[hexid] = {"pair_id": hexid, "name": msg["name"], "tier": msg["tier"], "rssi": rssi,
                                      "snr": snr, "seen_ms": now,
                                      "conflict": bool(known and known.get("conflict"))}
                return
            run = self.run
            if run is None or run.state in ("done", "failed") or msg["pair_id"] != run.pair_id \
                    or msg.get("sid") != run.sid:
                self.ignored += 1  # another run's, a replay, or nobody's
                return
            if msg["kind"] == "reply" and run.state == "starting":
                self._on_reply(run, msg, now)
            elif msg["kind"] == "done" and run.state == "sealing":
                self._on_done(run, msg, now)
            else:
                self.ignored += 1

    def owns_tx(self, tx_id: int) -> bool:
        return self.run is not None and tx_id in self.run.tx_ids

    def on_ack(self, tx_id: int, status: str) -> None:
        with self.ctl._lock:
            run = self.run
            if run is None or tx_id not in run.tx_ids:
                return
            run.tx_ids.discard(tx_id)
            if status != "ok":
                log.warning("pairing: frame %d not sent: %s", tx_id, status)
                if status == "duty_cycle":
                    run.detail = "duty_cycle"

    # --- a run -------------------------------------------------------------------------

    def _transmit(self, run: Run, now: int) -> None:
        tx = self._send(run.frame)
        run.sends += 1
        run.last_send_ms = now
        if tx is not None:
            run.tx_ids.add(tx)

    def _fail(self, run: Run, detail: str, now: int) -> None:
        run.state = "failed"
        run.detail = detail
        run.ended_ms = now
        run.wipe()
        self._record(run)
        log.warning("pairing: box %s (%s): failed, %s", run.name, run.pair_id.hex(), detail)

    def _on_reply(self, run: Run, msg: dict[str, Any], now: int) -> None:
        try:
            k = cpace.scalar_mult_vfy(run.ya_secret, msg["point"])
        except cpace.CpaceError:
            self._fail(run, "bad_answer", now)
            return
        keys = pf.keys(pf.isk(run.sid, k, run.ya, msg["point"]), run.sid)
        run.ya_secret = b""
        if not hmac.compare_digest(pf.tag_reply(keys), msg["tag"]):
            self._fail(run, "wrong_code", now)  # the box burns that code too: it shows a new one
            return
        join_key = self.ctl.join_key
        name = self.ctl.adoption.field_name() if self.ctl.adoption is not None else ""
        nonce = pf.key_nonce(keys, run.sender)
        sealed = pf.seal_key(keys, nonce, run.pair_id, run.sid, join_key, name)
        run.keys = keys
        run.frame = pf.encode({"kind": "key", "pair_id": run.pair_id, "sid": run.sid, "tag": pf.tag_key(keys),
                               "nonce": nonce, "sealed": sealed})
        run.state = "sealing"
        run.sends = 0
        run.step_ms = now
        self._transmit(run, now)

    def _on_done(self, run: Run, msg: dict[str, Any], now: int) -> None:
        keys = run.keys
        if keys is None or not hmac.compare_digest(
                pf.tag_done(keys, msg["result"], msg["fingerprint"]), msg["tag"]):
            self.ignored += 1
            return
        result = msg["result"]
        run.result = result
        run.ended_ms = now
        if result in pf.OK_RESULTS and msg["fingerprint"] != pf.fingerprint_bytes(self.ctl.join_key):
            run.state, run.detail = "failed", "fingerprint"
        elif result in pf.OK_RESULTS:
            run.state = "done"
            self.offers.pop(run.pair_id.hex(), None)
        else:
            run.state, run.detail = "failed", "box_refused"
        run.wipe()
        self._record(run)
        log.warning("pairing: box %s (%s): %s (%s)", run.name, run.pair_id.hex(), run.state, result)

    def _record(self, run: Run) -> None:
        adoption = self.ctl.adoption
        if adoption is None:
            return
        from atalaia_sim import field_card  # noqa: PLC0415
        adoption._record({"method": "radio", "result": run.result or run.detail or run.state,
                          "field": field_card.fingerprint(self.ctl.join_key), "box": run.name,
                          "pair_id": run.pair_id.hex()})

    def tick(self, now: int) -> None:
        with self.ctl._lock:
            run = self.run
            if run is not None and run.state in ("starting", "sealing"):
                if now - run.step_ms >= STEP_MS:
                    self._fail(run, "no_answer" if run.state == "starting" else "no_done", now)
                elif run.sends < SENDS_MAX and now - run.last_send_ms >= RESEND_MS:
                    self._transmit(run, now)
            for hexid in [h for h, o in self.offers.items() if now - o["seen_ms"] > OFFER_TTL_MS]:
                del self.offers[hexid]
            if self.retuned and (now >= self.listen_until_ms or self.ctl._channel_lock_reason()):
                self._tune_back()

    # --- the channel -------------------------------------------------------------------

    def channel_moved(self, why: str) -> None:
        """The engine tuned the modem to the field's channel (the channel set, a scan, the modem back):
        no longer listening for boxes unless that is the pairing channel; a run under way there fails."""
        with self.ctl._lock:
            was = self.retuned
            self.retuned = False
            if was:
                self.listen_until_ms = 0
                log.info("pairing: no longer listening on %d Hz (%s)", self._pair_hz(), why)
            run = self.run
            if run is not None and run.state in ("starting", "sealing") and \
                    self.ctl.field_channel != self._pair_hz():
                self._fail(run, "channel_changed", self.ctl.now_ms())

    def _pair_hz(self) -> int:
        """Where an unadopted box of the field's region listens: the region's default channel."""
        return self.ctl.field_region.default_channel_hz

    def _current_channel(self) -> int:
        game = self.ctl.game
        if game is not None and self.ctl._channel_lock_reason():
            return int(game.get("channel_hz") or self.ctl.field_channel)
        return self._pair_hz() if self.retuned else self.ctl.field_channel

    def _tune_back(self) -> None:
        self.retuned = False
        if self._modem_ok() and not self.ctl._channel_lock_reason():
            self.ctl.modem.set_channel(self.ctl.field_channel)
            log.info("pairing: the modem is back on the field's channel, %d Hz", self.ctl.field_channel)

    def listen(self) -> dict[str, Any]:
        """Keeps the modem on the pairing channel for LISTEN_MS (tuning it there if needed)."""
        from .engine import Conflict, Unavailable  # noqa: PLC0415
        with self.ctl._lock:
            if not self._modem_ok():
                raise Unavailable(f"the radio modem is {self.ctl.radio_state}: no pairing")
            if not getattr(self.ctl.modem, "has_pair_frames", False):
                raise Unavailable("the modem's firmware does not carry pair frames: update it")
            current = self._current_channel()
            if current != self._pair_hz():
                reason = self.ctl._channel_lock_reason()
                if reason:
                    raise Conflict(f"new boxes listen on {self._pair_hz()} Hz and the radio is on {current} Hz "
                                   f"for the live game ({reason}): pair them before or after it")
                self.ctl.modem.set_channel(self._pair_hz())
                self.retuned = True
                log.info("pairing: the modem listens on %d Hz for unadopted boxes", self._pair_hz())
            self.listen_until_ms = self.ctl.now_ms() + LISTEN_MS
            return self._status()

    def pair(self, pair_id: Any, code: Any) -> dict[str, Any]:
        """Starts a run with the box offering pair_id and the code the GM read on its screen."""
        from .engine import Conflict, ControllerError, NotFound, Unavailable  # noqa: PLC0415
        with self.ctl._lock:
            if not isinstance(pair_id, str) or len(pair_id) != 2 * pf.PAIR_ID_SIZE:
                raise ControllerError("pair_id: the box's 16 hex digits, from the list")
            if not isinstance(code, str) or not pf.code_ok(code.replace(" ", "")):
                raise ControllerError("code: the 6 digits the box shows")
            code = code.replace(" ", "")
            offer = self.offers.get(pair_id.lower())
            if offer is None:
                raise NotFound("that box is not offering itself now: check its screen and look again")
            if not self._modem_ok():
                raise Unavailable(f"the radio modem is {self.ctl.radio_state}: no pairing")
            if self.run is not None and self.run.state in ("starting", "sealing"):
                raise Conflict(f"a pairing with {self.run.name} is under way")
            if not self.ctl.join_key:
                raise Unavailable("no field join key on this controller")
            now = self.ctl.now_ms()
            pid = bytes.fromhex(pair_id)
            sid = os.urandom(pf.SID_SIZE)
            ya_secret = os.urandom(32)
            ya = cpace.scalar_mult(ya_secret, pf.generator(code, pid, sid))
            run = Run(pair_id=pid, name=offer["name"], sid=sid, ya_secret=ya_secret, ya=ya,
                      sender=os.urandom(8), started_ms=now, step_ms=now)
            run.frame = pf.encode({"kind": "start", "pair_id": pid, "sid": sid, "point": ya})
            self.run = run
            self.listen_until_ms = max(self.listen_until_ms, now + LISTEN_MS)
            log.info("pairing: started with box %s (%s)", run.name, pair_id)
            self._transmit(run, now)
            return self._status()

    def _status(self) -> dict[str, Any]:
        now = self.ctl.now_ms()
        offers = [dict(o, seen_ms_ago=now - o["seen_ms"]) for o in self.offers.values()]
        names: dict[str, int] = {}
        for o in offers:
            o.pop("seen_ms", None)
            names[o["name"]] = names.get(o["name"], 0) + 1
            o["short_id"] = o["pair_id"][:4]  # what the box's screen shows as "Id"
        for o in offers:
            # Two boxes offering under one name: one may be pretending (AD-26); the console flags both.
            o["duplicate_name"] = names[o["name"]] > 1
        return {"offers": sorted(offers, key=lambda o: o["name"]),
                "run": self.run.public() if self.run is not None else None,
                "channel_hz": self._pair_hz(), "radio_channel_hz": self._current_channel(),
                "listening": self._current_channel() == self._pair_hz(),
                "listen_ms_left": max(0, self.listen_until_ms - now) if self.retuned else None,
                "radio": self._modem_ok(),
                "pair_frames": self._modem_ok() and bool(getattr(self.ctl.modem, "has_pair_frames", False)),
                "ignored": self.ignored}

    def status(self) -> dict[str, Any]:
        with self.ctl._lock:
            return self._status()
