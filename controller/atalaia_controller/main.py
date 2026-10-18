# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Entry point: python -m atalaia_controller [run|tokens] [--config controller.toml].

    run      start the controller: radio modem, MQTT bridge, REST/WebSocket API
    tokens   print the GM and read tokens (generated on first start if not configured)
"""

from __future__ import annotations

import argparse
import logging
import secrets
import sys
from dataclasses import dataclass
from typing import Any, Callable, Optional

from atalaia_sim.core import Core, LibraryNotFound, find_library

from .api import Auth, create_app
from .config import Config, ConfigError, load_config
from .engine import Controller
from .mqtt import MqttBridge, maybe_bridge
from .radio_modem import RadioModem
from .store import Store
from .ws import Hub

log = logging.getLogger("atalaia")


def ensure_tokens(cfg: Config, store: Store) -> tuple[str, str]:
    """The configured tokens, or ones generated once and kept in the store."""
    out = []
    for name, configured in (("gm_token", cfg.gm_token), ("read_token", cfg.read_token)):
        token = configured or store.get_setting(name)
        if not token:
            token = secrets.token_urlsafe(24)
            store.set_setting(name, token)
            log.warning("generated a %s; show it with: python -m atalaia_controller tokens", name)
        out.append(token)
    if out[0] == out[1]:
        raise ConfigError("the GM and read tokens must differ")
    return out[0], out[1]


def load_core() -> Optional[Core]:
    try:
        return Core(find_library())
    except (LibraryNotFound, OSError) as exc:
        log.warning("core library not loaded (%s): field scripts and mode uploads are unavailable",
                    str(exc).splitlines()[0])
        return None


@dataclass
class Bundle:
    cfg: Config
    store: Store
    controller: Controller
    modem: Optional[RadioModem]
    mqtt: Optional[MqttBridge]
    hub: Hub
    app: Any


def build(cfg: Config, *, core: Optional[Core] = None, load_core_lib: bool = True,
          serial_factory: Optional[Callable[[], Any]] = None) -> Bundle:
    store = Store(cfg.db_path)
    gm, read = ensure_tokens(cfg, store)
    if core is None and load_core_lib:
        core = load_core()
    modem = None
    if cfg.port:
        modem = RadioModem(cfg.port, baudrate=cfg.baudrate, ping_interval=cfg.ping_interval_s,
                           serial_factory=serial_factory)
    else:
        log.warning("no modem port configured: the controller runs without a radio")
    controller = Controller(cfg, store, modem=modem, core=core)
    mqtt = maybe_bridge(cfg, controller)
    hub = Hub()

    def on_start() -> None:
        if modem is not None:
            modem.start()
        if mqtt is not None:
            mqtt.start()
        controller.start()

    def on_stop() -> None:
        controller.stop()
        if mqtt is not None:
            mqtt.stop()
        if modem is not None:
            modem.stop()

    app = create_app(controller, hub, Auth(gm, read), on_start=on_start, on_stop=on_stop)
    return Bundle(cfg, store, controller, modem, mqtt, hub, app)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m atalaia_controller", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", nargs="?", default="run", choices=("run", "tokens"))
    parser.add_argument("--config", help="TOML settings file (see controller/controller.example.toml)")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(name)s %(levelname)s %(message)s")
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"atalaia_controller: {exc}", file=sys.stderr)
        return 2
    if args.command == "tokens":
        store = Store(cfg.db_path)
        gm, read = ensure_tokens(cfg, store)
        print(f"GM token:   {gm}\nread token: {read}")
        return 0
    bundle = build(cfg)
    import uvicorn

    uvicorn.run(bundle.app, host=cfg.host, port=cfg.api_port, log_level=args.log_level.lower())
    return 0


if __name__ == "__main__":
    sys.exit(main())
