# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A TXT lookup with nothing but the standard library (the hub operator's ``hosted domain verify``; decision PKC-6).

The challenge that proves a field controls its custom host name is a TXT record, and Python's standard library
cannot read one. This asks the machine's own resolver (``/etc/resolv.conf``, or the servers the operator names) for
the TXT records of one name over UDP, and again over TCP when the answer was cut short, and returns each record as
text. It is a few lines of RFC 1035 rather than a new dependency in the hashed requirements; it never follows
anything it was not asked for, and an answer that does not match the question (id, name) is ignored.
"""

from __future__ import annotations

import secrets
import socket
import struct
from pathlib import Path
from typing import Optional, Sequence

TYPE_TXT = 16
CLASS_IN = 1
RESOLV_CONF = Path("/etc/resolv.conf")
MAX_NAME = 253


class DnsError(Exception):
    """The lookup could not be made or answered (not: the name has no TXT record, which is an empty list)."""


def nameservers(path: Path = RESOLV_CONF) -> list[str]:
    """The ``nameserver`` lines of a resolv.conf."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "nameserver":
            out.append(parts[1].split("%", 1)[0])
    return out


def build_query(name: str, qid: int) -> bytes:
    labels = name.rstrip(".").split(".")
    if not name or len(name) > MAX_NAME or any(not 1 <= len(label) <= 63 for label in labels):
        raise DnsError(f"not a DNS name: {name!r}")
    question = b"".join(bytes([len(label)]) + label.encode("ascii") for label in labels) + b"\x00"
    return struct.pack("!HHHHHH", qid, 0x0100, 1, 0, 0, 0) + question + struct.pack("!HH", TYPE_TXT, CLASS_IN)


def _name(data: bytes, offset: int) -> tuple[str, int]:
    """A (possibly compressed) name at ``offset``: the name and the offset just after it in the record."""
    labels: list[str] = []
    end: Optional[int] = None
    jumps = 0
    while True:
        if offset >= len(data):
            raise DnsError("a name runs past the end of the answer")
        length = data[offset]
        if length & 0xC0 == 0xC0:
            if offset + 1 >= len(data):
                raise DnsError("a name runs past the end of the answer")
            if end is None:
                end = offset + 2
            offset = ((length & 0x3F) << 8) | data[offset + 1]
            jumps += 1
            if jumps > 32:
                raise DnsError("a name loops")
            continue
        offset += 1
        if length == 0:
            return ".".join(labels).lower(), end if end is not None else offset
        labels.append(data[offset:offset + length].decode("ascii", "replace"))
        offset += length


def parse_answer(data: bytes, qid: int, name: str) -> tuple[list[str], bool]:
    """(the TXT records of ``name``, whether the answer was truncated) from a response to ``build_query``."""
    if len(data) < 12:
        raise DnsError("the answer is too short")
    rid, flags, qd, an, _, _ = struct.unpack("!HHHHHH", data[:12])
    if rid != qid or not flags & 0x8000:
        raise DnsError("not the answer to this question")
    rcode = flags & 0x000F
    if rcode == 3:
        return [], False  # the name does not exist
    if rcode != 0:
        raise DnsError(f"the resolver answered with error {rcode}")
    offset = 12
    for _ in range(qd):
        _, offset = _name(data, offset)
        offset += 4
    records: list[str] = []
    for _ in range(an):
        owner, offset = _name(data, offset)
        if offset + 10 > len(data):
            raise DnsError("a record runs past the end of the answer")
        rtype, rclass, _, rdlen = struct.unpack("!HHIH", data[offset:offset + 10])
        offset += 10
        rdata = data[offset:offset + rdlen]
        offset += rdlen
        if rtype == TYPE_TXT and rclass == CLASS_IN and owner == name.rstrip(".").lower():
            parts, i = [], 0
            while i < len(rdata):
                n = rdata[i]
                parts.append(rdata[i + 1:i + 1 + n])
                i += 1 + n
            records.append(b"".join(parts).decode("utf-8", "replace"))
    return records, bool(flags & 0x0200)


def _udp(server: str, query: bytes, timeout: float, port: int = 53) -> bytes:
    family = socket.AF_INET6 if ":" in server else socket.AF_INET
    with socket.socket(family, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.sendto(query, (server, port))
        return sock.recv(65535)


def _tcp(server: str, query: bytes, timeout: float, port: int = 53) -> bytes:
    with socket.create_connection((server, port), timeout=timeout) as sock:
        sock.sendall(struct.pack("!H", len(query)) + query)
        head = b""
        while len(head) < 2:
            chunk = sock.recv(2 - len(head))
            if not chunk:
                raise DnsError("the connection closed")
            head += chunk
        want = struct.unpack("!H", head)[0]
        body = b""
        while len(body) < want:
            chunk = sock.recv(want - len(body))
            if not chunk:
                raise DnsError("the connection closed")
            body += chunk
        return body


def txt(name: str, servers: Optional[Sequence[str]] = None, timeout: float = 3.0, port: int = 53) -> list[str]:
    """The TXT records of ``name`` (empty when it has none or does not exist); ``DnsError`` when no server answered."""
    name = name.rstrip(".").lower()
    last: Optional[Exception] = None
    for server in list(servers) if servers else nameservers():
        qid = secrets.randbits(16)
        query = build_query(name, qid)
        try:
            records, truncated = parse_answer(_udp(server, query, timeout, port), qid, name)
            if truncated:
                records, _ = parse_answer(_tcp(server, query, timeout, port), qid, name)
            return records
        except (OSError, DnsError) as exc:
            last = exc
    raise DnsError(f"no DNS server answered for {name}" + (f" ({last})" if last else " (no nameserver configured)"))


__all__ = ["DnsError", "build_query", "nameservers", "parse_answer", "txt"]
