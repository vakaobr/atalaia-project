# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The USB radio modem link (ADR-P2-4): frames over pyserial, watchdog and reconnect.

One worker thread owns the port. It reads frames and hands them to the
callbacks, pings the modem every ``ping_interval`` seconds, and when
``max_missed`` pings go unanswered (or the port fails) it closes and
reopens the port, asks for IDENT and sends the game configuration again.
After ``reconnect_attempts`` failed reconnects the link is "down" (the
controller reports radio.down) and it keeps retrying every
``retry_interval`` seconds; when the modem answers again it is "up".

The port is anything pyserial's serial_for_url opens: /dev/ttyACM0 on the
Raspberry Pi, or socket://127.0.0.1:PORT for the host modem in the tests.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable, Optional

from atalaia_sim.packet import header_encode, Header

from . import modem_framing as mf

log = logging.getLogger("atalaia.modem")

CLOSED = "closed"
CONNECTING = "connecting"
UP = "up"
DOWN = "down"


def open_serial(url: str, baudrate: int, timeout: float):
    """Opens a port without toggling DTR/RTS, which would reset an ESP32-S3."""
    import serial  # pyserial

    port = serial.serial_for_url(url, do_not_open=True, baudrate=baudrate, timeout=timeout)
    try:
        port.dtr = False
        port.rts = False
    except (AttributeError, ValueError, OSError):
        pass
    port.open()
    return port


