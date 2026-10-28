# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""USB radio modem framing (protocol/usb-modem.md), the Python side.

    0xA5 | type (1) | length (2, big-endian) | payload | CRC-16/CCITT-FALSE (2, big-endian)

The same algorithm as firmware/esp32/main/modem/modem_framing.c, which the
modem runs: tests check this module against the C host modem.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Iterator, Optional

from atalaia_sim.packet import HEADER_SIZE, KEY_SIZE, Header, header_decode

SYNC = 0xA5
PAYLOAD_MAX = 256
OVERHEAD = 6

# Frame types
IDENT = 0x01
RX = 0x02
TX = 0x03
TX_ACK = 0x04
CMD = 0x05
STATUS = 0x06
ERROR = 0x07
NOISE = 0x08
# Field frames (protocol/field-frames.md): sealed by the controller, carried as they are.
FIELD_TX = 0x09   # controller -> modem: id (2) + a whole field frame
FIELD_RX = 0x0A   # modem -> controller: a field frame heard + rssi + snr
FIELD_ACK = 0x0B  # modem -> controller: id (2) + status (TX_STATUS)
FIELD_FRAME_MAX = 217

# CMD opcodes
CMD_PING = 0x01
CMD_CONFIGURE = 0x02
CMD_SET_CHANNEL = 0x03
CMD_STATUS = 0x04
CMD_SET_PEER_EPOCH = 0x05
CMD_CLEAR = 0x06
CMD_IDENT = 0x07
CMD_MEASURE = 0x08
CMD_SET_LANG = 0x09  # the language of the modem's own screen (IDENT "lang": true)
LANG_MAX = 8

MEASURE_CAD = 0x01
MEASURE_DWELL_MIN_MS = 10
MEASURE_DWELL_MAX_MS = 10_000
NOISE_LEN = 17

# TX_ACK status codes
TX_STATUS = {
    0: "ok",
    1: "duty_cycle",
    2: "timeout",
    3: "not_configured",
    4: "invalid",
    5: "nonce_reuse",
    6: "queue_full",
    7: "no_radio",
    8: "busy",
}

# ERROR codes
ERRORS = {
    1: "bad_frame",
    2: "unknown_type",
    3: "unknown_cmd",
    4: "not_configured",
    5: "radio",
    6: "bad_params",
    7: "busy",
    8: "no_radio",
}


class FrameError(ValueError):
    pass


def set_lang_payload(code: str) -> bytes:
    """SET_LANG: the language code ("pt", "de", "zh-tw"...: letters, digits and '-', up to 8,
    sent in lower case); "" sends the modem back to its build's language."""
    if len(code) > LANG_MAX or not all(c.isascii() and (c.isalnum() or c == "-") for c in code):
        raise ValueError(f"a language code is up to {LANG_MAX} letters, digits or '-': {code!r}")
    return bytes([CMD_SET_LANG]) + code.lower().encode("ascii")


def crc16(data: bytes) -> int:
    """CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF. crc16(b"123456789") == 0x29B1."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def encode_frame(frame_type: int, payload: bytes = b"") -> bytes:
    if len(payload) > PAYLOAD_MAX:
        raise FrameError(f"payload of {len(payload)} bytes; at most {PAYLOAD_MAX}")
    body = bytes([frame_type]) + struct.pack(">H", len(payload)) + payload
    return bytes([SYNC]) + body + struct.pack(">H", crc16(body))


class FrameDecoder:
    """Finds frames in a byte stream, skipping junk; same resync rules as the C decoder."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self.frames = 0
        self.crc_errors = 0
        self.length_errors = 0
        self.dropped_bytes = 0

    def feed(self, data: bytes) -> list[tuple[int, bytes]]:
        self._buf.extend(data)
        return list(self._parse())

    def _parse(self) -> Iterator[tuple[int, bytes]]:
        buf = self._buf
        while True:
            start = buf.find(SYNC)
            if start < 0:
                self.dropped_bytes += len(buf)
                buf.clear()
                return
            if start:
                self.dropped_bytes += start
                del buf[:start]
            if len(buf) < 4:
                return
            length = (buf[2] << 8) | buf[3]
            if length > PAYLOAD_MAX:
                self.length_errors += 1
                self.dropped_bytes += 1
                del buf[:1]
                continue
            total = length + OVERHEAD
            if len(buf) < total:
                return
            want = (buf[4 + length] << 8) | buf[5 + length]
            if crc16(bytes(buf[1:4 + length])) != want:
                self.crc_errors += 1
                self.dropped_bytes += 1
                del buf[:1]
                continue
            self.frames += 1
            frame = (buf[1], bytes(buf[4:4 + length]))
            del buf[:total]
            yield frame


# --- payloads ----------------------------------------------------------------


