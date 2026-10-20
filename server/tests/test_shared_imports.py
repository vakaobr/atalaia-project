# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Python the site server shares with the controller stays free of its web stack (P4R16).

The controller runs on Raspberry Pi OS's own packages (FastAPI 0.101 with
pydantic 1, decision D15); the site server has its own pinned versions. So
the shared modules (the chrono verifier, the player-token codec, the image
checks, the mode loader and its core bindings) must import with FastAPI,
pydantic, SQLAlchemy and the rest blocked, and the site server's plain
modules (settings, ids) must too. Then the core library loads every built-in
mode's scripts the way the controller's ``modes.install`` checks them (P4R9):
in the site server's image that is the core its build stage compiled.

No database; also run by tools/check.sh.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
REPO = SERVER.parent
sys.path.insert(0, str(SERVER))

import atalaia_server  # noqa: E402,F401  (puts ../controller and ../simulator on the path)
from atalaia_controller.modes import check_scripts, parse_package  # noqa: E402
from atalaia_sim.core import Core, find_library  # noqa: E402
from atalaia_sim.mode import ModeError  # noqa: E402

REQUIRE_ALL = os.environ.get("ATALAIA_REQUIRE_ALL") == "1"
BLOCKED = ("fastapi", "pydantic", "pydantic_core", "starlette", "sqlalchemy", "alembic", "asyncpg", "uvicorn",
           "httpx", "anyio")
SHARED = ("atalaia_controller.chrono", "atalaia_controller.player_token", "atalaia_controller.images",
          "atalaia_controller.sync_format", "atalaia_controller.sync_client",
          "atalaia_controller.modes", "atalaia_sim.mode", "atalaia_sim.core",
          "atalaia_server.config", "atalaia_server.ids", "atalaia_server.chrono_verify")
MODES = Path(os.environ.get("ATALAIA_MODES_DIR", REPO / "modes"))


class SharedImportTests(unittest.TestCase):
    def test_shared_modules_import_without_the_web_stack(self) -> None:
        script = textwrap.dedent(f"""
            import importlib, importlib.abc, sys
            blocked = {BLOCKED!r}

            class Block(importlib.abc.MetaPathFinder):
                def find_spec(self, name, path=None, target=None):
                    if name.split(".")[0] in blocked:
                        raise ImportError(f"blocked for this test: {{name}}")
                    return None

            sys.meta_path.insert(0, Block())
            sys.path.insert(0, {str(SERVER)!r})
            import atalaia_server
            for name in {SHARED!r}:
                importlib.import_module(name)
            leaked = sorted(m for m in sys.modules if m.split(".")[0] in blocked)
            assert not leaked, leaked
            print("ok")
        """)
        proc = subprocess.run([sys.executable, "-I", "-c", script], capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "ok")


class CoreLoadCheckTests(unittest.TestCase):
    core: Core

    @classmethod
    def setUpClass(cls) -> None:
        try:
            cls.core = Core(find_library())
        except (FileNotFoundError, OSError) as exc:
            if REQUIRE_ALL:
                raise RuntimeError(f"ATALAIA_REQUIRE_ALL=1 but the core library does not load: {exc}") from exc
            raise unittest.SkipTest("the core library is not built (set ATALAIA_CORE_LIB)")

    def packages(self) -> list[Path]:
        found = sorted(p.parent for p in MODES.glob("*/mode.yaml"))
        if not found:
            self.fail(f"no built-in modes under {MODES}")
        return found

    def test_every_builtin_mode_loads_in_the_core(self) -> None:
        for mode_dir in self.packages():
            files = {name: (mode_dir / name).read_text(encoding="utf-8")
                     for name in ("mode.yaml", "node.lua", "field.lua") if (mode_dir / name).exists()}
            with self.subTest(mode=mode_dir.name):
                check_scripts(self.core, parse_package(files, mode_dir))

    def test_a_script_that_does_not_load_is_refused(self) -> None:
        mode_dir = self.packages()[0]
        files = {name: (mode_dir / name).read_text(encoding="utf-8")
                 for name in ("mode.yaml", "node.lua") if (mode_dir / name).exists()}
        files["node.lua"] = "this is not lua ("
        with self.assertRaisesRegex(ModeError, "node.lua does not load"):
            check_scripts(self.core, parse_package(files, mode_dir))


if __name__ == "__main__":
    unittest.main()
