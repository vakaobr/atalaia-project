# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The site server's commands: ``python -m atalaia_server <command>``.

    python -m atalaia_server create-admin --username NAME [--email EMAIL] [--password-stdin]
    python -m atalaia_server purge [--dry-run]

``create-admin`` makes a server administrator (ADR-P4-2): it asks for the
password twice (or reads one line from standard input with
``--password-stdin``), checks it against the password policy, shows a new
TOTP secret and its ``otpauth://`` URI for an authenticator app, and creates
the account only after a code from that app is typed back, since an
administrator cannot log in without TOTP. In the deployed Compose project:
``docker compose exec server python -m atalaia_server create-admin --username ...``.
It needs ATALAIA_DATABASE_URL and ATALAIA_SECRET_KEY, as the server does.

``purge`` runs the retention purge (ADR-P4-8) once and prints what it
deleted (``--dry-run``: what it would delete). The server runs it by itself
every day at ATALAIA_PURGE_HOUR (03:00 UTC by default); the command is for a
deployment that turns that off and schedules it elsewhere, or for a check.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Callable, Optional, TextIO

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from . import passwords, personal_data, totp
from .api.auth import EMAIL, username_problem
from .audit import record
from .config import ConfigError, Settings
from .db import make_engine, make_sessionmaker
from .models import User
from .tokens import Keys
from .totp import SeedBox

CODE_TRIES = 3


class CommandError(Exception):
    """A problem to report in one line (exit code 1)."""


async def create_admin(settings: Settings, username: str, email: Optional[str], password: str,
                       read_code: Callable[[str, str], str], out: TextIO,
                       clock: Callable[[], float] = time.time) -> uuid.UUID:
    """Creates the administrator once a code for its new TOTP secret is confirmed; returns its id."""
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
    engine = make_engine(settings)
    try:
        maker = make_sessionmaker(engine)
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
    finally:
        await engine.dispose()


async def run_purge(settings: Settings, dry_run: bool, out: TextIO) -> dict[str, int]:
    engine = make_engine(settings)
    try:
        async with make_sessionmaker(engine)() as db:
            counts = await personal_data.purge(db, dry_run=dry_run)
    finally:
        await engine.dispose()
    verb = "would delete" if dry_run else "deleted"
    print(f"Retention purge {verb}: " + ", ".join(f"{n} {what.replace('_', ' ')} rows" for what, n in counts.items()),
          file=out)
    return counts


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m atalaia_server", description="Atalaia site server commands")
    sub = parser.add_subparsers(dest="command", required=True)
    admin = sub.add_parser("create-admin", help="create a server administrator (with TOTP)")
    admin.add_argument("--username", required=True)
    admin.add_argument("--email")
    admin.add_argument("--password-stdin", action="store_true",
                       help="read the password from the first line of standard input, the TOTP code from the next")
    purge = sub.add_parser("purge", help="delete what is past its retention period (ADR-P4-8), once")
    purge.add_argument("--dry-run", action="store_true", help="count, delete nothing")
    return parser


def main(argv: Optional[list[str]] = None, stdin: TextIO = sys.stdin, out: TextIO = sys.stdout,
         err: TextIO = sys.stderr, ask: Callable[[str], str] = getpass.getpass) -> int:
    args = _parser().parse_args(argv)
    try:
        settings = Settings.from_env()
    except ConfigError as e:
        print(f"atalaia_server: {e}", file=err)
        return 2
    if args.command == "purge":
        asyncio.run(run_purge(settings, args.dry_run, out))
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
        asyncio.run(create_admin(settings, args.username, args.email, password, read_code, out))
    except CommandError as e:
        print(f"atalaia_server: {e}", file=err)
        return 1
    return 0
