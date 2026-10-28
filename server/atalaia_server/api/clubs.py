# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Club profiles, their members and the moderation of their public pages (P4R19; plan phase 18).

    POST   /api/v1/clubs                                 any account: {name, short_name, slug, description?,
                                                         colour?}; it becomes the club's admin
    GET    /api/v1/clubs                                 the caller's clubs (every club, for a server administrator)
    GET    /api/v1/clubs/{club_id}                       a member (or a server administrator); a public club: anyone;
                                                         ``fields``: where it plays (the fields that saved a team of
                                                         it; anyone but a member sees only fields with a public page)
    PATCH  /api/v1/clubs/{club_id}                       club admin: {name, short_name, description, colour,
                                                         public_page}
    DELETE /api/v1/clubs/{club_id}                       club admin (its saved teams at fields go with it)
    PUT    /api/v1/clubs/{club_id}/images/{logo|crest}?rights_confirmed=true   club admin: the raw image
    DELETE /api/v1/clubs/{club_id}/images/{logo|crest}   club admin
    GET    /api/v1/clubs/{club_id}/members               a member: the members (and, for its admins, the invitations)
    PUT    /api/v1/clubs/{club_id}/members               club admin: {username, role}: invite, or change a role
    DELETE /api/v1/clubs/{club_id}/members/{user_id}     club admin, or the member: remove, or leave
    GET    /api/v1/me/clubs                              the caller's memberships and invitations
    POST   /api/v1/me/clubs/{club_id}/accept             accept an invitation
    POST   /api/v1/club-reports                          {slug, reason, text?}: report a public club page (also its
                                                         report button, ``/c/<slug>/report``), with or without login
    GET    /api/v1/admin/club-reports?status=open        server administrator: the reports
    PATCH  /api/v1/admin/club-reports/{report_id}        server administrator: {status: dismissed|actioned}
    PUT    /api/v1/admin/clubs/{club_id}/hidden          server administrator: {reason}: hide the public page
    DELETE /api/v1/admin/clubs/{club_id}/hidden          show it again

A club is an organisation's profile, not an account: who belongs to it is personal data
(``club_members``, in access, export, erasure and the purge, decision S18-9). A club's admin invites an
account by its username and the person accepts; a club keeps at least one admin (409 ``last_admin``).
Club roles need no TOTP (they edit a public profile, not a field, decision S18-5). Public pages are off by
default; a server administrator can hide one, which takes it off the site (a 404, as if it never existed)
but not off the fields that saved the club's team (decision S18-8). Every change is in the audit log.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field as PydanticField
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import record
from ..auth import Principal, bearer, current_principal, principal_from_token, server_admin
from ..db import get_session
from ..models import CLUB_ROLES, REPORT_REASONS, Club, ClubMember, ClubReport, User
from ..ratelimit import client_ip
from ..services import branding as svc
from .branding import checked_image

router = APIRouter(prefix="/api/v1", tags=["clubs"])
NO_STORE = {"Cache-Control": "no-store"}
CLUB_SLOTS = ("logo", "crest")
MAX_CLUBS_CREATED = 10      # clubs one account may have made and still administer
REPORT_TEXT_MAX = 1000


class ClubIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = PydanticField(max_length=256)
    short_name: str = PydanticField(max_length=64)
    slug: str = PydanticField(max_length=128)
    description: Optional[str] = PydanticField(default=None, max_length=8000)
    colour: Optional[str] = PydanticField(default=None, max_length=16)


class ClubPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = PydanticField(default=None, max_length=256)
    short_name: Optional[str] = PydanticField(default=None, max_length=64)
    description: Optional[str] = PydanticField(default=None, max_length=8000)
    colour: Optional[str] = PydanticField(default=None, max_length=16)
    public_page: Optional[bool] = None


class MemberIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = PydanticField(max_length=64)
    role: str = PydanticField(default="member", max_length=16)


class ReportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str = PydanticField(max_length=128)
    reason: str = PydanticField(max_length=16)
    text: Optional[str] = PydanticField(default=None, max_length=4000)


class ReportPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = PydanticField(max_length=16)


class HideIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Optional[str] = PydanticField(default=None, max_length=1024)


def _problem(exc: svc.BrandingError) -> HTTPException:
    return HTTPException(exc.status, exc.code)


async def _club(db: AsyncSession, club_id: uuid.UUID) -> Club:
    club = await db.get(Club, club_id)
    if club is None:
        raise HTTPException(404, "club_not_found")
    return club


async def _role(db: AsyncSession, principal: Principal, club: Club) -> Optional[str]:
    """The caller's club role; a server administrator counts as the club's admin."""
    if principal.is_server_admin:
        return "admin"
    return await svc.club_role(db, club.id, principal.user.id)


async def _admin(db: AsyncSession, principal: Principal, club_id: uuid.UUID) -> Club:
    club = await _club(db, club_id)
    role = await _role(db, principal, club)
    if role is None and not svc.club_visible(club):
        raise HTTPException(404, "club_not_found")
    if role != "admin":
        raise HTTPException(403, "club_admin_required")
    return club


async def _answer(db: AsyncSession, club: Club, role: Optional[str], status: int = 200,
                  extra: Optional[dict[str, Any]] = None) -> JSONResponse:
    return JSONResponse({**await svc.club_json(db, club, role), **(extra or {})}, status_code=status,
                        headers=NO_STORE)


def _texts(body: Any, fields: set[str]) -> dict[str, Any]:
    """The club's checked texts, those that were sent."""
    out: dict[str, Any] = {}
    if "name" in fields:
        out["name"] = svc.one_line(body.name, "name", svc.CLUB_NAME_MAX, required=True)
    if "short_name" in fields:
        out["short_name"] = svc.one_line(body.short_name, "short_name", svc.TEAM_NAME_MAX, required=True)
    if "description" in fields:
        from ..services.scheduling import ScheduleError, clean_text  # noqa: PLC0415

        try:
            out["description"] = clean_text(body.description, "description", svc.CLUB_DESCRIPTION_MAX)
        except ScheduleError as exc:
            raise svc.BrandingError(exc.code) from None
    if "colour" in fields:
        out["colour"] = svc.accent(body.colour, "colour")
    return out


@router.post("/clubs", status_code=201)
async def create_club(body: ClubIn, request: Request, principal: Principal = Depends(current_principal),
                      db: AsyncSession = Depends(get_session)) -> JSONResponse:
    if not svc.CLUB_SLUG.fullmatch(body.slug):
        raise HTTPException(400, "slug_invalid")
    try:
        values = _texts(body, {"name", "short_name", "description", "colour"})
    except svc.BrandingError as exc:
        raise _problem(exc) from None
    # Lock the account's row: two requests at once cannot both pass the count below.
    await db.execute(select(User.id).where(User.id == principal.user.id).with_for_update())
    made = await db.scalar(select(func.count()).select_from(Club).join(
        ClubMember, (ClubMember.club_id == Club.id) & (ClubMember.user_id == principal.user.id)).where(
        Club.created_by == principal.user.id, ClubMember.role == "admin"))
    if not principal.is_server_admin and (made or 0) >= MAX_CLUBS_CREATED:
        raise HTTPException(409, "too_many_clubs")
    club = Club(slug=body.slug, created_by=principal.user.id, **values)
    db.add(club)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "slug_taken") from None
    now = datetime.now(timezone.utc)
    db.add(ClubMember(club_id=club.id, user_id=principal.user.id, role="admin", added_by=principal.user.id,
                      accepted_at=now))
    record(db, "club_create", request, user_id=principal.user.id, resource="club", resource_id=club.id,
           details={"slug": club.slug})
    await db.commit()
    await db.refresh(club)
    return await _answer(db, club, "admin", status=201)


