# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The relay study: what the field's flood does to airtime, duty cycle and delivery.

Decisions SL-7 to SL-20 (docs/review/decisions-to-review.md). **"firmware" below is the Field Box as it
was before RFC 0001 Amendment 13** (every frame relayed after the same 10-50 ms, 4 relay slots, a 3 s
resend); the Amendment, decision SL-16, built the "A+backoff" rules into the core and the box, and the
``A_backoff_core`` policy runs this harness on that code (``relay_core.py``) beside ``A_backoff``, the
model of it. A packet-level, discrete-event
model of one field's shared radio channel: N boxes and a controller, the real firmware's
relay rules (firmware/esp32/main/radio/field_link.c, core/src/flood.c, radio_task.c,
hal_esp_radio.c) and the project's own airtime and duty-cycle formulas, with what the older
``RadioModel`` leaves out because it matters here: frames *occupy* the channel and collide,
a radio is half duplex, a box has a 4-slot relay table, an 8-deep transmit queue and a
64-entry dedupe table, and it drops (not delays) what the duty-cycle limit refuses.

What is modelled, and where each rule comes from:

* A box relays **every** authenticated frame of its game it has not seen in 30 s, of any
  type (STATE, EVENT, HELLO, and the controller's ACK, TIME and CMD), once, if the
  header's ``hop_limit`` (2 by default) is above 0; the copy goes out with ``hop_limit`` - 1
  after ``atalaia_flood_jitter_ms(source, seq)``, 10-50 ms, **the same value for every box
  that heard the frame** (core/src/flood.c). ``field_link.c``: ``schedule_relay``, 4 slots.
* The controller's modem never relays (RFC 0001 section 5, protocol/usb-modem.md); it
  ACKs every frame that asks for one, at once, one ACK per frame, and sends TIME every 30 s.
* A box's STATE is sent every 15 s (``FIELD_LINK_STATE_MS``), and at once after
  ``zone.captured``; an EVENT goes into an outbox and is sent again in a new packet every
  3 s until its ACK (normal priority: 10 retries, then dropped; critical: until ACKed).
* The radio task sends one queued frame at a time (queue of 8, FIFO); a frame whose time
  on air does not fit in the sub-band's remaining budget is **dropped** (``send`` returns
  -3; nothing is queued for later, whatever RFC 0001 section 8 says). Every transmission,
  own or relayed, is recorded in the transmitting box's budget (60 one-minute buckets,
  ``core/src/duty_cycle.c``). No listen-before-talk: a box transmits when its turn comes.

What is a model, not a measurement (the simulator has no radio): the link budget (a
log-distance path loss with walls and shadowing, ``Layout``), the capture rule (a frame
survives interference only if it is at least 6 dB stronger than every overlapping one), and
the game traffic (relay_traces.py, from the real core, with the capture rate a parameter).
The caveats are in the decisions; the numbers are for comparing rules, and for the order of
magnitude of the problem, not for a field's last percent.
"""

from __future__ import annotations

import argparse
import heapq
import json
import math
import random
import statistics
import sys
from bisect import bisect_right
from collections import deque
from dataclasses import dataclass, replace
from typing import Any, Callable, Optional

from . import regions
from .field_controller import STATE_REPEAT_GAPS_MS, AckTracker
from .packet import ack_encode, cmd_encode

# ---------------------------------------------------------------------------
# constants taken from the firmware (cited)
# ---------------------------------------------------------------------------

HEADER = 9  # RFC 0001 section 2
MIC = 8
STATE_MS = 15_000  # FIELD_LINK_STATE_MS (field_link.h)
ACK_RETRY_MS = 3_000  # the pre-Amendment-13 resend gap, and the first gap of the backoff (ATALAIA_RETRY_FIRST_MS)
MAX_RETRIES = 10  # FIELD_LINK_MAX_RETRIES: normal priority
RELAY_SLOTS = 4  # FIELD_LINK_RELAYS before Amendment 13 (8 now: ATALAIA_RELAY_SLOTS)
DEDUPE = 64  # FIELD_LINK_DEDUPE / ATALAIA_DEDUPE_SIZE
DEDUPE_MS = 30_000  # FIELD_LINK_DEDUPE_MS
TX_QUEUE = 8  # RADIO_TX_QUEUE_LEN
OUTBOX = 32  # FIELD_LINK_OUTBOX
TICK_MS = 10  # the shell loop (shell.c: delta_ms = 10); box_game_tick and field_link_tick run on it
RADIO_LOOP_MS = 10  # radio_task: vTaskDelay(10) between queue checks
JITTER_MIN_MS, JITTER_MAX_MS = 10, 50  # flood.h
TIME_MS = 30_000  # election.BEACON_INTERVAL_MS
ACK_DELAY_MS = (15, 50)  # modem -> USB -> engine -> modem: the controller's ACK leaves this long after the frame ends
CAD_US = 2_100  # two symbols (SF7/125 kHz and SF9/500 kHz both 1.024 ms): when CAD can see a preamble
CAPTURE_DB = 6.0  # LoRa co-channel rejection: the stronger frame survives from here
SENS_DBM = -105.0  # a frame is heard above this (the model's link budget, see Layout)
MAX_HOPS = 2  # the join's max_hops default (RFC 0001 section 5)
SETUP_ACK_BYTES = 23  # a node.setup_applied event's CBOR (protocol/vectors/events.yaml)
RESEND_S = (8, 16, 32, 64, 128)  # the scenario's waits between a setup and its repeats (core/scenario/runtime.lua, PKB-3)
CMD_MODES = ("oneshot", "resend", "resend_ack")  # a setup is sent once | again 5 times | again until the box says so
HELLO_BYTES = 80  # HELLO payload: RFC 0001 section 4, 60-150 bytes typical
GAME_T0_US = 30_000_000  # the boxes join over the first 30 s; the game starts then

CONTROLLER = 0  # index of the controller in a layout


def state_frame_bytes(teams: int) -> int:
    """STATE on air: 9 + CBOR (23 + 4 per team) + 8 = 48 / 52 / 56 bytes for 2 / 3 / 4 teams (SL-4)."""
    return HEADER + 23 + 4 * teams + MIC


# ---------------------------------------------------------------------------
# firmware rules, ported
# ---------------------------------------------------------------------------


def flood_jitter_ms(source: int, seq: int) -> int:
    """atalaia_flood_jitter_ms (core/src/flood.c): FNV-1a of (source, seq) in 10..50 ms."""
    h = 2166136261
    for byte in (source & 0xFF, source >> 8, seq & 0xFF, seq >> 8):
        h = ((h ^ (byte & 0xFF)) * 16777619) & 0xFFFFFFFF
    return JITTER_MIN_MS + h % (JITTER_MAX_MS - JITTER_MIN_MS + 1)


def should_relay(hop_limit: int, max_hops: int) -> Optional[int]:
    """atalaia_flood_should_relay: the copy's hop_limit, or None when the frame is not relayed."""
    if hop_limit == 0:
        return None
    hop_limit = min(hop_limit, max_hops)
    return hop_limit - 1


class CoreDutyCycle:
    """atalaia_duty_cycle_t (core/src/duty_cycle.c): 60 one-minute buckets, budget per hour."""

    BUCKETS = 60
    MINUTE_MS = 60_000

    def __init__(self, duty_ppm: int) -> None:
        self.budget_us = duty_ppm * 3600
        self.buckets = [0] * self.BUCKETS
        self.used_us = 0
        self.current = 0
        self.last_update_ms = 0
        self._init = False

    def tick(self, now_ms: int) -> None:
        if not self._init:
            self.last_update_ms = now_ms
            self._init = True
            return
        minutes = (now_ms - self.last_update_ms) // self.MINUTE_MS
        if minutes <= 0:
            return
        if minutes >= self.BUCKETS:
            self.buckets = [0] * self.BUCKETS
            self.used_us = 0
        else:
            for i in range(minutes):
                nxt = (self.current + 1 + i) % self.BUCKETS
                self.used_us -= self.buckets[nxt]
                self.buckets[nxt] = 0
        self.current = (self.current + minutes) % self.BUCKETS
        self.last_update_ms += minutes * self.MINUTE_MS

    def can_send(self, air_us: int, now_ms: int) -> bool:
        """The radio task's two checks (radio_task.c, esp_radio_send): budget left, and it fits."""
        self.tick(now_ms)
        return self.used_us < self.budget_us and self.used_us + air_us <= self.budget_us

    def record(self, air_us: int, now_ms: int) -> None:
        self.tick(now_ms)
        self.buckets[self.current] += air_us
        self.used_us += air_us


def duty_ppm(region: regions.Region) -> int:
    """The game channel's sub-band budget: EU868 g2 and AS923-TW are 10 %."""
    band = region.band_of(region.default_channel_hz)
    assert band is not None
    return int(round(band.budget_ms_per_hour * 1000 / 3600))  # ms per hour -> us per hour / 3600 = ppm


_AIR_CACHE: dict[tuple[str, int], int] = {}


def air_us(region: regions.Region, nbytes: int) -> int:
    key = (region.code, nbytes)
    if key not in _AIR_CACHE:
        _AIR_CACHE[key] = int(round(region.airtime_ms(nbytes) * 1000))
    return _AIR_CACHE[key]


# ---------------------------------------------------------------------------
# layouts: who hears whom, and how loudly
# ---------------------------------------------------------------------------


