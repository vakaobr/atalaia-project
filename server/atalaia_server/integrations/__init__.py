# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Platform adapters (ADR-P4-12; plan phase 17): the interface (``base``), the adapters a server offers
(``Registry``), the encrypted per-field configuration (``ConfigBox``) and the test adapter (``testing``).

No adapter for a named platform ships without that platform's API documentation or a written agreement
(F21, F22): jogarairsoft.pt has none known, so there is no adapter for it. Plain Python.
"""

from __future__ import annotations

import json
import uuid
from typing import Iterable, Mapping, Optional

from cryptography.fernet import Fernet, InvalidToken

from .. import import_format
from .base import CAPABILITIES, AdapterError, PlatformAdapter
from .testing import TestAdapter, TestPlatform

CALL_TIMEOUT_S = 20.0  # a platform that does not answer in time fails the call, nothing else

__all__ = ["CALL_TIMEOUT_S", "AdapterError", "ConfigBox", "PlatformAdapter", "Registry", "TestAdapter",
           "TestPlatform"]


class Registry:
    """The adapters this server offers, by id. ``register`` checks the rules an adapter must meet to be
    offered at all: a stable id, known capabilities, a stated basis (a documented API or an agreement)."""

    def __init__(self, adapters: Iterable[PlatformAdapter] = ()) -> None:
        self._adapters: dict[str, PlatformAdapter] = {}
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: PlatformAdapter) -> None:
        if not isinstance(adapter, PlatformAdapter):
            raise ValueError("not a PlatformAdapter")
        if not import_format.SOURCE.fullmatch(adapter.id) or adapter.id in import_format.RESERVED_SOURCES:
            raise ValueError(f"adapter id {adapter.id!r} is not valid")
        if not adapter.capabilities or not adapter.capabilities <= CAPABILITIES:
            raise ValueError(f"adapter {adapter.id!r}: unknown capabilities")
        if not adapter.basis.strip():
            raise ValueError(f"adapter {adapter.id!r} names no documented API or agreement (ADR-P4-12)")
        if not adapter.secret_keys <= set(adapter.config_keys):
            raise ValueError(f"adapter {adapter.id!r}: secret keys outside its configuration")
        if adapter.id in self._adapters:
            raise ValueError(f"adapter {adapter.id!r} twice")
        self._adapters[adapter.id] = adapter

    def get(self, adapter_id: str) -> Optional[PlatformAdapter]:
        return self._adapters.get(adapter_id)

    def all(self) -> list[PlatformAdapter]:
        return [self._adapters[k] for k in sorted(self._adapters)]


def default_registry(test_adapter: bool) -> Registry:
    """What a server offers: no platform's adapter ships yet (F22), so only the test adapter, and only
    when ``ATALAIA_TEST_ADAPTER=on``."""
    return Registry([TestAdapter()] if test_adapter else [])


class ConfigBox:
    """Seals an adapter's configuration for ``platform_links.config_enc`` (Fernet, under a key derived
    from ATALAIA_SECRET_KEY, as the TOTP seeds). The field and the adapter are sealed in with it, so a
    sealed configuration copied to another field's row does not open there."""

    def __init__(self, fernet_key: bytes) -> None:
        self._fernet = Fernet(fernet_key)

    def seal(self, field_id: uuid.UUID, adapter_id: str, config: Mapping[str, str]) -> bytes:
        body = {"field": str(field_id), "adapter": adapter_id, "config": dict(config)}
        return self._fernet.encrypt(json.dumps(body, sort_keys=True).encode("utf-8"))

    def open(self, field_id: uuid.UUID, adapter_id: str, sealed: Optional[bytes]) -> Optional[dict[str, str]]:
        """The configuration, or None when there is none, it was sealed under another key (the secret key
        changed) or for another field or adapter."""
        if not sealed:
            return None
        try:
            body = json.loads(self._fernet.decrypt(bytes(sealed)).decode("utf-8"))
        except (InvalidToken, ValueError):
            return None
        if body.get("field") != str(field_id) or body.get("adapter") != adapter_id:
            return None
        config = body.get("config")
        return config if isinstance(config, dict) else None
