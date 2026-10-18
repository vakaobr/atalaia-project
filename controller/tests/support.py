# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Helpers for the controller tests: the core, the C host modem, Mosquitto, fake links.

With ATALAIA_REQUIRE_ALL=1 (check.sh and CI) a missing core library, host
modem binary or mosquitto is an error, never a skip.
"""

from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import atalaia_controller  # noqa: E402,F401  (puts the simulator on the path)
from atalaia_sim.core import Core, find_library  # noqa: E402
from atalaia_sim.packet import Header, packet_decrypt, packet_encrypt, vf_make  # noqa: E402
from atalaia_sim.protocol import MESSAGE_TYPES  # noqa: E402

from atalaia_controller import modem_framing as mf  # noqa: E402
from atalaia_controller.config import Config  # noqa: E402

REQUIRE_ALL = os.environ.get("ATALAIA_REQUIRE_ALL") == "1"

# The link and engine log every reconnect; the tests check behaviour, not log lines.
logging.getLogger("atalaia").setLevel(logging.ERROR)


def _missing(what: str) -> None:
    if REQUIRE_ALL:
        raise RuntimeError(f"ATALAIA_REQUIRE_ALL=1 but {what}")


def load_core() -> Optional[Core]:
    try:
        return Core(find_library())
    except (FileNotFoundError, OSError):
        _missing("the core library is not built (set ATALAIA_CORE_LIB)")
        return None


CORE = load_core()

MODEM_HOST = os.environ.get("ATALAIA_MODEM_HOST", "")
if not MODEM_HOST or not Path(MODEM_HOST).is_file():
    _missing("the host modem is not built (set ATALAIA_MODEM_HOST; see tools/check.sh)")
    MODEM_HOST = ""

MOSQUITTO = shutil.which("mosquitto") or ("/usr/sbin/mosquitto" if Path("/usr/sbin/mosquitto").exists() else "")
if not MOSQUITTO:
    _missing("mosquitto is not installed")


def config(tmp: str, **overrides) -> Config:
    cfg = Config(db_path=os.path.join(tmp, "controller.db"), gm_token="gm-secret",
                 read_token="read-secret", mqtt_enabled=False, tick_interval_s=0.02,
                 ping_interval_s=0.2)
    for k, v in overrides.items():
        setattr(cfg, k, v)
    cfg.validate()
    return cfg


def free_port(kind: int = socket.SOCK_STREAM) -> int:
    with socket.socket(socket.AF_INET, kind) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(predicate, timeout: float = 5.0, step: float = 0.01) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(step)
    return predicate()


def node_packet(key: bytes, game_id: int, source: int, seq: int, epoch: int, msg_type: str,
                payload: bytes, prio: int = 1, ack: bool = False, hop: int = 2) -> bytes:
    """A packet as a box would put it on air (Python codec, real AES-CCM)."""
    hdr = Header(vf_make(1, prio, ack, True), game_id, source, seq, hop, MESSAGE_TYPES[msg_type])
    return packet_encrypt(hdr, epoch, key, payload)


class HostModem:
    """The C host modem (firmware/esp32/test/modem_host) with a UDP 'air'."""

    def __init__(self, serial_port: int = 0, *args: str) -> None:
        if not MODEM_HOST:
            raise unittest_skip("host modem not built")
        self.air = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.air.bind(("127.0.0.1", 0))
        self.air.settimeout(2.0)
        self.peer_port = self.air.getsockname()[1]
        self.args = list(args)
        self.serial_port = serial_port
        self.proc: Optional[subprocess.Popen] = None
        self.start()

    def start(self) -> None:
        self.proc = subprocess.Popen(
            [MODEM_HOST, "--serial-port", str(self.serial_port), "--air-peer", str(self.peer_port),
             *self.args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        line = self.proc.stdout.readline().split()
        if not line or line[0] != "READY":
            raise RuntimeError(f"host modem did not start: {self.proc.stderr.read()}")
        fields = dict(part.split("=") for part in line[1:])
        self.serial_port = int(fields["serial"])
        self.air_port = int(fields["air"])

    @property
    def url(self) -> str:
        return f"socket://127.0.0.1:{self.serial_port}"

    def kill(self) -> None:
        if self.proc is not None:
            self.proc.kill()
            self.proc.wait(timeout=5)
            self.proc.stdout.close()
            self.proc.stderr.close()
            self.proc = None

    def close(self) -> None:
        self.kill()
        self.air.close()

    def hear(self, packet: bytes) -> None:
        """A packet arrives over the air at the modem."""
        self.air.sendto(packet, ("127.0.0.1", self.air_port))

    def transmitted(self, timeout: float = 2.0) -> bytes:
        """The next packet the modem put on air."""
        self.air.settimeout(timeout)
        data, _ = self.air.recvfrom(512)
        return data

    def transmitted_all(self, quiet: float = 0.3) -> list[bytes]:
        out = []
        while True:
            try:
                out.append(self.transmitted(quiet))
            except socket.timeout:
                return out


def unittest_skip(reason: str) -> Exception:
    import unittest
    return unittest.SkipTest(reason)


class Mosquitto:
    """A private mosquitto broker on a free port."""

    def __init__(self, port: int = 0) -> None:
        if not MOSQUITTO:
            raise unittest_skip("mosquitto not installed")
        self.dir = tempfile.mkdtemp()
        self.port = port or free_port()
        conf = Path(self.dir) / "mosquitto.conf"
        conf.write_text(f"listener {self.port} 127.0.0.1\nallow_anonymous true\npersistence false\n")
        self.proc = subprocess.Popen([MOSQUITTO, "-c", str(conf)], stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        if not wait_for(self._listening, 5):
            self.close()
            raise RuntimeError("mosquitto did not start")

    def _listening(self) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=0.2):
                return True
        except OSError:
            return False

    def close(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        shutil.rmtree(self.dir, ignore_errors=True)


class FakeSerial:
    """A scripted modem on the other end of a fake serial port (for watchdog tests).

    It answers PING with STATUS and IDENT with IDENT unless ``mute`` is set,
    and records every frame the controller sends.
    """

    def __init__(self, mute: bool = False) -> None:
        self.mute = mute
        self.decoder = mf.FrameDecoder()
        self.received: list[tuple[int, bytes]] = []
        self._out = bytearray()
        self._cond = threading.Condition()
        self.closed = False

    def write(self, data: bytes) -> int:
        if self.closed:
            raise OSError("port closed")
        for frame_type, payload in self.decoder.feed(data):
            with self._cond:
                self.received.append((frame_type, payload))
            if self.mute or frame_type != mf.CMD:
                continue
            op = payload[0]
            if op == mf.CMD_PING:
                token = int.from_bytes(payload[1:5], "big")
                self.push(mf.STATUS, f'{{"cmd":1,"configured":false,"ping":{token}}}'.encode())
            elif op == mf.CMD_IDENT:
                self.push(mf.IDENT, b'{"fw":"atalaia-modem","fw_version":"fake"}')
        return len(data)

    def push(self, frame_type: int, payload: bytes) -> None:
        with self._cond:
            self._out.extend(mf.encode_frame(frame_type, payload))
            self._cond.notify_all()

    def push_raw(self, data: bytes) -> None:
        with self._cond:
            self._out.extend(data)
            self._cond.notify_all()

    def read(self, n: int) -> bytes:
        with self._cond:
            if not self._out:
                self._cond.wait(0.02)
            if self.closed:
                raise OSError("port closed")
            data = bytes(self._out[:n])
            del self._out[:n]
            return data

    def close(self) -> None:
        self.closed = True

    def frames(self, frame_type: int, op: Optional[int] = None) -> list[bytes]:
        with self._cond:
            return [p for t, p in self.received if t == frame_type and (op is None or p[:1] == bytes([op]))]


class FakeModem:
    """Stands in for RadioModem in engine and API tests: records what the engine sends."""

    def __init__(self, up: bool = True) -> None:
        from atalaia_sim.packet import header_decode  # noqa: F401
        self.state = "up" if up else "down"
        self.ident = {"fw": "atalaia-modem", "fw_version": "fake"}
        self.status = {"configured": True}
        self.reconnects = 0
        self.sent: list[tuple[Header, bytes]] = []
        self.configured: list[tuple] = []
        self.cleared = 0
        self.peers: dict[int, int] = {}
        self.on_rx = self.on_tx_ack = self.on_state = self.on_error = None

    @property
    def is_up(self) -> bool:
        return self.state == "up"

    def configure(self, *args) -> None:
        self.configured.append(args)

    def clear(self) -> None:
        self.cleared += 1

    def set_peer_epochs(self, epochs: dict[int, int]) -> None:
        self.peers.update(epochs)

    def send_packet(self, header: Header, payload: bytes) -> bool:
        if not self.is_up:
            return False
        self.sent.append((header, payload))
        return True

    def of(self, msg_type: str) -> list[tuple[Header, bytes]]:
        return [(h, p) for h, p in self.sent if h.type == MESSAGE_TYPES[msg_type]]

    def rx(self, source: int, seq: int, msg_type: str, payload: bytes, *, game_id: int,
           epoch: int = 0, ack: bool = False, rssi: int = -60, snr: int = 5) -> None:
        """A packet the modem heard, as its RX frame reaches the engine."""
        hdr = Header(vf_make(1, 1, ack, True), game_id, source, seq, 2, MESSAGE_TYPES[msg_type])
        from atalaia_sim.packet import header_encode
        self.on_rx(mf.RxPacket(hdr, header_encode(hdr), payload, rssi, snr, epoch))


__all__ = ["FakeModem","CORE", "Config", "HostModem", "Mosquitto", "FakeSerial", "config", "free_port",
           "node_packet", "packet_decrypt", "wait_for", "REQUIRE_ALL", "MESSAGE_TYPES"]
