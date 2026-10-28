# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Demo data for a preview server (decisions PV-*): one fictional field with a public page and scoreboard, two
fictional clubs, scheduled games, finished games with their scores, events and boxes, a scenario and two presets.

    python -m atalaia_server demo load                  make it, or bring it up to date (idempotent)
    python -m atalaia_server demo reset                 delete the demo field and clubs, then load again
    python -m atalaia_server demo reviewer --username NAME --out FILE
                                                        a test account with the GM role on the demo field
    python -m atalaia_server demo live [--key-out FILE] [--keep N] [--reset]
                                                        the live demo field's side (see ``live`` below)

**Everything is invented**: the field, the clubs, the games, the callsigns, the scores. No real person, club or
place is named (a test checks the names against a list of what the loader may write). The loader writes
straight to the database with fixed, derived ids (UUIDv5), so running it again changes nothing that is already
right; it never touches an account, a session, the feedback or anything that is not the demo's.

``load`` also keeps the demo *alive*: the finished games' times are shifted so the newest ended ``NEWEST_ENDED_AGO``
ago (the public scoreboard shows an ended game for 12 hours, ``history.RECENT``), and the scheduled games are
moved to the next Saturdays when they have passed. The preview deployment runs it every hour; what a visitor
with a test account changed in the demo's own rows (a game's title, say) is put back by it.

The games are as a controller would have synced them: counters per box and team that only rise, the events a mode
writes, the boxes' health (one box with a low battery, so the devices page has something to flag).
"""

from __future__ import annotations

import os
import random
import secrets
import uuid
from dataclasses import dataclass, field as dc_field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from . import passwords, personal_data, sync, totp
from .history_models import FieldPreset, GameScoreSample
from .models import (ROLE_NAMES, Club, Controller, Field, FieldApiKey, FieldTeam, Game, GameEvent, GameNode,
                     GameNodeScore, GameRegistration, ScheduledGame, User, UserFieldRole)
from .services import library
from .tokens import Keys
from .totp import SeedBox

FIELD_SLUG = "campo-demo"
CLUB_SLUG = "corvos-da-serra"
CLUB2_SLUG = "raposas-do-vale"
NAMESPACE = uuid.UUID("5c2f6c1e-7a40-4c3a-9d8e-1b0f6a4e2d11")  # makes the demo's ids; never changes
NEWEST_ENDED_AGO = timedelta(minutes=25)
ZONE = "Europe/Lisbon"
CONTROLLER_VERSION = "0.3.0-dev.demo"

# Every text the loader writes that names something, for the test that checks nothing real is in it.
CALLSIGNS = ("Falcão", "Lince", "Sombra", "Brasa", "Corça", "Pardal", "Tojo", "Névoa", "Seixo", "Giesta", "Urze",
             "Cardo")
DESCRIPTION = (
    "Campo de demonstração do servidor Atalaia: um campo inventado, com jogos inventados, para ver como a "
    "página pública, o marcador e as páginas da organização ficam.\n\n"
    "Nada aqui é real: nem o campo, nem os clubes, nem as pessoas, nem as pontuações.")

MANIFEST = """\
id: org.demo.pinheiro
version: 0.1.0
name: Pinheiro Branco
description: >-
  Red takes the bridge, which reveals the vault to red; blue defends. A demonstration scenario.
lang: pt
teams: [red, blue]
params:
  vault_points: { type: int, min: 0, max: 1000, default: 100, label: "Points for the vault" }
i18n:
  pt:
    name: Pinheiro Branco
    description: >-
      A equipa red toma a ponte, o que lhe revela o cofre; a blue defende. Um cenário de demonstração.
    params:
      vault_points: Pontos do cofre

nodes:
  ponte: { role: objective }
  cofre: { role: objective }

objectives:
  - id: bridge
    name: Bridge
    i18n: { pt: { name: Ponte } }
    type: capture_and_hold
    target: ponte
    assignee: { team: red }
    params: { hold_ms: 3000 }
    effect: { points: 50 }

  - id: vault
    name: Vault
    i18n: { pt: { name: Cofre } }
    type: enter_code
    target: cofre
    assignee: { team: red }
    params: { code: "4711" }
    visibility: hidden
    depends_on: [bridge]
    effect: { points: { param: vault_points } }