@router.get("/clubs")
async def list_clubs(principal: Principal = Depends(current_principal),
                     db: AsyncSession = Depends(get_session)) -> JSONResponse:
    if principal.is_server_admin:
        rows = [(c, "admin") for c in await db.scalars(select(Club).order_by(Club.slug))]
    else:
        rows = list(await db.execute(select(Club, ClubMember.role).join(ClubMember, ClubMember.club_id == Club.id)
                                     .where(ClubMember.user_id == principal.user.id,
                                            ClubMember.accepted_at.is_not(None)).order_by(Club.slug)))
    return JSONResponse([await svc.club_json(db, c, r) for c, r in rows], headers=NO_STORE)


@router.get("/clubs/{club_id}")
async def get_club(club_id: uuid.UUID, principal: Principal = Depends(current_principal),
                   db: AsyncSession = Depends(get_session)) -> JSONResponse:
    club = await _club(db, club_id)
    role = await _role(db, principal, club)
    if role is None and not svc.club_visible(club):
        raise HTTPException(404, "club_not_found")
    # The fields where it plays: a member sees them all, anyone else only those with a public page (PKC-3).
    return await _answer(db, club, role, extra={"fields": await svc.club_fields(db, club, role is None)})


@router.patch("/clubs/{club_id}")
async def update_club(club_id: uuid.UUID, body: ClubPatch, request: Request,
                      principal: Principal = Depends(current_principal),
                      db: AsyncSession = Depends(get_session)) -> JSONResponse:
    club = await _admin(db, principal, club_id)
    try:
        values = _texts(body, body.model_fields_set - {"public_page"})
    except svc.BrandingError as exc:
        raise _problem(exc) from None
    changed: dict[str, Any] = {}
    for name, value in values.items():
        if value != getattr(club, name):
            setattr(club, name, value)
            changed[name] = value if name in ("colour", "short_name") else ("set" if value else "cleared")
    if body.public_page is not None and body.public_page != club.public_page:
        club.public_page = changed["public_page"] = body.public_page
    if changed:
        record(db, "club_update", request, user_id=principal.user.id, resource="club", resource_id=club.id,
               details=changed)
    await db.commit()
    if changed.keys() & {"name", "short_name", "slug"}:
        svc.announce(request, await svc.fields_of_club(db, club.id))  # their saved teams carry them (BR24)
    await db.refresh(club)
    return await _answer(db, club, await _role(db, principal, club))


@router.delete("/clubs/{club_id}", status_code=204)
async def delete_club(club_id: uuid.UUID, request: Request, principal: Principal = Depends(current_principal),
                      db: AsyncSession = Depends(get_session)) -> Response:
    club = await _admin(db, principal, club_id)
    record(db, "club_delete", request, user_id=principal.user.id, resource="club", resource_id=club.id,
           details={"slug": club.slug})
    fields = await svc.fields_of_club(db, club.id)
    await db.delete(club)
    await db.commit()
    svc.announce(request, fields)
    return Response(status_code=204)


def _club_slot(slot: str) -> str:
    if slot not in CLUB_SLOTS:
        raise HTTPException(404, "slot_not_found")
    return slot


@router.put("/clubs/{club_id}/images/{slot}")
async def put_club_image(club_id: uuid.UUID, slot: str, request: Request,
                         principal: Principal = Depends(current_principal),
                         db: AsyncSession = Depends(get_session)) -> JSONResponse:
    _club_slot(slot)
    club = await _admin(db, principal, club_id)
    sha = await checked_image(db, request, slot)
    setattr(club, f"{slot}_sha256", sha)
    record(db, "club_image", request, user_id=principal.user.id, resource="club", resource_id=club.id,
           details={"slot": slot, "sha256": sha})
    await db.commit()
    if slot == "crest":  # a club's logo is not sent to controllers, its crest follows its teams
        svc.announce(request, await svc.fields_of_club(db, club.id))
    await db.refresh(club)
    return await _answer(db, club, "admin", extra={"rights_notice": svc.RIGHTS_NOTICE})


