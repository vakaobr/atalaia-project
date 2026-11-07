# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A box still in a game that is over (decisions STUCK-1 to STUCK-19 and STUCK-40 to STUCK-47, RFC 0001 Amendment 27).

A box that was switched off when its game ended never heard the GAME_OVERs (reinvite.py). When it
comes back it is still in that game: it plays on and refuses every join. The modem reports the
packets of other games it hears (OTHER_GAME: the game id and source from the header in the clear,
at most once per game id in 10 s; protocol/usb-modem.md). When the game id is one of the games
this controller ran and ended, whose key's tag it still keeps (``key_tag:<game>``, the last
KEY_TAGS_KEPT games, so also after a restart without the key), it says that game's GAME_OVER
again, through the same path and channel rules as at the end, at most once a minute per game.
GAME_OVER can only end a game that is over, so a report forged from a header in the clear can
cost some air, never a game; that air is bounded (decisions SRB-1 to SRB-6): no automatic burst
while a game is started (running or paused) on this controller, so its TIME and CMD keep the
modem's duty budget (the GM's Release still works); otherwise one automatic burst for all games
together in AUTO_RESEND_MS, one at a time, the game served longest ago first, and one that takes
the modem off the field's channel in AUTO_RETUNE_MS. Each game keeps the SOURCES_KEPT node ids
heard most recently, with a count.

A standby controller never sends it (its games run on the primary). What it has heard is kept for
the console (``stuck`` in GET /api/v1/boxes): per game, when a box in it was last heard, from
which node ids, and how many times its GAME_OVER went again. The GM's console lists the games heard
within SHOWN_MS (STUCK-71: a box in a game sends STATE every 15 s, and the modem reports a game at
most every 10 s, so a box still in it is heard well within two minutes; a freed box, or one switched
off, is silent and leaves the list) and can say a game's GAME_OVER at once (``release``, the Release
button), within a short rate limit. What was heard of a game stays FORGET_MS, so a box heard again
keeps its game's resend count and once-a-minute limit.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .engine import Controller
    from .modem_framing import OtherGame

log = logging.getLogger("atalaia.stuck")

RESEND_MS = 60_000           # one GAME_OVER burst per game in this time at most
RELEASE_MS = 10_000          # the GM's Release: one burst per game in this time at most (STUCK-44)
RELEASE_FIELD_MS = 30_000    # the field-wide RELEASE (Amendment 28): one burst in this time at most
SHOWN_MS = 120_000           # the console lists a game heard within this time (STUCK-71)
FORGET_MS = 2 * 3_600_000    # a game not heard of for this long is forgotten (its resend count and rate limit)
KEY_TAGS_KEPT = 50           # the ended games whose key tag the controller keeps
AUTO_RESEND_MS = 60_000      # one automatic burst for all games together in this time at most (SRB-2)
AUTO_RETUNE_MS = 300_000     # one automatic burst off the field's channel in this time at most (SRB-3)
SOURCES_KEPT = 32            # the node ids a game keeps (the most recently heard), with a count (SRB-4)
LIVE_STATES = ("running", "paused")  # a started game: no automatic burst (SRB-1)


