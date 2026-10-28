# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The data export a field's administrator can download (S21-12: "an export a field's administrator can download").

    GET /api/v1/fields/{field_id}/export        the field's ``admin``, in a TOTP session (api/export.py)

A ZIP file (format ``atalaia-field-data``, version 1), built in one repeatable-read, read-only transaction so that
its tables agree with each other:

    manifest.json         format, version, time, the field (id, slug, name), the server's version and migration
                          revision, the mode (``hosted`` or ``single``), each dataset's file, row count, columns and
                          SHA-256, and the tables left out with the reason
    README.txt            what each file is, in English and Portuguese, and what is never in it
    data/<name>.jsonl     one dataset per file, one JSON object per line (UTF-8), the table's own column names;
                          timestamps are ISO 8601 with offset, ids are UUID strings, bytes are base64

This is **the field's own data** and not the operator's whole-schema export (``hosted export``, S21-8), which holds
every credential and is the processor's act on the controller's instruction. What is left out, always:

- credentials and secrets, whoever they belong to: password hashes, TOTP secrets and last steps, sessions and refresh
  tokens, API keys' hashes, tickets' hashes, claims' secrets, platform links' sealed configuration, the ATAK
  CA's sealed key;
- addresses (``audit_log.ip_address``, ``sessions``): the personal-data rules keep them for the person's own access
  only (ADR-P4-8);
- accounts' e-mail addresses: the person's own (``GET /api/v1/me/data``); the field sees usernames, as its roles
  page already does.

What is in it follows the personal-data rules as the server applies them: the export holds what the server holds
now, so whatever the retention purge (ADR-P4-8) or an erasure already removed or anonymised is not in it (an erased
account is its ``deleted-...`` row; the federation number of a past game is gone after 30 days). Nothing is
reformatted to be more revealing than the staff pages are.

Scope: in hosted mode (a tenant's schema is the field's) every row of the schema; on a single-field server, which
may hold several fields, the rows of the field (accounts: those with a role, a registration or a player id there).
The clubs and their members and reports are a hosted field's own; on a single-field server they belong to the
server, not to one field, and are left out. ``tests/test_field_export.py`` fails when a table of the schema is
neither exported nor listed in ``SKIPPED``, or when an exported column looks like a secret: a new table or column
needs this decision in the plan phase that adds it (the rule of ``personal_data.py``).