"""


def demo_id(*parts: object) -> uuid.UUID:
    """The demo row's id: the same every time (UUIDv5 of its name)."""
    return uuid.uuid5(NAMESPACE, "/".join(str(p) for p in parts))


# --- the simulated games ---------------------------------------------------------------------------------------


@dataclass
class SimEvent:
    t_ms: int
    node: int
    type: str
    team: Optional[str]
    data: dict[str, Any]
    prio: str = "normal"


@dataclass
class SimGame:
    key: str
    name: str
    mode_id: str
    duration_s: int
    ended_ago: timedelta
    seed: int
    zones: list[tuple[int, str]]            # (node id, zone name)
    params: dict[str, Any]
    events: list[SimEvent] = dc_field(default_factory=list)
    samples: list[tuple[int, int, str, int]] = dc_field(default_factory=list)   # (t_s, node, team, value)
    counters: dict[tuple[int, str], int] = dc_field(default_factory=dict)       # final (node, team) -> value


ZONES = [(3, "alpha"), (4, "bravo"), (5, "charlie"), (6, "delta"), (7, "echo")]
TEAMS = ("red", "blue")


def simulate_domination(game: SimGame) -> SimGame:
    """A Domination game: a zone is captured every minute or two, an owned zone scores ``points_per_tick`` each
    ``tick_s`` for its owner; the boxes' counters only rise and are sampled each minute they rose."""
    rng = random.Random(game.seed)
    owner: dict[int, Optional[str]] = {node: None for node, _ in game.zones}
    names = dict(game.zones)
    value = {(node, team): 0 for node, _ in game.zones for team in TEAMS}
    seq_of: dict[int, int] = {}
    tick, pts = int(game.params["tick_s"]), int(game.params["points_per_tick"])
    game.events.append(SimEvent(0, 0, "game.start", None, {"preset": game.name}, "critical"))
    next_capture = rng.randint(20, 60)
    last_sampled = dict(value)
    for t in range(tick, game.duration_s + 1, tick):
        if t >= next_capture:
            node = rng.choice([n for n, _ in game.zones])
            team = rng.choice([x for x in TEAMS if x != owner[node]])
            game.events.append(SimEvent(t * 1000, node, "zone.captured", team,
                                        {"zone": names[node], "previous_team": owner[node]}))
            owner[node] = team
            next_capture = t + rng.randint(45, 150)
        for node, team in owner.items():
            if team is not None:
                value[(node, team)] += pts
        if t % 60 == 0 or t == game.duration_s:
            for key, v in value.items():
                if v > last_sampled[key]:
                    game.samples.append((t, key[0], key[1], v))
                    last_sampled[key] = v
    game.counters = {k: v for k, v in value.items() if v}
    totals = {team: sum(v for (_, tm), v in value.items() if tm == team) for team in TEAMS}
    winner = max(totals, key=lambda tm: totals[tm]) if totals["red"] != totals["blue"] else None
    low = game.zones[-1][0]
    game.events.append(SimEvent(int(game.duration_s * 0.6) * 1000, low, "battery.low", None, {"percent": 14},
                                "telemetry"))
    game.events.append(SimEvent(game.duration_s * 1000, 0, "game.end", None,
                                {"reason": "time", "winner": winner}, "critical"))
    game.events.sort(key=lambda e: (e.t_ms, e.node))
    for e in game.events:
        seq_of[e.node] = seq_of.get(e.node, 0) + 1
        e.data = {**e.data, "_seq": seq_of[e.node]}
    return game


def simulate_bomb(game: SimGame) -> SimGame:
    """One round of Bomb: armed with a team code, defused in time: the defenders score."""
    game.events = [SimEvent(0, 0, "game.start", None, {"preset": game.name}, "critical"),
                   SimEvent(95_000, 3, "bomb.armed", "red", {"fuse_s": 60, "reason": "code"}, "critical"),
                   SimEvent(131_000, 3, "bomb.defused", "blue", {"reason": "code"}, "critical"),
                   SimEvent(game.duration_s * 1000, 0, "game.end", None, {"reason": "bomb", "winner": "blue"},
                            "critical")]
    game.samples = [(131, 3, "blue", 100)]
    game.counters = {(3, "blue"): 100}
    seq_of: dict[int, int] = {}
    for e in game.events:
        seq_of[e.node] = seq_of.get(e.node, 0) + 1
        e.data = {**e.data, "_seq": seq_of[e.node]}
    return game


