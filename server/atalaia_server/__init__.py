# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Atalaia site server: accounts, history, sync and the chrono registry (phase 4).

The application is a FastAPI app (``atalaia_server.app.create_app``) on
PostgreSQL 16 through SQLAlchemy 2's async engine and asyncpg; Alembic owns
the schema (``server/migrations``). It never runs game logic. It imports the
pure-Python code it shares with the field controller (the chrono verifier,
the player-token codec, the image checks, the mode loader) from
``controller/atalaia_controller`` and ``simulator/atalaia_sim``; in the image
those folders are on PYTHONPATH, and in a checkout the copies next to this
folder are used.
"""

from __future__ import annotations

import sys
from pathlib import Path

__version__ = "0.5.0"

try:
    import atalaia_controller  # noqa: F401
except ImportError:  # running from a checkout: use ../controller (which finds ../simulator)
    _CONTROLLER = Path(__file__).resolve().parents[2] / "controller"
    if (_CONTROLLER / "atalaia_controller").is_dir():
        sys.path.insert(0, str(_CONTROLLER))
