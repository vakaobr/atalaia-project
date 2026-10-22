# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The controller engine: games, the radio side, the store and the live feed.

The radio side of a game is the simulator's FieldController (shared code,
tested there over the radio model), sending through the USB modem
(ModemTransport) and fed with the modem's RX frames. Around it the engine
keeps the SQLite store, runs the mode's field.lua (if it has one) in the C
core, and tells its listeners (WebSocket hub, MQTT bridge) what happens.

Everything that changes state holds one lock; a background thread ticks
the FieldController (TIME beacons, election) every ``tick_interval_s``.

The field's radio channel is a setting kept in the store (channels.py,
RFC 0001 Amendment 3): new games use it, it goes to the modem with
SET_CHANNEL and CONFIGURE and to the boxes in the join payload. It can
only change while no game is live, and the noise scan that helps choose
it runs only then too (measuring takes the modem off the channel).

Between games, free boxes announce themselves and the GM can invite them
into the next game over the radio (reinvite.py, protocol/field-frames.md).
A game starts only once every role it needs has a joined node (a box or a
linked Android prop): ``start_check`` says which roles are missing, and the
GM can start anyway with ``force`` (logged, and told to every console).
Mode minimums (Hold-All's ``min_zones``, Last Stand's ``last_zones``) are
warnings, never a block (decisions RJ-1 to RJ-3).
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import threading
import time
from collections import Counter
from typing import Any, Callable, Optional

from atalaia_sim import eu868
from atalaia_sim import join as joinfmt
from atalaia_sim.core import Core, Emitted, FieldOps, Node
from atalaia_sim.election import LEADER, Election, priority_score
from atalaia_sim.field_controller import (
    CMD_OPCODES,
    GAME_ENDED,
    GAME_PAUSED,
    GAME_RUNNING,
    GAME_WAITING,
    HEALTH_EVENTS,
    LINK_GAP_MS,
    FieldController,
    FieldNode,
    NotController,
)
from atalaia_sim.mode import COMMAND_NAME, SEPARATOR, ModeError
from atalaia_sim.packet import Header, vf_make

from . import channels, radio_modem, visibility
from . import scenario_service as scenarios
from .pairing import Pairing
from .reinvite import Reinvite
from .config import Config
from .modem_framing import RxPacket
from .modes import ModeRegistry, resolve_params
from .store import Store, epoch_tag

log = logging.getLogger("atalaia.controller")

TEAM_NAME_MAX = 23  # ATALAIA_TEAM_NAME_MAX - 1 in the core
SQUADS_MAX = 16     # squads per team a game may define
BOX_LANGUAGES = ("auto", "pt", "en")  # the boxes' screens (join key 15); auto: the console's
TEAM_DISPLAY_MAX = 32  # characters of a team's display name (decision BR13)
CREST_ID_RE = re.compile(r"[0-9a-f]{64}")
GAME_TIME_SAVE_MS = 5_000
# Commands for one node; the lifecycle (start, pause, resume, end) goes through the game.
# "mode" is a mode command (RFC 0001 Amendment 5): params name one of the commands the
# game's manifests declare (`commands`, such as the Medic Kit's refill).
NODE_COMMANDS = ("set_owner", "message", "reset", "reboot", "mode")


class ControllerError(Exception):
    status = 400


class NotFound(ControllerError):
    status = 404


class Conflict(ControllerError):
    status = 409


class Unavailable(ControllerError):
    status = 503


class StartBlocked(Conflict):
    """Start refused: roles of the game with no joined node (start_check); force overrides it."""

    def __init__(self, message: str, check: dict[str, Any]) -> None:
        super().__init__(message)
        self.check = check


class ModemTransport:
    """The controller's own packets, as TX frames to the modem.

    The controller owns its (epoch, seq) nonce counter (ADR-P2-2): the epoch
    is stored +1 before the first packet of every run, and again when seq
    wraps, so a nonce is never reused; the modem also refuses any (epoch,
    seq) that is not above the last one it sent.
    """

    def __init__(self, modem: Optional[radio_modem.RadioModem], store: Store, game_id: int,
                 node_id: int, max_hops: int, channel_hz: int, key: bytes,
                 wifi: Optional[Callable[[int, bytes], bool]] = None, resuming: bool = False) -> None:
        self.modem = modem
        # Android props linked over Wi-Fi get the TIME beacons and commands too (prop_link.py).
        self.wifi = wifi
        self.store = store
        self.game_id = game_id
        self.node_id = node_id
        self.max_hops = max_hops
        self.channel_hz = channel_hz
        self.key = key
        # Per game key (RFC 0001 amendment of 2026-10-22): a new game starts at epoch 1.
        self.epoch = store.next_tx_epoch(key, resuming)
        self._next = 0
        self.seq = 0  # last seq sent (FieldController.seq)
        self.refused = 0
        self.configure_modem()

    def configure_modem(self) -> None:
        if self.modem is not None:
            self.modem.configure(self.game_id, self.node_id, self.epoch, self.max_hops,
                                 self.channel_hz, self.key)

    def send(self, msg_type: int, payload: bytes, *, priority: int, ack_req: bool,
             hop_limit: int, now_ms: int) -> Optional[int]:
        on_wifi = self.wifi(msg_type, payload) if self.wifi is not None else False
        if self.modem is None or not self.modem.is_up:
            self.refused += 1
            return self.seq if on_wifi else None
        if self._next > 0xFFFF:
            self.epoch = self.store.next_tx_epoch(self.key)  # persisted before the first packet with it
            self._next = 0
            self.configure_modem()
        seq = self._next
        header = Header(vf_make(1, priority, ack_req, True), self.game_id, self.node_id, seq,
                        hop_limit, msg_type)
        if not self.modem.send_packet(header, payload):
            self.refused += 1
            return None
        self._next = seq + 1
        self.seq = seq
        return seq


class FieldScript:
    """A mode's field.lua running in the core, with field.* answered by the engine.

    Its score.add() gains are the controller's own counters: they never
    travel in a box's STATE, so they are merged into the totals under
    ``score_key`` (one key per run of the script: a restart or a takeover
    starts a new run, whose points add to the earlier runs'). A game.end it
    emits (game.finish, game.win) ends the game once the script has
    returned (``pending_end``), never from inside the core's callback.
    """

    def __init__(self, core: Core, engine: "Controller", source: str, chunk: str,
                 teams: list[str], params: dict[str, Any], seed: int,
                 score_key: str = "field-1") -> None:
        self.engine = engine
        self.teams = list(teams)
        self.score_key = score_key
        self.state: dict[str, Any] = {}
        self.pending_end: Optional[dict[str, Any]] = None
        ops = FieldOps(nodes=self._nodes, owner=self._owner, send=self._send, on_state=self._on_state)
        self.node = Node(core, engine.node_id, seed, teams, params, source, chunk,
                         on_event=self._on_event, on_log=self._on_log, field_ops=ops)
        if not self.node.loaded:
            raise ModeError(f"field.lua does not load: {self.node.last_error}")

    def _fc(self) -> FieldController:
        assert self.engine.fc is not None
        return self.engine.fc

    def _nodes(self, role: Optional[str]) -> list[dict[str, Any]]:
        fc = self._fc()
        # A scenario's node names, as the GM gave them to the boxes in the Join tab (M6-7, P4R8);
        # else the box's own name.
        names = self.engine.scenario_names
        return [{"id": n.node_id, "name": names.get(n.node_id, n.name), "role": n.role,
                 "owner": n.owner_name(fc.teams)}
                for n in sorted(fc.nodes.values(), key=lambda n: n.node_id)
                if role is None or n.role == role]

    def _owner(self, node_id: int) -> Optional[str]:
        node = self._fc().nodes.get(node_id)
        return node.owner_name(self._fc().teams) if node else None

    def _send(self, node_id: int, cmd: str, params: dict[str, Any]) -> bool:
        if cmd == "mode" and not COMMAND_NAME.match(str((params or {}).get("name", ""))):
            return False  # a mode command names itself (atalaia_sim.mode.COMMAND_NAME)
        if cmd == "update":
            return False  # firmware updates are the GM's alone (firmware_updates.py, decision FU3-4)
        try:
            return self._fc().send_cmd(cmd, params or None, dest=node_id,
                                       now_ms=self.engine.now_ms()) is not None
        except (ValueError, NotController):
            return False

    def _on_state(self, key: str, value: Any) -> None:
        self.state[key] = value
        self.engine._emit({"type": "field_state", "key": key, "value": value})

    def _on_event(self, ev: Emitted) -> None:
        if ev.type == "game.end":
            self.pending_end = dict(ev.data)
            return
        fc = self._fc()
        team = fc.team_name(ev.team)
        fc.controller_event(ev.type, ev.data, team=team, prio=ev.prio)

    def _on_log(self, line: str) -> None:
        log.info("field.lua: %s", line)

    def input(self, type_: str, data: Optional[dict[str, Any]] = None) -> None:
        self.node.input(type_, data)
        self._merge_gains()

    def advance(self, game_time_ms: int) -> None:
        self.node.advance(game_time_ms)
        self._merge_gains()

    def gains(self) -> dict[str, int]:
        return {t: self.node.gained(t) for t in self.teams if self.node.gained(t)}

    def _merge_gains(self) -> None:
        gains = self.gains()
        if gains:
            self._fc().merge_counters(self.score_key, gains)

    def close(self) -> None:
        self.node.close()


