# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Radio model for multi-node simulation with lossy delivery.

Simulates the LoRa radio layer between field nodes: packet encoding,
random loss, jitter, flood relay, deduplication, network partitions,
and per-node duty-cycle tracking.

The duty-cycle budget and the maximum power follow the game channel's
sub-band in the field's region (regions.py, RFC 0001 Amendments 3 and 12),
as on the boxes and the USB modem: in EU868, 10% and 500 mW ERP on
869.4-869.65 MHz, 1% (0.1% on 868.7-869.2 MHz) and 25 mW elsewhere; in
AS923-TW, 0.5 W at the antenna port and this project's 10%. Time on air
uses the LoRa formula at the region's SF and bandwidth (SF7/125 kHz,
SF9/500 kHz). A node whose budget is spent does not transmit, nor one
whose packet is longer than the region's dwell rule allows.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional

from .packet import (
    HEADER_SIZE,
    KEY_SIZE,
    MIC_SIZE,
    Header,
    header_decode,
    header_encode,
    nonce_build,
    aad_extract,
    vf_make,
    vf_enc,
)
from . import regions
from .protocol import MESSAGE_TYPES

# Delivery jitter range in ms.
_JITTER_MIN_MS = 5
_JITTER_MAX_MS = 50

# Deduplication window: discard packets seen within this time.
_DEDUPE_WINDOW_MS = 10_000


# --- configuration -----------------------------------------------------------


@dataclass
class RadioConfig:
    """Configuration for the radio model."""

    loss_rate: float = 0.0       # 0.0 = no loss, 1.0 = all lost
    max_hops: int = 2            # default hop limit
    game_id: int = 1             # game identifier for packet headers
    game_key: bytes = b"\x00" * KEY_SIZE  # AES-128 key (test default)
    epoch: int = 0               # current encryption epoch
    channel_hz: Optional[int] = None  # single shared game channel (None: the region's default)
    fem_gain_db: int = 14        # Heltec V4.3 front-end module (decision C2)
    antenna_gain_dbi: int = 2
    region: str = "eu868"        # the field's radio region (regions.py)

    def __post_init__(self) -> None:
        if self.channel_hz is None:
            self.channel_hz = regions.get(self.region).default_channel_hz


# --- pending packet -----------------------------------------------------------


@dataclass
class PendingPacket:
    """A packet waiting to be delivered at a future time."""

    data: bytes          # raw on-air packet bytes
    header: Header       # decoded header (for inspection)
    deliver_at_ms: int   # simulation time when delivery occurs
    from_node: int       # source node id (immediate sender, may differ from header.source)
    raw: bool = False    # a field frame (protocol/field-frames.md): delivered as it is, never relayed
    dest: Optional[int] = None  # a field frame's one receiver (its loss was drawn at send)


# --- duty-cycle tracker -------------------------------------------------------


class DutyCycleTracker:
    """Per-node duty-cycle tracking (simplified for simulation).

    The budget is expressed in milliseconds of airtime allowed per
    rolling hour (3_600_000 ms): the channel's sub-band duty cycle times
    an hour, 360_000 ms at 10 % (g2) and 36_000 ms at 1 %.
    """

    HOUR_MS = 3_600_000

    def __init__(self, budget_ms_per_hour: float = 360_000.0) -> None:
        self.budget_ms_per_hour = budget_ms_per_hour
        self._used: list[tuple[int, float]] = []  # (timestamp_ms, airtime_ms)

    def _prune(self, now_ms: int) -> None:
        cutoff = now_ms - self.HOUR_MS
        self._used = [(t, a) for t, a in self._used if t > cutoff]

    def can_send(self, airtime_ms: float, now_ms: int = 0) -> bool:
        """Whether spending *airtime_ms* would exceed the hourly budget."""
        self._prune(now_ms)
        total = sum(a for _, a in self._used)
        return (total + airtime_ms) <= self.budget_ms_per_hour

    def record(self, airtime_ms: float, now_ms: int) -> None:
        """Record *airtime_ms* of transmission at *now_ms*."""
        self._used.append((now_ms, airtime_ms))

    def used(self, now_ms: int) -> float:
        """Total airtime used in the current hour window."""
        self._prune(now_ms)
        return sum(a for _, a in self._used)

    def tick(self, now_ms: int) -> None:
        """Prune old entries (called periodically by the radio model)."""
        self._prune(now_ms)


