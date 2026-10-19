# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""``python -m atalaia_server``: the site server's commands (``cli.py``)."""

import sys

from .cli import main

sys.exit(main())
