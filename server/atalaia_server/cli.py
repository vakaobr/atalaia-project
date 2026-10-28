# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The site server's commands: ``python -m atalaia_server <command>``.

    python -m atalaia_server create-admin --username NAME [--email EMAIL] [--password-stdin] [--field SLUG]
    python -m atalaia_server create-admin --username NAME --generate FILE
    python -m atalaia_server reset-totp --username NAME --reason TEXT [--yes] [--field SLUG]
    python -m atalaia_server demo load|reset
    python -m atalaia_server demo live [--key-out FILE] [--keep N] [--reset]
    python -m atalaia_server demo reviewer --username NAME --out FILE
    python -m atalaia_server feedback list [--status new|seen|done|all] [--json]
    python -m atalaia_server purge [--dry-run]
    python -m atalaia_server hosted init|create|list|migrate|check|suspend|resume|export|delete ...
    python -m atalaia_server import-field FILE.zip
    python -m atalaia_server atak issue --field SLUG --device NAME [--days N] --out FILE.zip
    python -m atalaia_server atak list --field SLUG
    python -m atalaia_server atak revoke --field SLUG CERTIFICATE_ID

``create-admin`` makes a server administrator (ADR-P4-2): it asks for the
password twice (or reads one line from standard input with
``--password-stdin``), checks it against the password policy, shows a new
TOTP secret and its ``otpauth://`` URI for an authenticator app, and creates
the account only after a code from that app is typed back, since an
administrator cannot log in without TOTP. In the deployed Compose project:
``docker compose exec server python -m atalaia_server create-admin --username ...``.
It needs ATALAIA_DATABASE_URL and ATALAIA_SECRET_KEY, as the server does.

``create-admin --generate FILE`` (preview deployments, decisions PV-*) asks nothing: it makes a strong password and a
TOTP secret, creates the administrator and writes the username, password, secret and ``otpauth://`` URI to FILE
(mode 0600, which must not exist); nothing secret is printed. ``demo`` loads, resets or adds a test account to the
demo data (``demo_data.py``); ``feedback list`` prints a preview server's feedback.