def configure_payload(game_id: int, node_id: int, epoch: int, max_hops: int, channel_hz: int,
                      key: bytes) -> bytes:
    if len(key) != KEY_SIZE:
        raise FrameError("the game key is 16 bytes")
    return struct.pack(">BHHHBI", CMD_CONFIGURE, game_id, node_id, epoch, max_hops, channel_hz) + key


def ping_payload(token: int) -> bytes:
    return struct.pack(">BI", CMD_PING, token & 0xFFFFFFFF)


def set_channel_payload(channel_hz: int) -> bytes:
    return struct.pack(">BI", CMD_SET_CHANNEL, channel_hz)


def measure_payload(channel_hz: int, dwell_ms: int, cad: bool = True) -> bytes:
    if not MEASURE_DWELL_MIN_MS <= dwell_ms <= MEASURE_DWELL_MAX_MS:
        raise FrameError(f"dwell of {dwell_ms} ms; {MEASURE_DWELL_MIN_MS}-{MEASURE_DWELL_MAX_MS}")
    return struct.pack(">BIHB", CMD_MEASURE, channel_hz, dwell_ms, MEASURE_CAD if cad else 0)


@dataclass
class Noise:
    """A NOISE frame: the noise the modem measured on one channel (MEASURE)."""

    channel_hz: int
    dwell_ms: int
    samples: int
    min_dbm: int
    mean_dbm: int
    p50_dbm: int
    p90_dbm: int
    max_dbm: int
    cad_tries: int
    cad_detected: int

    @property
    def activity(self) -> float:
        """The share of channel-activity detections that found a LoRa preamble."""
        return self.cad_detected / self.cad_tries if self.cad_tries else 0.0


def decode_noise(payload: bytes) -> Noise:
    if len(payload) != NOISE_LEN:
        raise FrameError(f"NOISE is {NOISE_LEN} bytes")
    return Noise(*struct.unpack(">IHHbbbbbHH", payload))


def peer_epoch_payload(pairs: list[tuple[int, int]]) -> bytes:
    return bytes([CMD_SET_PEER_EPOCH]) + b"".join(struct.pack(">HH", s, e) for s, e in pairs)


@dataclass
class RxPacket:
    """An RX frame: a packet the modem heard and authenticated."""

    header: Header
    raw_header: bytes
    payload: bytes
    rssi: int
    snr: int
    epoch: int


def decode_rx(payload: bytes) -> RxPacket:
    if len(payload) < HEADER_SIZE + 4:
        raise FrameError("RX frame shorter than a header and its trailer")
    raw_header = payload[:HEADER_SIZE]
    rssi, snr, epoch = struct.unpack(">bbH", payload[-4:])
    return RxPacket(header_decode(raw_header), raw_header, payload[HEADER_SIZE:-4], rssi, snr, epoch)


def decode_tx_ack(payload: bytes) -> tuple[int, str]:
    if len(payload) != 3:
        raise FrameError("TX_ACK is 3 bytes")
    seq, status = struct.unpack(">HB", payload)
    return seq, TX_STATUS.get(status, f"status_{status}")


def decode_error(payload: bytes) -> tuple[str, str]:
    if not payload:
        raise FrameError("empty ERROR frame")
    return ERRORS.get(payload[0], f"error_{payload[0]}"), payload[1:].decode("utf-8", "replace")


def tx_payload(header_bytes: bytes, plaintext: bytes) -> bytes:
    if len(header_bytes) != HEADER_SIZE:
        raise FrameError("a TX frame starts with the 9-byte header")
    return header_bytes + plaintext


def field_tx_payload(tx_id: int, frame: bytes) -> bytes:
    if not 0 <= tx_id <= 0xFFFF or not 1 <= len(frame) <= FIELD_FRAME_MAX:
        raise FrameError("FIELD_TX: an id of 0-65535 and a frame of at most 217 bytes")
    return struct.pack(">H", tx_id) + frame


def decode_field_rx(payload: bytes) -> tuple[bytes, int, int]:
    """A FIELD_RX frame: (the field frame as heard, rssi, snr)."""
    if len(payload) < HEADER_SIZE + 2:
        raise FrameError("FIELD_RX shorter than a header and its trailer")
    rssi, snr = struct.unpack(">bb", payload[-2:])
    return payload[:-2], rssi, snr


def decode_field_ack(payload: bytes) -> tuple[int, str]:
    if len(payload) != 3:
        raise FrameError("FIELD_ACK is 3 bytes")
    tx_id, status = struct.unpack(">HB", payload)
    return tx_id, TX_STATUS.get(status, f"status_{status}")


def frame_name(frame_type: int) -> Optional[str]:
    return {IDENT: "IDENT", RX: "RX", TX: "TX", TX_ACK: "TX_ACK", CMD: "CMD", STATUS: "STATUS",
            ERROR: "ERROR", NOISE: "NOISE", FIELD_TX: "FIELD_TX", FIELD_RX: "FIELD_RX",
            FIELD_ACK: "FIELD_ACK"}.get(frame_type)
