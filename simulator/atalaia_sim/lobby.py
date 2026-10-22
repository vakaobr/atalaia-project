# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Re-inviting boxes between games (protocol/field-frames.md): both sides of the field frames.

``IdleBox`` is a box's side, as firmware/esp32/main/box_lobby.c does it: a free
box (no game joined, or its game over) announces itself on its last channel
with a fresh token, answers a controller's DISCOVER, and takes an INVITE for
its device id and current token, which carries a join payload checked exactly
as a card's (protocol/join.md). It answers every invite it could read with an
ANNOUNCE that says how it went, and changes its token when it accepts, so an
invite recorded and played again later is refused.

``Inviter`` is the field controller's side (controller/atalaia_controller/
reinvite.py wraps it): the free boxes it has heard, a DISCOVER, invites
with their parts, retries and progress (invited, accepted, joined, refused,
failed), paced by their time on air, and GAME_OVER: "game N (its key's tag)
is over", sent GAME_OVER_REPEATS times when a game ends (decision OT-13), so
that a box still in it leaves, also when the controller no longer has the
game's key (a restart without persist_game_key).

The same timings as the firmware: an idle box announces 2-20 s after its
game ends (spread, so a field's boxes do not all talk at once), then at an
interval that keeps its announcements within ANNOUNCE_SHARE of its
sub-band's hourly duty-cycle budget (and never more often than once a
minute); it answers a DISCOVER after 0-3 s, at most every quarter of that
interval; its token changes every 10 minutes (the previous one still
counts) and when it accepts an invite.
"""

from __future__ import annotations

import math
import os
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from . import eu868
from . import field_frame as ff
from . import join as joinfmt

ANNOUNCE_SHARE = 0.02        # of the sub-band's hourly duty-cycle budget, for the periodic announcement
ANNOUNCE_MIN_MS = 60_000
FIRST_ANNOUNCE_MS = (2_000, 20_000)
DISCOVER_ANSWER_MS = (0, 3_000)
INVITE_ANSWER_MS = (100, 600)
TOKEN_ROTATE_MS = 600_000
ANSWER_REPEAT_MS = 10_000    # one answer per invite in this time
ANSWER_IDS = 8               # invites a box remembers answering (box_lobby.c's table)
ANSWERS_PER_MIN = 6          # answers a box sends a minute at most, in all
ENDED_GAMES = 4              # games a box remembers having played to their end
INVITE_RETRY_MS = 6_000      # the controller resends an invite unanswered for this long
INVITE_ATTEMPTS = 3
DISCOVER_MIN_MS = 10_000     # a controller sends at most one DISCOVER in this time
BOX_FORGET_MS = 2 * 3_600_000
GAP_MS = 50                  # between a controller's frames, on top of their time on air
PART_GAP_MS = 150            # between an invite's parts: the box re-arms its receiver after
                             # each part, and back-to-back parts lost the second on the bench
GAME_OVER_REPEATS = 3        # a GAME_OVER goes this many times (decision OT-15) ...
GAME_OVER_GAP_MS = 4_000     # ... this far apart: 3 x 92 ms of air in all


def announce_interval_ms(channel_hz: int, frame_len: int) -> int:
    """How often a free box announces: ANNOUNCE_SHARE of its sub-band's budget, at least a minute apart."""
    band = eu868.band_of(channel_hz)
    duty = band.duty if band is not None else 0.01
    return max(ANNOUNCE_MIN_MS, math.ceil(eu868.airtime_ms(frame_len) / (ANNOUNCE_SHARE * duty)))


def missing_parts(j: dict, installed: Optional[set[str]]) -> list[str]:
    """The parts of a join's mode_id a box with these modes lacks (None: it has every mode)."""
    if installed is None:
        return []
    return [m for m in j["mode_id"].split("+") if m not in installed]


def can_fetch(j: dict) -> bool:
    """A join with key 16 and the controller's link (keys 13 and 14): the box may fetch the
    signed packages it lacks (phase 5 plan phase 13, protocol/mode-packages.md)."""
    return bool(j.get("fetch_modes") and j.get("ca_sha256") and j.get("urls"))


