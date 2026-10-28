# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Controller settings: a TOML file, then ATALAIA_<SECTION>_<KEY> environment variables.

    [controller]
    node_id = 0                 # this controller's short id on the radio
    db_path = "atalaia.db"      # SQLite store
    modes_dirs = ["modes"]      # built-in mode packages
    failover_mode = "manual"    # or "auto" (ADR-P2-8)
    power_source = 3            # 3 mains, 2 large battery, 1 small battery
    battery_pct = 100
    storage_ok = true
    persist_game_key = true     # keep the live game's key in SQLite: it survives a restart (OT-7)

    [radio]
    region = "eu868"            # the field's radio region until the GM chooses one in the
                                # console: "eu868" (868 MHz) or "as923-tw" (Taiwan, 920-925 MHz)
                                # (RFC 0001 Amendment 12); the boxes and the modem must be
                                # built for it
    channel_hz = 869525000      # the field's channel until the GM chooses one in the console
                                # (RFC 0001 Amendments 1 and 3); the whole channel must fit
                                # inside one of the region's sub-bands; left out: the region's
                                # default (869525000, or 921500000 in AS923-TW)
    max_hops = 2
    controller_pace_ms = 0      # the gap the controller leaves between its own frames (ACKs, TIME,
                                # CMDs), after the previous one was on the air; 0 = no pacing (the
                                # default until the field test decides; 800 is the relay study's
                                # H_paced, decision SL-13)
    scan_dwell_s = 60.0         # "find a quiet channel": total listening time, split across
                                # the candidates (at most 10 s each)
    quiet_threshold_dbm = -105  # a channel whose 90th-percentile noise is at or below this
                                # counts as quiet (decision CH4; to be calibrated at bring-up)

    [health]                    # node health events (decisions FU1-1 to FU1-4)
    node_offline_s = 120.0      # node.offline after a box is silent this long (more than its
                                # STATE interval: 15 s by default); 0 = no link events
    battery_low_pct = 20        # battery.low when a box reports a level below this and has not
                                # sent its own; 0 = off

    [modem]
    port = "/dev/ttyACM0"       # or socket://host:port; empty = no radio
    baudrate = 921600
    ping_interval_s = 5.0

    [api]
    host = "0.0.0.0"
    port = 8080
    gm_token = ""               # empty: generated on first start (see `tokens`)
    read_token = ""
    tls_port = 8443             # HTTPS with the field's own CA (ADR-P3-9); 0 = off
    tls_dir = ""                # where the CA and server certificate live; empty: next to db_path
    tls_names = []              # extra host names or IP addresses for the server certificate

    [checkin]                   # field check-in (ADR-P3-13, protocol/checkin.md)
    field_id = "field"          # the field's id, as in chrono records
    field_name = "Atalaia"      # shown to players (1-48 characters)
    operator = ""               # the field operator, the data controller in the privacy notice
    confirm = "auto"            # or "staff": a check-in waits until a marshal or the GM confirms it
    federation = "off"          # or "optional", "required": the federation number (never verified)
    federation_label = "FPA"
    country = ""                # the field's country, ISO 3166-1 alpha-2 (PT, ES, ...); empty: PT where the
                                # time zone is Portugal's, otherwise unset (protocol/apd.md)
    apd_checkin = false         # check the player's APD membership at check-in (protocol/apd.md)
    apd_expiry = false          # ... and its expiry date
    apd_accepted = []           # APD ids accepted; empty: any
    max_replicas = 5            # per player and game, 1-20
    max_players = 300           # per game
    chrono_valid_for = "day"    # or "game": how long a chrono pass counts
    rate_per_minute = 10        # check-ins per client address and minute
    urls = []                   # the poster's https addresses; empty: from tls_names and this host
    wifi_ssid = ""              # the field network's name on the poster
    limit_template = "portugal" # the chrono limits the classes come from (app/lib/chrono/limit_templates)
    notice_version = 1          # raise it when the privacy notice changes
    notice_pt = ""              # privacy notice files (Markdown); empty: the default ones
    notice_en = ""
    retention_days = 30         # a check-in's personal data after its game (ADR-P4-8's guest rule)

    [mqtt]
    enabled = true
    host = "localhost"
    port = 1883
    username = ""
    password = ""

    [join]
    key = ""                    # the field join key, 64 hex digits (protocol/join.md);
                                # empty: generated on first start (see `join-key`)

    [adopt]                     # adopting boxes (protocol/adoption.md): the field card and the USB cable
    usb = true                  # look for Field Boxes plugged in by USB (Espressif USB-Serial-JTAG,
                                # 303a:1001; the modem's own port is never touched) when the GM
                                # asks in the console's Adopt tab
    usb_ports = []              # more ports to look at, e.g. "socket://host.docker.internal:7001"
                                # (a COM-to-TCP bridge on the Docker host); from the environment,
                                # separated by commas

    [sync]                      # the site server (ADR-P4-3, protocol/sync.md); the controller
                                # opens every connection and the game never waits for it
    enabled = false
    url = ""                    # https://site.example.org (http:// only to this machine)
    api_key = ""                # the field's API key (43 characters); or ATALAIA_SYNC_API_KEY,
                                # or stored with `python3 -m atalaia_controller sync-key`
    ca_file = ""                # a CA certificate (PEM) to trust instead of the system's
    interval_game_s = 30.0      # between syncs while a game runs
    interval_idle_s = 300.0     # between games; failures double the wait, up to interval_idle_s
    timeout_s = 15.0            # per request
    branding = "local"          # "site": the field's branding and saved teams come from the site
                                # server (plan phase 18) and the console cannot change them
    remote_gm = false           # true: keep a WebSocket open to the site server so that a user with
                                # the gm role on the field there sees the live game and can start,
                                # pause, resume and end it, send GM messages and declared mode
                                # commands (plan phase 19, P4R12); every command is logged here
    library = true              # install the field's scenario library and game presets from the
                                # site server (plan phase 20), on every controller of the field

    [firmware]                  # firmware updates for the Field Boxes (protocol/firmware-update.md,
                                # firmware_updates.py): the GM uploads a signed release in the console
                                # and starts an update per box or for all, never during a game
    release_keys = [...]        # Ed25519 public keys (standard base64, 44 characters each, at most 8;
                                # from the environment, separated by commas) whose releases the
                                # controller accepts; default: the project's two release keys
                                # (docs/community/keys.md); empty: no release is accepted. A box checks the
                                # signature again with the keys built into its own firmware
    dir = ""                    # where the images are kept; empty: "firmware" next to db_path
    update_timeout_s = 600.0    # an update not heard of (report or HELLO) this long counts as timed out
    variants = ["box"]          # the image variants accepted ("box-bench" only for a test on the desk)

    [modes]                     # signed mode packages (protocol/mode-packages.md, signed_modes.py):
                                # the GM uploads one, or installs one from the index, in the console
    keys = []                   # trusted mode keys: Ed25519 public keys (standard base64, at most 8;
                                # from the environment, separated by commas) whose packages the
                                # controller installs; empty: no signed package is installed
                                # (`python3 tools/mode_package.py keygen` prints one)
    revoked = []                # key ids (16 hex digits) that no longer count, even when listed above;
                                # an index's revoked.json is added to them
    index = ""                  # a registry index: an https:// URL, or the path of an index.json
                                # whose packages are next to it (a field without internet); empty: none
    box_keys = []               # the mode keys (and release keys) built into the boxes' firmware
                                # (CONFIG_ATALAIA_MODE_KEYS, CONFIG_ATALAIA_OTA_RELEASE_KEYS), at most 8:
                                # only packages one of them signed are offered to boxes that lack a
                                # game's mode (mode_fetch.py); empty: none is offered. Default: the
                                # project's two registry keys, as the firmware's default
    fetch_timeout_s = 300.0     # a box fetching a game's modes not heard of this long has timed out;
                                # until then the game waits for it (the GM may stop waiting)

    [atak]                      # Cursor on Target for ATAK (ADR-P4-7 as amended, P4R18; atak.py)
    enabled = false
    multicast = "239.2.3.1:6969"  # UDP, props and zones only (TTL 1); a unicast host:port works too;
                                # empty: no UDP
    interval_s = 30.0           # every marker again this often; owner changes go at once
    staff_endpoints = []        # staff ATAK devices, "host:port" (TCP; 4242 if no port); from the
                                # environment, separated by commas
    players = false             # player positions to staff_endpoints only, never to multicast
    remote = false              # true: push the same CoT events to the site server on the sync's stream
                                # (the controller opens it, as for the remote GM), which relays them to
                                # the field's enrolled ATAK devices over TLS with client certificates
                                # (Phase 4 follow-up FU5); needs sync.enabled and a site server with
                                # its relay on
    remote_players = false      # with remote: player positions too, which the site server sends only
                                # to certificates allowed to see them (a gm's or a marshal's, P4R18)
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Mapping, Optional

