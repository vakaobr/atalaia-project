# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""MQTT bridge to the system Mosquitto broker (ADR-P2-5, spec section 11).

Publishes:
    field/v1/{game}/events/{type}         every game event, JSON (QoS 1)
    field/v1/{game}/score                 totals per team (retained)
    field/v1/{game}/nodes/{node}/state    owner, phase, game time, counters (retained)
    field/v1/{game}/nodes/{node}/health   battery, RSSI, SNR, last seen (retained)
Subscribes:
    field/v1/{game}/cmd/{node}            {"cmd": "message", "params": {...}}
    field/v1/{game}/cmd/all

Who may publish to cmd/ is the broker's job: the read and GM tokens map to
Mosquitto users and an ACL (controller/deploy/mosquitto.conf, aclfile).
The bridge keeps the last retained payload per topic and publishes them
again after a reconnect; events published while the broker is unreachable
are not queued (they are in the SQLite log: GET /api/v1/games/{id}/log).
Works with paho-mqtt 1.6 (Debian/Raspberry Pi OS) and 2.x.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Optional

import paho.mqtt.client as paho

from .config import Config
from .engine import Controller, ControllerError

log = logging.getLogger("atalaia.mqtt")

PREFIX = "field/v1"


def _client(client_id: str) -> paho.Client:
    version = getattr(paho, "CallbackAPIVersion", None)
    if version is not None:  # paho-mqtt 2.x
        return paho.Client(version.VERSION2, client_id=client_id)
    return paho.Client(client_id=client_id)


def _ok(reason: Any) -> bool:
    if hasattr(reason, "is_failure"):
        return not reason.is_failure
    return reason == 0


class MqttBridge:
    def __init__(self, cfg: Config, controller: Controller, client_id: str = "atalaia-controller") -> None:
        self.cfg = cfg
        self.controller = controller
        self.client = _client(client_id)
        if cfg.mqtt_username:
            self.client.username_pw_set(cfg.mqtt_username, cfg.mqtt_password or None)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(1, 30)
        self.connected = threading.Event()
        self._retained: dict[str, bytes] = {}
        self._lock = threading.Lock()
        self.published = 0
        self.commands = 0
        controller.add_listener(self.on_controller_message)

    # --- lifecycle --------------------------------------------------------------

    def start(self) -> None:
        self.client.connect_async(self.cfg.mqtt_host, self.cfg.mqtt_port, keepalive=30)
        self.client.loop_start()

    def stop(self) -> None:
        self.client.disconnect()
        self.client.loop_stop()

    def _on_connect(self, client, userdata, flags, reason, *args) -> None:
        if not _ok(reason):
            log.warning("MQTT broker refused the connection: %s", reason)
            return
        log.info("MQTT connected to %s:%d", self.cfg.mqtt_host, self.cfg.mqtt_port)
        client.subscribe(f"{PREFIX}/+/cmd/+", qos=1)
        with self._lock:
            retained = list(self._retained.items())
        for topic, payload in retained:
            client.publish(topic, payload, qos=1, retain=True)
        self.connected.set()

    def _on_disconnect(self, client, userdata, *args) -> None:
        self.connected.clear()
        log.info("MQTT disconnected; reconnecting")

    # --- out --------------------------------------------------------------------

    def _publish(self, topic: str, data: Any, retain: bool = False) -> None:
        payload = json.dumps(data, separators=(",", ":")).encode()
        if retain:
            with self._lock:
                self._retained[topic] = payload
        info = self.client.publish(topic, payload, qos=1, retain=retain)
        if info.rc == 0:
            self.published += 1

    def on_controller_message(self, msg: dict[str, Any]) -> None:
        kind = msg.get("type")
        game = msg.get("game")
        if kind == "event":
            ev = msg["event"]
            self._publish(f"{PREFIX}/{game}/events/{ev['type']}", {"game": game, **ev})
        elif kind == "score":
            self._publish(f"{PREFIX}/{game}/score", {"game": game, "teams": msg["teams"],
                                                    "at": time.time()}, retain=True)
        elif kind == "node":
            node = msg["node"]
            base = f"{PREFIX}/{game}/nodes/{node['node_id']}"
            self._publish(f"{base}/state", {k: node.get(k) for k in (
                "node_id", "name", "role", "owner", "phase", "game_time_ms", "score")}, retain=True)
            self._publish(f"{base}/health", {**{k: node.get(k) for k in (
                "node_id", "battery_pct", "rssi", "snr", "epoch", "fw_version")}, "last_seen": time.time()},
                retain=True)

    # --- in ---------------------------------------------------------------------

    def _on_message(self, client, userdata, message) -> None:
        parts = message.topic.split("/")
        if len(parts) != 5 or parts[0:2] != PREFIX.split("/") or parts[3] != "cmd":
            return
        self.commands += 1
        try:
            game_id = int(parts[2])
            target = 0xFFFF if parts[4] == "all" else int(parts[4])
            body = json.loads(message.payload.decode("utf-8"))
            if not isinstance(body, dict):
                raise ValueError("the payload must be a JSON object")
            live = self.controller.game
            if live is None or live["id"] != game_id:
                raise ControllerError(f"game {game_id} is not live")
            result = self.controller.send_node_cmd(target, body.get("cmd"), body.get("params"))
            log.info("MQTT command to %s: %s", parts[4], result)
        except (ValueError, ControllerError, UnicodeDecodeError) as exc:
            log.warning("MQTT command on %s refused: %s", message.topic, exc)

    def wait_connected(self, timeout: float) -> bool:
        return self.connected.wait(timeout)


def maybe_bridge(cfg: Config, controller: Controller) -> Optional[MqttBridge]:
    return MqttBridge(cfg, controller) if cfg.mqtt_enabled else None