``reset-totp`` is the recovery for an account that lost its authenticator (decision S11-7): it
clears the account's TOTP secret, enrolment and last-used step, revokes every session of the account (a
session's access token stops working at once, and a login half-way through the TOTP step is refused), and writes
``totp_reset`` to the audit log (the account, the operator's system user, the ``--reason`` and ``via: cli``). The
password is not touched: at the next login the account gets a session that has not passed TOTP (an administrator's
and the privileged roles' powers wait for it) and enrols a new secret (``/auth/totp/enrol``, then ``confirm``). It
asks for the username to be typed again unless ``--yes`` is given, and refuses an unknown account, or one with no
TOTP to clear. The server keeps no recovery codes and no remembered devices: the secret is all there is. In hosted
mode it needs ``--field SLUG``, as ``create-admin`` does.

``purge`` runs the retention purge (ADR-P4-8) once and prints what it
deleted (``--dry-run``: what it would delete). The server runs it by itself
every day at ATALAIA_PURGE_HOUR (03:00 UTC by default); the command is for a
deployment that turns that off and schedules it elsewhere, or for a check.

``atak`` is the operator's side of the remote ATAK relay's enrolment (Phase 4
follow-up FU5; the field's admin and gm use ``/staff/fields/<field>/atak`` or
the API): ``issue`` writes a TAK data package for a device of the field named
by its slug (mode 0600) and prints its client certificate's password once;
the certificate has no holder, so it gets the field's boxes and zones, never
player positions. ``list`` shows the field's certificates; ``revoke`` revokes
one (a running server closes its connections within 30 seconds; the API does
it at once). They need ATALAIA_ATAK_RELAY=on and the server's settings.

In hosted mode (ATALAIA_HOSTED=on, plan phase 21) ``create-admin`` needs
``--field SLUG``: the account is made in that field's schema and administers
that field only, and ``purge`` runs once per active field. ``hosted ...`` are
the hub operator's commands and ``import-field`` loads a field's export into
a single-field server (``hosted.py``); they need only ATALAIA_DATABASE_URL,
with the owner role's credentials.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, TextIO

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from . import atak_pki, demo_data, hosted, passwords, personal_data, tenancy, totp
from .api.auth import EMAIL, username_problem
from .audit import record
from .config import QUOTA_DEFAULTS, ConfigError, Settings, database_url_from_env
from .db import make_engine, make_sessionmaker
from .models import Field, User, UserSession
from .services import atak as enrolment
from .tokens import Keys
from .totp import SeedBox

CODE_TRIES = 3


class CommandError(Exception):
    """A problem to report in one line (exit code 1)."""


async def create_admin(settings: Settings, username: str, email: Optional[str], password: str,
                       read_code: Callable[[str, str], str], out: TextIO,
                       clock: Callable[[], float] = time.time, field: Optional[str] = None) -> uuid.UUID:
    """Creates the administrator once a code for its new TOTP secret is confirmed; returns its id.
    In hosted mode ``field`` (a tenant's slug) is required: the account is that field's."""
    if settings.hosted != (field is not None):
        raise CommandError("--field SLUG names the field in hosted mode (ATALAIA_HOSTED=on) and only there")
    engine = make_engine(settings)
    try:
        tenant = None
        if field is not None:
            tenant = await tenancy.lookup(engine, tenancy.check_slug(field))
            if tenant is None:
                raise CommandError(f"no field {field!r} on this hub")
        with tenancy.use(tenant):
            return await _create_admin(settings, engine, username, email, password, read_code, out, clock)
    except tenancy.TenantError as e:
        raise CommandError(str(e)) from None
    finally:
        await engine.dispose()


async def _create_admin(settings: Settings, engine: Any, username: str, email: Optional[str], password: str,
                        read_code: Callable[[str, str], str], out: TextIO, clock: Callable[[], float]) -> uuid.UUID:
    username = username.strip().lower()
    email = email.strip().lower() if email and email.strip() else None
    if username_problem(username) == "username_reserved":
        raise CommandError(f"usernames starting with {personal_data.ERASED_PREFIX!r} are reserved for erased accounts")
    if username_problem(username):
        raise CommandError("the username must be 3-64 characters: letters, digits, '.', '_' or '-', "
                           "starting with a letter or digit")
    if email is not None and not EMAIL.fullmatch(email):
        raise CommandError("that email address is not valid")
    problem = passwords.policy_problem(password, username)
    if problem:
        raise CommandError({"password_too_short": f"the password needs at least {passwords.MIN_LENGTH} characters",
                            "password_too_long": f"the password may have at most {passwords.MAX_LENGTH} characters",
                            "password_is_username": "the password may not be the username",
                            "password_breached": "that password is on the list of breached passwords"}[problem])
    maker = make_sessionmaker(engine, hosted=settings.hosted)
    async with maker() as db:
        if await db.scalar(select(User.id).where(User.username == username)) is not None:
            raise CommandError(f"an account named {username!r} already exists")
    secret = totp.new_secret()
    uri = totp.provisioning_uri(secret, username)
    print("Add this account to an authenticator app (scan the URI as a QR code, or type the secret):",
          file=out)
    print(f"  {uri}", file=out)
    print(f"  secret: {secret}", file=out)
    step = None
    for _ in range(CODE_TRIES):
        step = totp.verify(secret, read_code(uri, secret), clock(), None)
        if step is not None:
            break
        print("That code is not right; try the current one.", file=out)
    if step is None:
        raise CommandError("no valid TOTP code: nothing was created")
    hashed = await passwords.hash_password(password)
    async with maker() as db:
        user = User(username=username, email=email, password_hash=hashed, server_admin=True,
                    totp_enabled=True, totp_secret_enc=SeedBox(Keys(settings.secret_key).totp_seed).seal(secret),
                    totp_last_step=step, gdpr_consent_at=datetime.now(timezone.utc))
        db.add(user)
        try:
            await db.flush()
        except IntegrityError:
            raise CommandError("that username or email address is already taken") from None
        personal_data.give_consent(db, user.id, personal_data.ACCOUNT, settings.privacy_notice_version,
                                   user.gdpr_consent_at)
        record(db, "admin_create", None, user_id=user.id, resource="user", resource_id=user.id,
               details={"via": "cli"})
        await db.commit()
        print(f"Server administrator {username!r} created ({user.id}).", file=out)
        return user.id


async def reset_totp(settings: Settings, username: str, reason: str, assume_yes: bool,
                     confirm: Callable[[str], str], out: TextIO, field: Optional[str] = None,
                     actor: Optional[str] = None) -> uuid.UUID:
    """Clears an account's TOTP enrolment, revokes its sessions and audits it (decision S11-7); returns its id.
    Asks for the username again unless ``assume_yes``. In hosted mode ``field`` is required."""
    if settings.hosted != (field is not None):
        raise CommandError("--field SLUG names the field in hosted mode (ATALAIA_HOSTED=on) and only there")
    username = username.strip().lower()
    reason = reason.strip()
    if not reason:
        raise CommandError("--reason says why (it goes in the audit log)")
    engine = make_engine(settings)
    try:
        tenant = None
        if field is not None:
            tenant = await tenancy.lookup(engine, tenancy.check_slug(field))
            if tenant is None:
                raise CommandError(f"no field {field!r} on this hub")
        with tenancy.use(tenant):
            async with make_sessionmaker(engine, hosted=settings.hosted)() as db:
                user = await db.scalar(select(User).where(User.username == username).with_for_update())
                if user is None:
                    raise CommandError(f"no account named {username!r}")
                if not user.totp_enabled and user.totp_secret_enc is None:
                    raise CommandError(f"{username!r} has no TOTP enrolment to clear")
                if not assume_yes:
                    print(f"This clears {username!r}'s TOTP enrolment and signs the account out everywhere; "
                          f"it enrols again at the next login.", file=out)
                    if confirm("Type the username to confirm: ").strip().lower() != username:
                        raise CommandError("not confirmed: nothing was changed")
                was_enabled = user.totp_enabled
                user.totp_enabled = False
                user.totp_secret_enc = None
                user.totp_last_step = None
                revoked = (await db.execute(update(UserSession).where(
                    UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
                    .values(revoked_at=func.now(), mfa=False))).rowcount
                record(db, "totp_reset", None, user_id=user.id, resource="user", resource_id=user.id,
                       details={"via": "cli", "actor": actor or hosted.default_actor(), "reason": reason,
                                "was_enabled": was_enabled, "sessions_revoked": revoked,
                                "server_admin": user.server_admin})
                await db.commit()
                print(f"TOTP cleared for {username!r} ({user.id}); {revoked} session(s) revoked. "
                      f"It enrols a new secret at the next login.", file=out)
                return user.id
    except tenancy.TenantError as e:
        raise CommandError(str(e)) from None
    finally:
        await engine.dispose()


async def run_purge(settings: Settings, dry_run: bool, out: TextIO) -> dict[str, int]:
    engine = make_engine(settings)
    total: dict[str, int] = {}
    try:
        maker = make_sessionmaker(engine, hosted=settings.hosted)
        for tenant in (await tenancy.active_tenants(engine)) if settings.hosted else [None]:
            with tenancy.use(tenant):
                async with maker() as db:
                    counts = await personal_data.purge(db, dry_run=dry_run)
            verb = "would delete" if dry_run else "deleted"
            where = f" ({tenant.slug})" if tenant is not None else ""
            print(f"Retention purge{where} {verb}: "
                  + ", ".join(f"{n} {what.replace('_', ' ')} rows" for what, n in counts.items()), file=out)
            for what, n in counts.items():
                total[what] = total.get(what, 0) + n
    finally:
        await engine.dispose()
    return total


async def run_atak(settings: Settings, args: argparse.Namespace, out: TextIO) -> None:
    """The ``atak`` commands: issue (a data package with no holder: props and zones only), list, revoke."""
    if args.action == "issue" and not settings.atak_relay:
        raise CommandError("the ATAK relay is off (ATALAIA_ATAK_RELAY=on turns it on)")
    engine = make_engine(settings)
    try:
        tenant = None
        if settings.hosted:
            tenant = await tenancy.lookup(engine, tenancy.check_slug(args.field))
            if tenant is None:
                raise CommandError(f"no field {args.field!r} on this hub")
        with tenancy.use(tenant):
            async with make_sessionmaker(engine, hosted=settings.hosted)() as db:
                query = select(Field).where(Field.id == tenant.field_id) if tenant is not None \
                    else select(Field).where(Field.slug == args.field)
                field = (await db.execute(query)).scalars().first()
                if field is None:
                    raise CommandError(f"no field {args.field!r}")
                if args.action == "list":
                    for c in await enrolment.list_certs(db, field.id):
                        print(f"{c['id']}\t{c['state']}\t{c['device_name']}\t{c['holder'] or '-'}\t"
                              f"positions={'yes' if c['positions'] else 'no'}\tuntil {c['not_after']}", file=out)
                    return
                if args.action == "revoke":
                    try:
                        row = await enrolment.revoke(db, field.id, uuid.UUID(args.certificate), None)
                    except (ValueError, enrolment.AtakProblem):
                        raise CommandError(f"no certificate {args.certificate} at {args.field}") from None
                    record(db, "atak_cert_revoked", None, resource="field", resource_id=field.id,
                           details={"certificate": str(row.id), "device_name": row.device_name,
                                    "reason": row.revoke_reason, "via": "command"})
                    await db.commit()
                    print(f"Revoked {row.device_name} ({row.id}); a running relay closes its connections within "
                          f"30 seconds.", file=out)
                    return
                path = Path(args.out)
                if path.exists():
                    raise CommandError(f"{path} exists")
                box = atak_pki.CaBox(settings.secret_key)
                try:
                    done = await enrolment.issue(db, box, field, device_name=args.device,
                                                 days=args.days if args.days is not None else settings.atak_cert_days,
                                                 holder=None, positions=False, issued_by=None, via="command")
                except enrolment.AtakProblem as e:
                    raise CommandError(f"refused: {e.detail}") from None
                host = settings.relay_host(tenant.slug if tenant else None)
                port = settings.relay_public_port()
                password = atak_pki.new_package_password()
                relay_ca, _ = atak_pki.server_ca(settings.secret_key)
                package = atak_pki.data_package(issued=done.issued, field_ca=done.ca, relay_ca=relay_ca,
                                                password=password, host=str(host), port=port,
                                                description=f"Atalaia {field.name}"[:64],
                                                name=atak_pki.package_name(field.slug, done.row.device_name))
                record(db, "atak_cert_issued", None, resource="field", resource_id=field.id,
                       details={"certificate": str(done.row.id), "device_name": done.row.device_name,
                                "serial": done.row.serial, "holder_id": None, "positions": False,
                                "not_after": done.row.not_after.isoformat(), "ca_made": done.ca_made,
                                "via": "command"})
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(package)
                await db.commit()
                print(f"Certificate {done.row.id} for {done.row.device_name} at {args.field}, valid until "
                      f"{done.row.not_after.isoformat()}: {path} (connects to {host}:{port}). Its password, shown "
                      f"once: {password}", file=out)
    finally:
        await engine.dispose()


def write_credentials(path: Path, username: str, password: str, secret: str, what: str) -> None:
    """Writes a generated account's login to ``path`` (mode 0600, must not exist); never printed."""
    if path.exists():
        raise CommandError(f"{path} exists")
    text = (f"{what}\nusername: {username}\npassword: {password}\ntotp_secret: {secret}\n"
            f"totp_uri: {totp.provisioning_uri(secret, username)}\n"
            "Add the TOTP secret (or the URI as a QR code) to an authenticator app; the password is for the login page.\n")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)


async def generate_admin(settings: Settings, username: str, email: Optional[str], out_path: Path, out: TextIO,
                         clock: Callable[[], float] = time.time) -> uuid.UUID:
    """``create-admin --generate``: a password and TOTP secret made here, the account created, the login written
    to ``out_path`` before anything is made (so a failure leaves no account nobody can enter)."""
    password = demo_data.new_password()
    secret_box: dict[str, str] = {}

    def read_code(uri: str, secret: str) -> str:
        secret_box["secret"] = secret
        # The code of the step before this one: the account's last step is then older than the current code.
        return totp.code_at(secret, clock() - totp.PERIOD_S)

    class _Quiet:  # create_admin prints the secret: not here
        def write(self, text: str) -> int:
            return len(text)

        def flush(self) -> None:
            return None

    if out_path.exists():
        raise CommandError(f"{out_path} exists")
    user_id = await create_admin(settings, username, email, password, read_code, _Quiet(), clock)  # type: ignore[arg-type]
    write_credentials(out_path, username.strip().lower(), password, secret_box["secret"], "Atalaia server administrator")
    print(f"Server administrator {username!r} created ({user_id}); its login is in {out_path} (mode 0600).", file=out)
    return user_id


async def run_demo(settings: Settings, args: argparse.Namespace, out: TextIO) -> None:
    engine = make_engine(settings)
    try:
        maker = make_sessionmaker(engine, hosted=False)
        async with maker() as db:
            if args.action == "load":
                print("Demo data:", demo_data.json_summary(await demo_data.load(db)), file=out)
            elif args.action == "reset":
                print("Demo data reset:", demo_data.json_summary(await demo_data.reset(db)), file=out)
            elif args.action == "live":
                key_out = Path(args.key_out) if args.key_out else None
                print("Live demo field:", demo_data.json_summary(
                    await demo_data.live(db, key_out, args.keep, args.reset)), file=out)
            else:
                username = args.username.strip().lower()
                if username_problem(username):
                    raise CommandError("the username must be 3-64 characters: letters, digits, '.', '_' or '-'")
                if await demo_data.username_taken(db, username):
                    raise CommandError(f"an account named {username!r} already exists")
                if await db.get(Field, demo_data.demo_id("field")) is None:
                    raise CommandError("there is no demo field: run `demo load` first")
                path = Path(args.out)
                if path.exists():
                    raise CommandError(f"{path} exists")
                password, secret = demo_data.new_password(), totp.new_secret()
                await demo_data.make_account(db, Keys(settings.secret_key), settings.privacy_notice_version, username,
                                             password, secret, role="gm")
                write_credentials(path, username, password, secret, "Atalaia preview test account (GM on the demo field)")
                await db.commit()
                print(f"Test account {username!r} (GM on the demo field) created; its login is in {path} (mode 0600).",
                      file=out)
    finally:
        await engine.dispose()


async def run_feedback(settings: Settings, args: argparse.Namespace, out: TextIO) -> None:
    import json  # noqa: PLC0415

    from .api.feedback import list_feedback  # noqa: PLC0415

    engine = make_engine(settings)
    try:
        async with make_sessionmaker(engine, hosted=False)() as db:
            body = await list_feedback(db, args.status, 500)
    finally:
        await engine.dispose()
    if args.json:
        print(json.dumps(body, ensure_ascii=False, indent=2), file=out)
        return
    c = body["counts"]
    print(f"{c['new']} new, {c['seen']} seen, {c['done']} done; showing {args.status}:", file=out)
    for f in body["feedback"]:
        who = f" ({f['who']})" if f["who"] else ""
        print(f"\n[{f['created_at'][:16]}] {f['kind']}{who} lang={f['lang']} page={f['page'] or '-'} "
              f"state={f['status']} id={f['id']}", file=out)
        print(f"  {f['message']}", file=out)
        if f["contact"]:
            print(f"  contact: {f['contact']}", file=out)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m atalaia_server", description="Atalaia site server commands")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("create-admin", help="create a server administrator (with TOTP)")
    admin.add_argument("--username", required=True)
    admin.add_argument("--email")
    admin.add_argument("--password-stdin", action="store_true",
                       help="read the password from the first line of standard input, the TOTP code from the next")
    admin.add_argument("--field", help="hosted mode: the field (slug) the administrator belongs to")
    admin.add_argument("--generate", metavar="FILE",
                       help="ask nothing: make a password and TOTP secret and write them to FILE (mode 0600)")
    rt = sub.add_parser("reset-totp", help="clear an account's TOTP enrolment, sign it out, enrol again at next login")
    rt.add_argument("--username", required=True)
    rt.add_argument("--reason", required=True, help="why (goes in the audit log)")
    rt.add_argument("--yes", action="store_true", help="do not ask for the username to be typed again")
    rt.add_argument("--field", help="hosted mode: the field (slug) the account belongs to")
    demo = sub.add_parser("demo", help="the preview deployment's demo data (decisions PV-*)")
    dsub = demo.add_subparsers(dest="action", required=True)
    dsub.add_parser("load", help="make the demo data or bring it up to date (idempotent)")
    dsub.add_parser("reset", help="delete the demo field and clubs, then load again")
    p = dsub.add_parser("live", help="the live demo field the preview's simulated controller syncs to: the field, "
                                     "its API key (written to --key-out, never printed) and the clean-up of old games")
    p.add_argument("--key-out", help="where to keep the field's API key for the simulated controller (mode 0600)")
    p.add_argument("--keep", type=int, default=demo_data.LIVE_KEEP, help="games to keep (default %(default)s)")
    p.add_argument("--reset", action="store_true", help="delete all the live field's games and controllers")
    p = dsub.add_parser("reviewer", help="a test account with the GM role on the demo field")
    p.add_argument("--username", required=True)
    p.add_argument("--out", required=True, help="where to write its login (mode 0600; must not exist)")
    fb = sub.add_parser("feedback", help="a preview server's feedback")
    fsub = fb.add_subparsers(dest="action", required=True)
    p = fsub.add_parser("list", help="print the feedback, newest first")
    p.add_argument("--status", default="new", choices=("new", "seen", "done", "all"))
    p.add_argument("--json", action="store_true")
    purge = sub.add_parser("purge", help="delete what is past its retention period (ADR-P4-8), once")
    purge.add_argument("--dry-run", action="store_true", help="count, delete nothing")
    imp = sub.add_parser("import-field", help="load a hosted field's export into this single-field server")
    imp.add_argument("archive")
    atak = sub.add_parser("atak", help="the remote ATAK relay's certificates (Phase 4 follow-up FU5)")
    asub = atak.add_subparsers(dest="action", required=True)
    p = asub.add_parser("issue", help="a TAK data package for one device (boxes and zones, never positions)")
    p.add_argument("--field", required=True, help="the field's slug")
    p.add_argument("--device", required=True, help="the device's name (1-48 characters)")
    p.add_argument("--days", type=int, default=None, help="1-365 (default: ATALAIA_ATAK_CERT_DAYS, 90)")
    p.add_argument("--out", required=True, help="where to write the ZIP (mode 0600; must not exist)")
    p = asub.add_parser("list", help="the field's certificates")
    p.add_argument("--field", required=True)
    p = asub.add_parser("revoke", help="revoke one certificate")
    p.add_argument("--field", required=True)
    p.add_argument("certificate", help="its id (atak list)")
    host = sub.add_parser("hosted", help="the hosted hub's operator commands (plan phase 21; owner role)")
    hsub = host.add_subparsers(dest="action", required=True)
    role_help = f"the server's database role (default ATALAIA_APP_ROLE or {hosted.DEFAULT_APP_ROLE})"
    for name, text in (("init", "make the registry and the hub's audit log"),
                       ("migrate", "bring every field to the newest revision, grants and policies again")):
        p = hsub.add_parser(name, help=text)
        p.add_argument("--app-role", help=role_help)
        p.add_argument("--actor")
    p = hsub.add_parser("check", help="check the ownership, row-level security and grants of every field")
    p.add_argument("--app-role", help=role_help)
    p = hsub.add_parser("create", help="a new field: its schema, migrations, row-level security")
    p.add_argument("slug")
    p.add_argument("--name", required=True)
    p.add_argument("--field-type", default="outdoor", choices=hosted.FIELD_TYPES)
    p.add_argument("--timezone", default="Europe/Lisbon")
    p.add_argument("--app-role", help=role_help)
    p.add_argument("--actor")
    hsub.add_parser("list", help="the fields on this hub")
    for name, text in (("suspend", "refuse every request to the field"), ("resume", "serve the field again")):
        p = hsub.add_parser(name, help=text)
        p.add_argument("slug")
        p.add_argument("--reason", required=True)
        p.add_argument("--actor")
    p = hsub.add_parser("quota", help="give one field its own limit on a resource, over the hub's (PKC-5)")
    p.add_argument("slug")
    p.add_argument("name", help=f"one of {', '.join(QUOTA_DEFAULTS)}")
    p.add_argument("value", help="a whole number of 1 or more, off (no limit) or default (the hub's own)")
    p.add_argument("--reason", required=True)
    p.add_argument("--actor")
    p = hsub.add_parser("usage", help="what each field (or one) uses against its limits")
    p.add_argument("slug", nargs="?")
    p = hsub.add_parser("quota-hits", help="the fields the server refused for a quota: into the audit log, shown")
    p.add_argument("--actor")
    p = hsub.add_parser("domain", help="a field's custom host name: set, verify (DNS TXT challenge), remove (PKC-6)")
    p.add_argument("domain_action", choices=hosted.DOMAIN_ACTIONS)
    p.add_argument("slug")
    p.add_argument("host", nargs="?", help="the name (set only), such as jogos.example.pt")
    p.add_argument("--reason", help="who asked, or why (set and remove)")
    p.add_argument("--actor")
    p = hsub.add_parser("export", help="the field's whole dataset as a ZIP (mode 0600)")
    p.add_argument("slug")
    p.add_argument("--out", required=True)
    p.add_argument("--reason", required=True, help="whose instruction (the data controller's)")
    p.add_argument("--actor")
    p = hsub.add_parser("delete", help="drop the field's schema and everything in it, for good")
    p.add_argument("slug")
    p.add_argument("--confirm", required=True, help="the slug again")
    p.add_argument("--reason", required=True)
    p.add_argument("--actor")
    return parser


def _say_quota_hits(waiting: int, out: TextIO) -> None:
    if waiting:
        print(f"{waiting} note(s) of fields refused for a quota are waiting: python -m atalaia_server hosted "
              "quota-hits", file=out)


def _run_domain(args: argparse.Namespace, url: str, actor: Optional[str], out: TextIO) -> None:
    if args.domain_action == "set":
        domain = os.environ.get("ATALAIA_HOSTED_DOMAIN", "").strip().lower()
        if not domain:
            raise hosted.HostedError("ATALAIA_HOSTED_DOMAIN is not set: the hub's domain is needed to refuse names "
                                     "under it")
        if not args.host:
            raise hosted.HostedError("the host name is missing: hosted domain set SLUG HOST --reason TEXT")
        name, value = asyncio.run(hosted.set_custom_domain(url, args.slug, args.host, domain, args.reason or "",
                                                           actor))
        print(f"Custom host name pending for {args.slug}. The field publishes, at its DNS provider:\n"
              f"  TXT {name}  \"{value}\"\n"
              f"and points {args.host.strip().lower().rstrip('.')} at this hub (an A/AAAA or CNAME record). Then: "
              f"python -m atalaia_server hosted domain verify {args.slug}", file=out)
    elif args.domain_action == "verify":
        host = asyncio.run(hosted.verify_custom_domain(url, args.slug, actor))
        print(f"Verified: {host} now serves the field {args.slug}; its certificate is issued by Caddy at the first "
              "request.", file=out)
    else:
        host = asyncio.run(hosted.remove_custom_domain(url, args.slug, args.reason or "", actor))
        print(f"Removed {host} from {args.slug}." if host else f"The field {args.slug} had no custom host name.",
              file=out)


def run_hosted(args: argparse.Namespace, url: str, out: TextIO) -> None:
    """One ``hosted`` command (or ``import-field``); raises ``hosted.HostedError`` or ``TenantError``."""
    if args.command == "import-field":
        counts = asyncio.run(hosted.import_field(url, Path(args.archive)))
        print(f"Imported {sum(counts.values())} rows into {len(counts)} tables; everyone logs in and enrols TOTP "
              "again, platform links need setting up again.", file=out)
        return
    action = args.action
    actor = getattr(args, "actor", None) or None
    app_role = getattr(args, "app_role", None) or os.environ.get("ATALAIA_APP_ROLE", "").strip() \
        or hosted.DEFAULT_APP_ROLE
    if action == "init":
        asyncio.run(hosted.init_hub(url, app_role, actor))
        print(f"Hosted hub ready; the server's role is {app_role}.", file=out)
    elif action == "create":
        tenant = hosted.create_tenant(url, args.slug, args.name, args.field_type, args.timezone, app_role, actor)
        print(f"Field {tenant.slug} created: schema {tenant.schema}, field id {tenant.field_id}. Its administrator: "
              f"python -m atalaia_server create-admin --field {tenant.slug} --username NAME", file=out)
    elif action == "list":
        for row in asyncio.run(hosted.list_tenants(url)):
            extra = f"\t{row['custom_host']} ({row['custom_host_status']})" if row["custom_host"] else ""
            print(f"{row['slug']}\t{row['status']}\t{row['schema_name']}\t{row['field_id']}\t"
                  f"{row['created_at'].isoformat()}{extra}", file=out)
        _say_quota_hits(asyncio.run(hosted.waiting_quota_hits(url)), out)
    elif action == "migrate":
        done = hosted.migrate_all(url, app_role, actor)
        print(f"Migrated {len(done)} fields: {', '.join(done) or '-'}", file=out)
    elif action == "check":
        report = asyncio.run(hosted.check_hub(url, app_role))
        if report.problems:
            raise hosted.HostedError(f"the hub check found {len(report.problems)} problems: "
                                     + "; ".join(report.problems))
        print(f"Hub check passed: {report.fields} fields, {report.tables} tables, each owned by the owner role "
              f"with row-level security forced and its one policy, and each field's own database role has its grants "
              f"and {app_role} none of them.",
              file=out)
        _say_quota_hits(report.quota_hits, out)
    elif action == "quota":
        change = asyncio.run(hosted.set_quota(url, args.slug, args.name, args.value, args.reason, actor))
        was = "the hub's" if change["old"] is None else ("no limit" if change["old"] == 0 else change["old"])
        now = "the hub's" if change["new"] is None else ("no limit" if change["new"] == 0 else change["new"])
        print(f"Field {args.slug}: {args.name} limit {was} -> {now}. It applies from the next request.", file=out)
    elif action == "usage":
        for row in asyncio.run(hosted.usage(url, args.slug)):
            print(f"{row['slug']} ({row['status']})", file=out)
            for q in row["quotas"]:
                used = "-" if q["used"] is None else q["used"]
                lim = "no limit" if q["limit"] is None else q["limit"]
                own = "  (this field's own)" if q["own"] else ""
                print(f"  {q['name']:<16}{used!s:>8} / {lim}{own}", file=out)
    elif action == "quota-hits":
        groups = asyncio.run(hosted.collect_quota_hits(url, actor))
        if not groups:
            print("No field was refused for a quota since the last look.", file=out)
        for g in groups:
            print(f"{g['slug']}: refused for {g['quota']} (limit {g['limit']}), {g['count']} note(s), "
                  f"{g['first'].isoformat()} to {g['last'].isoformat()}; recorded in the hub's audit log.", file=out)
    elif action == "domain":
        _run_domain(args, url, actor, out)
    elif action in ("suspend", "resume"):
        asyncio.run(hosted.set_status(url, args.slug, "suspended" if action == "suspend" else "active", args.reason,
                                      actor))
        print(f"Field {args.slug} {'suspended' if action == 'suspend' else 'resumed'}.", file=out)
    elif action == "export":
        result = asyncio.run(hosted.export_tenant(url, args.slug, Path(args.out), args.reason, actor))
        rows = sum(t["rows"] for t in result.manifest["tables"])
        print(f"Exported {args.slug}: {rows} rows in {len(result.manifest['tables'])} tables to {result.path} "
              f"(SHA-256 {result.sha256}). It holds personal data: hand it over encrypted.", file=out)
    elif action == "delete":
        counts = asyncio.run(hosted.delete_tenant(url, args.slug, args.confirm, args.reason, actor))
        print(f"Field {args.slug} deleted: {sum(counts.values())} rows in {len(counts)} tables. Backups keep it "
              "until they expire (ATALAIA_BACKUP_DAYS).", file=out)


def main(argv: Optional[list[str]] = None, stdin: TextIO = sys.stdin, out: TextIO = sys.stdout,
         err: TextIO = sys.stderr, ask: Callable[[str], str] = getpass.getpass,
         confirm: Callable[[str], str] = input) -> int:
    args = _parser().parse_args(argv)
    if args.command in ("hosted", "import-field"):
        try:
            run_hosted(args, database_url_from_env(), out)
        except (ConfigError, hosted.HostedError, tenancy.TenantError) as e:
            print(f"atalaia_server: {e}", file=err)
            return 1
        return 0
    try:
        settings = Settings.from_env()
    except ConfigError as e:
        print(f"atalaia_server: {e}", file=err)
        return 2
    if args.command == "purge":
        asyncio.run(run_purge(settings, args.dry_run, out))
        return 0
    if args.command == "atak":
        try:
            asyncio.run(run_atak(settings, args, out))
        except (CommandError, tenancy.TenantError) as e:
            print(f"atalaia_server: {e}", file=err)
            return 1
        return 0
    if args.command == "demo":
        try:
            asyncio.run(run_demo(settings, args, out))
        except CommandError as e:
            print(f"atalaia_server: {e}", file=err)
            return 1
        return 0
    if args.command == "reset-totp":
        try:
            asyncio.run(reset_totp(settings, args.username, args.reason, args.yes, confirm, out, field=args.field))
        except (CommandError, EOFError) as e:
            print(f"atalaia_server: {e or 'not confirmed: nothing was changed'}", file=err)
            return 1
        return 0
    if args.command == "feedback":
        asyncio.run(run_feedback(settings, args, out))
        return 0
    if args.generate:
        try:
            asyncio.run(generate_admin(settings, args.username, args.email, Path(args.generate), out))
        except CommandError as e:
            print(f"atalaia_server: {e}", file=err)
            return 1
        return 0
    if args.password_stdin:
        password = stdin.readline().rstrip("\r\n")

        def read_code(uri: str, secret: str) -> str:
            print("TOTP code: ", end="", file=out, flush=True)
            return stdin.readline().strip()
    else:
        password = ask("Password: ")
        if ask("Password again: ") != password:
            print("atalaia_server: the passwords differ", file=err)
            return 1

        def read_code(uri: str, secret: str) -> str:
            return input("TOTP code from the app: ").strip()
    try:
        asyncio.run(create_admin(settings, args.username, args.email, password, read_code, out, field=args.field))
    except CommandError as e:
        print(f"atalaia_server: {e}", file=err)
        return 1
    return 0
