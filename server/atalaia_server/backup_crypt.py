# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Encrypted backups (plan phase 22; decision S22-3): ``python -m atalaia_server.backup_crypt seal|open``.

``server/backup.sh`` pipes ``pg_dump -Fc`` through ``seal`` and
``server/restore.sh`` pipes a backup through ``open`` into ``pg_restore``,
so a database dump is never on disk unencrypted. The key is
ATALAIA_BACKUP_KEY: 32 random bytes as 64 hexadecimal digits, made by
``server/setup.sh``. Lose it and every backup is unreadable: keep a copy
away from the server (server/docs/DEPLOY.md).

The format is AES-256-GCM in the STREAM construction (Hoang, Reyhanitabar,
Rogaway and Vizár, "Online Authenticated-Encryption and its Nonce-Reuse
Misuse-Resistance", CRYPTO 2015), with ``cryptography``'s AESGCM:

    header   MAGIC (8 bytes) + a random nonce prefix (7 bytes)
    records  4-byte big-endian length + AES-256-GCM(chunk), one per chunk of up to 64 KiB
    nonce    prefix (7) + chunk counter (4, big-endian) + last flag (1: 0x01 on the final chunk)
    AAD      the header

Every chunk is authenticated with its position and with whether it is the
last, so a backup that was cut short, reordered, spliced with another or
changed in any byte fails to open (exit code 1). ``open`` writes each chunk
as soon as it is verified: a consumer must not trust its output until
``open`` exits with 0, which is why restore.sh verifies a whole backup first.
"""

from __future__ import annotations

import os
import re
import struct
import sys
from typing import BinaryIO, Mapping, Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"ATLBAK\x00\x01"  # "ATLBAK", format 1
PREFIX = 7
HEADER = len(MAGIC) + PREFIX
CHUNK = 64 * 1024
TAG = 16
MAX_RECORD = CHUNK + TAG
MAX_CHUNKS = 2**32
KEY_HEX = re.compile(r"[0-9a-fA-F]{64}")


class BackupError(Exception):
    """A key, file or record that cannot be used: one line for the operator."""


def key_from_env(env: Optional[Mapping[str, str]] = None) -> bytes:
    env = os.environ if env is None else env
    raw = env.get("ATALAIA_BACKUP_KEY", "").strip()
    if not raw:
        raise BackupError("ATALAIA_BACKUP_KEY is not set (server/setup.sh makes it in server/.env)")
    if not KEY_HEX.fullmatch(raw):
        raise BackupError("ATALAIA_BACKUP_KEY must be 64 hexadecimal digits (32 bytes)")
    return bytes.fromhex(raw)


def _nonce(prefix: bytes, counter: int, last: bool) -> bytes:
    if counter >= MAX_CHUNKS:
        raise BackupError("the backup is too large for one file (2^32 chunks)")
    return prefix + struct.pack(">I", counter) + (b"\x01" if last else b"\x00")


def _read(src: BinaryIO, size: int) -> bytes:
    """Up to ``size`` bytes: fewer only at the end of the input."""
    parts = []
    while size > 0:
        part = src.read(size)
        if not part:
            break
        parts.append(part)
        size -= len(part)
    return b"".join(parts)


def seal(key: bytes, src: BinaryIO, dst: BinaryIO, prefix: Optional[bytes] = None) -> int:
    """Encrypts ``src`` to ``dst``; returns the plaintext's length. ``prefix`` is for tests only."""
    aead = AESGCM(key)
    prefix = os.urandom(PREFIX) if prefix is None else prefix
    if len(prefix) != PREFIX:
        raise BackupError("bad nonce prefix")
    header = MAGIC + prefix
    dst.write(header)
    counter = total = 0
    chunk = _read(src, CHUNK)
    while True:
        following = _read(src, CHUNK) if len(chunk) == CHUNK else b""
        last = not following
        sealed = aead.encrypt(_nonce(prefix, counter, last), chunk, header)
        dst.write(struct.pack(">I", len(sealed)) + sealed)
        total += len(chunk)
        if last:
            return total
        chunk, counter = following, counter + 1


def open_(key: bytes, src: BinaryIO, dst: BinaryIO) -> int:
    """Decrypts ``src`` to ``dst``; returns the plaintext's length. Raises BackupError on any damage."""
    aead = AESGCM(key)
    header = _read(src, HEADER)
    if len(header) != HEADER or header[:len(MAGIC)] != MAGIC:
        raise BackupError("not an Atalaia backup (or a format this version does not read)")
    prefix = header[len(MAGIC):]
    counter = total = 0
    record = _record(src)
    if record is None:
        raise BackupError("the backup is cut short (no data)")
    while True:
        following = _record(src)
        last = following is None
        try:
            chunk = aead.decrypt(_nonce(prefix, counter, last), record, header)
        except InvalidTag:
            raise BackupError(f"the backup is damaged, cut short or sealed with another key (chunk {counter})") \
                from None
        if not last and len(chunk) != CHUNK:
            raise BackupError(f"the backup is damaged (chunk {counter})")
        dst.write(chunk)
        total += len(chunk)
        if last:
            return total
        record, counter = following, counter + 1


def _record(src: BinaryIO) -> Optional[bytes]:
    head = _read(src, 4)
    if not head:
        return None
    if len(head) != 4:
        raise BackupError("the backup is cut short")
    (size,) = struct.unpack(">I", head)
    if not TAG <= size <= MAX_RECORD:
        raise BackupError("the backup is damaged (a record's length)")
    body = _read(src, size)
    if len(body) != size:
        raise BackupError("the backup is cut short")
    return body


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in ("seal", "open"):
        print("usage: python -m atalaia_server.backup_crypt seal|open  < input > output "
              "(the key in ATALAIA_BACKUP_KEY)", file=sys.stderr)
        return 2
    try:
        key = key_from_env()
        if argv[0] == "seal":
            seal(key, sys.stdin.buffer, sys.stdout.buffer)
        else:
            open_(key, sys.stdin.buffer, sys.stdout.buffer)
        sys.stdout.buffer.flush()
    except BackupError as exc:
        print(f"backup_crypt: {exc}", file=sys.stderr)
        return 1
    except BrokenPipeError:
        print("backup_crypt: the output was closed early", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
