# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Entry point: python -m atalaia_controller [run|tokens|join-key|ca|sync-key] [--config controller.toml].

    run       start the controller: radio modem, MQTT bridge, REST/WebSocket API, GM console
              (HTTP on [api] port, HTTPS with the field CA on [api] tls_port), and with
              [atak] enabled the CoT feed for ATAK
    tokens    print the GM and read tokens (generated on first start if not configured)
    join-key  print the field join key that authenticates join cards (protocol/join.md):
              boxes get it when they are adopted (protocol/adoption.md), a standby controller
              in [join] key; --fingerprint prints only its fingerprint, --rotate makes a new one
              (after a field card is lost: every box must then be adopted again)
    ca        print the field CA's fingerprint (it is on the check-in poster) and its folder
    sync-key  store the field's site server API key, read from standard input (ADR-P4-3);
              --status shows where the key comes from and its fingerprint, --clear forgets
              the stored one, --resend sends every game and the chrono registry to the site server again
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from atalaia_sim.core import Core, LibraryNotFound, find_library

from . import tls as tlsmod
from .adoption import PREVIOUS_SETTING, Adoption
from .api import Auth, create_app
from .atak import AtakEmitter
from .checkin import Checkin
from .config import Config, ConfigError, load_config
from .engine import Controller
from .firmware_updates import FirmwareUpdates, firmware_dir
from .mqtt import MqttBridge, maybe_bridge
from .positions import Positions
from .prop_link import PropLinks
from .radio_modem import RadioModem
from .mode_fetch import ModeFetch
from .signed_modes import SignedModes
from .store import Store
from .remote_gm import RemoteGm
from .sync_client import KEY_SETTING, SyncClient, api_key_ok, key_fingerprint, resolve_api_key
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


def ensure_join_key(cfg: Config, store: Store) -> bytes:
    """The configured field join key, or one generated once and kept in the store."""
    if cfg.join_key:
        return bytes.fromhex(cfg.join_key)
    stored = store.get_setting("join_key")
    if not stored:
        stored = secrets.token_bytes(32).hex()
        store.set_setting("join_key", stored)
        log.warning("generated the field join key; show it with: python -m atalaia_controller join-key")
    return bytes.fromhex(stored)


def load_core() -> Optional[Core]:
    try:
        return Core(find_library())
    except (LibraryNotFound, OSError) as exc:
        log.warning("core library not loaded (%s): field scripts and mode uploads are unavailable",
                    str(exc).splitlines()[0])
        return None


def tls_dir(cfg: Config) -> Path:
    if cfg.tls_dir:
        return Path(cfg.tls_dir)
    return Path(os.path.dirname(os.path.abspath(cfg.db_path))) / "tls"


def ensure_tls(cfg: Config) -> Optional[tlsmod.FieldTls]:
    """The field CA and the server certificate, made on first start (None with tls_port = 0)."""
    if not cfg.tls_port:
        return None
    return tlsmod.ensure(tls_dir(cfg), tlsmod.local_names(cfg.tls_names), cfg.field_name)


def poster_urls(cfg: Config, tls: Optional[tlsmod.FieldTls], container: Optional[bool] = None) -> list[str]:
    """The https addresses of the poster and of the boxes' joins (key 14): the configured names first,
    then this host's names and addresses that another device can reach (none in a container: OT-10)."""
    if tls is None:
        return []
    if container is None:
        container = tlsmod.in_container()
    names = tlsmod.link_names(cfg.tls_names, tls.names, container)
    if container and not cfg.tls_names:
        log.warning("running in a container with no [api] tls_names: the boxes and the check-in poster get no "
                    "address for this controller (its own host name and addresses resolve only inside the "
                    "container); set [api] tls_names to the address the field reaches it at")
    out = []
    for name in names:
        host = f"[{name}]" if ":" in name else name
        url = f"https://{host}:{cfg.tls_port}" if cfg.tls_port != 443 else f"https://{host}"
        if url not in out and len(url) <= 64:
            out.append(url)
    return out[:3]


@dataclass
class Bundle:
    cfg: Config
    store: Store
    controller: Controller
    modem: Optional[RadioModem]
    mqtt: Optional[MqttBridge]
    hub: Hub
    app: Any
    tls: Optional[tlsmod.FieldTls] = None
    sync: Optional[SyncClient] = None
    atak: Optional[AtakEmitter] = None
    remote: Optional[RemoteGm] = None