@dataclass
class Layout:
    """N boxes (index 1..N) and the controller (index 0), with the received level of every link.

    ``rssi[r][s]`` is the level in dBm at r of a frame sent by s; a frame is heard when it is
    at least SENS_DBM. Log-distance path loss, exponent 3, 30 dB at 1 m, a fixed loss per
    wall crossed, and a fixed per-link shadowing (sigma 3 dB, same both ways). Nothing here
    is measured; the *shape* (who reaches whom in how many hops) is what the study uses.
    """

    name: str
    n: int
    rssi: list[list[float]]
    description: str = ""

    def hears(self) -> list[list[int]]:
        """hears()[s]: the nodes that hear a frame sent by s (above SENS_DBM), the controller included."""
        size = self.n + 1
        return [[r for r in range(size) if r != s and self.rssi[r][s] >= SENS_DBM] for s in range(size)]

    def hop_distance(self) -> list[int]:
        """BFS hop count from the controller over audible links (-1: unreachable)."""
        hears = self.hears()
        dist = [-1] * (self.n + 1)
        dist[CONTROLLER] = 0
        frontier = [CONTROLLER]
        while frontier:
            nxt = []
            for u in frontier:
                for v in hears[u]:
                    if dist[v] < 0:
                        dist[v] = dist[u] + 1
                        nxt.append(v)
            frontier = nxt
        return dist

    def reach(self, max_hops: int = MAX_HOPS) -> dict[str, Any]:
        """How many boxes the controller hears directly, within the hop limit, and not at all."""
        d = self.hop_distance()[1:]
        within = sum(1 for x in d if 1 <= x <= max_hops + 1)
        hears = self.hears()
        mean = sum(sum(1 for r in hears[s] if r != CONTROLLER) for s in range(1, self.n + 1)) / max(1, self.n)
        return {"direct": sum(1 for x in d if x == 1), "within_hop_limit": within,
                "unreachable": self.n - within, "neighbours_mean": round(mean, 1)}

    def designated_relays(self, parents: int = 2) -> set[int]:
        """Controller-designated relays (an oracle: the controller knows the graph): for every
        box at hop distance L >= 2 its ``parents`` best-heard neighbours at L - 1 are relays, and
        so are *their* parents, up to the controller. The set that a field's controller could
        announce in one CMD."""
        dist = self.hop_distance()
        hears = self.hears()
        chosen: set[int] = set()

        def best_parents(v: int) -> list[int]:
            cands = [u for u in hears[v] if dist[u] == dist[v] - 1 and u != CONTROLLER]
            cands.sort(key=lambda u: -self.rssi[v][u])
            return cands[:parents]

        for v in range(1, self.n + 1):
            if dist[v] >= 2:
                chosen.update(best_parents(v))
        changed = True
        while changed:  # a relay's own frame must be heard back too: its parents relay as well
            changed = False
            for v in list(chosen):
                if dist[v] >= 2:
                    for u in best_parents(v):
                        if u not in chosen:
                            chosen.add(u)
                            changed = True
        return chosen


def _path_loss(d_m: float) -> float:
    return -30.0 - 30.0 * math.log10(max(d_m, 1.0))


def _links(pts: list[tuple[float, float]], rng: random.Random, sigma: float, wall_db: Optional[list[list[float]]] = None
           ) -> list[list[float]]:
    """rssi[r][s] from positions: path loss, optional wall loss, per-link shadowing (the same both ways)."""
    size = len(pts)
    rssi = [[0.0] * size for _ in range(size)]
    for a in range(size):
        for b in range(a + 1, size):
            level = _path_loss(math.dist(pts[a], pts[b])) + rng.gauss(0.0, sigma)
            if wall_db is not None:
                level -= wall_db[a][b]
            rssi[a][b] = rssi[b][a] = level
    return rssi


def layout_all_in_range(n: int, seed: int = 1) -> Layout:
    """Every box hears every other and the controller: a park, 50 m across, the worst case for relays."""
    rng = random.Random(seed)
    pts = [(0.0, 0.0)] + [(rng.uniform(-25, 25), rng.uniform(-25, 25)) for _ in range(n)]
    return Layout("all_in_range", n, _links(pts, rng, 3.0), "every box hears every other (a 50 m park)")


def layout_long(n: int, seed: int = 1, k: int = 0) -> Layout:
    """A long field: boxes along a line, the controller in the middle, each box hears the k
    nearest on either side. ``k`` 0 picks the smallest k >= 3 that lets the controller hear every
    box within the default hop limit (three hops of k boxes each way must cover N/2, so k grows
    past N/6): a field longer than that cannot be served by max_hops 2 at all (``Layout.reach``)."""
    d_max = 10 ** ((-30.0 - SENS_DBM) / 30.0)  # metres at which a frame falls below SENS_DBM
    for kk in ([k] if k else range(3, n + 3)):
        rng = random.Random(seed)
        spacing = d_max / (kk + 0.5)
        pts = [(0.0, 0.0)] + [((i - (n - 1) / 2.0) * spacing + spacing / 2.0, 0.0) for i in range(n)]
        lay = Layout("long", n, _links(pts, rng, 0.9),  # little shadowing, so "k neighbours" is crisp
                     f"a line, the controller in the middle, each box hears {kk} each side")
        if k or lay.reach()["unreachable"] == 0:
            return lay
    raise AssertionError("unreachable")


def layout_cqb(n: int, seed: int = 1) -> Layout:
    """CQB: a building of rooms 8 m wide on a grid, the controller in a central room, boxes
    spread over the rooms; every wall crossed (rooms apart, Manhattan) costs 18 dB."""
    rng = random.Random(seed)
    rooms = max(3, math.ceil(n / 2.5))
    cols = max(2, math.ceil(math.sqrt(rooms * 1.4)))
    rows = math.ceil(rooms / cols)
    cells = [(c, r) for r in range(rows) for c in range(cols)][:rooms]
    centre = min(cells, key=lambda cr: (cr[0] - (cols - 1) / 2) ** 2 + (cr[1] - (rows - 1) / 2) ** 2)
    boxes_room = [cells[i % len(cells)] for i in range(n)]
    rng.shuffle(boxes_room)
    room_of = [centre] + boxes_room
    pts = [(centre[0] * 8.0 + 4.0, centre[1] * 8.0 + 4.0)] + [
        (c * 8.0 + rng.uniform(1, 7), r * 8.0 + rng.uniform(1, 7)) for c, r in boxes_room]
    walls = [[18.0 * (abs(a[0] - b[0]) + abs(a[1] - b[1])) for b in room_of] for a in room_of]
    return Layout("cqb", n, _links(pts, rng, 3.0, walls),
                  f"{rooms} rooms of 8 m on a {cols}x{rows} grid, 18 dB per wall, controller central")


LAYOUTS: dict[str, Callable[[int, int], Layout]] = {
    "all_in_range": layout_all_in_range,
    "long": layout_long,
    "cqb": layout_cqb,
}


# ---------------------------------------------------------------------------
# relay policies: the rules under study. "firmware" is what runs today.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Policy:
    """A relay rule. The defaults are the firmware's today; every knob is a proposal."""

    name: str = "firmware"
    summary: str = "what runs today: every frame once, jitter 10-50 ms from (source, seq), 4 relay slots"
    state_period_ms: Optional[Callable[[int], int]] = None  # n_boxes -> ms; None: 15 s
    state_delta_every: int = 0  # >0: a STATE nothing changed in is skipped, but one in this many goes
    state_relay: str = "all"  # "all" | "none"
    jitter_mode: str = "fnv"  # "fnv": the firmware's | "uniform": a random draw in jitter_ms
    jitter_ms: tuple[int, int] = (10, 50)
    relay_slots: int = RELAY_SLOTS
    density_c: float = 0.0  # >0: STATE, ACK, TIME and CMD relay with probability min(1, c / neighbours)
    suppress_k: int = 0  # >0: cancel a pending relay once this many other copies were heard
    ack_cancel: bool = False  # EVENT and HELLO wait for the controller's ACK, and are not relayed if heard
    ack_wait_ms: tuple[int, int] = (350, 700)
    ack_relay_path: bool = False  # relay an ACK only for a box whose frame I relayed in the last 30 s
    designated: bool = False  # only the controller-designated boxes relay (an oracle, see Layout)
    retry_backoff: bool = False  # EVENT/HELLO retries at 3, 6, 12, 24 s, then every 30 s (x0.75-1.25), not every 3 s
    density_window_s: int = 600  # neighbours = distinct boxes heard in this long (a slow memory: loss must not shrink it)
    relay_off: bool = False  # no relaying at all (a reference)
    controller_pace_ms: int = 0  # >0: the controller leaves this long between its own frames (the relays of one are not on top of the next)
    ack_gap_horizon: int = 0  # >0: the controller skips an ACK hole once the box is this many seqs past it (SL-8)
    lbt: bool = False  # listen before talk: a frame waits (random backoff) while the channel is heard busy
    lbt_backoff_ms: tuple[int, int] = (20, 200)
    lbt_tries: int = 8  # then it goes anyway (the built rule: RFC 0001 Amendment 14; core atalaia_lbt_*)
    # The built transmit path (SL-30): 0 keeps the study's ideal CAD (instant, counted on every look).
    # >0 models the firmware: a frame the receiver already hears (a frame older than two symbols: the
    # preamble and header flags) is busy with no CAD; otherwise one CAD of this many ms, deaf meanwhile,
    # looked at in its middle, and a free answer sends at its end (a frame that starts in between is
    # collided with, the hidden window the ideal model does not have).
    lbt_cad_ms: float = 0.0
    lbt_core: bool = False  # the tries and the 20-200 ms wait are the core's atalaia_lbt_* (relay_core.CoreLbt)
    radio_loop_ms: int = 0  # >0: the radio task's loop grid (11 with LBT: recv waits 10 ms; 60 without: 50 + 10)
    # The controller's TIME repeats after a start, a pause or a resume (RFC 0001 Amendment 19 part 2, decision
    # RB-8): the built gaps; () is the controller as it was before. Used only when the Engine is given
    # ``state_changes`` (the study's older runs have no state change after the start and are unchanged).
    time_repeat_gaps_ms: tuple[int, ...] = STATE_REPEAT_GAPS_MS
    core_rules: bool = False  # every box runs the core's own relay rules (core/src/flood.c, ack.c; relay_core.py)
                              # instead of this file's model of them: RFC 0001 Amendment 13, the shipped code

    def period(self, n_boxes: int) -> int:
        return self.state_period_ms(n_boxes) if self.state_period_ms else STATE_MS


FIRMWARE = Policy()


def _adaptive_period(n: int) -> int:
    """15 s up to 10 boxes, then 1.5 s more per box: 15 / 15 / 22.5 / 33 s at 5 / 10 / 15 / 20,
    45 s at 30 (capped at 45 s: a score trails by at most that, RFC 0001's 10-60 s)."""
    return int(min(45_000, max(15_000, 1_500 * n)))