class Controller:
    def __init__(self, cfg: Config, store: Store, *, modem: Optional[radio_modem.RadioModem] = None,
                 core: Optional[Core] = None, clock: Callable[[], float] = time.monotonic,
                 join_key: bytes = b"") -> None:
        self.cfg = cfg
        # The field join key authenticates join payloads (protocol/join.md); never on the API.
        self.join_key = join_key
        self.store = store
        self.modem = modem
        self.core = core
        self.modes = ModeRegistry(store, cfg.modes_dirs, core)
        self._clock = clock
        self._t0 = clock()
        self._lock = threading.RLock()
        self._listeners: list[Callable[[dict[str, Any]], None]] = []
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

        self.priority = priority_score(cfg.power_source, cfg.battery_pct, cfg.storage_ok, 100)
        self.game: Optional[dict[str, Any]] = None
        self.fc: Optional[FieldController] = None
        self.transport: Optional[ModemTransport] = None
        self.field: Optional[FieldScript] = None
        self._field_scores: dict[str, dict[str, int]] = {}  # field.lua points per run
        self.scenario_names: dict[int, str] = {}  # the live game's box names for its scenario (Join tab)
        self._devices: dict[int, str] = {}  # the live game's device ids by node id (BN-18)
        self.conflicts: dict[int, list[str]] = {}  # node ids two devices said HELLO on
        self._meta_cache: dict[str, tuple[int, Optional[scenarios.Meta]]] = {}
        self.key_lost = False
        self._key = b""
        self.tx_status: Counter[str] = Counter()
        self._last_time_save = 0
        self.scan: Optional[channels.Scan] = None
        # Phase 3 (plan phase E): field check-in, player positions, Android props on Wi-Fi.
        # Set by checkin.Checkin, positions.Positions and prop_link.PropLinks.
        self.checkin: Any = None
        self.positions: Any = None
        self.prop_links: Any = None
        self.branding: Any = None  # branding.Branding: the field's logo, wallpaper, crests (BR1-BR24)
        self.sync: Any = None      # sync_client.SyncClient: the site server sync (ADR-P4-3), when on
        self.atak: Any = None      # atak.AtakEmitter: CoT for ATAK (ADR-P4-7), when [atak] enabled
        self.ca_sha256: Optional[bytes] = None  # the field CA (tls.py): join payload key 13
        self.link_urls: list[str] = []          # its https addresses: join payload key 14
        # Why the live game may not start now (firmware updates still running), or None.
        self.start_guard: Optional[Callable[[], Optional[str]]] = None
        # More of the same: boxes still fetching the game's modes (mode_fetch.py), and others.
        self.start_guards: list[Callable[[], Optional[str]]] = []
        self.firmware: Any = None  # firmware_updates.FirmwareUpdates, set by main.build
        self.signed_modes: Any = None  # signed_modes.SignedModes, set by main.build
        self.mode_fetch: Any = None  # mode_fetch.ModeFetch, set by main.build
        self.adoption: Any = None  # adoption.Adoption: field cards and USB adoption, set by main.build
        self._last_scan: Optional[dict[str, Any]] = None
        saved_scan = store.get_setting("radio.last_scan")
        if saved_scan:
            try:
                self._last_scan = json.loads(saved_scan)
            except ValueError:
                self._last_scan = None
        stored = self.store.get_setting("radio.channel_hz")
        if stored is not None and (not stored.isdigit() or not eu868.channel_ok(int(stored))):
            log.error("the stored field channel %r is not a legal EU868 game channel; using the "
                      "configured %d Hz", stored, cfg.channel_hz)
            self.store.set_setting("radio.channel_source", "default")
            self.store.set_setting("radio.channel_hz", str(cfg.channel_hz))
        elif stored is not None and int(stored) != cfg.channel_hz:
            log.info("field channel %s Hz (chosen in the console; radio.channel_hz = %d is the "
                     "default)", stored, cfg.channel_hz)

        # Free boxes and invites between games (reinvite.py); needs the field join key.
        self.reinvite: Optional[Reinvite] = Reinvite(self) if join_key else None
        # Unadopted boxes paired by the code they show (pairing.py, protocol/adoption.md).
        self.pairing: Optional[Pairing] = Pairing(self) if join_key else None
        if modem is not None:
            modem.on_rx = self._on_rx
            modem.on_tx_ack = self._on_tx_ack
            modem.on_state = self._on_modem_state
            modem.on_error = self._on_modem_error
            if self.reinvite is not None:
                modem.on_field_rx = self._on_field_rx
                modem.on_field_ack = self._on_field_ack
        self._restore()

    # --- plumbing -----------------------------------------------------------

    def now_ms(self) -> int:
        return int((self._clock() - self._t0) * 1000)

    def add_listener(self, fn: Callable[[dict[str, Any]], None]) -> None:
        self._listeners.append(fn)

    def _emit(self, msg: dict[str, Any]) -> None:
        for fn in list(self._listeners):
            try:
                fn(msg)
            except Exception:
                log.exception("listener failed")

    @property
    def node_id(self) -> int:
        """This controller's short id in the live game (a joined standby has its own), else the configured one."""
        if self.game is not None and self.game.get("node_id") is not None:
            return int(self.game["node_id"])
        return self.cfg.node_id

    @property
    def radio_state(self) -> str:
        return self.modem.state if self.modem is not None else "none"

    def stop_scan(self) -> None:
        if self.scan is not None:
            self.scan.cancel()
            self.scan.join(15)

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="controller-tick", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.stop_scan()
        if self._thread is not None:
            self._thread.join(timeout=5)
        with self._lock:
            self._save_game_time()
            if self.field is not None:
                self.field.close()
                self.field = None

    def _run(self) -> None:
        while not self._stop.wait(self.cfg.tick_interval_s):
            try:
                self.tick()
            except Exception:
                log.exception("controller tick failed")

    # --- games: activation and restore ---------------------------------------

    def _activate(self, game: dict[str, Any], key: bytes, term: int, lead: bool = True,
                  resuming: bool = False) -> None:
        """Puts a game on the radio: transport, FieldController, election, hooks.

        lead=False for a game joined as a standby controller: it follows the
        TIME beacons until it is promoted (ADR-P2-8).
        """
        node_id = game.get("node_id")
        node_id = self.cfg.node_id if node_id is None else int(node_id)
        channel = game.get("channel_hz") or self.cfg.channel_hz
        max_hops = game.get("max_hops") or self.cfg.max_hops
        election = Election(node_id, self.priority, mode=self.cfg.failover_mode)
        if lead:
            election.lead(term, self.now_ms())
        else:
            election.follow(self.now_ms())
        self.transport = ModemTransport(self.modem, self.store, game["id"], node_id, max_hops,
                                        channel, key, wifi=self._to_wifi, resuming=resuming)
        fc = FieldController(transport=self.transport, game_id=game["id"], teams=game["teams"],
                             node_id=node_id, election=election, max_hops=max_hops)
        fc.duration_ms = game["duration_ms"]
        # Node health events (decisions FU1-1 to FU1-4): node.online/node.offline and battery.low.
        fc.node_offline_ms = int(self.cfg.health_node_offline_s * 1000)
        fc.link_gap_ms = min(LINK_GAP_MS, fc.node_offline_ms)
        fc.battery_low_pct = self.cfg.health_battery_low_pct
        for node_id, role in game["assignments"].items():
            fc.register_node(int(node_id), f"node-{node_id}", role)
        fc.on_event = self._on_event
        fc.on_node = self._on_node
        fc.on_scores = self._on_scores
        fc.on_role = self._on_role
        self.fc = fc
        self.game = game
        self._key = key
        # The key's tag (not secret) outlives the key, so a GAME_OVER can still name this game
        # after a restart without the key (decision OT-13).
        self.store.set_setting(f"key_tag:{game['id']}", epoch_tag(key))
        self.scenario_names = scenarios.node_names(self, game["id"])
        # Each box's device id as its HELLOs gave it, and the node ids two devices shared (BN-18).
        self._devices: dict[int, str] = {}
        self.conflicts: dict[int, list[str]] = {}

    def _restore(self) -> None:
        game = self.store.live_game()
        if game is None:
            return
        key = self.store.game_key(game["id"])
        if key is None:
            # ADR-P2-4: the key never touches the Pi's disk unless persist_game_key is on.
            log.warning("game %d was live but its key was not kept; end it and start a new one",
                        game["id"])
            self.game = game
            self.key_lost = True
            return
        # A joined standby restarts as a follower; the GM promotes it again if needed.
        self._activate(game, key, game["term"], lead=not game.get("joined"), resuming=True)
        assert self.fc is not None
        fc = self.fc
        fc.restore_adjustments(self._adjustments(game["id"]))
        for node in self.store.nodes(game["id"]):
            # Each box's counters as last reported: merging by maximum continues from them.
            fc.merge_scores(node["node_id"], node.get("score") or {})
            known = fc.register_node(node["node_id"], node["name"], node["role"])
            known.epoch = node.get("epoch") or 0
            if node.get("device_id"):
                self._devices[node["node_id"]] = node["device_id"]
            if isinstance(node.get("battery_pct"), int):
                known.battery_pct = node["battery_pct"]
        self._restore_health(fc, game["id"])
        # The controller's own events go on from their stored seq: from 1 again, an event at the
        # same game time and of the same type as an earlier one (a second GM adjustment before
        # the start) would be dropped as a replay (decision PE24-42).
        fc._event_seq = max((e["seq"] for e in self.store.events(game["id"])
                             if e["node"] == fc.node_id and e["epoch"] is None), default=0)
        saved = self.store.get_setting(f"game_time:{game['id']}")
        fc.game_time_ms = int(saved) if saved else 0
        fc.game_state = {"running": GAME_RUNNING, "paused": GAME_PAUSED}.get(game["state"], 0)
        fc._last_tick = self.now_ms()
        # The field script's points from earlier runs, and the script itself again.
        saved_runs = self.store.get_setting(f"field_scores:{game['id']}")
        self._field_scores = json.loads(saved_runs) if saved_runs else {}
        for key, counters in self._field_scores.items():
            fc.merge_counters(key, counters)
        if fc.is_controller and fc.game_state in (GAME_RUNNING, GAME_PAUSED):
            try:
                self._start_field()
            except (ModeError, ControllerError) as exc:
                log.error("field.lua cannot run after the restart: %s", exc)
        log.info("resumed game %d (%s) at %d ms", game["id"], game["state"], fc.game_time_ms)

    def _restore_health(self, fc: FieldController, game_id: int) -> None:
        """After a restart: the health events' seq goes on from the stored ones, each box's link is
        what its last link event said (one that was online has node_offline_s from now to be
        heard again before it counts as offline) and a battery.low already logged is not repeated."""
        health = [e for t in HEALTH_EVENTS for e in self.store.events(game_id, event_type=t)]
        fc.health_seq = max((e["seq"] for e in health if e["epoch"] is None), default=0)
        now = self.now_ms()
        for node in fc.nodes.values():
            mine = [e for e in health if e["node"] == node.node_id]
            links = [e for e in mine if e["type"] != "battery.low"]
            if links:
                node.link = max(links, key=lambda e: (e["t"], e["seq"]))["type"].split(".")[1]
                node.link_changed_ms = now if node.link == "online" else None
            node.battery_low = any(e["type"] == "battery.low" for e in mine)

    def _adjustments(self, game_id: int) -> dict[str, int]:
        out: dict[str, int] = {}
        for ev in self.store.events(game_id, event_type="score.delta"):
            if ev["node"] == self.node_id and ev["team"]:
                out[ev["team"]] = out.get(ev["team"], 0) + int(ev["data"].get("amount", 0))
        return out

    def _to_wifi(self, msg_type: int, payload: bytes) -> bool:
        links = self.prop_links
        return links.forward(msg_type, payload) if links is not None else False

    def _deactivate(self) -> None:
        if self.field is not None:
            self.field.close()
            self.field = None
        self._field_scores = {}
        if self.modem is not None:
            self.modem.clear()  # the modem forgets the key
        self.fc = None
        self.transport = None
        self._key = b""
        self.game = None
        self.key_lost = False
        self.scenario_names = {}

    # --- public API (REST, MQTT, console) ------------------------------------

    def public_game(self, game: dict[str, Any]) -> dict[str, Any]:
        out = dict(game)
        live = self.game is not None and self.game["id"] == game["id"]
        out["live"] = live
        meta = self.scenario_meta(game.get("mode_id"))
        if meta is not None:
            # The staff's view: every objective, and the boxes the GM named (Join tab).
            out["scenario"] = meta.staff_view()
            names = self.scenario_names if live else scenarios.node_names(self, game["id"])
            out["scenario_nodes"] = {str(k): v for k, v in sorted(names.items())}
        if live and self.fc is not None:
            out["game_time_ms"] = self.fc.game_time_ms
            out["term"] = self.fc.term
        if live and self.key_lost:
            out["key_lost"] = True
        if live and game.get("state") == "ready" and self.fc is not None and not game.get("joined"):
            out["start_check"] = self.start_check()
        return out

    def players_game(self, game: dict[str, Any], viewer: Any = None) -> dict[str, Any]:
        """A game as players and the read token see it: without its gm_only parameters
        (decision M5-1, visibility.py), and of its scenario only the objectives this viewer may
        know (P4R24): none of the boxes' names, targets or dependencies."""
        pkg = self.modes.get(game.get("mode_id")) if isinstance(game.get("mode_id"), str) else None
        out = {**game, "params": visibility.public_params(pkg.mode if pkg else None, game.get("params"))}
        out.pop("scenario_nodes", None)
        meta = self.scenario_meta(game.get("mode_id"))
        if meta is not None:
            out["scenario"] = meta.player_view(viewer, game, scenarios.revealed(self, game["id"]))
        return out

    def scenario_meta(self, mode_id: Any) -> Optional[scenarios.Meta]:
        """The scenario a game's id leads with (its package's mode.yaml, M7-8), or None."""
        if not isinstance(mode_id, str):
            return None
        cached = self._meta_cache.get(mode_id)
        if cached is not None and cached[0] == self.modes.generation:
            return cached[1]
        meta = None
        try:
            pkg = self.modes.get(mode_id) if SEPARATOR in mode_id else None
        except ModeError:
            pkg = None
        if pkg is not None:
            meta = scenarios.Meta.parse(pkg.files.get("mode.yaml", ""))
        self._meta_cache[mode_id] = (self.modes.generation, meta)
        return meta

    def event_for(self, viewer: Any, game_id: Any, ev: dict[str, Any]) -> dict[str, Any]:
        """An event as this viewer may see it (visibility.scenario_event: gm_only data for staff,
        and a scenario objective's id for the players it is for)."""
        if visibility.is_staff(viewer, game_id if isinstance(game_id, int) else None):
            return ev
        if ev.get("type") not in visibility.OBJECTIVE_EVENTS or not isinstance(game_id, int):
            return visibility.public_event(ev)
        game = self.game if self.game is not None and self.game["id"] == game_id else self.store.game(game_id)
        meta = self.scenario_meta(game.get("mode_id")) if game is not None else None
        return visibility.scenario_event(viewer, ev, game, meta.objectives if meta else None)

    def list_games(self) -> list[dict[str, Any]]:
        return [self.public_game(g) for g in self.store.games()]

    def get_game(self, game_id: int) -> dict[str, Any]:
        game = self.store.game(game_id)
        if game is None:
            raise NotFound(f"no game {game_id}")
        return self.public_game(game)

    def create_game(self, spec: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if self.game is not None:
                raise Conflict(f"game {self.game['id']} is still live; end it first")
            if self.scan is not None and self.scan.running:
                raise Conflict("a channel scan is running; wait for it or cancel it first")
            name = spec.get("name", "")
            if not isinstance(name, str) or not 1 <= len(name) <= 64:
                raise ControllerError("name: 1 to 64 characters")
            preset = None
            if spec.get("preset_id") is not None:
                preset = self.store.preset(_int(spec["preset_id"], "preset_id"))
                if preset is None:
                    raise NotFound(f"no preset {spec['preset_id']}")
            mode_id = spec.get("mode_id") or (preset["mode_id"] if preset else None)
            modifiers = spec.get("modifiers") or []
            if not isinstance(modifiers, list) or not all(isinstance(m, str) for m in modifiers):
                raise ControllerError("modifiers: a list of modifier ids")
            if modifiers and isinstance(mode_id, str):
                mode_id = SEPARATOR.join([mode_id, *modifiers])
            pkg = self.modes.get(mode_id) if isinstance(mode_id, str) else None
            if pkg is None:
                raise ControllerError(f"unknown mode {mode_id!r}")
            if len(pkg.id.encode()) > joinfmt.MODE_MAX:
                # A standby controller's join carries the whole id (decisions M6-1, M7-1).
                raise ControllerError(f"the game's id {pkg.id} is {len(pkg.id.encode())} bytes; a join carries "
                                      f"at most {joinfmt.MODE_MAX}: drop a part, or give the scenario a shorter id")
            teams = spec.get("teams", ["red", "blue"])
            if (not isinstance(teams, list) or not 1 <= len(teams) <= 8
                    or not all(isinstance(t, str) and 0 < len(t.encode()) <= TEAM_NAME_MAX for t in teams)
                    or len(set(teams)) != len(teams)):
                raise ControllerError(f"teams: 1 to 8 different names of 1 to {TEAM_NAME_MAX} bytes")
            overrides = dict(preset["params"]) if preset else {}
            if spec.get("params") is not None:
                if not isinstance(spec["params"], dict):
                    raise ControllerError("params must be a map")
                overrides.update(spec["params"])
            try:
                params = resolve_params(pkg.mode, overrides, teams)
            except ModeError as exc:
                raise ControllerError(str(exc)) from None
            duration = _int(spec.get("duration_ms", 0), "duration_ms")
            if not 0 <= duration <= 0xFFFFFFFF:
                raise ControllerError("duration_ms: 0 (no limit) to 4294967295")
            assignments = spec.get("assignments", {})
            if not isinstance(assignments, dict):
                raise ControllerError("assignments: a map of node id to role")
            clean: dict[str, str] = {}
            for node_id, role in assignments.items():
                nid = _int(node_id, "assignments node id")
                if not 1 <= nid <= 0xFFFE or nid == self.cfg.node_id:
                    raise ControllerError(f"node id {nid}: 1-65534, not the controller's")
                if role not in pkg.mode.roles:
                    raise ControllerError(f"role {role!r} is not one of {sorted(pkg.mode.roles)}")
                clean[str(nid)] = role
            if pkg.field_script is not None and self.core is None:
                raise Unavailable("this mode has a field.lua and the core library is not loaded")
            # Squads are sub-groups inside each team, only in games that have them (milsims,
            # big games): 0, the default, is a game with teams only (decision PE25).
            squads = _int(spec.get("squads", 0), "squads")
            if not 0 <= squads <= SQUADS_MAX:
                raise ControllerError(f"squads: 0 (none) to {SQUADS_MAX} per team")
            # Team branding (decisions BR12-BR15): display names and crests next to the colours,
            # which stay the team names the boxes and the radio know.
            raw_info = spec.get("team_info") or {}
            if not isinstance(raw_info, dict):
                raise ControllerError("team_info: an object {team: {display_name, crest_id, team_preset_id}}")
            team_info = {}
            for team, entry in raw_info.items():
                if team not in teams:
                    raise ControllerError(f"team_info: {team!r} is not one of the game's teams {teams}")
                team_info[team] = self._team_entry(team, entry, {})
            team_info = {k: v for k, v in team_info.items() if v}

            # The language of the boxes' screens (join key 15, RFC 0001 Amendment 10): the field's
            # setting, or with "auto" the language of the console the GM created the game in.
            box_lang = self._box_lang_for(spec.get("console_lang"))

            used = self.store.game_ids()
            game_id = random.SystemRandom().choice([g for g in range(1, 0xFFFF) if g not in used][:4096])
            key = os.urandom(16)  # ADR-P2-2: a fresh AES-128 key per game
            game = {
                "id": game_id, "name": name, "mode_id": pkg.id,
                "preset_id": preset["id"] if preset else None, "teams": teams, "params": params,
                "assignments": clean, "duration_ms": duration,
                "game_seed": random.SystemRandom().randrange(1, 0xFFFFFFFF),
                "state": "ready", "term": 1, "created_at": time.time(),
                "node_id": self.cfg.node_id, "channel_hz": self.field_channel,
                "max_hops": self.cfg.max_hops, "joined": False, "squads": squads,
                "team_info": team_info,
            }
            self.store.create_game(game, key if self.cfg.persist_game_key else None)
            if box_lang is not None:
                self.store.set_setting(f"box_lang:{game_id}", box_lang)
            self._activate(self.store.game(game_id) or game, key, 1)
            out = self.get_game(game_id)
            self._emit({"type": "game", "game": out})
            return out

    # --- team branding (decisions BR12-BR15) --------------------------------------

    def _team_entry(self, team: str, spec: Any, current: dict[str, Any]) -> dict[str, Any]:
        """A team's display name and crest from a request: a team preset's, then the request's own
        fields on top (null removes one); the colour is the team's name and never changes here."""
        if not isinstance(spec, dict):
            raise ControllerError(f"team_info.{team}: an object with display_name, crest_id or team_preset_id")
        unknown = set(spec) - {"display_name", "crest_id", "team_preset_id"}
        if unknown:
            raise ControllerError(f"team_info.{team}: unknown fields {sorted(unknown)}")
        out = dict(current)
        if spec.get("team_preset_id") is not None:
            preset = self.store.team_preset(_int(spec["team_preset_id"], "team_preset_id"))
            if preset is None:
                raise NotFound(f"no team preset {spec['team_preset_id']}")
            out["display_name"] = preset["name"]
            out["crest_id"] = preset["crest_id"]
            out["team_preset_id"] = preset["id"]
        if "display_name" in spec:
            out["display_name"] = display_name(spec["display_name"], f"team_info.{team}.display_name")
        if "crest_id" in spec:
            crest = spec["crest_id"]
            if crest is not None and (not isinstance(crest, str) or not CREST_ID_RE.fullmatch(crest)
                                      or self.store.image(crest, with_data=False) is None):
                raise ControllerError(f"team_info.{team}.crest_id: an uploaded crest's id (POST /api/v1/crests)")
            out["crest_id"] = crest
        if "display_name" in spec or "crest_id" in spec:
            out.pop("team_preset_id", None)  # changed by hand: no longer the preset's
        return {k: v for k, v in out.items() if v is not None}

    def set_team_info(self, game_id: int, team: str, spec: Any) -> dict[str, Any]:
        """PUT /api/v1/games/{id}/teams/{team}: change a team's display name or crest until the game ends."""
        with self._lock:
            game = self.store.game(game_id)
            if game is None:
                raise NotFound(f"no game {game_id}")
            if game["state"] == "ended":
                raise Conflict(f"game {game_id} has ended")
            if team not in game["teams"]:
                raise NotFound(f"game {game_id} has no team {team!r}")
            info = dict(game.get("team_info") or {})
            entry = self._team_entry(team, spec, info.get(team, {}))
            if entry:
                info[team] = entry
            else:
                info.pop(team, None)
            self.store.update_game(game_id, team_info=info)
            if self.game is not None and self.game["id"] == game_id:
                self.game["team_info"] = info
            out = self.get_game(game_id)
        self._emit({"type": "game", "game": out})
        return out

    # --- the field's radio channel (channels.py, RFC 0001 Amendment 3) ---------

    @property
    def field_channel(self) -> int:
        """The channel new games use: the GM's choice, else radio.channel_hz from the config."""
        stored = self.store.get_setting("radio.channel_hz")
        return int(stored) if stored is not None else self.cfg.channel_hz

    def _channel_lock_reason(self) -> Optional[str]:
        if self.game is not None:
            return f"game {self.game['id']} is live ({self.game['state']}); end it first"
        if self.scan is not None and self.scan.running:
            return "a channel scan is running"
        return None

    SCAN_UNAVAILABLE = {
        "no_modem": ("no USB radio modem is configured (modem.port is empty), so the noise cannot "
                     "be measured; the field keeps its channel"),
        "modem_down": "the USB radio modem is not connected; the scan needs it",
        "no_radio": "the USB radio modem has no radio chip, so the noise cannot be measured",
        "old_firmware": "the USB radio modem's firmware cannot measure noise (update it)",
    }

    def _scan_unavailable(self) -> Optional[str]:
        """Why a scan cannot run now (a key of SCAN_UNAVAILABLE), or None."""
        if self.modem is None:
            return "no_modem"
        if self.modem.state != radio_modem.UP:
            return "modem_down"
        ident = self.modem.ident or {}
        if ident.get("radio") != "sx1262":
            return "no_radio"
        if not self.modem.can_measure:
            return "old_firmware"
        return None

    # --- the boxes' language (join key 15, RFC 0001 Amendment 10) ----------------

    def box_language(self) -> dict[str, Any]:
        """The field setting (GET /api/v1/settings/box-language): "auto" (the default: the
        language of the console that creates the game), "pt" or "en"; and the live game's."""
        with self._lock:
            live = self.store.get_setting(f"box_lang:{self.game['id']}") if self.game is not None else None
            return {"box_language": self.store.get_setting("box_language") or "auto",
                    "choices": list(BOX_LANGUAGES), "game_box_language": live or ("en" if self.game else None)}

    def set_box_language(self, value: Any) -> dict[str, Any]:
        """The GM's choice; games created from now on use it (a live game keeps its own)."""
        if value not in BOX_LANGUAGES:
            raise ControllerError(f"box_language: one of {', '.join(BOX_LANGUAGES)}")
        with self._lock:
            self.store.set_setting("box_language", value)
        return self.box_language()

    def _box_lang_for(self, console_lang: Any) -> Optional[str]:
        """A new game's box language: the setting, or with "auto" the console's ("pt", "en");
        None (English, the join without key 15) when neither says."""
        setting = self.store.get_setting("box_language") or "auto"
        if setting != "auto":
            return setting
        if console_lang is None:
            return None
        if console_lang not in BOX_LANGUAGES or console_lang == "auto":
            raise ControllerError("console_lang: pt or en")
        return console_lang

    def radio_settings(self) -> dict[str, Any]:
        """The field channel, its limits, the candidates and the last scan (GET /api/v1/radio)."""
        with self._lock:
            hz = self.field_channel
            scan = self.scan.public() if self.scan is not None else self._last_scan
            return {
                "channel": eu868.describe(hz),
                "source": self.store.get_setting("radio.channel_source") or "default",
                "confirmed": self.store.get_setting("radio.channel_confirmed") == "1",
                "set_at": float(self.store.get_setting("radio.channel_set_at") or 0) or None,
                "default": eu868.describe(self.cfg.channel_hz),
                "recommended_hz": eu868.DEFAULT_CHANNEL_HZ,
                "candidates": channels.candidates(),
                "locked": self._channel_lock_reason(),
                "scan_unavailable": self._scan_unavailable(),
                "scan_dwell_s": self.cfg.scan_dwell_s,
                "quiet_threshold_dbm": self.cfg.quiet_threshold_dbm,
                "scan": scan,
                "game_channel_hz": (self.game.get("channel_hz") if self.game is not None else None),
            }

    def set_field_channel(self, channel_hz: Any, source: Any = "manual") -> dict[str, Any]:
        """The GM's choice for the field (accepting the default counts): stored, sent to the modem."""
        with self._lock:
            reason = self._channel_lock_reason()
            if reason:
                raise Conflict(f"the channel cannot change now: {reason}")
            hz = _int(channel_hz, "channel_hz")
            if not eu868.channel_ok(hz):
                raise ControllerError(
                    f"channel_hz {hz}: the 125 kHz channel (centre +-62.5 kHz) must fit inside "
                    "one EU868 sub-band")
            if source not in channels.SOURCES:
                raise ControllerError(f"source: one of {', '.join(channels.SOURCES)}")
            self.store.set_setting("radio.channel_hz", str(hz))
            self.store.set_setting("radio.channel_source", source)
            self.store.set_setting("radio.channel_confirmed", "1")
            self.store.set_setting("radio.channel_set_at", str(time.time()))
            if self.modem is not None and self.modem.is_up:
                self.modem.set_channel(hz)
                self._modem_moved("the field's channel changed")
            log.info("field channel set to %d Hz (%s)", hz, source)
        out = self.radio_settings()
        self._emit({"type": "radio", "radio": out})
        return out

    def random_channel(self) -> dict[str, Any]:
        """A random legal channel as a suggestion; nothing changes until the GM accepts it."""
        return channels.random_choice()

    def start_scan(self, dwell_s: Any = None) -> dict[str, Any]:
        """Starts the noise scan of the candidates ("find a quiet channel")."""
        with self._lock:
            reason = self._channel_lock_reason()
            if reason:
                raise Conflict(f"no scan now: {reason}")
            unavailable = self._scan_unavailable()
            if unavailable:
                raise Unavailable(self.SCAN_UNAVAILABLE[unavailable])
            total = self.cfg.scan_dwell_s
            if dwell_s is not None:
                if isinstance(dwell_s, bool) or not isinstance(dwell_s, (int, float)) \
                        or not 1 <= dwell_s <= 600:
                    raise ControllerError("dwell_s: 1 to 600 seconds")
                total = float(dwell_s)
            assert self.modem is not None
            modem = self.modem
            self.scan = channels.Scan(lambda hz, ms: modem.measure(hz, ms), total,
                                      self.cfg.quiet_threshold_dbm, self._on_scan)
            self._modem_moved("a channel scan started")
            self.scan.start()
            return self.scan.public()

    def cancel_scan(self) -> dict[str, Any]:
        with self._lock:
            if self.scan is None or not self.scan.running:
                raise Conflict("no channel scan is running")
            scan = self.scan
        scan.cancel()
        return scan.public()

    def scan_status(self) -> Optional[dict[str, Any]]:
        with self._lock:
            return self.scan.public() if self.scan is not None else self._last_scan

    def _on_scan(self, state: dict[str, Any]) -> None:
        if state["state"] != "running":
            self._last_scan = state
            self.store.set_setting("radio.last_scan", json.dumps(state))
            if self.modem is not None and self.modem.is_up:
                self.modem.set_channel(self.field_channel)  # back on the field's channel
                self._modem_moved("a channel scan ended")
        self._emit({"type": "radio_scan", "scan": state})

    def game_key(self, game_id: int) -> bytes:
        """The live game's key. Only ever leaves the controller inside a join payload."""
        with self._lock:
            if self.game is None or self.game["id"] != game_id or self.key_lost:
                raise Conflict("no key: the game is not live on this controller")
            return self._key

    # --- join flow (ADR-P2-12, protocol/join.md) -------------------------------

    def _issued_ids(self) -> set[int]:
        """The node ids a join was issued for in the live game (kept across restarts)."""
        assert self.game is not None
        saved = self.store.get_setting(f"issued_nodes:{self.game['id']}")
        return set(json.loads(saved)) if saved else set()

    def _used_ids(self) -> set[int]:
        assert self.game is not None
        used = {self.node_id, self.cfg.node_id, 0xFFFF}
        used.update(int(n) for n in self.game["assignments"])
        used.update(self._issued_ids())  # a standby controller's id too (BN-18)
        if self.fc is not None:
            used.update(self.fc.nodes)
        if self.game.get("controller_id") is not None:
            used.add(int(self.game["controller_id"]))
        return used

    def issue_join(self, spec: dict[str, Any], node_id: Optional[int] = None,
                   same_device: bool = False, device: Optional[str] = None,
                   tier: Optional[int] = None) -> dict[str, Any]:
        """A join payload for a box (kind "node") or a standby controller (kind "controller").

        The node id is the given one or the lowest free id; a box's role is
        recorded in the game's assignments. The answer holds the game key (in
        the payload), so only the GM token may ask for it.

        A node id a join was already issued for, or a box was heard on, in this game is never
        issued again (decision BN-18): two devices on one (game key, node id) would use the same
        nonces. A replacement box gets a new node id. same_device: the box that has it, invited
        again (reinvite.py), whose epochs go on above its own.

        ``fetch_modes`` (join key 16) asks the box to fetch the parts of its mode it lacks from
        this controller, ``forget_modes`` (key 17) to forget those it fetched before (phase 5
        plan phase 13, mode_fetch.py); device and tier: the invited box's, when known.
        """
        with self._lock:
            if self.game is None:
                raise Conflict("no live game: create a game first")
            fc = self._live(self.game["id"])
            if not self.join_key:
                raise Unavailable("no join key configured")
            kind = spec.get("kind", "node")
            if kind not in joinfmt.KINDS:
                raise ControllerError(f"kind: one of {', '.join(sorted(joinfmt.KINDS))}")
            fetch, forget = spec.get("fetch_modes", False), spec.get("forget_modes", False)
            if not isinstance(fetch, bool) or not isinstance(forget, bool):
                raise ControllerError("fetch_modes and forget_modes: true or false")
            if (fetch or forget) and kind != "node":
                raise ControllerError("fetch_modes and forget_modes are for boxes")
            if (fetch or forget) and self.mode_fetch is None:
                raise Unavailable("sending modes to boxes is not set up on this controller")
            # A scenario's box: the name the GM gives it (P4R8, M6-7), whose role is the scenario's.
            scenario_name = spec.get("name")
            if scenario_name is not None:
                meta = self.scenario_meta(self.game["mode_id"])
                boxes = meta.box_nodes() if meta is not None else {}
                if kind != "node" or meta is None:
                    raise ControllerError("name: only a box of a scenario's game takes a scenario node's name")
                if not isinstance(scenario_name, str) or scenario_name not in boxes:
                    raise ControllerError(f"name: one of the scenario's boxes {sorted(boxes)}")
                if spec.get("role") is not None and spec["role"] != boxes[scenario_name]:
                    raise ControllerError(f"{scenario_name} is a {boxes[scenario_name]} in the scenario, "
                                          f"not a {spec['role']}")
                spec = {**spec, "role": boxes[scenario_name]}
            pkg = self.modes.get(self.game["mode_id"])
            if kind == "node":
                role = spec.get("role")
                roles = sorted(pkg.mode.roles) if pkg is not None else []
                if role is None and len(roles) == 1:
                    role = roles[0]
                if role not in roles:
                    raise ControllerError(f"role: one of {roles}")
            else:
                role = "controller"
            if node_id is None and spec.get("node_id") is not None:
                node_id = _int(spec["node_id"], "node_id")
            if node_id is None:
                used = self._used_ids()
                node_id = next(i for i in range(1, 0xFFFF) if i not in used)
            node_id = _int(node_id, "node id")
            if not 1 <= node_id <= 0xFFFE or node_id == self.node_id:
                raise ControllerError(f"node id {node_id}: 1-65534, not the controller's")
            assigned = self.game["assignments"].get(str(node_id))
            if kind == "controller" and (assigned is not None or node_id in fc.nodes):
                raise Conflict(f"node id {node_id} is a box in this game")
            issued = self._issued_ids()
            known = fc.nodes.get(node_id)
            if not same_device and (node_id in issued or (known is not None and known.heard)):
                raise Conflict(f"node id {node_id} already has a box in this game: two boxes on one "
                               "node id would reuse each other's radio nonces. A replacement box "
                               "gets a new node id (Join).")
            # A box's join names what it runs, with that part's parameters: for a role of a
            # role package (the Medic Kit's medic), the package alone; else the main mode and
            # its modifiers (modes/README.md, protocol/join.md). A standby controller gets
            # the whole game, as it runs every part's field.lua.
            mode_id, params = self.game["mode_id"], self.game["params"]
            if kind == "node" and pkg is not None:
                mode_id, params = pkg.mode.node_mode_id(role), pkg.mode.params_for(role, params or {})
            if fetch:
                why = self.mode_fetch.refusal(mode_id, tier)
                if why:
                    raise Conflict(why)
            join = {
                "game_id": self.game["id"], "game_key": self._key, "node_id": node_id,
                "controller_id": self.node_id,
                "channel_hz": self.game.get("channel_hz") or self.cfg.channel_hz,
                "max_hops": self.game.get("max_hops") or self.cfg.max_hops,
                "teams": list(self.game["teams"]), "mode_id": mode_id, "role": role,
                "game_seed": int(self.game["game_seed"]) & 0xFFFFFFFF,
                "params": params or None, "kind": kind,
                "lang": self.store.get_setting(f"box_lang:{self.game['id']}"),
                "fetch_modes": fetch, "forget_modes": forget,
            }
            # Android props link over Wi-Fi with the field CA and the controller's addresses
            # (keys 13 and 14, RFC 0001 Amendment 4, proposed); boxes use them for firmware
            # updates (protocol/firmware-update.md). A payload too long with them is made
            # without them (the prop then asks for the address; a box cannot be updated).
            link = {}
            if kind == "node" and self.ca_sha256 is not None:
                link = {"ca_sha256": self.ca_sha256, "urls": list(self.link_urls[:3]) or None}
            try:
                try:
                    payload = joinfmt.encode({**join, **link}, self.join_key)
                except joinfmt.JoinError as exc:
                    if not link or exc.reason != "length":
                        raise
                    if fetch:  # a box fetches over that link: without it the join is no use
                        raise Conflict("this game's join with the field CA and the controller's addresses "
                                       "is too long: the box could not fetch its modes") from None
                    link = {}
                    payload = joinfmt.encode(join, self.join_key)
            except joinfmt.JoinError as exc:
                raise Conflict(f"this game does not fit in a join payload: {exc}") from None
            if node_id not in issued:
                self.store.set_setting(f"issued_nodes:{self.game['id']}",
                                       json.dumps(sorted(issued | {node_id})))
            if kind == "node" and assigned != role:
                self.game["assignments"][str(node_id)] = role
                self.store.update_game(self.game["id"], assignments=self.game["assignments"])
                fc.register_node(node_id, f"node-{node_id}", role)
            if scenario_name is not None:
                self.scenario_names = scenarios.name_node(self, self.game["id"], node_id, scenario_name)
            out = {
                "game": self.game["id"], "node_id": node_id, "kind": kind, "role": role, "name": scenario_name,
                "controller_id": self.node_id, "channel_hz": join["channel_hz"],
                "max_hops": join["max_hops"], "bytes": len(payload),
                "text": joinfmt.to_text(payload), "payload_hex": payload.hex(),
                "ndef_tag_hex": joinfmt.to_ndef_tag(payload).hex(),
                "wifi_link": bool(link),
            }
            if fetch or forget:
                out.update(fetch_modes=fetch, forget_modes=forget)
                self.mode_fetch.track(self.game["id"], node_id, role, mode_id, device, fetch, forget)
            self._emit({"type": "join", "game": self.game["id"], "node_id": node_id, "kind": kind,
                        "role": role, "name": scenario_name})
            return out

    def join_as_standby(self, text: Any) -> dict[str, Any]:
        """Takes a game as a standby controller from a join text (kind "controller").

        The game is stored and put on the radio with the payload's key, node
        id and channel; this controller follows the TIME beacons until the
        GM promotes it (ADR-P2-8). Answers with the game.
        """
        with self._lock:
            if self.game is not None:
                raise Conflict(f"game {self.game['id']} is still live here; end it first")
            if not self.join_key:
                raise Unavailable("no join key configured")
            if not isinstance(text, str):
                raise ControllerError("text: the join text (atalaia:join:...)")
            try:
                j = joinfmt.decode(joinfmt.from_text(text), self.join_key)
            except joinfmt.JoinError as exc:
                raise ControllerError(f"join payload refused ({exc.reason}): {exc}") from None
            if j["kind"] != "controller":
                raise ControllerError("this join payload is for a box, not a standby controller")
            try:
                pkg = self.modes.get(j["mode_id"])
            except ModeError as exc:
                raise Conflict(f"mode {j['mode_id']}: {exc}") from None
            if pkg is None:
                # A scenario is an upload (P4R7): the standby needs it too (decision M6-1, M8-3).
                missing = [m for m in j["mode_id"].split(SEPARATOR) if not any(p.id == m for p in self.modes.all())]
                raise Conflict(f"mode {j['mode_id']} is not installed on this controller (missing: "
                               f"{', '.join(missing)}); install a scenario here first, with the same manifest "
                               "(the leading controller's GET /api/v1/scenarios/{id} gives it)")
            if pkg.field_script is not None and self.core is None:
                raise Unavailable("this mode has a field.lua and the core library is not loaded")
            existing = self.store.game(j["game_id"])
            if existing is not None:
                raise Conflict(f"this controller already has a game {j['game_id']} "
                               f"({existing['state']})")
            try:
                params = resolve_params(pkg.mode, j["params"] or {}, j["teams"])
            except ModeError as exc:
                raise ControllerError(str(exc)) from None
            game = {
                "id": j["game_id"], "name": f"Game {j['game_id']} (standby)", "mode_id": pkg.id,
                "preset_id": None, "teams": j["teams"], "params": params, "assignments": {},
                "duration_ms": 0, "game_seed": j["game_seed"], "state": "ready", "term": 0,
                "created_at": time.time(), "node_id": j["node_id"], "channel_hz": j["channel_hz"],
                "max_hops": j["max_hops"], "joined": True, "controller_id": j["controller_id"],
            }
            key = j["game_key"]
            self.store.create_game(game, key if self.cfg.persist_game_key else None)
            if j.get("lang"):  # promoted, it issues joins in the same language
                self.store.set_setting(f"box_lang:{j['game_id']}", j["lang"])
            self._activate(self.store.game(j["game_id"]) or game, key, 0, lead=False)
            out = self.get_game(j["game_id"])
            self._emit({"type": "game", "game": out})
            return out

    def _live(self, game_id: int) -> FieldController:
        game = self.store.game(game_id)
        if game is None:
            raise NotFound(f"no game {game_id}")
        if self.game is None or self.game["id"] != game_id:
            raise Conflict(f"game {game_id} is {game['state']}, not live")
        if self.key_lost or self.fc is None:
            raise Conflict("this game's key was lost when the controller restarted; end it")
        if not self.fc.is_controller:
            raise Conflict(f"this controller is on standby (term {self.fc.term}); promote it first")
        return self.fc

    def _set_state(self, game_id: int, state: str, **times: float) -> dict[str, Any]:
        self.store.update_game(game_id, state=state, **times)
        if self.game is not None and self.game["id"] == game_id:
            self.game["state"] = state
        out = self.get_game(game_id)
        self._emit({"type": "game", "game": out})
        return out

    # --- the start guard (decisions RJ-1 to RJ-3) -----------------------------------

    def _joined_nodes(self) -> list[tuple[int, str]]:
        """The live game's nodes that have joined: heard (HELLO first), or stored as heard before
        a restart; boxes and Android props alike. (node id, role)."""
        assert self.game is not None
        out: dict[int, str] = {n["node_id"]: n["role"] for n in self.store.nodes(self.game["id"])}
        if self.fc is not None:
            for node in self.fc.nodes.values():
                if node.heard or node.hello:
                    out[node.node_id] = node.role
        if self.mode_fetch is not None:
            # A box still fetching the game's modes (or whose fetch failed) has not joined until
            # its HELLO, even if a node.modes_failed of it was heard (mode_fetch.py).
            out = {n: r for n, r in out.items() if not self.mode_fetch.holds(n)}
        return sorted(out.items())

    def _needed_roles(self) -> list[str]:
        """The roles that must each have a joined node before the game starts.

        A scenario's game: the roles of the boxes its manifest names (its ``nodes``); without
        any, as for every other game: every role of the game's mode and role packages (each has
        ``requires:`` capabilities), unless its manifest says ``needed: false``. A modifier
        brings no role (modes/README.md)."""
        assert self.game is not None
        meta = self.scenario_meta(self.game.get("mode_id"))
        if meta is not None:
            boxes = sorted(set(meta.box_nodes().values()))
            if boxes:
                return boxes
        try:
            pkg = self.modes.get(self.game["mode_id"])
        except ModeError:
            pkg = None
        if pkg is None:
            return []
        return sorted(r for r, spec in pkg.mode.roles.items()
                      if not (isinstance(spec, dict) and spec.get("needed") is False))

    def start_check(self) -> dict[str, Any]:
        """What Start would say now: the needed roles, how many nodes of each have joined, the
        missing ones (Start refuses unless forced) and the mode's minimums not met (warnings)."""
        with self._lock:
            if self.game is None:
                raise Conflict("no live game")
            needed = self._needed_roles()
            joined: Counter[str] = Counter(role for _, role in self._joined_nodes())
            missing = [r for r in needed if joined[r] == 0]
            warnings = []
            params = self.game.get("params") or {}
            roles = set(needed) | set(joined)
            for name, value in params.items():
                if not isinstance(value, int) or isinstance(value, bool):
                    continue
                for prefix in ("min_", "last_"):
                    role = name[len(prefix):-1] if name.startswith(prefix) and name.endswith("s") else None
                    if role not in roles:
                        continue
                    have = joined[role]
                    if prefix == "min_" and have < value:
                        warnings.append({"code": "min", "param": name, "role": role, "value": value, "have": have,
                                         "text": f"{have} {role} node(s) joined; {name} is {value}"})
                    elif prefix == "last_" and 0 < have <= value:
                        warnings.append({"code": "last", "param": name, "role": role, "value": value,
                                         "have": have,
                                         "text": f"only {have} {role} node(s) joined and {name} is {value}: "
                                                 "the countdown can run from the start"})
            return {"needed": needed, "joined": dict(sorted(joined.items())), "missing": missing,
                    "warnings": warnings, "ok": not missing}

    def start_game(self, game_id: int, force: bool = False) -> dict[str, Any]:
        with self._lock:
            fc = self._live(game_id)
            assert self.game is not None
            if self.game["state"] != "ready":
                raise Conflict(f"game {game_id} is {self.game['state']}; only a ready game starts")
            for guard in [self.start_guard, *self.start_guards]:
                reason = guard() if guard is not None else None
                if reason:
                    raise Conflict(reason)
            check = self.start_check()
            if check["missing"] and not force:
                raise StartBlocked("no box or prop has joined for: " + ", ".join(check["missing"])
                                   + "; join them, or start anyway (force)", check)
            if check["missing"]:
                # The GM's override, after the console's confirmation: logged and told.
                log.warning("game %d started anyway (forced) without nodes for: %s", game_id,
                            ", ".join(check["missing"]))
                self._emit({"type": "system", "kind": "start.forced", "game": game_id,
                            "missing": check["missing"]})
            fc.start_game(duration_ms=self.game["duration_ms"], now_ms=self.now_ms())
            preset = self.store.preset(self.game["preset_id"]) if self.game.get("preset_id") else None
            fc.controller_event("game.start", {"preset": preset["name"] if preset else self.game["mode_id"]},
                                prio="critical")
            try:
                self._start_field()
            except ModeError as exc:
                raise ControllerError(str(exc)) from None
            out = self._set_state(game_id, "running", started_at=time.time())
            self._after_field()
            self._save_game_time(force=True)
            return out

    def pause_game(self, game_id: int, reason: str = "") -> dict[str, Any]:
        with self._lock:
            fc = self._live(game_id)
            if self.game is None or self.game["state"] != "running":
                raise Conflict("only a running game pauses")
            fc.pause_game(now_ms=self.now_ms(), reason=reason or None)
            fc.controller_event("game.pause", {"reason": reason} if reason else {}, prio="critical")
            if self.field is not None:
                self.field.input("game.pause", {"reason": reason} if reason else None)
            self._save_game_time(force=True)
            return self._set_state(game_id, "paused")

    def resume_game(self, game_id: int) -> dict[str, Any]:
        with self._lock:
            fc = self._live(game_id)
            if self.game is None or self.game["state"] != "paused":
                raise Conflict("only a paused game resumes")
            fc.resume_game(now_ms=self.now_ms())
            fc.controller_event("game.resume", {}, prio="critical")
            if self.field is not None:
                self.field.input("game.resume")
            return self._set_state(game_id, "running")

    def end_game(self, game_id: int, reason: str = "", winner: Optional[str] = None) -> dict[str, Any]:
        with self._lock:
            game = self.store.game(game_id)
            if game is None:
                raise NotFound(f"no game {game_id}")
            if self.game is None or self.game["id"] != game_id:
                raise Conflict(f"game {game_id} is {game['state']}, not live")
            if self.fc is not None and not self.fc.is_controller and self.game.get("joined"):
                return self._leave_standby(game_id, reason or "left")
            if not self.key_lost:
                fc = self._live(game_id)
                fc.end_game(now_ms=self.now_ms(), reason=reason or None)
                data = {"reason": reason} if reason else {}
                if winner not in fc.teams:
                    winner = _winner(fc.total_scores, fc.teams)
                if winner:
                    data["winner"] = winner
                fc.controller_event("game.end", data, prio="critical")
                if self.field is not None:
                    self.field.input("game.end", {"reason": reason} if reason else None)
                self.store.save_scores(game_id, fc.total_scores)
                self._save_game_time(force=True)
            self.store.update_game(game_id, game_key=None)  # the key does not outlive the game
            if self.positions is not None:
                self.positions.end_game(game_id)  # ADR-P3-6: positions last as long as the game
            tag = epoch_tag(self._key) if self._key else self.store.get_setting(f"key_tag:{game_id}")
            key_lost = self.key_lost
            out = self._set_state(game_id, "ended", ended_at=time.time())
            self._deactivate()
            if self.reinvite is not None:
                self.reinvite.forget_game(game_id)  # no invite into a game that is over
            told = self._tell_game_over(game, tag, key_lost)
            result = self.public_game(self.store.game(game_id) or out)
            result["game_over_frame"] = told
            return result

    def _tell_game_over(self, game: dict[str, Any], tag: Optional[str], key_lost: bool) -> str:
        """GAME_OVER to the game's boxes over the field radio (decisions OT-7, OT-13): "sent",
        "no_tag" (a game this controller made before it kept key tags), "no_join_key" or
        "no_radio". Always after a game this controller ran ends, besides its CMD end; the only
        way to its boxes when the controller restarted without the game's key."""
        self.store.delete_setting(f"key_tag:{game['id']}")
        if game.get("joined"):
            return "standby"  # a standby's game may still run on its primary: never ended from here
        if tag is None:
            told = "no_tag"
        elif self.reinvite is None:
            told = "no_join_key"
        elif self.reinvite.game_over(game["id"], bytes.fromhex(tag), game.get("channel_hz") or self.cfg.channel_hz):
            told = "sent"
        else:
            told = "no_radio"
        if key_lost:
            log.warning("game %d ended without its key: its boxes told over the field radio: %s", game["id"], told)
        return told

    def _leave_standby(self, game_id: int, reason: str) -> dict[str, Any]:
        """A standby controller stops following a game (the GM left it, or it ended)."""
        if self.fc is not None:
            self.store.save_scores(game_id, self.fc.total_scores)
            self._save_game_time(force=True)
        self.store.update_game(game_id, game_key=None)
        self.store.delete_setting(f"key_tag:{game_id}")
        log.info("standby: left game %d (%s)", game_id, reason)
        out = self._set_state(game_id, "ended", ended_at=time.time())
        self._deactivate()
        return self.public_game(self.store.game(game_id) or out)

    def score(self, game_id: int) -> dict[str, Any]:
        with self._lock:
            game = self.store.game(game_id)
            if game is None:
                raise NotFound(f"no game {game_id}")
            if self.fc is not None and self.game is not None and self.game["id"] == game_id:
                teams = self.fc.total_scores
            else:
                teams = self.store.scores(game_id)
            return {"game": game_id, "teams": {t: int(teams.get(t, 0)) for t in game["teams"]}}

    def adjust_score(self, game_id: int, team: str, amount: int, reason: str) -> dict[str, Any]:
        with self._lock:
            fc = self._live(game_id)
            if team not in fc.teams:
                raise ControllerError(f"team {team!r} is not one of {fc.teams}")
            amount = _int(amount, "amount")
            if amount == 0 or abs(amount) > 1_000_000:
                raise ControllerError("amount: a non-zero integer up to 1000000")
            if not isinstance(reason, str) or len(reason) > 64:
                raise ControllerError("reason: text up to 64 characters")
            event = fc.adjust_score(team, amount, reason, now_ms=self.now_ms())
            return {"score": self.score(game_id), "event": _public_event(event)}

    def log(self, game_id: int, since_ms: Optional[int] = None) -> list[dict[str, Any]]:
        if self.store.game(game_id) is None:
            raise NotFound(f"no game {game_id}")
        return self.store.events(game_id, since_ms=since_ms)

    def nodes(self, game_id: Optional[int] = None) -> list[dict[str, Any]]:
        with self._lock:
            if game_id is None and self.game is not None:
                game_id = self.game["id"]
            if game_id is None:
                return []
            if self.store.game(game_id) is None:
                raise NotFound(f"no game {game_id}")
            stored = {n["node_id"]: n for n in self.store.nodes(game_id)}
            if self.fc is not None and self.game is not None and self.game["id"] == game_id:
                now = self.now_ms()
                for node in self.fc.nodes.values():
                    stored[node.node_id] = {**stored.get(node.node_id, {}), **self._node_info(node),
                                            "seen_ms_ago": now - node.last_seen_ms if node.last_seen_ms else None}
            return [stored[k] for k in sorted(stored)]

    def _node_info(self, node: FieldNode) -> dict[str, Any]:
        assert self.fc is not None
        hello = node.hello
        device = hello.get("device_id")
        return {
            "node_id": node.node_id, "name": node.name, "role": node.role,
            "owner": node.owner_name(self.fc.teams), "phase": node.phase,
            "game_time_ms": node.game_time_ms, "battery_pct": node.battery_pct,
            "rssi": node.rssi, "snr": node.snr, "epoch": node.epoch,
            "platform": hello.get("platform"), "fw_version": hello.get("fw_version"),
            "core_version": hello.get("core_version"), "tier": hello.get("tier"),
            "capabilities": hello.get("capabilities"),
            # The box's stable device id (HELLO key 10, protocol/field-frames.md), as hex.
            "device_id": device.hex() if isinstance(device, (bytes, bytearray)) and len(device) == 8 else None,
            "score": {t: v.get(f"node-{node.node_id}", 0) for t, v in self.fc._scores.items()},
            # Health as the controller logged it (node.online/node.offline, battery.low).
            "link": node.link, "battery_low": node.battery_low,
            # Two devices said HELLO on this node id (BN-18): one join used twice.
            "conflict": node.node_id in self.conflicts,
        }

    def send_node_cmd(self, node_id: int, cmd: str, params: Optional[dict[str, Any]]) -> dict[str, Any]:
        with self._lock:
            if self.game is None:
                raise Conflict("no live game")
            fc = self._live(self.game["id"])
            node_id = _int(node_id, "node id")
            if not 1 <= node_id <= 0xFFFF:
                raise ControllerError("node id: 1-65535 (65535 = every node)")
            if cmd not in NODE_COMMANDS:
                raise ControllerError(f"cmd: one of {', '.join(NODE_COMMANDS)} "
                                      "(start, pause, resume and end go through the game)")
            if params is not None and not isinstance(params, dict):
                raise ControllerError("params must be a map")
            if cmd == "mode":
                self._check_mode_command(fc, node_id, params or {})
            try:
                seq = fc.send_cmd(cmd, params or None, dest=node_id, now_ms=self.now_ms())
            except ValueError as exc:
                raise ControllerError(str(exc)) from None
            if seq is None:
                raise Unavailable(f"the radio modem is {self.radio_state}; command not sent")
            return {"node": node_id, "cmd": cmd, "opcode": CMD_OPCODES[cmd], "seq": seq}

    def send_update(self, node_id: int, params: dict[str, Any]) -> int:
        """CMD update (RFC 0001 Amendment 6) to one box, only while the live game has not started
        (firmware_updates.py checks the release and the box first). The packet's seq."""
        with self._lock:
            if self.game is None:
                raise Conflict("no live game: the boxes to update must be joined to one")
            fc = self._live(self.game["id"])
            if self.game["state"] != "ready":
                raise Conflict(f"game {self.game['id']} is {self.game['state']}: firmware updates only "
                               "before a game starts, never during one")
            try:
                seq = fc.send_cmd("update", params, dest=node_id, now_ms=self.now_ms())
            except ValueError as exc:
                raise ControllerError(str(exc)) from None
            if seq is None:
                raise Unavailable(f"the radio modem is {self.radio_state}; command not sent")
            return seq

    def _check_mode_command(self, fc: FieldController, node_id: int, params: dict[str, Any]) -> None:
        """A GM's mode command must be one the game's manifests declare, for the node's role."""
        assert self.game is not None
        name = params.get("name")
        pkg = self.modes.get(self.game["mode_id"])
        commands = pkg.mode.commands if pkg is not None else {}
        if not isinstance(name, str) or name not in commands:
            known = ", ".join(sorted(commands)) or "none in this game"
            raise ControllerError(f"params.name: one of the game's mode commands ({known})")
        node = fc.nodes.get(node_id)
        roles = commands[name].get("roles") or []
        if node_id != 0xFFFF and node is not None and node.role and node.role not in roles:
            raise ControllerError(f"{name} is a command for {', '.join(roles)} nodes; "
                                  f"node {node_id} is a {node.role}")

    def status(self) -> dict[str, Any]:
        with self._lock:
            fc = self.fc
            return {
                "node_id": self.node_id,
                "failover_mode": self.cfg.failover_mode,
                "joined": bool(self.game.get("joined")) if self.game else False,
                "leader": fc.election.leader if fc else None,
                "priority": self.priority,
                "role": fc.election.role if fc else None,
                "term": fc.term if fc else None,
                "live_game": self.game["id"] if self.game else None,
                "key_lost": self.key_lost,
                "radio": self.radio_state,
                "modem": {
                    "ident": self.modem.ident if self.modem else None,
                    "status": self.modem.status if self.modem else None,
                    "reconnects": self.modem.reconnects if self.modem else 0,
                },
                "tx_epoch": self.transport.epoch if self.transport else None,
                "tx_status": dict(self.tx_status),
                "field_channel_hz": self.field_channel,
                "channel_confirmed": self.store.get_setting("radio.channel_confirmed") == "1",
                "sync": self.sync.status() if self.sync is not None else {"enabled": False},
            }

    def promote(self) -> dict[str, Any]:
        """Manual failover (ADR-P2-8): stand for election on the live game."""
        with self._lock:
            if self.fc is None:
                raise Conflict("no live game")
            if self.fc.is_controller:
                raise Conflict(f"already the controller (term {self.fc.term})")
            self.fc.promote(self.now_ms())
            return self.status()

    # --- the tick -------------------------------------------------------------

    def tick(self) -> None:
        if self.checkin is not None:
            self.checkin.purge()  # retention (ADR-P3-13), at most every 10 minutes
        if self.branding is not None:
            self.branding.purge()  # crests nothing refers to any more, at most every 10 minutes
        if self.reinvite is not None:
            self.reinvite.tick(self.now_ms())  # invites and their retries, with or without a game
        if self.pairing is not None:
            self.pairing.tick(self.now_ms())  # pairing runs, offers heard, the listening window
        with self._lock:
            fc = self.fc
            if fc is None:
                return
            now = self.now_ms()
            fc.tick(now)
            if self.positions is not None:
                self.positions.tick()
            if self.field is not None and fc.game_state == GAME_RUNNING:
                self.field.advance(fc.game_time_ms)
                if self._after_field():
                    return
            if (self.game is not None and fc.is_controller and fc.game_state == GAME_RUNNING
                    and fc.duration_ms and fc.game_time_ms >= fc.duration_ms):
                self.end_game(self.game["id"], "time")
                return
            if self.game is not None and not fc.is_controller:
                self._follow_state(fc)
                if self.game is None:
                    return
            self._save_game_time()

    def _follow_state(self, fc: FieldController) -> None:
        """On standby: the stored game follows the controller's TIME beacons."""
        assert self.game is not None
        state = {GAME_RUNNING: "running", GAME_PAUSED: "paused", GAME_ENDED: "ended",
                 GAME_WAITING: "ready"}.get(fc.game_state, "ready")
        if fc.duration_ms != self.game.get("duration_ms"):
            self.game["duration_ms"] = fc.duration_ms
            self.store.update_game(self.game["id"], duration_ms=fc.duration_ms)
        if state == self.game["state"]:
            return
        if state == "ended":
            self._leave_standby(self.game["id"], "the game ended")
            return
        times: dict[str, float] = {}
        if state == "running" and not self.game.get("started_at"):
            times["started_at"] = time.time()
            self.game["started_at"] = times["started_at"]
        self._set_state(self.game["id"], state, **times)

    def _save_game_time(self, force: bool = False) -> None:
        if self.fc is None or self.game is None:
            return
        now = self.now_ms()
        if force or now - self._last_time_save >= GAME_TIME_SAVE_MS:
            self._last_time_save = now
            self.store.set_setting(f"game_time:{self.game['id']}", str(self.fc.game_time_ms))

    # --- radio side -------------------------------------------------------------

    def _on_rx(self, rx: RxPacket) -> None:
        with self._lock:
            if self.fc is None or self.game is None or rx.header.game_id != self.game["id"]:
                return
            self.fc.on_packet(rx.header.source, rx.header, rx.payload,
                              {"epoch": rx.epoch, "rssi": rx.rssi, "snr": rx.snr})

    def _on_tx_ack(self, seq: int, status: str) -> None:
        self.tx_status[status] += 1
        if status != "ok":
            log.warning("TX seq %d: %s", seq, status)
            self._emit({"type": "system", "kind": "tx.failed", "seq": seq, "status": status})

    def _on_modem_state(self, state: str) -> None:
        if state == radio_modem.UP:
            self._emit({"type": "system", "kind": "radio.up"})
            with self._lock:
                if self.fc is None and self.modem is not None and not (
                        self.scan is not None and self.scan.running):
                    self.modem.set_channel(self.field_channel)  # no game: listen on the field's channel
                    self._modem_moved("the modem came back")
                if self.fc is not None:
                    known = {n.node_id: n.epoch for n in self.fc.nodes.values() if n.epoch}
                    if known and self.modem is not None:
                        self.modem.set_peer_epochs(known)
        elif state == radio_modem.DOWN:
            self._emit({"type": "system", "kind": "radio.down"})

    def _on_modem_error(self, code: str, message: str) -> None:
        self._emit({"type": "system", "kind": "modem.error", "code": code, "message": message})

    def _modem_moved(self, why: str) -> None:
        """The modem was tuned to the field's channel: pairing is no longer listening on its own."""
        if self.pairing is not None:
            self.pairing.channel_moved(why)

    def _on_field_rx(self, frame: bytes, rssi: int, snr: int) -> None:
        """FIELD_RX: a pair frame (type 10) is pairing's, a field frame (type 9) the invites'."""
        if self.pairing is not None and self.pairing.is_ours(frame):
            self.pairing.on_frame(frame, rssi, snr)
        elif self.reinvite is not None:
            self.reinvite.on_field_rx(frame, rssi, snr)

    def _on_field_ack(self, tx_id: int, status: str) -> None:
        if self.pairing is not None and self.pairing.owns_tx(tx_id):
            self.pairing.on_ack(tx_id, status)
        elif self.reinvite is not None:
            self.reinvite.on_field_ack(tx_id, status)

    # --- FieldController hooks ---------------------------------------------------

    def _on_event(self, record: dict[str, Any]) -> None:
        if self.game is None:
            return
        if not self.store.insert_event(self.game["id"], record):
            return
        ev = _public_event(record)
        self._emit({"type": "event", "game": self.game["id"], "event": ev})
        if record.get("type") == scenarios.REVEALED:
            # A hidden objective's names reach its players with the game (P4R24): send it again.
            meta = self.scenario_meta(self.game["mode_id"])
            objective = meta.objectives.get((record.get("data") or {}).get("objective")) if meta else None
            if objective is not None and objective.get("visibility") == "hidden":
                self._emit({"type": "game", "game": self.public_game(self.game)})
        if self.positions is not None:
            self.positions.on_event(self.game["id"], record)
        if self.field is not None and record["node"] != self.node_id and record.get("origin") != "controller":
            # A box's events; not the health events the controller logs about a box (FU1-4).
            data = dict(record.get("data") or {})
            data.setdefault("node", record["node"])
            if record.get("team"):
                data.setdefault("team", record["team"])
            self.field.input(record["type"], data)
            # Inside the radio receive path: an end the script asks for waits for the tick.
            self._after_field(may_end=False)

    def _on_node(self, node: FieldNode, kind: str) -> None:
        if self.game is None:
            return
        info = self._node_info(node)
        self.store.upsert_node(self.game["id"], node.node_id, node.name, node.role,
                               {k: v for k, v in info.items() if k not in ("node_id", "name", "role")})
        # When it was last heard: a link event is news about a box that may have said nothing.
        info["seen_ms_ago"] = max(0, self.now_ms() - node.last_seen_ms) if node.heard else None
        self._emit({"type": "node", "game": self.game["id"], "kind": kind, "node": info})
        if kind == "hello":
            device = info.get("device_id")
            seen = self._devices.get(node.node_id)
            if device and seen and device != seen and node.node_id not in self.conflicts:
                # One join (a card, a text) used on two boxes, or a node id given twice: the two
                # use the same nonces under the game key (BN-18). Said loudly; the GM re-joins one.
                self.conflicts[node.node_id] = [seen, device]
                log.warning("two boxes share node %d (devices %s and %s): one join was used twice; "
                            "re-join one of them", node.node_id, seen, device)
                info["conflict"] = True
                self._emit({"type": "node", "game": self.game["id"], "kind": "conflict", "node": info})
            if device:
                self._devices[node.node_id] = device
            if self.reinvite is not None:
                self.reinvite.on_hello(node.node_id, info.get("device_id"))
            if self.game.get("state") == "ready" and not self.game.get("joined"):
                # The start check changed: the console's Start shows what is still missing.
                self._emit({"type": "game", "game": self.public_game(self.game)})

    def _on_scores(self, totals: dict[str, int]) -> None:
        if self.game is None:
            return
        self.store.save_scores(self.game["id"], totals)
        self._emit({"type": "score", "game": self.game["id"],
                    "teams": {t: int(totals.get(t, 0)) for t in self.game["teams"]}})

    def _on_role(self, role: str, term: int) -> None:
        if self.game is not None:
            self.store.update_game(self.game["id"], term=term)
        self._emit({"type": "system", "kind": "role", "role": role, "term": term})
        # A takeover: the game's field.lua runs here from now on (a new run; the
        # points of the old controller's runs are not known here, decision K5).
        if (role == LEADER and self.game is not None and self.fc is not None
                and self.fc.game_state in (GAME_RUNNING, GAME_PAUSED)):
            try:
                self._start_field()
            except (ModeError, ControllerError) as exc:
                log.error("field.lua cannot run after the takeover: %s", exc)

    # --- the field script ---------------------------------------------------------

    def _start_field(self) -> None:
        """Runs the game's field.lua (if its mode has one): at the start, after a
        controller restart and after a takeover. Each run is numbered, and its
        points are kept under its own key, so a new run adds to the earlier ones."""
        if self.game is None or self.fc is None or self.field is not None:
            return
        pkg = self.modes.get(self.game["mode_id"])
        if pkg is None or pkg.field_script is None:
            return
        if self.core is None:
            raise Unavailable("this mode has a field.lua and the core library is not loaded")
        gid = self.game["id"]
        run = int(self.store.get_setting(f"field_run:{gid}") or 0) + 1
        self.store.set_setting(f"field_run:{gid}", str(run))
        self.field = FieldScript(self.core, self, pkg.field_script, f"{pkg.id}/field.lua",
                                 self.game["teams"], self.game["params"], self.game["game_seed"],
                                 score_key=f"field-{run}")
        if self.fc.game_time_ms > 0:
            self.field.advance(self.fc.game_time_ms)  # a restart or a takeover joins mid-game
        self.field.input("game.start")
        if self.fc.game_state == GAME_PAUSED:
            self.field.input("game.pause")

    def field_position(self, game_id: int, fix: dict[str, Any]) -> bool:
        """A VIP's position report for the game's field.lua, as the input position.fix (player,
        team, role, lat, lon, acc, src; decision P4R6). Only the script gets it: it is not logged,
        not emitted, not sent on the radio, MQTT or the stream, not kept in state.field and not
        handed to a standby. True when the script got it (a running game on this controller)."""
        with self._lock:
            fc, field, game = self.fc, self.field, self.game
            if (field is None or fc is None or game is None or game["id"] != game_id
                    or not fc.is_controller or fc.game_state != GAME_RUNNING):
                return False
            field.advance(fc.game_time_ms)
            field.input("position.fix", fix)
            self._after_field()
            return True

    def _after_field(self, may_end: bool = True) -> bool:
        """After field.lua ran: keeps its points with the game, and ends the game if it
        asked to. True when the game ended."""
        field, game = self.field, self.game
        if field is None or game is None:
            return False
        gains = field.gains()
        if gains and self._field_scores.get(field.score_key) != gains:
            self._field_scores[field.score_key] = gains
            self.store.set_setting(f"field_scores:{game['id']}", json.dumps(self._field_scores))
        if not may_end or field.pending_end is None or not self.fc or not self.fc.is_controller:
            return False
        data, field.pending_end = field.pending_end, None
        self.end_game(game["id"], str(data.get("reason") or ""), winner=data.get("winner"))
        return True


def display_name(value: Any, name: str) -> Optional[str]:
    """A team's display name: 1-32 characters without control characters, or None to clear it."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ControllerError(f"{name}: text")
    value = value.strip()
    if value == "":
        return None
    if len(value) > TEAM_DISPLAY_MAX or any(ord(c) < 0x20 or 0x7F <= ord(c) <= 0x9F
                                             or 0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise ControllerError(f"{name}: 1-{TEAM_DISPLAY_MAX} characters without control characters")
    return value


def _int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ControllerError(f"{name} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ControllerError(f"{name} must be an integer") from None


def _winner(totals: dict[str, int], teams: list[str]) -> Optional[str]:
    """The team with the highest total, or None on a tie or when nobody scored."""
    ranked = sorted(((totals.get(t, 0), t) for t in teams), reverse=True)
    if not ranked or ranked[0][0] <= 0 or (len(ranked) > 1 and ranked[0][0] == ranked[1][0]):
        return None
    return ranked[0][1]


def _public_event(record: dict[str, Any]) -> dict[str, Any]:
    return {k: record.get(k) for k in ("node", "seq", "t", "type", "team", "squad", "prio",
                                       "data", "epoch", "pkt_seq")}
