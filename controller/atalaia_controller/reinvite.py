# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Re-inviting boxes into the next game over the radio (protocol/field-frames.md).

A box whose game is over announces itself in field frames sealed with a key
derived from the field join key; the USB modem hands them over as they are
(FIELD_RX). This module keeps the free boxes the controller has heard, sends
a DISCOVER when the GM opens the console's box picker, and invites the boxes
the GM picks into the live game: for each, a join payload made exactly as
for a card (Controller.issue_join), split into one to three INVITE parts
for the box's device id and the token of its last announcement, sent through
the modem (FIELD_TX), resent until the box answers. Its HELLO in the game
closes the invite. The shared logic is atalaia_sim.lobby, which the
simulator's radio-model tests also run.

The previous game's boxes (to pre-select in the console) are the nodes of
the most recent other game whose HELLO carried a device id, with their roles.
Nothing here is stored: invites last as long as the controller runs.

A box that answered *no mode* can be invited again with ``fetch_modes`` (join key 16): it
then fetches the parts it lacks over HTTPS before its HELLO (mode_fetch.py, phase 5 plan phase
13); a box the GM marked in the Boxes tab gets ``forget_modes`` (key 17) in its next invite.

When a game ends, GAME_OVER says so to its boxes (decisions OT-7, OT-13): the
game id and its key's tag, sealed under the field key, three times, on the
game's channel. A controller that restarted without the game's key can still
end it this way; with the key, it follows the game's own CMD end.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any, Optional

from atalaia_sim import field_frame as ff
from atalaia_sim import lobby

if TYPE_CHECKING:
    from .engine import Controller

log = logging.getLogger("atalaia.reinvite")

DEVICE_HEX_LEN = 2 * ff.DEVICE_SIZE


def ff_repeats() -> int:
    return lobby.GAME_OVER_REPEATS


