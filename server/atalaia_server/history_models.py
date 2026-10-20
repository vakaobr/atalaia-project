# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""ORM models of plan phase 20 (migration 0011_history): game history and the scenario library.

- ``field_history_settings``: per field, how long spectators wait behind a live game
  (``spectator_delay_s``) and how long its game history is kept (``retention_days``, ADR-P4-8's
  "game history: 24 months, per field"). The public scoreboard's switch is ``fields.public_scoreboard``
  (ADR-P4-1, there since 0001_base). A field without a row has the defaults.
- ``game_score_samples``: every rise of a score counter (game, source, team) as the site server
  received it, so the score timeline can be drawn from the per-node counters (P4R10).
- ``field_scenarios`` and ``field_scenario_revisions``: the field's scenario library (ADR-P4-6 as
  amended, P4R9): every saved manifest is a revision; the current one is pushed to the field's
  controllers with ``GET /api/v1/sync/presets``. No author column: who saved what is in the audit log.
- ``field_presets``: the field's game presets (ADR-P4-1's ``presets``: a name, a mode id, its
  parameters), pushed with the scenarios.

None of these tables holds personal data (decision S20-6); the samples go with their game.
Imported by ``models`` so ``Base.metadata`` (Alembic, ``tests.test_migrations``) has them.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint, func, text)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .ids import uuid7
from .models import Base

DEFAULT_DELAY_S = 60          # spectators see a live game a minute late unless the field says otherwise
MAX_DELAY_S = 3600
DEFAULT_RETENTION_DAYS = 730  # ADR-P4-8: game history, 24 months
MIN_RETENTION_DAYS = 30


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7,
                         server_default=text("gen_random_uuid()"))


def _now(nullable: bool = False) -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=nullable, server_default=func.now())


class FieldHistorySettings(Base):
    __tablename__ = "field_history_settings"
    __table_args__ = (
        CheckConstraint(f"spectator_delay_s BETWEEN 0 AND {MAX_DELAY_S}", name="delay"),
        CheckConstraint(f"retention_days BETWEEN {MIN_RETENTION_DAYS} AND {DEFAULT_RETENTION_DAYS}",
                        name="retention"),
    )

    field_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"), primary_key=True)
    spectator_delay_s: Mapped[int] = mapped_column(Integer, nullable=False, server_default=str(DEFAULT_DELAY_S))
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default=str(DEFAULT_RETENTION_DAYS))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(),
                                                 onupdate=func.now())


class GameScoreSample(Base):
    """A counter's new value as it arrived (only rises are kept: counters merge by maximum)."""

    __tablename__ = "game_score_samples"
    __table_args__ = (Index("idx_game_score_samples_game", "game", "received_at"),
                      CheckConstraint("value >= 0", name="value"))

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    game: Mapped[uuid.UUID] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    team: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[int] = mapped_column(BigInteger, nullable=False)
    received_at: Mapped[datetime] = _now()


class FieldScenario(Base):
    """A scenario of the field's library, by its package id; ``revision`` is the current one."""

    __tablename__ = "field_scenarios"
    __table_args__ = (UniqueConstraint("field_id", "scenario_id"),
                      CheckConstraint("revision >= 1", name="revision"))

    id: Mapped[uuid.UUID] = _uuid_pk()
    field_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"), nullable=False)
    scenario_id: Mapped[str] = mapped_column(String(64), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(),
                                                 onupdate=func.now())


class FieldScenarioRevision(Base):
    """One saved manifest, as it was typed (the YAML or JSON text), with what the validator warned."""

    __tablename__ = "field_scenario_revisions"
    __table_args__ = (UniqueConstraint("scenario", "revision"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    scenario: Mapped[uuid.UUID] = mapped_column(ForeignKey("field_scenarios.id", ondelete="CASCADE"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    manifest: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    warnings: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    created_at: Mapped[datetime] = _now()


class FieldPreset(Base):
    """A game preset of the field: a controller's preset (name, mode id, parameters)."""

    __tablename__ = "field_presets"
    __table_args__ = (UniqueConstraint("field_id", "name"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    field_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    mode_id: Mapped[str] = mapped_column(String(128), nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(),
                                                 onupdate=func.now())


__all__ = ["DEFAULT_DELAY_S", "DEFAULT_RETENTION_DAYS", "MAX_DELAY_S", "MIN_RETENTION_DAYS", "FieldHistorySettings",
           "FieldPreset", "FieldScenario", "FieldScenarioRevision", "GameScoreSample"]