from atalaia_sim import eu868, regions

from . import REPO_ROOT

# The project's registry keys (docs/community/keys.md): root d9521a79030ce544, held offline by the
# maintainer, and CI 7275108d2e3fe583, which signs the registry's verified badges. They are the
# default of the boxes' CONFIG_ATALAIA_MODE_KEYS, so they are the default of [modes] box_keys too.
# A field trusts them for its own installs only by listing them in [modes] keys.
# The project's release keys (docs/community/keys.md): root 424d053af5cdbc35, held offline by the
# maintainer, and CI 32b3c815ac30ad43, which signs the GitHub releases. They are the default of the
# boxes' CONFIG_ATALAIA_OTA_RELEASE_KEYS, so the default of [firmware] release_keys too.
PROJECT_RELEASE_KEYS = ("5tzPkN0AJSn+g34CP59linCRf/fcaWFc7GAAg7qzYNc=", "rIO8ogMU3LRLLtnt6Rys+URdKYfmNv5mxvuRJQsX9Tw=")
PROJECT_MODE_KEYS = ("I+m3rO++TcVNhvDHzI28pkNA8UGoTJSi84IWQguq4Mo=", "0nMp0OGboGJZUMsbc/ykqkxQFNdmI/a2k4nQ6YsdTIY=")

