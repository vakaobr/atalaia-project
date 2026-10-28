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
    ATALAIA_HOSTED          "on": hosted multi-tenant mode (ADR-P4-4, plan phase 21): one PostgreSQL
                            schema per field, each field at https://<slug>.<ATALAIA_HOSTED_DOMAIN>,
                            row-level security underneath (atalaia_server/tenancy.py, hosted.py);
                            "off" by default: a club's own single-field server, as before
    ATALAIA_HOSTED_DOMAIN   hosted mode only, and required there: the hub's domain (hub.example.pt);
                            ATALAIA_PUBLIC_URL must then be unset (each field has its own address)
    ATALAIA_LANG_FROM_BROWSER
                            "on" (default): the pages' language is ?lang=, else the browser's Accept-Language,
                            else the default; "off": only an explicit choice (?lang= or the language switcher,
                            remembered in a ``lang`` cookie) changes it, else the default (a preview, PV-9)
    ATALAIA_DEFAULT_LANG    "pt" (default) or "en": the language when nothing says otherwise
    ATALAIA_PREVIEW         "on": a preview instance (decision PV-3): a "Preview, not for real games" banner
                            on every page, the landing page, the feedback form (/feedback, stored in the
                            database, read by the server administrators), /robots.txt and
                            X-Robots-Tag: noindex everywhere; "off" by default: nothing changes
    ATALAIA_ATAK_RELAY      "on": the remote ATAK relay (Phase 4 follow-up FU5, atak_relay.py): a TLS
                            listener for the fields' enrolled ATAK devices, client certificates
                            required; "off" by default (no listener, no certificate can be issued)
    ATALAIA_ATAK_RELAY_PORT the relay's port in the container (default 8089, TAK's streaming TLS port)
    ATALAIA_ATAK_RELAY_HOST the name ATAK devices connect to, written into their data packages and the
                            relay's certificate; default: ATALAIA_PUBLIC_URL's host (hosted mode: each
                            field's <slug>.<ATALAIA_HOSTED_DOMAIN>, and this must be unset)
    ATALAIA_ATAK_RELAY_PUBLIC_PORT
                            the port ATAK devices connect to, if the deployment publishes the relay on
                            another one (default: ATALAIA_ATAK_RELAY_PORT)
    ATALAIA_PASSWORD_LOGIN  "on" (default) or "off": "off" turns password login and password registration off
                            (accounts then sign in with a passkey or a social login; decision LG-3)
    ATALAIA_APP_ANDROID_PACKAGE, ATALAIA_APP_ANDROID_SHA256
                            the Android app's package name and its signing certificate's SHA-256 (hex pairs
                            separated by colons; several, separated by commas, for a debug and a release key):
                            both set, the server serves /.well-known/assetlinks.json, which lets the app open
                            this site's /app/... links (App Links) and use its passkeys (decision PKA-1); unset:
                            nothing is served
    ATALAIA_APP_IOS_APP_IDS the iOS app's ids (<team id>.<bundle id>, separated by commas): set, the server
                            serves /.well-known/apple-app-site-association (webcredentials and applinks)
    ATALAIA_OIDC_GOOGLE_CLIENT_ID, ATALAIA_OIDC_GOOGLE_CLIENT_SECRET
    ATALAIA_OIDC_MICROSOFT_CLIENT_ID, ATALAIA_OIDC_MICROSOFT_CLIENT_SECRET,
    ATALAIA_OIDC_MICROSOFT_TENANT   (common by default: personal and work accounts; organizations, consumers
                            or one tenant's id)
    ATALAIA_OIDC_APPLE_CLIENT_ID (the Services ID), ATALAIA_OIDC_APPLE_TEAM_ID, ATALAIA_OIDC_APPLE_KEY_ID,
    ATALAIA_OIDC_APPLE_KEY_FILE     (the .p8 private key the client secret JWT is signed with)
                            each social login provider is off until all of its settings are given
                            (atalaia_server/oidc.py; decisions LG-*)

    ATALAIA_QUOTA_<NAME>    hosted mode only: one field's limit on a resource (``QUOTA_DEFAULTS`` lists the names
                            and defaults: ACCOUNTS, SCHEDULED_GAMES, REGISTRATIONS, GAMES,
                            ATAK_CERTS, STREAMS, STORED_MB), a whole number of 1 or more, or "off" for no
                            limit; past it the API answers 409 ``quota_exceeded`` (atalaia_server/quotas.py).
                            The operator may give one field its own limits in the hub's registry
                            (``hosted quota``), which override these for that field
    ATALAIA_EXPORT_MIN_INTERVAL_S
                            seconds between two data exports of the same field (default 300, 0-86400); a
                            field's administrator may download the field's data
                            (GET /api/v1/fields/{id}/export, atalaia_server/field_export.py)
    ATALAIA_EXPORT_MAX_MB   the largest export the server builds, in MB (default 512, 1-10240); a bigger one is
                            refused with 413 ``export_too_large`` (the operator's ``hosted export`` has no limit)
    ATALAIA_HOSTED_WATCH_S  hosted mode only: how often (seconds, 0.1-60, default 2) the server looks at the
                            registry and closes the open sockets of a field that was deleted or suspended
                            (atalaia_server/tenant_watch.py)

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
DEFAULT_ATAK_PORT = 8089  # TAK's streaming CoT over TLS (FU5)
# A host name of one label or more, lower case, no port: where ATAK devices reach the relay.
ATAK_HOST = re.compile(r"(?=.{1,200}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
# A DNS name of two labels or more, lower case, no port: the hosted hub's domain (plan phase 21).
HOSTED_DOMAIN = re.compile(r"(?=.{4,200}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?")


# Hosted mode's per-field quotas (atalaia_server/quotas.py): name -> default limit. They sit far above what a
# field's club needs and far below what one tenant could use to starve the others.
QUOTA_DEFAULTS: dict[str, int] = {
    "accounts": 5000,           # user accounts of the field
    "scheduled_games": 5000,    # the field's schedule (any status)
    "registrations": 50000,     # game registrations, imported ones too
    "games": 20000,             # games synced from the field's controllers (the retention purge frees room)
    "atak_certs": 200,          # live (not revoked, not expired) ATAK certificates
    "streams": 8,               # open WebSocket streams of the field's controllers
    "stored_mb": 2048,          # what the field's schema takes in the database, in MiB (tables, indexes, TOAST)
}
MAX_QUOTA = 100_000_000
DEFAULT_EXPORT_INTERVAL_S = 300
DEFAULT_EXPORT_MAX_MB = 512
DEFAULT_HOSTED_WATCH_S = 2.0
OIDC_PROVIDERS = ("google", "microsoft", "apple")
MICROSOFT_TENANT = re.compile(
    r"common|organizations|consumers|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
OIDC_VALUE = re.compile(r"[\x21-\x7e]{1,512}")  # printable ASCII, no spaces: client ids, team and key ids


class ConfigError(ValueError):
    """A setting is missing or not valid."""


@dataclass(frozen=True)
class OidcClient:
    """One social login provider's client, as the operator registered it with the provider."""

    provider: str
    client_id: str
    client_secret: Optional[str] = field(default=None, repr=False)   # Google, Microsoft
    tenant: Optional[str] = None                                      # Microsoft
    team_id: Optional[str] = None                                     # Apple
    key_id: Optional[str] = None                                      # Apple
    key_file: Optional[str] = None                                    # Apple: the .p8 file's path

    def __post_init__(self) -> None:
        if self.provider not in OIDC_PROVIDERS:
            raise ConfigError(f"unknown social login provider {self.provider!r}")
        if not OIDC_VALUE.fullmatch(self.client_id):
            raise ConfigError(f"ATALAIA_OIDC_{self.provider.upper()}_CLIENT_ID is not a client id")
        if self.provider == "microsoft" and not MICROSOFT_TENANT.fullmatch(self.tenant or ""):
            raise ConfigError("ATALAIA_OIDC_MICROSOFT_TENANT must be common, organizations, consumers or a "
                              "tenant's id (a UUID)")


ANDROID_PACKAGE = re.compile(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+")
CERT_SHA256 = re.compile(r"[0-9A-F]{2}(?::[0-9A-F]{2}){31}")
IOS_APP_ID = re.compile(r"[A-Z0-9]{10}\.[A-Za-z0-9][A-Za-z0-9.-]{0,150}")
MAX_APP_IDS = 8


def _list(env: Mapping[str, str], name: str) -> tuple[str, ...]:
    return tuple(v.strip() for v in env.get(name, "").split(",") if v.strip())


def _oidc_clients(env: Mapping[str, str]) -> tuple[OidcClient, ...]:
    """The providers whose settings are all there; one that has some and not all is an error (a typo must
    not turn a login method off silently)."""
    wanted = {"google": ("CLIENT_ID", "CLIENT_SECRET"), "microsoft": ("CLIENT_ID", "CLIENT_SECRET"),
              "apple": ("CLIENT_ID", "TEAM_ID", "KEY_ID", "KEY_FILE")}
    clients = []
    for provider, names in wanted.items():
        values = {n: env.get(f"ATALAIA_OIDC_{provider.upper()}_{n}", "").strip() for n in names}
        if not any(values.values()):
            continue
        missing = [f"ATALAIA_OIDC_{provider.upper()}_{n}" for n, v in values.items() if not v]
        if missing:
            raise ConfigError(f"{', '.join(missing)} not set: a social login provider needs all of its settings")
        if provider == "apple":
            if not os.path.isfile(values["KEY_FILE"]):
                raise ConfigError("ATALAIA_OIDC_APPLE_KEY_FILE is not a file this server can read")
            clients.append(OidcClient("apple", values["CLIENT_ID"], team_id=values["TEAM_ID"],
                                      key_id=values["KEY_ID"], key_file=values["KEY_FILE"]))
        else:
            tenant = env.get("ATALAIA_OIDC_MICROSOFT_TENANT", "").strip().lower() or "common"
            clients.append(OidcClient(provider, values["CLIENT_ID"], client_secret=values["CLIENT_SECRET"],
                                      tenant=tenant if provider == "microsoft" else None))
    return tuple(clients)


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


def _on_off(env: Mapping[str, str], name: str, default: bool = False) -> bool:
    raw = env.get(name, "").strip().lower()
    if raw == "":
        return default
    if raw == "off":
        return False
    if raw == "on":
        return True
    raise ConfigError(f"{name} must be on or off, not {raw}")


def quotas_from_env(env: Mapping[str, str]) -> dict[str, int]:
    """The per-field quotas: each default, or ATALAIA_QUOTA_<NAME> (a number of 1 or more, or "off" = 0)."""
    out = dict(QUOTA_DEFAULTS)
    for name in QUOTA_DEFAULTS:
        var = f"ATALAIA_QUOTA_{name.upper()}"
        if env.get(var, "").strip().lower() == "off":
            out[name] = 0
        else:
            out[name] = int(_number(env, var, QUOTA_DEFAULTS[name], 1, MAX_QUOTA, int))
    return out


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
    hosted: bool = False
    hosted_domain: Optional[str] = None
    atak_relay: bool = False
    preview: bool = False
    lang_from_browser: bool = True
    default_lang: str = "pt"
    atak_relay_port: int = DEFAULT_ATAK_PORT       # 0: any free port (the tests)
    atak_relay_host: Optional[str] = None
    atak_relay_public_port: Optional[int] = None
    quotas: Mapping[str, int] = field(default_factory=lambda: dict(QUOTA_DEFAULTS))  # 0: no limit
    export_min_interval_s: int = DEFAULT_EXPORT_INTERVAL_S
    export_max_mb: int = DEFAULT_EXPORT_MAX_MB
    hosted_watch_s: float = DEFAULT_HOSTED_WATCH_S
    password_login: bool = True                    # LG-3: "off" turns password login and registration off
    oidc: tuple[OidcClient, ...] = ()              # the configured social login providers (LG-1)
    app_android_package: Optional[str] = None      # PKA-1: the app's Digital Asset Links (off when unset)
    app_android_sha256: tuple[str, ...] = ()
    app_ios_app_ids: tuple[str, ...] = ()          # PKA-1: apple-app-site-association (off when unset)

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
        if self.hosted:
            domain = (self.hosted_domain or "").strip().lower()
            if not domain:
                raise ConfigError("ATALAIA_HOSTED_DOMAIN is not set: hosted mode needs the hub's domain "
                                  "(each field is at https://<slug>.<domain>)")
            if not HOSTED_DOMAIN.fullmatch(domain):
                raise ConfigError("ATALAIA_HOSTED_DOMAIN must be a domain name such as hub.example.pt "
                                  "(no scheme, port or path)")
            object.__setattr__(self, "hosted_domain", domain)
            if self.public_url is not None:
                raise ConfigError("ATALAIA_PUBLIC_URL must be unset in hosted mode: each field's address is "
                                  "https://<slug>.<ATALAIA_HOSTED_DOMAIN>")
        elif self.hosted_domain is not None:
            raise ConfigError("ATALAIA_HOSTED_DOMAIN is only for hosted mode (ATALAIA_HOSTED=on)")
        if self.default_lang not in ("pt", "en"):
            raise ConfigError("ATALAIA_DEFAULT_LANG must be pt or en")
        if self.preview and self.hosted:
            raise ConfigError("ATALAIA_PREVIEW=on is for a single-field preview server, not a hosted hub")
        self._check_atak()
        quotas = {**QUOTA_DEFAULTS, **dict(self.quotas)}
        for name, value in quotas.items():
            if name not in QUOTA_DEFAULTS:
                raise ConfigError(f"unknown quota {name!r} (known: {', '.join(QUOTA_DEFAULTS)})")
            if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= MAX_QUOTA:
                raise ConfigError(f"ATALAIA_QUOTA_{name.upper()} must be a whole number of 1 or more, or off")
        object.__setattr__(self, "quotas", quotas)
        if not 0 <= self.export_min_interval_s <= 86400:
            raise ConfigError("ATALAIA_EXPORT_MIN_INTERVAL_S must be between 0 and 86400")
        if not 1 <= self.export_max_mb <= 10240:
            raise ConfigError("ATALAIA_EXPORT_MAX_MB must be between 1 and 10240")
        if not 0.1 <= self.hosted_watch_s <= 60:
            raise ConfigError("ATALAIA_HOSTED_WATCH_S must be between 0.1 and 60")
        self._check_app()
        if len({c.provider for c in self.oidc}) != len(self.oidc):
            raise ConfigError("a social login provider is configured twice")

    def oidc_client(self, provider: str) -> Optional[OidcClient]:
        return next((c for c in self.oidc if c.provider == provider), None)

    def _check_app(self) -> None:
        """The app's identity for App Links and passkeys (PKA-1): the package and its certificates go together;
        a typo must not turn the file off silently."""
        package = self.app_android_package
        if (package is None) != (not self.app_android_sha256):
            raise ConfigError("ATALAIA_APP_ANDROID_PACKAGE and ATALAIA_APP_ANDROID_SHA256 go together: "
                              "set both or neither")
        if package is not None and not ANDROID_PACKAGE.fullmatch(package):
            raise ConfigError("ATALAIA_APP_ANDROID_PACKAGE must be an Android package name such as org.atalaia.app")
        hashes = tuple(h.strip().upper() for h in self.app_android_sha256)
        if len(hashes) > MAX_APP_IDS or not all(CERT_SHA256.fullmatch(h) for h in hashes):
            raise ConfigError("ATALAIA_APP_ANDROID_SHA256 is up to 8 SHA-256 fingerprints, each 32 hex pairs "
                              "separated by colons (keytool -list -v shows it)")
        object.__setattr__(self, "app_android_sha256", hashes)
        if len(self.app_ios_app_ids) > MAX_APP_IDS or not all(IOS_APP_ID.fullmatch(i) for i in self.app_ios_app_ids):
            raise ConfigError("ATALAIA_APP_IOS_APP_IDS is up to 8 ids like TEAMID123.org.atalaia.app")

    def _check_atak(self) -> None:
        if not 0 <= self.atak_relay_port <= 65535:
            raise ConfigError("ATALAIA_ATAK_RELAY_PORT must be a port of 1-65535")
        if self.atak_relay_public_port is not None and not 1 <= self.atak_relay_public_port <= 65535:
            raise ConfigError("ATALAIA_ATAK_RELAY_PUBLIC_PORT must be a port of 1-65535")
        if self.atak_relay_host is not None:
            host = self.atak_relay_host.strip().lower()
            if not ATAK_HOST.fullmatch(host):
                raise ConfigError("ATALAIA_ATAK_RELAY_HOST must be a host name such as campo.example.pt "
                                  "(no scheme, port or path)")
            if self.hosted:
                raise ConfigError("ATALAIA_ATAK_RELAY_HOST must be unset in hosted mode: each field's ATAK "
                                  "devices connect to <slug>.<ATALAIA_HOSTED_DOMAIN>")
            object.__setattr__(self, "atak_relay_host", host)
        if self.atak_relay and not self.hosted and self.relay_host() is None:
            raise ConfigError("ATALAIA_ATAK_RELAY=on needs ATALAIA_ATAK_RELAY_HOST or ATALAIA_PUBLIC_URL: the "
                              "name ATAK devices connect to")

    def relay_host(self, slug: Optional[str] = None) -> Optional[str]:
        """The name a field's ATAK devices connect to (hosted mode: that field's own name)."""
        if self.hosted:
            return f"{slug}.{self.hosted_domain}" if slug else None
        if self.atak_relay_host:
            return self.atak_relay_host
        return urlsplit(self.public_url).hostname if self.public_url else None

    def relay_public_port(self) -> int:
        return self.atak_relay_public_port or self.atak_relay_port or DEFAULT_ATAK_PORT

    def __repr__(self) -> str:
        return (f"Settings(database_url={redact_url(self.database_url)!r}, secret_key=set, "
                f"db_pool_size={self.db_pool_size}, "
                f"db_max_overflow={self.db_max_overflow}, db_timeout_s={self.db_timeout_s}, "
                f"metrics_token={'set' if self.metrics_token else 'unset'}, log_level={self.log_level!r}, "
                f"purge_hour={self.purge_hour!r}, privacy_notice_version={self.privacy_notice_version!r}, "
                f"public_url={self.public_url!r}, test_adapter={self.test_adapter!r}, "
                f"firmware_keys={len(self.firmware_keys)}, hosted={self.hosted!r}, "
                f"hosted_domain={self.hosted_domain!r}, atak_relay={self.atak_relay!r}, preview={self.preview!r}, "
                f"lang_from_browser={self.lang_from_browser!r}, default_lang={self.default_lang!r}, "
                f"atak_relay_port={self.atak_relay_port}, atak_relay_host={self.atak_relay_host!r}, "
                f"atak_relay_public_port={self.atak_relay_public_port!r}, quotas={dict(self.quotas)!r}, "
                f"export_min_interval_s={self.export_min_interval_s}, export_max_mb={self.export_max_mb}, "
                f"hosted_watch_s={self.hosted_watch_s}, password_login={self.password_login!r}, "
                f"oidc={[c.provider for c in self.oidc]!r})")

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
            hosted=_on_off(env, "ATALAIA_HOSTED"),
            hosted_domain=env.get("ATALAIA_HOSTED_DOMAIN", "").strip() or None,
            atak_relay=_on_off(env, "ATALAIA_ATAK_RELAY"),
            preview=_on_off(env, "ATALAIA_PREVIEW"),
            lang_from_browser=_on_off(env, "ATALAIA_LANG_FROM_BROWSER", default=True),
            default_lang=env.get("ATALAIA_DEFAULT_LANG", "").strip().lower() or "pt",
            atak_relay_port=int(_number(env, "ATALAIA_ATAK_RELAY_PORT", DEFAULT_ATAK_PORT, 1, 65535, int)),
            atak_relay_host=env.get("ATALAIA_ATAK_RELAY_HOST", "").strip() or None,
            atak_relay_public_port=(int(_number(env, "ATALAIA_ATAK_RELAY_PUBLIC_PORT", 0, 1, 65535, int))
                                    if env.get("ATALAIA_ATAK_RELAY_PUBLIC_PORT", "").strip() else None),
            quotas=quotas_from_env(env),
            export_min_interval_s=int(_number(env, "ATALAIA_EXPORT_MIN_INTERVAL_S", DEFAULT_EXPORT_INTERVAL_S,
                                              0, 86400, int)),
            export_max_mb=int(_number(env, "ATALAIA_EXPORT_MAX_MB", DEFAULT_EXPORT_MAX_MB, 1, 10240, int)),
            hosted_watch_s=float(_number(env, "ATALAIA_HOSTED_WATCH_S", DEFAULT_HOSTED_WATCH_S, 0.1, 60.0, float)),
            password_login=_on_off(env, "ATALAIA_PASSWORD_LOGIN", default=True),
            oidc=_oidc_clients(env),
            app_android_package=env.get("ATALAIA_APP_ANDROID_PACKAGE", "").strip() or None,
            app_android_sha256=_list(env, "ATALAIA_APP_ANDROID_SHA256"),
            app_ios_app_ids=_list(env, "ATALAIA_APP_IOS_APP_IDS"),
        )
