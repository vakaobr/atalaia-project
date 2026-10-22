# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Firmware updates for the Field Boxes (protocol/firmware-update.md, decisions FU3-*).

The GM uploads a signed release in the console: the image and the fields of its
``.release.json`` (``tools/firmware_release.py``). The controller keeps it only if a
key of ``[firmware] release_keys`` signed exactly that platform, version, size and
SHA-256, and the image's own descriptors agree (an Atalaia Field Box image, of that
version). It keeps at most ``MAX_RELEASES``, in ``[firmware] dir``.

Then the GM starts an update for one box or for all, only while the live game has
not started (``ready``): never during a game. For each box the controller checks
what it knows from the box's HELLO (its platform is the release's, its tier is a
box's, its version is lower) and sends it CMD update (opcode 9, RFC 0001
Amendment 6) with the release's id and version over the radio. The box fetches
the release text and the image over HTTPS from the addresses in its join
(key 14), pinning the field CA (key 13), checks everything again with the keys in
its own firmware, installs, and reports (an HMAC-SHA256 with the game key). Its
next HELLO shows the version it runs: the new one (done) or, after a report of
"installed", the old one (the new image did not confirm itself: rolled back).

Served without a token, for the boxes: ``GET /api/v1/firmware/{id}/release`` and
``.../image`` (a signed release is public: the firmware is open source and every
box verifies it) and ``POST /api/v1/firmware/report`` (authenticated by its MAC).
The update attempts live in memory: after a restart the boxes' HELLOs tell the
truth again. The live game cannot start while an update is on its way (the GM can
cancel the tracking); a box also stops its download when a game starts.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from . import firmware_release as fr
from .engine import Conflict, Controller, ControllerError, NotFound, Unavailable

log = logging.getLogger("atalaia.firmware")

MAX_RELEASES = 4
SLOT_SIZE = 0x200000  # bytes of a Field Box's OTA slot (firmware/esp32/partitions.csv)
BOX_PLATFORMS = ("esp32", "esp32s3")  # platforms whose boxes take firmware updates
BOX_TIERS = (0, 1)  # HELLO's tier: full, reduced (2 = proxy: a phone, never updated this way)
VARIANTS = ("box",)  # the Field Box's images ([firmware] variants: "box-bench" for a test on the desk)
REPORT_MAX = 512
ACTIVE = ("sent", "installed")  # an update on its way
UPDATE_FAILED = "node.update_failed"  # a box's failure said over LoRa (protocol/schema/events.yaml, id 52)
REASON = re.compile(r"[a-z][a-z_]{0,23}")  # a result code: no_wifi, unreachable, busy...