def join_result(join_key: bytes, payload: bytes, installed: Optional[set[str]] = None) -> tuple[str, Optional[dict]]:
    """What a box makes of a join payload: (result, join) with a field_frame result name.

    A part the box lacks is ``no_mode``, unless the join asks it to fetch the missing modes
    (key 16, with keys 13 and 14): then the box accepts the join *fetching* and says HELLO
    only once it has them (protocol/mode-packages.md, "Fetching missing modes")."""
    try:
        j = joinfmt.decode(payload, join_key)
    except joinfmt.JoinError:
        return "refused", None
    if j["kind"] != "node":
        return "not_box", None
    if missing_parts(j, installed) and not can_fetch(j):
        return "no_mode", None
    return "accepted", j


class IdleBox:
    """A box's side of the field frames (the simulator's model of box_lobby.c)."""

    def __init__(self, join_key: bytes, name: str = "field-box", *, rng: Optional[random.Random] = None,
                 device_id: Optional[bytes] = None, tier: int = 0, channel_hz: int = eu868.DEFAULT_CHANNEL_HZ,
                 installed: Optional[set[str]] = None, now_ms: int = 0) -> None:
        self.rng = rng or random.Random()
        self.join_key = join_key
        self.key = ff.field_key(join_key)
        self.name = name
        self.tier = tier
        self.channel_hz = channel_hz
        self.installed = installed
        self.fetched: dict[str, str] = {}  # the packages fetched from a controller: id -> version
        self.fetching: list[str] = []      # the parts the joined game's mode needs and the box lacks
        self.device_id = device_id or bytes(self.rng.getrandbits(8) for _ in range(ff.DEVICE_SIZE))
        # The box's nonces: its device id as sender, a boot count kept "in NVS" (RJ-15).
        self.nonces = ff.NonceSource(join_key, self.device_id)
        self.token = self._fresh()
        self.prev_token: Optional[bytes] = None
        self.phase = "idle"          # idle, joined, playing, ended
        self.standalone = False      # a game picked on the box itself is being played
        self.game: Optional[dict[str, Any]] = None
        self.last_game: Optional[int] = None
        self.last_role: Optional[str] = None
        self.ended: list[int] = []
        self.reasm = ff.Reassembly()
        self.answered: dict[int, int] = {}
        self.answer_times: list[int] = []
        self.log: list[str] = []
        self.rotate_at = now_ms + TOKEN_ROTATE_MS
        self.last_announce: Optional[int] = None
        self.next_announce: Optional[int] = now_ms + self.rng.randint(*FIRST_ANNOUNCE_MS)
        self.queue: list[tuple[int, dict[str, Any]]] = []  # (due_ms, announce fields)

    def _fresh(self) -> bytes:
        return bytes(self.rng.getrandbits(8) for _ in range(ff.TOKEN_SIZE))

    @property
    def available(self) -> bool:
        return self.phase in ("idle", "ended") and not self.standalone

    # --- the game it is in ---------------------------------------------------

    def join(self, payload: bytes, now_ms: int = 0, *, invited: bool = False) -> str:
        """A join payload from a card, a text or an invite (the same checks)."""
        if self.phase in ("joined", "playing") or self.standalone:
            return "busy"
        try:
            forget = joinfmt.decode(payload, self.join_key)["forget_modes"]
        except joinfmt.JoinError:
            forget = False
        if forget and self.fetched:
            # Key 17: every package fetched before goes, before the join's modes are looked at.
            self.log.append(f"forgot the fetched modes {', '.join(sorted(self.fetched))}")
            if self.installed is not None:
                self.installed -= set(self.fetched)
            self.fetched = {}
        result, j = join_result(self.join_key, payload, self.installed)
        if result == "accepted" and j is not None and j["game_id"] in self.ended:
            result = "ended"
        if result != "accepted" or j is None:
            return result
        self.game = j
        self.phase = "joined"
        # Key 16: a box that lacks parts fetches them now, and says HELLO only once it has them.
        self.fetching = missing_parts(j, self.installed)
        self.channel_hz = j["channel_hz"]
        self.next_announce = None
        self.queue = [q for q in self.queue if q[1].get("answer")]
        self.log.append(f"{'invited to' if invited else 'joined'} game {j['game_id']} as {j['role']}")
        self._drop_tokens(now_ms)  # joined by any way: no invite from before works now
        return "accepted"

    def start(self) -> None:
        if self.phase == "joined":
            self.phase = "playing"

    def on_game_over(self, msg: dict[str, Any], now_ms: int) -> bool:
        """GAME_OVER (decision OT-13): only the box's own game, by its id and its key's tag, ends."""
        if self.phase not in ("joined", "playing") or self.game is None:
            return False
        if msg["game_id"] != self.game["game_id"] or msg["key_tag"] != ff.key_tag(self.game["game_key"]):
            return False
        self.log.append(f"game {msg['game_id']} is over (said by a field controller)")
        self.end(now_ms)
        return True

    def end(self, now_ms: int = 0) -> None:
        """The game ended (CMD end): the box is free again and soon announces itself."""
        if self.phase not in ("joined", "playing") or self.game is None:
            return
        self.phase = "ended"
        self.last_game, self.last_role = self.game["game_id"], self.game["role"]
        self.ended = ([self.last_game] + [g for g in self.ended if g != self.last_game])[:ENDED_GAMES]
        self.next_announce = now_ms + self.rng.randint(*FIRST_ANNOUNCE_MS)
        self._drop_tokens(now_ms)  # free again: nothing sent before this counts

    def fetched_part(self, mode_id: str, version: str) -> None:
        """A part fetched and checked (the test's stand-in for main/mode_fetch.c's work): kept."""
        self.fetched[mode_id] = version
        if self.installed is not None:
            self.installed.add(mode_id)
        self.fetching = [m for m in self.fetching if m != mode_id]

    def fetch_failed(self, now_ms: int = 0) -> None:
        """A fetch that did not end with every part: the box leaves the join and is free again
        (it said why in its report or in node.modes_failed); the game is not one it ended."""
        if self.phase != "joined" or self.game is None:
            return
        self.log.append(f"left game {self.game['game_id']}: its modes could not be fetched")
        self.phase, self.game, self.fetching = "idle", None, []
        self.next_announce = now_ms + self.rng.randint(*FIRST_ANNOUNCE_MS)
        self._drop_tokens(now_ms)

    def _drop_tokens(self, now_ms: int) -> None:
        self.token, self.prev_token = self._fresh(), None
        self.rotate_at = now_ms + TOKEN_ROTATE_MS

    # --- the radio -------------------------------------------------------------

    def _announce(self, answer: Optional[int] = None, result: Optional[str] = None) -> dict[str, Any]:
        msg: dict[str, Any] = {"kind": "announce", "device_id": self.device_id, "token": self.token,
                               "name": self.name, "tier": self.tier}
        if self.last_game:
            msg["last_game"] = self.last_game
        if self.last_role:
            msg["last_role"] = self.last_role
        if answer is not None:
            msg["answer"], msg["result"] = answer, result
        return msg

    def _interval(self) -> int:
        return announce_interval_ms(self.channel_hz, len(ff.encode(self.key, self._announce(), bytes(ff.NONCE_SIZE))))

    def on_frame(self, raw: bytes, now_ms: int) -> None:
        """A frame heard on the radio (anything: it is ignored unless it is ours to read)."""
        try:
            msg = ff.decode(self.key, raw)
        except (ff.FieldFrameError, ValueError):
            return  # another field's, a stranger's, or not a field frame at all
        if msg["kind"] == "game_over":
            self.on_game_over(msg, now_ms)
            return
        if msg["kind"] == "discover":
            gap = self._interval() // 4
            if self.available and (self.last_announce is None or now_ms - self.last_announce >= gap):
                self.queue.append((now_ms + self.rng.randint(*DISCOVER_ANSWER_MS), self._announce()))
            return
        if msg["kind"] != "invite" or msg["device_id"] != self.device_id:
            return
        if msg["token"] not in (self.token, self.prev_token):
            self.log.append(f"invite {msg['invite_id']} refused: an old token")
            return
        if not self.available:
            self._drop_tokens(now_ms)  # answered: this invite and every older one never work again
            self._answer(msg["invite_id"], "busy", now_ms)
            return
        try:
            payload = self.reasm.add(msg)
        except ff.FieldFrameError:
            return
        if payload is None:
            return
        result = self.join(payload, now_ms, invited=True)
        self._drop_tokens(now_ms)  # whatever the result: this invite never works again (RJ-8)
        self._answer(msg["invite_id"], result, now_ms)

    def _answer(self, invite_id: int, result: str, now_ms: int) -> None:
        last = self.answered.get(invite_id)
        if last is not None and now_ms - last < ANSWER_REPEAT_MS:
            return
        self.answer_times = [t for t in self.answer_times if now_ms - t < 60_000]
        if len(self.answer_times) >= ANSWERS_PER_MIN:
            self.log.append(f"invite {invite_id}: no answer (more than {ANSWERS_PER_MIN} a minute)")
            return
        self.answer_times.append(now_ms)
        self.answered[invite_id] = now_ms
        while len(self.answered) > ANSWER_IDS:
            del self.answered[min(self.answered, key=self.answered.get)]
        self.log.append(f"invite {invite_id}: {result}")
        self.queue.append((now_ms + self.rng.randint(*INVITE_ANSWER_MS), self._announce(invite_id, result)))

    def tick(self, now_ms: int) -> list[bytes]:
        """The frames the box sends now: answers, announcements."""
        out = []
        if now_ms >= self.rotate_at:
            self.token, self.prev_token = self._fresh(), self.token
            self.rotate_at = now_ms + TOKEN_ROTATE_MS
        due = [q for q in self.queue if q[0] <= now_ms]
        self.queue = [q for q in self.queue if q[0] > now_ms]
        for _, msg in due:
            if not msg.get("answer") and not self.available:
                continue
            out.append(ff.encode(self.key, {**msg, "token": self.token}, self.nonces.next()))
            self.last_announce = now_ms
        if self.available and self.next_announce is not None and now_ms >= self.next_announce:
            out.append(ff.encode(self.key, self._announce(), self.nonces.next()))
            self.last_announce = now_ms
            self.next_announce = now_ms + int(self._interval() * self.rng.uniform(0.9, 1.1))
        return out