SECTIONS = {
    "controller": ("node_id", "db_path", "modes_dirs", "failover_mode", "power_source",
                   "battery_pct", "storage_ok", "persist_game_key", "tick_interval_s"),
    "radio": ("region", "channel_hz", "max_hops", "controller_pace_ms", "scan_dwell_s", "quiet_threshold_dbm"),
    "health": ("node_offline_s", "battery_low_pct"),
    "modem": ("port", "baudrate", "ping_interval_s"),
    "api": ("host", "port", "gm_token", "read_token", "tls_port", "tls_dir", "tls_names"),
    "mqtt": ("enabled", "host", "port", "username", "password"),
    "join": ("key",),
    "sync": ("enabled", "url", "api_key", "ca_file", "interval_game_s", "interval_idle_s", "timeout_s",
             "branding", "remote_gm", "library"),
    "checkin": ("field_id", "field_name", "operator", "confirm", "federation", "federation_label",
                "country", "apd_checkin", "apd_expiry", "apd_accepted", "max_replicas", "max_players", "chrono_valid_for",
                "rate_per_minute", "urls",
                "wifi_ssid", "limit_template", "notice_version", "notice_pt", "notice_en",
                "retention_days"),
    "atak": ("enabled", "multicast", "interval_s", "staff_endpoints", "players", "remote", "remote_players"),
    "firmware": ("release_keys", "dir", "update_timeout_s", "variants"),
    "modes": ("keys", "revoked", "index", "box_keys", "fetch_timeout_s"),
    "adopt": ("usb", "usb_ports"),
}


class ConfigError(ValueError):
    pass


