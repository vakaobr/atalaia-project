# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The cross-field sharing terms a field accepts before it shares chrono records (decision LEG-41).

The terms are ``docs/templates/sharing-terms.md`` (and ``-pt.md``): the Art. 26 GDPR arrangement between the fields
that share. ``current()`` is the version of that text this server asks for; a hub operator who publishes terms of its
own sets ``ATALAIA_SHARING_TERMS_VERSION``. A field's acceptance (``fields.sharing_terms_version`` / ``_accepted_at`` /
``_accepted_by``) is for one version: when the current one changes the field is asked again, and until its
administrator accepts, its sharing is **not live** (it keeps its switch on, but publishes and reads nothing).
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import and_

from .models import Field

DEFAULT_VERSION = "2026-10-30"
_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+-]{0,63}")


def current() -> str:
    """The version of the terms asked for now (the environment's, else the shipped text's)."""
    value = os.environ.get("ATALAIA_SHARING_TERMS_VERSION", "").strip()
    return value if _VERSION.fullmatch(value) else DEFAULT_VERSION


def live_clause() -> Any:
    """SQL: the fields whose sharing is live: the switch is on and the current terms were accepted."""
    return and_(Field.chrono_sharing_enabled.is_(True), Field.sharing_terms_version == current())


def is_live(field: Field) -> bool:
    return bool(field.chrono_sharing_enabled) and field.sharing_terms_version == current()


def view(field: Field) -> dict[str, Any]:
    """What the API shows of a field's acceptance (``accepted_by`` is an account id, null after an erasure)."""
    when: Optional[datetime] = field.sharing_terms_accepted_at
    return {"version": current(), "accepted_version": field.sharing_terms_version,
            "accepted_at": when.isoformat() if when else None,
            "accepted_by": str(field.sharing_terms_accepted_by) if field.sharing_terms_accepted_by else None,
            "current": field.sharing_terms_version == current()}
