#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Serves a serial port on TCP, for a field controller in Docker that cannot see COM ports.

    python tools/serial_bridge.py COM3 7001            (Windows; pip install pyserial)
    python tools/serial_bridge.py /dev/ttyACM0 7001

The controller then opens ``socket://host.docker.internal:7001``: for USB adoption,
``[adopt] usb_ports`` or ``ATALAIA_ADOPT_USB_PORTS`` (protocol/adoption.md); for the
radio modem, ``[modem] port`` (at the modem's baud rate, ``--baud 921600``). The
port is opened without raising DTR or RTS, which would reset an ESP32-S3, and stays
open; one TCP client at a time, a new one replaces the old. Listens on 127.0.0.1
unless ``--host`` says otherwise (Docker Desktop reaches it as host.docker.internal).
Close any serial monitor on the port first.
"""

from __future__ import annotations

import argparse
import socket
import sys
import threading


def open_port(name: str, baud: int):
    import serial  # noqa: PLC0415 (pyserial)

    port = serial.serial_for_url(name, do_not_open=True, baudrate=baud, timeout=0.05)
    port.dtr = False
    port.rts = False
    port.open()
    return port


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("port", help="the serial port: COM3, /dev/ttyACM0")
    ap.add_argument("tcp_port", type=int, help="the TCP port to serve it on")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args(argv)
    try:
        port = open_port(args.port, args.baud)
    except Exception as exc:  # noqa: BLE001 - serial.SerialException, ImportError
        print(f"serial_bridge: cannot open {args.port}: {exc}", file=sys.stderr)
        return 1
    server = socket.create_server((args.host, args.tcp_port))
    lock = threading.Lock()
    client: list[socket.socket] = []

    def to_tcp() -> None:
        while True:
            data = port.read(512)
            if not data:
                continue
            with lock:
                conns = list(client)
            for c in conns:
                try:
                    c.sendall(data)
                except OSError:
                    pass

    threading.Thread(target=to_tcp, daemon=True).start()
    print(f"serial_bridge: {args.port} at {args.baud} baud on tcp://{args.host}:{args.tcp_port}", flush=True)
    try:
        while True:
            conn, addr = server.accept()
            with lock:
                for old in client:
                    old.close()
                client[:] = [conn]
            print(f"serial_bridge: client {addr[0]}:{addr[1]}", flush=True)
            threading.Thread(target=from_tcp, args=(conn, port), daemon=True).start()
    except KeyboardInterrupt:
        return 0


def from_tcp(conn: socket.socket, port) -> None:
    while True:
        try:
            data = conn.recv(512)
        except OSError:
            return
        if not data:
            return
        port.write(data)


if __name__ == "__main__":
    sys.exit(main())