class RadioModem:
    def __init__(
        self,
        url: str,
        *,
        baudrate: int = 921_600,
        ping_interval: float = 5.0,
        max_missed: int = 3,
        reconnect_attempts: int = 3,
        retry_interval: float = 10.0,
        read_timeout: float = 0.05,
        serial_factory: Optional[Callable[[], Any]] = None,
        on_rx: Optional[Callable[[mf.RxPacket], None]] = None,
        on_tx_ack: Optional[Callable[[int, str], None]] = None,
        on_state: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self.url = url
        self.ping_interval = ping_interval
        self.max_missed = max_missed
        self.reconnect_attempts = reconnect_attempts
        self.retry_interval = retry_interval
        self._factory = serial_factory or (lambda: open_serial(url, baudrate, read_timeout))
        self.on_rx = on_rx
        self.on_tx_ack = on_tx_ack
        self.on_state = on_state
        self.on_error = on_error

        self.state = CLOSED
        self.ident: Optional[dict[str, Any]] = None
        self.status: Optional[dict[str, Any]] = None
        self.reconnects = 0
        self.decoder = mf.FrameDecoder()

        self._port: Any = None
        self._write_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._config: Optional[bytes] = None
        self._peers: dict[int, int] = {}
        self._ping_token = 0
        self._pending_ping: Optional[int] = None
        self._missed = 0
        self._next_ping = 0.0
        self._up_event = threading.Event()

    # --- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="radio-modem", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._close()
        self._set_state(CLOSED)

    def wait_up(self, timeout: float) -> bool:
        return self._up_event.wait(timeout)

    @property
    def is_up(self) -> bool:
        return self.state == UP

    # --- commands ---------------------------------------------------------------

    def configure(self, game_id: int, node_id: int, epoch: int, max_hops: int, channel_hz: int,
                  key: bytes) -> None:
        """Gives the modem the game (kept and sent again after every reconnect)."""
        self._config = mf.configure_payload(game_id, node_id, epoch, max_hops, channel_hz, key)
        self._peers = {}
        self._write(mf.CMD, self._config)

    def clear(self) -> None:
        """Ends the game on the modem: it forgets the key."""
        self._config = None
        self._peers = {}
        self._write(mf.CMD, bytes([mf.CMD_CLEAR]))

    def set_peer_epochs(self, epochs: dict[int, int]) -> None:
        """Tells the modem each box's last known epoch (also resent after a reconnect)."""
        self._peers.update(epochs)
        pairs = sorted(epochs.items())
        for i in range(0, len(pairs), 60):  # 60 pairs = 241 bytes, under the 256-byte limit
            self._write(mf.CMD, mf.peer_epoch_payload(pairs[i:i + 60]))

    def send_packet(self, header: Header, payload: bytes) -> bool:
        """Queues a TX frame: the modem encrypts and transmits it. False if the link is not up."""
        if self.state != UP:
            return False
        return self._write(mf.TX, mf.tx_payload(header_encode(header), payload))

    # --- internals --------------------------------------------------------------

    def _set_state(self, state: str) -> None:
        if state == self.state:
            return
        self.state = state
        if state == UP:
            self._up_event.set()
        else:
            self._up_event.clear()
        log.info("modem link %s", state)
        if self.on_state:
            try:
                self.on_state(state)
            except Exception:  # a callback must not kill the link
                log.exception("modem state callback failed")

    def _write(self, frame_type: int, payload: bytes) -> bool:
        frame = mf.encode_frame(frame_type, payload)
        with self._write_lock:
            port = self._port
            if port is None:
                return False
            try:
                port.write(frame)
                return True
            except Exception as exc:  # serial.SerialException, OSError
                log.warning("modem write failed: %s", exc)
                self._port_failed = True
                return False

    def _close(self) -> None:
        with self._write_lock:
            port, self._port = self._port, None
        if port is not None:
            try:
                port.close()
            except Exception:
                pass

    def _open(self) -> bool:
        try:
            port = self._factory()
        except Exception as exc:
            log.warning("cannot open the modem at %s: %s", self.url, exc)
            return False
        with self._write_lock:
            self._port = port
        self._port_failed = False
        self.decoder = mf.FrameDecoder()
        self._missed = 0
        self._pending_ping = None
        self._next_ping = time.monotonic()  # ping at once: the reply proves the modem is there
        self._write(mf.CMD, bytes([mf.CMD_IDENT]))
        if self._config is not None:
            self._write(mf.CMD, self._config)
            if self._peers:
                pairs = sorted(self._peers.items())
                for i in range(0, len(pairs), 60):
                    self._write(mf.CMD, mf.peer_epoch_payload(pairs[i:i + 60]))
        return True

    def _connect(self, attempts: int) -> bool:
        for attempt in range(attempts):
            if self._stop.is_set():
                return False
            if self._open():
                return True
            self._stop.wait(min(1.0 * (attempt + 1), self.retry_interval))
        return False

    def _run(self) -> None:
        self._port_failed = False
        self._set_state(CONNECTING)
        while not self._stop.is_set():
            if self._port is None:
                if not self._connect(self.reconnect_attempts):
                    if self._stop.is_set():
                        break
                    self._set_state(DOWN)
                    self._stop.wait(self.retry_interval)
                    continue
            self._serve()
            # _serve returns when the link failed; reconnect.
            self._close()
            if self._stop.is_set():
                break
            self.reconnects += 1
            if self.state == UP:
                self._set_state(CONNECTING)
            log.warning("modem link lost; reconnecting")

    def _serve(self) -> None:
        """Reads frames and pings until the port fails or pings go unanswered."""
        while not self._stop.is_set():
            now = time.monotonic()
            if now >= self._next_ping:
                if self._pending_ping is not None:
                    self._missed += 1
                    log.warning("modem missed ping %d of %d", self._missed, self.max_missed)
                    if self._missed >= self.max_missed:
                        return
                self._ping_token = (self._ping_token + 1) & 0xFFFFFFFF
                self._pending_ping = self._ping_token
                self._write(mf.CMD, mf.ping_payload(self._ping_token))
                self._next_ping = now + self.ping_interval
            port = self._port
            if port is None or self._port_failed:
                return
            try:
                data = port.read(512)
            except Exception as exc:
                log.warning("modem read failed: %s", exc)
                return
            if data:
                for frame_type, payload in self.decoder.feed(data):
                    self._dispatch(frame_type, payload)

    def _dispatch(self, frame_type: int, payload: bytes) -> None:
        try:
            if frame_type == mf.RX:
                rx = mf.decode_rx(payload)
                if self.on_rx:
                    self.on_rx(rx)
            elif frame_type == mf.TX_ACK:
                seq, status = mf.decode_tx_ack(payload)
                if self.on_tx_ack:
                    self.on_tx_ack(seq, status)
            elif frame_type == mf.STATUS:
                self.status = json.loads(payload.decode("utf-8"))
                if self.status.get("ping") == self._pending_ping:
                    self._pending_ping = None
                    self._missed = 0
                    self._set_state(UP)
            elif frame_type == mf.IDENT:
                self.ident = json.loads(payload.decode("utf-8"))
                log.info("modem: %s", self.ident)
            elif frame_type == mf.ERROR:
                code, message = mf.decode_error(payload)
                log.warning("modem error %s: %s", code, message)
                if self.on_error:
                    self.on_error(code, message)
            else:
                log.warning("unexpected frame type 0x%02x from the modem", frame_type)
        except (ValueError, UnicodeDecodeError) as exc:
            log.warning("bad frame 0x%02x from the modem: %s", frame_type, exc)
        except Exception:
            log.exception("modem frame handler failed")