def build(cfg: Config, *, core: Optional[Core] = None, load_core_lib: bool = True,
          serial_factory: Optional[Callable[[], Any]] = None) -> Bundle:
    store = Store(cfg.db_path)
    gm, read = ensure_tokens(cfg, store)
    join_key = ensure_join_key(cfg, store)
    if core is None and load_core_lib:
        core = load_core()
    modem = None
    if cfg.port:
        modem = RadioModem(cfg.port, baudrate=cfg.baudrate, ping_interval=cfg.ping_interval_s,
                           serial_factory=serial_factory)
    else:
        log.warning("no modem port configured: the controller runs without a radio")
    controller = Controller(cfg, store, modem=modem, core=core, join_key=join_key)
    tls = ensure_tls(cfg)
    controller.ca_sha256 = tls.ca_sha256 if tls else None
    controller.link_urls = poster_urls(cfg, tls)
    Checkin(controller, ca_sha256=tls.ca_sha256 if tls else None, default_urls=controller.link_urls)
    Positions(controller)
    PropLinks(controller)
    FirmwareUpdates(controller, firmware_dir(cfg.db_path, cfg.firmware_dir), cfg.firmware_release_keys,
                    cfg.firmware_update_timeout_s, variants=cfg.firmware_variants)
    SignedModes(controller, cfg.modes_keys, cfg.modes_revoked, cfg.modes_index)
    ModeFetch(controller, cfg.modes_box_keys, cfg.modes_fetch_timeout_s)
    Adoption(controller)
    mqtt = maybe_bridge(cfg, controller)
    hub = Hub()
    sync = None
    if cfg.sync_enabled:
        sync = SyncClient(cfg, store, checkin=controller.checkin, controller=controller)
        controller.sync = sync
        controller.add_listener(sync.on_controller_message)
    remote = None
    key, _ = resolve_api_key(cfg, store)
    if sync is not None and (cfg.sync_remote_gm or cfg.atak_remote) and key:
        # The remote GM (plan phase 19, P4R12) and the remote ATAK relay (FU5): only with [sync] remote_gm
        # or [atak] remote on, on a socket this controller opens; the site server never holds the GM token.
        client = sync
        remote = RemoteGm(cfg, store, controller, api_key=key, controller_id=lambda: client.controller_id)
        sync.remote = remote
        controller.add_listener(remote.on_controller_message)
    atak = AtakEmitter(cfg, controller, remote=remote) if cfg.atak_enabled else None

    def on_start() -> None:
        if modem is not None:
            modem.start()
        if mqtt is not None:
            mqtt.start()
        controller.start()
        if sync is not None:
            sync.start()
        if remote is not None:
            remote.start()
        if atak is not None:
            atak.start()

    def on_stop() -> None:
        if atak is not None:
            atak.stop()
        if remote is not None:
            remote.stop()
        if sync is not None:
            sync.stop()
        controller.stop()
        if mqtt is not None:
            mqtt.stop()
        if modem is not None:
            modem.stop()

    app = create_app(controller, hub, Auth(gm, read), on_start=on_start, on_stop=on_stop,
                     ca_pem=tls.ca_pem if tls else None)
    return Bundle(cfg, store, controller, modem, mqtt, hub, app, tls, sync, atak, remote)


def serve(bundle: Bundle, log_level: str = "info") -> None:
    """HTTP on [api] port and, with the field CA, HTTPS on [api] tls_port: one app, one lifespan."""
    import uvicorn  # noqa: PLC0415

    cfg = bundle.cfg
    servers = [uvicorn.Server(uvicorn.Config(bundle.app, host=cfg.host, port=cfg.api_port,
                                             log_level=log_level, lifespan="on"))]
    if bundle.tls is not None:
        servers.append(uvicorn.Server(uvicorn.Config(
            bundle.app, host=cfg.host, port=cfg.tls_port, log_level=log_level, lifespan="off",
            ssl_certfile=str(bundle.tls.server_cert), ssl_keyfile=str(bundle.tls.server_key))))
        log.info("HTTPS on port %d with the field CA %s", cfg.tls_port, bundle.tls.ca_sha256.hex())

    async def run_all() -> None:
        await asyncio.gather(*(srv.serve() for srv in servers))

    asyncio.run(run_all())


