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

BOX_HOST = os.environ.get("ATALAIA_BOX_HOST", "")
if not BOX_HOST or not Path(BOX_HOST).is_file():
    _missing("the host box is not built (set ATALAIA_BOX_HOST; see tools/check.sh)")
    BOX_HOST = ""

POD_HOST = os.environ.get("ATALAIA_POD_HOST", "")
if not POD_HOST or not Path(POD_HOST).is_file():
    _missing("the host pod is not built (set ATALAIA_POD_HOST; see tools/check.sh)")
    POD_HOST = ""

REPO = HERE.parents[1]

MOSQUITTO = shutil.which("mosquitto") or ("/usr/sbin/mosquitto" if Path("/usr/sbin/mosquitto").exists() else "")
if not MOSQUITTO:
    _missing("mosquitto is not installed")


def config(tmp: str, **overrides) -> Config:
    cfg = Config(db_path=os.path.join(tmp, "controller.db"), gm_token="gm-secret",
                 read_token="read-secret", mqtt_enabled=False, tick_interval_s=0.02,
                 ping_interval_s=0.2, controller_pace_ms=0)  # SL-13: the older tests send in bursts; test_tx_pacing.py and the contract cases set it
    for k, v in overrides.items():
        setattr(cfg, k, v)
    cfg.validate()
    return cfg


def free_port(kind: int = socket.SOCK_STREAM) -> int:
    with socket.socket(socket.AF_INET, kind) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


WAIT_FLOOR_S = 20.0  # a full verification runs six suites at once: a C host modem can stall for seconds


def wait_for(predicate, timeout: float = 5.0, step: float = 0.01) -> bool:
    """Waits until predicate() holds, at least WAIT_FLOOR_S: every caller waits for something that should
    happen (none uses it to show that something does not), so a longer deadline only costs time when a
    test is failing anyway. test_engine_scan_over_the_c_modem missed its 3 s under load (2026-10-26)."""
    end = time.monotonic() + max(timeout, WAIT_FLOOR_S)
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

    def __init__(self, serial_port: int = 0, *args: str, hub: Optional["AirHub"] = None) -> None:
        if not MODEM_HOST:
            raise unittest_skip("host modem not built")
        self.air = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.air.bind(("127.0.0.1", 0))
        self.air.settimeout(2.0)
        # With a hub the modem transmits to the hub, which shares the air with others.
        self.peer_port = hub.port if hub is not None else self.air.getsockname()[1]
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


class AirHub:
    """A shared 'air' for several host programs (modems, host boxes): UDP broadcast.

    Every program sends what it transmits to the hub's port; the hub hands
    each datagram to every other registered program, as a radio channel
    does. ``drop`` (a predicate on the datagram) simulates lost packets, and
    ``heard`` keeps everything that went on air.
    """

    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.05)
        self.port = self.sock.getsockname()[1]
        self.members: list[int] = []
        self.heard: list[tuple[int, bytes]] = []
        self.drop = None
        self.blocked: set[tuple[int, int]] = set()  # (from, to): out of radio range
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def add(self, air_port: int) -> None:
        with self._lock:
            self.members.append(air_port)

    def block(self, a: int, b: int) -> None:
        """a and b cannot hear each other (both directions)."""
        with self._lock:
            self.blocked.update({(a, b), (b, a)})

    def remove(self, air_port: int) -> None:
        with self._lock:
            if air_port in self.members:
                self.members.remove(air_port)

    def send(self, packet: bytes, from_port: int = 0) -> None:
        """A packet put on air by something that is not a member (a test playing a box)."""
        self._deliver(packet, from_port)

    def _deliver(self, packet: bytes, from_port: int) -> None:
        with self._lock:
            self.heard.append((from_port, packet))
            targets = [p for p in self.members if p != from_port and (from_port, p) not in self.blocked]
            drop = self.drop
        if drop is not None and drop(packet):
            return
        for port in targets:
            self.sock.sendto(packet, ("127.0.0.1", port))

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                data, addr = self.sock.recvfrom(512)
            except socket.timeout:
                continue
            except OSError:
                return
            self._deliver(data, addr[1])

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        self.sock.close()


