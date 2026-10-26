# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""ORM model of the preview deployment's feedback (decisions PV-*; migration 0013_preview_feedback).

``preview_feedback``: what a visitor of a preview server (``ATALAIA_PREVIEW=on``) wrote on its feedback
form: a kind (what looks good, usability, what should change, a bug, something else), who they are in
a word (optional), the text, an optional way to answer, the page they came from and the language of the
form. **No account, no address, no user agent is kept.** The only personal data is what the visitor
chooses to type: ``contact`` (optional) and whatever the text says; the server administrators read it
(``GET /api/v1/admin/feedback``, ``/staff/feedback``, ``python -m atalaia_server feedback list``), and the
retention purge erases the contact after ``CONTACT_RETENTION`` and deletes the row after ``RETENTION``
(``personal_data.py``). The table exists on every server (it is one migration) but only a preview server
writes to it.

Imported by ``models`` so ``Base.metadata`` (Alembic, ``tests.test_migrations``) has it.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .ids import uuid7
from .models import Base

FEEDBACK_KINDS = ("good", "usability", "change", "bug", "other")
FEEDBACK_WHO = ("player", "organiser", "staff", "other")
FEEDBACK_STATUSES = ("new", "seen", "done")
MESSAGE_MAX = 2000
CONTACT_MAX = 200
CONTACT_RETENTION = timedelta(days=90)
RETENTION = timedelta(days=365)


class PreviewFeedback(Base):
    __tablename__ = "preview_feedback"
    __table_args__ = (
        CheckConstraint("kind IN ('good', 'usability', 'change', 'bug', 'other')", name="kind"),
        CheckConstraint("who IS NULL OR who IN ('player', 'organiser', 'staff', 'other')", name="who"),
        CheckConstraint("status IN ('new', 'seen', 'done')", name="status"),
        CheckConstraint("length(message) BETWEEN 1 AND 2000", name="message"),
        Index("idx_preview_feedback_status_created", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7,
                                          server_default=text("gen_random_uuid()"))
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    who: Mapped[Optional[str]] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    contact: Mapped[Optional[str]] = mapped_column(String(200))
    page: Mapped[Optional[str]] = mapped_column(String(128))
    lang: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(8), nullable=False, server_default="new")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(),
                                                 onupdate=func.now())