def games() -> list[SimGame]:
    """The demo's finished games (the same every time: fixed seeds)."""
    return [
        simulate_domination(SimGame("a", "Domínio da Serra, manhã", "org.atalaia.domination", 5400, NEWEST_ENDED_AGO,
                                    20261001, ZONES, {"capture_hold_ms": 3000, "tick_s": 10, "points_per_tick": 1})),
        simulate_bomb(SimGame("b", "Bomba na Fábrica, 2.ª ronda", "org.atalaia.bomb", 240,
                              timedelta(days=3, hours=2), 20260928, [(3, "alpha")], {})),
        simulate_domination(SimGame("c", "Domínio da Serra, treino", "org.atalaia.domination", 2700,
                                    timedelta(days=10, hours=1), 20260917, ZONES[:3],
                                    {"capture_hold_ms": 3000, "tick_s": 10, "points_per_tick": 1})),
    ]


# --- scheduled games -------------------------------------------------------------------------------------------


def next_weekday(now: datetime, weekday: int, hour: int, minute: int, minimum_days: int) -> datetime:
    """The first ``weekday`` (Monday is 0) at hour:minute in the field's zone at least ``minimum_days`` days from now."""
    tz = ZoneInfo(ZONE)
    day = (now.astimezone(tz) + timedelta(days=minimum_days)).date()
    day += timedelta(days=(weekday - day.weekday()) % 7)
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz).astimezone(timezone.utc)


@dataclass
class PlannedGame:
    key: str
    title: str
    description: str
    mode_id: str
    starts_at: datetime
    hours: float
    max_players: int
    opens_days: int                 # the registration opens this many days before the start
    status: str = "published"
    cancelled_reason: Optional[str] = None
    registered: int = 0


def schedule(now: datetime) -> list[PlannedGame]:
    sat = next_weekday(now, 5, 9, 30, 3)
    return [
        PlannedGame("dom", "Domínio da Serra", "Jogo de Domínio com cinco caixas espalhadas pela serra: ganha a "
                    "equipa que mais tempo as tiver. Inscrições abertas.", "org.atalaia.domination", sat, 6.5, 24, 12,
                    registered=9),
        PlannedGame("bomb", "Bomba na Fábrica", "Rondas curtas de Bomba numa fábrica abandonada (inventada). As "
                    "inscrições abrem daqui a uns dias.", "org.atalaia.bomb", sat + timedelta(days=14, hours=4.5), 4, 30,
                    7),
        PlannedGame("last", "Noite de Último Elemento", "Jogo noturno de Último Elemento.",
                    "org.atalaia.laststand", sat + timedelta(days=28, hours=10.5), 3.5, 16, 10),
        PlannedGame("rain", "Treino de sábado", "Treino aberto.", "org.atalaia.domination",
                    sat + timedelta(days=7), 3, 20, 10, status="cancelled",
                    cancelled_reason="Previsão de chuva forte: fica para outro sábado."),
    ]


# --- the loader ------------------------------------------------------------------------------------------------


def _set(row: Any, **values: Any) -> bool:
    """Sets the attributes that differ; True if any did."""
    changed = False
    for name, value in values.items():
        if getattr(row, name) != value:
            setattr(row, name, value)
            changed = True
    return changed


async def _get_or_new(db: AsyncSession, model: Any, pk: Any, **create: Any) -> tuple[Any, bool]:
    row = await db.get(model, pk)
    if row is not None:
        return row, False
    row = model(**create)
    db.add(row)
    return row, True


