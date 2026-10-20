# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Personal data: access, export, erasure, consents and the retention purge (ADR-P4-8).

The one place that knows which tables hold personal data. **Rule for every
later plan phase** (ADR-P4-8's amendment): a table with personal data is
added here, to ``collect`` (access and export), ``erase`` and ``purge``, in
the same plan phase that adds the table, with tests in
``tests/test_personal_data.py``.

What holds personal data now (plan phases 10-12):

| Table | Access / export | Erasure | Purge |
| --- | --- | --- | --- |
| ``users`` | the profile (never the password hash or the TOTP secret) | anonymised in place: a ``deleted-...`` name, everything else cleared | (the anonymised row stays, it identifies nobody) |
| ``user_field_roles`` | the person's roles, with the field's name | deleted | (with the account) |
| ``sessions`` (+ ``refresh_tokens``) | address, user agent, times | deleted | 30 days after expiry or revocation |
| ``consents`` | every record | deleted | (with the account) |
| ``audit_log`` | the person's own entries, and entries about them (without who made them) | kept for the log's integrity, without addresses; the account it names is anonymised | after 36 months |
| ``user_game_roles`` (plan phase 13) | the person's roles per game, with the game (``games.json`` in the export) | deleted | with the game |
| ``games`` with ``game_events``, ``game_node_scores``, ``game_nodes`` (plan phase 13) | (not linked to an account: see below) | (nothing to unlink) | 24 months after the game ended (or was made, if it never ended) |
| ``field_player_ids`` (plan phase 14) | the person's player id at each field (``player_ids.json``) | deleted: the link to the person | (with the account) |
| ``chrono_readings``, ``chrono_violations``, ``chrono_rejects`` (plan phase 14) | the readings, violations and refused readings of the person's player ids, each record as signed (``chrono_records.json``) | kept, signatures intact; erasure removes the link (``field_player_ids``) | the field's ``default_retention_days`` (365) after the reading (a reject: after it first arrived) |
| ``replicas`` (plan phase 14) | the replicas of the person's player ids (in ``chrono_records.json``) | kept for the readings, without make, model and tag | the field's retention after the last change, once no reading names them |
| ``marshal_keys`` (plan phase 14) | the keys the person registered as a marshal (``marshal_keys.json``) | kept, so what they signed still verifies, without the link to the account | the field's retention after the key's period ended, once no reading needs it |

The synced games (plan phase 13) come from field controllers and hold no
account: their events carry only the field's pseudonymous player ids
(``player``: ``p-`` and 12 base32 characters, ADR-P4-8's amendment), never a
name, a federation number or a position (P4R25). Nothing links them to an
account until accounts adopt their player ids (plan phase 16), which then
adds them to access, export and erasure; until then the person's games are
the ones they hold a per-game role on (decision S13-10). The whole game goes
when its history retention ends.

The chrono registry (plan phase 14) is per field and pseudonymous too: a
reading names the field's ``player_id`` and the marshal who signed it. It is
the person's through ``field_player_ids``, the player ids their account holds
(adopted in plan phase 16, decision S14-3). Erasure deletes those links and
keeps the signed records as they are (ADR-P4-8: signatures stay valid), so
nothing leads from them to the person any more.

Erasure is anonymisation, not deletion (ADR-P4-8): the ``users`` row stays
under a random ``deleted-`` name with no email, no password and no consent,
so the rows that point at it (the audit log; game, chrono and history rows
from later plan phases) keep their integrity but no longer lead to the
person. The erasure itself is logged with no account and no address.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import secrets
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from sqlalchemy import DateTime, delete, func, literal, literal_column, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from . import chrono_registry
from .audit import record
from .models import (ROLE_BY_ID, AuditLog, ChronoReading, ChronoReject, Consent, Field, FieldPlayerId, Game,
                     MarshalKey, Replica, User, UserFieldRole, UserGameRole, UserSession)

log = logging.getLogger("atalaia.server.purge")

FORMAT = "atalaia-personal-data/1"
ACCOUNT = "account"
CHRONO_SHARING = "chrono_sharing"  # per field (consents.field_id): plan phase 14
PURPOSES = (ACCOUNT, CHRONO_SHARING)
ERASED_PREFIX = "deleted-"
ERASED_PASSWORD = "DELETED"  # not an Argon2 hash: passwords.verify_password never accepts it

# Retention (ADR-P4-8's table; decisions S12-6, S13-10, S14-8). Guest data comes with its table (plan
# phase 16); game history is 24 months, fixed until fields get a setting; the chrono registry keeps each
# field's fields.default_retention_days (365 by default, the controller's CHRONO_RETENTION_DAYS).
SESSION_RETENTION = timedelta(days=30)   # after a session expired or was revoked
AUDIT_RETENTION = timedelta(days=1095)   # 36 months
GAME_RETENTION = timedelta(days=730)     # 24 months: game history, after the game ended


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _str(value: Any) -> Optional[str]:
    return str(value) if value is not None else None


def give_consent(db: AsyncSession, user_id: uuid.UUID, purpose: str, notice_version: str,
                 given_at: Optional[datetime] = None, field_id: Optional[uuid.UUID] = None) -> None:
    """Records a consent in the caller's transaction (``chrono_sharing`` is for one field)."""
    if purpose not in PURPOSES:
        raise ValueError(f"unknown consent purpose {purpose!r}")
    if (purpose == CHRONO_SHARING) != (field_id is not None):
        raise ValueError("chrono_sharing is given per field, and only it")
    db.add(Consent(user_id=user_id, purpose=purpose, notice_version=notice_version, field_id=field_id,
                   given_at=given_at or datetime.now(timezone.utc)))


async def collect(db: AsyncSession, user: User, current_session: Optional[uuid.UUID] = None) -> dict[str, Any]:
    """Everything the server holds about the account (GDPR Art. 15), as JSON-ready data."""
    roles = await db.execute(
        select(UserFieldRole.field_id, Field.name, UserFieldRole.role_id, UserFieldRole.granted_at)
        .join(Field, Field.id == UserFieldRole.field_id)
        .where(UserFieldRole.user_id == user.id).order_by(Field.name, UserFieldRole.role_id))
    sessions = await db.scalars(select(UserSession).where(UserSession.user_id == user.id)
                                .order_by(UserSession.created_at))
    own = await db.scalars(select(AuditLog).where(AuditLog.user_id == user.id).order_by(AuditLog.id))
    # Entries other people made about this account (a role granted, say): what and when, not who.
    about = await db.scalars(select(AuditLog).where(
        AuditLog.resource == "user", AuditLog.resource_id == user.id,
        or_(AuditLog.user_id.is_(None), AuditLog.user_id != user.id)).order_by(AuditLog.id))
    consents = await db.scalars(select(Consent).where(Consent.user_id == user.id).order_by(Consent.given_at))
    player_ids = await db.execute(select(FieldPlayerId.field_id, Field.name, FieldPlayerId.player_id,
                                         FieldPlayerId.created_at).join(Field, Field.id == FieldPlayerId.field_id)
                                  .where(FieldPlayerId.user_id == user.id).order_by(Field.name))
    keys = await db.execute(select(MarshalKey, Field.name).join(Field, Field.id == MarshalKey.field_id)
                            .where(MarshalKey.user_id == user.id).order_by(Field.name, MarshalKey.valid_from))
    game_roles = await db.execute(
        select(UserGameRole.role_id, UserGameRole.granted_at, Game, Field.name)
        .join(Game, Game.id == UserGameRole.game).join(Field, Field.id == Game.field_id)
        .where(UserGameRole.user_id == user.id).order_by(Game.controller_created_at, UserGameRole.role_id))
    return {
        "format": FORMAT,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "user": {
            "id": str(user.id), "username": user.username, "email": user.email,
            "created_at": _iso(user.created_at), "updated_at": _iso(user.updated_at),
            "last_login_at": _iso(user.last_login_at), "gdpr_consent_at": _iso(user.gdpr_consent_at),
            "data_retention_days": user.data_retention_days, "totp_enabled": user.totp_enabled,
            "server_admin": user.server_admin,
        },
        "field_roles": [{"field_id": str(field_id), "field": name, "role": ROLE_BY_ID[role_id],
                         "granted_at": _iso(granted_at)} for field_id, name, role_id, granted_at in roles],
        "sessions": [{"id": str(s.id), "created_at": _iso(s.created_at), "expires_at": _iso(s.expires_at),
                      "revoked_at": _iso(s.revoked_at), "last_used_at": _iso(s.last_used_at), "mfa": s.mfa,
                      "ip_address": _str(s.ip_address), "user_agent": s.user_agent,
                      "current": s.id == current_session} for s in sessions],
        "audit_log": [{"id": a.id, "action": a.action, "resource": a.resource, "resource_id": _str(a.resource_id),
                       "details": a.details, "ip_address": _str(a.ip_address), "created_at": _iso(a.created_at)}
                      for a in own],
        "audit_log_about_you": [{"id": a.id, "action": a.action, "details": a.details,
                                 "created_at": _iso(a.created_at)} for a in about],
        "consents": [{"purpose": c.purpose, "field_id": _str(c.field_id), "notice_version": c.notice_version,
                      "given_at": _iso(c.given_at), "withdrawn_at": _iso(c.withdrawn_at)} for c in consents],
        "games": [{"game": str(g.id), "field": field_name, "name": g.name, "mode_id": g.mode_id,
                   "state": g.state, "started_at": _iso(g.started_at), "ended_at": _iso(g.ended_at),
                   "role": ROLE_BY_ID[role_id], "granted_at": _iso(granted_at)}
                  for role_id, granted_at, g, field_name in game_roles],
        "player_ids": [{"field_id": str(field_id), "field": name, "player_id": pid, "linked_at": _iso(at)}
                       for field_id, name, pid, at in player_ids],
        "chrono_records": await chrono_registry.my_history(db, user.id),
        "marshal_keys": [{"field": name, **chrono_registry.key_json(k)} for k, name in keys],
    }


README = """Atalaia site server: your personal data (format {format})
Os seus dados pessoais no servidor do campo (formato {format})

Made {generated_at} for the account {username}.

Every file is JSON (UTF-8). / Todos os ficheiros são JSON (UTF-8).

profile.json        Your account: id, username, email, when it was made and last
                    used, when you consented, whether TOTP is on. The password
                    hash and the TOTP secret are not included: they are security
                    credentials, not information about you.
                    A sua conta (sem o hash da palavra-passe nem o segredo TOTP).
field_roles.json    Your roles on each field (player, marshal, gm, ...).
                    Os seus papéis em cada campo.
sessions.json       Your logins: address, browser or app (user agent), when they
                    started, were last used, expire or were ended.
                    As suas sessões: endereço, navegador ou app, datas.
audit_log.json      What the server logged about your own actions (logins, failed
                    logins, changes), with the address. Kept for 36 months.
                    O registo das suas ações, guardado 36 meses.
audit_log_about_you.json
                    What others did to your account (a role granted or removed),
                    without who did it.
                    O que outras pessoas fizeram à sua conta, sem dizer quem.
consents.json       Your consents: purpose, the privacy notice's version, when given
                    and when withdrawn.
                    Os seus consentimentos.
games.json          The games you hold a role on (gm, marshal, player...): the game,
                    its field, when it ran, your role.
                    Os jogos em que tem um papel.
player_ids.json     Your player id at each field (the field's pseudonymous id for you).
                    O seu identificador de jogador em cada campo.
chrono_records.json Per field: your chrono readings, each with the record exactly as
                    the marshal signed it (record_json) and the marshal's public key,
                    so anyone can check it; your replicas; spot checks over the limit;
                    readings the server could not verify.
                    As suas leituras de cronógrafo, assinadas pelo marshal, as suas
                    réplicas e as infrações.
marshal_keys.json   The public keys you registered as a marshal (never a private key:
                    it stays on your phone).
                    As chaves públicas que registou como marshal.

Game events name players only by the field's pseudonymous player ids, which
are not linked to accounts yet. Positions never reach the site server.
"""


def export_zip(data: dict[str, Any]) -> bytes:
    """The portable copy (GDPR Art. 20): a ZIP of JSON files and a README.txt."""
    files = {
        "profile.json": data["user"], "field_roles.json": data["field_roles"], "sessions.json": data["sessions"],
        "audit_log.json": data["audit_log"], "audit_log_about_you.json": data["audit_log_about_you"],
        "consents.json": data["consents"], "games.json": data["games"], "player_ids.json": data["player_ids"],
        "chrono_records.json": data["chrono_records"], "marshal_keys.json": data["marshal_keys"],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(f"export/{name}", json.dumps(content, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
        zf.writestr("export/README.txt", README.format(format=FORMAT, generated_at=data["generated_at"],
                                                       username=data["user"]["username"]))
    return buffer.getvalue()


async def erase(db: AsyncSession, user_id: uuid.UUID, reason: str = "user_request") -> str:
    """Anonymises the account (GDPR Art. 17, ADR-P4-8) in the caller's transaction; returns the
    anonymised name. The caller commits."""
    tombstone = ERASED_PREFIX + secrets.token_hex(8)
    await db.execute(update(User).where(User.id == user_id).values(
        username=tombstone, email=None, password_hash=ERASED_PASSWORD, totp_secret_enc=None, totp_enabled=False,
        totp_last_step=None, server_admin=False, gdpr_consent_at=None, data_retention_days=None,
        last_login_at=None).execution_options(synchronize_session=False))
    await db.execute(delete(UserFieldRole).where(UserFieldRole.user_id == user_id))
    await db.execute(delete(UserSession).where(UserSession.user_id == user_id))  # refresh tokens cascade
    await db.execute(delete(Consent).where(Consent.user_id == user_id))
    await db.execute(delete(UserGameRole).where(UserGameRole.user_id == user_id))
    # The chrono registry (ADR-P4-8 as amended): signed records stay as they are; the person's replicas
    # lose what describes them; marshal keys stay for the records they signed, unlinked; then the links
    # from the account to its per-field player ids go, and with them every way back to the person.
    await db.execute(update(Replica).where(chrono_registry.owned_by(user_id, Replica.owner_player_id,
                                                                    Replica.field_id))
                     .values(make_model=None, tag_type=None, tag_uid=None).execution_options(synchronize_session=False))
    await db.execute(update(MarshalKey).where(MarshalKey.user_id == user_id).values(user_id=None)
                     .execution_options(synchronize_session=False))
    await db.execute(delete(FieldPlayerId).where(FieldPlayerId.user_id == user_id))
    # The log keeps what happened, not where from: the person's addresses go.
    await db.execute(update(AuditLog).where(AuditLog.user_id == user_id, AuditLog.ip_address.is_not(None))
                     .values(ip_address=None))
    record(db, "gdpr_erasure", None, resource="user", resource_id=user_id, details={"reason": reason})
    return tombstone


async def purge(db: AsyncSession, now: Optional[datetime] = None, dry_run: bool = False) -> dict[str, int]:
    """Deletes what is past its retention (ADR-P4-8) and commits; returns the counts. With
    ``dry_run`` it counts the same rows and rolls back."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - SESSION_RETENTION
    sessions = await db.execute(delete(UserSession).where(
        or_(UserSession.expires_at < cutoff, UserSession.revoked_at < cutoff)))
    audit = await db.execute(delete(AuditLog).where(AuditLog.created_at < now - AUDIT_RETENTION))
    # A game with its events, counters, nodes and per-game roles (they cascade).
    games = await db.execute(delete(Game).where(
        func.coalesce(Game.ended_at, Game.controller_created_at) < now - GAME_RETENTION))
    counts = {"sessions": sessions.rowcount or 0, "audit_log": audit.rowcount or 0, "games": games.rowcount or 0}
    counts.update(await _purge_chrono(db, now))
    if dry_run:
        await db.rollback()
        return counts
    record(db, "retention_purge", None, details=counts)
    await db.commit()
    return counts


def _past_retention(now: datetime, field_column: Any, when: Any) -> Any:
    """``when`` is older than the retention of the field in ``field_column`` (``fields.default_retention_days``)."""
    cutoff = literal(now, DateTime(timezone=True)) - literal_column("interval '1 day'") * Field.default_retention_days
    return select(Field.id).where(Field.id == field_column, when < cutoff).exists()


async def _purge_chrono(db: AsyncSession, now: datetime) -> dict[str, int]:
    """The chrono registry after each field's retention: readings (their violations cascade) by the
    record's time, refused readings by their first arrival, then replicas and marshal keys that no
    reading needs any more."""
    readings = await db.execute(delete(ChronoReading).where(
        _past_retention(now, ChronoReading.field_id, ChronoReading.timestamp)))
    rejects = await db.execute(delete(ChronoReject).where(
        _past_retention(now, ChronoReject.field_id, ChronoReject.first_seen_at)))
    replicas = await db.execute(delete(Replica).where(
        _past_retention(now, Replica.field_id, Replica.updated_at),
        ~select(ChronoReading.id).where(ChronoReading.field_id == Replica.field_id,
                                        ChronoReading.replica_id == Replica.replica_id).exists()))
    keys = await db.execute(delete(MarshalKey).where(
        _past_retention(now, MarshalKey.field_id, func.coalesce(MarshalKey.revoked_at, MarshalKey.valid_until)),
        ~select(ChronoReading.id).where(ChronoReading.marshal_key == MarshalKey.id).exists()))
    return {"chrono_readings": readings.rowcount or 0, "chrono_rejects": rejects.rowcount or 0,
            "replicas": replicas.rowcount or 0, "marshal_keys": keys.rowcount or 0}


async def live_server_admins(db: AsyncSession, other_than: uuid.UUID) -> int:
    """The other server administrators, their rows locked: two administrators erasing themselves at
    once cannot both see the other one still there."""
    rows = await db.scalars(select(User.id).where(User.server_admin.is_(True), User.id != other_than)
                            .order_by(User.id).with_for_update())
    return len(list(rows))


def seconds_until(now: datetime, hour: int) -> float:
    """Seconds from ``now`` (aware) to the next ``hour``:00 UTC."""
    now = now.astimezone(timezone.utc)
    nxt = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(days=1)
    return (nxt - now).total_seconds()


async def purge_daily(maker: async_sessionmaker[AsyncSession], hour: int,
                      now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
    """Runs ``purge`` every day at ``hour``:00 UTC until cancelled (the app's lifespan task).
    A failed run is logged and the next one is the next day; ``python -m atalaia_server purge``
    runs it by hand."""
    while True:
        await asyncio.sleep(seconds_until(now(), hour))
        try:
            async with maker() as db:
                counts = await purge(db)
            log.info("retention purge: %s", ", ".join(f"{k} {v}" for k, v in counts.items()))
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001  (the database down, say: tomorrow's run tries again)
            log.exception("retention purge failed")