@router.delete("/clubs/{club_id}/images/{slot}")
async def delete_club_image(club_id: uuid.UUID, slot: str, request: Request,
                            principal: Principal = Depends(current_principal),
                            db: AsyncSession = Depends(get_session)) -> JSONResponse:
    _club_slot(slot)
    club = await _admin(db, principal, club_id)
    removed = getattr(club, f"{slot}_sha256") is not None
    if removed:
        setattr(club, f"{slot}_sha256", None)
        record(db, "club_image", request, user_id=principal.user.id, resource="club", resource_id=club.id,
               details={"slot": slot, "sha256": None})
    await db.commit()
    if removed and slot == "crest":
        svc.announce(request, await svc.fields_of_club(db, club.id))
    await db.refresh(club)
    return await _answer(db, club, "admin")


# --- members ---------------------------------------------------------------------------------

def _member_json(m: ClubMember, username: str) -> dict[str, Any]:
    return {"user_id": str(m.user_id), "username": username, "role": m.role,
            "accepted": m.accepted_at is not None,
            "accepted_at": m.accepted_at.isoformat() if m.accepted_at else None,
            "invited_at": m.created_at.isoformat() if m.created_at else None}


async def _admins_left(db: AsyncSession, club_id: uuid.UUID, without: uuid.UUID) -> int:
    """The club's other accepted admins, their rows locked (two admins leaving at once cannot both go)."""
    rows = await db.scalars(select(ClubMember.id).where(
        ClubMember.club_id == club_id, ClubMember.role == "admin", ClubMember.accepted_at.is_not(None),
        ClubMember.user_id != without).order_by(ClubMember.id).with_for_update())
    return len(list(rows))


@router.get("/clubs/{club_id}/members")
async def list_members(club_id: uuid.UUID, principal: Principal = Depends(current_principal),
                       db: AsyncSession = Depends(get_session)) -> JSONResponse:
    club = await _club(db, club_id)
    role = await _role(db, principal, club)
    if role is None:
        raise HTTPException(404, "club_not_found")
    query = select(ClubMember, User.username).join(User, User.id == ClubMember.user_id).where(
        ClubMember.club_id == club_id)
    if role != "admin":  # invitations are the admins' business
        query = query.where(ClubMember.accepted_at.is_not(None))
    rows = await db.execute(query.order_by(User.username))
    return JSONResponse([_member_json(m, u) for m, u in rows], headers=NO_STORE)


@router.put("/clubs/{club_id}/members")
async def put_member(club_id: uuid.UUID, body: MemberIn, request: Request,
                     principal: Principal = Depends(current_principal),
                     db: AsyncSession = Depends(get_session)) -> JSONResponse:
    if body.role not in CLUB_ROLES:
        raise HTTPException(400, "role_invalid")
    club = await _admin(db, principal, club_id)
    target = await db.scalar(select(User).where(User.username == body.username.strip().lower()))
    if target is None:
        raise HTTPException(404, "user_not_found")
    member = await db.scalar(select(ClubMember).where(ClubMember.club_id == club.id,
                                                      ClubMember.user_id == target.id).with_for_update())
    status = 200
    if member is None:
        member = ClubMember(club_id=club.id, user_id=target.id, role=body.role, added_by=principal.user.id)
        db.add(member)
        status = 201
        record(db, "club_invite", request, user_id=principal.user.id, resource="user", resource_id=target.id,
               details={"club_id": str(club.id), "role": body.role})
    elif member.role != body.role:
        if member.role == "admin" and member.accepted_at is not None \
                and await _admins_left(db, club.id, target.id) == 0:
            raise HTTPException(409, "last_admin")
        member.role = body.role
        record(db, "club_role", request, user_id=principal.user.id, resource="user", resource_id=target.id,
               details={"club_id": str(club.id), "role": body.role})
    await db.commit()
    await db.refresh(member)
    return JSONResponse(_member_json(member, target.username), status_code=status, headers=NO_STORE)