async def load(db: AsyncSession, now: Optional[datetime] = None, holder: Optional[library.CoreHolder] = None
               ) -> dict[str, Any]:
    """Makes the demo, or brings it up to date; commits. Returns what it did, by name."""
    now = now or datetime.now(timezone.utc)
    done: dict[str, Any] = {}
    field_id = demo_id("field")
    field = await db.get(Field, field_id)
    done["field"] = "created" if field is None else "kept"
    if field is None:
        field = Field(id=field_id, name="Campo Demo da Serra Azul", slug=FIELD_SLUG)
        db.add(field)
    _set(field, field_type="outdoor", timezone=ZONE, public_page=True, public_scoreboard=True,
         description=DESCRIPTION, address_text="Serra Azul (local fictício, sem morada)", federation_label="N.º fed.",
         limit_template="portugal", max_replicas=5, branding_name="Serra Azul", accent="#3b5d2a")
    await db.flush()

    clubs = {}
    for slug, name, short, colour, text in (
            (CLUB_SLUG, "Corvos da Serra", "Corvos", "#2f4f6f",
             "Clube inventado para a demonstração. Joga de azul-escuro e gosta de Domínio.\n\n"
             "Nenhum clube real tem este nome de propósito."),
            (CLUB2_SLUG, "Raposas do Vale", "Raposas", "#a0522d",
             "Outro clube inventado. Prefere as rondas curtas de Bomba.")):
        club, _ = await _get_or_new(db, Club, demo_id("club", slug), id=demo_id("club", slug), name=name,
                                    short_name=short, slug=slug)
        _set(club, name=name, short_name=short, description=text, colour=colour, public_page=True)
        clubs[slug] = club
    await db.flush()
    for slug, colour in ((CLUB_SLUG, "#c0392b"), (CLUB2_SLUG, "#2471a3")):
        team, _ = await _get_or_new(db, FieldTeam, demo_id("team", slug), id=demo_id("team", slug),
                                    field_id=field_id, club_id=clubs[slug].id)
        _set(team, field_id=field_id, club_id=clubs[slug].id, colour=colour)

    sim = games()
    done["games"] = await _games(db, field_id, sim, now)

    controller = await db.scalar(select(Controller).where(Controller.field_id == field_id))
    if controller is None:
        controller = Controller(field_id=field_id, controller_id=demo_id("controller"), version=CONTROLLER_VERSION)
        db.add(controller)
    controller.last_seen_at = now

    done["scheduled"] = await _scheduled(db, field_id, schedule(now), sim, now)

    for name, mode, params in (("Domínio, 90 minutos", "org.atalaia.domination",
                                {"capture_hold_ms": 3000, "tick_s": 10, "points_per_tick": 1}),
                               ("Bomba, ronda curta", "org.atalaia.bomb", {})):
        library.check_preset({"name": name, "mode_id": mode, "params": params})
        preset, _ = await _get_or_new(db, FieldPreset, demo_id("preset", name), id=demo_id("preset", name),
                                      field_id=field_id, name=name, mode_id=mode)
        _set(preset, name=name, mode_id=mode, params=params)

    done["scenario"] = await _scenario(db, field_id, holder or library.CoreHolder())
    await db.commit()
    return done