@dataclass
class StuckGame:
    game_id: int
    heard_ms: int
    sources: dict[int, None] = field(default_factory=dict)  # the most recently heard last
    sources_dropped: int = 0
    rssi: Optional[int] = None
    resent: int = 0
    resent_ms: Optional[int] = None

    def hear(self, source: int) -> None:
        """A node id heard: kept among the SOURCES_KEPT most recent (SRB-4)."""
        self.sources.pop(source, None)
        self.sources[source] = None
        while len(self.sources) > SOURCES_KEPT:
            del self.sources[next(iter(self.sources))]
            self.sources_dropped += 1

    def public(self, now_ms: int, name: Optional[str] = None) -> dict[str, Any]:
        return {"game": self.game_id, "name": name, "last_heard_s": max(0, (now_ms - self.heard_ms) // 1000),
                "nodes": sorted(self.sources), "nodes_count": len(self.sources) + self.sources_dropped,
                "rssi": self.rssi, "game_over_resent": self.resent}


class StuckGames:
    def __init__(self, controller: "Controller") -> None:
        self.ctl = controller
        self.games: dict[int, StuckGame] = {}
        self.reports = 0     # OTHER_GAME reports heard
        self.unknown = 0     # of those, for no game of this controller that is over (another field's)
        self.resend_ms = RESEND_MS
        self.release_ms = RELEASE_MS
        self.released: dict[int, int] = {}  # game id -> when the GM last released a game not in the list
        self.release_field_ms = RELEASE_FIELD_MS
        self.field_released_ms: Optional[int] = None  # when the last field-wide RELEASE started
        self.auto_resend_ms = AUTO_RESEND_MS
        self.auto_retune_ms = AUTO_RETUNE_MS
        self.auto_ms: Optional[int] = None    # when the last burst (automatic or released) went
        self.retune_ms: Optional[int] = None  # when the last automatic burst off the field's channel went

    def on_report(self, other: "OtherGame") -> None:
        """OTHER_GAME from the modem (its own thread)."""
        with self.ctl._lock:
            self.reports += 1
            now = self.ctl.now_ms()
            live = self.ctl.game
            if live is not None and live["id"] == other.game_id:
                return  # the live game's own (a report sent as the modem was being configured)
            if live is not None and live.get("joined"):
                return  # a standby: the primary tells its boxes
            game = self.ctl.store.game(other.game_id)
            tag = self.ctl.store.get_setting(f"key_tag:{other.game_id}")
            if game is None or game.get("state") != "ended" or game.get("joined") or tag is None:
                self.unknown += 1
                return
            stuck = self.games.get(other.game_id)
            fresh = stuck is None
            if stuck is None:
                stuck = self.games[other.game_id] = StuckGame(other.game_id, now)
            stuck.heard_ms = now
            stuck.hear(other.source)
            stuck.rssi = other.rssi
            # The consoles' list carries the stuck games: told of a new one, and of each resend (STUCK-63).
            if (self._resend_next(now) or fresh) and self.ctl.reinvite is not None:
                self.ctl.reinvite.refresh_boxes()

    def _resend_next(self, now: int) -> bool:
        """One automatic GAME_OVER burst, if the air budget allows (decisions SRB-1 to SRB-3): none while
        a game is started on this controller, none while any GAME_OVER is still being said, one for all
        games together in ``auto_resend_ms``, and one that takes the modem off the field's channel in
        ``auto_retune_ms``. Of the games heard within SHOWN_MS that may go (each at most once in
        ``resend_ms``), the one served longest ago goes, so forged reports for many games cannot keep
        a real one waiting for ever. True when a burst went."""
        reinvite = self.ctl.reinvite
        if reinvite is None:
            return False
        live = self.ctl.game
        if live is not None and live.get("state") in LIVE_STATES:
            return False  # its TIME and CMD keep the duty budget; the GM can still Release
        if reinvite.inviter.games_over:
            return False  # one burst at a time (the end's own three included)
        if self.auto_ms is not None and now - self.auto_ms < self.auto_resend_ms:
            return False
        fc, transport, field_hz = self.ctl.fc, self.ctl.transport, self.ctl.field_channel
        retune_ok = self.retune_ms is None or now - self.retune_ms >= self.auto_retune_ms
        best: Optional[tuple[tuple[int, int], StuckGame, int, str]] = None
        for stuck in self.games.values():
            if now - stuck.heard_ms > SHOWN_MS:
                continue
            if stuck.resent_ms is not None and now - stuck.resent_ms < self.resend_ms:
                continue
            game = self.ctl.store.game(stuck.game_id)
            tag = self.ctl.store.get_setting(f"key_tag:{stuck.game_id}")
            if game is None or game.get("state") != "ended" or tag is None:
                continue
            channel = game.get("channel_hz") or self.ctl.cfg.channel_hz
            if fc is not None:
                if transport is None or transport.channel_hz != channel:
                    continue  # a game made on another channel: the burst would be dropped
            elif channel != field_hz and not retune_ok:
                continue
            order = (stuck.resent_ms if stuck.resent_ms is not None else -1, -stuck.heard_ms)
            if best is None or order < best[0]:
                best = (order, stuck, channel, tag)
        if best is None:
            return False
        _, stuck, channel, tag = best
        if not reinvite.game_over(stuck.game_id, bytes.fromhex(tag), channel,
                                  why="a box is still in it; GAME_OVER sent again"):
            return False
        stuck.resent += 1
        stuck.resent_ms = now
        self.auto_ms = now
        if fc is None and channel != field_hz:
            self.retune_ms = now
        return True

    def release(self, game_id: int) -> dict[str, Any]:
        """The GM's Release (POST /api/v1/boxes/stuck/{game}/release, decisions STUCK-40 to STUCK-47):
        that game's GAME_OVER now, by the same path and channel rules as the resends, whether or not a
        box of it was heard. ``game_over_frame`` says what happened, as for End: "sent", "no_radio"
        (no modem that carries field frames), "no_tag" (no key tag kept for it). Refused: a game
        that is not this controller's or not over (404, 409), a standby (409), a game live on another
        channel (409: the burst would be dropped), and within RELEASE_MS of its last burst or while
        its GAME_OVERs are still being said (429)."""
        from .engine import Conflict, NotFound, TooSoon
        with self.ctl._lock:
            live = self.ctl.game
            if live is not None and live.get("joined"):
                raise Conflict("this controller follows a game as a standby: its primary tells the boxes")
            game = self.ctl.store.game(game_id)
            if game is None:
                raise NotFound(f"no game {game_id}")
            if (live is not None and live["id"] == game_id) or game.get("state") != "ended":
                raise Conflict(f"game {game_id} is not over")
            if game.get("joined"):
                raise Conflict(f"game {game_id} was followed as a standby: its primary tells its boxes")
            tag = self.ctl.store.get_setting(f"key_tag:{game_id}")
            if tag is None:
                return {"game": game_id, "game_over_frame": "no_tag"}
            reinvite = self.ctl.reinvite
            if reinvite is None:
                return {"game": game_id, "game_over_frame": "no_join_key"}
            now = self.ctl.now_ms()
            if any(g.game_id == game_id for g in reinvite.inviter.games_over):
                raise TooSoon(f"game {game_id}: its GAME_OVER is being sent now")
            stuck = self.games.get(game_id)
            last = stuck.resent_ms if stuck is not None else self.released.get(game_id)
            if last is not None and now - last < self.release_ms:
                wait = (self.release_ms - (now - last) + 999) // 1000
                raise TooSoon(f"game {game_id}: its GAME_OVER was sent a moment ago; try again in {wait} s")
            channel = game.get("channel_hz") or self.ctl.cfg.channel_hz
            transport = self.ctl.transport
            if self.ctl.fc is not None and (transport is None or transport.channel_hz != channel):
                raise Conflict(f"a game is live on another channel: game {game_id}'s GAME_OVER (on "
                               f"{channel} Hz) would not be sent until it ends")
            if not reinvite.game_over(game_id, bytes.fromhex(tag), channel,
                                      why="released by the GM; GAME_OVER sent again"):
                return {"game": game_id, "game_over_frame": "no_radio"}
            if stuck is not None:
                stuck.resent += 1
                stuck.resent_ms = now
            else:
                self.released[game_id] = now
            self.auto_ms = now  # the automatic minute starts again (SRB-2)
            reinvite.refresh_boxes()
            return {"game": game_id, "game_over_frame": "sent"}

    def release_field(self, device_time: Any = None) -> dict[str, Any]:
        """The field-wide RELEASE (POST /api/v1/boxes/release, RFC 0001 Amendment 28, decisions STUCK-50
        to STUCK-59, its addendum of 2026-11-06 and decisions RLB-*), for a controller that lost the game
        a box is stuck in (a new database: no key tag, so no GAME_OVER can name it): every box on the
        modem's channel in a game other than the live one (or any game, with none live) that it joined
        before now leaves it. ``release_frame``: "sent", "no_radio" or "no_join_key". Refused: a standby
        (409), a wall clock that is not plausible or is ahead of what the controller can vouch for (409,
        ``ClockGuard.release_check``: the GM's device's ``device_time``, else the uncorrected system
        clock), and while one is being said or within RELEASE_FIELD_MS of the last (429)."""
        from . import wallclock
        from .engine import Conflict, TooSoon
        with self.ctl._lock:
            live = self.ctl.game
            if live is not None and live.get("joined"):
                raise Conflict("this controller follows a game as a standby: a RELEASE would take the "
                               "primary's boxes out of its game")
            self.ctl.clock_guard.release_check(device_time)
            live_id = live["id"] if live is not None else 0
            reinvite = self.ctl.reinvite
            if reinvite is None:
                return {"live_game": live_id, "release_frame": "no_join_key"}
            now = self.ctl.now_ms()
            if reinvite.inviter.releases:
                raise TooSoon("a RELEASE is being sent now")
            last = self.field_released_ms
            if last is not None and now - last < self.release_field_ms:
                wait = (self.release_field_ms - (now - last) + 999) // 1000
                raise TooSoon(f"a RELEASE was sent a moment ago; try again in {wait} s")
            time_s = min(0xFFFFFFFF, int(wallclock.now()))
            sent, channel = reinvite.release(live_id, time_s)
            out = {"live_game": live_id, "time": time_s, "channel_hz": channel}
            if not sent:
                return {**out, "release_frame": "no_radio"}
            self.field_released_ms = now
            return {**out, "release_frame": "sent"}

    def public(self) -> list[dict[str, Any]]:
        """The games a box was heard still in within SHOWN_MS, the most recent first, with their names
        (STUCK-71: a game whose boxes went silent, freed or switched off, is not shown)."""
        with self.ctl._lock:
            now = self.ctl.now_ms()
            for gid in [g for g, s in self.games.items() if now - s.heard_ms > FORGET_MS]:
                del self.games[gid]
            for gid in [g for g, t in self.released.items() if now - t > self.release_ms]:
                del self.released[gid]
            out = []
            for s in sorted(self.games.values(), key=lambda s: -s.heard_ms):
                if now - s.heard_ms > SHOWN_MS:
                    continue
                game = self.ctl.store.game(s.game_id)
                out.append(s.public(now, game.get("name") if game is not None else None))
            return out


def prune_key_tags(store: Any, keep: int = KEY_TAGS_KEPT) -> None:
    """Keeps the key tags of the ``keep`` most recent ended games and of every live one."""
    tagged = {int(k.split(":", 1)[1]) for k in store.setting_keys("key_tag:")}
    ended = [g["id"] for g in store.games() if g.get("state") == "ended" and g["id"] in tagged]
    for gid in ended[:-keep] if keep else ended:
        store.delete_setting(f"key_tag:{gid}")