# --- radio node (per-node state) ----------------------------------------------


@dataclass
class RadioNode:
    """Per-node state inside the radio model."""

    node_id: int
    duty: DutyCycleTracker = field(default_factory=DutyCycleTracker)
    duty_refused: int = 0  # packets not sent: the budget was spent


# --- radio model --------------------------------------------------------------


class RadioModel:
    """Simulated lossy radio layer for multi-node field testing."""

    def __init__(
        self,
        config: Optional[RadioConfig] = None,
        rng: Optional[random.Random] = None,
    ) -> None:
        self.config = config or RadioConfig()
        self.region = regions.get(self.config.region)
        band = self.region.band_of(self.config.channel_hz)
        if band is None:
            raise ValueError(f"channel {self.config.channel_hz} Hz: the {self.region.bw_hz // 1000} kHz "
                             f"channel must fit inside a {self.region.code} sub-band")
        self.band: regions.SubBand = band
        power = regions.legal_tx_power_dbm(band, self.config.fem_gain_db, self.config.antenna_gain_dbi)
        if power is None:
            raise ValueError(f"channel {self.config.channel_hz} Hz: even the radio's lowest power would "
                             "exceed the limit with these gains")
        self._tx_power_dbm = power
        self.rng = rng or random.Random(42)
        self.nodes: dict[int, RadioNode] = {}
        self.pending: list[PendingPacket] = []
        # Per-node deduplication: node_id -> {(source, seq): last_seen_ms}
        self.dedupe: dict[int, dict[tuple[int, int], int]] = {}
        # Link connectivity: (a, b) -> connected (bidirectional)
        self.links: dict[tuple[int, int], bool] = {}
        # Record of all delivered packets: (dest_node_id, raw_data)
        self.delivered: list[tuple[int, bytes]] = []
        # Field frames heard by each node, not yet taken (take_raw): sealed with the field's
        # key, not the game's, so the model hands them over as they are (protocol/field-frames.md).
        self.raw_inbox: dict[int, list[bytes]] = {}
        # Track the current simulation time for internal bookkeeping.
        self._now_ms: int = 0

    # --- node management ------------------------------------------------------

    def add_node(self, node_id: int) -> None:
        """Register a node with the radio model."""
        if node_id in self.nodes:
            return
        self.nodes[node_id] = RadioNode(
            node_id=node_id, duty=DutyCycleTracker(self.band.budget_ms_per_hour))
        self.dedupe[node_id] = {}
        # By default, every new node can reach every existing node.
        for other_id in self.nodes:
            if other_id != node_id:
                self._set_link_internal(node_id, other_id, True)

    def remove_node(self, node_id: int) -> None:
        """Remove a node from the radio model."""
        self.nodes.pop(node_id, None)
        self.dedupe.pop(node_id, None)
        # Remove all links involving this node.
        to_remove = [k for k in self.links if node_id in k]
        for k in to_remove:
            del self.links[k]
        # Remove pending packets from/to this node.
        self.pending = [
            p for p in self.pending if p.from_node != node_id
        ]

    # --- link management ------------------------------------------------------

    def _link_key(self, a: int, b: int) -> tuple[int, int]:
        return (min(a, b), max(a, b))

    def _set_link_internal(self, a: int, b: int, connected: bool) -> None:
        self.links[self._link_key(a, b)] = connected

    def set_link(self, a: int, b: int, connected: bool) -> None:
        """Set the connectivity between two nodes."""
        self._set_link_internal(a, b, connected)

    def is_linked(self, a: int, b: int) -> bool:
        """Check if two nodes can communicate."""
        return self.links.get(self._link_key(a, b), False)

    def partition(self, group_a: set[int], group_b: set[int]) -> None:
        """Disconnect all links between group_a and group_b."""
        for a in group_a:
            for b in group_b:
                self._set_link_internal(a, b, False)

    def heal(self) -> None:
        """Restore full connectivity between all registered nodes."""
        node_ids = list(self.nodes.keys())
        for i, a in enumerate(node_ids):
            for b in node_ids[i + 1:]:
                self._set_link_internal(a, b, True)

    # --- airtime and limits ---------------------------------------------------

    def _estimate_airtime(self, packet_len: int) -> float:
        """On-air time in ms of a whole packet (LoRa formula, the region's SF and bandwidth)."""
        return self.region.airtime_ms(packet_len)

    @property
    def duty_budget_ms_per_hour(self) -> float:
        """The channel's sub-band duty cycle times an hour."""
        return self.band.budget_ms_per_hour

    @property
    def max_erp_dbm(self) -> int:
        """The sub-band's power limit: 27 dBm (500 mW) on g2 and in AS923-TW, 14 dBm (25 mW) elsewhere."""
        return self.band.limit_dbm

    @property
    def tx_power_dbm(self) -> int:
        """The SX1262 conducted power the boxes use on this channel (radio_power.h)."""
        return self._tx_power_dbm

    def _spend(self, node_id: int, packet_len: int, now_ms: int) -> bool:
        """Records a transmission in the node's budget; False (and nothing sent) if it does not fit."""
        node_obj = self.nodes.get(node_id)
        if node_obj is None:
            return True
        airtime = self._estimate_airtime(packet_len)
        dwell = self.region.max_dwell_ms
        if (dwell and airtime > dwell) or not node_obj.duty.can_send(airtime, now_ms):
            node_obj.duty_refused += 1
            return False
        node_obj.duty.record(airtime, now_ms)
        return True

    # --- send -----------------------------------------------------------------

    def send(
        self,
        from_node: int,
        payload: bytes,
        msg_type: int,
        source: int,
        seq: int,
        priority: int = 1,
        ack_req: bool = False,
        hop_limit: int = 2,
        now_ms: Optional[int] = None,
    ) -> bytes:
        """Construct and broadcast a packet from *from_node*.

        Returns the raw packet bytes (header + payload + MIC if encrypted,
        or header + plaintext payload if encryption is unavailable).
        """
        if now_ms is None:
            now_ms = self._now_ms

        encrypted = True
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESCCM  # noqa: F401
        except ImportError:
            encrypted = False

        vf = vf_make(version=1, prio=priority, ack=ack_req, enc=encrypted)
        hdr = Header(
            version_flags=vf,
            game_id=self.config.game_id,
            source=source,
            seq=seq,
            hop_limit=hop_limit,
            type=msg_type,
        )

        if encrypted:
            from .packet import packet_encrypt
            raw = packet_encrypt(hdr, self.config.epoch, self.config.game_key, payload)
        else:
            raw = header_encode(hdr) + payload

        # Duty-cycle check: a node whose budget is spent stays silent.
        if not self._spend(from_node, len(raw), now_ms):
            return raw

        # Mark the sender as having seen this (source, seq) so it won't
        # process its own packet or relay it back.
        if from_node in self.dedupe:
            self.dedupe[from_node][(source, seq)] = now_ms

        # Enqueue delivery to every connected node (except the sender).
        for dest_id in self.nodes:
            if dest_id == from_node:
                continue
            if not self.is_linked(from_node, dest_id):
                continue
            # Random loss
            if self.rng.random() < self.config.loss_rate:
                continue
            jitter = self.rng.randint(_JITTER_MIN_MS, _JITTER_MAX_MS)
            self.pending.append(PendingPacket(
                data=raw,
                header=hdr,
                deliver_at_ms=now_ms + jitter,
                from_node=from_node,
            ))

        return raw

    def send_raw(self, from_node: int, raw: bytes, now_ms: Optional[int] = None) -> bool:
        """Puts a ready-made frame on air (a field frame): duty cycle and loss as for any packet,
        no relay, no game key. False if the sender's duty-cycle budget is spent."""
        if now_ms is None:
            now_ms = self._now_ms
        if not self._spend(from_node, len(raw), now_ms):
            return False
        hdr = header_decode(raw[:HEADER_SIZE])
        for dest_id in self.nodes:
            if dest_id == from_node or not self.is_linked(from_node, dest_id):
                continue
            if self.rng.random() < self.config.loss_rate:
                continue
            self.pending.append(PendingPacket(data=raw, header=hdr, from_node=from_node, raw=True, dest=dest_id,
                                              deliver_at_ms=now_ms + self.rng.randint(_JITTER_MIN_MS, _JITTER_MAX_MS)))
        return True

    def take_raw(self, node_id: int) -> list[bytes]:
        """The field frames node_id has heard since the last call."""
        return self.raw_inbox.pop(node_id, [])

    # --- tick (deliver pending packets) ----------------------------------------

    def tick(self, now_ms: int) -> list[tuple[int, Header, bytes]]:
        """Advance time to *now_ms* and deliver pending packets.

        Returns a list of ``(dest_node_id, header, decrypted_payload)``
        for every successfully received packet.
        """
        self._now_ms = now_ms

        # Prune old deduplication entries.
        for nid, table in self.dedupe.items():
            expired = [
                k for k, t in table.items()
                if now_ms - t > _DEDUPE_WINDOW_MS
            ]
            for k in expired:
                del table[k]

        # Tick duty-cycle trackers.
        for node_obj in self.nodes.values():
            node_obj.duty.tick(now_ms)

        # Collect packets that are due.
        due: list[PendingPacket] = []
        still_pending: list[PendingPacket] = []
        for pkt in self.pending:
            if pkt.deliver_at_ms <= now_ms:
                due.append(pkt)
            else:
                still_pending.append(pkt)
        self.pending = still_pending

        results: list[tuple[int, Header, bytes]] = []

        for pkt in due:
            if pkt.raw:
                if pkt.dest in self.nodes and self.is_linked(pkt.from_node, pkt.dest):
                    self.raw_inbox.setdefault(pkt.dest, []).append(pkt.data)
                continue
            # Deliver to every connected node that hasn't seen it.
            for dest_id in list(self.nodes.keys()):
                if dest_id == pkt.from_node:
                    continue
                if not self.is_linked(pkt.from_node, dest_id):
                    continue

                src = pkt.header.source
                seq = pkt.header.seq
                if self._is_duplicate(dest_id, src, seq, now_ms):
                    continue

                # Mark as seen.
                self.dedupe[dest_id][(src, seq)] = now_ms
                self.delivered.append((dest_id, pkt.data))

                # Decrypt if possible.
                try:
                    from .packet import packet_decrypt
                    hdr, plaintext = packet_decrypt(
                        pkt.data, self.config.epoch, self.config.game_key
                    )
                except ImportError:
                    # No cryptography library -- deliver raw payload after header.
                    hdr = pkt.header
                    plaintext = pkt.data[HEADER_SIZE:]
                except Exception:
                    # Decryption failure -- drop.
                    continue

                results.append((dest_id, hdr, plaintext))

                # Flood relay: if hop_limit > 1 and this node should relay.
                if self._should_relay(hdr):
                    relay_hdr = Header(
                        version_flags=hdr.version_flags,
                        game_id=hdr.game_id,
                        source=hdr.source,
                        seq=hdr.seq,
                        hop_limit=hdr.hop_limit - 1,
                        type=hdr.type,
                    )
                    # Re-encrypt with decremented hop_limit.
                    try:
                        from .packet import packet_encrypt
                        relay_raw = packet_encrypt(
                            relay_hdr, self.config.epoch,
                            self.config.game_key, plaintext,
                        )
                    except ImportError:
                        relay_raw = header_encode(relay_hdr) + plaintext

                    if not self._spend(dest_id, len(relay_raw), now_ms):
                        continue

                    for next_id in self.nodes:
                        if next_id == dest_id or next_id == pkt.from_node:
                            continue
                        if not self.is_linked(dest_id, next_id):
                            continue
                        if self.rng.random() < self.config.loss_rate:
                            continue
                        jitter = self.rng.randint(_JITTER_MIN_MS, _JITTER_MAX_MS)
                        self.pending.append(PendingPacket(
                            data=relay_raw,
                            header=relay_hdr,
                            deliver_at_ms=now_ms + jitter,
                            from_node=dest_id,
                        ))

        return results

    # --- deduplication --------------------------------------------------------

    def _is_duplicate(self, node_id: int, source: int, seq: int, now_ms: int) -> bool:
        """Check if node *node_id* has already seen (source, seq)."""
        table = self.dedupe.get(node_id, {})
        if (source, seq) in table:
            return True
        return False

    # --- relay decision -------------------------------------------------------

    def _should_relay(self, header: Header) -> bool:
        """Decide whether a received packet should be flood-relayed."""
        return header.hop_limit > 1