async def _games(db: AsyncSession, field_id: uuid.UUID, sim: list[SimGame], now: datetime) -> dict[str, str]:
    result = {}
    for g in sim:
        gid = demo_id("game", g.key)
        ended = now - g.ended_ago
        row = await db.get(Game, gid)
        if row is None:
            started = ended - timedelta(seconds=g.duration_s)
            ids = random.Random(g.seed)
            row = Game(id=gid, field_id=field_id, game_id=ids.randint(1, 65535), game_seed=ids.randint(1, 2**32 - 1),
                       name=g.name, mode_id=g.mode_id, teams=list(TEAMS),
                       team_info={"red": {"display_name": "Corvos da Serra"},
                                  "blue": {"display_name": "Raposas do Vale"}},
                       params=g.params, squads=0, duration_ms=g.duration_s * 1000, state="ended",
                       controller_created_at=started - timedelta(minutes=10), started_at=started, ended_at=ended)
            db.add(row)
            await db.flush()
            for e in g.events:
                data = dict(e.data)
                seq = data.pop("_seq")
                db.add(GameEvent(game=gid, node_id=e.node, seq=seq, game_time_ms=e.t_ms, event_type=e.type,
                                 team=e.team, priority=e.prio, data=data,
                                 received_at=started + timedelta(milliseconds=e.t_ms)))
            for t_s, node, team, value in g.samples:
                db.add(GameScoreSample(game=gid, source=f"node-{node}", team=team, value=value,
                                       received_at=started + timedelta(seconds=t_s)))
            for (node, team), value in g.counters.items():
                db.add(GameNodeScore(game=gid, source=f"node-{node}", team=team, value=value, updated_at=ended))
            for node, zone in g.zones:
                info: dict[str, Any] = {"battery_pct": 14 if (g.key != "b" and node == g.zones[-1][0]) else 60 + node * 5,
                                        "rssi": -62 - node * 3, "platform": "esp32", "tier": "reduced",
                                        "fw_version": "0.3.0-dev.12", "core_version": "0.3.0"}
                role = "zone" if g.mode_id.endswith("domination") else "bomb"
                db.add(GameNode(game=gid, node_id=node, name=f"Caixa {zone.capitalize()}", role=role, info=info,
                                last_seen_at=ended))
            result[g.key] = "created"
            continue
        shift = ended - row.ended_at
        if abs(shift) < timedelta(seconds=1):
            result[g.key] = "kept"
            continue
        # Every time the game owns moves by the same amount: it ended ``ended_ago`` ago, as on the first load.
        interval = shift
        row.started_at += interval
        row.ended_at += interval
        row.controller_created_at += interval
        await db.execute(update(GameEvent).where(GameEvent.game == gid).values(
            received_at=GameEvent.received_at + interval))
        await db.execute(update(GameScoreSample).where(GameScoreSample.game == gid).values(
            received_at=GameScoreSample.received_at + interval))
        await db.execute(update(GameNodeScore).where(GameNodeScore.game == gid).values(
            updated_at=GameNodeScore.updated_at + interval))
        await db.execute(update(GameNode).where(GameNode.game == gid).values(
            last_seen_at=GameNode.last_seen_at + interval))
        result[g.key] = "shifted"
    return result


async def _scheduled(db: AsyncSession, field_id: uuid.UUID, plan: list[PlannedGame], sim: list[SimGame],
                     now: datetime) -> dict[str, str]:
    result = {}
    for p in plan:
        sid = demo_id("scheduled", p.key)
        row = await db.get(ScheduledGame, sid)
        starts = p.starts_at
        ends = starts + timedelta(hours=p.hours)
        values: dict[str, Any] = {
            "title": p.title, "description": p.description, "mode_id": p.mode_id, "teams": list(TEAMS),
            "location_text": "Serra Azul (local fictício)", "max_players": p.max_players, "status": p.status,
            "registration_opens_at": starts - timedelta(days=p.opens_days),
            "registration_closes_at": starts - timedelta(days=1), "federation": "off", "predeclare_replicas": True,
            "cancelled_reason": p.cancelled_reason, "cancelled_at": now if p.status == "cancelled" else None}
        if row is None:
            row = ScheduledGame(id=sid, field_id=field_id, starts_at=starts, ends_at=ends,
                                published_at=now, **{k: v for k, v in values.items() if k != "cancelled_at"})
            if p.status == "cancelled":
                row.cancelled_at = now
            db.add(row)
            await db.flush()
            result[p.key] = "created"
        else:
            keep_cancelled_at = row.cancelled_at if p.status == "cancelled" and row.cancelled_at else values["cancelled_at"]
            values["cancelled_at"] = keep_cancelled_at
            moved = row.starts_at < now + timedelta(days=1) or abs(row.starts_at - starts) > timedelta(days=3)
            if moved:
                values.update(starts_at=starts, ends_at=ends)
            result[p.key] = "updated" if _set(row, **values) else "kept"
        for i in range(p.registered):
            ref = f"demo-{p.key}-{i + 1}"
            rid = demo_id("registration", ref)
            if await db.get(GameRegistration, rid) is None:
                db.add(GameRegistration(
                    id=rid, scheduled_game=sid, field_id=field_id, player_id=f"p-{uuid.uuid5(NAMESPACE, ref).hex[:12]}",
                    display_name=f"{CALLSIGNS[i % len(CALLSIGNS)]} {i + 1}", team_preference=TEAMS[i % 2],
                    status="registered", source="demo", external_ref=ref))
    # Last Saturday's game: completed, and the finished Domination game is its game.
    done = await db.get(ScheduledGame, demo_id("scheduled", "done"))
    ended = now - NEWEST_ENDED_AGO
    if done is None:
        done = ScheduledGame(id=demo_id("scheduled", "done"), field_id=field_id, title="Domínio da Serra, manhã",
                             description="O jogo que já acabou: as pontuações estão no marcador.",
                             starts_at=ended - timedelta(minutes=100), ends_at=ended + timedelta(minutes=20),
                             mode_id="org.atalaia.domination", teams=list(TEAMS), status="completed",
                             published_at=now - timedelta(days=20), controller_game=demo_id("game", "a"),
                             location_text="Serra Azul (local fictício)")
        db.add(done)
        result["done"] = "created"
    else:
        _set(done, starts_at=ended - timedelta(minutes=100), ends_at=ended + timedelta(minutes=20),
             controller_game=demo_id("game", "a"))
        result["done"] = "kept"
    return result