class BoxHost:
    """The C host box (firmware/esp32/test/box_host): a Field Box's game and radio logic.

    It shares the hub's air with modems and other boxes. Its NVS and flash
    are files in ``state_dir``, so ``kill()`` then ``start()`` is a battery
    pull. Lines it prints are kept in ``lines``.
    """

    def __init__(self, hub: AirHub, state_dir: str, join_key: bytes, *, state_ms: int = 500,
                 name: str = "box", extra: tuple[str, ...] = ()) -> None:
        if not BOX_HOST:
            raise unittest_skip("host box not built")
        self.hub = hub
        self.state_dir = state_dir
        self.join_key = join_key
        self.state_ms = state_ms
        self.name = name
        self.extra = tuple(extra)  # more box_host options (--as-box VERSION, --release-keys HEX)
        self.lines: list[str] = []
        self.proc: Optional[subprocess.Popen] = None
        self.air_port = 0
        self._cond = threading.Condition()
        self.start()

    def start(self) -> None:
        self.proc = subprocess.Popen(
            [BOX_HOST, "--state-dir", self.state_dir, "--modes", str(REPO / "modes"),
             "--air-peer", str(self.hub.port),
             # No key: an unadopted box (protocol/adoption.md), e.g. to pair it by its code.
             *(["--join-key", self.join_key.hex()] if self.join_key else []),
             "--state-ms", str(self.state_ms), "--name", self.name, *self.extra],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        # A box that rejoins a stored game logs that before it is READY.
        while True:
            line = self.proc.stdout.readline()
            if not line:
                self.proc.wait(timeout=5)
                raise RuntimeError(f"host box did not start: {self.proc.stderr.read()}")
            if line.startswith("READY "):
                break
            self.lines.append(line.rstrip("\n"))
        self.air_port = int(line.split()[1].split("=")[1])
        self.hub.add(self.air_port)
        threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()

    def _read(self, proc: subprocess.Popen) -> None:
        for line in proc.stdout:
            with self._cond:
                self.lines.append(line.rstrip("\n"))
                self._cond.notify_all()

    def send(self, line: str) -> None:
        assert self.proc is not None and self.proc.stdin is not None
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()

    def join(self, text: str) -> None:
        self.send("@join " + text)

    def hold(self, button: int, ms: int) -> None:
        self.send(f"hold {button} {ms}")

    def logged(self, needle: str) -> bool:
        with self._cond:
            return any(needle in line for line in self.lines)

    def status(self, timeout: float = 3.0) -> dict:
        import json
        with self._cond:
            seen = len(self.lines)
        self.send("status")
        end = time.monotonic() + timeout
        with self._cond:
            while time.monotonic() < end:
                for line in self.lines[seen:]:
                    if line.startswith("STATUS "):
                        return json.loads(line[7:])
                self._cond.wait(0.05)
        raise RuntimeError("the host box did not answer status")

    def kill(self) -> None:
        """A battery pull: no goodbye, no flush beyond what the box already wrote."""
        if self.proc is not None:
            self.hub.remove(self.air_port)
            self.proc.kill()
            self.proc.wait(timeout=5)
            for f in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
                try:
                    f.close()
                except OSError:
                    pass
            self.proc = None

    def close(self) -> None:
        self.kill()


class PodHost:
    """The C host pod (firmware/esp32/test/pod_host): an I/O pod's proxy and radio.

    It shares the hub's air with modems and boxes. ``phone()`` opens its USB
    link (a TCP socket carrying the frames of protocol/capability-proxy.md);
    its hardware is driven with ``send()`` (press, tag, case open...) and what
    it does with its outputs is in ``lines``.
    """

    def __init__(self, hub: Optional[AirHub] = None, *args: str) -> None:
        if not POD_HOST:
            raise unittest_skip("host pod not built")
        self.hub = hub
        self.lines: list[str] = []
        self._cond = threading.Condition()
        cmd = [POD_HOST, *args]
        if hub is not None:
            cmd += ["--air-peer", str(hub.port)]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True)
        line = self.proc.stdout.readline().split()
        if not line or line[0] != "READY":
            raise RuntimeError(f"host pod did not start: {self.proc.stderr.read()}")
        fields = dict(part.split("=") for part in line[1:])
        self.usb_port, self.ble_port = int(fields["usb"]), int(fields["ble"])
        self.air_port = int(fields["air"])
        if hub is not None:
            hub.add(self.air_port)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for line in self.proc.stdout:
            with self._cond:
                self.lines.append(line.rstrip("\n"))
                self._cond.notify_all()

    def send(self, line: str) -> None:
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()

    def logged(self, needle: str) -> bool:
        with self._cond:
            return any(needle in line for line in self.lines)

    def status(self, timeout: float = 3.0) -> dict:
        import json
        with self._cond:
            seen = len(self.lines)
        self.send("status")
        end = time.monotonic() + timeout
        with self._cond:
            while time.monotonic() < end:
                for line in self.lines[seen:]:
                    if line.startswith("STATUS "):
                        return json.loads(line[7:])
                self._cond.wait(0.05)
        raise RuntimeError("the host pod did not answer status")

    def phone(self) -> "PodPhone":
        return PodPhone(self.usb_port)

    def close(self) -> None:
        if self.hub is not None:
            self.hub.remove(self.air_port)
        try:
            self.send("quit")
            self.proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            self.proc.kill()
            self.proc.wait(timeout=5)
        for f in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            try:
                f.close()
            except OSError:
                pass


