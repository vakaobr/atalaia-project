# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Importing a registration list into a scheduled game (ADR-P4-12; plan phase 17, decisions F20, S17-*).

The file is read and each row checked by ``import_format`` (plain Python); this module matches rows to
the game's registrations and writes them. Rows **upsert by (source, external_ref)**: the same export
imported again changes the same registrations (``unchanged`` when nothing differs), and a row without
``external_ref`` is added each time. An imported registration has no account (``user_id`` null), the
``source`` the admin gave, a new ``player_id`` and **no ticket** (the marshal ticks it by name at the
field); it counts toward ``max_players`` and goes in the roster like any other. A dry run checks and
counts the same way and writes nothing.

Rules (S17-3): a published game that has not started (the registration window does not apply: this is
the field's staff); a registration the field cancelled is ``skipped``, not brought back; a row the game
cannot take is ``refused`` with a code and the other rows still go in; registrations of the same source
that are not in the file are listed (``missing``), never cancelled by the import. Columns the file does
not have are left as they are on an update; an empty cell clears that value.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import import_format as fmt
from .. import quotas
from ..models import Field, FieldPlayerId, GameRegistration, RegistrationReplica, ScheduledGame
from . import registration as reg_svc

MAX_LISTED = 100  # external refs listed as missing


@dataclass
class Outcome:
    answer: dict[str, Any]
    counts: dict[str, int]


def rules_for(field: Field, game: ScheduledGame) -> fmt.Rules:
    rule = reg_svc.field_rule(field)
    # A field whose APD rule asks keeps the number an import carries even when the game itself asks for none
    # (never required by an import: protocol/apd.md).
    federation = "optional" if game.federation == "off" and (rule["register"] or rule["checkin"]) else game.federation
    return fmt.Rules(teams=tuple(game.teams or ()), federation=federation,
                     predeclare_replicas=game.predeclare_replicas, classes=reg_svc.classes(field.limit_template),
                     max_replicas=field.max_replicas)


def check_game(game: ScheduledGame, now: datetime) -> None:
    if game.status == "cancelled":
        raise reg_svc.RegistrationError("game_cancelled", 409)
    if game.status != "published" or game.starts_at <= now:
        raise reg_svc.RegistrationError("game_started", 409)


def _same_replicas(old: list[RegistrationReplica], new: list[dict[str, Optional[str]]]) -> bool:
    return [(r.replica_type, r.replica_class, r.make_model) for r in old] == \
        [(d["type"], d["class"], d["make_model"]) for d in new]


async def _new_player_id(db: AsyncSession, field_id: uuid.UUID, taken: set[str]) -> str:
    """A player id nobody at the field has: not in this game and no account's id there."""
    for _ in range(5):
        candidate = reg_svc.new_player_id()
        if candidate in taken:
            continue
        if await db.scalar(select(FieldPlayerId.id).where(FieldPlayerId.field_id == field_id,
                                                          FieldPlayerId.player_id == candidate)) is None:
            taken.add(candidate)
            return candidate
    raise reg_svc.RegistrationError("player_id_unavailable", 503)


async def run(db: AsyncSession, field: Field, game: ScheduledGame, parsed: fmt.Parsed, source: str,
              dry_run: bool, now: datetime) -> Outcome:
    """Applies (or, with ``dry_run``, only previews) the file in the caller's transaction, ``game``
    locked by ``registration.lock_game``. The caller commits or rolls back."""
    check_game(game, now)
    rules = rules_for(field, game)
    regs = list(await db.scalars(select(GameRegistration).where(GameRegistration.scheduled_game == game.id)
                                 .with_for_update()))
    by_ref = {r.external_ref: r for r in regs if r.source == source and r.external_ref is not None}
    names = {r.display_name for r in regs if r.status in reg_svc.ACTIVE and r.display_name}
    taken = {r.player_id for r in regs}
    live = sum(1 for r in regs if r.status in reg_svc.ACTIVE)
    reps = await reg_svc.replicas_of(db, [r.id for r in by_ref.values()])
    seen_refs: set[str] = set()
    free = await quotas.room(db, "registrations", field.id)  # hosted mode's quota; None: no limit
    results: list[dict[str, Any]] = []
    counts = {"created": 0, "updated": 0, "unchanged": 0, "skipped": 0, "refused": 0}

    for raw in parsed.rows:
        entry: dict[str, Any] = {"row": raw.number}
        try:
            row = fmt.check_row(raw, rules)
        except fmt.RowError as exc:
            entry.update(result="refused", code=exc.code)
            counts["refused"] += 1
            results.append(entry)
            continue
        entry.update(external_ref=row.external_ref, display_name=row.display_name, warnings=list(row.warnings))
        if row.external_ref is not None:
            if row.external_ref in seen_refs:
                entry.update(result="refused", code="external_ref_twice")
                counts["refused"] += 1
                results.append(entry)
                continue
            seen_refs.add(row.external_ref)
        existing = by_ref.get(row.external_ref) if row.external_ref is not None else None
        if existing is None:
            if game.max_players is not None and live >= game.max_players:
                entry.update(result="refused", code="game_full")
                counts["refused"] += 1
                results.append(entry)
                continue
            if free is not None and free <= 0:
                entry.update(result="refused", code=quotas.CODE)
                counts["refused"] += 1
                results.append(entry)
                continue
            if free is not None:
                free -= 1
            if row.display_name in names:
                entry["warnings"].append("same_name")  # perhaps registered on the site too
            live += 1
            names.add(row.display_name)
            entry["result"] = "created"
            if not dry_run:
                reg = GameRegistration(scheduled_game=game.id, field_id=field.id, user_id=None,
                                       player_id=await _new_player_id(db, field.id, taken),
                                       display_name=row.display_name, team_preference=row.team_preference,
                                       federation_number=row.federation_number, status="registered",
                                       ticket_hash=None, source=source, external_ref=row.external_ref,
                                       updated_at=now)
                db.add(reg)
                await db.flush()
                await _put(db, reg, row.replicas or [])
                entry["registration_id"] = str(reg.id)
        elif existing.status != "registered":
            entry.update(result="skipped", code="cancelled", registration_id=str(existing.id))
        else:
            changed = _changes(existing, reps.get(existing.id, []), row)
            entry.update(result="updated" if changed else "unchanged", registration_id=str(existing.id))
            if changed:
                entry["changed"] = changed
                if not dry_run:
                    for name in changed:
                        if name == "replicas":
                            await _put(db, existing, row.replicas or [])
                        else:
                            setattr(existing, name, getattr(row, name))
                    existing.updated_at = now
        counts[entry["result"]] += 1
        results.append(entry)

    missing = sorted(ref for ref, r in by_ref.items() if ref not in seen_refs and r.status == "registered")
    if not dry_run:
        await db.flush()
    answer = {
        "dry_run": dry_run, "format": parsed.format, "source": source, "scheduled_game_id": str(game.id),
        "columns": list(parsed.columns), "not_imported_columns": parsed.ignored,
        "not_imported_more": parsed.ignored_more, "rows": len(parsed.rows), "counts": counts,
        "missing": {"count": len(missing), "external_refs": missing[:MAX_LISTED]},
        "results": results,
    }
    return Outcome(answer, counts)


def _changes(reg: GameRegistration, old: list[RegistrationReplica], row: fmt.Row) -> list[str]:
    """The names of what the row changes, among the columns the file has."""
    changed = []
    for name in ("display_name", "team_preference", "federation_number"):
        if name in row.present and getattr(reg, name) != getattr(row, name):
            changed.append(name)
    if row.replicas is not None and not _same_replicas(old, row.replicas):
        changed.append("replicas")
    return changed


async def _put(db: AsyncSession, reg: GameRegistration, replicas: list[dict[str, Optional[str]]]) -> None:
    await db.execute(RegistrationReplica.__table__.delete().where(RegistrationReplica.registration == reg.id))
    for pos, d in enumerate(replicas):
        db.add(RegistrationReplica(registration=reg.id, declaration_id=uuid.uuid4(), replica_id=None,
                                   replica_type=d["type"], replica_class=d["class"], make_model=d["make_model"],
                                   position=pos))


async def export_rows(db: AsyncSession, game: ScheduledGame) -> list[dict[str, Any]]:
    """The game's registrations for the CSV export, oldest first."""
    regs = list(await db.scalars(select(GameRegistration).where(GameRegistration.scheduled_game == game.id)
                                 .order_by(GameRegistration.created_at, GameRegistration.id)))
    reps = await reg_svc.replicas_of(db, [r.id for r in regs])
    return [{"display_name": r.display_name, "external_ref": r.external_ref, "team_preference": r.team_preference,
             "federation_number": r.federation_number,
             "replicas": [{"type": d.replica_type, "class": d.replica_class, "make_model": d.make_model}
                          for d in reps[r.id]],
             "registration_id": str(r.id), "player_id": r.player_id, "status": r.status, "source": r.source}
            for r in regs]