@router.delete("/clubs/{club_id}/members/{user_id}", status_code=204)
async def delete_member(club_id: uuid.UUID, user_id: uuid.UUID, request: Request,
                        principal: Principal = Depends(current_principal),
                        db: AsyncSession = Depends(get_session)) -> Response:
    if user_id != principal.user.id:
        await _admin(db, principal, club_id)
    await _leave(db, club_id, user_id)
    record(db, "club_leave" if user_id == principal.user.id else "club_remove", request, user_id=principal.user.id,
           resource="user", resource_id=user_id, details={"club_id": str(club_id)})
    await db.commit()
    return Response(status_code=204)


async def _leave(db: AsyncSession, club_id: uuid.UUID, user_id: uuid.UUID) -> None:
    member = await db.scalar(select(ClubMember).where(ClubMember.club_id == club_id, ClubMember.user_id == user_id)
                             .with_for_update())
    if member is None:
        raise HTTPException(404, "member_not_found")
    if member.role == "admin" and member.accepted_at is not None and await _admins_left(db, club_id, user_id) == 0:
        raise HTTPException(409, "last_admin")
    await db.delete(member)


@router.get("/me/clubs")
async def my_clubs(principal: Principal = Depends(current_principal),
                   db: AsyncSession = Depends(get_session)) -> JSONResponse:
    rows = await db.execute(select(ClubMember, Club).join(Club, Club.id == ClubMember.club_id)
                            .where(ClubMember.user_id == principal.user.id).order_by(Club.slug))
    name = principal.user.username
    return JSONResponse([{"club_id": str(c.id), "slug": c.slug, "name": c.name, **_member_json(m, name)}
                         for m, c in rows], headers=NO_STORE)


@router.post("/me/clubs/{club_id}/accept")
async def accept_invitation(club_id: uuid.UUID, request: Request, principal: Principal = Depends(current_principal),
                            db: AsyncSession = Depends(get_session)) -> JSONResponse:
    member = await db.scalar(select(ClubMember).where(ClubMember.club_id == club_id,
                                                      ClubMember.user_id == principal.user.id))
    if member is None:
        raise HTTPException(404, "invitation_not_found")
    if member.accepted_at is None:
        member.accepted_at = datetime.now(timezone.utc)
        record(db, "club_join", request, user_id=principal.user.id, resource="club", resource_id=club_id,
               details={"role": member.role})
    await db.commit()
    await db.refresh(member)
    return JSONResponse(_member_json(member, principal.user.username), headers=NO_STORE)


# --- reports and moderation -------------------------------------------------------------------

async def file_report(db: AsyncSession, request: Request, slug: str, reason: str, text: Optional[str],
                      reporter: Optional[uuid.UUID]) -> Optional[ClubReport]:
    """A report of a public club page; None if there is no such page (or it is hidden already). Rate-limited
    per address (``Limits.reports``); no address is stored. Raises HTTPException for a bad reason or text."""
    if reason not in REPORT_REASONS:
        raise HTTPException(400, "reason_invalid")
    from ..services.scheduling import ScheduleError, clean_text  # noqa: PLC0415

    try:
        text = clean_text(text, "text", REPORT_TEXT_MAX)
    except ScheduleError as exc:
        raise HTTPException(400, exc.code) from None
    club = await db.scalar(select(Club).where(Club.slug == slug))
    if club is None or not svc.club_visible(club):
        return None
    wait = request.app.state.limits.reports.hit(client_ip(request.scope))
    if wait:
        raise HTTPException(429, "too_many_requests", headers={"Retry-After": str(wait)})
    report = ClubReport(club_id=club.id, reason=reason, text=text, reporter_id=reporter)
    db.add(report)
    await db.flush()
    record(db, "club_report", None, user_id=reporter, resource="club", resource_id=club.id,
           details={"report_id": str(report.id), "reason": reason})
    await db.commit()
    return report


