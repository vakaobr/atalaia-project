# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Site server settings, from ATALAIA_* environment variables.

    ATALAIA_DATABASE_URL    required: postgresql+asyncpg://user:password@host:5432/database
    ATALAIA_SECRET_KEY      required (at least 32 characters): the keys of the access tokens,
                            the TOTP login step and the TOTP seeds are derived from it
    ATALAIA_DB_POOL_SIZE    connections kept open (default 5, 1-100)
    ATALAIA_DB_MAX_OVERFLOW extra connections under load (default 5, 0-100)
    ATALAIA_DB_TIMEOUT_S    connect and health-check timeout in seconds (default 5, 0.1-60)
    ATALAIA_METRICS_TOKEN   optional bearer token for GET /api/v1/metrics (a monitoring
                            system); server administrators can always read it
    ATALAIA_LOG_LEVEL       debug, info (default), warning or error
    ATALAIA_PURGE_HOUR      the hour (UTC, 0-23, default 3) of the daily retention purge, or
                            "off" when something else runs `python -m atalaia_server purge`
    ATALAIA_PRIVACY_NOTICE_VERSION
                            the version of the privacy notice the field shows (default
                            "template-2026-10-19"), stored with every consent
    ATALAIA_PUBLIC_URL      the site's public origin (https://campo.example.pt): the links in
                            the field pages and feeds and the host name in iCalendar UIDs;
                            unset, they follow the request (a local trial only)
    ATALAIA_TEST_ADAPTER    "on" offers the platform adapters' test adapter (an in-memory stand-in
                            for a platform, for trials and tests); "off" by default (plan phase 17)
    ATALAIA_FIRMWARE_KEYS   the Ed25519 public keys (32 bytes in standard base64, separated by
                            commas, at most 8) whose signatures the firmware catalogue accepts
                            (plan phase 19); unset, the catalogue takes no entry at all