@dataclass
class Config:
    # [controller]
    node_id: int = 0
    db_path: str = "atalaia-controller.db"
    modes_dirs: list[str] = field(default_factory=lambda: [str(REPO_ROOT / "modes")])
    failover_mode: str = "manual"
    power_source: int = 3
    battery_pct: int = 100
    storage_ok: bool = True
    persist_game_key: bool = True  # decision OT-7 (2026-10-22): on by default
    tick_interval_s: float = 0.1
    # [radio]
    region: str = regions.DEFAULT.code
    channel_hz: int = eu868.DEFAULT_CHANNEL_HZ
    max_hops: int = 2
    controller_pace_ms: int = 0  # decision SL-13: off; 800 is H_paced's gap between the controller's own frames
    scan_dwell_s: float = 60.0
    quiet_threshold_dbm: int = -105
    # [health]
    health_node_offline_s: float = 120.0
    health_battery_low_pct: int = 20
    # [modem]
    port: str = ""
    baudrate: int = 921_600
    ping_interval_s: float = 5.0
    # [api]
    host: str = "0.0.0.0"
    api_port: int = 8080
    gm_token: str = ""
    read_token: str = ""
    tls_port: int = 8443
    tls_dir: str = ""
    tls_names: list[str] = field(default_factory=list)
    # [mqtt]
    mqtt_enabled: bool = True
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_username: str = ""
    mqtt_password: str = ""
    # [join]
    join_key: str = ""
    # [checkin]
    field_id: str = "field"
    field_name: str = "Atalaia"
    operator: str = ""
    checkin_confirm: str = "auto"
    federation: str = "off"
    federation_label: str = "FPA"
    country: str = ""
    apd_checkin: bool = False
    apd_expiry: bool = False
    apd_accepted: list[str] = field(default_factory=list)
    max_replicas: int = 5
    max_players: int = 300
    chrono_valid_for: str = "day"
    rate_per_minute: int = 10
    checkin_urls: list[str] = field(default_factory=list)
    wifi_ssid: str = ""
    limit_template: str = "portugal"
    notice_version: int = 1
    notice_pt: str = ""
    notice_en: str = ""
    retention_days: int = 30
    # [sync]
    sync_enabled: bool = False
    sync_url: str = ""
    sync_api_key: str = ""
    sync_ca_file: str = ""
    sync_interval_game_s: float = 30.0
    sync_interval_idle_s: float = 300.0
    sync_timeout_s: float = 15.0
    sync_branding: str = "local"  # "local" (the console's) or "site" (pulled from the site server)
    sync_remote_gm: bool = False  # the remote GM through the site server's stream (plan phase 19)
    sync_library: bool = True  # pull the field's scenarios and presets from the site server (plan phase 20)
    # [atak]
    atak_enabled: bool = False
    atak_multicast: str = "239.2.3.1:6969"
    atak_interval_s: float = 30.0
    atak_staff_endpoints: list[str] = field(default_factory=list)
    atak_players: bool = False
    atak_remote: bool = False  # the remote ATAK relay through the site server (Phase 4 follow-up FU5)
    atak_remote_players: bool = False
    # [firmware]
    firmware_release_keys: list[str] = field(default_factory=lambda: list(PROJECT_RELEASE_KEYS))
    firmware_dir: str = ""
    firmware_update_timeout_s: float = 600.0
    firmware_variants: list[str] = field(default_factory=lambda: ["box"])
    # [modes]
    modes_keys: list[str] = field(default_factory=list)
    modes_revoked: list[str] = field(default_factory=list)
    modes_index: str = ""
    modes_box_keys: list[str] = field(default_factory=lambda: list(PROJECT_MODE_KEYS))
    modes_fetch_timeout_s: float = 300.0
    # [adopt]
    adopt_usb: bool = True
    adopt_usb_ports: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if not 0 <= self.node_id <= 0xFFFE:
            raise ConfigError("controller.node_id must be 0-65534")
        if self.failover_mode not in ("manual", "auto"):
            raise ConfigError("controller.failover_mode must be 'manual' or 'auto'")
        if not 1 <= self.max_hops <= 3:
            raise ConfigError("radio.max_hops must be 1-3 (ADR-P2-6)")
        if not 0 <= self.controller_pace_ms <= 10_000:
            raise ConfigError("radio.controller_pace_ms must be 0-10000 (0 = no pacing)")
        if self.region not in regions.BY_CODE:
            raise ConfigError(f"radio.region = {self.region!r}: one of {', '.join(regions.BY_CODE)}")
        region = regions.get(self.region)
        if region is regions.EU868 and not eu868.channel_ok(self.channel_hz):
            # The whole 125 kHz channel, not just its centre (RFC 0001 Amendment 3):
            # 869.40 MHz is inside 869.4-869.65 MHz but its channel starts at 869.3375.
            raise ConfigError(
                f"radio.channel_hz = {self.channel_hz}: the 125 kHz channel (centre +-62.5 kHz) "
                "must fit inside one EU868 sub-band (868.0-868.6, 868.7-869.2, 869.4-869.65 or "
                "869.7-870.0 MHz); the default is 869525000")
        if not region.channel_ok(self.channel_hz):
            raise ConfigError(
                f"radio.channel_hz = {self.channel_hz}: the {region.bw_hz // 1000} kHz channel must fit "
                f"inside {region.lo_hz / 1e6:g}-{region.hi_hz / 1e6:g} MHz ({region.code}); "
                f"the default is {region.default_channel_hz}")
        if not 1.0 <= self.scan_dwell_s <= 600.0:
            raise ConfigError("radio.scan_dwell_s must be 1-600 seconds")
        if not -128 <= self.quiet_threshold_dbm <= 0:
            raise ConfigError("radio.quiet_threshold_dbm must be -128 to 0")
        if not (self.health_node_offline_s == 0 or 1.0 <= self.health_node_offline_s <= 3600.0):
            raise ConfigError("health.node_offline_s must be 0 (off) or 1-3600 seconds")
        if not 0 <= self.health_battery_low_pct <= 99:
            raise ConfigError("health.battery_low_pct must be 0 (off) to 99")
        if self.tick_interval_s <= 0 or self.ping_interval_s <= 0:
            raise ConfigError("intervals must be positive")
        if not 0 <= self.tls_port <= 65535 or (self.tls_port and self.tls_port == self.api_port):
            raise ConfigError("api.tls_port must be 0 (off) or a port other than api.port")
        _check_checkin(self)
        _check_sync(self)
        _check_atak(self)
        _check_firmware(self)
        _check_modes(self)
        if len(self.adopt_usb_ports) > 8 or not all(
                re.fullmatch(r"(/dev/[\w./:-]{1,120}|socket://[\w.\[\]:-]{1,120}|COM\d{1,3})", p)
                for p in self.adopt_usb_ports):
            raise ConfigError("adopt.usb_ports: at most 8 serial ports, each /dev/..., COMn or "
                              "socket://host:port (a COM-to-TCP bridge)")
        if self.join_key:
            try:
                ok = len(bytes.fromhex(self.join_key)) == 32
            except ValueError:
                ok = False
            if not ok:
                raise ConfigError("join.key must be 64 hex digits (32 bytes)")