@router.post("/club-reports", status_code=201)
async def report_club(body: ReportIn, request: Request, db: AsyncSession = Depends(get_session)) -> JSONResponse:
    token = bearer(request)
    principal = await principal_from_token(request, db, token) if token else None
    report = await file_report(db, request, body.slug.strip().lower(), body.reason, body.text,
                               principal.user.id if principal else None)
    if report is None:
        raise HTTPException(404, "club_not_found")
    return JSONResponse({"report_id": str(report.id), "status": report.status}, status_code=201, headers=NO_STORE)


def _report_json(r: ClubReport, club: Club) -> dict[str, Any]:
    return {"id": str(r.id), "club_id": str(club.id), "slug": club.slug, "club": club.name, "reason": r.reason,
            "text": r.text, "status": r.status, "reported_by_account": r.reporter_id is not None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "decided_at": r.decided_at.isoformat() if r.decided_at else None,
            "club_hidden": club.hidden_at is not None}


@router.get("/admin/club-reports")
async def list_reports(request: Request, principal: Principal = Depends(server_admin),
                       db: AsyncSession = Depends(get_session)) -> JSONResponse:
    status = request.query_params.get("status", "open")
    query = select(ClubReport, Club).join(Club, Club.id == ClubReport.club_id)
    if status != "all":
        query = query.where(ClubReport.status == status)
    rows = await db.execute(query.order_by(ClubReport.created_at, ClubReport.id).limit(500))
    return JSONResponse([_report_json(r, c) for r, c in rows], headers=NO_STORE)


@router.patch("/admin/club-reports/{report_id}")
async def decide_report(report_id: uuid.UUID, body: ReportPatch, request: Request,
                        principal: Principal = Depends(server_admin),
                        db: AsyncSession = Depends(get_session)) -> JSONResponse:
    if body.status not in ("dismissed", "actioned"):
        raise HTTPException(400, "status_invalid")
    report = await db.get(ClubReport, report_id)
    if report is None:
        raise HTTPException(404, "report_not_found")
    report.status = body.status
    report.decided_at = datetime.now(timezone.utc)
    report.decided_by = principal.user.id
    record(db, "club_report_decide", request, user_id=principal.user.id, resource="club",
           resource_id=report.club_id, details={"report_id": str(report.id), "status": body.status})
    await db.commit()
    club = await _club(db, report.club_id)
    return JSONResponse(_report_json(report, club), headers=NO_STORE)


@router.put("/admin/clubs/{club_id}/hidden")
async def hide_club(club_id: uuid.UUID, request: Request, body: Optional[HideIn] = None,
                    principal: Principal = Depends(server_admin),
                    db: AsyncSession = Depends(get_session)) -> JSONResponse:
    club = await _club(db, club_id)
    from ..services.scheduling import ScheduleError, clean_line  # noqa: PLC0415

    try:
        reason = clean_line(body.reason if body else None, "reason", 512)
    except ScheduleError as exc:
        raise HTTPException(400, exc.code) from None
    club.hidden_at = datetime.now(timezone.utc)
    club.hidden_reason = reason
    club.hidden_by = principal.user.id
    record(db, "club_hide", request, user_id=principal.user.id, resource="club", resource_id=club.id,
           details={"slug": club.slug})
    await db.commit()
    await db.refresh(club)
    return await _answer(db, club, "admin")


@router.delete("/admin/clubs/{club_id}/hidden")
async def show_club(club_id: uuid.UUID, request: Request, principal: Principal = Depends(server_admin),
                    db: AsyncSession = Depends(get_session)) -> JSONResponse:
    club = await _club(db, club_id)
    if club.hidden_at is not None:
        club.hidden_at = club.hidden_reason = club.hidden_by = None
        record(db, "club_show", request, user_id=principal.user.id, resource="club", resource_id=club.id,
               details={"slug": club.slug})
    await db.commit()
    await db.refresh(club)
    return await _answer(db, club, "admin")
