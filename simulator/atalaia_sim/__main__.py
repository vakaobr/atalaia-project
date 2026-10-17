# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Command line: python -m atalaia_sim test [paths...]"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core import Core, find_library
from .mode import ModeError, find_modes, load_mode
from .testing import run_test

REPO = Path(__file__).resolve().parents[2]


def cmd_test(args: argparse.Namespace) -> int:
    core = Core(find_library(args.lib))
    paths = [Path(p) for p in args.paths] or [REPO / "modes"]
    mode_dirs = find_modes(paths)
    if not mode_dirs:
        print("no modes found", file=sys.stderr)
        return 1

    print(f"Atalaia core {core.version} ({core.path.name})")
    failed = total = 0
    for mode_dir in mode_dirs:
        try:
            mode = load_mode(mode_dir)
        except ModeError as exc:
            print(f"FAIL {mode_dir}: {exc}")
            failed += 1
            total += 1
            continue
        tests = mode.tests
        if not tests:
            print(f"  -- {mode.id}: no tests")
            continue
        for test in tests:
            total += 1
            result = run_test(core, mode, test)
            mark = "ok  " if result.passed else "FAIL"
            print(f"{mark} {mode.id} / {result.name}")
            if not result.passed:
                failed += 1
                print(f"     {test.relative_to(REPO) if test.is_relative_to(REPO) else test}")
                print(f"     {result.message}")
                if result.log:
                    print("     event log:")
                    for line in result.log:
                        print(f"       {line}")
    print(f"\n{total - failed} of {total} test(s) passed")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="atalaia_sim", description="Atalaia desktop simulator")
    parser.add_argument("--lib", help="path to the shared core library")
    sub = parser.add_subparsers(dest="command", required=True)
    test = sub.add_parser("test", help="run mode tests (default: every mode in modes/)")
    test.add_argument("paths", nargs="*", help="mode folders, or folders of modes")
    test.set_defaults(func=cmd_test)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