CHECKIN_CHOICES = {"checkin_confirm": ("auto", "staff"), "federation": ("off", "optional", "required"),
                   "chrono_valid_for": ("day", "game")}


def _check_checkin(cfg: "Config") -> None:
    from .checkin_poster import FIELD_ID_RE, FIELD_NAME_MAX, url_ok  # noqa: PLC0415

    for attr, choices in CHECKIN_CHOICES.items():
        if getattr(cfg, attr) not in choices:
            name = "confirm" if attr == "checkin_confirm" else attr
            raise ConfigError(f"checkin.{name} must be one of {', '.join(choices)}")
    if not FIELD_ID_RE.fullmatch(cfg.field_id):
        raise ConfigError("checkin.field_id: 1-64 of A-Z a-z 0-9 . _ : -")
    if not 1 <= len(cfg.field_name) <= FIELD_NAME_MAX or cfg.field_name != cfg.field_name.strip():
        raise ConfigError(f"checkin.field_name: 1-{FIELD_NAME_MAX} characters")
    if not 1 <= len(cfg.federation_label) <= 16:
        raise ConfigError("checkin.federation_label: 1-16 characters")
    if cfg.country:
        from .apd import COUNTRY_RE  # noqa: PLC0415

        if not COUNTRY_RE.fullmatch(cfg.country):
            raise ConfigError("checkin.country: two capital letters (ISO 3166-1 alpha-2, e.g. PT) or empty")
    try:
        from .apd import check_rule  # noqa: PLC0415

        check_rule({"accepted": list(cfg.apd_accepted) or None, "checkin": cfg.apd_checkin,
                    "expiry": cfg.apd_expiry})
    except ValueError as exc:
        raise ConfigError(f"checkin.apd_accepted: 1-32 distinct ids of a-z 0-9 - ({exc})") from None
    if not 1 <= cfg.max_replicas <= 20:
        raise ConfigError("checkin.max_replicas must be 1-20")
    if not 1 <= cfg.max_players <= 5000:
        raise ConfigError("checkin.max_players must be 1-5000")
    if not 1 <= cfg.rate_per_minute <= 1000:
        raise ConfigError("checkin.rate_per_minute must be 1-1000")
    if len(cfg.checkin_urls) > 3 or not all(url_ok(u) for u in cfg.checkin_urls):
        raise ConfigError("checkin.urls: at most 3 addresses like https://10.42.0.1:8443")
    if len(cfg.wifi_ssid.encode("utf-8")) > 32:
        raise ConfigError("checkin.wifi_ssid: at most 32 bytes")
    if not 1 <= cfg.notice_version <= 1_000_000:
        raise ConfigError("checkin.notice_version must be a positive integer")
    if not 1 <= cfg.retention_days <= 3653:
        raise ConfigError("checkin.retention_days must be 1-3653")