async def _scenario(db: AsyncSession, field_id: uuid.UUID, holder: library.CoreHolder) -> str:
    try:
        _, outcome = await library.save(db, holder, field_id, MANIFEST)
    except library.LibraryProblem as exc:
        return f"skipped ({exc.detail})"  # the core library is not there (a controller-less machine): no scenario
    return outcome


async def reset(db: AsyncSession, now: Optional[datetime] = None, holder: Optional[library.CoreHolder] = None
                ) -> dict[str, Any]:
    """Deletes the demo field (with everything under it) and the demo clubs, then loads again. Test accounts keep
    their roles on the demo field; feedback and every other account are untouched."""
    field_id = demo_id("field")
    roles = list((await db.execute(select(UserFieldRole.user_id, UserFieldRole.role_id).where(
        UserFieldRole.field_id == field_id))).all())
    await db.execute(delete(Field).where(Field.id == field_id))
    await db.execute(delete(Club).where(Club.id.in_([demo_id("club", CLUB_SLUG), demo_id("club", CLUB2_SLUG)])))
    await db.commit()
    done = await load(db, now, holder)
    for user_id, role_id in roles:
        db.add(UserFieldRole(user_id=user_id, field_id=field_id, role_id=role_id))
    await db.commit()
    done["roles_restored"] = len(roles)
    return done


# --- the live demo field --------------------------------------------------------------------------------------

LIVE_SLUG = "demo-ao-vivo"
LIVE_NAME = "Campo Demo ao Vivo"
LIVE_KEEP = 12                    # games kept on the live field; older ones are deleted by each run
LIVE_CONTROLLER_KEEP = timedelta(hours=6)  # a controller that has not synced for this long is forgotten
LIVE_DESCRIPTION = (
    "Campo de demonstração ao vivo: um controlador de campo simulado, com caixas simuladas, joga um jogo atrás do "
    "outro e envia-os para aqui como faria um campo a sério.\n\n"
    "Nada aqui é real: nem o campo, nem as alcunhas, nem as pontuações. Os jogos mais antigos vão sendo apagados.")