class FirmwareUpdates:
    """The releases the GM uploaded, and the updates sent to the live game's boxes."""

    def __init__(self, controller: Controller, directory: Path, keys: list[str], timeout_s: float = 600.0,
                 clock: Callable[[], float] = time.time, variants: Optional[list[str]] = None) -> None:
        self.controller = controller
        self.variants = tuple(variants or VARIANTS)
        self.dir = Path(directory)
        self.keys = list(keys)
        self.timeout_s = timeout_s
        self.clock = clock
        self._lock = threading.Lock()
        self.attempts: dict[int, dict[str, Any]] = {}  # node id -> the latest update sent to it
        self.dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.dir, 0o700)
        except OSError:
            pass
        controller.start_guard = self.busy
        controller.firmware = self
        controller.add_listener(self.on_message)

    # ---- releases -------------------------------------------------------------------------

    def _entries(self) -> list[dict[str, Any]]:
        out = []
        for meta in sorted(self.dir.glob("*.json")):
            try:
                entry = json.loads(meta.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(entry, dict) and (self.dir / f"{entry.get('sha256')}.bin").is_file():
                out.append(entry)
        out.sort(key=lambda e: (e["platform"], fr.version_key(e["version"]) or ()), reverse=True)
        return out

    def _signer(self, e: dict[str, Any]) -> Optional[str]:
        return fr.signer(self.keys, e["platform"], e["version"], e["size"], e["sha256"], e["signature"])

    def _public(self, e: dict[str, Any]) -> dict[str, Any]:
        key = self._signer(e)
        return {"id": e["sha256"][:16], "platform": e["platform"], "version": e["version"], "size": e["size"],
                "sha256": e["sha256"], "signature": e["signature"], "variant": e["variant"], "board": e["board"],
                "uploaded_at": e["uploaded_at"], "key_id": key, "verified": key is not None}

    def releases(self) -> list[dict[str, Any]]:
        """Every kept release; ``verified`` is False once its key left ``release_keys``."""
        with self._lock:
            return [self._public(e) for e in self._entries()]

    def _find(self, release_id: str) -> dict[str, Any]:
        if not isinstance(release_id, str) or not fr.RELEASE_ID.fullmatch(release_id):
            raise NotFound("no such firmware release")
        for e in self._entries():
            if e["sha256"].startswith(release_id):
                return e
        raise NotFound("no such firmware release")

    def add(self, image: bytes, platform: Any, version: Any, signature: Any) -> dict[str, Any]:
        """Keeps a release the GM uploaded, after every check; ControllerError (or Conflict) otherwise."""
        if not self.keys:
            raise Conflict("no release key is configured ([firmware] release_keys): no release is accepted")
        if platform not in BOX_PLATFORMS:
            raise ControllerError(f"platform: one of {', '.join(BOX_PLATFORMS)} (a Field Box's)")
        if not isinstance(version, str) or fr.version_key(version) is None or len(version) > 31:
            raise ControllerError("version: MAJOR.MINOR.PATCH with an optional -pre-release, at most 31 characters")
        if fr.signature_bytes(signature) is None:
            raise ControllerError("signature: 64 bytes in standard base64 (88 characters)")
        if not 1 <= len(image) <= SLOT_SIZE:
            raise ControllerError(f"the image must be 1 to {SLOT_SIZE} bytes (a Field Box's OTA slot)")
        sha = hashlib.sha256(image).hexdigest()
        if fr.signer(self.keys, platform, version, len(image), sha, signature) is None:
            raise ControllerError("the signature does not verify with a release key of this controller "
                                  "(another image, version or platform than the one signed, or another key)")
        try:
            info = fr.image_info(image[:fr.IMAGE_HEAD])
        except fr.ReleaseError as exc:
            raise ControllerError(f"not a Field Box image: {exc.detail}") from None
        if info.project != fr.PROJECT_NAME or info.version != version:
            raise ControllerError(f"the image says {info.project} {info.version}, the release {version}")
        if info.variant not in self.variants:
            raise ControllerError(f"the image is a '{info.variant}' build; this controller takes "
                                  f"{', '.join(repr(v) for v in self.variants)} images ([firmware] variants)")
        with self._lock:
            entries = self._entries()
            if any(e["sha256"] == sha for e in entries):
                raise Conflict("this release is already here")
            if len(entries) >= MAX_RELEASES:
                raise Conflict(f"at most {MAX_RELEASES} releases are kept: delete one first")
            entry = {"platform": platform, "version": version, "size": len(image), "sha256": sha,
                     "signature": signature, "variant": info.variant, "board": info.board,
                     "uploaded_at": round(self.clock(), 3)}
            _write(self.dir / f"{sha}.bin", image)
            _write(self.dir / f"{sha}.json", json.dumps(entry, sort_keys=True).encode("utf-8"))
            log.warning("firmware release %s %s (%s, %s) uploaded, signed by key %s", platform, version, sha[:16],
                        info.board, self._signer(entry))
            return self._public(entry)

    def remove(self, release_id: str) -> None:
        with self._lock:
            e = self._find(release_id)
            for suffix in (".bin", ".json"):
                (self.dir / f"{e['sha256']}{suffix}").unlink(missing_ok=True)
            log.warning("firmware release %s %s (%s) deleted", e["platform"], e["version"], release_id)

    def _verified(self, release_id: str) -> dict[str, Any]:
        e = self._find(release_id)
        if self._signer(e) is None:
            raise NotFound("no such firmware release")  # its key was withdrawn: not offered any more
        return e

    def release_text(self, release_id: str) -> bytes:
        """What a box fetches before the image: the manifest and the signature."""
        with self._lock:
            e = self._verified(release_id)
            return fr.release_text(e["platform"], e["version"], e["size"], e["sha256"], e["signature"])

    def image_path(self, release_id: str) -> Path:
        with self._lock:
            e = self._verified(release_id)
            return self.dir / f"{e['sha256']}.bin"

    # ---- updates --------------------------------------------------------------------------

    def _refresh(self) -> None:
        now = self.clock()
        for a in self.attempts.values():
            if a["state"] in ACTIVE and now - a["updated_at"] > self.timeout_s:
                a.update(state="timeout", updated_at=now)

    def updates(self) -> list[dict[str, Any]]:
        with self._lock:
            self._refresh()
            return [dict(a) for _, a in sorted(self.attempts.items())]

    def busy(self) -> Optional[str]:
        """Why the live game may not start now: an update on its way to a box."""
        with self._lock:
            self._refresh()
            nodes = sorted(n for n, a in self.attempts.items() if a["state"] in ACTIVE)
        if not nodes:
            return None
        return (f"firmware updates are on their way to box(es) {', '.join(map(str, nodes))}: wait for them, "
                "or cancel them (DELETE /api/v1/firmware/updates) before the game starts")

    def cancel(self) -> list[int]:
        """Stops tracking the updates on their way (a box that already installed reboots anyway)."""
        with self._lock:
            now = self.clock()
            nodes = [n for n, a in self.attempts.items() if a["state"] in ACTIVE]
            for n in nodes:
                self.attempts[n].update(state="cancelled", updated_at=now)
        if nodes:
            log.warning("firmware updates to boxes %s cancelled by the GM", nodes)
        return nodes

    def eligibility(self, release: dict[str, Any], node: dict[str, Any], retry: bool = False) -> Optional[str]:
        """Why this box cannot take this release now, from what its HELLO said; None: it can. With
        ``retry`` (the GM named the box), an update still ``sent`` is sent again at once: a box whose
        failure never reached the controller is not stuck for ``update_timeout_s`` (decision OT-9);
        a box already running an update ignores the second offer."""
        if node.get("platform") is None or not node.get("fw_version"):
            return "unknown"  # never heard: no HELLO yet
        if fr.platform_name(node["platform"]) != release["platform"]:
            return "wrong_platform"
        if node.get("tier") not in BOX_TIERS:
            return "wrong_tier"
        if fr.version_key(str(node["fw_version"])) is None:
            return "unknown_version"
        if fr.compare_versions(release["version"], str(node["fw_version"])) <= 0:
            return "not_newer"
        current = self.attempts.get(int(node["node_id"]))
        if current is not None and current["state"] in ACTIVE and not (retry and current["state"] == "sent"):
            return "in_progress"
        return None

    def install(self, release_id: str, nodes: Any) -> dict[str, Any]:
        """Sends CMD update to the given boxes (a list of node ids, or "all") of the live game."""
        c = self.controller
        if c.game is None:
            raise Conflict("no live game: join the boxes to a game first (updates go only before it starts)")
        if c.game["state"] != "ready":
            raise Conflict(f"game {c.game['id']} is {c.game['state']}: firmware updates only before a game starts, "
                           "never during one")
        if c.ca_sha256 is None or not c.link_urls:
            raise Conflict("this controller does not serve HTTPS ([api] tls_port): boxes fetch updates only over "
                           "HTTPS pinned to the field CA")
        with self._lock:
            e = self._verified(release_id)
            self._refresh()
        known = {int(n["node_id"]): n for n in c.nodes() if n.get("node_id") is not None}
        if nodes == "all":
            targets = sorted(known)
        elif isinstance(nodes, list) and nodes and all(isinstance(n, int) and not isinstance(n, bool) for n in nodes):
            targets = sorted(set(nodes))
        else:
            raise ControllerError('nodes: a list of node ids, or "all"')
        params = {"id": e["sha256"][:16], "version": e["version"]}
        results = []
        for node_id in targets:
            node = known.get(node_id)
            with self._lock:
                why = "not_in_game" if node is None else self.eligibility(e, node, retry=nodes != "all")
            if why is None:
                try:
                    seq = c.send_update(node_id, params)
                except Unavailable:
                    why = "radio"
                except Conflict as exc:
                    raise Conflict(str(exc)) from None
                else:
                    with self._lock:
                        now = self.clock()
                        self.attempts[node_id] = {
                            "node_id": node_id, "game": c.game["id"] if c.game else None, "release": params["id"],
                            "version": e["version"], "from_version": str(node["fw_version"]), "state": "sent",
                            "reason": None, "seq": seq, "sent_at": now, "updated_at": now}
                    log.warning("firmware update to %s sent to box %d (running %s)", e["version"], node_id,
                                node["fw_version"])
            results.append({"node_id": node_id, "result": "sent" if why is None else why})
        if nodes != "all" and len(targets) == 1 and results[0]["result"] != "sent":
            raise Conflict(f"box {targets[0]}: {results[0]['result']}")
        self._emit()
        return {"release": self._public(e), "results": results}

    def report(self, body: bytes, mac: Any) -> dict[str, Any]:
        """A box's report on its update, authenticated with the live game's key."""
        try:
            r = fr.parse_report(body)
        except fr.ReleaseError:
            raise ControllerError("not a firmware report") from None
        c = self.controller
        try:
            key = c.game_key(r["game"])
        except ControllerError:
            raise Conflict("not this controller's live game") from None
        if not isinstance(mac, str) or not re.fullmatch(r"[0-9a-f]{64}", mac) or \
                not hmac.compare_digest(fr.report_mac(key, body), mac):
            raise ControllerError("the report's MAC does not verify")
        with self._lock:
            a = self.attempts.get(r["node"])
            now = self.clock()
            if a is None or a["release"] != r["release"] or a["state"] not in ACTIVE + ("timeout",):
                log.warning("box %d reported %s for release %s, which was not sent to it", r["node"], r["result"],
                            r["release"])
                return {"accepted": False}
            if r["result"] == "installed":
                a.update(state="installed", reason=None, updated_at=now)
            else:
                a.update(state="failed", reason=r["result"], updated_at=now)
        log.warning("box %d: firmware update to %s %s", r["node"], a["version"], r["result"])
        self._emit()
        return {"accepted": True}

    def on_failed_over_radio(self, ev: dict[str, Any]) -> None:
        """node.update_failed: a box says over LoRa (sealed with the game key, like all its events) that
        an update failed where it could not report over HTTPS: no Wi-Fi, the controller unreachable,
        refused before any network (decision OT-8). Only for the update sent to that box."""
        data = ev.get("data") or {}
        node_id, release, reason = ev.get("node"), data.get("release"), data.get("reason")
        if not isinstance(node_id, int) or not isinstance(reason, str) or not REASON.fullmatch(reason):
            return
        with self._lock:
            a = self.attempts.get(node_id)
            if a is None or a["release"] != release or a["state"] not in ("sent", "timeout"):
                log.warning("box %d said over the radio that release %s failed (%s): not an update sent to it",
                            node_id, release, reason)
                return
            a.update(state="failed", reason=reason, updated_at=self.clock())
        log.warning("box %d: firmware update to %s failed: %s (said over the radio)", node_id, a["version"], reason)
        self._emit()

    def on_message(self, msg: dict[str, Any]) -> None:
        """A box's HELLO shows what it runs: the update's version (done) or, once it said installed,
        the old one (the new image did not confirm itself). A box's node.update_failed: failed."""
        if msg.get("type") == "event" and isinstance(msg.get("event"), dict) and \
                msg["event"].get("type") == UPDATE_FAILED:
            self.on_failed_over_radio(msg["event"])
            return
        if msg.get("type") != "node" or not isinstance(msg.get("node"), dict):
            return
        node = msg["node"]
        fw = node.get("fw_version")
        if not isinstance(fw, str) or node.get("node_id") is None:
            return
        changed = False
        with self._lock:
            a = self.attempts.get(int(node["node_id"]))
            if a is None or a["state"] not in ACTIVE + ("timeout",):
                return
            now = self.clock()
            if fw == a["version"]:
                a.update(state="done", reason=None, updated_at=now)
                changed = True
            elif a["state"] == "installed" and msg.get("kind") == "hello" and fw == a["from_version"]:
                a.update(state="rolled_back", reason="self_test", updated_at=now)
                changed = True
        if changed:
            log.warning("box %s: firmware update to %s %s", node["node_id"], a["version"], a["state"])
            self._emit()

    def status(self) -> dict[str, Any]:
        c = self.controller
        return {"keys": [fr.key_id(k) for k in self.keys], "https": c.ca_sha256 is not None and bool(c.link_urls),
                "slot_size": SLOT_SIZE, "max_releases": MAX_RELEASES, "releases": self.releases(),
                "updates": self.updates()}

    def _emit(self) -> None:
        self.controller._emit({"type": "firmware", "updates": self.updates()})


def _write(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def firmware_dir(db_path: str, configured: str = "") -> Path:
    """[firmware] dir, or "firmware" next to the controller's database."""
    if configured:
        return Path(configured)
    return Path(os.path.dirname(os.path.abspath(db_path))) / "firmware"