def _check_sync(cfg: "Config") -> None:
    from .sync_client import api_key_ok, url_problem  # noqa: PLC0415

    if cfg.sync_url:
        problem = url_problem(cfg.sync_url)
        if problem:
            raise ConfigError(f"sync.url: {problem}")
    elif cfg.sync_enabled:
        raise ConfigError("sync.enabled needs sync.url (the site server's https:// address)")
    if cfg.sync_api_key and not api_key_ok(cfg.sync_api_key):
        raise ConfigError("sync.api_key: the field's API key from the site server (43 characters of A-Z a-z 0-9 - _)")
    if not 1.0 <= cfg.sync_interval_game_s <= cfg.sync_interval_idle_s <= 86400.0:
        raise ConfigError("sync.interval_game_s and sync.interval_idle_s: 1 to 86400 seconds, the first not above "
                          "the second")
    if not 1.0 <= cfg.sync_timeout_s <= 300.0:
        raise ConfigError("sync.timeout_s must be 1-300 seconds")
    if cfg.sync_branding not in ("local", "site"):
        raise ConfigError("sync.branding must be 'local' (the console's) or 'site' (the site server's)")
    if cfg.sync_remote_gm and not cfg.sync_enabled:
        raise ConfigError("sync.remote_gm needs sync.enabled (the remote GM rides the sync's link)")


def _check_atak(cfg: "Config") -> None:
    from .atak import AtakConfigError, check_config  # noqa: PLC0415

    try:
        check_config(cfg)
    except AtakConfigError as exc:
        raise ConfigError(str(exc)) from None
    if cfg.atak_remote and not (cfg.atak_enabled and cfg.sync_enabled):
        raise ConfigError("atak.remote needs atak.enabled and sync.enabled (the relay rides the sync's stream)")
    if cfg.atak_remote_players and not cfg.atak_remote:
        raise ConfigError("atak.remote_players needs atak.remote")


def _check_modes(cfg: "Config") -> None:
    from .firmware_release import public_key_bytes  # noqa: PLC0415

    if len(cfg.modes_keys) > 8 or not all(public_key_bytes(k) for k in cfg.modes_keys):
        raise ConfigError("modes.keys: at most 8 Ed25519 public keys, each 32 bytes in standard base64 "
                          "(44 characters; `python3 tools/mode_package.py keygen` prints it)")
    if not all(re.fullmatch(r"[0-9a-f]{16}", k) for k in cfg.modes_revoked):
        raise ConfigError("modes.revoked: key ids, 16 lower-case hex digits each")
    if len(cfg.modes_box_keys) > 8 or not all(public_key_bytes(k) for k in cfg.modes_box_keys):
        raise ConfigError("modes.box_keys: at most 8 Ed25519 public keys, each 32 bytes in standard base64 "
                          "(the boxes' CONFIG_ATALAIA_MODE_KEYS and release keys)")
    if not 30.0 <= cfg.modes_fetch_timeout_s <= 3600.0:
        raise ConfigError("modes.fetch_timeout_s must be 30-3600 seconds")
    index = cfg.modes_index.strip()
    if index and (index.startswith(("http://", "file:", "ftp:")) or "://" in index and not index.startswith("https://")):
        raise ConfigError("modes.index: an https:// URL or the path of an index.json")