POLICIES: dict[str, Policy] = {
    "firmware": FIRMWARE,
    "no_state_relay": replace(FIRMWARE, name="no_state_relay", state_relay="none",
                              summary="STATE is not relayed (only EVENT, HELLO, ACK, TIME, CMD are)"),
    "period_30": replace(FIRMWARE, name="period_30", state_period_ms=lambda n: 30_000,
                         summary="STATE every 30 s, relays as today"),
    "period_adaptive": replace(FIRMWARE, name="period_adaptive", state_period_ms=_adaptive_period,
                               summary="STATE every max(15 s, 1.5 s x boxes), at most 45 s; relays as today"),
    "state_delta": replace(FIRMWARE, name="state_delta", state_delta_every=4,
                           summary="a STATE nothing changed in is not sent (one in 4 periods goes); relays as today"),
    "spread_jitter": replace(FIRMWARE, name="spread_jitter", jitter_mode="uniform", jitter_ms=(10, 400),
                             relay_slots=8,
                             summary="relays after a random 10-400 ms (not the same value for every box), 8 slots"),
    "counter": replace(FIRMWARE, name="counter", jitter_mode="uniform", jitter_ms=(20, 600), relay_slots=8,
                       suppress_k=1,
                       summary="counter-based: random 20-600 ms, cancelled once one other copy is heard; 8 slots"),
    "density": replace(FIRMWARE, name="density", jitter_mode="uniform", jitter_ms=(20, 600), relay_slots=8,
                       density_c=3.0, summary="STATE, ACK, TIME, CMD relay with probability min(1, 3 / neighbours); "
                                              "random 20-600 ms; 8 slots"),
    "ack_gated": replace(FIRMWARE, name="ack_gated", jitter_mode="uniform", jitter_ms=(20, 600), relay_slots=8,
                         ack_cancel=True, ack_relay_path=True,
                         summary="EVENT and HELLO relays wait for the controller's ACK and are cancelled by it; "
                                 "an ACK is relayed only by boxes that relayed that box's frame; random 20-600 ms"),
    "designated": replace(FIRMWARE, name="designated", jitter_mode="uniform", jitter_ms=(20, 300),
                          relay_slots=8, designated=True,
                          summary="only boxes the controller designated relay (oracle: it knows the graph)"),
    "no_relay": replace(FIRMWARE, name="no_relay", relay_off=True,
                        summary="nobody relays (the ALOHA floor: what a field with every box in range of the controller would see)"),
    "lbt": replace(FIRMWARE, name="lbt", lbt=True,
                   summary="the firmware's relays plus listen-before-talk (CAD, 20-200 ms backoff)"),
    # the candidates the decisions compare
    "A_relay": replace(FIRMWARE, name="A_relay", jitter_mode="uniform", jitter_ms=(20, 600),
                             relay_slots=8, density_c=3.0, ack_cancel=True, ack_relay_path=True,
                             summary="A: density-adaptive probabilistic relay + overheard-ACK cancel + path-gated ACK relay"),
    "B_counter": replace(FIRMWARE, name="B_counter", jitter_mode="uniform", jitter_ms=(20, 600),
                             relay_slots=8, suppress_k=1, ack_cancel=True, ack_relay_path=True,
                             summary="B: counter-based suppression + overheard-ACK cancel + path-gated ACK relay"),
    "C_period": replace(FIRMWARE, name="C_period", jitter_mode="uniform",
                                      jitter_ms=(20, 600), relay_slots=8, density_c=3.0, ack_cancel=True,
                                      ack_relay_path=True, state_period_ms=_adaptive_period,
                                      summary="C: A + the STATE period grows with the field (15 s to 45 s)"),
    "D_backoff": replace(FIRMWARE, name="D_backoff", jitter_mode="uniform", jitter_ms=(20, 600),
                                  relay_slots=8, density_c=3.0, ack_cancel=True, ack_relay_path=True,
                                  state_period_ms=_adaptive_period, retry_backoff=True,
                                  summary="D: C + EVENT/HELLO retries back off (3, 6, 12, 24, 30 s)"),
    "E_period_backoff": replace(FIRMWARE, name="E_period_backoff", state_period_ms=_adaptive_period,
                                retry_backoff=True,
                                summary="E: the relay rules untouched; STATE period grows with the field and EVENT/HELLO retries back off"),
    "H_paced": replace(FIRMWARE, name="H_paced", jitter_mode="uniform", jitter_ms=(20, 600), relay_slots=8,
                       density_c=3.0, ack_cancel=True, ack_relay_path=True, retry_backoff=True, controller_pace_ms=800,
                       summary="A_backoff + the controller leaves 0.8 s between its own frames"),
    "backoff": replace(FIRMWARE, name="backoff", retry_backoff=True,
                       summary="the firmware's relays; EVENT/HELLO retries back off (3, 6, 12, 24, 30 s)"),
    "A_backoff": replace(FIRMWARE, name="A_backoff", jitter_mode="uniform", jitter_ms=(20, 600),
                         relay_slots=8, density_c=3.0, ack_cancel=True, ack_relay_path=True, retry_backoff=True,
                         summary="A + EVENT/HELLO retries back off; STATE stays at 15 s (keeps SL-5)"),
    # A+backoff as built (RFC 0001 Amendment 13): the same rules, run by the core's own code
    "A_backoff_core": replace(FIRMWARE, name="A_backoff_core", jitter_mode="uniform", jitter_ms=(20, 600),
                              relay_slots=8, density_c=3.0, ack_cancel=True, ack_relay_path=True,
                              retry_backoff=True, core_rules=True,
                              summary="A+backoff run by the core's atalaia_relay_* and atalaia_retry_gap_ms "
                                      "(what the box ships), not by this file's model"),
    # SL-25: listen-before-talk on the rules that are built (the CAD wraps the TX decision in the harness)
    "A_backoff_lbt": replace(FIRMWARE, name="A_backoff_lbt", jitter_mode="uniform", jitter_ms=(20, 600),
                             relay_slots=8, density_c=3.0, ack_cancel=True, ack_relay_path=True,
                             retry_backoff=True, lbt=True,
                             summary="A_backoff plus listen-before-talk (CAD, 20-200 ms backoff, at most 8 times)"),
    "A_backoff_core_lbt": replace(FIRMWARE, name="A_backoff_core_lbt", jitter_mode="uniform", jitter_ms=(20, 600),
                                  relay_slots=8, density_c=3.0, ack_cancel=True, ack_relay_path=True,
                                  retry_backoff=True, core_rules=True, lbt=True,
                                  summary="A_backoff_core (the core's rules) plus a simulator-side CAD before TX"),
    # SL-30: the built transmit path, on the hardware's own timing (an 8 ms CAD, a receiver-flag check that
    # costs none, the radio task's real loop: 11 ms with LBT, up to 60 ms without it)
    "A_backoff_core_hw": replace(FIRMWARE, name="A_backoff_core_hw", jitter_mode="uniform", jitter_ms=(20, 600),
                                 relay_slots=8, density_c=3.0, ack_cancel=True, ack_relay_path=True,
                                 retry_backoff=True, core_rules=True, radio_loop_ms=60,
                                 summary="A_backoff_core with the radio task's real 60 ms loop (no LBT)"),
    "A_backoff_core_lbt_hw": replace(FIRMWARE, name="A_backoff_core_lbt_hw", jitter_mode="uniform",
                                     jitter_ms=(20, 600), relay_slots=8, density_c=3.0, ack_cancel=True,
                                     ack_relay_path=True, retry_backoff=True, core_rules=True, lbt=True,
                                     lbt_cad_ms=8.0, lbt_core=True, radio_loop_ms=11,
                                     summary="A_backoff_core plus the built LBT: 8 ms CAD, flags first, 11 ms loop"),
    "D_lbt": replace(FIRMWARE, name="D_lbt", jitter_mode="uniform", jitter_ms=(20, 600), relay_slots=8,
                     density_c=3.0, ack_cancel=True, ack_relay_path=True, state_period_ms=_adaptive_period,
                     retry_backoff=True, lbt=True, summary="D plus listen-before-talk"),
}

# Every rule but "firmware" includes the ACK-gap fix (SL-8), a controller-side bug fix that is neither a
# relay rule nor a wire change, so that what a rule does shows by itself; "G_ackfix" is the fix alone.
POLICIES["G_ackfix"] = replace(FIRMWARE, name="G_ackfix", summary="G: the firmware as it is, plus the controller's ACK-gap fix (SL-8)")
for _name, _pol in list(POLICIES.items()):
    if _name != "firmware":
        POLICIES[_name] = replace(_pol, ack_gap_horizon=128)


# ---------------------------------------------------------------------------
# the channel and the nodes
# ---------------------------------------------------------------------------


class Frame:
    """A packet on air. ``hop`` is the header's hop_limit; copies share everything else."""

    __slots__ = ("src", "seq", "ptype", "nbytes", "ack_req", "hop", "ref", "t0")

    def __init__(self, src: int, seq: int, ptype: str, nbytes: int, ack_req: bool, hop: int,
                 ref: Any, t0: int) -> None:
        self.src, self.seq, self.ptype, self.nbytes = src, seq, ptype, nbytes
        self.ack_req, self.hop, self.ref, self.t0 = ack_req, hop, ref, t0

    def copy_with_hop(self, hop: int) -> "Frame":
        return Frame(self.src, self.seq, self.ptype, self.nbytes, self.ack_req, hop, self.ref, self.t0)


@dataclass
class Tx:
    sender: int
    frame: Frame
    start: int
    end: int


class Stats:
    """Per-node counters."""

    def __init__(self) -> None:
        self.air_us: dict[str, int] = {}
        self.air_ptype: dict[str, int] = {}  # on air by frame type (own and relayed), for the load tables
        self.dc_dropped: dict[str, int] = {}
        self.queue_dropped: dict[str, int] = {}
        self.relay_slot_dropped = 0
        self.relay_cancelled = 0
        self.relay_skipped = 0  # the policy decided not to relay at all
        self.lbt_deferred = 0
        self.lbt_gave_up = 0  # frames sent after the last allowed wait (the firmware's lbt_gave_up counter)
        self.lbt_cads = 0  # channel-activity detections made before a transmission (the energy cost, SL-25)
        self.relayed = 0
        self.rx_ok = 0
        self.rx_dup = 0
        self.rx_collided = 0
        self.rx_halfduplex = 0
        self.dedupe_evictions = 0
        self.dup_after_evict = 0
        self.peak_used_us = 0
        self.air_by_minute: list[int] = []

    def add(self, d: dict[str, int], k: str, v: int = 1) -> None:
        d[k] = d.get(k, 0) + v


