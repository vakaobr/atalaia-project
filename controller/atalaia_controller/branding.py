# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Field and team branding (decisions BR1-BR24): how a field or club running its own
controller shows who it is.

The field's branding is its name (the same one the check-in poster prints),
a logo, an optional wallpaper and an accent colour, set in the GM console's
settings with the GM token and kept in the store, so it survives restarts.
Teams get a display name and a crest per game next to their colour (the
colour stays the team's name: box LEDs and buttons need it); team presets
keep a club's name and crest for the next game.

Everything here is public to the field's network: no token is needed to
read it (players fetch it before or right after checking in), and none of
it is personal data. Uploads are PNG, JPEG or WebP only, checked and
stripped of metadata by images.py; the uploader is responsible for having
the rights to them (the console says so).

Images are stored once, by the SHA-256 of their checked bytes, which is
also their ETag. A logo or wallpaper that is replaced is deleted at once
when nothing else uses it; a crest that no game and no team preset refers
to is deleted a day after its upload (purge, from the controller's tick).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import TYPE_CHECKING, Any, Optional

from . import images
from .checkin import RateLimit
from .engine import Conflict, ControllerError, NotFound, display_name

if TYPE_CHECKING:
    from .engine import Controller

ACCENT_RE = re.compile(r"#[0-9a-fA-F]{6}")
SLOTS = {"logo": images.LOGO, "wallpaper": images.WALLPAPER}
SETTING = "branding.field"
NAME_SETTING = "branding.field_name"  # only without check-in (the poster keeps the name otherwise)
FIELD_NAME_MAX = 48
CREST_MAX = 500           # crests kept at once (decision BR8)
CREST_GRACE_S = 24 * 3600  # an unused crest's life after its upload
PURGE_EVERY_S = 600
TEAM_NAME_MAX = 23         # the colour a preset usually plays: a team name as the boxes know it


def etag(text: str) -> str:
    return f'"{text}"'


class Branding:
    def __init__(self, controller: "Controller") -> None:
        self.ctrl = controller
        self.cfg = controller.cfg
        self.store = controller.store
        self.rate = RateLimit(240)  # public reads per address and minute
        self._last_purge = 0.0
        controller.branding = self

    # --- the field --------------------------------------------------------------

    def _saved(self) -> dict[str, Any]:
        raw = self.store.get_setting(SETTING)
        try:
            saved = json.loads(raw) if raw else {}
        except ValueError:
            saved = {}
        return saved if isinstance(saved, dict) else {}

    def _save(self, saved: dict[str, Any]) -> None:
        self.store.set_setting(SETTING, json.dumps(saved, sort_keys=True))

    def field_name(self) -> str:
        """One name for the field: the poster's (decision BR4)."""
        if self.ctrl.checkin is not None:
            return self.ctrl.checkin.poster_fields()["field_name"]
        return self.store.get_setting(NAME_SETTING) or self.cfg.field_name

    def _image_ref(self, slot: str, image_id: Optional[str]) -> Optional[dict[str, Any]]:
        img = self.store.image(image_id, with_data=False) if image_id else None
        if img is None:
            return None
        return {"url": f"/api/v1/field/branding/{slot}", "id": img["id"], "etag": etag(img["id"]),
                "content_type": img["content_type"], "width": img["width"], "height": img["height"],
                "bytes": img["bytes"]}

    def view(self) -> dict[str, Any]:
        """GET /api/v1/field/branding: no token, no personal data."""
        saved = self._saved()
        out: dict[str, Any] = {
            "version": 1,
            "field_id": self.cfg.field_id,
            "field_name": self.field_name(),
            "accent": saved.get("accent"),
            "logo": self._image_ref("logo", saved.get("logo")),
            "wallpaper": self._image_ref("wallpaper", saved.get("wallpaper")),
        }
        digest = hashlib.sha256(json.dumps(out, sort_keys=True).encode()).hexdigest()[:32]
        out["etag"] = etag(digest)
        return out

    def _changed(self) -> dict[str, Any]:
        view = self.view()
        self.ctrl._emit({"type": "branding", "branding": view})
        return view

    def set_field(self, spec: dict[str, Any]) -> dict[str, Any]:
        """PUT /api/v1/field/branding {"field_name"?, "accent"?}: the GM's settings."""
        unknown = set(spec) - {"field_name", "accent"}
        if unknown:
            raise ControllerError(f"unknown branding fields {sorted(unknown)} (images have their own endpoints)")
        saved = self._saved()
        if "accent" in spec:
            accent = spec["accent"]
            if accent in (None, ""):
                saved.pop("accent", None)
            elif not isinstance(accent, str) or not ACCENT_RE.fullmatch(accent):
                raise ControllerError("accent: a colour as #rrggbb, or null for the default")
            else:
                saved["accent"] = accent.lower()
        if "field_name" in spec:
            name = spec["field_name"]
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= FIELD_NAME_MAX \
                    or any(ord(c) < 0x20 or 0x7F <= ord(c) <= 0x9F for c in name):
                raise ControllerError(f"field_name: 1-{FIELD_NAME_MAX} characters without control characters")
            if self.ctrl.checkin is not None:
                self.ctrl.checkin.set_poster({"field_name": name.strip()})  # the poster's checks too
            else:
                self.store.set_setting(NAME_SETTING, name.strip())
        self._save(saved)
        return self._changed()

    def put_image(self, slot: str, data: bytes, content_type: str) -> dict[str, Any]:
        """PUT /api/v1/field/branding/{logo|wallpaper}: raw PNG, JPEG or WebP (images.check)."""
        checked = images.check(data, content_type, SLOTS[slot])
        image_id = hashlib.sha256(checked.data).hexdigest()
        self.store.put_image(image_id, slot, checked.content_type, checked.width, checked.height, checked.data)
        saved = self._saved()
        old = saved.get(slot)
        saved[slot] = image_id
        self._save(saved)
        if old and old != image_id:
            self._drop_if_unused(old)
        return self._changed()

    def delete_image(self, slot: str) -> dict[str, Any]:
        saved = self._saved()
        old = saved.pop(slot, None)
        self._save(saved)
        if old:
            self._drop_if_unused(old)
        return self._changed()

    def image(self, slot: str) -> Optional[dict[str, Any]]:
        image_id = self._saved().get(slot)
        return self.store.image(image_id) if image_id else None

    # --- crests and team presets ---------------------------------------------

    def add_crest(self, data: bytes, content_type: str) -> tuple[dict[str, Any], bool]:
        """POST /api/v1/crests: a team crest, stored once by its checked bytes' SHA-256."""
        checked = images.check(data, content_type, images.CREST)
        crest_id = hashlib.sha256(checked.data).hexdigest()
        if self.store.image(crest_id, with_data=False) is None \
                and len(self.store.image_ids("crest")) >= CREST_MAX:
            self.purge(force=True)
            if len(self.store.image_ids("crest")) >= CREST_MAX:
                raise Conflict(f"the controller keeps at most {CREST_MAX} crests; delete team presets first")
        created = self.store.put_image(crest_id, "crest", checked.content_type, checked.width, checked.height,
                                       checked.data)
        return self.crest_ref(crest_id), created

    def crest_ref(self, crest_id: str) -> dict[str, Any]:
        img = self.store.image(crest_id, with_data=False)
        if img is None:
            raise NotFound(f"no crest {crest_id}")
        return {"crest_id": crest_id, "url": f"/api/v1/crests/{crest_id}", "etag": etag(crest_id),
                "content_type": img["content_type"], "width": img["width"], "height": img["height"],
                "bytes": img["bytes"]}

    def crest(self, crest_id: str) -> Optional[dict[str, Any]]:
        if not re.fullmatch(r"[0-9a-f]{64}", crest_id):
            return None
        return self.store.image(crest_id)

    def _preset_spec(self, spec: dict[str, Any], current: Optional[dict[str, Any]]) -> tuple[str, Any, Any]:
        unknown = set(spec) - {"name", "colour", "crest_id"}
        if unknown:
            raise ControllerError(f"unknown team preset fields {sorted(unknown)}")
        name = current["name"] if current else None
        colour = current["colour"] if current else None
        crest = current["crest_id"] if current else None
        if "name" in spec or current is None:
            name = display_name(spec.get("name"), "name")
            if name is None:
                raise ControllerError("name: the team's display name, 1-32 characters")
        if "colour" in spec:
            colour = spec["colour"]
            if colour in (None, ""):
                colour = None
            elif not isinstance(colour, str) or not 0 < len(colour.encode()) <= TEAM_NAME_MAX \
                    or any(ord(c) < 0x21 for c in colour):
                raise ControllerError(f"colour: a team name as the game uses it (red, blue...), "
                                      f"1-{TEAM_NAME_MAX} bytes")
        if "crest_id" in spec:
            crest = spec["crest_id"]
            if crest is not None and (not isinstance(crest, str) or self.crest(crest) is None):
                raise ControllerError("crest_id: an uploaded crest's id (POST /api/v1/crests)")
        return name, colour, crest

    def save_team_preset(self, spec: dict[str, Any], preset_id: Optional[int] = None) -> dict[str, Any]:
        current = None
        if preset_id is not None:
            current = self.store.team_preset(preset_id)
            if current is None:
                raise NotFound(f"no team preset {preset_id}")
        name, colour, crest = self._preset_spec(spec, current)
        try:
            out = self.store.save_team_preset(name, colour, crest, preset_id)
        except ValueError as exc:
            raise Conflict(str(exc)) from None
        if current and current["crest_id"] and current["crest_id"] != crest:
            self._drop_if_unused(current["crest_id"], grace=True)
        return self.preset_view(out)

    def delete_team_preset(self, preset_id: int) -> dict[str, Any]:
        current = self.store.team_preset(preset_id)
        if current is None:
            raise NotFound(f"no team preset {preset_id}")
        self.store.delete_team_preset(preset_id)
        if current["crest_id"]:
            self._drop_if_unused(current["crest_id"], grace=True)
        return {"deleted": preset_id}

    @staticmethod
    def preset_view(p: dict[str, Any]) -> dict[str, Any]:
        out = dict(p)
        out["crest_url"] = f"/api/v1/crests/{p['crest_id']}" if p.get("crest_id") else None
        return out

    def team_presets(self) -> list[dict[str, Any]]:
        return [self.preset_view(p) for p in self.store.team_presets()]

    def game_teams(self, game_id: int) -> dict[str, Any]:
        """GET /api/v1/games/{id}/teams: each team's colour, display name and crest (no token: an Android
        prop, which has no read token, draws its buttons with them)."""
        game = self.store.game(game_id)
        if game is None:
            raise NotFound(f"no game {game_id}")
        info = game.get("team_info") or {}
        teams = []
        for team in game["teams"]:
            entry = info.get(team) or {}
            crest = entry.get("crest_id")
            teams.append({"team": team, "display_name": entry.get("display_name"), "crest_id": crest,
                          "crest_url": f"/api/v1/crests/{crest}" if crest else None})
        return {"game_id": game_id, "state": game["state"], "teams": teams}

    # --- clean-up ----------------------------------------------------------------

    def referenced(self) -> set[str]:
        saved = self._saved()
        out = {saved[s] for s in SLOTS if saved.get(s)}
        out |= {p["crest_id"] for p in self.store.team_presets() if p["crest_id"]}
        out |= self.store.team_info_crests()
        return out

    def _drop_if_unused(self, image_id: str, grace: bool = False) -> None:
        if image_id in self.referenced():
            return
        if grace:
            img = self.store.image(image_id, with_data=False)
            if img is not None and img["created_at"] > time.time() - CREST_GRACE_S:
                return  # a fresh upload may be about to go into a game or a preset
        self.store.delete_image(image_id)

    def purge(self, force: bool = False, now: Optional[float] = None) -> int:
        """Deletes images nothing refers to (crests a day after their upload); at most every 10 minutes."""
        now = time.time() if now is None else now
        if not force and now - self._last_purge < PURGE_EVERY_S:
            return 0
        self._last_purge = now
        used = self.referenced()
        gone = 0
        for img in self.store.image_ids():
            if img["id"] in used:
                continue
            if img["kind"] == "crest" and img["created_at"] > now - CREST_GRACE_S:
                continue
            gone += self.store.delete_image(img["id"])
        return gone
