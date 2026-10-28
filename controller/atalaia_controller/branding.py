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

With ``[sync] branding = "site"`` (plan phase 18; P4R19) the field's
branding and its saved teams come from the site server: the sync client
fetches them and ``apply_site`` makes this controller's match, keeping the
team presets it made in a setting (``branding.site_presets``, site team id
to preset id). Then the console cannot change the field's branding nor those
presets (409); presets made here stay the GM's.

Images are stored once, by the SHA-256 of their checked bytes, which is
also their ETag. A logo or wallpaper that is replaced is deleted at once
when nothing else uses it; a crest that no game and no team preset refers
to is deleted a day after its upload (purge, from the controller's tick).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from typing import TYPE_CHECKING, Any, Optional

from . import box_logo, images
from .checkin import RateLimit
from .engine import Conflict, ControllerError, NotFound, display_name

if TYPE_CHECKING:
    from .engine import Controller

log = logging.getLogger("atalaia.branding")

ACCENT_RE = re.compile(r"#[0-9a-fA-F]{6}")
SLOTS = {"logo": images.LOGO, "wallpaper": images.WALLPAPER}
SETTING = "branding.field"
SITE_PRESETS = "branding.site_presets"  # {site team id: team preset id} (plan phase 18)
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
        self._box_logo: Optional[tuple[str, bytes]] = None
        controller.branding = self
        sync = getattr(controller, "sync", None)
        if sync is not None:
            sync.branding = self  # the site server's branding, with [sync] branding = "site"

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
        if self.from_site():
            out["source"] = "site"  # PKE-4: the console says so and does not offer to edit it (absent when local)
        digest = hashlib.sha256(json.dumps(out, sort_keys=True).encode()).hexdigest()[:32]
        out["etag"] = etag(digest)
        return out

    def _changed(self) -> dict[str, Any]:
        view = self.view()
        self.ctrl._emit({"type": "branding", "branding": view})
        return view

    def from_site(self) -> bool:
        """The field's branding and saved teams are the site server's (``[sync] branding = "site"``)."""
        return bool(getattr(self.cfg, "sync_enabled", False)) and getattr(self.cfg, "sync_branding", "") == "site"

    def _local_only(self) -> None:
        if self.from_site():
            raise Conflict("the field's branding comes from the site server ([sync] branding = \"site\"): "
                           "change it there")

    def set_field(self, spec: dict[str, Any]) -> dict[str, Any]:
        """PUT /api/v1/field/branding {"field_name"?, "accent"?}: the GM's settings."""
        self._local_only()
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
        self._local_only()
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
        self._local_only()
        saved = self._saved()
        old = saved.pop(slot, None)
        self._save(saved)
        if old:
            self._drop_if_unused(old)
        return self._changed()

    def image(self, slot: str) -> Optional[dict[str, Any]]:
        image_id = self._saved().get(slot)
        return self.store.image(image_id) if image_id else None

    def box_logo(self) -> Optional[tuple[str, bytes]]:
        """The field's logo as a Field Box draws it (box_logo.py, decision PKG-1): the source image's id and the
        box-ready bytes, or None when there is no logo or it is not a PNG the controller can convert. The result
        is kept by the image's id, so each logo is converted once."""
        img = self.image("logo")
        if img is None or img["content_type"] != "image/png":
            return None
        if self._box_logo is None or self._box_logo[0] != img["id"]:
            try:
                self._box_logo = (img["id"], box_logo.convert(img["data"]))
            except box_logo.BoxLogoError:
                self._box_logo = (img["id"], b"")
        return self._box_logo if self._box_logo[1] else None

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
            self._not_site_preset(preset_id)
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
        self._not_site_preset(preset_id)
        self.store.delete_team_preset(preset_id)
        if current["crest_id"]:
            self._drop_if_unused(current["crest_id"], grace=True)
        return {"deleted": preset_id}

    def _not_site_preset(self, preset_id: int) -> None:
        if self.from_site() and preset_id in self._site_presets().values():
            raise Conflict("this team preset comes from the site server's saved teams: change it there")

    @staticmethod
    def preset_view(p: dict[str, Any], site: bool = False) -> dict[str, Any]:
        out = dict(p)
        out["crest_url"] = f"/api/v1/crests/{p['crest_id']}" if p.get("crest_id") else None
        if site:
            out["source"] = "site"
        return out

    def team_presets(self) -> list[dict[str, Any]]:
        site = set(self._site_presets().values()) if self.from_site() else set()
        return [self.preset_view(p, p["id"] in site) for p in self.store.team_presets()]

    # --- from the site server (plan phase 18) ------------------------------------------

    def _site_presets(self) -> dict[str, int]:
        try:
            saved = json.loads(self.store.get_setting(SITE_PRESETS) or "{}")
        except ValueError:
            saved = {}
        if not isinstance(saved, dict):
            return {}
        return {k: v for k, v in saved.items() if isinstance(k, str) and isinstance(v, int)}

    def apply_site(self, answer: dict[str, Any], unavailable: Optional[set[str]] = None) -> dict[str, int]:
        """Makes the field's branding and the site's team presets match the site server's answer (checked by
        ``sync_format.check_field``; its images already in the store, except those in ``unavailable``, which
        keep what was there). A preset made here with a site team's name becomes that team's. Returns the counts
        of what changed; the console hears of a change as for a GM's edit."""
        unavailable = unavailable or set()
        out = {"field": 0, "added": 0, "updated": 0, "removed": 0, "conflicts": 0}
        field = answer["field"]
        saved = self._saved()
        before = dict(saved)
        replaced: list[str] = []  # a logo or wallpaper: deleted at once when unused (BR8)
        dropped: list[str] = []   # crests: a day after their upload, as the console's
        for slot in SLOTS:
            ref = field[slot]
            want = ref["sha256"] if ref is not None else None
            if want is not None and (want in unavailable or self.store.image(want, with_data=False) is None):
                continue  # not fetched yet: the next cycle tries again
            if saved.get(slot) != want:
                if saved.get(slot):
                    replaced.append(saved[slot])
                if want is None:
                    saved.pop(slot, None)
                else:
                    saved[slot] = want
        if field["accent"] is None:
            saved.pop("accent", None)
        else:
            saved["accent"] = field["accent"]
        if saved != before:
            self._save(saved)
            out["field"] += 1
        name = field["field_name"]
        if name is not None and name != self.field_name():
            try:
                if self.ctrl.checkin is not None:
                    self.ctrl.checkin.set_poster({"field_name": name})
                else:
                    self.store.set_setting(NAME_SETTING, name)
                out["field"] += 1
            except ControllerError as exc:
                log.warning("the site server's field name is not used: %s", exc)
        out.update(self._apply_site_teams(answer["teams"], unavailable, dropped))
        for image_id in replaced:
            self._drop_if_unused(image_id)
        for image_id in dropped:
            self._drop_if_unused(image_id, grace=True)
        if out["field"] or out["added"] or out["updated"] or out["removed"]:
            self._changed()
        return out

    def _apply_site_teams(self, teams: list[dict[str, Any]], unavailable: set[str],
                          dropped: list[str]) -> dict[str, int]:
        out = {"added": 0, "updated": 0, "removed": 0, "conflicts": 0}
        mapping = self._site_presets()
        by_name = {p["name"]: p for p in self.store.team_presets()}
        kept: dict[str, int] = {}
        for team in teams:
            crest = team["crest"]["sha256"] if team["crest"] is not None else None
            current = self.store.team_preset(mapping[team["team_id"]]) if team["team_id"] in mapping else None
            if current is None:
                current = by_name.get(team["name"])  # one made here with that name becomes the site's
            if crest is not None and (crest in unavailable or self.store.image(crest, with_data=False) is None):
                crest = current["crest_id"] if current is not None else None
            if current is not None and (current["name"], current["colour"], current["crest_id"]) == \
                    (team["name"], team["colour"], crest):
                kept[team["team_id"]] = current["id"]
                continue
            try:
                row = self.store.save_team_preset(team["name"], team["colour"], crest,
                                                  current["id"] if current is not None else None)
            except ValueError:
                out["conflicts"] += 1  # another preset already has the name: it is left alone
                log.warning("site team %s: a team preset named %r already exists", team["team_id"], team["name"])
                if current is not None:
                    kept[team["team_id"]] = current["id"]
                continue
            kept[team["team_id"]] = row["id"]
            if current is None:
                out["added"] += 1
            else:
                out["updated"] += 1
                if current["crest_id"] and current["crest_id"] != crest:
                    dropped.append(current["crest_id"])
        for team_id, preset_id in mapping.items():
            if team_id in kept or preset_id in kept.values():
                continue
            gone = self.store.team_preset(preset_id)
            if gone is not None:
                self.store.delete_team_preset(preset_id)
                out["removed"] += 1
                if gone["crest_id"]:
                    dropped.append(gone["crest_id"])
        if kept != mapping:
            self.store.set_setting(SITE_PRESETS, json.dumps(kept, sort_keys=True))
        return out

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
