# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Android props on the field's Wi-Fi (decision PD12, protocol/prop-link.md).

A phone prop that joined a game with a join payload holds the game's id,
key and its node id. It connects to WS /api/v1/prop (wss:// with the field
CA from the payload's key 13), proves it holds the game key with an
HMAC-SHA256 over a fresh challenge, and then takes part as a box does over
the radio:

    prop -> controller   hello, state, event (the HELLO, STATE and EVENT payloads' fields as JSON)
    controller -> prop   welcome, time (TIME beacons), cmd (CMD), ack (an event was logged)

Nothing is written twice: each message is encoded with the same codecs as
the radio's payloads (atalaia_sim.packet, atalaia_sim.codec) and handed to
the game's FieldController exactly like a packet from the USB modem, so
registration, score merging, event decoding and the log's duplicate checks
are the radio's. The controller's TIME beacons and commands reach linked
props as well as the radio (ModemTransport calls :meth:`PropLinks.forward`).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import os
import threading
from typing import TYPE_CHECKING, Any, Optional

from atalaia_sim import codec
from atalaia_sim.field_controller import CMD_OPCODES, CMD_PEER_EPOCH, STATE_NAMES
from atalaia_sim.packet import Header, cmd_decode, hello_encode, state_encode, time_decode, vf_make
from atalaia_sim.protocol import MESSAGE_TYPES

if TYPE_CHECKING:
    from .engine import Controller

log = logging.getLogger("atalaia.prop")

DOMAIN = b"atalaia-prop-link-v1\x00"
NONCE_SIZE = 32
QUEUE_MAX = 256
AUTH_TIMEOUT_S = 10.0
# CMD peer (opcode 11, Amendment 24) is the controller's own and not in the GM's list, but a prop is told it too (EP-1).
OPCODE_NAMES = {**{v: k for k, v in CMD_OPCODES.items()}, CMD_PEER_EPOCH: "peer"}
PRIOS = {"telemetry": 0, "normal": 1, "critical": 2}


def proof(game_key: bytes, nonce: bytes, game_id: int, node_id: int) -> bytes:
    """HMAC-SHA256(game key, domain | nonce | game id | node id), ids as 16-bit big-endian."""
    msg = DOMAIN + nonce + game_id.to_bytes(2, "big") + node_id.to_bytes(2, "big")
    return hmac.new(game_key, msg, hashlib.sha256).digest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: Any) -> Optional[bytes]:
    if not isinstance(text, str) or len(text) > 64:
        return None
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (ValueError, TypeError):
        return None


class _Link:
    def __init__(self, node_id: int, game_id: int, loop: asyncio.AbstractEventLoop) -> None:
        self.node_id = node_id
        self.game_id = game_id
        self.loop = loop
        self.queue: asyncio.Queue = asyncio.Queue(QUEUE_MAX)

    def put(self, msg: Optional[dict[str, Any]]) -> None:
        def _put() -> None:
            try:
                self.queue.put_nowait(msg)
            except asyncio.QueueFull:
                while not self.queue.empty():
                    self.queue.get_nowait()
                self.queue.put_nowait(None)  # too slow: closes, the prop reconnects
        try:
            self.loop.call_soon_threadsafe(_put)
        except RuntimeError:
            pass


class PropLinks:
    def __init__(self, controller: "Controller") -> None:
        self.ctrl = controller
        self._links: dict[int, _Link] = {}
        self._seq: dict[int, int] = {}
        self._lock = threading.Lock()
        controller.prop_links = self

    @property
    def count(self) -> int:
        return len(self._links)

    def linked(self) -> list[int]:
        with self._lock:
            return sorted(self._links)

    # --- controller -> props -------------------------------------------------------

    def forward(self, msg_type: int, payload: bytes) -> bool:
        """A packet the controller sends: TIME and CMD also go to the linked props. True if one got it."""
        with self._lock:
            links = list(self._links.values())
        if not links:
            return False
        if msg_type == MESSAGE_TYPES["TIME"]:
            try:
                t = time_decode(payload)
            except Exception:
                return False
            msg = {"type": "time", **t, "state": STATE_NAMES.get(t.get("game_state"), "waiting")}
            for link in links:
                link.put(msg)
            return True
        if msg_type == MESSAGE_TYPES["CMD"]:
            try:
                c = cmd_decode(payload)
            except Exception:
                return False
            msg = {"type": "cmd", "cmd": OPCODE_NAMES.get(c.get("cmd"), str(c.get("cmd"))),
                   "opcode": c.get("cmd"), "params": c.get("params") or {}}
            dest = c.get("dest")
            sent = False
            for link in links:
                if dest is None or dest == link.node_id:
                    link.put({**msg, "dest": dest})
                    sent = True
            return sent
        return False

    def _time_now(self) -> Optional[dict[str, Any]]:
        fc = self.ctrl.fc
        if fc is None:
            return None
        return {"type": "time", "game_time_ms": fc.game_time_ms, "game_state": fc.game_state,
                "state": STATE_NAMES.get(fc.game_state, "waiting"), "duration_ms": fc.duration_ms,
                "term": fc.term}

    # --- props -> controller ---------------------------------------------------------

    def _deliver(self, node_id: int, game_id: int, kind: str, payload: bytes, prio: int) -> None:
        ctrl = self.ctrl
        with ctrl._lock:
            fc = ctrl.fc
            if fc is None or ctrl.game is None or ctrl.game["id"] != game_id:
                raise ValueError("the game is no longer live here")
            with self._lock:
                seq = self._seq.get(node_id, 0) % 0x10000
                self._seq[node_id] = seq + 1
            header = Header(vf_make(1, prio, False, True), game_id, node_id, seq, 0, MESSAGE_TYPES[kind])
            fc.on_packet(node_id, header, payload, {"epoch": 0, "link": "wifi"})

    def handle(self, link: _Link, msg: Any) -> Optional[dict[str, Any]]:
        """One message from a prop; the answer to send back, if any. Raises ValueError to refuse it."""
        if not isinstance(msg, dict):
            raise ValueError("a message is a JSON object")
        kind = msg.get("type")
        if kind == "ping":
            return {"type": "pong"}
        if kind == "hello":
            fields = {k: msg[k] for k in ("node_name", "platform", "fw_version", "core_version", "tier",
                                          "capabilities", "transports", "battery_pct") if k in msg}
            fields.setdefault("platform", 3)  # android
            fields.setdefault("transports", 0b10)  # wifi
            fields["epoch"] = 0
            self._deliver(link.node_id, link.game_id, "HELLO", hello_encode(fields), 1)
            return None
        if kind == "state":
            fields = {k: msg[k] for k in ("owner_team", "phase", "game_time_ms", "counters", "battery_pct",
                                          "flags") if k in msg}
            counters = fields.get("counters")
            if isinstance(counters, dict):
                fields["counters"] = {int(k): v for k, v in counters.items() if str(k).isdigit()}
            fields["epoch"] = 0
            self._deliver(link.node_id, link.game_id, "STATE", state_encode(fields), 0)
            return None
        if kind == "event":
            ev = msg.get("event")
            if not isinstance(ev, dict):
                raise ValueError("event: an object")
            record = {k: ev[k] for k in ("seq", "t", "type", "team", "squad", "prio", "data") if k in ev}
            record["node"] = link.node_id
            problems = codec.schema_problems(str(record.get("type")), record.get("data") or {})
            if problems:
                raise ValueError("; ".join(problems))
            payload = codec.encode_event(record)
            self._deliver(link.node_id, link.game_id, "EVENT", payload, PRIOS.get(record.get("prio"), 1))
            return {"type": "ack", "seq": record.get("seq"), "event_type": record.get("type")}
        raise ValueError(f"unknown message type {kind!r}")

    # --- the WebSocket ---------------------------------------------------------------

    async def serve(self, ws: Any) -> None:
        """WS /api/v1/prop: challenge, proof, then the link (close codes: 4401 refused, 4409 replaced)."""
        await ws.accept()
        nonce = os.urandom(NONCE_SIZE)
        await ws.send_json({"type": "challenge", "nonce": _b64(nonce), "version": 1})
        try:
            auth = await asyncio.wait_for(ws.receive_json(), AUTH_TIMEOUT_S)
        except Exception:
            await ws.close(code=4401)
            return
        link = self._authenticate(auth, nonce)
        if link is None:
            await ws.send_json({"type": "refused", "reason": "auth"})
            await ws.close(code=4401)
            return
        with self._lock:
            old = self._links.get(link.node_id)
            self._links[link.node_id] = link
        if old is not None:
            old.put({"type": "replaced"})
            old.put(None)
        log.info("prop %d linked over Wi-Fi to game %d", link.node_id, link.game_id)
        try:
            welcome = {"type": "welcome", "game_id": link.game_id, "node_id": link.node_id,
                       "controller_id": self.ctrl.node_id, "time": self._time_now()}
            await ws.send_json(welcome)

            async def sender() -> None:
                while True:
                    out = await link.queue.get()
                    if out is None:
                        await ws.close(code=4409)
                        return
                    await ws.send_json(out)

            async def receiver() -> None:
                while True:
                    msg = await ws.receive_json()
                    try:
                        answer = self.handle(link, msg)
                    except (ValueError, codec.CodecError) as exc:
                        answer = {"type": "error", "message": str(exc)[:200],
                                  "seq": msg.get("event", {}).get("seq") if isinstance(msg, dict)
                                  and isinstance(msg.get("event"), dict) else None}
                    if answer is not None:
                        link.put(answer)

            tasks = [asyncio.ensure_future(sender()), asyncio.ensure_future(receiver())]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            for task in done:
                task.exception()  # a closed socket ends the link either way
        finally:
            with self._lock:
                if self._links.get(link.node_id) is link:
                    del self._links[link.node_id]
            log.info("prop %d left the Wi-Fi link", link.node_id)

    def _authenticate(self, auth: Any, nonce: bytes) -> Optional[_Link]:
        if not isinstance(auth, dict) or auth.get("type") != "auth":
            return None
        game_id, node_id = auth.get("game_id"), auth.get("node_id")
        if isinstance(game_id, bool) or isinstance(node_id, bool) or not isinstance(game_id, int) \
                or not isinstance(node_id, int) or not 1 <= node_id <= 0xFFFE:
            return None
        ctrl = self.ctrl
        with ctrl._lock:
            game = ctrl.game
            if game is None or game["id"] != game_id or ctrl.key_lost or ctrl.fc is None:
                return None
            if node_id == ctrl.node_id or str(node_id) not in game["assignments"]:
                return None
            key = ctrl._key
        got = _unb64(auth.get("proof"))
        if got is None or not hmac.compare_digest(got, proof(key, nonce, game_id, node_id)):
            return None
        return _Link(node_id, game_id, asyncio.get_running_loop())
