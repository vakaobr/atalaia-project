# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""python3 -m atalaia_controller.scenarios validate|check|compile scenario.yaml

    validate  the manifest's problems only
    check     validate, compile, and load the generated field.lua in the core, as the controller
              does when the package is installed (P4R9)
    compile   check, then write the package (mode.yaml and field.lua) into -o DIR, or print
              the generated field.lua without -o

The validator and the compiler are the core's (core/scenario/, decision PE24-109), so every
command needs the core library (ATALAIA_CORE_LIB, or a build folder of the repository);
--no-core only skips loading the generated field.lua in it. Problems are printed one a line,
"file: path: level: message (code)", or as JSON with --json. Exit status: 0 without errors
(warnings are printed), 1 with errors, 2 when the file cannot be read or is not a manifest, or
the core library is missing. Also ``python3 -m atalaia_controller scenario ...``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

from atalaia_sim.mode import ModeError

from . import CoreUnavailable, ManifestError, Problem, check_package, errors, load
from .package import compile_package


def _core() -> Any:
    """The C core (ATALAIA_CORE_LIB, or a build folder of the repository); LibraryNotFound or OSError."""
    from atalaia_sim.core import Core, find_library  # noqa: PLC0415

    return Core(find_library())


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m atalaia_controller.scenarios", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("validate", "check", "compile"))
    parser.add_argument("manifest", help="the scenario manifest (YAML or JSON)")
    parser.add_argument("-o", "--output", help="compile: the folder to write the package into")
    parser.add_argument("--json", action="store_true", help="print the problems (and the files) as JSON")
    parser.add_argument("--no-core", action="store_true",
                        help="check, compile: do not load the generated Lua in the core")
    args = parser.parse_args(argv)

    path = Path(args.manifest)
    try:
        text = path.read_text(encoding="utf-8")
        manifest = load(text)
    except (OSError, UnicodeDecodeError, ManifestError) as exc:
        if args.json:
            print(json.dumps({"ok": False, "problems": [Problem("", "bad_manifest", str(exc)).to_dict()]}))
        else:
            print(f"{path}: error: {exc}", file=sys.stderr)
        return 2
    try:
        core = _core()
        problems, package = compile_package(manifest, core)
    except (CoreUnavailable, OSError) as exc:  # LibraryNotFound is an OSError
        print(f"scenario: the core library is needed: it holds the validator and the compiler "
              f"({str(exc).splitlines()[0]})", file=sys.stderr)
        return 2
    bad = bool(errors(problems))
    result: dict[str, Any] = {"ok": not bad, "problems": [p.to_dict() for p in problems]}
    if args.command == "validate":
        package = None
    if package is not None and not args.no_core:
        try:
            check_package(core, package)
        except ModeError as exc:
            problems.append(Problem("", "lua_does_not_load", str(exc)))
            result = {"ok": False, "problems": [p.to_dict() for p in problems]}
            bad = True
    if args.json:
        if package is not None and not bad:
            result["files"] = package.files
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for p in problems:
            print(f"{path}: {p}", file=sys.stderr if p.level == "error" else sys.stdout)
    if bad:
        return 1
    if args.command == "compile" and package is not None:
        if args.output:
            for written in package.write(Path(args.output)):
                if not args.json:
                    print(f"wrote {written}")
        elif not args.json:
            sys.stdout.write(package.field_lua)
    elif not args.json:
        n = len(manifest.get("objectives") or [])
        print(f"{path}: {manifest.get('id')}: {n} objective{'s' if n != 1 else ''}, no errors"
              + ("" if args.command == "validate" else "; the field.lua loads in the core" if not args.no_core
                 else "; the field.lua was not load-checked"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