The export is audit-logged by the API (``field_export``: who, the file's SHA-256, its size and the rows per dataset).
"""

from __future__ import annotations

import base64
import datetime as dt
import decimal
import hashlib
import json
import tempfile
import uuid
import zipfile
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Callable, IO, Optional

from sqlalchemy import Select, and_, or_, select, union
from sqlalchemy.ext.asyncio import AsyncSession

from . import __version__
from .atak_models import AtakCa, AtakCert
from .history_models import FieldHistorySettings, FieldPreset, FieldScenario, FieldScenarioRevision, GameScoreSample
from .models import (AuditLog, BrandingImage, ChronoReading, ChronoReject, ChronoViolation, Club, ClubMember,
                     ClubReport, Consent, Controller, ExternalGameLink, Field, FieldApiKey, FieldPlayerId, FieldTeam,
                     Game, GameEvent, GameNode, GameNodeScore, GameRegistration, MarshalKey, PlatformLink,
                     PlayerIdClaim, RegistrationReplica, Replica, Role, ScheduledGame, User, UserFieldRole,
                     UserGameRole)

FORMAT = "atalaia-field-data"
VERSION = 1
BATCH = 1000
SPOOL_BYTES = 16 * 1024 * 1024


class ExportTooLarge(Exception):
    """The archive passed ``ATALAIA_EXPORT_MAX_MB``."""


# A column whose name matches one of these is a secret or an address: the test refuses it in any dataset.
SECRET_WORDS = ("password", "hash", "secret", "sealed", "_enc", "token", "ip_address", "key_sha256", "email")
# ``public_key`` is a public key, ``key_id`` an identifier, ``revoke_reason``... : these contain a word above
# but are not secrets.
NOT_SECRET = frozenset({"key_id", "marshal_key", "public_key", "api_key_id", "token_type", "roster_key_label",
                        "roster_key_fingerprint"})

# Tables never exported, with the reason (the manifest repeats it).
SKIPPED: dict[str, str] = {
    "alembic_version": "the schema's migration bookkeeping (its revision is in the manifest)",
    "sessions": "logins: addresses and security credentials of the persons' own accounts",
    "refresh_tokens": "security credentials",
    "firmware_releases": "the server's firmware catalogue, not a field's data",
    "preview_feedback": "a preview server's visitor feedback, belongs to no field",
}
# Left out on a single-field server, exported in hosted mode where the whole schema is the field's.
HOSTED_ONLY = ("clubs", "club_members", "club_reports")


@dataclass(frozen=True)
class Dataset:
    name: str                                            # the file's name: data/<name>.jsonl (the table's name)
    table: Any
    omit: dict[str, str]                                 # column -> why it is never exported
    scope: Callable[[uuid.UUID, bool], Optional[Any]]    # (field id, hosted) -> a WHERE clause, None for every row
    hosted_only: bool = False

    def columns(self) -> list[str]:
        return [c.name for c in self.table.columns if c.name not in self.omit]

    def query(self, field_id: uuid.UUID, hosted: bool) -> Select[Any]:
        q = select(*[self.table.c[name] for name in self.columns()])
        where = self.scope(field_id, hosted)
        if where is not None:
            q = q.where(where)
        pk = [c for c in self.table.primary_key.columns if c.name in self.columns()]
        return q.order_by(*pk) if pk else q


def _field(column: Any) -> Callable[[uuid.UUID, bool], Any]:
    return lambda fid, hosted: column == fid


def _all(fid: uuid.UUID, hosted: bool) -> None:
    return None


def _games_of(fid: uuid.UUID) -> Any:
    return select(Game.id).where(Game.field_id == fid)


def _account_ids(fid: uuid.UUID) -> Any:
    """The accounts of a field on a single-field server: a role, a registration or a player id there."""
    return union(select(UserFieldRole.user_id).where(UserFieldRole.field_id == fid),
                 select(GameRegistration.user_id).where(GameRegistration.field_id == fid,
                                                        GameRegistration.user_id.is_not(None)),
                 select(FieldPlayerId.user_id).where(FieldPlayerId.field_id == fid))


def _accounts(fid: uuid.UUID, hosted: bool) -> Any:
    return None if hosted else User.id.in_(_account_ids(fid))


def _consents(fid: uuid.UUID, hosted: bool) -> Any:
    return None if hosted else Consent.user_id.in_(_account_ids(fid))


def _audit(fid: uuid.UUID, hosted: bool) -> Any:
    if hosted:
        return None
    return or_(AuditLog.user_id.in_(_account_ids(fid)),
               and_(AuditLog.resource == "field", AuditLog.resource_id == fid))


def _images(fid: uuid.UUID, hosted: bool) -> Any:
    used = [select(Field.logo_sha256).where(Field.id == fid), select(Field.wallpaper_sha256).where(Field.id == fid),
            select(FieldTeam.crest_sha256).where(FieldTeam.field_id == fid)]
    if hosted:
        used += [select(Club.logo_sha256), select(Club.crest_sha256)]
    return BrandingImage.sha256.in_(union(*used))


def _registrations_of(fid: uuid.UUID) -> Any:
    return select(GameRegistration.id).where(GameRegistration.field_id == fid)


def _t(model: Any) -> Any:
    return model.__table__


DATASETS: tuple[Dataset, ...] = (
    Dataset("fields", _t(Field), {}, lambda fid, h: Field.id == fid),
    Dataset("roles", _t(Role), {}, _all),
    Dataset("users", _t(User), {
        "email": "the person's own: GET /api/v1/me/data", "password_hash": "a credential",
        "totp_secret_enc": "a credential", "totp_last_step": "a credential's state"}, _accounts),
    Dataset("user_field_roles", _t(UserFieldRole), {}, _field(UserFieldRole.field_id)),
    Dataset("consents", _t(Consent), {}, _consents),
    Dataset("field_api_keys", _t(FieldApiKey), {"key_sha256": "a credential"}, _field(FieldApiKey.field_id)),
    Dataset("controllers", _t(Controller), {}, _field(Controller.field_id)),
    Dataset("games", _t(Game), {}, _field(Game.field_id)),
    Dataset("game_events", _t(GameEvent), {}, lambda fid, h: GameEvent.game.in_(_games_of(fid))),
    Dataset("game_node_scores", _t(GameNodeScore), {}, lambda fid, h: GameNodeScore.game.in_(_games_of(fid))),
    Dataset("game_nodes", _t(GameNode), {}, lambda fid, h: GameNode.game.in_(_games_of(fid))),
    Dataset("game_score_samples", _t(GameScoreSample), {},
            lambda fid, h: GameScoreSample.game.in_(_games_of(fid))),
    Dataset("user_game_roles", _t(UserGameRole), {}, lambda fid, h: UserGameRole.game.in_(_games_of(fid))),
    Dataset("field_player_ids", _t(FieldPlayerId), {}, _field(FieldPlayerId.field_id)),
    Dataset("marshal_keys", _t(MarshalKey), {}, _field(MarshalKey.field_id)),
    Dataset("replicas", _t(Replica), {}, _field(Replica.field_id)),
    Dataset("chrono_readings", _t(ChronoReading), {}, _field(ChronoReading.field_id)),
    Dataset("chrono_rejects", _t(ChronoReject), {}, _field(ChronoReject.field_id)),
    Dataset("chrono_violations", _t(ChronoViolation), {}, _field(ChronoViolation.field_id)),
    Dataset("scheduled_games", _t(ScheduledGame), {}, _field(ScheduledGame.field_id)),
    Dataset("game_registrations", _t(GameRegistration), {"ticket_hash": "a credential"},
            _field(GameRegistration.field_id)),
    Dataset("registration_replicas", _t(RegistrationReplica), {},
            lambda fid, h: RegistrationReplica.registration.in_(_registrations_of(fid))),
    Dataset("player_id_claims", _t(PlayerIdClaim), {"secret_sha256": "a credential"}, _field(PlayerIdClaim.field_id)),
    Dataset("platform_links", _t(PlatformLink), {"config_enc": "sealed platform credentials"},
            _field(PlatformLink.field_id)),
    Dataset("external_game_links", _t(ExternalGameLink), {},
            lambda fid, h: ExternalGameLink.scheduled_game_id.in_(
                select(ScheduledGame.id).where(ScheduledGame.field_id == fid))),
    Dataset("field_teams", _t(FieldTeam), {}, _field(FieldTeam.field_id)),
    Dataset("field_history_settings", _t(FieldHistorySettings), {}, _field(FieldHistorySettings.field_id)),
    Dataset("field_scenarios", _t(FieldScenario), {}, _field(FieldScenario.field_id)),
    Dataset("field_scenario_revisions", _t(FieldScenarioRevision), {},
            lambda fid, h: FieldScenarioRevision.scenario.in_(
                select(FieldScenario.id).where(FieldScenario.field_id == fid))),
    Dataset("field_presets", _t(FieldPreset), {}, _field(FieldPreset.field_id)),
    Dataset("atak_cas", _t(AtakCa), {"key_sealed": "the CA's sealed private key"}, _field(AtakCa.field_id)),
    Dataset("atak_certs", _t(AtakCert), {}, _field(AtakCert.field_id)),
    Dataset("branding_images", _t(BrandingImage), {"data": "the image itself: fetch it from the field's pages"},
            _images),
    Dataset("audit_log", _t(AuditLog), {"ip_address": "an address (ADR-P4-8)"}, _audit),
    Dataset("clubs", _t(Club), {}, _all, hosted_only=True),
    Dataset("club_members", _t(ClubMember), {}, _all, hosted_only=True),
    Dataset("club_reports", _t(ClubReport), {}, _all, hosted_only=True),
)


def code_revision() -> Optional[str]:
    """The migration head of this server's code. The database is at it (the single-field image migrates as it
    starts; the hosted ``hub`` service migrates every field before the server does), and the server's role may not
    read ``alembic_version`` (S21-5), so the manifest names the code's."""
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        return ScriptDirectory.from_config(cfg).get_current_head()
    except Exception:  # noqa: BLE001  (no migrations folder in this image: the manifest says so)
        return None


