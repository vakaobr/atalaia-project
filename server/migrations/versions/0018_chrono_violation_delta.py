# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Chrono violations: the class limit, the excess and repeat offenders (decision PKD-3; closes S14-7's gap).

Revision ID: 0018_chrono_violation_delta
Revises: 0016_apd_membership
Created: 2026-10-28

- ``chrono_violations.limit_j``: the class limit in joules the controller judged the series against (it sends it
  with each reading since PKD-3); null for a violation that came before, or from a controller that does not send it.
- ``chrono_violations.delta_j``: the deciding reading's energy minus that limit (``energy_j - limit_j``), null
  with it.
- ``chrono_violations.repeat_offender``: the player already has an earlier violation at the field (a violation
  of an earlier reading, whatever the replica). Existing rows are worked out here by the deciding readings' times.

The downgrade drops the three columns.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018_chrono_violation_delta"
down_revision = "0016_apd_membership"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chrono_violations", sa.Column("limit_j", sa.Float(), nullable=True))
    op.add_column("chrono_violations", sa.Column("delta_j", sa.Float(), nullable=True))
    op.add_column("chrono_violations", sa.Column("repeat_offender", sa.Boolean(), nullable=False,
                                                 server_default=sa.false()))
    op.execute("""
        UPDATE chrono_violations v SET repeat_offender = true
        FROM chrono_readings r
        WHERE r.id = v.reading AND EXISTS (
            SELECT 1 FROM chrono_violations o JOIN chrono_readings ro ON ro.id = o.reading
            WHERE o.field_id = v.field_id AND o.player_id = v.player_id AND o.id <> v.id
              AND (ro.timestamp, ro.reading_id) < (r.timestamp, r.reading_id))
    """)


def downgrade() -> None:
    op.drop_column("chrono_violations", "repeat_offender")
    op.drop_column("chrono_violations", "delta_j")
    op.drop_column("chrono_violations", "limit_j")
