# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The registration import's format (ADR-P4-12; plan phase 17): the code lives in the controller's package
(``atalaia_controller/import_format.py``) because the field controller imports the same CSV into its
check-in list (PKE-1), so the site server and the controller read and check a file the same way. This
module only re-exports it under the name the server's code and tests have always used."""

from atalaia_controller.import_format import *  # noqa: F401,F403
from atalaia_controller.import_format import (  # noqa: F401
    COLUMNS, EXPORT_COLUMNS, FEDERATION_MAX, FORMULA_START, MAKE_MODEL_MAX, MAX_BYTES, MAX_IGNORED,
    MAX_REPLICAS, MAX_ROWS, NAME_MAX, REF_MAX, REPLICA_TYPES, RESERVED_SOURCES, SOURCE, TEAM_MAX,
    FileError, Parsed, RawRow, Row, RowError, Rules, check_replicas, check_row, check_source, csv_safe,
    csv_unsafe, export_csv, parse, parse_csv, parse_json, replicas_text,
)
