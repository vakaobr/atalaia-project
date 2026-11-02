#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Example scoreboard: follows a game through the field controller's MQTT topics.

    python3 scoreboard.py --host <controller-ip>            one line per change
    python3 scoreboard.py --host <controller-ip> --curses   a full-screen board

It subscribes to

    field/v1/+/score              totals per team (retained: the current score arrives at once)
    field/v1/+/events/#           every game event (game.start, zone.captured, ...)

and needs only paho-mqtt (Debian/Raspberry Pi OS: apt install python3-paho-mqtt;
1.6 and 2.x both work). With the Mosquitto setup in controller/deploy/, log
in as the read-only user (--username/--password). Read-only: it never
publishes. A starting point for your own scoreboard: an LED panel, a TV, a
speaker that calls out captures.
"""

from __future__ import annotations

import argparse
import json
import queue
import sys
import time
from typing import Any, Optional

import paho.mqtt.client as mqtt

PREFIX = "field/v1"


def format_score(game: Any, teams: dict[str, int]) -> str:
    """'game 4242: red 30 · blue 15' (teams in the order the controller sends them)."""
    parts = " · ".join(f"{team} {int(points)}" for team, points in teams.items())
    return f"game {game}: {parts}" if parts else f"game {game}: no teams"


def format_event(game: Any, event: dict[str, Any]) -> str:
    """'game 4242 05:00 zone.captured node 7 red' for one event."""
    t = int(event.get("t") or 0) // 1000
    who = f" {event['team']}" if event.get("team") else ""
    return f"game {game} {t // 60:02d}:{t % 60:02d} {event.get('type')} node {event.get('node')}{who}"


def parse(topic: str, payload: bytes) -> Optional[tuple[str, Any, dict[str, Any]]]:
    """('score' or 'event', game id, message) for our topics, else None."""
    parts = topic.split("/")
    if len(parts) < 4 or "/".join(parts[:2]) != PREFIX:
        return None
    try:
        msg = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(msg, dict):
        return None
    game = parts[2]
    if parts[3] == "score" and len(parts) == 4 and isinstance(msg.get("teams"), dict):
        return "score", game, msg
    if parts[3] == "events" and len(parts) == 5:
        return "event", game, msg
    return None


def make_client(client_id: str) -> mqtt.Client:
    version = getattr(mqtt, "CallbackAPIVersion", None)
    if version is not None:  # paho-mqtt 2.x
        return mqtt.Client(version.VERSION2, client_id=client_id)
    return mqtt.Client(client_id=client_id)


def run_lines(inbox: "queue.Queue[tuple[str, Any, dict]]", once: bool, timeout: Optional[float]) -> int:
    end = time.monotonic() + timeout if timeout else None
    while True:
        wait = None if end is None else max(0.0, end - time.monotonic())
        try:
            kind, game, msg = inbox.get(timeout=wait)
        except queue.Empty:
            print("scoreboard: no score arrived in time", file=sys.stderr)
            return 1
        if kind == "score":
            print(format_score(game, msg["teams"]), flush=True)
            if once:
                return 0
        else:
            print(format_event(game, msg), flush=True)


def run_curses(inbox: "queue.Queue[tuple[str, Any, dict]]") -> int:
    import curses

    def board(screen: Any) -> None:
        curses.curs_set(0)
        screen.timeout(500)
        scores: dict[str, dict[str, int]] = {}
        last: list[str] = []
        while True:
            try:
                while True:
                    kind, game, msg = inbox.get_nowait()
                    if kind == "score":
                        scores[game] = msg["teams"]
                    else:
                        last = (last + [format_event(game, msg)])[-5:]
            except queue.Empty:
                pass
            screen.erase()
            screen.addstr(0, 0, "Atalaia scoreboard (q to quit)", curses.A_BOLD)
            row = 2
            for game, teams in scores.items():
                screen.addstr(row, 0, f"game {game}")
                row += 1
                for team, points in teams.items():
                    screen.addstr(row, 2, f"{team:<24}{int(points):>8}", curses.A_BOLD)
                    row += 1
                row += 1
            for line in last:
                screen.addstr(row, 0, line[: max(1, curses.COLS - 1)])
                row += 1
            screen.refresh()
            if screen.getch() in (ord("q"), ord("Q")):
                return

    curses.wrapper(board)
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="localhost", help="the controller's MQTT broker (default localhost)")
    ap.add_argument("--port", type=int, default=1883, help="1883 on the controller itself; 8883 (TLS) from the field")
    ap.add_argument("--cafile", default="", help="the field CA's ca.pem: connect over TLS, trusting that CA alone "
                                                 "(the field's network is 8883, FLD-5)")
    ap.add_argument("--username", default="")
    ap.add_argument("--password", default="")
    ap.add_argument("--game", default="+", help="only this game id (default: every game)")
    ap.add_argument("--curses", action="store_true", help="full-screen board instead of lines")
    ap.add_argument("--once", action="store_true", help="exit after the first score (for scripts and tests)")
    ap.add_argument("--timeout", type=float, default=None, help="give up after this many seconds")
    args = ap.parse_args(argv)

    inbox: "queue.Queue[tuple[str, Any, dict]]" = queue.Queue()
    client = make_client(f"atalaia-scoreboard-{int(time.time() * 1000) % 100000}")
    if args.username:
        client.username_pw_set(args.username, args.password or None)
    if args.cafile:
        import ssl  # noqa: PLC0415

        client.tls_set(ca_certs=args.cafile, tls_version=ssl.PROTOCOL_TLS_CLIENT)
        client.tls_insecure_set(True)  # the certificate is checked against the field CA alone, not against a name

    def on_connect(client: Any, userdata: Any, flags: Any, reason: Any, *rest: Any) -> None:
        failed = getattr(reason, "is_failure", reason != 0)
        if failed:
            print(f"scoreboard: the broker refused the connection ({reason})", file=sys.stderr)
            return
        client.subscribe(f"{PREFIX}/{args.game}/score", qos=1)
        client.subscribe(f"{PREFIX}/{args.game}/events/#", qos=1)

    def on_message(client: Any, userdata: Any, message: Any) -> None:
        parsed = parse(message.topic, message.payload)
        if parsed is not None:
            inbox.put(parsed)

    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(args.host, args.port, keepalive=30)
    except OSError as exc:
        print(f"scoreboard: cannot reach {args.host}:{args.port}: {exc}", file=sys.stderr)
        return 1
    client.loop_start()
    try:
        return run_curses(inbox) if args.curses else run_lines(inbox, args.once, args.timeout)
    except KeyboardInterrupt:
        return 0
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    sys.exit(main())
