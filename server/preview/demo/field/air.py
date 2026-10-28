# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The demo's simulated radio side: a UDP "air" shared by the C host modem and the C host boxes.

These are the programs the controller's end-to-end tests use (firmware/esp32/test/modem_host and box_host): the
Field Box firmware's own game and radio code, with the real core and AES-CCM, on Linux. The "air" is UDP on
127.0.0.1; there is no radio, no serial device and no hardware here.
"""

from __future__ import annotations

import socket
import subprocess
import threading
import time
from typing import Optional


class AirHub:
    """What one radio channel does: every datagram a member sends is handed to every other member."""

    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.05)
        self.port = self.sock.getsockname()[1]
        self.members: list[int] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="air")
        self._thread.start()

    def add(self, air_port: int) -> None:
        with self._lock:
            self.members.append(air_port)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                data, addr = self.sock.recvfrom(512)
            except socket.timeout:
                continue
            except OSError:
                return
            with self._lock:
                targets = [p for p in self.members if p != addr[1]]
            for port in targets:
                self.sock.sendto(data, ("127.0.0.1", port))

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        self.sock.close()


def _drain(stream) -> None:
    """Reads a child's output until it closes, so a full pipe never stops it."""
    for _ in stream:
        pass


class HostModem:
    """The C host modem: the controller reaches it as socket://127.0.0.1:<serial_port> (pyserial)."""

    def __init__(self, binary: str, hub: AirHub) -> None:
        self.proc = subprocess.Popen([binary, "--serial-port", "0", "--air-peer", str(hub.port)],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        line = self.proc.stdout.readline().split()
        if not line or line[0] != "READY":
            raise RuntimeError("the host modem did not start")
        fields = dict(part.split("=") for part in line[1:])
        self.serial_port = int(fields["serial"])
        self.air_port = int(fields["air"])
        hub.add(self.air_port)
        threading.Thread(target=_drain, args=(self.proc.stdout,), daemon=True).start()

    @property
    def url(self) -> str:
        return f"socket://127.0.0.1:{self.serial_port}"


class HostBox:
    """The C host box: one simulated Field Box. Its serial console and buttons are lines on stdin."""

    def __init__(self, binary: str, hub: AirHub, state_dir: str, modes_dir: str, join_key_hex: str, name: str,
                 state_ms: int = 2000) -> None:
        self.name = name
        self.lines: list[str] = []  # the last KEEP lines it printed
        self.dropped = 0            # lines that fell off the front of ``lines``
        self._cond = threading.Condition()
        self.proc = subprocess.Popen(
            [binary, "--state-dir", state_dir, "--modes", modes_dir, "--air-peer", str(hub.port),
             "--join-key", join_key_hex, "--state-ms", str(state_ms), "--name", name],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError(f"the host box {name} did not start")
            if line.startswith("READY "):
                break
        self.air_port = int(line.split()[1].split("=")[1])
        hub.add(self.air_port)
        threading.Thread(target=self._read, daemon=True).start()

    KEEP = 400

    def _read(self) -> None:
        for line in self.proc.stdout:
            with self._cond:
                self.lines.append(line.rstrip("\n"))
                if len(self.lines) > self.KEEP:
                    del self.lines[0]
                    self.dropped += 1
                self._cond.notify_all()

    def alive(self) -> bool:
        return self.proc.poll() is None

    def send(self, line: str) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()

    def join(self, text: str) -> None:
        self.send("@join " + text)

    def hold(self, button: int, ms: int) -> None:
        self.send(f"hold {button} {ms}")

    def mark(self) -> int:
        """A position in the output, for wait_for: only lines printed after it count."""
        with self._cond:
            return self.dropped + len(self.lines)

    def _seen(self, needle: str, since: int) -> bool:
        return any(needle in line for line in self.lines[max(0, since - self.dropped):])

    def wait_for(self, needle: str, timeout: float, since: int = 0) -> bool:
        end = time.monotonic() + timeout
        with self._cond:
            while time.monotonic() < end:
                if self._seen(needle, since):
                    return True
                self._cond.wait(0.1)
            return self._seen(needle, since)
