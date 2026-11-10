#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes a join card or the field card with a Field Box's own PN532 reader, over its USB console.

    python3 tools/nfc_write.py --port /dev/ttyACM0 "03 5a d2 1d 3a ... fe"
                                   the bytes the GM console shows (Join tab, "NFC card"; or the
                                   adoption page's "Make the field card"), spaces and all
    python3 tools/nfc_write.py --port COM3 --file card.txt     the same bytes from a file (hex text,
                                                               or the raw bytes)
    python3 tools/nfc_write.py --port COM3 "d2 1b ..."         a player tag's "NDEF record (hex)"
                                                               (a bare NDEF message: put in its TLV)
    python3 tools/nfc_write.py --port COM3 --pin 123456 ...    a release build wants the admin PIN
    python3 tools/nfc_write.py --port COM3 --read [--all] [--out card.hex]
                                   dumps the card from page 4 (to the end of its NDEF message, or
                                   the whole user memory), and saves it as hex
    python3 tools/nfc_write.py --dry-run "03 00 fe"            prints the console lines, opens nothing
    python3 tools/nfc_write.py --selftest                      checks this tool; opens no port

The box (any Field Box image with the serial join commands: the bench image, or a release with the
admin PIN) waits 10 s for an NTAG213, NTAG215 or NTAG216 card on its reader once the bytes are in,
writes them from page 4 (user memory only: never the lock, capability container or configuration
pages, for the size it reads from the card), reads every page back and answers with an
"ATALAIA-NFC {json}" line, which this tool waits for. A long card goes in pieces ("@nfcappend
<hex>", then "@nfcwrite <the last hex>"), as a console line holds 768 characters. Refused while
the box is in a game. An Android phone (the app's tag writer, or any NFC writer app) stays the
normal way to write cards; this is the bench's and the workshop's (firmware/esp32/docs/BRING_UP.md
step 7). The port is opened without raising DTR or RTS, which would reset an ESP32-S3 (as
tools/serial_bridge.py). Needs pyserial for --port only.

Exit status: 0 written (or read) and checked, 1 the box refused or failed, 2 no answer in time,
64 bad input.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

NTAG_USER_BYTES = {"NTAG213": 144, "NTAG215": 504, "NTAG216": 888}
MAX_BYTES = NTAG_USER_BYTES["NTAG216"]
LINE_MAX = 768  # SERIAL_CONSOLE_LINE_MAX: the console drops a longer line whole
CHUNK_BYTES = 256  # bytes per console line: 512 hex digits and the command, well under LINE_MAX
CARD_WAIT_S = 10  # NFC_CARD_WAIT_MS on the box
RESULT_PREFIX = "ATALAIA-NFC "
REPO = Path(__file__).resolve().parent.parent


class InputError(ValueError):
    pass


def parse_hex(text: str) -> bytes:
    """The bytes of hex text as the GM console shows it: whitespace, colons, dashes, commas and
    0x prefixes are allowed between bytes."""
    cleaned = re.sub(r"0x", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"[\s:,\-]", "", cleaned)
    if not cleaned:
        raise InputError("no bytes")
    if not re.fullmatch(r"[0-9a-fA-F]+", cleaned):
        raise InputError("not hex: only 0-9 and a-f, with spaces between bytes if you like")
    if len(cleaned) % 2:
        raise InputError("an odd number of hex digits")
    return bytes.fromhex(cleaned)


def read_input(arg: str | None, file: str | None) -> bytes:
    if (arg is None) == (file is None):
        raise InputError("give the bytes (hex) or --file, one of the two")
    if arg is not None:
        data = parse_hex(sys.stdin.read() if arg == "-" else arg)
    else:
        raw = Path(file).read_bytes()
        try:
            data = parse_hex(raw.decode("ascii"))
        except (UnicodeDecodeError, InputError):
            data = raw  # not hex text: the bytes themselves
    data = wrap_message(data)
    check_card(data)
    return data


TLV_TYPES = {0x00, 0x01, 0x02, 0x03, 0xFD, 0xFE}  # NULL, lock, memory control, NDEF, proprietary, end


def wrap_message(data: bytes) -> bytes:
    """A bare NDEF message (the console's "NDEF record (hex)" of a player tag, which starts with a
    record header with MB set) in the NDEF message TLV and the terminator TLV, as a Type 2 tag holds
    it from page 4; bytes that already start with a TLV are left as they are."""
    if not data or data[0] in TLV_TYPES or not data[0] & 0x80:
        return data
    n = len(data)
    head = bytes([0x03, n]) if n < 0xFF else bytes([0x03, 0xFF, n >> 8, n & 0xFF])
    return head + data + b"\xfe"


def ndef_summary(data: bytes) -> str:
    """What the bytes hold, as far as the TLVs say (NFC Forum Type 2 Tag), for the log."""
    i = 0
    while i < len(data):
        t = data[i]
        i += 1
        if t == 0x00:
            continue
        if t == 0xFE:
            return "no NDEF message before the terminator"
        if i >= len(data):
            break
        length = data[i]
        i += 1
        if length == 0xFF:
            if i + 2 > len(data):
                break
            length = int.from_bytes(data[i:i + 2], "big")
            i += 2
        if t == 0x03:
            if i + length > len(data):
                return f"an NDEF message of {length} bytes, cut short"
            rec = data[i:i + length]
            mime = ""
            if rec and rec[0] & 0x07 == 2 and len(rec) >= 3:  # TNF 2: MIME
                short = rec[0] & 0x10
                il = 1 if rec[0] & 0x08 else 0
                tlen = rec[1]
                start = 2 + (1 if short else 4) + il
                mime = rec[start:start + tlen].decode("ascii", errors="replace")
            terminated = 0xFE in data[i + length:i + length + 1]
            return f"an NDEF message of {length} bytes" + (f" ({mime})" if mime else "") + (
                "" if terminated else ", no terminator TLV after it")
        i += length
    return "no NDEF message TLV"


def check_card(data: bytes) -> None:
    if not data:
        raise InputError("no bytes")
    if len(data) > MAX_BYTES:
        raise InputError(f"{len(data)} bytes: more than an NTAG216's {MAX_BYTES} bytes of user memory")


def fits(data: bytes) -> list[str]:
    padded = (len(data) + 3) // 4 * 4
    return [name for name, size in NTAG_USER_BYTES.items() if padded <= size]


def console_lines(data: bytes, pin: str | None) -> list[str]:
    """The console lines that hand the bytes to the box: "@nfcappend" pieces, then "@nfcwrite"."""
    chunks = [data[i:i + CHUNK_BYTES] for i in range(0, len(data), CHUNK_BYTES)]
    lines = [f"@nfcappend {c.hex()}" for c in chunks[:-1]]
    lines.append(f"@nfcwrite {chunks[-1].hex()}" + (f" {pin}" if pin else ""))
    for line in lines:
        assert len(line) < LINE_MAX, len(line)
    return lines


def masked(line: str, pin: str | None) -> str:
    return line[: -len(pin)] + "*" * len(pin) if pin and line.endswith(" " + pin) else line


def parse_result(line: str) -> dict | None:
    """The box's "ATALAIA-NFC {json}" line (after any log prefix), or None."""
    at = line.find(RESULT_PREFIX)
    if at < 0:
        return None
    try:
        obj = json.loads(line[at + len(RESULT_PREFIX):])
    except ValueError:
        return None
    return obj if isinstance(obj, dict) and "op" in obj and "result" in obj else None


def describe(res: dict) -> str:
    parts = [f"{res['op']}: {res['result']}"]
    if "tag" in res:
        parts.append(f"{res['tag']} ({res.get('user_pages', '?')} user pages)")
    if "uid" in res:
        parts.append(f"UID {res['uid']}")
    if res["op"] == "write":
        parts.append(f"{res.get('pages', 0)} pages written")
        if "page" in res:
            parts.append(f"page {res['page']}")
    if "bytes" in res:
        parts.append(f"{res['bytes']} bytes read")
    return ", ".join(parts)


class Box:
    """The box's console over a port-like object (pyserial, or the selftest's fake)."""

    def __init__(self, port, echo=print):
        self.port = port
        self.buf = b""
        self.echo = echo

    def send(self, line: str) -> None:
        raw = (line + "\n").encode("ascii")
        for i in range(0, len(raw), 64):
            self.port.write(raw[i:i + 64])
            if hasattr(self.port, "flush"):
                self.port.flush()
            time.sleep(0.02)  # the UART's 1 KiB buffer is drained between the box's ticks

    def wait_result(self, op: str, seconds: float) -> dict | None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.buf += self.port.read(4096)
            while b"\n" in self.buf:
                raw, self.buf = self.buf.split(b"\n", 1)
                text = raw.decode("utf-8", errors="replace").rstrip("\r")
                res = parse_result(text)
                if res is not None and res["op"] == op:
                    return res
                if res is None and "nfc" in text.lower():
                    self.echo(text)
        return None


def run(box: Box, data: bytes | None, pin: str | None, read_all: bool, timeout: float) -> tuple[int, dict | None]:
    """Writes data (or reads, data None) and returns the exit status and the box's answer."""
    if data is None:
        box.send("@nfcread all" if read_all else "@nfcread")
        res = box.wait_result("read", timeout)
        if res is None:
            return 2, None
        return (0 if res["result"] == "ok" else 1), res
    lines = console_lines(data, pin)
    for line in lines[:-1]:
        box.send(line)
        res = box.wait_result("append", 5)
        if res is None:
            return 2, None
        if res["result"] != "ok":
            return 1, res
    box.send(lines[-1])
    res = box.wait_result("write", timeout)
    if res is None:
        return 2, None
    if res["result"] == "ok" and res.get("pages") != (len(data) + 3) // 4:
        res = dict(res, result="wrong_length")  # not these bytes alone: never trust such a card
    return (0 if res["result"] == "ok" else 1), res


def open_port(name: str):
    import serial  # noqa: PLC0415 (pyserial, only for a real port)

    port = serial.serial_for_url(name, do_not_open=True, baudrate=115200, timeout=0.1)
    port.dtr = False
    port.rts = False
    port.open()
    return port


# ---- the selftest: no port ----


class FakeBox:
    """A box's console as far as this tool sees it: lines in, log and ATALAIA-NFC lines out."""

    def __init__(self, card_size: int = 504, present: bool = True, pin: str | None = None):
        self.out = b""
        self.inbuf = b""
        self.staged = b""
        self.card = bytearray(card_size)
        self.card_size = card_size
        self.present = present
        self.pin = pin
        self.lines: list[str] = []

    def say(self, text: str) -> None:
        self.out += b"I (1234) atalaia: " + text.encode() + b"\r\n"

    def result(self, obj: dict) -> None:
        self.out += (RESULT_PREFIX + json.dumps(obj)).encode() + b"\n"

    def write(self, data: bytes) -> None:
        self.inbuf += data
        while b"\n" in self.inbuf:
            raw, self.inbuf = self.inbuf.split(b"\n", 1)
            line = raw.decode()
            assert len(line) < LINE_MAX
            self.lines.append(line)
            self.command(line[1:])

    def command(self, cmd: str) -> None:
        words = cmd.split(" ")
        if words[0] == "nfcappend":
            self.staged += bytes.fromhex(words[1])
            self.say(f"nfcappend: {len(self.staged)} bytes so far")
            self.result({"op": "append", "result": "ok"})
        elif words[0] == "nfcwrite":
            if self.pin is not None and (len(words) != 3 or words[2] != self.pin):
                self.say("nfcwrite: wrong admin PIN")
                self.staged = b""
                self.result({"op": "write", "result": "refused"})
                return
            data = self.staged + bytes.fromhex(words[1])
            self.staged = b""
            if not self.present:
                self.say("nfcwrite: no card within 10 s")
                self.result({"op": "write", "result": "timeout"})
                return
            pages = (len(data) + 3) // 4
            if pages * 4 > self.card_size:
                self.result({"op": "write", "result": "too_big", "tag": "NTAG213", "user_pages": 36,
                             "uid": "04a1b2c3d4e580", "pages": 0})
                return
            self.card[: len(data)] = data
            self.say(f"nfcwrite: NTAG215, wrote {pages} pages")
            self.result({"op": "write", "result": "ok", "tag": "NTAG215", "user_pages": self.card_size // 4,
                         "uid": "04a1b2c3d4e580", "pages": pages})
        elif words[0] == "nfcread":
            n = self.card_size if len(words) > 1 else 96
            self.result({"op": "read", "result": "ok", "tag": "NTAG215", "user_pages": self.card_size // 4,
                         "uid": "04a1b2c3d4e580", "bytes": n, "hex": bytes(self.card[:n]).hex()})

    def read(self, n: int) -> bytes:
        out, self.out = self.out[:n], self.out[n:]
        return out


def selftest() -> int:
    failures = 0

    def check(cond: bool, what: str) -> None:
        nonlocal failures
        if not cond:
            failures += 1
            print(f"selftest FAIL: {what}", file=sys.stderr)

    # The shared field card and join card vectors, as the GM console would show their bytes.
    fc = json.loads((REPO / "protocol/vectors/field_card.json").read_text(encoding="utf-8"))
    joins = json.loads((REPO / "protocol/vectors/join.json").read_text(encoding="utf-8"))
    cards = [bytes.fromhex(v["ndef_tag"]) for v in fc["valid"]] + [
        bytes.fromhex(v["ndef_tag"]) for v in joins["valid"] if v.get("ndef_tag")]
    check(len(cards) >= 5, "the vectors have field and join cards")
    for card in cards:
        shown = " ".join(f"{b:02x}" for b in card)
        check(parse_hex(shown) == card, "the console's spaced hex")
        check(parse_hex(card.hex().upper()) == card, "upper case")
        check(parse_hex(":".join(f"0x{b:02X}" for b in card)) == card, "0x and colons")
        check("NDEF message" in ndef_summary(card) and "cut short" not in ndef_summary(card),
              f"summary: {ndef_summary(card)}")
        check(fits(card) and fits(card)[-1] == "NTAG216", "fits an NTAG216")
    check("application/vnd.atalaia.field" in ndef_summary(cards[0]), "the field card's MIME type")
    for bad in ["", "0", "zz", "03 0"]:
        try:
            parse_hex(bad)
            check(False, f"accepted {bad!r}")
        except InputError:
            pass
    try:
        check_card(bytes(889))
        check(False, "accepted 889 bytes")
    except InputError:
        pass
    # A player tag's bare NDEF message (protocol/vectors/tag.json) gets its TLVs.
    tags = json.loads((REPO / "protocol/vectors/tag.json").read_text(encoding="utf-8"))
    tag_mems = [bytes.fromhex(v["ndef_tag"]) for v in tags["valid"]]
    check(len(tag_mems) >= 2, "the player tag vectors")
    for mem in tag_mems:
        check(mem[0] == 0x03 and mem[1] < 0xFF, "a player tag's memory starts with the NDEF TLV")
        msg = mem[2:2 + mem[1]]
        check(wrap_message(msg) == mem[:2 + len(msg) + 1], "the bare message wrapped as the vector")
        check(wrap_message(mem) == mem, "a wrapped one is left alone")
    check(wrap_message(cards[0]) == cards[0], "a card from page 4 is left alone")
    long = bytes([0xD2]) + bytes(299)
    check(wrap_message(long)[:4] == bytes([0x03, 0xFF, 0x01, 0x2C]), "the 3-byte length")
    check(fits(bytes(144)) == ["NTAG213", "NTAG215", "NTAG216"], "144 bytes fit an NTAG213")
    check(fits(bytes(145)) == ["NTAG215", "NTAG216"], "145 bytes do not")
    check(fits(bytes(505)) == ["NTAG216"], "505 bytes only an NTAG216")

    # The console lines: pieces under the line limit, the PIN last, the bytes whole.
    for n in (1, 255, 256, 257, 600, 888):
        data = bytes((i * 13) & 0xFF for i in range(n))
        lines = console_lines(data, "4826")
        check(all(len(ln) < LINE_MAX for ln in lines), f"{n}: lines fit")
        check(lines[-1].startswith("@nfcwrite ") and lines[-1].endswith(" 4826"), f"{n}: the PIN last")
        check(all(ln.startswith("@nfcappend ") for ln in lines[:-1]), f"{n}: appends first")
        back = b"".join(bytes.fromhex(ln.split(" ")[1]) for ln in lines)
        check(back == data, f"{n}: the bytes whole")
        check(len(lines) == (n + CHUNK_BYTES - 1) // CHUNK_BYTES, f"{n}: as few lines as can be")
    check(console_lines(b"\x03\x00\xfe", None) == ["@nfcwrite 0300fe"], "no PIN on a bench build")
    check(masked("@nfcwrite 0300fe 4826", "4826") == "@nfcwrite 0300fe ****", "the PIN masked")

    # The box's answer among its log lines.
    check(parse_result('I (5) atalaia: x\r') is None, "a log line is not a result")
    r = parse_result('ATALAIA-NFC {"op":"write","result":"ok","tag":"NTAG215","pages":24}')
    check(r is not None and r["pages"] == 24, "a result line")
    check(parse_result("ATALAIA-NFC {broken") is None, "a broken result line")
    check("24 pages written" in describe(r), "described")

    # A whole run against the fake box: a long join card in pieces, a field card, a read.
    quiet = []
    big = max(cards, key=len)
    box = FakeBox()
    code, res = run(Box(box, echo=quiet.append), big, None, False, 2)
    check(code == 0 and res["pages"] == (len(big) + 3) // 4, "the longest card written")
    check(bytes(box.card[: len(big)]) == big, "the card holds the bytes")
    check(any("nfcappend" in q for q in quiet) == (len(big) > CHUNK_BYTES), "the log lines echoed")
    box = FakeBox(pin="4826")
    code, res = run(Box(box, echo=quiet.append), cards[0], "4826", False, 2)
    check(code == 0 and box.lines[-1].endswith(" 4826"), "a release build's PIN")
    box = FakeBox(pin="4826")
    code, res = run(Box(box, echo=quiet.append), cards[0], "1111", False, 2)
    check(code == 1 and res["result"] == "refused", "a wrong PIN refused")
    box = FakeBox()
    box.staged = bytes(8)  # an older run's piece still on the box: the page count gives it away
    code, res = run(Box(box, echo=quiet.append), cards[0], None, False, 2)
    check(code == 1 and res["result"] == "wrong_length", "a card with more than these bytes")
    box = FakeBox(present=False)
    code, res = run(Box(box, echo=quiet.append), cards[0], None, False, 2)
    check(code == 1 and res["result"] == "timeout", "no card")
    box = FakeBox(card_size=144)
    code, res = run(Box(box, echo=quiet.append), bytes(200), None, False, 2)
    check(code == 1 and res["result"] == "too_big", "too big for the card")
    box = FakeBox()
    box.card[: len(cards[0])] = cards[0]
    code, res = run(Box(box, echo=quiet.append), None, None, False, 2)
    check(code == 0 and bytes.fromhex(res["hex"]).startswith(cards[0][:90]), "read back")

    class Silent:
        def write(self, data):
            pass

        def read(self, n):
            return b""

    code, res = run(Box(Silent(), echo=quiet.append), cards[0], None, False, 0.2)
    check(code == 2 and res is None, "no answer in time")
    return 1 if failures else 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("hex", nargs="?", help="the card's bytes from page 4, in hex (spaces allowed; - reads stdin)")
    ap.add_argument("--file", help="the bytes from a file: hex text, or the raw bytes")
    ap.add_argument("--port", help="the box's USB serial port (COM3, /dev/ttyACM0, socket://host:7001)")
    ap.add_argument("--pin", default=os.environ.get("ATALAIA_ADMIN_PIN"),
                    help="the admin PIN, for a release build (or ATALAIA_ADMIN_PIN)")
    ap.add_argument("--read", action="store_true", help="read the card on the box's reader instead")
    ap.add_argument("--all", action="store_true", help="with --read: the whole user memory")
    ap.add_argument("--out", help="with --read: save the bytes read here, as hex")
    ap.add_argument("--timeout", type=float, default=CARD_WAIT_S + 10,
                    help=f"seconds to wait for the box's answer (default {CARD_WAIT_S + 10})")
    ap.add_argument("--dry-run", action="store_true", help="print the console lines; open nothing")
    ap.add_argument("--selftest", action="store_true", help="check this tool (opens no port)")
    args = ap.parse_args(argv)
    if args.selftest:
        code = selftest()
        print("nfc_write: selftest ok" if code == 0 else "nfc_write: selftest FAILED")
        return code
    data = None
    if not args.read:
        try:
            data = read_input(args.hex, args.file)
        except (InputError, OSError) as e:
            print(f"nfc_write: {e}", file=sys.stderr)
            return 64
        print(f"nfc_write: {len(data)} bytes, {(len(data) + 3) // 4} pages from page 4: {ndef_summary(data)}; "
              f"fits {', '.join(fits(data))}")
    if args.dry_run:
        for line in console_lines(data, args.pin) if data else ["@nfcread all" if args.all else "@nfcread"]:
            print(masked(line, args.pin))
        return 0
    if not args.port:
        ap.error("--port (the box's USB serial port), --dry-run or --selftest")
    port = open_port(args.port)
    try:
        print(f"nfc_write: hold an NTAG213/215/216 card on the box's reader (the box waits {CARD_WAIT_S} s)")
        code, res = run(Box(port), data, args.pin, args.all, args.timeout)
    finally:
        port.close()
    if res is None:
        print(f"nfc_write: no answer from the box within {args.timeout:g} s (is it a Field Box image with the "
              "serial join commands, and the right port?)", file=sys.stderr)
        return code
    print(f"nfc_write: {describe(res)}")
    if args.read and res.get("hex") is not None:
        got = bytes.fromhex(res["hex"])
        for off in range(0, len(got), 16):
            print(f"  page {4 + off // 4:3d}: {got[off:off + 16].hex(' ')}")
        print(f"nfc_write: {ndef_summary(got)}")
        if args.out:
            Path(args.out).write_text(got.hex() + "\n", encoding="ascii")
            print(f"nfc_write: saved to {args.out}")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