class Reinvite:
    def __init__(self, controller: "Controller") -> None:
        self.ctl = controller
        self.inviter = lobby.Inviter(controller.join_key, self._send, nonces=self._nonces())
        self.inviter.on_change = self._changed
        self.inviter.tune = self._tune
        self._pending_emit: set[str] = set()
        self._tuned: Optional[int] = None  # the channel a GAME_OVER took the modem to

    def _nonces(self) -> ff.NonceSource:
        """This controller's field frame nonces (decisions RJ-7, RJ-15): a sender id fresh from
        os.urandom for every run, never stored, so nothing persisted can roll back (a restored
        backup, an SD card image, a standby built from a copy of the primary's database); boot 1
        and the frame count, then boot 2 after 65536 frames, within the run."""
        self.sender_id = os.urandom(ff.SENDER_SIZE)
        return ff.NonceSource(self.ctl.join_key, self.sender_id)

    # --- the radio ----------------------------------------------------------------

    def _send(self, frame: bytes) -> Optional[int]:
        modem = self.ctl.modem
        if modem is None or not modem.is_up:
            return None
        return modem.send_field(frame)

    def on_field_rx(self, frame: bytes, rssi: int, snr: int) -> None:
        with self.ctl._lock:
            msg = self.inviter.on_frame(frame, self.ctl.now_ms(), rssi, snr)
            if msg is not None and msg.get("answer") is not None:
                log.info("box %s answered invite %d: %s", msg["device_id"].hex(), msg["answer"], msg["result"])
            self._flush()

    def on_field_ack(self, tx_id: int, status: str) -> None:
        with self.ctl._lock:
            self.inviter.on_tx_result(tx_id, status)
            if status != "ok":
                log.warning("field frame %d: %s", tx_id, status)
            self._flush()

    def tick(self, now_ms: int) -> None:
        with self.ctl._lock:
            self.inviter.tick(now_ms)
            self._flush()

    def on_hello(self, node_id: int, device_hex: Optional[str]) -> None:
        """A HELLO in the live game: an invite for that node is done."""
        device = bytes.fromhex(device_hex) if device_hex else None
        game = self.ctl.game
        inv = self.inviter.on_hello(node_id, device, game_id=game["id"] if game is not None else None)
        if inv is not None:
            log.info("box %s joined game %d as node %d (%s)", inv.device_id.hex(), inv.game_id, node_id, inv.role)
        self._flush()

    def game_over(self, game_id: int, key_tag: bytes, channel_hz: Optional[int]) -> bool:
        """Tells the game's boxes it is over (GAME_OVER, decision OT-13); False without a radio."""
        modem = self.ctl.modem
        if modem is None or not modem.is_up or not getattr(modem, "has_field_frames", False):
            log.warning("game %d: no GAME_OVER sent (the radio modem is %s)", game_id, self.ctl.radio_state)
            return False
        self.inviter.game_over(game_id, key_tag, self.ctl.now_ms(), channel_hz=channel_hz)
        log.info("game %d: GAME_OVER to its boxes (%d times, on %s Hz)", game_id, ff_repeats(), channel_hz)
        self.inviter.tick(self.ctl.now_ms())  # the first one at once
        return True

    def _tune(self, channel_hz: Optional[int]) -> bool:
        """The modem on a GAME_OVER's channel (its game's) while no game is live, then back on the
        field's; with a game live on another channel, that GAME_OVER is dropped."""
        modem, field = self.ctl.modem, self.ctl.field_channel
        if channel_hz is None:
            if self._tuned is not None and self.ctl.fc is None and modem is not None and modem.is_up:
                modem.set_channel(field)
                self.ctl._modem_moved("a game over was told on its game's channel")
            self._tuned = None
            return True
        if self.ctl.fc is not None:
            transport = self.ctl.transport
            return transport is not None and transport.channel_hz == channel_hz
        if channel_hz != field and self._tuned != channel_hz and modem is not None:
            modem.set_channel(channel_hz)
            self.ctl._modem_moved("a game over is told on its game's channel")
            self._tuned = channel_hz
        return True

    def forget_game(self, game_id: int) -> None:
        """The game ended or was deleted: its invites go (no more retries into it)."""
        self.inviter.forget_game(game_id)
        self._flush()

    def _changed(self, what: str) -> None:
        self._pending_emit.add(what)

    def _flush(self) -> None:
        """Tells the consoles what changed (outside the inviter's own calls)."""
        pending, self._pending_emit = self._pending_emit, set()
        if "boxes" in pending:
            self.ctl._emit({"type": "boxes", "boxes": self.boxes()["boxes"]})
        if "invites" in pending and self.ctl.game is not None:
            gid = self.ctl.game["id"]
            invites = self.invites(gid)
            self.ctl._emit({"type": "invites", "game": gid, "invites": invites})
            if self.ctl.mode_fetch is not None:
                self.ctl.mode_fetch.on_invites(invites)  # a box fetching, or one that could not

    # --- what the console shows ----------------------------------------------------

    def previous_game(self) -> Optional[dict[str, Any]]:
        """The most recent game other than the live one that had boxes with a device id."""
        live = self.ctl.game["id"] if self.ctl.game is not None else None
        for game in reversed(self.ctl.store.games()):
            if game["id"] == live:
                continue
            nodes = [n for n in self.ctl.store.nodes(game["id"]) if n.get("device_id")]
            if nodes:
                return {"id": game["id"], "name": game["name"], "mode_id": game["mode_id"],
                        "boxes": {n["device_id"]: n["role"] for n in nodes}}
        return None

    def _in_live_game(self) -> dict[str, int]:
        """Device id -> node id of the boxes the live game has heard."""
        fc = self.ctl.fc
        out: dict[str, int] = {}
        if fc is not None:
            for node in fc.nodes.values():
                dev = node.hello.get("device_id")
                if isinstance(dev, (bytes, bytearray)) and len(dev) == ff.DEVICE_SIZE:
                    out[bytes(dev).hex()] = node.node_id
        return out

    def boxes(self) -> dict[str, Any]:
        with self.ctl._lock:
            now = self.ctl.now_ms()
            prev = self.previous_game()
            prev_boxes = prev["boxes"] if prev else {}
            live = self._in_live_game()
            out = []
            for box in self.inviter.available(now):
                entry = box.public(now)
                hexid = entry["device_id"]
                entry["previous"] = hexid in prev_boxes
                entry["previous_role"] = prev_boxes.get(hexid) or entry.get("last_role")
                entry["node_id"] = live.get(hexid)
                inv = self.inviter.invites.get(hexid)
                entry["invite"] = inv.public() if inv is not None else None
                out.append(entry)
            radio = self.ctl.modem
            return {"boxes": out, "previous_game": {k: v for k, v in prev.items() if k != "boxes"} if prev else None,
                    "radio": radio is not None and radio.is_up,
                    "field_frames": radio is not None and getattr(radio, "has_field_frames", False),
                    "ignored": self.inviter.ignored, "stale": self.inviter.stale}

    def invites(self, game_id: int) -> list[dict[str, Any]]:
        return [i.public() for i in self.inviter.invites.values() if i.game_id == game_id]

    # --- what the GM does ------------------------------------------------------------

    def discover(self) -> dict[str, Any]:
        from .engine import Unavailable
        with self.ctl._lock:
            modem = self.ctl.modem
            if modem is None or not modem.is_up:
                raise Unavailable(f"the radio modem is {self.ctl.radio_state}: no DISCOVER sent")
            sent = self.inviter.discover(self.ctl.now_ms())
            return {"sent": sent}

    def invite(self, game_id: int, specs: Any) -> dict[str, Any]:
        """Invites boxes into the live game: [{"device_id", "role"?, "name"?, "fetch_modes"?}, ...].

        ``fetch_modes``: the box fetches the parts it lacks (join key 16, mode_fetch.py); a box
        marked to forget its fetched modes gets join key 17 as well."""
        from .engine import Conflict, ControllerError, Unavailable
        with self.ctl._lock:
            game = self.ctl.game
            if game is None or game["id"] != game_id:
                raise Conflict(f"game {game_id} is not the live game")
            if game["state"] != "ready":
                raise Conflict(f"game {game_id} is {game['state']}: boxes are invited before it starts")
            modem = self.ctl.modem
            if modem is None or not modem.is_up:
                raise Unavailable(f"the radio modem is {self.ctl.radio_state}: no invite can be sent")
            if not isinstance(specs, list) or not specs or len(specs) > 64:
                raise ControllerError("boxes: a list of 1-64 {device_id, role?, name?}")
            now = self.ctl.now_ms()
            out = []
            for spec in specs:
                if not isinstance(spec, dict) or not isinstance(spec.get("device_id"), str) \
                        or len(spec["device_id"]) != DEVICE_HEX_LEN:
                    raise ControllerError("each box: {device_id: 16 hex digits, role?, name?}")
                hexid = spec["device_id"].lower()
                try:
                    device = bytes.fromhex(hexid)
                except ValueError:
                    raise ControllerError(f"device_id {hexid!r}: 16 hex digits") from None
                if hexid not in self.inviter.boxes:
                    out.append({"device_id": hexid, "status": "failed", "detail": "not announcing itself"})
                    continue
                if hexid in self._in_live_game():
                    out.append({"device_id": hexid, "status": "joined", "detail": "already in this game"})
                    continue
                existing = self.inviter.invites.get(hexid)
                join_spec = {"kind": "node", "role": spec.get("role")}
                if spec.get("name") is not None:
                    join_spec["name"] = spec["name"]
                fetch = spec.get("fetch_modes", False)
                if not isinstance(fetch, bool):
                    raise ControllerError("fetch_modes: true or false")
                mf = self.ctl.mode_fetch
                if fetch:
                    join_spec["fetch_modes"] = True
                if mf is not None and hexid in mf.forget_marked():
                    join_spec["forget_modes"] = True
                # The same node id when the box is invited again into this game.
                node_id = existing.node_id if existing is not None and existing.game_id == game_id else None
                tier = self.inviter.boxes[hexid].tier
                try:
                    made = self.ctl.issue_join(join_spec, node_id=node_id, same_device=node_id is not None,
                                               device=hexid, tier=tier)
                except Conflict as exc:
                    if not fetch:
                        raise
                    # This box cannot be sent the modes (a Reduced box, a part not offered...): said
                    # for it alone, the other boxes are still invited.
                    out.append({"device_id": hexid, "status": "not_sent", "detail": str(exc)})
                    continue
                payload = bytes.fromhex(made["payload_hex"])
                try:
                    inv = self.inviter.invite(device, payload, game_id=game_id, node_id=made["node_id"],
                                              role=made["role"], now_ms=now, name=made.get("name"))
                except lobby.InviteError as exc:
                    out.append({"device_id": hexid, "status": "too_big", "detail": str(exc)})
                    continue
                log.info("inviting box %s into game %d as node %d (%s), %d bytes in %d part(s)",
                         hexid, game_id, inv.node_id, inv.role, len(payload), inv.parts)
                out.append(inv)
            self.inviter.tick(now)  # the first one goes at once; the others as the air allows
            self._flush()
            return {"invites": [i.public() if isinstance(i, lobby.Invite) else i for i in out]}