class PodPhone:
    """A phone's end of a pod's USB link: frames out, frames in (decoded, kept in order)."""

    def __init__(self, port: int) -> None:
        from atalaia_sim import capability_proxy as cp
        self.cp = cp
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.frames: list[tuple[int, bytes]] = []
        self._dec = cp.FrameDecoder()
        self._cond = threading.Condition()
        self._closed = False
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        while True:
            try:
                data = self.sock.recv(4096)
            except OSError:
                return
            if not data:
                return
            with self._cond:
                self.frames += self._dec.feed(data)
                self._cond.notify_all()

    def send(self, frame_type: int, payload: bytes = b"") -> None:
        self.sock.sendall(self.cp.encode_frame(frame_type, payload))

    def wait(self, frame_type: int, match=None, timeout: float = 5.0, start: int = 0):
        """The first frame of frame_type at index >= start whose payload match() accepts."""
        end = time.monotonic() + timeout
        with self._cond:
            while True:
                for i in range(start, len(self.frames)):
                    t, p = self.frames[i]
                    if t == frame_type and (match is None or match(p)):
                        return p
                left = end - time.monotonic()
                if left <= 0:
                    return None
                self._cond.wait(min(left, 0.05))

    def close(self) -> None:
        # shutdown first: it sends the FIN at once and wakes the reader
        # thread's recv (a bare close() can wait for that recv to return).
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()


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
        self.ident = {"fw": "atalaia-modem", "fw_version": "fake", "radio": "sx1262", "measure": True}
        self.status = {"configured": True}
        self.reconnects = 0
        self.sent: list[tuple[Header, bytes]] = []
        self.configured: list[tuple] = []
        self.cleared = 0
        self.peers: dict[int, int] = {}
        self.on_rx = self.on_tx_ack = self.on_state = self.on_error = None
        self.on_field_rx = self.on_field_ack = None
        self.fields: list[bytes] = []             # field frames sent (FIELD_TX)
        self.has_field_frames = True
        self.has_pair_frames = True             # pair frames too (protocol/adoption.md)
        self.channels: list[int] = []             # SET_CHANNEL commands
        self.measured: list[tuple[int, int]] = []  # MEASURE (channel, dwell_ms)
        self.noise: dict[int, tuple[int, int]] = {}  # channel -> (p90 dBm, CAD detections of 10)
        self.measure_gate = None                  # a threading.Event a measurement waits for
        self.can_measure = True

    @property
    def is_up(self) -> bool:
        return self.state == "up"

    def set_channel(self, channel_hz: int) -> bool:
        self.channels.append(channel_hz)
        return True

    def measure(self, channel_hz: int, dwell_ms: int, cad: bool = True, timeout=None) -> "mf.Noise":
        self.measured.append((channel_hz, dwell_ms))
        if self.measure_gate is not None:
            self.measure_gate.wait(5)
        p90, hits = self.noise.get(channel_hz, (-118, 0))
        return mf.Noise(channel_hz, dwell_ms, dwell_ms, p90 - 6, p90 - 3, p90 - 4, p90, p90 + 9,
                        10, hits)

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

    def send_field(self, frame: bytes):
        """A field frame (FIELD_TX): its id, as the modem's FIELD_ACK would carry it."""
        if not self.is_up:
            return None
        self.fields.append(frame)
        return len(self.fields)

    def of(self, msg_type: str) -> list[tuple[Header, bytes]]:
        return [(h, p) for h, p in self.sent if h.type == MESSAGE_TYPES[msg_type]]

    def rx(self, source: int, seq: int, msg_type: str, payload: bytes, *, game_id: int,
           epoch: int = 0, ack: bool = False, rssi: int = -60, snr: int = 5) -> None:
        """A packet the modem heard, as its RX frame reaches the engine."""
        hdr = Header(vf_make(1, 1, ack, True), game_id, source, seq, 2, MESSAGE_TYPES[msg_type])
        from atalaia_sim.packet import header_encode
        self.on_rx(mf.RxPacket(hdr, header_encode(hdr), payload, rssi, snr, epoch))


__all__ = ["AirHub", "BoxHost", "BOX_HOST", "FakeModem", "CORE", "Config", "HostModem", "Mosquitto", "FakeSerial", "config", "free_port",
           "node_packet", "packet_decrypt", "wait_for", "REQUIRE_ALL", "MESSAGE_TYPES"]
