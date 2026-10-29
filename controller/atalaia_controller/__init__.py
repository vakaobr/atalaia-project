# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Atalaia field controller: the Raspberry Pi side of a field (ADR-P2-5).

It reuses the simulator's packet codec, CLAIM election and FieldController
(simulator/atalaia_sim) and its ctypes bindings to the C core. When the
simulator package is not installed, the copy next to this one in the
repository is used.
"""

from __future__ import annotations

import sys
from pathlib import Path

__version__ = "0.5.0"

try:
    import atalaia_sim  # noqa: F401
except ImportError:  # running from a checkout: use ../simulator
    _SIM = Path(__file__).resolve().parents[2] / "simulator"
    if (_SIM / "atalaia_sim").is_dir():
        sys.path.insert(0, str(_SIM))
    import atalaia_sim  # noqa: F401

REPO_ROOT = Path(__file__).resolve().parents[2]