# --- the controller's side -----------------------------------------------------------


@dataclass
class BoxSeen:
    """A free box as its last announcement told it."""

    device_id: bytes
    name: str
    tier: int
    token: bytes
    seen_ms: int
    last_game: Optional[int] = None
    last_role: Optional[str] = None
    battery_pct: Optional[int] = None
    rssi: Optional[int] = None
    snr: Optional[int] = None

    def public(self, now_ms: int) -> dict[str, Any]:
        return {"device_id": self.device_id.hex(), "name": self.name, "tier": self.tier,
                "last_game": self.last_game, "last_role": self.last_role, "battery_pct": self.battery_pct,
                "rssi": self.rssi, "snr": self.snr, "seen_s_ago": max(0, (now_ms - self.seen_ms) // 1000)}


@dataclass
class Invite:
    device_id: bytes
    invite_id: int
    game_id: int
    node_id: int
    role: str
    payload: bytes
    status: str = "sending"      # sending, invited, accepted, joined, refused, failed
    detail: Optional[str] = None
    attempts: int = 0
    next_ms: int = 0
    name: Optional[str] = None
    tx: set[int] = field(default_factory=set)
    pending: list[bytes] = field(default_factory=list)  # this attempt's parts not yet sent

    @property
    def parts(self) -> int:
        return len(ff.split(self.payload))

    @property
    def done(self) -> bool:
        return self.status in ("joined", "refused", "failed")

    def public(self) -> dict[str, Any]:
        return {"device_id": self.device_id.hex(), "game": self.game_id, "node_id": self.node_id,
                "role": self.role, "name": self.name, "status": self.status, "detail": self.detail,
                "attempts": self.attempts, "parts": self.parts, "bytes": len(self.payload)}


class InviteError(ValueError):
    pass


@dataclass
class GameOver:
    """A GAME_OVER on its way: the game id, its key's tag, the channel its boxes listen on."""

    game_id: int
    key_tag: bytes
    channel_hz: Optional[int] = None
    left: int = GAME_OVER_REPEATS
    next_ms: int = 0
    sent: int = 0


class Inviter:
    """A field controller's side: the free boxes heard, DISCOVER, invites with retries.

    ``send(frame)`` puts a frame on air and returns an id for its outcome
    (``on_tx_result``), or None if the radio refused it at once.
    """

    def __init__(self, join_key: bytes, send: Callable[[bytes], Optional[int]],
                 rng: Optional[random.Random] = None, nonces: Optional[ff.NonceSource] = None) -> None:
        self.key = ff.field_key(join_key)
        # The controller's nonces: its own sender id and a stored boot count (RJ-15); the
        # controller passes its store's (reinvite.py), a test a fresh one.
        self.nonces = nonces or ff.NonceSource(join_key, os.urandom(ff.SENDER_SIZE))
        self.send = send
        self.rng = rng or random.SystemRandom()
        self.boxes: dict[str, BoxSeen] = {}
        self.invites: dict[str, Invite] = {}
        self.busy_until = 0
        self.last_discover: Optional[int] = None
        self.ignored = 0  # frames that did not open: another field's, or strangers'
        self.stale = 0    # announcements older than one already heard from that box (replays)
        self._nkey = ff.nonce_key(join_key)
        self._fresh: dict[str, tuple[int, int]] = {}  # device id -> highest (boot, ctr) heard
        self.on_change: Optional[Callable[[str], None]] = None  # "boxes" or "invites"
        self.games_over: list[GameOver] = []
        # Called with a GAME_OVER's channel before it is sent (False: drop it, the radio is busy
        # elsewhere), and with None once none is left (the controller's radio goes back).
        self.tune: Optional[Callable[[Optional[int]], bool]] = None

    def _changed(self, what: str) -> None:
        if self.on_change is not None:
            self.on_change(what)

    # --- hearing ------------------------------------------------------------------

    def on_frame(self, raw: bytes, now_ms: int, rssi: Optional[int] = None,
                 snr: Optional[int] = None) -> Optional[dict[str, Any]]:
        try:
            msg = ff.decode(self.key, raw)
        except (ff.FieldFrameError, ValueError):
            self.ignored += 1
            return None
        if msg["kind"] != "announce":
            return msg  # another controller's DISCOVER or INVITE
        hexid = msg["device_id"].hex()
        # Fresh only: a box's nonces carry its pseudonym and a rising (boot, ctr) (decision RJ-15),
        # so an announcement played back, or not the box's own, is refused.
        nonce = raw[ff.HEADER_SIZE:ff.HEADER_SIZE + ff.NONCE_SIZE]
        seq = (int.from_bytes(nonce[8:11], "big"), int.from_bytes(nonce[11:13], "big"))
        if nonce[:8] != ff.nonce(self._nkey, msg["device_id"], 0, 0)[:8] or seq <= self._fresh.get(hexid, (0, -1)):
            self.stale += 1
            return None
        self._fresh[hexid] = seq
        self.boxes[hexid] = BoxSeen(msg["device_id"], msg["name"], msg["tier"], msg["token"], now_ms,
                                    msg.get("last_game"), msg.get("last_role"), msg.get("battery_pct"), rssi, snr)
        inv = self.invites.get(hexid)
        if inv is not None and msg.get("answer") == inv.invite_id and inv.status in ("sending", "invited"):
            if msg["result"] == "accepted":
                inv.status, inv.detail = "accepted", None
            else:
                inv.status, inv.detail = "refused", msg["result"]
            self._changed("invites")
        self._changed("boxes")
        return msg

    def on_hello(self, node_id: int, device_id: Optional[bytes] = None,
                 game_id: Optional[int] = None) -> Optional[Invite]:
        """A HELLO in the game (game_id: the live game's; only its invites match)."""
        for inv in self.invites.values():
            if game_id is not None and inv.game_id != game_id:
                continue
            if inv.node_id == node_id and (device_id is None or device_id == inv.device_id) \
                    and inv.status in ("sending", "invited", "accepted", "failed"):
                inv.status, inv.detail = "joined", None
                self.boxes.pop(inv.device_id.hex(), None)  # in a game now
                self._changed("invites")
                self._changed("boxes")
                return inv
        return None

    def on_tx_result(self, tx_id: int, status: str) -> None:
        for inv in self.invites.values():
            if tx_id in inv.tx:
                inv.tx.discard(tx_id)
                if status != "ok" and inv.status in ("sending", "invited"):
                    inv.detail = f"radio: {status}"
                    self._changed("invites")

    # --- sending ----------------------------------------------------------------------

    def available(self, now_ms: int) -> list[BoxSeen]:
        for hexid in [h for h, b in self.boxes.items() if now_ms - b.seen_ms > BOX_FORGET_MS]:
            del self.boxes[hexid]
        return sorted(self.boxes.values(), key=lambda b: (b.name, b.device_id))

    def discover(self, now_ms: int) -> bool:
        if self.last_discover is not None and now_ms - self.last_discover < DISCOVER_MIN_MS:
            return False
        frame = ff.encode(self.key, {"kind": "discover"}, self.nonces.next())
        self.last_discover = now_ms
        self.busy_until = max(self.busy_until, now_ms) + int(eu868.airtime_ms(len(frame))) + GAP_MS
        return self.send(frame) is not None

    def invite(self, device_id: bytes, payload: bytes, *, game_id: int, node_id: int, role: str,
               now_ms: int, name: Optional[str] = None) -> Invite:
        hexid = device_id.hex()
        if hexid not in self.boxes:
            raise InviteError(f"box {hexid} has not announced itself")
        if not 1 <= len(payload) <= ff.JOIN_MAX:
            raise InviteError(f"a join payload of {len(payload)} bytes does not fit in {ff.PARTS_MAX} parts")
        inv = Invite(device_id, self.rng.randrange(1, 0x10000), game_id, node_id, role, payload,
                     next_ms=now_ms, name=name)
        self.invites[hexid] = inv
        self._changed("invites")
        return inv

    def game_over(self, game_id: int, key_tag: bytes, now_ms: int,
                  channel_hz: Optional[int] = None) -> GameOver:
        """Says GAME_OVER_REPEATS times, GAME_OVER_GAP_MS apart, that game_id (its key's tag) is over."""
        ff.validate({"kind": "game_over", "game_id": game_id, "key_tag": key_tag})
        self.games_over = [g for g in self.games_over if g.game_id != game_id]
        go = GameOver(game_id, bytes(key_tag), channel_hz, next_ms=now_ms)
        self.games_over.append(go)
        return go

    def _tick_game_over(self, now_ms: int) -> bool:
        """Sends the next GAME_OVER that is due; True if the radio was used."""
        done = [g for g in self.games_over if g.left == 0 and now_ms >= g.next_ms]
        if done:
            self.games_over = [g for g in self.games_over if g not in done]
            if not self.games_over and self.tune is not None:
                self.tune(None)
        due = [g for g in self.games_over if g.left > 0 and now_ms >= g.next_ms]
        if not due or now_ms < self.busy_until:
            return False
        go = due[0]
        if self.tune is not None and not self.tune(go.channel_hz):
            self.games_over.remove(go)
            return False
        frame = ff.encode(self.key, {"kind": "game_over", "game_id": go.game_id, "key_tag": go.key_tag},
                          self.nonces.next())
        if self.send(frame) is not None:
            go.sent += 1
        go.left -= 1
        airtime = int(eu868.airtime_ms(len(frame)))
        self.busy_until = now_ms + airtime + GAP_MS
        go.next_ms = now_ms + airtime + (GAME_OVER_GAP_MS if go.left else GAP_MS)
        return True

    def forget_game(self, game_id: int) -> None:
        for hexid in [h for h, i in self.invites.items() if i.game_id == game_id]:
            del self.invites[hexid]
        self._changed("invites")

    def tick(self, now_ms: int) -> None:
        """Sends the next invite that is due (one at a time, paced by time on air)."""
        changed = False
        for inv in self.invites.values():
            if inv.status == "invited" and now_ms >= inv.next_ms and inv.attempts >= INVITE_ATTEMPTS:
                inv.status, inv.detail = "failed", inv.detail or "no answer"
                changed = True
        if changed:
            self._changed("invites")
        if self._tick_game_over(now_ms) or now_ms < self.busy_until:
            return
        due = [i for i in self.invites.values() if i.status in ("sending", "invited") and now_ms >= i.next_ms
               and i.attempts < INVITE_ATTEMPTS]
        if not due:
            return
        inv = min(due, key=lambda i: (i.next_ms, i.invite_id))
        box = self.boxes.get(inv.device_id.hex())
        token = box.token if box is not None else None
        if token is None:
            inv.status, inv.detail = "failed", "the box is no longer announcing itself"
            self._changed("invites")
            return
        if not inv.pending:  # a new attempt: all its parts, sent one per tick
            inv.pending = ff.invite_frames(self.key, self.nonces, inv.device_id, token, inv.invite_id,
                                           inv.payload)
            inv.detail = None
        frame = inv.pending.pop(0)
        tx = self.send(frame)
        if tx is not None:
            inv.tx.add(tx)
        else:
            inv.detail = "radio: not sent"
        airtime = int(eu868.airtime_ms(len(frame)))
        if inv.status != "invited":  # out with its first part
            inv.status = "invited"
            self._changed("invites")
        if inv.pending:  # the next part once this one is on air and the box listens again
            self.busy_until = now_ms + airtime + PART_GAP_MS
            inv.next_ms = self.busy_until
            return
        inv.attempts += 1
        self.busy_until = now_ms + airtime + GAP_MS
        inv.next_ms = now_ms + airtime + INVITE_RETRY_MS
        self._changed("invites")


def random_device_id() -> bytes:
    return os.urandom(ff.DEVICE_SIZE)
