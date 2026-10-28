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
| ``user_identities`` (LG-1) | the provider and subject of each social login linked, and when (``identities.json``) | deleted | (with the account) |
| ``passkeys`` (LG-2) | the name, when made and last used, the host name (``passkeys.json``; never a key) | deleted | (with the account) |
| ``oidc_logins`` (LG-1) | (a login in progress, ten minutes: nothing to give) | deleted | when it expires |
| ``consents`` | every record | deleted | (with the account) |
| ``audit_log`` | the person's own entries, and entries about them (without who made them) | kept for the log's integrity, without addresses; the account it names is anonymised | after 36 months |
| ``user_game_roles`` (plan phase 13) | the person's roles per game, with the game (``games.json`` in the export) | deleted | with the game |
| ``games`` with ``game_events``, ``game_node_scores``, ``game_nodes`` (plan phase 13) | (not linked to an account: see below) | (nothing to unlink) | 24 months after the game ended (or was made, if it never ended) |
| ``field_player_ids`` (plan phase 14) | the person's player id at each field (``player_ids.json``) | deleted: the link to the person | (with the account) |
| ``chrono_readings``, ``chrono_violations``, ``chrono_rejects`` (plan phase 14) | the readings, violations and refused readings of the person's player ids, each record as signed (``chrono_records.json``) | kept, signatures intact; erasure removes the link (``field_player_ids``) | the field's ``default_retention_days`` (365) after the reading (a reject: after it first arrived) |
| ``replicas`` (plan phase 14) | the replicas of the person's player ids (in ``chrono_records.json``) | kept for the readings, without make, model and tag | the field's retention after the last change, once no reading names them |
| ``marshal_keys`` (plan phase 14) | the keys the person registered as a marshal (``marshal_keys.json``) | kept, so what they signed still verifies, without the link to the account | the field's retention after the key's period ended, once no reading needs it |
| ``scheduled_games`` (plan phase 15) | the games the person scheduled as the field's staff (``scheduled_games.json``) | kept (they are the field's), without the link to the account (``created_by``) | 24 months after the game's end, as game history |
| ``game_registrations.paid_by`` and ``outcome_by``, ``scheduled_games.roster_*`` (FU7) | the registrations' ``paid_at`` (``registrations.json``); that staff marked others' registrations paid or no-show is in the person's own audit log entries (``registration_paid``, ``registration_no_show``, never a name); a roster pull has no person (a key's label and a User-Agent) | ``paid_by`` and ``outcome_by`` cleared (the marks stay as the field's record) | with the registration or the scheduled game |
| ``game_registrations`` with ``registration_replicas`` (plan phase 16) | the person's registrations with their pre-declared replicas and outcomes (``registrations.json``; never the ticket's hash) | a game not yet started: cancelled; every one: the account, the name, the team preference, the federation (membership) number, the APD and its expiry and the ticket's hash cleared, the replicas' make and model too (the outcome and the declarations' states stay, the field's history) | the federation (membership) number, the APD and its expiry 30 days after the game (ADR-P4-11, APD-*); the rest with the scheduled game (24 months) |
| ``player_id_claims`` (plan phase 16) | the person's claims of a phone's player id (``player_id_claims.json``) | deleted | 30 days after the claim was made |
| imported ``game_registrations`` (plan phase 17: ``source`` not ``site``, no account) with their replicas | (no account: the field's staff see them in the game's list and its CSV export) | (no account to erase; the field answers a request from the person, as the data controller of what it imported) | deleted 30 days after the game, the guest rule (ADR-P4-8, ADR-P4-12) |
| ``platform_links``, ``external_game_links`` (plan phase 17) | (the field's: no person in them) | | |
| ``club_members`` (plan phase 18) | the person's clubs, club role and invitations (``clubs.json``) | deleted (a club whose last admin goes keeps its profile; a server administrator can still manage it) | an invitation not accepted, 30 days after it was made; a membership with the account |
| ``club_reports`` (plan phase 18) | the reports the person made while logged in (``club_reports.json``; never an address) | kept for the moderation record, without the link to the account (reporter and deciding administrator) | 12 months after the decision (an open report stays until decided) |
| ``games`` and ``game_events`` as the person's game history (plan phase 20) | the games whose events name one of the person's player ids (``player``, ``owner``, ``holder``), with those events and the game's totals, and the games their registrations were checked in to (``game_history.json``) | nothing to change: the events keep the field's pseudonymous ids; erasure deletes ``field_player_ids``, the only link to the person | the field's ``retention_days`` (``field_history_settings``, 30-730, 730 by default: ADR-P4-8's 24 months) after the game ended |
| ``game_score_samples``, ``field_history_settings``, ``field_scenarios``, ``field_scenario_revisions``, ``field_presets`` (plan phase 20) | (the field's: no person in them; who saved a scenario or a preset is only in the audit log) | | the samples with their game |
| ``clubs``, ``field_teams``, ``branding_images``, the field's branding columns (plan phase 18) | (a club's or a field's public profile: no person in them; who made a club is ``created_by``, unlinked at erasure) | ``created_by`` and ``hidden_by`` cleared | an image nothing uses, a day after its upload |
| ``firmware_releases`` (plan phase 19) | (the server's catalogue: no person in it; who added a release is ``added_by``, unlinked at erasure) | ``added_by`` cleared | (kept: withdrawn releases stay, marked) |
| the remote GM's audit rows (plan phase 19: ``remote_gm_command``, ``remote_gm_denied``) | in the audit log as every other action | as every other audit row: kept without the person's addresses | 36 months, as the audit log |
| ``atak_certs`` (Phase 4 follow-up FU5) | the ATAK certificates the person holds: device, field, dates, whether positions, last connection (``atak_certificates.json``; never a key) | revoked (``erasure``), the device's name replaced and the account unlinked (holder, issuer, revoker) | 30 days after the certificate expired |
| ``preview_feedback`` (decisions PV-*; only a preview server writes it) | (no account, no address: what a visitor typed, which no one can be matched to; the administrators answer a request to see or delete one by hand: ``DELETE /api/v1/admin/feedback/{id}``) | | the optional contact after 90 days, the row after 12 months |
| ``atak_cas`` and the relay's audit rows (FU5: ``atak_cert_issued``, ``atak_cert_revoked``, ``atak_connect`` with the device's address, ``atak_refused``) | (a CA is the field's: no person in it) / in the audit log | / as every other audit row, and their details as the certificate's row (FU5-18): the person's devices' names replaced, the account's id taken out of ``holder_id`` and ``issued_by`` | / 36 months, as the audit log |

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

The schedule (plan phase 15) is the field's: a scheduled game names only the staff
account that made it (``created_by``), and the public pages and feeds show no person at all.
Registrations (plan phase 16) are the person's: a display name for the game, a team
preference, the federation (membership) number, the APD and its expiry when the game or the field's rule asks for them, the pre-declared replicas
and, from the controller after the game, the outcome. The roster sent to the field's
controller holds only what the check-in holds (the controller's own 30-day rule then
applies there); what comes back holds no name. The account's player id at a field is made
on its first registration there or adopted from the phone (a claim the controller confirms);
from then on the field's synced events and chrono records under that id are the person's
(``field_player_ids``), and erasure drops that link as before.
Imported registrations (plan phase 17) belong to no account: a list the field brought from
another platform, with only the import's columns (any other column is never read). The field is
the data controller for them and must have its own basis for that list (the import asks the staff
to confirm it); they are guests, so the whole registration goes 30 days after its game.

Clubs (plan phase 18) are organisations' public profiles; who belongs to one is the person's
(``club_members``). A membership exists only once the invited person accepts it (decision S18-9).
Reports of club pages keep the reporting account only when it was logged in, and never an address.

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
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import DateTime, cast, delete, func, literal, literal_column, or_, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from . import chrono_registry, tenancy
from .atak_models import AtakCert
from .preview_models import CONTACT_RETENTION, RETENTION as FEEDBACK_RETENTION, PreviewFeedback
from .audit import record
from .models import (ROLE_BY_ID, AuditLog, ChronoReading, ChronoReject, Club, ClubMember, ClubReport, Consent, Field,
                     FieldPlayerId, FirmwareRelease, Game, GameRegistration, MarshalKey, PlayerIdClaim, RegistrationReplica, Replica,
                     ScheduledGame, User, UserFieldRole, UserGameRole, UserSession, OidcLogin, Passkey, UserIdentity)
from .services import branding, history

log = logging.getLogger("atalaia.server.purge")

FORMAT = "atalaia-personal-data/1"
ACCOUNT = "account"
CHRONO_SHARING = "chrono_sharing"  # per field (consents.field_id): plan phase 14
PURPOSES = (ACCOUNT, CHRONO_SHARING)
ERASED_PREFIX = "deleted-"
ERASED_PASSWORD = "DELETED"  # not an Argon2 hash: passwords.verify_password never accepts it

# Retention (ADR-P4-8's table; decisions S12-6, S13-10, S14-8, S16-7, S17-5). Guest data is plan phase 17's
# imports (GUEST_RETENTION); game history is 24 months, or less per field (plan phase 20); the chrono registry
# keeps each field's fields.default_retention_days (365 by default, the controller's CHRONO_RETENTION_DAYS).
SESSION_RETENTION = timedelta(days=30)   # after a session expired or was revoked
AUDIT_RETENTION = timedelta(days=1095)   # 36 months
GAME_RETENTION = timedelta(days=730)     # 24 months: game history, after the game ended (scheduled games too)
FEDERATION_RETENTION = timedelta(days=30)  # a registration's federation number, after the game (ADR-P4-11)
CLAIM_RETENTION = timedelta(days=30)     # a claim of a phone's player id, after it was made
GUEST_RETENTION = timedelta(days=30)     # an imported registration (no account), after its game (ADR-P4-8)
INVITATION_RETENTION = timedelta(days=30)  # a club invitation not accepted, after it was made (plan phase 18)
REPORT_RETENTION = timedelta(days=365)   # a club page report, after its decision (plan phase 18)
ATAK_CERT_RETENTION = timedelta(days=30)  # an ATAK certificate, after it expired (FU5)


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


async def account_consent(db: AsyncSession, user_id: uuid.UUID, current_version: str) -> dict[str, Any]:
    """Where the account's ``account`` consent stands against the privacy notice's current version (CONS-2):
    ``status`` is ``current`` (given for the current version), ``outdated`` (given for another version: the account
    is asked to consent again) or ``missing`` (no live consent)."""
    live = await db.scalar(select(Consent).where(Consent.user_id == user_id, Consent.purpose == ACCOUNT,
                                                 Consent.field_id.is_(None), Consent.withdrawn_at.is_(None)))
    status = "missing" if live is None else ("current" if live.notice_version == current_version else "outdated")
    return {"status": status, "version": live.notice_version if live is not None else None,
            "current_version": current_version, "given_at": _iso(live.given_at) if live is not None else None}


async def renew_account_consent(db: AsyncSession, user: User, version: str) -> Optional[str]:
    """Consent again, to ``version``, in the caller's transaction (the caller locked ``user`` and commits): the live
    consent for another version ends (``withdrawn_at``: it was replaced, not taken back) and a new one is
    recorded; ``users.gdpr_consent_at`` becomes its time. Returns the version replaced, None when the account had no
    live consent. Already consented to ``version``: nothing changes."""
    live = await db.scalar(select(Consent).where(Consent.user_id == user.id, Consent.purpose == ACCOUNT,
                                                 Consent.field_id.is_(None), Consent.withdrawn_at.is_(None))
                           .with_for_update())
    if live is not None and live.notice_version == version:
        return version
    now = datetime.now(timezone.utc)
    if live is not None:
        live.withdrawn_at = now
        await db.flush()  # the one live consent per purpose: the old one ends before the new one starts
    give_consent(db, user.id, ACCOUNT, version, now)
    user.gdpr_consent_at = now
    return live.notice_version if live is not None else None


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
    identities = await db.scalars(select(UserIdentity).where(UserIdentity.user_id == user.id)
                                  .order_by(UserIdentity.created_at))
    passkeys = await db.scalars(select(Passkey).where(Passkey.user_id == user.id).order_by(Passkey.created_at))
    player_ids = await db.execute(select(FieldPlayerId.field_id, Field.name, FieldPlayerId.player_id,
                                         FieldPlayerId.created_at).join(Field, Field.id == FieldPlayerId.field_id)
                                  .where(FieldPlayerId.user_id == user.id).order_by(Field.name))
    keys = await db.execute(select(MarshalKey, Field.name).join(Field, Field.id == MarshalKey.field_id)
                            .where(MarshalKey.user_id == user.id).order_by(Field.name, MarshalKey.valid_from))
    game_roles = await db.execute(
        select(UserGameRole.role_id, UserGameRole.granted_at, Game, Field.name)
        .join(Game, Game.id == UserGameRole.game).join(Field, Field.id == Game.field_id)
        .where(UserGameRole.user_id == user.id).order_by(Game.controller_created_at, UserGameRole.role_id))
    scheduled = await db.execute(
        select(ScheduledGame, Field.name).join(Field, Field.id == ScheduledGame.field_id)
        .where(ScheduledGame.created_by == user.id).order_by(ScheduledGame.starts_at))
    regs = list(await db.execute(
        select(GameRegistration, ScheduledGame, Field.name).join(ScheduledGame, ScheduledGame.id ==
                                                                 GameRegistration.scheduled_game)
        .join(Field, Field.id == GameRegistration.field_id)
        .where(GameRegistration.user_id == user.id).order_by(ScheduledGame.starts_at, GameRegistration.id)))
    reps = {r.id: [] for r, _, _ in regs}
    if reps:
        for d in await db.scalars(select(RegistrationReplica).where(RegistrationReplica.registration.in_(list(reps)))
                                  .order_by(RegistrationReplica.position)):
            reps[d.registration].append(d)
    claims = await db.scalars(select(PlayerIdClaim).where(PlayerIdClaim.user_id == user.id)
                              .order_by(PlayerIdClaim.created_at))
    clubs = await db.execute(select(ClubMember, Club).join(Club, Club.id == ClubMember.club_id)
                             .where(ClubMember.user_id == user.id).order_by(Club.slug))
    reports = await db.execute(select(ClubReport, Club.slug).join(Club, Club.id == ClubReport.club_id)
                               .where(ClubReport.reporter_id == user.id).order_by(ClubReport.created_at))
    return {
        "format": FORMAT,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "user": {
            "id": str(user.id), "username": user.username, "email": user.email,
            "created_at": _iso(user.created_at), "updated_at": _iso(user.updated_at),
            "last_login_at": _iso(user.last_login_at), "gdpr_consent_at": _iso(user.gdpr_consent_at),
            "totp_enabled": user.totp_enabled,
            "has_password": user.password_hash is not None, "server_admin": user.server_admin,
        },
        # Login methods (LG-1, LG-2): the social logins linked (provider and the subject it gave) and the
        # passkeys (name, when, where it was made for). Never a key, never a credential id.
        "identities": [{"provider": i.provider, "subject": i.subject, "linked_at": _iso(i.created_at),
                        "last_login_at": _iso(i.last_login_at)} for i in identities],
        "passkeys": [{"id": str(k.id), "name": k.name, "rp_id": k.rp_id, "backed_up": k.backed_up,
                      "transports": k.transports, "created_at": _iso(k.created_at),
                      "last_used_at": _iso(k.last_used_at)} for k in passkeys],
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
        "player_id_claims": [{"field_id": str(c.field_id), "player_id": c.player_id, "status": c.status,
                              "created_at": _iso(c.created_at), "decided_at": _iso(c.decided_at)} for c in claims],
        "registrations": [{"id": str(r.id), "field": name, "scheduled_game_id": str(g.id), "title": g.title,
                           "starts_at": _iso(g.starts_at), "player_id": r.player_id, "display_name": r.display_name,
                           "team_preference": r.team_preference, "federation_number": r.federation_number,
                           "membership_number": r.federation_number, "apd_id": r.apd_id,
                           "membership_expires": r.membership_expires.isoformat() if r.membership_expires else None,
                           "status": r.status, "source": r.source, "created_at": _iso(r.created_at),
                           "updated_at": _iso(r.updated_at), "outcome_at": _iso(r.outcome_at),
                           "paid_at": _iso(r.paid_at),
                           "replicas": [{"declaration_id": str(d.declaration_id),
                                         "replica_id": _str(d.replica_id), "type": d.replica_type,
                                         "class": d.replica_class, "make_model": d.make_model, "state": d.state}
                                        for d in reps[r.id]]}
                          for r, g, name in regs],
        "chrono_records": await chrono_registry.my_history(db, user.id),
        "marshal_keys": [{"field": name, **chrono_registry.key_json(k)} for k, name in keys],
        "scheduled_games": [{"id": str(g.id), "field_id": str(g.field_id), "field": name, "title": g.title,
                             "starts_at": _iso(g.starts_at), "ends_at": _iso(g.ends_at), "status": g.status,
                             "created_at": _iso(g.created_at)} for g, name in scheduled],
        "clubs": [{"club_id": str(c.id), "slug": c.slug, "name": c.name, "role": m.role,
                   "invited_at": _iso(m.created_at), "accepted_at": _iso(m.accepted_at),
                   "created_by_you": c.created_by == user.id} for m, c in clubs],
        "club_reports": [{"id": str(r.id), "club": slug, "reason": r.reason, "text": r.text, "status": r.status,
                          "created_at": _iso(r.created_at), "decided_at": _iso(r.decided_at)} for r, slug in reports],
        "game_history": await history.player_history(db, user.id),
        "atak_certificates": [{"id": str(c.id), "field_id": str(c.field_id), "field": name,
                               "device_name": c.device_name, "positions": c.positions, "issued_at": _iso(c.issued_at),
                               "not_after": _iso(c.not_after), "revoked_at": _iso(c.revoked_at),
                               "last_connected_at": _iso(c.last_connected_at)}
                              for c, name in await db.execute(
                                  select(AtakCert, Field.name).join(Field, Field.id == AtakCert.field_id)
                                  .where(AtakCert.holder_id == user.id).order_by(AtakCert.issued_at))],
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
identities.json     The social logins (Google, Microsoft, Apple) linked to your account:
                    the provider, the opaque subject it gave and when. Nothing else of
                    your profile there is ever read or kept.
                    Os inícios de sessão social ligados à conta.
passkeys.json       Your passkeys: the name you gave, when made and last used, the host
                    name they were made for. Never a key.
                    As suas chaves de acesso (passkeys), sem qualquer chave.
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
player_id_claims.json
                    Your requests to link a phone's player id at a field to your
                    account, and whether the field's controller confirmed them.
                    Os seus pedidos para ligar à conta o identificador de um telemóvel.
registrations.json  Your registrations for scheduled games: the name you chose for the
                    game, team preference, federation (membership) number, APD and expiry, the replicas you declared
                    and, after the game, whether you checked in; and when the field
                    marked it paid. Never the ticket.
                    As suas inscrições em jogos, com as réplicas declaradas.
chrono_records.json Per field: your chrono readings, each with the record exactly as
                    the marshal signed it (record_json) and the marshal's public key,
                    so anyone can check it; your replicas; spot checks over the limit;
                    readings the server could not verify.
                    As suas leituras de cronógrafo, assinadas pelo marshal, as suas
                    réplicas e as infrações.
marshal_keys.json   The public keys you registered as a marshal (never a private key:
                    it stays on your phone).
                    As chaves públicas que registou como marshal.
scheduled_games.json
                    The games you scheduled for a field as its staff (title, times,
                    status). They are the field's and stay when you erase your account,
                    without your name.
                    Os jogos que marcou para um campo, como staff.
clubs.json          The clubs you belong to or were invited to, with your club role.
                    Os clubes a que pertence e os convites recebidos, com o papel no clube.
club_reports.json   The reports of club pages you made while logged in.
                    As denúncias de páginas de clubes que fez com sessão iniciada.
game_history.json   The games you played, by your player ids at each field: the game, its
                    teams and final totals, and the events that name your player id (a
                    respawn, a tag scanned...); and the games you were checked in to from
                    a registration. Kept as the field's game history (24 months at most).
                    Os jogos em que participou: o jogo, as equipas, a pontuação final e os
                    eventos com o seu identificador de jogador.
atak_certificates.json
                    The ATAK certificates issued to you for a field's remote ATAK relay: the
                    device's name, when issued, when they expire or were revoked, whether
                    they see player positions, when they last connected. Never a key.
                    Os certificados ATAK emitidos para si: o dispositivo, as datas, se veem
                    posições de jogadores, a última ligação. Nunca uma chave.

Game events name players only by the field's pseudonymous player ids; yours
are listed in player_ids.json. Positions never reach the site server.
"""


def export_zip(data: dict[str, Any]) -> bytes:
    """The portable copy (GDPR Art. 20): a ZIP of JSON files and a README.txt."""
    files = {
        "profile.json": data["user"], "identities.json": data["identities"], "passkeys.json": data["passkeys"],
        "field_roles.json": data["field_roles"], "sessions.json": data["sessions"],
        "audit_log.json": data["audit_log"], "audit_log_about_you.json": data["audit_log_about_you"],
        "consents.json": data["consents"], "games.json": data["games"],
        "player_ids.json": data["player_ids"], "player_id_claims.json": data["player_id_claims"],
        "registrations.json": data["registrations"],
        "chrono_records.json": data["chrono_records"], "marshal_keys.json": data["marshal_keys"],
        "scheduled_games.json": data["scheduled_games"], "clubs.json": data["clubs"],
        "club_reports.json": data["club_reports"], "game_history.json": data["game_history"],
        "atak_certificates.json": data["atak_certificates"],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(f"export/{name}", json.dumps(content, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
        zf.writestr("export/README.txt", README.format(format=FORMAT, generated_at=data["generated_at"],
                                                       username=data["user"]["username"]))
    return buffer.getvalue()


ATAK_AUDIT = ("atak_cert_issued", "atak_cert_revoked", "atak_connect", "atak_refused")
ERASED_DEVICE = "erased"


async def erase(db: AsyncSession, user_id: uuid.UUID, reason: str = "user_request",
                revoked_atak: Optional[list[uuid.UUID]] = None) -> str:
    """Anonymises the account (GDPR Art. 17, ADR-P4-8) in the caller's transaction; returns the
    anonymised name. The caller commits. The ATAK certificates it revokes are added to ``revoked_atak``:
    the caller closes their relay connections once committed (``AtakRelay.drop_cert``)."""
    tombstone = ERASED_PREFIX + secrets.token_hex(8)
    await db.execute(update(User).where(User.id == user_id).values(
        username=tombstone, email=None, password_hash=ERASED_PASSWORD, totp_secret_enc=None, totp_enabled=False,
        totp_last_step=None, server_admin=False, gdpr_consent_at=None,
        last_login_at=None).execution_options(synchronize_session=False))
    await db.execute(delete(UserFieldRole).where(UserFieldRole.user_id == user_id))
    await db.execute(delete(UserSession).where(UserSession.user_id == user_id))  # refresh tokens cascade
    await db.execute(delete(UserIdentity).where(UserIdentity.user_id == user_id))
    await db.execute(delete(Passkey).where(Passkey.user_id == user_id))
    await db.execute(delete(OidcLogin).where(OidcLogin.user_id == user_id))
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
    # Registrations (plan phase 16): one for a game still to come is cancelled; every one loses the
    # account, the name, the team preference, the federation number and the ticket, and its replicas their
    # make and model. The outcome and the declarations' states stay, as the field's history.
    now = datetime.now(timezone.utc)
    upcoming = select(ScheduledGame.id).where(ScheduledGame.starts_at > now).scalar_subquery()
    await db.execute(update(GameRegistration).where(
        GameRegistration.user_id == user_id, GameRegistration.status == "registered",
        GameRegistration.scheduled_game.in_(upcoming)).values(status="cancelled", cancelled_at=now)
        .execution_options(synchronize_session=False))
    mine = select(GameRegistration.id).where(GameRegistration.user_id == user_id).scalar_subquery()
    await db.execute(update(RegistrationReplica).where(RegistrationReplica.registration.in_(mine))
                     .values(make_model=None).execution_options(synchronize_session=False))
    await db.execute(update(GameRegistration).where(GameRegistration.user_id == user_id).values(
        user_id=None, display_name=None, team_preference=None, federation_number=None, apd_id=None,
        membership_expires=None, ticket_hash=None, updated_at=now).execution_options(synchronize_session=False))
    await db.execute(delete(PlayerIdClaim).where(PlayerIdClaim.user_id == user_id))
    # What a staff account marked on registrations (paid, no-show: FU7) stays, without who marked it.
    await db.execute(update(GameRegistration).where(GameRegistration.paid_by == user_id).values(paid_by=None)
                     .execution_options(synchronize_session=False))
    await db.execute(update(GameRegistration).where(GameRegistration.outcome_by == user_id).values(outcome_by=None)
                     .execution_options(synchronize_session=False))
    # The field's schedule stays; who scheduled a game does not.
    await db.execute(update(ScheduledGame).where(ScheduledGame.created_by == user_id).values(created_by=None)
                     .execution_options(synchronize_session=False))
    # Clubs (plan phase 18): memberships and invitations go; clubs, reports and the moderation record stay,
    # without the links to the account.
    await db.execute(delete(ClubMember).where(ClubMember.user_id == user_id))
    await db.execute(update(ClubMember).where(ClubMember.added_by == user_id).values(added_by=None)
                     .execution_options(synchronize_session=False))
    await db.execute(update(Club).where(Club.created_by == user_id).values(created_by=None)
                     .execution_options(synchronize_session=False))
    await db.execute(update(Club).where(Club.hidden_by == user_id).values(hidden_by=None)
                     .execution_options(synchronize_session=False))
    await db.execute(update(ClubReport).where(ClubReport.reporter_id == user_id).values(reporter_id=None)
                     .execution_options(synchronize_session=False))
    await db.execute(update(ClubReport).where(ClubReport.decided_by == user_id).values(decided_by=None)
                     .execution_options(synchronize_session=False))
    # The firmware catalogue (plan phase 19) stays; who added a release does not.
    await db.execute(update(FirmwareRelease).where(FirmwareRelease.added_by == user_id).values(added_by=None)
                     .execution_options(synchronize_session=False))
    # The remote ATAK relay (FU5): the person's certificates are revoked, their devices' names go, and no
    # certificate keeps a link to the account (holder, issuer, revoker). The relay's audit rows keep what
    # happened, with the same done to their details (FU5-18): the devices' names of the person's
    # certificates replaced, the account's id out of ``holder_id`` and ``issued_by``.
    held = [str(i) for i in await db.scalars(select(AtakCert.id).where(AtakCert.holder_id == user_id))]
    revoked = await db.scalars(update(AtakCert).where(AtakCert.holder_id == user_id, AtakCert.revoked_at.is_(None))
                               .values(revoked_at=now, revoke_reason="erasure").returning(AtakCert.id)
                               .execution_options(synchronize_session=False))
    if revoked_atak is not None:
        revoked_atak.extend(revoked)
    await db.execute(update(AtakCert).where(AtakCert.holder_id == user_id)
                     .values(holder_id=None, device_name=ERASED_DEVICE).execution_options(synchronize_session=False))
    for column in (AtakCert.issued_by, AtakCert.revoked_by):
        await db.execute(update(AtakCert).where(column == user_id).values({column.key: None})
                         .execution_options(synchronize_session=False))
    atak_rows = AuditLog.action.in_(ATAK_AUDIT)
    if held:
        await db.execute(update(AuditLog).where(atak_rows, AuditLog.details["certificate"].astext.in_(held),
                                                AuditLog.details.has_key("device_name"))
                         .values(details=AuditLog.details.op("||")(cast({"device_name": ERASED_DEVICE}, JSONB)))
                         .execution_options(synchronize_session=False))
    for key in ("holder_id", "issued_by"):
        await db.execute(update(AuditLog).where(atak_rows, AuditLog.details[key].astext == str(user_id))
                         .values(details=AuditLog.details.op("||")(cast({key: None}, JSONB)))
                         .execution_options(synchronize_session=False))
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
    # Each field's game history retention (plan phase 20: field_history_settings, 24 months by default).
    games = await db.execute(delete(Game).where(history.past_retention(now)))
    counts = {"sessions": sessions.rowcount or 0, "audit_log": audit.rowcount or 0, "games": games.rowcount or 0}
    counts.update(await _purge_chrono(db, now))
    # The schedule (plan phase 15): a scheduled game is game history once it has ended.
    scheduled = await db.execute(delete(ScheduledGame).where(ScheduledGame.ends_at < now - GAME_RETENTION))
    counts["scheduled_games"] = scheduled.rowcount or 0
    # Registrations (plan phase 16): the federation number 30 days after the game; claims after 30 days.
    ended = select(ScheduledGame.id).where(ScheduledGame.ends_at < now - FEDERATION_RETENTION).scalar_subquery()
    federation = await db.execute(update(GameRegistration).where(
        or_(GameRegistration.federation_number.is_not(None), GameRegistration.apd_id.is_not(None),
            GameRegistration.membership_expires.is_not(None)), GameRegistration.scheduled_game.in_(ended))
        .values(federation_number=None, apd_id=None, membership_expires=None)
        .execution_options(synchronize_session=False))
    counts["federation_numbers"] = federation.rowcount or 0
    claims = await db.execute(delete(PlayerIdClaim).where(PlayerIdClaim.created_at < now - CLAIM_RETENTION))
    counts["player_id_claims"] = claims.rowcount or 0
    # Imported registrations (plan phase 17) are guests: the whole row 30 days after the game (replicas cascade).
    guests_ended = select(ScheduledGame.id).where(ScheduledGame.ends_at < now - GUEST_RETENTION).scalar_subquery()
    guests = await db.execute(delete(GameRegistration).where(
        GameRegistration.source != "site", GameRegistration.user_id.is_(None),
        GameRegistration.scheduled_game.in_(guests_ended)))
    counts["imported_registrations"] = guests.rowcount or 0
    # Clubs (plan phase 18): invitations never accepted, decided reports, then images nothing uses.
    invitations = await db.execute(delete(ClubMember).where(ClubMember.accepted_at.is_(None),
                                                            ClubMember.created_at < now - INVITATION_RETENTION))
    counts["club_invitations"] = invitations.rowcount or 0
    reports = await db.execute(delete(ClubReport).where(ClubReport.status != "open",
                                                        ClubReport.decided_at < now - REPORT_RETENTION))
    counts["club_reports"] = reports.rowcount or 0
    counts["branding_images"] = await branding.purge_images(db, now)
    atak = await db.execute(delete(AtakCert).where(AtakCert.not_after < now - ATAK_CERT_RETENTION))
    counts["atak_certificates"] = atak.rowcount or 0
    # A preview server's feedback (decisions PV-*): the contact is erased after 90 days, the row after a year.
    contacts = await db.execute(update(PreviewFeedback).where(
        PreviewFeedback.contact.is_not(None), PreviewFeedback.created_at < now - CONTACT_RETENTION)
        .values(contact=None, updated_at=now).execution_options(synchronize_session=False))
    counts["feedback_contacts"] = contacts.rowcount or 0
    feedback = await db.execute(delete(PreviewFeedback).where(PreviewFeedback.created_at < now - FEEDBACK_RETENTION))
    counts["preview_feedback"] = feedback.rowcount or 0
    logins = await db.execute(delete(OidcLogin).where(OidcLogin.expires_at < now))  # social logins never finished
    counts["oidc_logins"] = logins.rowcount or 0
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
                      now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                      tenants: Optional[Callable[[], Awaitable[list[tenancy.Tenant]]]] = None) -> None:
    """Runs ``purge`` every day at ``hour``:00 UTC until cancelled (the app's lifespan task).
    A failed run is logged and the next one is the next day; ``python -m atalaia_server purge``
    runs it by hand. In hosted mode (``tenants``: the active ones, plan phase 21) it runs once
    per field, each in its own tenant, and one field's failure does not stop the others."""
    while True:
        await asyncio.sleep(seconds_until(now(), hour))
        try:
            for tenant in (await tenants()) if tenants is not None else [None]:
                await _purge_one(maker, tenant)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001  (the database down, say: tomorrow's run tries again)
            log.exception("retention purge failed")


async def _purge_one(maker: async_sessionmaker[AsyncSession], tenant: Optional[tenancy.Tenant]) -> None:
    where = f" ({tenant.slug})" if tenant is not None else ""
    try:
        with tenancy.use(tenant):
            async with maker() as db:
                counts = await purge(db)
        log.info("retention purge%s: %s", where, ", ".join(f"{k} {v}" for k, v in counts.items()))
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001  (logged; the next field, or tomorrow, tries again)
        log.exception("retention purge failed%s", where)
