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

Plain Python with no third-party imports, so its tests also run in the
atalaia-dev image (tools/check.sh). A setting that is present but wrong is
an error at start-up, never silently replaced by its default.
"""

from __future__ import annotations

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


class ConfigError(ValueError):
    """A setting is missing or not valid."""


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

    def __repr__(self) -> str:
        return (f"Settings(database_url={redact_url(self.database_url)!r}, secret_key=set, "
                f"db_pool_size={self.db_pool_size}, "
                f"db_max_overflow={self.db_max_overflow}, db_timeout_s={self.db_timeout_s}, "
                f"metrics_token={'set' if self.metrics_token else 'unset'}, log_level={self.log_level!r}, "
                f"purge_hour={self.purge_hour!r}, privacy_notice_version={self.privacy_notice_version!r})")

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
        )
