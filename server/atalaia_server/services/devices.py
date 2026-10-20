# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Device health and the firmware catalogue's reads (plan phase 19; RESEARCH section 8; decisions S19-5 to S19-8).

Device health is read from what the controllers already sync (no table of its
own): each game's nodes (``game_nodes``: name, role, last seen and the health
fields protocol/sync.md allows: battery, RSSI, SNR, platform, firmware, core
version, tier) and their events ``node.online``, ``node.offline``,
``battery.low`` and ``node.tamper`` (``game_events``; an event's node is the
node it is about). Nodes get their ids per game, so across games a device is
known by its name (HELLO's ``node_name``, set on the box itself; decision
S19-7): the field's device list is each name's latest entry.

A device is ``battery_low`` below ``BATTERY_LOW_PCT`` (or, without a level, when
its game logged ``battery.low`` for it), ``offline`` when the last of its
``node.online``/``node.offline`` events is an ``offline`` one, ``silent`` when
its game is live and the controller has not heard it for ``SILENT_S`` (by the
times the controller synced), and ``outdated`` when the catalogue has a newer
verified stable release for its platform.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import firmware
from ..models import FirmwareRelease, Game, GameEvent, GameNode

BATTERY_LOW_PCT = 20
SILENT_S = 180               # a live game's node not heard for 3 minutes (STATE comes every 10-60 s)
HEALTH_EVENTS = ("node.online", "node.offline", "battery.low", "node.tamper")
DEVICE_DAYS = 90             # the field's device list looks at the games of the last 90 days by default
MAX_DEVICE_DAYS = 730
MAX_ROWS = 20000
LIVE = ("running", "paused")


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def release_json(r: FirmwareRelease, verified: bool) -> dict[str, Any]:
    return {"id": str(r.id), "platform": r.platform, "version": r.version, "size": r.size, "sha256": r.sha256,
            "signature": r.signature, "key_id": r.key_id, "notes": r.notes, "released_at": _iso(r.released_at),
            "yanked_at": _iso(r.yanked_at), "yank_reason": r.yank_reason, "verified": verified,
            "pre_release": "-" in r.version, "added_at": _iso(r.created_at)}


async def catalogue(db: AsyncSession, keys: Iterable[str]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Every release, newest first per platform, each checked again against today's keys; and per platform
    the latest stable release that is verified and not withdrawn."""
    keys = tuple(keys)
    rows = (await db.scalars(select(FirmwareRelease))).all()
    out, latest = [], {}
    best: dict[str, tuple] = {}
    for r in rows:
        ok = firmware.signer(keys, r.platform, r.version, r.size, r.sha256, r.signature) is not None
        out.append(release_json(r, ok))
        vkey = firmware.version_key(r.version)
        if ok and r.yanked_at is None and vkey is not None and vkey[3] == 1:
            if r.platform not in best or vkey > best[r.platform]:
                best[r.platform] = vkey
                latest[r.platform] = r.version
    out.sort(key=lambda e: (e["platform"], firmware.version_key(e["version"]) or (0, 0, 0, 0, ())), reverse=True)
    out.sort(key=lambda e: e["platform"])
    return out, latest


def firmware_state(info: dict[str, Any], latest: dict[str, str]) -> dict[str, Any]:
    platform = firmware.platform_name(info.get("platform"))
    current = info.get("fw_version") if isinstance(info.get("fw_version"), str) else None
    newest = latest.get(platform) if platform else None
    outdated = None
    if newest is not None and current is not None:
        have, want = firmware.version_key(current), firmware.version_key(newest)
        outdated = have < want if have is not None and want is not None else None
    return {"platform": platform, "version": current, "latest": newest, "outdated": outdated}


def _health(node: GameNode, game: Game, events: dict[str, dict[str, Any]], latest: dict[str, str],
            now: datetime) -> dict[str, Any]:
    info = node.info or {}
    battery = info.get("battery_pct") if isinstance(info.get("battery_pct"), int) else None
    seen = events.get("battery.low")
    link = [e for e in (events.get("node.online"), events.get("node.offline")) if e is not None]
    last_link = max(link, key=lambda e: e["id"]) if link else None
    silent = game.state in LIVE and node.last_seen_at is not None and now - node.last_seen_at > timedelta(
        seconds=SILENT_S)
    return {"node_id": node.node_id, "name": node.name, "role": node.role, "last_seen_at": _iso(node.last_seen_at),
            "battery_pct": battery, "rssi": info.get("rssi"), "snr": info.get("snr"), "tier": info.get("tier"),
            "core_version": info.get("core_version"), "owner": info.get("owner"),
            "firmware": firmware_state(info, latest),
            "battery_low": (battery < BATTERY_LOW_PCT) if battery is not None else seen is not None,
            "offline": last_link is not None and last_link["type"] == "node.offline",
            "silent": bool(silent), "tampered": events.get("node.tamper") is not None,
            "game": {"id": str(game.id), "name": game.name, "state": game.state, "game_id": game.game_id},
            "events": {t: events[t]["count"] for t in HEALTH_EVENTS if t in events}}


async def _events(db: AsyncSession, game_ids: list[uuid.UUID]) -> dict[tuple[uuid.UUID, int], dict[str, Any]]:
    """Per (game, node) and health event type: how many, and the last one's id and game time."""
    if not game_ids:
        return {}
    rows = await db.execute(
        select(GameEvent.game, GameEvent.node_id, GameEvent.event_type, func.count(), func.max(GameEvent.id),
               func.max(GameEvent.game_time_ms))
        .where(GameEvent.game.in_(game_ids), GameEvent.event_type.in_(HEALTH_EVENTS))
        .group_by(GameEvent.game, GameEvent.node_id, GameEvent.event_type))
    out: dict[tuple[uuid.UUID, int], dict[str, Any]] = {}
    for game, node, kind, count, last_id, last_t in rows:
        out.setdefault((game, node), {})[kind] = {"type": kind, "count": int(count), "id": int(last_id),
                                                  "t": int(last_t)}
    return out


async def game_devices(db: AsyncSession, game: Game, keys: Iterable[str]) -> list[dict[str, Any]]:
    """One game's nodes with their health."""
    _, latest = await catalogue(db, keys)
    nodes = (await db.scalars(select(GameNode).where(GameNode.game == game.id).order_by(GameNode.node_id))).all()
    events = await _events(db, [game.id])
    now = datetime.now(timezone.utc)
    return [_health(n, game, events.get((game.id, n.node_id), {}), latest, now) for n in nodes]


async def field_devices(db: AsyncSession, field_id: uuid.UUID, keys: Iterable[str],
                        days: int = DEVICE_DAYS) -> list[dict[str, Any]]:
    """The field's devices: each node name's latest entry among the games synced in the last ``days``."""
    _, latest = await catalogue(db, keys)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (await db.execute(
        select(GameNode, Game).join(Game, Game.id == GameNode.game)
        .where(Game.field_id == field_id, Game.updated_at >= since)
        .order_by(GameNode.last_seen_at.desc()).limit(MAX_ROWS))).all()
    newest: dict[str, tuple[GameNode, Game]] = {}
    games: dict[str, int] = {}
    for node, game in rows:
        newest.setdefault(node.name, (node, game))
        games[node.name] = games.get(node.name, 0) + 1
    events = await _events(db, list({g.id for _, g in newest.values()}))
    now = datetime.now(timezone.utc)
    out = []
    for name in sorted(newest):
        node, game = newest[name]
        entry = _health(node, game, events.get((game.id, node.node_id), {}), latest, now)
        entry["games"] = games[name]
        out.append(entry)
    return out
