# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The field's scenario library and game presets (ADR-P4-6 as amended, P4R7, P4R9; plan phase 20).

A scenario is checked here as the controller checks it: the shared compiler's validator
(``atalaia_controller.scenarios``, plain Python, P4R16), then the compiled ``field.lua`` loaded in the C
core (``check_package``, the controller's own ``modes.check_scripts``). The image builds the core in a build
stage (``ATALAIA_CORE_LIB``); without it a manifest can be checked by the validator alone but not saved
(``core_unavailable``), as the controller refuses an install without its core. Every save of a manifest is a
new revision, kept as it was typed; the current revision of each scenario that is not archived, and the
field's presets, are what ``GET /api/v1/sync/presets`` gives the field's controllers, the primary and every
standby (decision S20-1). The controller compiles and checks the manifest again when it installs it, and
stays the authority (P4R9).
"""

from __future__ import annotations

import hashlib
import logging
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from atalaia_controller import sync_format
from atalaia_controller.scenarios import ManifestError, Problem, check_package, compile_scenario, load, validate
from atalaia_controller.scenarios.validator import errors
from atalaia_sim.mode import ModeError
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..history_models import FieldPreset, FieldScenario, FieldScenarioRevision

log = logging.getLogger("atalaia.server.library")

MAX_SCENARIOS = sync_format.MAX_LIBRARY  # live scenarios of a field: what one presets answer carries
MAX_PRESETS = sync_format.MAX_LIBRARY
REVISIONS_KEPT = 50  # per scenario: older revisions go when a new one is saved


class LibraryProblem(Exception):
    def __init__(self, status: int, detail: str, problems: Optional[list[dict[str, str]]] = None) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.problems = problems

    def body(self) -> dict[str, Any]:
        out: dict[str, Any] = {"detail": self.detail}
        if self.problems is not None:
            out["problems"] = self.problems
        return out


@dataclass
class CoreHolder:
    """The core library, loaded once on first use; its calls are serialised (one Lua state at a time)."""

    path: Optional[str] = None
    core: Any = None
    error: Optional[str] = None
    tried: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)

    def get(self) -> Any:
        if not self.tried:
            self.tried = True
            try:
                from atalaia_sim.core import Core, find_library  # noqa: PLC0415 (ctypes: only when needed)

                self.core = Core(self.path or find_library())
            except (FileNotFoundError, OSError) as exc:
                self.error = str(exc)
                log.warning("the core library does not load (%s): scenarios can be checked but not saved", exc)
        return self.core


@dataclass
class Checked:
    manifest: Optional[dict[str, Any]]
    problems: list[Problem]
    checked_in_core: bool

    @property
    def ok(self) -> bool:
        return self.manifest is not None and not errors(self.problems)


def check(holder: CoreHolder, text: str) -> Checked:
    """Every problem of a manifest: the validator's, then (without errors) the compiled field.lua's load in
    the core, as the controller's install does (P4R9)."""
    try:
        manifest = load(text)
    except ManifestError as exc:
        return Checked(None, [Problem("", "bad_manifest", str(exc))], False)
    problems = validate(manifest)
    core = holder.get()
    if errors(problems) or core is None:
        return Checked(manifest, problems, False)
    try:
        package = compile_scenario(manifest)
        with holder.lock:
            check_package(core, package)
    except ModeError as exc:
        problems.append(Problem("", "lua_does_not_load", str(exc)))
    return Checked(manifest, problems, True)


def summary(manifest: Optional[dict[str, Any]]) -> dict[str, Any]:
    manifest = manifest or {}
    objectives = manifest.get("objectives") if isinstance(manifest.get("objectives"), list) else []
    nodes = manifest.get("nodes") if isinstance(manifest.get("nodes"), dict) else {}
    return {"scenario_id": manifest.get("id") if isinstance(manifest.get("id"), str) else None,
            "name": manifest.get("name") if isinstance(manifest.get("name"), str) else None,
            "nodes": [{"name": str(n), "role": s.get("role"), "player": bool(s.get("player"))}
                      for n, s in nodes.items() if isinstance(s, dict)],
            "objectives": [{"id": o.get("id"), "type": o.get("type"), "name": o.get("name")}
                           for o in objectives if isinstance(o, dict)]}


def manifest_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if value is not None else None


async def current(db: AsyncSession, scenario: FieldScenario) -> FieldScenarioRevision:
    row = await db.scalar(select(FieldScenarioRevision).where(FieldScenarioRevision.scenario == scenario.id,
                                                              FieldScenarioRevision.revision == scenario.revision))
    assert row is not None  # every scenario row is made with its first revision
    return row


async def find(db: AsyncSession, field_id: uuid.UUID, scenario_id: str) -> Optional[FieldScenario]:
    return await db.scalar(select(FieldScenario).where(FieldScenario.field_id == field_id,
                                                       FieldScenario.scenario_id == scenario_id))


def scenario_json(s: FieldScenario, rev: FieldScenarioRevision) -> dict[str, Any]:
    return {"scenario_id": s.scenario_id, "revision": s.revision, "version": rev.version, "name": rev.name,
            "sha256": rev.manifest_sha256, "archived": s.archived_at is not None, "created_at": _iso(s.created_at),
            "updated_at": _iso(rev.created_at)}


async def listing(db: AsyncSession, field_id: uuid.UUID, archived: bool = False) -> list[dict[str, Any]]:
    stmt = (select(FieldScenario, FieldScenarioRevision)
            .join(FieldScenarioRevision, (FieldScenarioRevision.scenario == FieldScenario.id)
                  & (FieldScenarioRevision.revision == FieldScenario.revision))
            .where(FieldScenario.field_id == field_id).order_by(FieldScenario.scenario_id))
    if not archived:
        stmt = stmt.where(FieldScenario.archived_at.is_(None))
    return [scenario_json(s, rev) for s, rev in await db.execute(stmt)]


async def save(db: AsyncSession, holder: CoreHolder, field_id: uuid.UUID, text: str) -> tuple[dict[str, Any], str]:
    """Checks and stores a manifest as the scenario's next revision (or its first). Returns the scenario and
    what happened: ``created``, ``revised``, ``unchanged`` (the same text as the current revision) or
    ``restored`` (an archived scenario saved again). The caller commits."""
    checked = check(holder, text)
    if not checked.ok:
        raise LibraryProblem(400, "scenario_refused", [p.to_dict() for p in checked.problems])
    if not checked.checked_in_core:
        raise LibraryProblem(503, "core_unavailable")
    manifest = checked.manifest
    assert manifest is not None
    scenario_id = manifest["id"]
    sha = manifest_sha256(text)
    warnings = [p.to_dict() for p in checked.problems]
    version, name = str(manifest["version"]), str(manifest["name"])[:128]
    # A scenario's row is locked while its next revision is made; two first saves at once are settled by the
    # unique (field, scenario id) key (the loser gets 409, api/scenarios.py).
    scenario = await db.scalar(select(FieldScenario).where(FieldScenario.field_id == field_id,
                                                           FieldScenario.scenario_id == scenario_id)
                               .with_for_update())
    if scenario is None:
        live = await db.scalar(select(func.count()).select_from(FieldScenario).where(
            FieldScenario.field_id == field_id, FieldScenario.archived_at.is_(None)))
        if (live or 0) >= MAX_SCENARIOS:
            raise LibraryProblem(409, "too_many_scenarios")
        scenario = FieldScenario(field_id=field_id, scenario_id=scenario_id, revision=1)
        db.add(scenario)
        await db.flush()
        outcome = "created"
    else:
        rev = await current(db, scenario)
        if rev.manifest_sha256 == sha and scenario.archived_at is None:
            return scenario_json(scenario, rev), "unchanged"
        outcome = "restored" if scenario.archived_at is not None else "revised"
        if scenario.archived_at is not None:
            live = await db.scalar(select(func.count()).select_from(FieldScenario).where(
                FieldScenario.field_id == field_id, FieldScenario.archived_at.is_(None)))
            if (live or 0) >= MAX_SCENARIOS:
                raise LibraryProblem(409, "too_many_scenarios")
        scenario.revision += 1
        scenario.archived_at = None
    rev = FieldScenarioRevision(scenario=scenario.id, revision=scenario.revision, version=version, name=name,
                                manifest=text, manifest_sha256=sha, warnings=warnings)
    db.add(rev)
    await db.flush()
    await db.execute(delete(FieldScenarioRevision).where(
        FieldScenarioRevision.scenario == scenario.id,
        FieldScenarioRevision.revision <= scenario.revision - REVISIONS_KEPT))
    await db.refresh(scenario)
    await db.refresh(rev)
    return {**scenario_json(scenario, rev), "warnings": warnings}, outcome


async def revisions(db: AsyncSession, scenario: FieldScenario) -> list[dict[str, Any]]:
    rows = await db.scalars(select(FieldScenarioRevision).where(FieldScenarioRevision.scenario == scenario.id)
                            .order_by(FieldScenarioRevision.revision.desc()))
    return [{"revision": r.revision, "version": r.version, "name": r.name, "sha256": r.manifest_sha256,
             "warnings": r.warnings, "created_at": _iso(r.created_at)} for r in rows]


def package_files(text: str) -> Optional[dict[str, str]]:
    """The package a manifest compiles to (mode.yaml, field.lua), for staff to read; None if it no longer
    compiles (a compiler of a newer server may refuse what an older one saved)."""
    try:
        return dict(compile_scenario(load(text)).files)
    except Exception:  # noqa: BLE001  (any refusal: the manifest is still shown)
        return None


# --- presets --------------------------------------------------------------------------------


def check_preset(body: Any) -> dict[str, Any]:
    """A preset as the staff send it: ``{name, mode_id, params}`` with the limits of the sync answer. The mode
    and its parameters are checked by the controller, which knows its modes (decision S20-4)."""
    if not isinstance(body, dict):
        raise LibraryProblem(400, "invalid_body")
    unknown = set(body) - {"name", "mode_id", "params"}
    if unknown:
        raise LibraryProblem(400, "unknown_field")
    probe = {"preset_id": "00000000-0000-4000-8000-000000000000", "name": body.get("name"),
             "mode_id": body.get("mode_id"), "params": body.get("params", {})}
    try:
        sync_format.check_presets({"sync_version": sync_format.SYNC_VERSION, "scenarios": [], "presets": [probe]})
    except sync_format.SyncFormatError as exc:
        raise LibraryProblem(400, f"invalid_{exc.path.split('.')[-1]}") from None
    return {"name": probe["name"], "mode_id": probe["mode_id"], "params": probe["params"]}


def preset_json(p: FieldPreset) -> dict[str, Any]:
    return {"id": str(p.id), "name": p.name, "mode_id": p.mode_id, "params": p.params,
            "created_at": _iso(p.created_at), "updated_at": _iso(p.updated_at)}


async def presets(db: AsyncSession, field_id: uuid.UUID) -> list[FieldPreset]:
    return list(await db.scalars(select(FieldPreset).where(FieldPreset.field_id == field_id)
                                 .order_by(FieldPreset.name)))


# --- what the controllers pull -----------------------------------------------------------------


async def sync_answer(db: AsyncSession, field_id: uuid.UUID) -> dict[str, Any]:
    """``GET /api/v1/sync/presets``: the live scenarios by id, revision and SHA-256, and the presets whole."""
    scenarios = [{k: s[k] for k in ("scenario_id", "revision", "version", "name", "sha256")}
                 for s in await listing(db, field_id)]
    answer = {"sync_version": sync_format.SYNC_VERSION, "scenarios": scenarios,
              "presets": [{"preset_id": str(p.id), "name": p.name, "mode_id": p.mode_id, "params": p.params}
                          for p in await presets(db, field_id)]}
    return sync_format.check_presets(answer)


async def sync_scenario(db: AsyncSession, field_id: uuid.UUID, scenario_id: str) -> Optional[dict[str, Any]]:
    """``GET /api/v1/sync/scenarios/{id}``: the current manifest of a live scenario of the field, or None."""
    scenario = await find(db, field_id, scenario_id)
    if scenario is None or scenario.archived_at is not None:
        return None
    rev = await current(db, scenario)
    return sync_format.check_scenario({"sync_version": sync_format.SYNC_VERSION, "scenario_id": scenario.scenario_id,
                                       "revision": scenario.revision, "sha256": rev.manifest_sha256,
                                       "manifest": rev.manifest})