Plain Python with no third-party imports, so its tests also run in the
atalaia-dev image (tools/check.sh). A setting that is present but wrong is
an error at start-up, never silently replaced by its default.
"""

from __future__ import annotations

import base64
import binascii
import os
import re
from dataclasses import dataclass, field
from typing import Mapping, Optional
from urllib.parse import urlsplit, urlunsplit

LOG_LEVELS = ("debug", "info", "warning", "error")
URL_SCHEME = "postgresql+asyncpg"
MIN_METRICS_TOKEN = 32
MIN_SECRET_KEY = 32
DEFAULT_NOTICE_VERSION = "template-2026-10-19"
NOTICE_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+-]{0,63}")
_KEY_HINT = "(python3 -c \"import secrets; print(secrets.token_urlsafe(32))\")"


MAX_FIRMWARE_KEYS = 8


class ConfigError(ValueError):
    """A setting is missing or not valid."""


def check_firmware_key(text: str) -> str:
    """One release key of ATALAIA_FIRMWARE_KEYS: an Ed25519 public key, 32 bytes in standard base64."""
    try:
        raw = base64.b64decode(text.strip(), validate=True)
    except (binascii.Error, ValueError):
        raw = b""
    if len(raw) != 32:
        raise ConfigError("ATALAIA_FIRMWARE_KEYS: each key is an Ed25519 public key, 32 bytes in standard base64 "
                          "(44 characters)")
    return base64.b64encode(raw).decode("ascii")


def redact_url(url: str) -> str:
    """The URL with its password replaced by ***, for logs and error messages."""
    parts = urlsplit(url)
    if parts.password is None:
        return url
    host = parts.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    netloc = f"{parts.username or ''}:***@{host}"
    if parts.port is not None:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _check_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        parts.port  # noqa: B018  (raises ValueError for a bad port)
    except ValueError:
        raise ConfigError("ATALAIA_DATABASE_URL is not a valid URL") from None
    if parts.scheme != URL_SCHEME:
        raise ConfigError(f"ATALAIA_DATABASE_URL must start with {URL_SCHEME}:// "
                          "(PostgreSQL through asyncpg; no other database is supported)")
    if not parts.hostname:
        raise ConfigError("ATALAIA_DATABASE_URL has no host")
    if not parts.path.strip("/"):
        raise ConfigError("ATALAIA_DATABASE_URL has no database name")
    return url


def check_public_url(url: str) -> str:
    """ATALAIA_PUBLIC_URL: an http(s) origin with a host and no path, query or fragment; returned
    without a trailing slash. ``http`` only for a trial on this computer."""
    try:
        parts = urlsplit(url.strip())
        parts.port  # noqa: B018  (raises ValueError for a bad port)
    except ValueError:
        raise ConfigError("ATALAIA_PUBLIC_URL is not a valid URL") from None
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise ConfigError("ATALAIA_PUBLIC_URL must be https://<host>[:port] (the site's public address)")
    if parts.scheme == "http" and parts.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ConfigError("ATALAIA_PUBLIC_URL must use https:// (http:// only for localhost)")
    if parts.path not in ("", "/") or parts.query or parts.fragment or parts.username or parts.password:
        raise ConfigError("ATALAIA_PUBLIC_URL must be an origin only, with no path, query or user")
    return f"{parts.scheme}://{parts.netloc.lower()}"


def database_url_from_env(env: Optional[Mapping[str, str]] = None) -> str:
    """ATALAIA_DATABASE_URL alone, checked (Alembic needs nothing else)."""
    env = os.environ if env is None else env
    url = env.get("ATALAIA_DATABASE_URL", "").strip()
    if not url:
        raise ConfigError("ATALAIA_DATABASE_URL is not set "
                          "(postgresql+asyncpg://user:password@host:5432/database)")
    return _check_url(url)


def _number(env: Mapping[str, str], name: str, default: float, low: float, high: float, kind: type) -> float:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = kind(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a{'n integer' if kind is int else ' number'}, not {raw!r}") from None
    if not low <= value <= high:
        raise ConfigError(f"{name} must be between {low} and {high}, not {raw}")
    return value


def _purge_hour(env: Mapping[str, str]) -> Optional[int]:
    if env.get("ATALAIA_PURGE_HOUR", "").strip().lower() == "off":
        return None
    return int(_number(env, "ATALAIA_PURGE_HOUR", 3, 0, 23, int))


def _on_off(env: Mapping[str, str], name: str) -> bool:
    raw = env.get(name, "").strip().lower()
    if raw in ("", "off"):
        return False
    if raw == "on":
        return True
    raise ConfigError(f"{name} must be on or off, not {raw}")


@dataclass(frozen=True)
class Settings:
    database_url: str = field(repr=False)
    secret_key: str = field(repr=False)
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_timeout_s: float = 5.0
    metrics_token: Optional[str] = field(default=None, repr=False)
    log_level: str = "info"
    purge_hour: Optional[int] = 3
    privacy_notice_version: str = DEFAULT_NOTICE_VERSION
    public_url: Optional[str] = None
    test_adapter: bool = False
    firmware_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _check_url(self.database_url)
        if len(self.secret_key) < MIN_SECRET_KEY:
            raise ConfigError(f"ATALAIA_SECRET_KEY must be at least {MIN_SECRET_KEY} characters {_KEY_HINT}")
        if self.log_level not in LOG_LEVELS:
            raise ConfigError(f"ATALAIA_LOG_LEVEL must be one of {', '.join(LOG_LEVELS)}")
        if self.metrics_token is not None and len(self.metrics_token) < MIN_METRICS_TOKEN:
            raise ConfigError(f"ATALAIA_METRICS_TOKEN must be at least {MIN_METRICS_TOKEN} characters {_KEY_HINT}")
        if self.purge_hour is not None and not 0 <= self.purge_hour <= 23:
            raise ConfigError("ATALAIA_PURGE_HOUR must be an hour from 0 to 23, or off")
        if not NOTICE_VERSION.fullmatch(self.privacy_notice_version):
            raise ConfigError("ATALAIA_PRIVACY_NOTICE_VERSION must be 1-64 characters: letters, digits and . _ : + -, "
                              "starting with a letter or digit")
        if self.public_url is not None:
            object.__setattr__(self, "public_url", check_public_url(self.public_url))
        if len(self.firmware_keys) > MAX_FIRMWARE_KEYS:
            raise ConfigError(f"ATALAIA_FIRMWARE_KEYS: at most {MAX_FIRMWARE_KEYS} keys")
        object.__setattr__(self, "firmware_keys", tuple(check_firmware_key(k) for k in self.firmware_keys))

    def __repr__(self) -> str:
        return (f"Settings(database_url={redact_url(self.database_url)!r}, secret_key=set, "
                f"db_pool_size={self.db_pool_size}, "
                f"db_max_overflow={self.db_max_overflow}, db_timeout_s={self.db_timeout_s}, "
                f"metrics_token={'set' if self.metrics_token else 'unset'}, log_level={self.log_level!r}, "
                f"purge_hour={self.purge_hour!r}, privacy_notice_version={self.privacy_notice_version!r}, "
                f"public_url={self.public_url!r}, test_adapter={self.test_adapter!r}, "
                f"firmware_keys={len(self.firmware_keys)})")

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "Settings":
        env = os.environ if env is None else env
        url = database_url_from_env(env)
        secret = env.get("ATALAIA_SECRET_KEY", "").strip()
        if not secret:
            raise ConfigError(f"ATALAIA_SECRET_KEY is not set {_KEY_HINT}")
        return cls(
            database_url=url,
            secret_key=secret,
            db_pool_size=int(_number(env, "ATALAIA_DB_POOL_SIZE", 5, 1, 100, int)),
            db_max_overflow=int(_number(env, "ATALAIA_DB_MAX_OVERFLOW", 5, 0, 100, int)),
            db_timeout_s=float(_number(env, "ATALAIA_DB_TIMEOUT_S", 5.0, 0.1, 60.0, float)),
            metrics_token=env.get("ATALAIA_METRICS_TOKEN", "").strip() or None,
            log_level=env.get("ATALAIA_LOG_LEVEL", "info").strip().lower() or "info",
            purge_hour=_purge_hour(env),
            privacy_notice_version=env.get("ATALAIA_PRIVACY_NOTICE_VERSION", "").strip() or DEFAULT_NOTICE_VERSION,
            public_url=env.get("ATALAIA_PUBLIC_URL", "").strip() or None,
            test_adapter=_on_off(env, "ATALAIA_TEST_ADAPTER"),
            firmware_keys=tuple(k for k in env.get("ATALAIA_FIRMWARE_KEYS", "").split(",") if k.strip()),
        )