class Node:
    """The radio task and the field link of one box (or of the controller's modem)."""

    def __init__(self, eng: "Engine", idx: int) -> None:
        self.eng, self.idx = eng, idx
        self.stats = Stats()
        self.dc = CoreDutyCycle(duty_ppm(eng.region))
        self.txq: deque[tuple[Frame, str]] = deque()
        self.tx_busy = False
        self.pop_scheduled = False
        self.lbt_waits = 0
        self.next_ok_us = 0  # the controller's pacing: no frame of its own before this
        self.tick_phase = eng.rng.randrange(TICK_MS * 1000)
        self.loop_ms = eng.policy.radio_loop_ms or RADIO_LOOP_MS
        self.radio_phase = eng.rng.randrange(self.loop_ms * 1000)
        self.cad_win = (0, 0)  # the last CAD's [start, end) in us: deaf to a frame that begins in it
        self.core_lbt = None
        if eng.policy.lbt_core:
            from .relay_core import CoreLbt
            self.core_lbt = CoreLbt(eng.rng, eng.lib)
        # a crystal's error: periodic timers (STATE, retries, TIME) run this much fast or slow
        self.drift = 1.0 + eng.rng.gauss(0.0, eng.drift_ppm * 1e-6)
        self.seq = 0
        # dedupe: a FIFO of (key, t_ms); a key is live for 30 s from first sight (field_link.c seen_before)
        self.seen: deque[tuple[tuple[int, int], int]] = deque()
        self.seen_set: dict[tuple[int, int], int] = {}
        self.evicted: set[tuple[int, int]] = set()
        # relay slots: key -> [frame, due_us, copies_heard, ack_wait]
        self.pending: dict[tuple[int, int], list[Any]] = {}

    # --- time helpers: a box acts on its own loop grid ---
    def tick_at(self, t_us: int) -> int:
        g = TICK_MS * 1000
        return ((t_us - self.tick_phase + g - 1) // g) * g + self.tick_phase

    def radio_at(self, t_us: int) -> int:
        g = self.loop_ms * 1000
        return ((t_us - self.radio_phase + g - 1) // g) * g + self.radio_phase

    # --- transmit path: the radio task ---
    def next_seq(self) -> int:
        s = self.seq
        self.seq = (self.seq + 1) & 0xFFFF
        return s

    def enqueue(self, frame: Frame, kind: str, t_us: int) -> bool:
        if len(self.txq) >= TX_QUEUE:
            self.stats.add(self.stats.queue_dropped, kind)
            return False
        self.txq.append((frame, kind))
        self.kick(t_us)
        return True

    def _cad(self, t_us: int) -> bool:
        self.stats.lbt_cads += 1
        return self.eng.chan.busy_for(self.idx, t_us)

    def kick(self, t_us: int) -> None:
        if self.tx_busy or self.pop_scheduled or not self.txq:
            return
        self.pop_scheduled = True
        self.eng.at(self.radio_at(t_us), self.pop)

    def pop(self, t_us: int) -> None:
        self.pop_scheduled = False
        if self.tx_busy or not self.txq:
            return
        pol = self.eng.policy
        if t_us < self.next_ok_us:
            self.pop_scheduled = True
            self.eng.at(self.radio_at(self.next_ok_us), self.pop)
            return
        # The CAD is a simulator-side wrapper around the TX decision: the core has no CAD (SL-25), so with
        # lbt the harness asks the channel before handing the frame to the radio, for either rule set.
        if pol.lbt and self.core_lbt is not None and not self.core_lbt.should_listen():
            self.core_lbt.decide(True)  # eight waits spent: SEND_ANYWAY, with no look at the channel
            self.stats.lbt_gave_up += 1
        elif pol.lbt and (self.core_lbt is not None or self.lbt_waits < pol.lbt_tries):
            if pol.lbt_cad_ms <= 0:
                if self._cad(t_us):
                    self._defer(t_us)
                    return
            elif self.eng.chan.busy_for(self.idx, t_us):
                self._defer(t_us)  # the receiver's flags say a frame is on air: busy, no CAD
                return
            else:
                # one CAD: deaf for its length, looked at in the middle, the answer at its end
                self.stats.lbt_cads += 1
                cad_us = int(pol.lbt_cad_ms * 1000)
                self.cad_win = (t_us, t_us + cad_us)
                self.pop_scheduled = True
                self.eng.at(t_us + cad_us, lambda t, t0=t_us, c=cad_us: self._after_cad(t, t0 + c // 2))
                return
        self._send_head(t_us)

    def _defer(self, t_us: int) -> None:
        pol = self.eng.policy
        if self.core_lbt is not None:
            _verdict, wait_ms = self.core_lbt.decide(True)  # WAIT: the core's draw in 20-200 ms
        else:
            self.lbt_waits += 1
            wait_ms = self.eng.rng.randint(*pol.lbt_backoff_ms)
        self.stats.lbt_deferred += 1
        self.pop_scheduled = True
        self.eng.at(self.radio_at(t_us + wait_ms * 1000), self.pop)

    def _after_cad(self, t_us: int, looked_us: int) -> None:
        """The CAD's answer: busy if a frame it could hear had been on air two symbols when it looked."""
        self.pop_scheduled = False
        if self.tx_busy or not self.txq:
            return
        if self.eng.chan.busy_for(self.idx, looked_us):
            self._defer(t_us)
            return
        if self.core_lbt is not None:
            self.core_lbt.decide(False)  # SEND: the count starts again
        self._send_head(t_us)

    def _send_head(self, t_us: int) -> None:
        self.lbt_waits = 0
        frame, kind = self.txq.popleft()
        a = air_us(self.eng.region, frame.nbytes)
        now_ms = t_us // 1000
        if not self.dc.can_send(a, now_ms):
            self.stats.add(self.stats.dc_dropped, kind)
            self.eng.on_dc_drop(self.idx, frame, kind)
            self.kick(t_us)
            return
        self.tx_busy = True
        tx = Tx(self.idx, frame, t_us, t_us + a)
        self.eng.chan.begin(tx)
        self.eng.at(tx.end, lambda t, tx=tx, kind=kind: self.done(t, tx, kind))

    def done(self, t_us: int, tx: Tx, kind: str) -> None:
        a = tx.end - tx.start
        self.dc.record(a, t_us // 1000)
        self.stats.add(self.stats.air_us, kind, a)
        self.stats.add(self.stats.air_ptype, tx.frame.ptype, a)
        self.stats.peak_used_us = max(self.stats.peak_used_us, self.dc.used_us)
        minute = t_us // 60_000_000
        ab = self.stats.air_by_minute
        while len(ab) <= minute:
            ab.append(0)
        ab[minute] += a
        self.tx_busy = False
        if self.idx == CONTROLLER:
            self.next_ok_us = t_us + self.eng.policy.controller_pace_ms * 1000
        self.eng.chan.finish(tx)
        self.kick(t_us)

    # --- receive path: field_link_on_packet ---
    def seen_before(self, key: tuple[int, int], t_ms: int) -> bool:
        """field_link.c seen_before: a key is live for 30 s from the first time it was seen; a full
        table of live keys evicts the oldest (so a frame heard again after that is processed again)."""
        while self.seen and t_ms - self.seen[0][1] >= DEDUPE_MS:
            self.seen_set.pop(self.seen.popleft()[0], None)
        if key in self.seen_set:
            return True
        if len(self.seen) >= DEDUPE:
            old = self.seen.popleft()[0]
            self.seen_set.pop(old, None)
            self.stats.dedupe_evictions += 1
            self.evicted.add(old)
        self.seen.append((key, t_ms))
        self.seen_set[key] = t_ms
        if key in self.evicted:
            self.evicted.discard(key)
            self.stats.dup_after_evict += 1
        return False


class Channel:
    """One shared channel: frames occupy it for their time on air; a receiver loses a frame to
    an overlapping one unless it is CAPTURE_DB stronger, and to its own transmitting."""

    def __init__(self, eng: "Engine", layout: Layout, ideal: bool, loss: float, capture_db: float) -> None:
        self.eng = eng
        self.capture_db = capture_db
        self.R = layout.rssi
        self.hears = layout.hears()
        self.ideal = ideal
        self.loss = loss
        self.active: list[Tx] = []
        self.recent: list[Tx] = []
        self.tx_count = 0

    def busy_for(self, idx: int, t_us: int) -> bool:
        """Channel activity detection at idx: a LoRa frame it can hear has been on air for two symbols."""
        for o in self.active:
            if o.sender != idx and o.start <= t_us - CAD_US and self.R[idx][o.sender] >= SENS_DBM:
                return True
        return False

    def begin(self, tx: Tx) -> None:
        self.active.append(tx)
        self.tx_count += 1

    def finish(self, tx: Tx) -> None:
        self.active.remove(tx)
        horizon = tx.end - 2_000_000
        self.recent = [o for o in self.recent if o.end > horizon]
        s = tx.sender
        others = [] if self.ideal else self.active + [o for o in self.recent if o.end > tx.start]
        senders = {o.sender for o in others}
        floor = SENS_DBM - 3.0
        R, cap, nodes = self.R, self.capture_db, self.eng.nodes
        for r in self.hears[s]:
            cw = nodes[r].cad_win
            if cw[0] <= tx.start < cw[1]:  # the receiver was in its CAD when this frame began
                nodes[r].stats.rx_halfduplex += 1
                continue
            if others:
                if r in senders:
                    nodes[r].stats.rx_halfduplex += 1
                    continue
                row = R[r]
                strongest = max((row[o.sender] for o in others if row[o.sender] >= floor), default=-1e9)
                if row[s] - strongest < cap:
                    nodes[r].stats.rx_collided += 1
                    continue
            if self.loss and self.eng.rng.random() < self.loss:
                continue
            self.eng.deliver(r, tx.frame, tx.end)
        self.recent.append(tx)


@dataclass
class OutboxEntry:
    ev: Any  # EventRec
    ptype: str
    prio: str
    plen: int
    tries: int = 0
    next_us: int = 0
    pkt_seq: int = -1
    sent: bool = False


@dataclass
class EventRec:
    eid: int
    box: int
    type: str
    prio: str
    t_us: int
    delivered_us: Optional[int] = None
    acked_us: Optional[int] = None
    expired: bool = False
    tx_count: int = 0


class Box(Node):
    def __init__(self, eng: "Engine", idx: int) -> None:
        super().__init__(eng, idx)
        self.outbox: list[OutboxEntry] = []
        self.backlog: list[OutboxEntry] = []
        self.last_state_us = 0
        self.state_due = False
        self.state_skipped = 0
        self.heard: dict[int, int] = {}  # neighbour -> last heard (ms)
        self._n_cache = (0, 0)
        self.path: dict[int, int] = {}  # source -> ms of the last frame of it I relayed
        self.states_sent = 0
        self.is_relay = True
        self.last_time_us = 0
        self.max_time_gap_us = 0
        self.acks_for_me = 0  # the controller's ACKs addressed to this box that it heard (first copies)
        self.core = None
        self.core_frames: dict[int, Frame] = {}  # core relay slot -> the frame it holds
        if eng.policy.core_rules:
            from .relay_core import CoreRelay
            self.core = CoreRelay(eng.rng, eng.lib)

    # -- own frames --
    def state_frame(self, t_us: int) -> Frame:
        return Frame(self.idx, self.next_seq(), "STATE", state_frame_bytes(self.eng.trace.teams), False,
                     MAX_HOPS, ("state", self.idx, self.states_sent), t_us)

    def send_state(self, t_us: int) -> None:
        eng = self.eng
        pol = eng.policy
        self.state_due = False
        if pol.state_delta_every:
            changed = eng.trace.changed(self.idx - 1, (self.last_state_us - GAME_T0_US) / 1000,
                                        (t_us - GAME_T0_US) / 1000)
            self.state_skipped += 1
            if not changed and self.state_skipped < pol.state_delta_every:
                self.last_state_us = t_us
                return
        self.state_skipped = 0
        f = self.state_frame(t_us)
        self.states_sent += 1
        eng.state_log.append((self.idx, f.seq, t_us))
        self.last_state_us = t_us
        self.enqueue(f, "own_state", t_us)

    def transmit(self, p: OutboxEntry, t_us: int) -> None:
        seq = self.seq
        f = Frame(self.idx, self.next_seq(), p.ptype, HEADER + p.plen + MIC, True, MAX_HOPS,
                  ("event", p.ev), t_us)
        p.pkt_seq, p.sent = seq, True
        if p.tries > 0:
            kind = "own_retry"
        else:
            kind = "own_hello" if p.ptype == "HELLO" else "own_event"
        p.tries += 1
        p.ev.tx_count += 1
        gap_ms = ACK_RETRY_MS
        if self.core is not None:
            gap_ms = self.core.retry_gap_ms(p.tries)
        elif self.eng.policy.retry_backoff:
            gap_ms = min(30_000, ACK_RETRY_MS * 2 ** min(p.tries - 1, 4)) * self.eng.rng.uniform(0.75, 1.25)
        p.next_us = t_us + int(gap_ms * 1000 * self.drift)
        self.eng.at(self.tick_at(p.next_us), lambda t, p=p: self.retry(t, p))
        self.enqueue(f, kind, t_us)

    def retry(self, t_us: int, p: OutboxEntry) -> None:
        if p not in self.outbox or t_us < p.next_us:
            return
        if p.tries > 0 and p.prio != "critical" and p.tries > MAX_RETRIES:
            self.outbox.remove(p)
            p.ev.expired = True
            self.refill(t_us)
            return
        self.transmit(p, t_us)

    def refill(self, t_us: int) -> None:
        while self.backlog and len(self.outbox) < OUTBOX:
            p = self.backlog.pop(0)
            self.outbox.append(p)
            self.transmit(p, t_us)

    def new_event(self, ev: EventRec, plen: int, ptype: str, t_us: int) -> None:
        p = OutboxEntry(ev, ptype, ev.prio, plen)
        if ev.prio == "telemetry":
            self.enqueue(Frame(self.idx, self.next_seq(), ptype, HEADER + plen + MIC, False, MAX_HOPS,
                               ("event", ev), t_us), "own_event", t_us)
            return
        if len(self.outbox) >= OUTBOX:
            self.backlog.append(p)
        else:
            self.outbox.append(p)
            self.transmit(p, t_us)
        if ev.type in ("zone.captured", "zone.neutralized"):
            self.state_due = True  # field_link_event: a capture changes what STATE says
            self.eng.at(self.tick_at(t_us), self.state_due_tick)

    def state_due_tick(self, t_us: int) -> None:
        if self.state_due:
            self.send_state(t_us)

    def state_tick(self, t_us: int) -> None:
        """The periodic chain: one per box, re-armed from the last STATE (sent or skipped)."""
        interval = int(self.eng.state_interval * 1000 * self.drift)
        if t_us - self.last_state_us >= interval:
            self.send_state(t_us)
        self.eng.at(self.tick_at(max(self.last_state_us + interval, t_us + 1)), self.state_tick)

    # -- receiving --
    def on_rx(self, f: Frame, t_us: int) -> None:
        if f.src == self.idx:
            return
        t_ms = t_us // 1000
        key = (f.src, f.seq)
        if self.seen_before(key, t_ms):
            self.stats.rx_dup += 1
            ent = self.pending.get(key)
            if ent is not None:
                ent[2] += 1
                k = self.eng.policy.suppress_k
                if k and ent[2] >= k:
                    del self.pending[key]
                    self.stats.relay_cancelled += 1
            return
        self.stats.rx_ok += 1
        if f.src != CONTROLLER:
            self.heard[f.src] = t_ms
            if self.core is not None:
                self.core.heard(f.src, t_ms)
        if f.ptype == "ACK":
            self.on_ack(f, t_us)
        elif f.ptype == "CMD":
            self.eng.on_cmd_rx(self.idx, f, t_us)
        elif f.ptype == "TIME":
            self.max_time_gap_us = max(self.max_time_gap_us, t_us - (self.last_time_us or GAME_T0_US))
            self.last_time_us = t_us
        self.schedule_relay(f, t_us)

    def neighbours(self, t_ms: int) -> int:
        if t_ms - self._n_cache[0] > 2000 or self._n_cache[0] == 0:
            n = sum(1 for t in self.heard.values() if t_ms - t <= self.eng.policy.density_window_s * 1000)
            self._n_cache = (t_ms, max(n, 1))
        return self._n_cache[1]

    def schedule_relay_core(self, f: Frame, t_us: int) -> None:
        """field_link.c schedule_relay: the core's rules decide; this only holds the frame by slot."""
        new_hop = should_relay(f.hop, MAX_HOPS)
        if new_hop is None:
            return
        from . import relay_core
        kind = relay_core.ACK if f.ptype == "ACK" else relay_core.ASKS_ACK if f.ack_req else relay_core.OTHER
        t_ms = t_us // 1000
        slot = self.core.plan(kind, f.src, f.seq, f.ref[1] if f.ptype == "ACK" else 0, t_ms)
        if slot == relay_core.SKIP:
            self.stats.relay_skipped += 1
            return
        if slot == relay_core.NO_SLOT:
            self.stats.relay_slot_dropped += 1
            return
        self.core_frames[slot] = f.copy_with_hop(new_hop)
        due = self.tick_at(self.core.due_ms(slot) * 1000)
        self.eng.at(due, self.relay_due_core)

    def relay_due_core(self, t_us: int) -> None:
        """field_link_tick: every slot whose delay has passed goes out (an ACK-waiting frame joins the path)."""
        while True:
            slot = self.core.take_due(t_us // 1000)
            if slot < 0:
                return
            frame = self.core_frames.pop(slot)
            if self.enqueue(frame, "relay", t_us):
                self.stats.relayed += 1

    def schedule_relay(self, f: Frame, t_us: int) -> None:
        pol = self.eng.policy
        if self.core is not None:
            return self.schedule_relay_core(f, t_us)
        new_hop = should_relay(f.hop, MAX_HOPS)
        if new_hop is None:
            return
        st = self.stats
        t_ms = t_us // 1000
        if pol.relay_off:
            st.relay_skipped += 1
            return
        if pol.designated and not self.is_relay:
            st.relay_skipped += 1
            return
        if f.ptype == "STATE" and pol.state_relay == "none":
            st.relay_skipped += 1
            return
        if f.ptype == "ACK" and pol.ack_relay_path:
            who = f.ref[1]
            if t_ms - self.path.get(who, -10**9) > 30_000:
                st.relay_skipped += 1
                return
        if pol.density_c and not f.ack_req:
            p = min(1.0, pol.density_c / self.neighbours(t_ms))
            if p < 1.0 and self.eng.rng.random() > p:
                st.relay_skipped += 1
                return
        wait_ack = pol.ack_cancel and f.ack_req
        if wait_ack:
            delay_us = self.eng.rng.randint(*pol.ack_wait_ms) * 1000
        elif pol.jitter_mode == "fnv":
            delay_us = flood_jitter_ms(f.src, f.seq) * 1000
        else:
            delay_us = self.eng.rng.randint(*pol.jitter_ms) * 1000
        if len(self.pending) >= pol.relay_slots:
            st.relay_slot_dropped += 1
            return
        key = (f.src, f.seq)
        due = self.tick_at(t_us + delay_us)
        self.pending[key] = [f.copy_with_hop(new_hop), due, 0, wait_ack]
        self.eng.at(due, lambda t, key=key: self.relay_due(t, key))

    def relay_due(self, t_us: int, key: tuple[int, int]) -> None:
        ent = self.pending.pop(key, None)
        if ent is None:
            return
        frame = ent[0]
        if ent[3]:
            self.path[frame.src] = t_us // 1000
        if self.enqueue(frame, "relay", t_us):
            self.stats.relayed += 1

    def on_ack(self, f: Frame, t_us: int) -> None:
        who, contig, above = f.ref[1], f.ref[2], f.ref[3]
        if who == self.idx:
            self.acks_for_me += 1
        pol = self.eng.policy
        if self.core is not None:
            self.stats.relay_cancelled += self.core.ack_heard(who, contig, above)
        elif pol.ack_cancel:
            for key, ent in list(self.pending.items()):
                fr = ent[0]
                if ent[3] and fr.src == who and _covers(contig, above, fr.seq):
                    del self.pending[key]
                    self.stats.relay_cancelled += 1
        if who != self.idx:
            return
        for p in list(self.outbox):
            if p.sent and _covers(contig, above, p.pkt_seq):
                self.outbox.remove(p)
                if p.ev.acked_us is None:
                    p.ev.acked_us = t_us
        self.refill(t_us)


def _covers(contig: int, above: set[int], seq: int) -> bool:
    return seq <= contig or seq in above


class GapSkippingAckTracker(AckTracker):
    """AckTracker that gives up on a hole once the box is ``horizon`` packets past it.

    The shipped tracker (field_controller.AckTracker) reports the highest contiguous seq and a
    256-bit bitmap above it. A packet that never arrives (a STATE lost on air: nothing resends
    it, and an EVENT's resend takes a new seq) leaves a hole *forever*, so 256 packets later
    the box's newest seq is out of the bitmap's reach and none of its EVENTs is ever ACKed
    again until it reboots (decision SL-8). Here the hole is skipped (treated as received)
    once the newest seq is more than ``horizon`` (128: half the bitmap) above it.
    """

    def __init__(self, horizon: int = 128) -> None:
        super().__init__()
        self.horizon = horizon

    def record(self, node: int, epoch: int, seq: int) -> None:
        super().record(node, epoch, seq)
        key = (node, epoch)
        contig = self._contig.get(key, -1)
        above = self._above.get(key)
        if not above:
            return
        newest = max(above)
        if newest - contig > self.horizon:
            contig = newest - self.horizon
            for q in [q for q in above if q <= contig]:
                above.discard(q)
            while contig + 1 in above:
                contig += 1
                above.discard(contig)
            self._contig[key] = contig


@dataclass
class Setup:
    """One setup command of the scenario (a trace command for one box) and what became of it."""
    dest: int
    t_us: int
    params_len: int
    frames: int = 0  # CMD frames the controller sent for it (the first and the repeats)
    reached_us: Optional[int] = None  # the first time its box heard one of them
    acked_us: Optional[int] = None  # when the controller heard the box say node.setup_applied
    confirmations: int = 0  # node.setup_applied events the box sent for it


class Controller(Node):
    def __init__(self, eng: "Engine") -> None:
        super().__init__(eng, CONTROLLER)
        h = eng.policy.ack_gap_horizon
        self.acks = GapSkippingAckTracker(h) if h else AckTracker()
        self.heard: set[tuple[int, int]] = set()
        self.ack_sent = 0
        self.time_gen = 0  # a state change starts a new TIME beacon chain (its last repeat resets the 30 s period)
        self.state_changes_sent = 0
        self.time_repeats_sent = 0

    def on_rx(self, f: Frame, t_us: int) -> None:
        key = (f.src, f.seq)
        if key in self.heard:
            self.stats.rx_dup += 1
            return
        self.heard.add(key)
        self.stats.rx_ok += 1
        eng = self.eng
        self.acks.record(f.src, 0, f.seq)
        eng.on_controller_rx(f, t_us)
        if f.ack_req:
            delay = eng.rng.randint(*ACK_DELAY_MS) * 1000
            eng.at(t_us + delay, lambda t, src=f.src: self.send_ack(src, t))

    def send_ack(self, node: int, t_us: int) -> None:
        payload = self.acks.ack_payload(node, 0)
        contig = payload["ack_seq"]
        contig = -1 if contig == 0xFFFF else contig
        bits = payload.get("ack_bitmap", b"")
        above = {contig + 1 + n for n in range(len(bits) * 8) if (bits[n // 8] >> (n % 8)) & 1}
        n = len(ack_encode(payload))
        f = Frame(CONTROLLER, self.next_seq(), "ACK", HEADER + n + MIC, False, MAX_HOPS,
                  ("ack", node, contig, above), t_us)
        self.ack_sent += 1
        self.enqueue(f, "ack", t_us)

    def send_time(self, t_us: int, gen: Optional[int] = None) -> None:
        if gen is not None and gen != self.time_gen:
            return  # a state change took over the beacon chain
        gen = self.time_gen
        f = Frame(CONTROLLER, self.next_seq(), "TIME", HEADER + 23 + MIC, False, MAX_HOPS,
                  ("time",), t_us)
        self.enqueue(f, "time", t_us)
        self.eng.at(t_us + int(TIME_MS * 1000 * self.drift), lambda t, g=gen: self.send_time(t, g))

    def send_state_change(self, t_us: int, kind: str) -> None:
        """A start, pause or resume (field_controller.py: CMD + TIME at once, then TIME alone after each gap of
        ``time_repeat_gaps_ms``; a new change replaces the repeats still due; the 30 s beacon goes on from the
        last repeat). An end is not modelled (GAME_OVER is three field frames, not TIME)."""
        self.time_gen += 1
        gen = self.time_gen
        self.state_changes_sent += 1
        code = {"start": 0, "pause": 1, "resume": 2}[kind]
        body = cmd_encode({"cmd": code, "dest": 0xFFFF})
        self.enqueue(Frame(CONTROLLER, self.next_seq(), "CMD", HEADER + len(body) + MIC, False, MAX_HOPS,
                           ("cmd", None, None), t_us), "cmd", t_us)
        self.enqueue(Frame(CONTROLLER, self.next_seq(), "TIME", HEADER + 23 + MIC, False, MAX_HOPS,
                           ("time",), t_us), "time", t_us)
        at = t_us
        for gap in self.eng.policy.time_repeat_gaps_ms:
            at += int(gap * 1000 * self.drift)
            self.eng.at(at, lambda t, g=gen: self.send_time_repeat(t, g))
        self.eng.at(at + int(TIME_MS * 1000 * self.drift), lambda t, g=gen: self.send_time(t, g))

    def send_time_repeat(self, t_us: int, gen: int) -> None:
        if gen != self.time_gen:
            return  # a later change replaced it
        self.time_repeats_sent += 1
        self.enqueue(Frame(CONTROLLER, self.next_seq(), "TIME", HEADER + 23 + MIC, False, MAX_HOPS,
                           ("time",), t_us), "time", t_us)

    def send_cmd(self, t_us: int, dest: Optional[int], params_len: int, setup: Optional["Setup"] = None) -> None:
        body = cmd_encode({"cmd": 8, "params": {"p": "x" * max(params_len - 8, 0)}, "dest": dest or 0xFFFF})
        f = Frame(CONTROLLER, self.next_seq(), "CMD", HEADER + len(body) + MIC, False, MAX_HOPS,
                  ("cmd", dest, setup), t_us)
        self.eng.cmd_sent.append((dest, t_us))
        if setup is not None:
            setup.frames += 1
        self.enqueue(f, "cmd", t_us)


# ---------------------------------------------------------------------------
# the engine
# ---------------------------------------------------------------------------


class Engine:
    def __init__(self, layout: Layout, trace: Any, region: str, policy: Policy, seed: int = 1,
                 minutes: Optional[int] = None, ideal_channel: bool = False, loss: float = 0.0,
                 drift_ppm: float = 20.0, capture_db: float = CAPTURE_DB, lib: Optional[str] = None,
                 cmd_mode: str = "oneshot", state_changes: Optional[list[tuple[int, str]]] = None) -> None:
        if cmd_mode not in CMD_MODES:
            raise ValueError(f"cmd_mode is one of {CMD_MODES}")
        self.cmd_mode = cmd_mode
        self.state_changes = state_changes  # [(ms after the game's start, "start"|"pause"|"resume")] or None
        self.setups: list[Setup] = []
        self.ack_events: list[EventRec] = []
        self.lib = lib
        self.drift_ppm = drift_ppm
        self.layout, self.trace, self.policy = layout, trace, policy
        self.region = regions.get(region)
        self.rng = random.Random(seed)
        self.minutes = minutes or trace.minutes
        self.q: list[tuple[int, int, Callable[[int], None]]] = []
        self.n_q = 0
        self.now = 0
        self.chan = Channel(self, layout, ideal_channel, loss, capture_db)
        self.nodes: list[Node] = [Controller(self)] + [Box(self, i) for i in range(1, layout.n + 1)]
        self.ctl: Controller = self.nodes[0]  # type: ignore[assignment]
        self.state_interval = policy.period(layout.n)
        self.state_log: list[tuple[int, int, int]] = []
        self.state_heard: dict[tuple[int, int], int] = {}
        self.state_rx_times: dict[int, list[int]] = {i: [] for i in range(1, layout.n + 1)}
        self.state_heard_at: dict[tuple[int, int], int] = {}
        self.events: list[EventRec] = []
        self.cmd_sent: list[tuple[Optional[int], int]] = []
        self.cmd_rx: dict[tuple[int, int], int] = {}
        self.cmd_at: dict[tuple[Optional[int], int], int] = {}
        self.first_heard_by_ctl: dict[int, int] = {}
        if policy.designated:
            relays = layout.designated_relays()
            for i in range(1, layout.n + 1):
                self.nodes[i].is_relay = i in relays  # type: ignore[attr-defined]
            self.n_designated = len(relays)
        else:
            self.n_designated = 0

    def at(self, t_us: int, fn: Callable[[int], None]) -> None:
        self.n_q += 1
        heapq.heappush(self.q, (max(t_us, self.now), self.n_q, fn))

    def deliver(self, r: int, f: Frame, t_us: int) -> None:
        self.nodes[r].on_rx(f, t_us)  # type: ignore[attr-defined]

    def on_dc_drop(self, idx: int, frame: Frame, kind: str) -> None:
        pass

    def on_controller_rx(self, f: Frame, t_us: int) -> None:
        ref = f.ref
        if ref[0] == "state" and f.src != CONTROLLER:
            self.state_rx_times[f.src].append(t_us)
            self.state_heard_at[(f.src, f.seq)] = t_us
        elif ref[0] == "event":
            ev: EventRec = ref[1]
            if ev.delivered_us is None:
                ev.delivered_us = t_us
            setup = getattr(ev, "setup", None)
            if setup is not None and setup.acked_us is None:
                setup.acked_us = t_us  # the scenario hears node.setup_applied: no more repeats of this setup

    def on_cmd_rx(self, idx: int, f: Frame, t_us: int) -> None:
        dest = f.ref[1]
        if dest is None or dest == idx:
            self.cmd_rx.setdefault((idx, f.seq), t_us)
        setup = f.ref[2] if len(f.ref) > 2 else None
        if setup is not None and dest == idx:
            if setup.reached_us is None:
                setup.reached_us = t_us
            if self.cmd_mode == "resend_ack":
                # the box's script says it took the setup: an event like any other (ACK requested, repeated)
                rec = EventRec(len(self.ack_events), idx, "node.setup_applied", "normal", t_us)
                rec.setup = setup  # type: ignore[attr-defined]
                setup.confirmations += 1
                self.ack_events.append(rec)
                self.nodes[idx].new_event(rec, SETUP_ACK_BYTES, "EVENT", t_us)  # type: ignore[attr-defined]

    def setup(self) -> None:
        n = self.layout.n
        tr = self.trace
        # boxes join over the first 30 s: HELLO until acknowledged, then STATE every period
        for i in range(1, n + 1):
            box: Box = self.nodes[i]  # type: ignore[assignment]
            t_join = self.rng.randrange(0, 30_000_000)
            box.last_state_us = t_join
            hello = EventRec(-i, i, "hello", "critical", t_join)
            self.events.append(hello)
            self.at(t_join, lambda t, b=box, h=hello: b.new_event(h, HELLO_BYTES, "HELLO", t))
            self.at(box.tick_at(t_join + self.state_interval * 1000), box.state_tick)
        # the game's events
        for k, e in enumerate(tr.events):
            if e.box + 1 > n:
                continue
            rec = EventRec(k, e.box + 1, e.type, e.prio, e.t_ms * 1000 + GAME_T0_US)
            self.events.append(rec)
            box = self.nodes[e.box + 1]
            self.at(rec.t_us, lambda t, b=box, r=rec, e=e: b.new_event(r, e.payload_len, "EVENT", t))
        for c in tr.commands:
            # a command answers an event the controller has to hear first, and its field script runs on
            # 100 ms steps: 0.3-1.5 s after the trace's time (the first, at the game's start, is not an answer)
            lag = self.rng.randint(300, 1500) * 1000 if c.t_ms > 0 else 0
            self.at(c.t_ms * 1000 + GAME_T0_US + lag, lambda t, c=c: self.send_setup(t, c))
        if self.state_changes is None:
            self.at(GAME_T0_US, self.ctl.send_time)
        else:
            for ms, kind in self.state_changes:
                self.at(GAME_T0_US + ms * 1000, lambda t, k=kind: self.ctl.send_state_change(t, k))

    def send_setup(self, t_us: int, c: Any) -> None:
        """A command of the scenario. For one box it is a setup; in the repeating modes the controller sends it
        again after each wait of RESEND_S (the runtime's every-second tick, so up to a second late) until the box's
        node.setup_applied is heard (``resend_ack``) or the waits are used (``resend``, a box that never says it)."""
        if c.dest is None:
            self.ctl.send_cmd(t_us, None, c.params_len)
            return
        setup = Setup(c.dest + 1, t_us, c.params_len)
        self.setups.append(setup)
        self.ctl.send_cmd(t_us, setup.dest, c.params_len, setup)
        if self.cmd_mode == "oneshot":
            return
        due = t_us
        for wait in RESEND_S:
            due += wait * 1_000_000 + self.rng.randrange(0, 1_000_000)
            self.at(due, lambda t, s=setup, n=c.params_len: self.repeat_setup(t, s, n))

    def repeat_setup(self, t_us: int, setup: Setup, params_len: int) -> None:
        if self.cmd_mode == "resend_ack" and setup.acked_us is not None:
            return
        self.ctl.send_cmd(t_us, setup.dest, params_len, setup)

    def run(self) -> dict[str, Any]:
        self.setup()
        end_us = (self.minutes * 60 + 30) * 1_000_000
        while self.q:
            t, _, fn = heapq.heappop(self.q)
            if t > end_us:
                break
            self.now = t
            fn(t)
        return self.metrics(end_us)

    # -- results --
    def metrics(self, end_us: int) -> dict[str, Any]:
        n = self.layout.n
        t0 = 30_000_000  # the game's start: every box has joined
        dur_s = self.minutes * 60.0
        boxes: list[Box] = self.nodes[1:]  # type: ignore[assignment]
        res: dict[str, Any] = {
            "layout": self.layout.name, "n": n, "game": self.trace.game, "region": self.region.code,
            "policy": self.policy.name, "minutes": self.minutes, "reach": self.layout.reach(),
            "state_period_s": self.state_interval / 1000,
        }
        total_s = dur_s + GAME_T0_US / 1e6

        def share(b: Node, pick: Callable[[str], bool]) -> float:
            return sum(v for k, v in b.stats.air_us.items() if pick(k)) / (total_s * 1e6) * 100

        def last30(b: Node) -> float:
            mins = b.stats.air_by_minute
            end_min = int(end_us // 60_000_000)
            return sum(mins[m] for m in range(max(0, end_min - 30), min(len(mins), end_min))) / (30 * 60e6) * 100

        allp = [share(b, lambda k: True) for b in boxes]
        ownp = [share(b, lambda k: k.startswith("own_")) for b in boxes]
        relp = [share(b, lambda k: k == "relay") for b in boxes]
        l30 = [last30(b) for b in boxes]
        peakp = [b.stats.peak_used_us / b.dc.budget_us * 10.0 for b in boxes]  # of the 10 % budget
        res["airtime_pct"] = {
            "mean": round(statistics.fmean(allp), 2), "max": round(max(allp), 2),
            "own_mean": round(statistics.fmean(ownp), 2), "relay_mean": round(statistics.fmean(relp), 2),
            "last30_mean": round(statistics.fmean(l30), 2), "last30_max": round(max(l30), 2),
            "peak_hour_mean": round(statistics.fmean(peakp), 2), "peak_hour_max": round(max(peakp), 2),
        }
        res["per_box"] = [
            {"box": b.idx, "air_pct": round(allp[i], 2), "own_pct": round(ownp[i], 2), "relay_pct": round(relp[i], 2),
             "dc_dropped": sum(b.stats.dc_dropped.values()), "queue_dropped": sum(b.stats.queue_dropped.values()),
             "rx_collided": b.stats.rx_collided, "rx_halfduplex": b.stats.rx_halfduplex,
             "relays": b.stats.relayed, "states": b.states_sent}
            for i, b in enumerate(boxes)]
        # what a box's budget refused, and what its queues and tables lost
        def total(d: str) -> dict[str, int]:
            out: dict[str, int] = {}
            for b in boxes:
                for k, v in getattr(b.stats, d).items():
                    out[k] = out.get(k, 0) + v
            return out
        dcd, qd = total("dc_dropped"), total("queue_dropped")
        res["dc_dropped"] = {"total": sum(dcd.values()), "per_box_mean": round(sum(dcd.values()) / n, 1),
                             "per_box_max": max(sum(b.stats.dc_dropped.values()) for b in boxes), "by_kind": dcd}
        res["boxes_over_budget"] = sum(1 for b in boxes if b.stats.dc_dropped)
        res["queue_dropped"] = {"total": sum(qd.values()), "by_kind": qd}
        res["relay_slot_dropped"] = sum(b.stats.relay_slot_dropped for b in boxes)
        res["relay_cancelled"] = sum(b.stats.relay_cancelled for b in boxes)
        res["relay_skipped"] = sum(b.stats.relay_skipped for b in boxes)
        res["lbt_deferred"] = sum(b.stats.lbt_deferred for b in boxes)
        res["lbt_gave_up_per_box_hour"] = round(sum(b.stats.lbt_gave_up for b in boxes) / n / (dur_s / 3600.0), 2)
        res["lbt_cads_per_box_hour"] = round(sum(b.stats.lbt_cads for b in boxes) / n / (dur_s / 3600.0), 1)
        res["relays_sent"] = sum(b.stats.relayed for b in boxes)
        res["dedupe_evictions"] = sum(b.stats.dedupe_evictions for b in boxes)
        res["dup_after_evict"] = sum(b.stats.dup_after_evict for b in boxes)
        coll = [b.stats.rx_collided for b in boxes]
        hdx = [b.stats.rx_halfduplex for b in boxes]
        ok = [b.stats.rx_ok for b in boxes]
        res["collisions"] = {
            "rx_lost_per_box_mean": round(statistics.fmean(coll), 1), "rx_lost_per_box_max": max(coll),
            "rx_halfduplex_per_box_mean": round(statistics.fmean(hdx), 1),
            "lost_pct_of_audible": round(100.0 * (sum(coll) + sum(hdx)) / max(1, sum(coll) + sum(hdx) + sum(ok)
                                                                           + sum(b.stats.rx_dup for b in boxes)), 1),
            "controller_lost": self.ctl.stats.rx_collided + self.ctl.stats.rx_halfduplex,
        }
        res["controller"] = {
            "airtime_pct": round(sum(self.ctl.stats.air_us.values()) / (dur_s * 1e6 + 30e6) * 100, 2),
            "dc_dropped": sum(self.ctl.stats.dc_dropped.values()),
            "queue_dropped": sum(self.ctl.stats.queue_dropped.values()),
            "air_s_by_type": {k: round(v / 1e6, 2) for k, v in sorted(self.ctl.stats.air_ptype.items())},
            "state_changes": self.ctl.state_changes_sent, "time_repeats": self.ctl.time_repeats_sent,
            "acks_sent": self.ctl.ack_sent,
            "acks_heard_by_their_box_pct": round(100.0 * sum(b.acks_for_me for b in boxes) / max(1, self.ctl.ack_sent), 1),
        }
        res["time_air_s_per_box_hour"] = {
            "all": round(statistics.fmean(b.stats.air_ptype.get("TIME", 0) for b in boxes) / 1e6 / (dur_s / 3600.0), 2),
            "cmd": round(statistics.fmean(b.stats.air_ptype.get("CMD", 0) for b in boxes) / 1e6 / (dur_s / 3600.0), 2)}
        res["events"] = self._event_metrics(end_us)
        res["states"] = self._state_metrics(end_us, t0)
        if self.cmd_sent:
            res["cmds"] = self._cmd_metrics()
            res["setups"] = self._setup_metrics()
        # TIME every 30 s keeps the boxes' clocks together: a box that went over two minutes without one
        # (or never got one) is at risk of drifting off the game clock
        gaps = [max(b.max_time_gap_us, end_us - (b.last_time_us or GAME_T0_US)) for b in boxes]
        res["time_sync"] = {"boxes_gap_over_120s": sum(1 for g in gaps if g > 120_000_000),
                            "max_gap_s": round(max(gaps) / 1e6, 1)}
        if self.n_designated:
            res["designated_relays"] = self.n_designated
        return res

    def _event_metrics(self, end_us: int) -> dict[str, Any]:
        game = [e for e in self.events if e.eid >= 0 and e.prio != "telemetry"]
        hello = [e for e in self.events if e.eid < 0]
        def stats(evs: list[EventRec]) -> dict[str, Any]:
            if not evs:
                return {"n": 0}
            lat = sorted((e.delivered_us - e.t_us) / 1e6 for e in evs if e.delivered_us is not None)
            ack = sorted((e.acked_us - e.t_us) / 1e6 for e in evs if e.acked_us is not None)
            def q(v: list[float], p: float) -> Optional[float]:
                return round(v[min(len(v) - 1, int(p * len(v)))], 2) if v else None
            return {"n": len(evs), "delivered_pct": round(100.0 * len(lat) / len(evs), 1),
                    "acked_pct": round(100.0 * len(ack) / len(evs), 1),
                    "latency_p50_s": q(lat, 0.5), "latency_p95_s": q(lat, 0.95),
                    "latency_max_s": round(lat[-1], 2) if lat else None,
                    "ack_latency_p50_s": q(ack, 0.5), "ack_latency_p95_s": q(ack, 0.95),
                    "mean_transmissions": round(statistics.fmean(e.tx_count for e in evs), 2),
                    "expired": sum(1 for e in evs if e.expired)}
        caps = [e for e in game if e.type in ("zone.captured", "zone.neutralized")]
        by_time = {}
        for name, lo, hi in (("first_45_min", 0, 45), ("last_30_min", self.minutes - 30, self.minutes)):
            part = [e for e in caps if lo * 60e6 <= e.t_us - GAME_T0_US < hi * 60e6]
            by_time[name] = round(100.0 * sum(1 for e in part if e.acked_us is not None) / len(part), 1) if part else None
        return {"captures": stats(caps), "captures_acked_pct_by_period": by_time,
                "all_game_events": stats(game), "hello": stats(hello)}

    def _state_metrics(self, end_us: int, t0: int) -> dict[str, Any]:
        sent = len(self.state_log)
        # a STATE is "heard" when the controller got that (source, seq)
        heard = sum(1 for (src, seq, _t) in self.state_log if (src, seq) in self.ctl.heard)
        # age of each box's newest STATE at the controller, sampled each second after the first minute
        # (a box never heard has the age of the game)
        ages: list[float] = []
        never = 0
        grid = range(t0 + 60_000_000, end_us, 1_000_000)
        for i in range(1, self.layout.n + 1):
            times = sorted(self.state_rx_times[i])
            never += 0 if times else 1
            for g in grid:
                k = bisect_right(times, g)
                ages.append((g - (times[k - 1] if k else t0)) / 1e6)
        ages.sort()
        lat = sorted((self.state_heard_at[(src, seq)] - t_tx) / 1e6 for (src, seq, t_tx) in self.state_log
                     if (src, seq) in self.state_heard_at)

        def lq(p: float) -> Optional[float]:
            return round(lat[min(len(lat) - 1, int(p * len(lat)))], 2) if lat else None

        def pct(p: float) -> Optional[float]:
            return round(ages[min(len(ages) - 1, int(p * len(ages)))], 1) if ages else None

        return {"sent": sent, "heard_pct": round(100.0 * heard / max(1, sent), 1), "boxes_never_heard": never,
                "latency_p50_s": lq(0.5), "latency_p95_s": lq(0.95),
                "age_p50_s": pct(0.5), "age_p95_s": pct(0.95), "age_max_s": round(ages[-1], 1) if ages else None,
                "stale_over_60s_pct": round(100.0 * sum(1 for a in ages if a > 60) / max(1, len(ages)), 2),
                "period_s": self.state_interval / 1000}

    def _setup_metrics(self) -> dict[str, Any]:
        """The scenario's setup commands as logical commands (one per box and trace command, whatever the number
        of repeats): how many reached their box, how long it took, what they cost, and how many the scenario
        knew had arrived (the box's own node.setup_applied, heard)."""
        n = len(self.setups)
        lat = sorted((x.reached_us - x.t_us) / 1e6 for x in self.setups if x.reached_us is not None)
        def q(p: float) -> Optional[float]:
            return round(lat[min(len(lat) - 1, int(p * len(lat)))], 2) if lat else None
        acks = [e for e in self.ack_events]
        return {"mode": self.cmd_mode, "n": n,
                "reached_pct": round(100.0 * len(lat) / max(1, n), 1),
                "acked_pct": round(100.0 * sum(1 for x in self.setups if x.acked_us is not None) / max(1, n), 1),
                "latency_p50_s": q(0.5), "latency_p95_s": q(0.95),
                "cmd_frames": sum(x.frames for x in self.setups),
                "frames_per_setup": round(sum(x.frames for x in self.setups) / max(1, n), 2),
                "confirmations": len(acks),
                "confirmations_heard_pct": round(100.0 * sum(1 for e in acks if e.delivered_us is not None)
                                                 / max(1, len(acks)), 1)}

    def _cmd_metrics(self) -> dict[str, Any]:
        sent = len(self.cmd_sent)
        # a CMD for one box is delivered if that box heard it; a broadcast if each box did
        got = 0
        want = 0
        n = self.layout.n
        for dest, _t in self.cmd_sent:
            want += 1 if dest is not None else n
        for (idx, _seq), _t in self.cmd_rx.items():
            got += 1
        return {"sent": sent, "box_deliveries_wanted": want, "box_deliveries": got,
                "delivered_pct": round(100.0 * min(got, want) / max(1, want), 1)}


# ---------------------------------------------------------------------------
# running studies
# ---------------------------------------------------------------------------


def run_one(game: str, n: int, layout: str, region: str, policy: str, minutes: int = 90, seed: int = 1,
            lib: Optional[str] = None, ideal_channel: bool = False, loss: float = 0.0, capture_db: float = CAPTURE_DB,
            drift_ppm: float = 20.0, trace: Any = None, cmd_mode: str = "oneshot",
            state_changes: Optional[list[tuple[int, str]]] = None, time_repeat_gaps_ms: Optional[tuple[int, ...]] = None,
            **trace_kw: Any) -> dict[str, Any]:
    from .relay_traces import get_trace
    tr = trace or get_trace(game, n, minutes, seed, lib, **trace_kw)
    lay = LAYOUTS[layout](n, seed)
    pol = POLICIES[policy]
    if time_repeat_gaps_ms is not None:
        pol = replace(pol, time_repeat_gaps_ms=time_repeat_gaps_ms)
    eng = Engine(lay, tr, region, pol, seed=seed, minutes=minutes, ideal_channel=ideal_channel,
                 loss=loss, capture_db=capture_db, drift_ppm=drift_ppm, lib=lib, cmd_mode=cmd_mode,
                 state_changes=state_changes)
    res = eng.run()
    res["seed"] = seed
    return res


def _worker(args: tuple[Any, ...]) -> dict[str, Any]:
    game, n, layout, region, policy, minutes, seed, lib, kw = args
    return run_one(game, n, layout, region, policy, minutes, seed, lib, **kw)


def run_matrix(games: list[str], sizes: list[int], layouts: list[str], regions_: list[str],
               policies: list[str], minutes: int = 90, seeds: Optional[list[int]] = None,
               lib: Optional[str] = None, workers: int = 0, **run_kw: Any) -> list[dict[str, Any]]:
    """Every combination, ``seeds`` times (a seed changes the layout's randomness, the clocks, the
    traffic and every draw). ``run_kw``: ideal_channel, loss, capture_db, drift_ppm, captures_per_box_per_min."""
    jobs = [(g, n, lay, r, p, minutes, sd, lib, run_kw)
            for g in games for n in sizes for lay in layouts for r in regions_ for p in policies
            for sd in (seeds or [1]) if not (g == "scenario" and n < 4)]
    if workers == 1:
        return [_worker(j) for j in jobs]
    import concurrent.futures as cf
    with cf.ProcessPoolExecutor(max_workers=workers or None) as ex:
        return list(ex.map(_worker, jobs, chunksize=1))


def _csv(s: str) -> list[str]:
    return [x for x in s.split(",") if x]


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m atalaia_sim.relay_study",
                                 description="Measure the field's relay flood: airtime, duty cycle, collisions, delivery.")
    ap.add_argument("--games", default="domination,scenario")
    ap.add_argument("--sizes", default="5,10,20,30")
    ap.add_argument("--layouts", default=",".join(LAYOUTS))
    ap.add_argument("--regions", default="eu868,as923-tw")
    ap.add_argument("--policies", default="firmware")
    ap.add_argument("--minutes", type=int, default=90)
    ap.add_argument("--seeds", default="1", help="comma-separated; the tables show the median over them")
    ap.add_argument("--lib", default=None, help="the core's shared library (default: as the simulator finds it)")
    ap.add_argument("--ideal-channel", action="store_true",
                    help="no collisions and no half duplex: SL-4's arithmetic, for comparison")
    ap.add_argument("--capture-db", type=float, default=CAPTURE_DB)
    ap.add_argument("--loss", type=float, default=0.0, help="random loss of each reception (0.05 = 5 %%)")
    ap.add_argument("--drift-ppm", type=float, default=20.0)
    ap.add_argument("--captures-per-box-per-min", type=float, default=0.33)
    ap.add_argument("--cmd-mode", default="oneshot", choices=CMD_MODES,
                    help="the scenario's setup commands: sent once (the controller as built before PKB-3), again "
                         "after 8, 16, 32, 64 and 128 s whatever happens, or again until the box confirms it")
    ap.add_argument("--workers", type=int, default=0, help="processes (default: all cores; 1: in this one)")
    ap.add_argument("--out", default=None, help="write the results as JSON here")
    ap.add_argument("--report", default=None, metavar="FILE", help="write the decision tables (Markdown) here")
    ap.add_argument("--list-policies", action="store_true")
    args = ap.parse_args(argv)
    if args.list_policies:
        for p in POLICIES.values():
            print(f"{p.name:<22} {p.summary}")
        return 0
    results = run_matrix(_csv(args.games), [int(x) for x in _csv(args.sizes)], _csv(args.layouts),
                         _csv(args.regions), _csv(args.policies), args.minutes, [int(x) for x in _csv(args.seeds)],
                         args.lib, args.workers, ideal_channel=args.ideal_channel, loss=args.loss,
                         capture_db=args.capture_db, drift_ppm=args.drift_ppm,
                         captures_per_box_per_min=args.captures_per_box_per_min, cmd_mode=args.cmd_mode)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(results, fh)
    from .relay_report import decision_tables, summary_table
    print(summary_table(results))
    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            fh.write(decision_tables(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