def _check_firmware(cfg: "Config") -> None:
    from .firmware_release import public_key_bytes  # noqa: PLC0415

    if len(cfg.firmware_release_keys) > 8 or not all(public_key_bytes(k) for k in cfg.firmware_release_keys):
        raise ConfigError("firmware.release_keys: at most 8 Ed25519 public keys, each 32 bytes in standard base64 "
                          "(44 characters; `python3 tools/firmware_release.py keygen` prints it)")
    if not 30.0 <= cfg.firmware_update_timeout_s <= 3600.0:
        raise ConfigError("firmware.update_timeout_s must be 30-3600 seconds")
    if not cfg.firmware_variants or not all(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,10}", v) for v in cfg.firmware_variants):
        raise ConfigError('firmware.variants: image variants such as "box" (1-11 of a-z, 0-9, -)')


# (section, key) -> Config attribute
_ATTR = {("api", "port"): "api_port", ("mqtt", "enabled"): "mqtt_enabled",
         ("mqtt", "host"): "mqtt_host", ("mqtt", "port"): "mqtt_port",
         ("mqtt", "username"): "mqtt_username", ("mqtt", "password"): "mqtt_password",
         ("join", "key"): "join_key", ("checkin", "confirm"): "checkin_confirm",
         ("checkin", "urls"): "checkin_urls"}
_ATTR.update({("sync", k): f"sync_{k}" for k in SECTIONS["sync"]})
_ATTR.update({("atak", k): f"atak_{k}" for k in SECTIONS["atak"]})
_ATTR.update({("health", k): f"health_{k}" for k in SECTIONS["health"]})
_ATTR.update({("firmware", k): f"firmware_{k}" for k in SECTIONS["firmware"]})
_ATTR.update({("modes", k): f"modes_{k}" for k in SECTIONS["modes"]})
_ATTR.update({("adopt", k): f"adopt_{k}" for k in SECTIONS["adopt"]})
# Lists whose items contain ":" (host:port) or "/" (base64): from the environment they are separated by commas.
COMMA_LISTS = {"atak_staff_endpoints", "firmware_release_keys", "adopt_usb_ports", "modes_keys", "modes_revoked",
               "modes_box_keys"}


def _attr(section: str, key: str) -> str:
    return _ATTR.get((section, key), key)


def _coerce(name: str, value: Any, default: Any) -> Any:
    if isinstance(default, bool):
        if isinstance(value, str):
            if value.lower() in ("1", "true", "yes", "on"):
                return True
            if value.lower() in ("0", "false", "no", "off"):
                return False
            raise ConfigError(f"{name}: expected true or false, got {value!r}")
        return bool(value)
    if isinstance(default, int):
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ConfigError(f"{name}: expected an integer, got {value!r}") from None
    if isinstance(default, float):
        try:
            return float(value)
        except (TypeError, ValueError):
            raise ConfigError(f"{name}: expected a number, got {value!r}") from None
    if isinstance(default, list):
        if isinstance(value, str):
            return [v for v in value.split(os.pathsep) if v]
        return [str(v) for v in value]
    return str(value)


def load_config(path: Optional[str] = None, env: Mapping[str, str] = os.environ) -> Config:
    cfg = Config()
    defaults = {f.name: getattr(cfg, f.name) for f in fields(cfg)}
    given: set[str] = set()
    if path:
        try:
            data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(f"{path}: {exc}") from None
        for section, values in data.items():
            if section not in SECTIONS or not isinstance(values, dict):
                raise ConfigError(f"{path}: unknown section [{section}]")
            for key, value in values.items():
                if key not in SECTIONS[section]:
                    raise ConfigError(f"{path}: unknown setting {section}.{key}")
                attr = _attr(section, key)
                setattr(cfg, attr, _coerce(f"{section}.{key}", value, defaults[attr]))
                given.add(attr)
    for section, keys in SECTIONS.items():
        for key in keys:
            name = f"ATALAIA_{section.upper()}_{key.upper()}"
            if name in env:
                attr = _attr(section, key)
                value: Any = env[name]
                if attr in COMMA_LISTS:
                    value = [v.strip() for v in value.split(",") if v.strip()]
                setattr(cfg, attr, _coerce(name, value, defaults[attr]))
                given.add(attr)
    # A region without a channel: the region's default channel (RFC 0001 Amendment 12).
    if "channel_hz" not in given and cfg.region in regions.BY_CODE:
        cfg.channel_hz = regions.get(cfg.region).default_channel_hz
    cfg.validate()
    return cfg
