# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A small WebSocket client (RFC 6455) on the standard library, for the site server's stream.

The remote GM (``remote_gm.py``, plan phase 19) keeps one WebSocket open to the
site server's ``WS /api/v1/sync/stream``. The controller's packaged
``websockets`` (10.4 on Ubuntu 24.04 and Raspberry Pi OS) has no client that
fits a plain thread, and the site server's test image has no ``websockets`` at
all, so this module speaks the protocol itself (decision S19-2): text messages
only, no extensions, client frames masked (RFC 6455 section 5.3), the server's
frames never masked, pings answered with pongs, a message at most 1 MiB.

The connection follows the sync's own rules (protocol/sync.md): ``wss://`` with
the site server's certificate checked against the system's CAs or the sync's CA
file, ``ws://`` only to this machine, the API key in ``Authorization: Bearer``,
no redirect followed (anything but ``101 Switching Protocols`` is a refusal).
"""

from __future__ import annotations

import base64
import hashlib
import os
import socket
import ssl
import struct
import time
from typing import Optional
from urllib.parse import urlsplit

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"  # RFC 6455 section 1.3
MAX_MESSAGE = 1024 * 1024
MAX_HEADERS = 16 * 1024
OP_CONT, OP_TEXT, OP_BINARY, OP_CLOSE, OP_PING, OP_PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA


class WsError(Exception):
    """The connection failed or broke: ``code`` is the close code (4401: the API key was refused), or None;
    ``status`` the HTTP status of a refused upgrade."""

    def __init__(self, message: str, code: Optional[int] = None, status: Optional[int] = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def accept_key(key: str) -> str:
    """The ``Sec-WebSocket-Accept`` a server must answer for ``key`` (RFC 6455 section 4.2.2)."""
    return base64.b64encode(hashlib.sha1((key + GUID).encode("ascii")).digest()).decode("ascii")


def mask(payload: bytes, key: bytes) -> bytes:
    """XOR with the 4-byte masking key (RFC 6455 section 5.3); its own inverse."""
    if not payload:
        return b""
    n = len(payload)
    whole = (key * (n // 4 + 1))[:n]
    return (int.from_bytes(payload, "big") ^ int.from_bytes(whole, "big")).to_bytes(n, "big")


def encode_frame(opcode: int, payload: bytes, mask_key: Optional[bytes] = None) -> bytes:
    """One final frame; masked when ``mask_key`` is given (a client's frames always are)."""
    head = bytes([0x80 | opcode])
    flag = 0x80 if mask_key is not None else 0
    n = len(payload)
    if n < 126:
        head += bytes([flag | n])
    elif n < 1 << 16:
        head += bytes([flag | 126]) + struct.pack("!H", n)
    else:
        head += bytes([flag | 127]) + struct.pack("!Q", n)
    if mask_key is None:
        return head + payload
    return head + mask_key + mask(payload, mask_key)


class WebSocket:
    """One client connection; not thread-safe (the remote GM's thread is its only user)."""

    def __init__(self, sock: socket.socket, leftover: bytes = b"") -> None:
        self._sock = sock
        self._buf = bytearray(leftover)
        self._parts: list[bytes] = []
        self._opcode: Optional[int] = None
        self.closed = False

    @classmethod
    def connect(cls, url: str, headers: dict[str, str], *, ca_file: str = "", timeout_s: float = 15.0,
                context: Optional[ssl.SSLContext] = None) -> "WebSocket":
        parts = urlsplit(url)
        if parts.scheme not in ("wss", "ws") or not parts.hostname:
            raise WsError(f"not a WebSocket address: {url}")
        host = parts.hostname
        port = parts.port or (443 if parts.scheme == "wss" else 80)
        sock = socket.create_connection((host, port), timeout=timeout_s)
        try:
            if parts.scheme == "wss":
                if context is None:
                    context = ssl.create_default_context(cafile=ca_file or None)
                    context.minimum_version = ssl.TLSVersion.TLSv1_2
                sock = context.wrap_socket(sock, server_hostname=host)
            key = base64.b64encode(os.urandom(16)).decode("ascii")
            netloc = host if ":" not in host else f"[{host}]"
            if parts.port:
                netloc += f":{parts.port}"
            lines = [f"GET {parts.path or '/'} HTTP/1.1", f"Host: {netloc}", "Upgrade: websocket",
                     "Connection: Upgrade", f"Sec-WebSocket-Key: {key}", "Sec-WebSocket-Version: 13"]
            lines += [f"{k}: {v}" for k, v in headers.items()]
            sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1"))
            raw = b""
            deadline = time.monotonic() + timeout_s
            while b"\r\n\r\n" not in raw:
                if len(raw) > MAX_HEADERS or time.monotonic() > deadline:
                    raise WsError("the upgrade's answer is too long or too slow")
                chunk = sock.recv(4096)
                if not chunk:
                    raise WsError("the server closed the connection during the upgrade")
                raw += chunk
            head, _, leftover = raw.partition(b"\r\n\r\n")
            status_line, *header_lines = head.decode("latin-1").split("\r\n")
            fields = status_line.split(" ", 2)
            status = int(fields[1]) if len(fields) > 1 and fields[1].isdigit() else 0
            if status != 101:
                raise WsError(f"the server refused the upgrade (HTTP {status})", status=status)
            got = {}
            for line in header_lines:
                name, _, value = line.partition(":")
                got[name.strip().lower()] = value.strip()
            if got.get("upgrade", "").lower() != "websocket" or "upgrade" not in got.get("connection", "").lower():
                raise WsError("the server's answer is not a WebSocket upgrade")
            if got.get("sec-websocket-accept") != accept_key(key):
                raise WsError("the server's Sec-WebSocket-Accept does not match")
            if got.get("sec-websocket-extensions"):
                raise WsError("the server chose an extension the client did not offer")
            return cls(sock, leftover)
        except BaseException:
            sock.close()
            raise

    # --- sending -------------------------------------------------------------------------

    def _send(self, opcode: int, payload: bytes) -> None:
        if self.closed:
            raise WsError("the connection is closed")
        try:
            self._sock.sendall(encode_frame(opcode, payload, os.urandom(4)))
        except OSError as exc:
            self.closed = True
            raise WsError(f"send failed: {exc}") from None

    def send_text(self, text: str) -> None:
        data = text.encode("utf-8")
        if len(data) > MAX_MESSAGE:
            raise WsError("message too large")
        self._send(OP_TEXT, data)

    def close(self, code: int = 1000) -> None:
        if self.closed:
            return
        try:
            self._sock.sendall(encode_frame(OP_CLOSE, struct.pack("!H", code), os.urandom(4)))
        except OSError:
            pass
        self.closed = True
        try:
            self._sock.close()
        except OSError:
            pass

    # --- receiving -----------------------------------------------------------------------

    def _frame(self) -> Optional[tuple[bool, int, bytes]]:
        """One whole frame from the buffer, or None when it is not all here yet."""
        buf = self._buf
        if len(buf) < 2:
            return None
        b0, b1 = buf[0], buf[1]
        if b0 & 0x70:
            raise self._fail(1002, "a reserved bit is set (no extension was negotiated)")
        if b1 & 0x80:
            raise self._fail(1002, "the server masked a frame")
        n, at = b1 & 0x7F, 2
        if n == 126:
            if len(buf) < 4:
                return None
            n, at = struct.unpack("!H", buf[2:4])[0], 4
        elif n == 127:
            if len(buf) < 10:
                return None
            n, at = struct.unpack("!Q", buf[2:10])[0], 10
        if n > MAX_MESSAGE:
            raise self._fail(1009, "frame too large")
        if len(buf) < at + n:
            return None
        payload = bytes(buf[at:at + n])
        del buf[:at + n]
        return bool(b0 & 0x80), b0 & 0x0F, payload

    def _fail(self, code: int, why: str) -> WsError:
        self.close(code)
        return WsError(why, code=code)

    def recv(self, timeout_s: float) -> Optional[str]:
        """The next text message, or None if none came within ``timeout_s``. Pings are answered on the way."""
        deadline = time.monotonic() + max(timeout_s, 0.0)
        while True:
            frame = self._frame()
            if frame is None:
                left = deadline - time.monotonic()
                if left <= 0:
                    return None
                self._sock.settimeout(left)
                try:
                    chunk = self._sock.recv(65536)
                except (socket.timeout, TimeoutError):
                    return None
                except ssl.SSLWantReadError:
                    continue
                except OSError as exc:
                    self.closed = True
                    raise WsError(f"receive failed: {exc}") from None
                if not chunk:
                    self.closed = True
                    raise WsError("the server closed the connection")
                self._buf += chunk
                continue
            fin, opcode, payload = frame
            if opcode == OP_PING:
                self._send(OP_PONG, payload)
            elif opcode == OP_PONG:
                pass
            elif opcode == OP_CLOSE:
                code = struct.unpack("!H", payload[:2])[0] if len(payload) >= 2 else None
                self.close(code if code in (1000, 1001) else 1000)
                raise WsError(f"the server closed the stream (code {code})", code=code)
            elif opcode == OP_BINARY or (opcode == OP_TEXT and self._opcode is not None):
                raise self._fail(1003 if opcode == OP_BINARY else 1002, "unexpected frame")
            elif opcode in (OP_TEXT, OP_CONT):
                if opcode == OP_CONT and self._opcode is None:
                    raise self._fail(1002, "a continuation with no message")
                self._opcode = OP_TEXT
                self._parts.append(payload)
                if sum(len(p) for p in self._parts) > MAX_MESSAGE:
                    raise self._fail(1009, "message too large")
                if fin:
                    data, self._parts, self._opcode = b"".join(self._parts), [], None
                    try:
                        return data.decode("utf-8")
                    except UnicodeDecodeError:
                        raise self._fail(1007, "a text message that is not UTF-8") from None
            else:
                raise self._fail(1002, f"unknown opcode {opcode}")
