# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The ctypes structs in atalaia_sim/core.py against the C compiler's layout of the real
headers, as the FFI stub reports it (atalaia_stub_layout, core/tests/stub.c). The app's Dart
structs are checked against the same report (app/test/ffi/layout_test.dart).

The stub is built with -DATALAIA_STUB=ON (tools/check.sh and CI do); $ATALAIA_CORE_STUB_LIB
names it, or it is looked for next to the core in the build folders.
"""

from __future__ import annotations

import ctypes
import json
import os
import unittest
from pathlib import Path

from atalaia_sim import core

REPO = Path(__file__).resolve().parents[2]


def _stub_path() -> Path | None:
    if os.environ.get("ATALAIA_CORE_STUB_LIB"):
        return Path(os.environ["ATALAIA_CORE_STUB_LIB"])
    for folder in ("build", "build/core", "core/build"):
        candidate = REPO / folder / "libatalaia_core_stub.so"
        if candidate.exists():
            return candidate
    return None


STUB = _stub_path()
if os.environ.get("ATALAIA_REQUIRE_ALL") == "1" and (STUB is None or not STUB.exists()):
    raise ImportError("ATALAIA_REQUIRE_ALL=1 but the FFI stub library was not built "
                      "(cmake -DATALAIA_STUB=ON; set ATALAIA_CORE_STUB_LIB)")

STRUCTS = {
    "atalaia_event_t": core._Event,
    "atalaia_node_callbacks_t": core._Callbacks,
    "atalaia_field_ops_t": core._FieldOps,
    "atalaia_node_config_t": core._Config,
    "atalaia_score_t": core._Score,
    "atalaia_tpl_scope_t": core._Scope,
}


@unittest.skipIf(STUB is None or not STUB.exists(), "FFI stub library not built")
class LayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        lib = ctypes.CDLL(str(STUB))
        lib.atalaia_stub_layout.restype = ctypes.c_char_p
        cls.layout = json.loads(lib.atalaia_stub_layout())

    def test_every_struct_is_reported(self) -> None:
        self.assertEqual(set(self.layout), set(STRUCTS))

    def test_sizes_and_offsets(self) -> None:
        for c_name, struct in STRUCTS.items():
            with self.subTest(c_name):
                c = self.layout[c_name]
                self.assertEqual(ctypes.sizeof(struct), c["size"], f"sizeof({c_name})")
                fields = {name: getattr(struct, name).offset for name, _ in struct._fields_}
                self.assertEqual(fields, c["fields"], f"offsets in {c_name}")


if __name__ == "__main__":
    unittest.main()
