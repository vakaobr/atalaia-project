# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A box still in a game that is over (decisions STUCK-1 to STUCK-19, RFC 0001 Amendment 27).

A box that was switched off when its game ended never heard the GAME_OVERs (reinvite.py). When it
comes back it is still in that game: it plays on and refuses every join. The modem reports the
packets of other games it hears (OTHER_GAME: the game id and source from the header in the clear,
at most once per game id in 10 s; protocol/usb-modem.md). When the game id is one of the games
this controller ran and ended, whose key's tag it still keeps (``key_tag:<game>``, the last
KEY_TAGS_KEPT games, so also after a restart without the key), it says that game's GAME_OVER
again, through the same path and channel rules as at the end, at most once a minute per game.
GAME_OVER can only end a game that is over, so a report forged from a header in the clear can
cost some air, never a game.

A standby controller never sends it (its games run on the primary). What it has heard is kept for
the console (``stuck`` in GET /api/v1/boxes): per game, when a box in it was last heard, from
which node ids, and how many times its GAME_OVER went again.
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
FORGET_MS = 2 * 3_600_000    # a game not heard of for this long leaves the list (as a free box)
KEY_TAGS_KEPT = 50           # the ended games whose key tag the controller keeps


@dataclass
class StuckGame:
    game_id: int
    heard_ms: int
    sources: set[int] = field(default_factory=set)
    rssi: Optional[int] = None
    resent: int = 0
    resent_ms: Optional[int] = None

    def public(self, now_ms: int) -> dict[str, Any]:
        return {"game": self.game_id, "last_heard_s": max(0, (now_ms - self.heard_ms) // 1000),
                "nodes": sorted(self.sources), "rssi": self.rssi, "game_over_resent": self.resent}


class StuckGames:
    def __init__(self, controller: "Controller") -> None:
        self.ctl = controller
        self.games: dict[int, StuckGame] = {}
        self.reports = 0     # OTHER_GAME reports heard
        self.unknown = 0     # of those, for no game of this controller that is over (another field's)
        self.resend_ms = RESEND_MS

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
            if stuck is None:
                stuck = self.games[other.game_id] = StuckGame(other.game_id, now)
            stuck.heard_ms = now
            stuck.sources.add(other.source)
            stuck.rssi = other.rssi
            self._resend(stuck, game, tag, now)

    def _resend(self, stuck: StuckGame, game: dict[str, Any], tag: str, now: int) -> None:
        reinvite = self.ctl.reinvite
        if reinvite is None:
            return
        if any(g.game_id == stuck.game_id for g in reinvite.inviter.games_over):
            return  # its GAME_OVERs are still being said
        if stuck.resent_ms is not None and now - stuck.resent_ms < self.resend_ms:
            return
        channel = game.get("channel_hz") or self.ctl.cfg.channel_hz
        if reinvite.game_over(stuck.game_id, bytes.fromhex(tag), channel,
                              why="a box is still in it; GAME_OVER sent again"):
            stuck.resent += 1
            stuck.resent_ms = now
            reinvite.refresh_boxes()  # the consoles' list carries the stuck games

    def public(self) -> list[dict[str, Any]]:
        """The games a box was heard still in, the most recent first."""
        with self.ctl._lock:
            now = self.ctl.now_ms()
            for gid in [g for g, s in self.games.items() if now - s.heard_ms > FORGET_MS]:
                del self.games[gid]
            return [s.public(now) for s in sorted(self.games.values(), key=lambda s: -s.heard_ms)]


def prune_key_tags(store: Any, keep: int = KEY_TAGS_KEPT) -> None:
    """Keeps the key tags of the ``keep`` most recent ended games and of every live one."""
    tagged = {int(k.split(":", 1)[1]) for k in store.setting_keys("key_tag:")}
    ended = [g["id"] for g in store.games() if g.get("state") == "ended" and g["id"] in tagged]
    for gid in ended[:-keep] if keep else ended:
        store.delete_setting(f"key_tag:{gid}")
