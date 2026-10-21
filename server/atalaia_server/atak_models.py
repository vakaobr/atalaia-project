# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""ORM models of the remote ATAK relay (Phase 4 follow-up, decisions FU5-*; migration 0012_atak).

- ``atak_cas``: one certificate authority per field, made on the field's first certificate. Its
  certificate (PEM) is public; its private key is kept only sealed (``atak_pki.CaBox``: Fernet under a
  key derived from ATALAIA_SECRET_KEY, with the field's id sealed in), is never exported and never
  leaves the server process.
- ``atak_certs``: every client certificate the field's CA issued, by the SHA-256 of its DER encoding
  and its serial number: the device's name, who holds it (an account with a role on the field, or
  nobody for one the operator issued with ``python -m atalaia_server atak issue``), whether it may see
  player positions (only for a holder with the field's ``gm`` or ``marshal`` role, P4R18, checked again
  at every connection), when it expires, when and by whom it was revoked and when it last connected.
  A certificate issued through the API whose holder's account is gone is refused; the operator's
  (``issued_via = 'command'``) never had one. The relay accepts a certificate only if its row is here,
  belongs to the CA's field, is not revoked and has not expired: a list of what is allowed, so a
  deleted row is refused too.

Personal data (``personal_data.py``): a holder's certificates are theirs (access and export); erasure
revokes them and unlinks the account; a row goes 30 days after it expired. The private keys of the
client certificates are never stored: they exist only in the data package the issuer downloads once.
Imported by ``models`` so ``Base.metadata`` (Alembic, ``tests.test_migrations``) has them.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (Boolean, CheckConstraint, DateTime, ForeignKey, Index, LargeBinary, String, Text, func,
                        text)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .ids import uuid7
from .models import Base

DEVICE_NAME_MAX = 48


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7,
                         server_default=text("gen_random_uuid()"))


class AtakCa(Base):
    """A field's ATAK certificate authority (one per field)."""

    __tablename__ = "atak_cas"
    __table_args__ = (CheckConstraint("ski ~ '^[0-9a-f]{40}$'", name="ski"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    field_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"), nullable=False,
                                                unique=True)
    cert_pem: Mapped[str] = mapped_column(Text, nullable=False)
    key_sealed: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    ski: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)  # subject key identifier, hex
    not_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AtakCert(Base):
    """A client certificate the field's CA issued to one ATAK device."""

    __tablename__ = "atak_certs"
    __table_args__ = (
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256"),
        CheckConstraint("serial ~ '^[0-9a-f]{1,40}$'", name="serial"),
        CheckConstraint(f"char_length(device_name) BETWEEN 1 AND {DEVICE_NAME_MAX}", name="device_name"),
        CheckConstraint("not_after > issued_at", name="lifetime"),
        CheckConstraint("issued_via IN ('api', 'command')", name="issued_via"),
        Index("ix_atak_certs_field_id", "field_id", "issued_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    field_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"), nullable=False)
    serial: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    device_name: Mapped[str] = mapped_column(String(DEVICE_NAME_MAX), nullable=False)
    holder_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    positions: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    issued_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # "api": a field's admin or gm issued it for a holder (no holder any more: refused); "command": the
    # operator's ``atak issue``, with no holder (props and zones only).
    issued_via: Mapped[str] = mapped_column(String(8), nullable=False, server_default=text("'api'"))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    not_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    revoke_reason: Mapped[Optional[str]] = mapped_column(String(32))
    last_connected_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
