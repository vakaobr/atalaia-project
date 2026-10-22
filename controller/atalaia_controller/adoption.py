# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Adopting boxes (protocol/adoption.md): giving a new Field Box the field join key.

Two of the three ways the maintainer chose (decision AD-1) are built here; the
third, a pairing code over LoRa, waits for the sealed radio invites:

- **The NFC field card.** ``field_card()`` gives the bytes of an NTAG215/216
  holding the field join key and the field's name (MIME type
  application/vnd.atalaia.field, atalaia_sim.field_card), which the GM writes
  like a join card and taps once on each new box. The card is the field's
  master secret: whoever holds it can make join cards and, with the sealed
  radio invites, read later games' keys. A lost card means rotating the key
  (``python -m atalaia_controller join-key --rotate``) and adopting every box
  again.
- **The USB cable.** ``scan()`` lists the Field Boxes plugged into this
  controller: every Espressif USB-Serial-JTAG port (303a:1001) but the modem's
  own, and ``[adopt] usb_ports`` (e.g. a COM-to-TCP bridge's
  ``socket://host.docker.internal:7001``), each asked "@adopt-info". The GM
  confirms one box (its name and MAC) and ``adopt_usb()`` checks it is still
  that box and types "@adopt <key> <PIN|-> <field name>". The box applies its
  own rules: an unadopted box takes the key; a box adopted to another field
  (or to this field's previous key) only with its admin PIN.

Every card made and every USB adoption is logged (``atalaia.adoption``) and
kept in the store's last 100 adoption records (who, which box, the result,
never the key or the PIN). GM token only.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from atalaia_sim import field_card

from .engine import Conflict, Controller, ControllerError, NotFound, Unavailable
from .radio_modem import open_serial

log = logging.getLogger("atalaia.adoption")

ESPRESSIF_VID = 0x303A
USB_SERIAL_JTAG_PID = 0x1001
BAUDRATE = 115200
REPLY = "ATALAIA-ADOPT "
LOG_SETTING = "adoption.log"
LOG_MAX = 100
PREVIOUS_SETTING = "join_key.previous_fingerprint"
PIN_RE = re.compile(r"[0-9]{1,8}")
MAC_RE = re.compile(r"([0-9A-F]{2}:){5}[0-9A-F]{2}")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
OK_RESULTS = ("adopted", "same", "readopted")


class PortFailed(Exception):
    """A port that could not be opened, or a box that did not answer."""


def list_usb_ports() -> list[dict[str, Any]]:
    """Espressif USB-Serial-JTAG ports on this machine: [{"port", "serial"}]."""
    try:
        from serial.tools import list_ports  # noqa: PLC0415 (pyserial)
    except ImportError:
        return []
    out = []
    for p in list_ports.comports():
        if p.vid == ESPRESSIF_VID and p.pid == USB_SERIAL_JTAG_PID:
            out.append({"port": p.device, "serial": (p.serial_number or "").upper()})
    return out


def _same_port(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    if a.startswith("/dev/") and b.startswith("/dev/"):
        return os.path.realpath(a) == os.path.realpath(b)
    return False


class BoxLink:
    """One console line exchange with a box: open the port, send a line, read the reply."""

    def __init__(self, port: Any, clock: Callable[[], float] = time.monotonic) -> None:
        self.port = port
        self.clock = clock
        self._buf = b""

    def send(self, line: str) -> None:
        # A line end first: whatever was typed on the console before is not part of the command.
        self.port.write(("\n@" + line + "\n").encode("utf-8"))
        self.port.flush()

    def reply(self, kind: str, timeout: float, resend: Optional[str] = None) -> Optional[dict[str, Any]]:
        """The next "ATALAIA-ADOPT {...}" line of that kind, or None at the timeout.

        With resend, the line is sent again half-way: a box that resets when its port
        opens (DTR on some hosts) misses the first one while it boots."""
        end = self.clock() + timeout
        half = self.clock() + timeout / 2
        while self.clock() < end:
            if resend is not None and self.clock() >= half:
                self.send(resend)
                resend = None
            chunk = self.port.read(256)
            if chunk:
                self._buf += chunk
            while b"\n" in self._buf:
                raw, self._buf = self._buf.split(b"\n", 1)
                line = ANSI_RE.sub("", raw.decode("utf-8", errors="replace")).strip()
                i = line.find(REPLY)
                if i < 0:
                    continue
                try:
                    msg = json.loads(line[i + len(REPLY):])
                except ValueError:
                    continue
                if isinstance(msg, dict) and msg.get("v") == 1 and msg.get("kind") == kind:
                    return msg
            if len(self._buf) > 4096:
                self._buf = self._buf[-1024:]
        return None


class Adoption:
    """The field card and the USB adoption, for the GM console (api.py: /api/v1/adopt...)."""

    def __init__(self, controller: Controller, *,
                 lister: Callable[[], list[dict[str, Any]]] = list_usb_ports,
                 opener: Optional[Callable[[str], Any]] = None,
                 probe_timeout_s: float = 3.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.controller = controller
        self.cfg = controller.cfg
        self.store = controller.store
        self.lister = lister
        self.opener = opener or (lambda url: open_serial(url, BAUDRATE, 0.05))
        self.probe_timeout_s = probe_timeout_s
        self.clock = clock
        self._lock = threading.Lock()
        controller.adoption = self

    # ---- the field ------------------------------------------------------------------

    def _key(self) -> bytes:
        key = self.controller.join_key
        if not key or len(key) != field_card.KEY_SIZE:
            raise Unavailable("no field join key on this controller")
        return key

    def field_name(self) -> str:
        branding = self.controller.branding
        try:
            name = branding.field_name() if branding is not None else self.cfg.field_name
        except Exception:  # noqa: BLE001 - the name is cosmetic; the configured one does
            name = self.cfg.field_name
        return field_card.clean_name(name or "")

    def info(self) -> dict[str, Any]:
        return {"fingerprint": field_card.fingerprint(self._key()), "field_name": self.field_name(),
                "previous_fingerprint": self.store.get_setting(PREVIOUS_SETTING) or None,
                "usb": self.cfg.adopt_usb, "usb_ports": list(self.cfg.adopt_usb_ports),
                "log": self.records()[-20:][::-1]}

    def records(self) -> list[dict[str, Any]]:
        raw = self.store.get_setting(LOG_SETTING)
        try:
            out = json.loads(raw) if raw else []
        except ValueError:
            out = []
        return out if isinstance(out, list) else []

    def _record(self, entry: dict[str, Any]) -> None:
        entry = {"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **entry}
        rec = (self.records() + [entry])[-LOG_MAX:]
        self.store.set_setting(LOG_SETTING, json.dumps(rec, separators=(",", ":")))

    # ---- method 2: the NFC field card ------------------------------------------------

    def field_card(self) -> dict[str, Any]:
        """The field card's bytes: the field's master secret (never cached, GM token only)."""
        key = self._key()
        name = self.field_name()
        payload = field_card.encode(key, name)
        fp = field_card.fingerprint(key)
        log.warning("adoption: a field card was made (field %s); it holds the field join key", fp)
        self._record({"method": "card", "result": "card_made", "field": fp})
        return {"fingerprint": fp, "field_name": name, "bytes": len(payload),
                "ndef_tag_hex": field_card.to_ndef_tag(payload).hex()}

    # ---- method 3: the USB cable ------------------------------------------------------

    def candidate_ports(self) -> list[dict[str, Any]]:
        if not self.cfg.adopt_usb:
            return []
        out: list[dict[str, Any]] = []
        for p in self.lister():
            if _same_port(p["port"], self.cfg.port):
                continue  # the radio modem: never written to
            out.append({"port": p["port"], "serial": p.get("serial", "")})
        for url in self.cfg.adopt_usb_ports:
            if url != self.cfg.port and all(o["port"] != url for o in out):
                out.append({"port": url, "serial": ""})
        return out

    def _probe(self, link: BoxLink) -> Optional[dict[str, Any]]:
        link.send("adopt-info")
        return link.reply("info", self.probe_timeout_s, resend="adopt-info")

    def _open(self, url: str) -> Any:
        try:
            return self.opener(url)
        except Exception as exc:  # serial.SerialException, OSError
            raise PortFailed(str(exc).splitlines()[0] if str(exc) else type(exc).__name__) from None

    def _box(self, port: str, info: dict[str, Any], usb_serial: str = "") -> dict[str, Any]:
        own = field_card.fingerprint(self._key())
        field = info.get("field") or ""
        previous = self.store.get_setting(PREVIOUS_SETTING) or ""
        relation = ("none" if info.get("state") != "adopted" else "this_field" if field == own
                    else "previous_key" if previous and field == previous else "other_field")
        return {"port": port, "name": str(info.get("name", "")), "mac": str(info.get("mac", "")).upper(),
                "fw": str(info.get("fw", "")), "state": info.get("state"), "field": field,
                "field_name": str(info.get("field_name", "")), "relation": relation,
                "busy": bool(info.get("busy")), "locked": bool(info.get("locked")),
                # Older boxes say neither (decisions AD-28, AD-29): a wait of 1 min, a PIN set.
                "locked_min": int(info.get("locked_min") or 1) if info.get("locked") else 0,
                "pin_set": info.get("pin_set") is not False,
                "usb_serial": usb_serial}

    def scan(self) -> dict[str, Any]:
        """Every box plugged in by USB, as it describes itself; ports that did not answer too."""
        if not self.cfg.adopt_usb:
            raise Unavailable("USB adoption is off on this controller ([adopt] usb = false)")
        boxes, silent = [], []
        with self._lock:
            for p in self.candidate_ports():
                try:
                    port = self._open(p["port"])
                except PortFailed as exc:
                    silent.append({"port": p["port"], "error": str(exc)})
                    continue
                try:
                    info = self._probe(BoxLink(port, self.clock))
                finally:
                    _close(port)
                if info is None:
                    silent.append({"port": p["port"], "error": "no answer to @adopt-info (not an Atalaia box, "
                                                               "or its firmware predates USB adoption)"})
                else:
                    boxes.append(self._box(p["port"], info, p["serial"]))
        return {"boxes": boxes, "silent": silent, "fingerprint": field_card.fingerprint(self._key())}

    def adopt_usb(self, port: Any, mac: Any, pin: Any = None) -> dict[str, Any]:
        """Adopts the box on port, which must still be the box with mac the GM confirmed."""
        if not self.cfg.adopt_usb:
            raise Unavailable("USB adoption is off on this controller ([adopt] usb = false)")
        if not isinstance(port, str) or not port:
            raise ControllerError("port: the box's port, from the scan")
        if not isinstance(mac, str) or not MAC_RE.fullmatch(mac.upper()):
            raise ControllerError("mac: the MAC of the box the GM confirmed (AA:BB:CC:DD:EE:FF)")
        if pin not in (None, "") and (not isinstance(pin, str) or not PIN_RE.fullmatch(pin)):
            raise ControllerError("pin: the box's admin PIN, 1-8 digits")
        if all(p["port"] != port for p in self.candidate_ports()):
            raise NotFound(f"{port} is not a box's port here (scan again)")
        key = self._key()
        name = self.field_name()
        fp = field_card.fingerprint(key)
        with self._lock:
            try:
                handle = self._open(port)
            except PortFailed as exc:
                raise Conflict(f"cannot open {port}: {exc}") from None
            try:
                link = BoxLink(handle, self.clock)
                info = self._probe(link)
                if info is None:
                    raise Conflict(f"the box on {port} does not answer; check the cable and scan again")
                if str(info.get("mac", "")).upper() != mac.upper():
                    raise Conflict(f"the box on {port} is now {info.get('mac')}, not {mac.upper()}: scan again")
                line = f"adopt {key.hex()} {pin or '-'}" + (f" {name}" if name else "")
                link.send(line)
                answer = link.reply("result", self.probe_timeout_s)
            finally:
                _close(handle)
        if answer is None:
            raise Conflict(f"the box on {port} did not answer the adoption; scan it again to see its state")
        result = str(answer.get("result", "?"))
        box = self._box(port, answer | {"name": info.get("name"), "mac": info.get("mac"), "fw": info.get("fw"),
                                        "busy": info.get("busy"), "locked": result == "locked"})
        self._record({"method": "usb", "result": result, "field": fp, "box": box["name"], "mac": box["mac"],
                      "port": port, "pin_given": bool(pin)})
        log.warning("adoption: box %s (%s) on %s, field %s: %s", box["name"], box["mac"], port, fp, result)
        return {"result": result, "ok": result in OK_RESULTS, "box": box}


def _close(port: Any) -> None:
    try:
        port.close()
    except Exception:  # noqa: BLE001
        pass
