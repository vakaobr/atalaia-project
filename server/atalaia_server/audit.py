# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The audit log (ADR-P4-1's ``audit_log``): who did what, from where.

Rows are added in the caller's transaction, so an action and its record are
committed together. They never hold a password, a code, a token or the
username typed in a failed login (a password typed into the wrong box would
end up in the log); a failed login names the account only when it exists.

Actions written by plan phase 11: ``register``, ``login``, ``login_failed``,
``login_locked``, ``totp_failed``, ``totp_locked``, ``refresh_replay``,
``logout``, ``totp_enabled``, ``totp_disabled``, ``field_create``,
``role_grant``, ``role_revoke``, ``admin_create``. ``totp_reset`` (decision S11-7: ``reset-totp`` on the
command line; the operator, the reason and the sessions revoked are in ``details``) is written the same way, and so is ``password_set`` (decision SP-1: ``set-password``; never the password). Plan phase 12 adds
``profile_update`` (the names of the fields changed, never their values),
``password_change``, ``gdpr_erasure`` (no account, no address) and
``retention_purge`` (the counts deleted); a ``login_locked`` row says which
lockout tripped (``scope``). The remote ATAK relay (Phase 4 follow-up FU5) adds
``atak_cert_issued``, ``atak_cert_revoked``, ``atak_connect`` (a device's
certificate accepted, with its address) and ``atak_refused`` (a certificate
of a known field refused after the TLS handshake, and why).
"""

from __future__ import annotations

import ipaddress
import uuid
from typing import Any, Optional

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from .models import AuditLog


def request_ip(request: Optional[Request]) -> Optional[str]:
    """The client's address as the INET column takes it, or None."""
    if request is None or request.client is None:
        return None
    try:
        return str(ipaddress.ip_address(request.client.host))
    except ValueError:
        return None


def record(db: AsyncSession, action: str, request: Optional[Request] = None, *,
           user_id: Optional[uuid.UUID] = None, resource: Optional[str] = None,
           resource_id: Optional[uuid.UUID] = None, details: Optional[dict[str, Any]] = None,
           address: Optional[str] = None) -> None:
    """One row; ``address`` is the client's address when there is no HTTP request (the ATAK relay's TLS
    connections, FU5)."""
    ip = request_ip(request)
    if ip is None and address is not None:
        try:
            ip = str(ipaddress.ip_address(address))
        except ValueError:
            ip = None
    db.add(AuditLog(user_id=user_id, action=action, resource=resource, resource_id=resource_id,
                    details=details, ip_address=ip))