def covered_tables() -> set[str]:
    """Every table the export decides on (exported or skipped); the test compares it with the models."""
    return {d.name for d in DATASETS} | set(SKIPPED)


def _json(value: Any) -> Any:
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return base64.b64encode(bytes(value)).decode("ascii")
    if isinstance(value, decimal.Decimal):
        return str(value)
    return str(value)


def _line(row: Any, columns: list[str]) -> bytes:
    return (json.dumps(dict(zip(columns, row)), default=_json, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


README = """Atalaia site server: the data of the field {slug} (format {format}, version {version})
Os dados do campo {slug} no servidor do campo (formato {format}, versao {version})

Made {generated_at} by the server {server_version}, at migration revision {revision}, mode: {mode}.

manifest.json       The list of the files below: each file's rows, columns and SHA-256, and the tables left out
                    and why. / A lista dos ficheiros abaixo, com linhas, colunas e SHA-256, e as tabelas deixadas
                    de fora e porque.
data/<name>.jsonl   One file per table: one JSON object per line (UTF-8), the table's own column names.
                    Times are ISO 8601 with their offset, ids are UUID strings, binary values are base64.
                    Um ficheiro por tabela: um objeto JSON por linha. Datas ISO 8601, ids em UUID, binario em base64.

What is in it is what the server holds now: the field's settings, schedule, registrations, games and their events,
the chrono registry, scenarios and presets, staff roles, controllers, ATAK certificates (no keys), and the field's audit
log (no addresses). Whatever the retention rules (ADR-P4-8) or an erasure already removed is not in it.
O que o servidor guarda agora: definicoes do campo, calendario, inscricoes, jogos e eventos, registo de cronografo,
cenarios, papeis da equipa, controladores, certificados ATAK (sem chaves) e o registo de auditoria do campo (sem enderecos).
O que as regras de retencao ja apagaram, ou um apagamento de conta, nao aparece.

Never in it / Nunca incluido: password hashes, TOTP secrets, sessions and refresh tokens, API keys, ticket and claim
secrets, platform credentials, the ATAK CA's private key, e-mail addresses, IP addresses.
Hashes de palavras-passe, segredos TOTP, sessoes, chaves de API, segredos de bilhetes, credenciais de plataformas,
chave privada da CA ATAK, e-mails e enderecos IP.

Every export is logged in the field's audit log (action field_export) with the SHA-256 of the file.
Cada exportacao fica no registo de auditoria do campo (acao field_export) com o SHA-256 do ficheiro.
"""


@dataclass
class Built:
    file: IO[bytes]            # the archive, positioned at its start; the caller closes it
    size: int
    sha256: str
    manifest: dict[str, Any]


async def build(db: AsyncSession, field: Any, *, hosted: bool, max_bytes: int) -> Built:
    """The field's archive in a temporary file (memory up to 16 MB, then disk); ``field`` is anything with ``id``,
    ``slug`` and ``name``. Raises ``ExportTooLarge`` past ``max_bytes``. The session must be fresh: this makes its
    transaction repeatable-read and read-only."""
    await db.connection(execution_options={"isolation_level": "REPEATABLE READ", "postgresql_readonly": True})
    revision = code_revision()
    spool: IO[bytes] = tempfile.SpooledTemporaryFile(max_size=SPOOL_BYTES)  # noqa: SIM115  (the caller closes it)
    try:
        entries: list[dict[str, Any]] = []
        written = 0
        with zipfile.ZipFile(spool, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for ds in DATASETS:
                if ds.hosted_only and not hosted:
                    continue
                columns = ds.columns()
                digest, rows = hashlib.sha256(), 0
                with zf.open(f"data/{ds.name}.jsonl", "w", force_zip64=True) as out:
                    result = await db.stream(ds.query(field.id, hosted))
                    async for part in result.partitions(BATCH):
                        chunk = b"".join(_line(r, columns) for r in part)
                        out.write(chunk)
                        digest.update(chunk)
                        rows += len(part)
                        written += len(chunk)
                        if written > max_bytes:
                            raise ExportTooLarge()
                entries.append({"name": ds.name, "file": f"data/{ds.name}.jsonl", "rows": rows, "columns": columns,
                                "omitted_columns": ds.omit, "sha256": digest.hexdigest()})
            skipped = [{"table": t, "reason": r} for t, r in SKIPPED.items()]
            if not hosted:
                skipped += [{"table": t, "reason": "belongs to the server, not to one field (hosted mode: exported)"}
                            for t in HOSTED_ONLY]
            generated = dt.datetime.now(dt.timezone.utc).isoformat()
            manifest = {"format": FORMAT, "version": VERSION, "generated_at": generated,
                        "server_version": __version__, "revision": revision,
                        "mode": "hosted" if hosted else "single",
                        "field": {"id": str(field.id), "slug": field.slug, "name": field.name},
                        "datasets": entries, "skipped": skipped}
            zf.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
            zf.writestr("README.txt", README.format(
                slug=field.slug, format=FORMAT, version=VERSION, generated_at=generated, server_version=__version__,
                revision=revision, mode=manifest["mode"]))
        spool.seek(0, 2)
        size = spool.tell()
        if size > max_bytes:
            raise ExportTooLarge()
        spool.seek(0)
        sha = hashlib.sha256()
        while block := spool.read(1024 * 1024):
            sha.update(block)
        spool.seek(0)
        return Built(spool, size, sha.hexdigest(), manifest)
    except BaseException:
        spool.close()
        raise


__all__ = ["DATASETS", "FORMAT", "VERSION", "SKIPPED", "Built", "ExportTooLarge", "build", "covered_tables"]