async def live(db: AsyncSession, key_file: Optional[Path] = None, keep: int = LIVE_KEEP, reset: bool = False,
               now: Optional[datetime] = None) -> dict[str, Any]:
    """The server's side of the preview's live demo (docs/runbooks/preview-server.md, "The live demo"): a field of
    its own, ``demo-ao-vivo``, that a simulated field controller (the ``demo-field`` service) syncs its looping
    games to, so the public pages show what the controller plays. Kept apart from ``campo-demo`` so that the
    hourly ``demo load`` never touches a synced game and the sync never touches the made-up ones.

    ``key_file``: the field's API key for that controller. Made once (only its SHA-256 is kept here, as for any
    key) and written to the file, mode 0600; kept while the file holds a live key of this field, otherwise
    replaced (the old one is revoked). Nothing secret is printed. Every run also deletes what is old: all but the
    newest ``keep`` games and controllers that stopped syncing; ``reset`` deletes all the field's games and
    controllers. Idempotent; commits."""
    now = now or datetime.now(timezone.utc)
    done: dict[str, Any] = {}
    field_id = demo_id("live-field")
    field = await db.get(Field, field_id)
    done["field"] = "created" if field is None else "kept"
    if field is None:
        field = Field(id=field_id, name=LIVE_NAME, slug=LIVE_SLUG)
        db.add(field)
    _set(field, field_type="outdoor", timezone=ZONE, public_page=True, public_scoreboard=True,
         description=LIVE_DESCRIPTION, address_text="Campo simulado (local fictício, sem morada)",
         federation_label="N.º fed.", limit_template="portugal", max_replicas=5, branding_name="Demo ao vivo",
         accent="#3b5d2a")
    await db.flush()

    if key_file is not None:
        wanted = None
        try:
            wanted = key_file.read_text(encoding="utf-8").strip() or None
        except OSError:
            pass
        live_keys = list(await db.scalars(select(FieldApiKey).where(
            FieldApiKey.field_id == field_id, FieldApiKey.revoked_at.is_(None))))
        if wanted is not None and any(k.key_sha256 == sync.key_hash(wanted) for k in live_keys):
            done["key"] = "kept"
        else:
            for k in live_keys:
                k.revoked_at = now
            key = sync.new_key()
            db.add(FieldApiKey(field_id=field_id, key_sha256=sync.key_hash(key), label="demo-field"))
            tmp = key_file.with_name(key_file.name + ".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(key + "\n")
            os.replace(tmp, key_file)
            done["key"] = "made"

    if reset:
        done["deleted_games"] = (await db.execute(delete(Game).where(Game.field_id == field_id))).rowcount
        await db.execute(delete(Controller).where(Controller.field_id == field_id))
    else:
        old = list(await db.scalars(select(Game.id).where(Game.field_id == field_id)
                                    .order_by(Game.controller_created_at.desc()).offset(max(keep, 1))))
        if old:
            await db.execute(delete(Game).where(Game.id.in_(old)))
        done["deleted_games"] = len(old)
        await db.execute(delete(Controller).where(Controller.field_id == field_id,
                                                  Controller.last_seen_at < now - LIVE_CONTROLLER_KEEP))
    await db.commit()
    return done


# --- test accounts ---------------------------------------------------------------------------------------------


def new_password() -> str:
    """A strong password: 24 characters of letters and digits, no look-alikes (it is read aloud and typed)."""
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(24))
        if passwords.policy_problem(password, "reviewer") is None:
            return password


async def make_account(db: AsyncSession, keys: Keys, notice_version: str, username: str, password: str, secret: str,
                       server_admin: bool = False, role: Optional[str] = None, now: Optional[datetime] = None) -> uuid.UUID:
    """An account with TOTP already enrolled (``secret``), made without asking anyone: for the operator's
    preview setup (``create-admin --generate``, ``demo reviewer``). ``role`` is a role on the demo field."""
    now = now or datetime.now(timezone.utc)
    hashed = await passwords.hash_password(password)
    user = User(username=username, password_hash=hashed, server_admin=server_admin, totp_enabled=True,
                totp_secret_enc=SeedBox(keys.totp_seed).seal(secret), totp_last_step=totp.step_of(now.timestamp()) - 1,
                gdpr_consent_at=now)
    db.add(user)
    await db.flush()
    personal_data.give_consent(db, user.id, personal_data.ACCOUNT, notice_version, now)
    if role is not None:
        db.add(UserFieldRole(user_id=user.id, field_id=demo_id("field"), role_id=ROLE_NAMES[role]))
    return user.id


async def username_taken(db: AsyncSession, username: str) -> bool:
    return await db.scalar(select(func.count()).select_from(User).where(User.username == username)) != 0


def json_summary(done: dict[str, Any]) -> str:
    """What ``load`` or ``reset`` did, on one line."""
    return ", ".join(f"{k}={v}" for k, v in done.items())