def sync_key(cfg: Config, store: Store, action: str, stdin: Any = sys.stdin) -> int:
    """The sync-key command: store, show, clear the API key, or send everything again."""
    if action == "status":
        key, source = resolve_api_key(cfg, store)
        state = "on" if cfg.sync_enabled else "off ([sync] enabled = false)"
        if key is None:
            print(f"sync: {state}\nAPI key: none")
        else:
            where = "settings ([sync] api_key or ATALAIA_SYNC_API_KEY)" if source == "config" else "the store"
            print(f"sync: {state}\nsite server: {cfg.sync_url or '(no [sync] url)'}\n"
                  f"API key: from {where}, fingerprint {key_fingerprint(key)}")
        return 0
    if action == "clear":
        store.set_setting(KEY_SETTING, "")
        print("the stored API key is gone" + (" ([sync] api_key is still set)" if cfg.sync_api_key else ""))
        return 0
    if action == "resend":
        n = store.reset_sync_state()
        print(f"every game and the chrono registry are sent again at the next sync ({n} games were sent "
              "before); the site server drops what it already has")
        return 0
    if stdin.isatty():
        import getpass  # noqa: PLC0415

        key = getpass.getpass("the field's API key from the site server: ").strip()
    else:
        key = stdin.readline().strip()
    if not api_key_ok(key):
        print("atalaia_controller: that is not a site server API key (43 characters of A-Z a-z 0-9 - _)",
              file=sys.stderr)
        return 2
    store.set_setting(KEY_SETTING, key)
    print(f"stored the API key {key_fingerprint(key)}" +
          (" ([sync] api_key is set and wins over it)" if cfg.sync_api_key else ""))
    return 0


def join_key_command(cfg: Config, store: Store, action: str) -> int:
    """join-key: print the key (show), its fingerprint, or make a new one (rotate, protocol/adoption.md)."""
    from atalaia_sim.field_card import fingerprint  # noqa: PLC0415

    if action == "rotate":
        if cfg.join_key:
            print("atalaia_controller: [join] key is set in the settings; put a new one there "
                  "(64 hex digits) instead", file=sys.stderr)
            return 2
        old = ensure_join_key(cfg, store)
        new = secrets.token_bytes(32)
        store.set_setting(PREVIOUS_SETTING, fingerprint(old))
        store.set_setting("join_key", new.hex())
        log.warning("adoption: the field join key was rotated (%s -> %s)", fingerprint(old), fingerprint(new))
        print(f"new field join key, fingerprint {fingerprint(new)} (was {fingerprint(old)}).\n"
              "Restart the controller. Then adopt every box again (field card or USB cable; a box still on\n"
              "the old key asks for its admin PIN), write new field cards and destroy the old ones, and\n"
              "give a standby controller the new key ([join] key). Join cards made before no longer work.")
        return 0
    key = ensure_join_key(cfg, store)
    print(fingerprint(key) if action == "fingerprint" else key.hex())
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m atalaia_controller", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", nargs="?", default="run",
                        choices=("run", "tokens", "join-key", "ca", "sync-key"))
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--status", action="store_true", help="sync-key: where the API key comes from")
    group.add_argument("--clear", action="store_true", help="sync-key: forget the stored API key")
    group.add_argument("--resend", action="store_true", help="sync-key: send every game and the chrono registry again")
    group.add_argument("--fingerprint", action="store_true",
                       help="join-key: print only the key's fingerprint (what boxes and the console show)")
    group.add_argument("--rotate", action="store_true",
                       help="join-key: make a new field join key (after a field card is lost); every box "
                            "and standby controller must then be given the new one")
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
    if args.command == "sync-key":
        action = "status" if args.status else "clear" if args.clear else "resend" if args.resend else "set"
        return sync_key(cfg, Store(cfg.db_path), action)
    if args.command == "join-key":
        action = "rotate" if args.rotate else "fingerprint" if args.fingerprint else "show"
        return join_key_command(cfg, Store(cfg.db_path), action)
    if args.command == "ca":
        tls = ensure_tls(cfg)
        if tls is None:
            print("HTTPS is off ([api] tls_port = 0)")
            return 1
        from .checkin_poster import fingerprint_text, short_fingerprint  # noqa: PLC0415

        print(f"field CA:    {fingerprint_text(tls.ca_sha256)}\nshort form:  {short_fingerprint(tls.ca_sha256)}"
              f"\nfolder:      {tls.dir}\nnames:       {', '.join(tls.names)}")
        return 0
    serve(build(cfg), args.log_level.lower())
    return 0


if __name__ == "__main__":
    sys.exit(main())
