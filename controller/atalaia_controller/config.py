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
    persist_game_key = false    # keep the game key in SQLite to survive a restart

    [radio]
    channel_hz = 869525000      # the shared game channel (RFC 0001 Amendment 1)
    max_hops = 2

    [modem]
    port = "/dev/ttyACM0"       # or socket://host:port; empty = no radio
    baudrate = 921600
    ping_interval_s = 5.0

    [api]
    host = "0.0.0.0"
    port = 8080
    gm_token = ""               # empty: generated on first start (see `tokens`)
    read_token = ""

    [mqtt]
    enabled = true
    host = "localhost"
    port = 1883
    username = ""
    password = ""

    [join]
    key = ""                    # the field join key, 64 hex digits (protocol/join.md);
                                # empty: generated on first start (see `join-key`)
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Mapping, Optional

from . import REPO_ROOT

SECTIONS = {
    "controller": ("node_id", "db_path", "modes_dirs", "failover_mode", "power_source",
                   "battery_pct", "storage_ok", "persist_game_key", "tick_interval_s"),
    "radio": ("channel_hz", "max_hops"),
    "modem": ("port", "baudrate", "ping_interval_s"),
    "api": ("host", "port", "gm_token", "read_token"),
    "mqtt": ("enabled", "host", "port", "username", "password"),
    "join": ("key",),
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
    persist_game_key: bool = False
    tick_interval_s: float = 0.1
    # [radio]
    channel_hz: int = 869_525_000
    max_hops: int = 2
    # [modem]
    port: str = ""
    baudrate: int = 921_600
    ping_interval_s: float = 5.0
    # [api]
    host: str = "0.0.0.0"
    api_port: int = 8080
    gm_token: str = ""
    read_token: str = ""
    # [mqtt]
    mqtt_enabled: bool = True
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_username: str = ""
    mqtt_password: str = ""
    # [join]
    join_key: str = ""

    def validate(self) -> None:
        if not 0 <= self.node_id <= 0xFFFE:
            raise ConfigError("controller.node_id must be 0-65534")
        if self.failover_mode not in ("manual", "auto"):
            raise ConfigError("controller.failover_mode must be 'manual' or 'auto'")
        if not 1 <= self.max_hops <= 3:
            raise ConfigError("radio.max_hops must be 1-3 (ADR-P2-6)")
        if not (869_400_000 <= self.channel_hz <= 869_650_000 or 868_000_000 <= self.channel_hz <= 868_600_000
                or 868_700_000 <= self.channel_hz <= 869_200_000 or 869_700_000 <= self.channel_hz <= 870_000_000):
            raise ConfigError("radio.channel_hz must be inside an EU868 sub-band")
        if self.tick_interval_s <= 0 or self.ping_interval_s <= 0:
            raise ConfigError("intervals must be positive")
        if self.join_key:
            try:
                ok = len(bytes.fromhex(self.join_key)) == 32
            except ValueError:
                ok = False
            if not ok:
                raise ConfigError("join.key must be 64 hex digits (32 bytes)")


# (section, key) -> Config attribute
_ATTR = {("api", "port"): "api_port", ("mqtt", "enabled"): "mqtt_enabled",
         ("mqtt", "host"): "mqtt_host", ("mqtt", "port"): "mqtt_port",
         ("mqtt", "username"): "mqtt_username", ("mqtt", "password"): "mqtt_password",
         ("join", "key"): "join_key"}


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
    for section, keys in SECTIONS.items():
        for key in keys:
            name = f"ATALAIA_{section.upper()}_{key.upper()}"
            if name in env:
                attr = _attr(section, key)
                setattr(cfg, attr, _coerce(name, env[name], defaults[attr]))
    cfg.validate()
    return cfg
