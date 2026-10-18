# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Command line: python -m atalaia_sim test [paths...] | serve MODE"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import yaml

from .core import Core, LibraryNotFound, find_library
from .mode import ModeError, compose, find_modes, load_mode
from .sim import SimError, Simulation
from .testing import DEFAULT_TEAMS, run_test

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


def _key_values(items: list[str], what: str) -> dict[str, str]:
    out = {}
    for item in items:
        key, sep, value = item.partition("=")
        if not sep or not key:
            raise SystemExit(f"{what} must look like name=value, got {item!r}")
        out[key] = value
    return out


def cmd_serve(args: argparse.Namespace) -> int:
    from .live import LiveGame
    from .web import make_server

    core = Core(find_library(args.lib))
    try:
        mode = compose(load_mode(Path(args.mode)), [load_mode(Path(m)) for m in args.modifier])
        teams = [t for t in args.teams.split(",") if t] if args.teams else DEFAULT_TEAMS
        overrides = {k: yaml.safe_load(v) for k, v in _key_values(args.param, "--param").items()}
        params = mode.resolve_params(overrides, teams)
        nodes = _key_values(args.node, "--node") or {next(iter(mode.roles)): next(iter(mode.roles))}

        def make_sim() -> Simulation:
            return Simulation(core, mode, nodes, teams, params, seed=args.seed)

        game = LiveGame(make_sim)
    except (ModeError, SimError) as exc:
        print(f"cannot serve {args.mode}: {exc}", file=sys.stderr)
        return 1

    server = make_server(game, args.host, args.port, args.allow_host)
    print(f"Atalaia core {core.version}: {mode.name} {mode.version} with {', '.join(nodes)}")
    print(f"Open {server.url} (Ctrl+C stops)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        game.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="atalaia_sim", description="Atalaia desktop simulator")
    parser.add_argument("--lib", help="path to the shared core library")
    sub = parser.add_subparsers(dest="command", required=True)
    test = sub.add_parser("test", help="run mode tests (default: every mode in modes/)")
    test.add_argument("paths", nargs="*", help="mode folders, or folders of modes")
    test.set_defaults(func=cmd_test)
    serve = sub.add_parser("serve", help="play a mode in the browser")
    serve.add_argument("mode", help="mode folder, e.g. ../modes/bomb")
    serve.add_argument("--node", action="append", default=[], metavar="NAME=ROLE",
                       help="a node and its role; repeat for more (default: one node of the first role)")
    serve.add_argument("--modifier", action="append", default=[], metavar="FOLDER",
                       help="a modifier to run alongside the mode, e.g. ../modes/codes; repeat for more")
    serve.add_argument("--teams", help="comma-separated team names (default: red,blue)")
    serve.add_argument("--param", action="append", default=[], metavar="NAME=VALUE",
                       help="override a mode parameter; repeat for more")
    serve.add_argument("--seed", type=int, default=1, help="game seed for rand() (default 1)")
    serve.add_argument("--host", default="127.0.0.1",
                       help="address to listen on (default 127.0.0.1; use 0.0.0.0 inside a container)")
    serve.add_argument("--port", type=int, default=8000, help="port (default 8000)")
    serve.add_argument("--allow-host", action="append", default=[], metavar="NAME",
                       help="another host name the browser may use, besides localhost")
    serve.set_defaults(func=cmd_serve)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except LibraryNotFound as exc:
        launcher = os.path.relpath(REPO / "tools" / "docker_sim.py")
        rest = argv if argv is not None else sys.argv[1:]
        print(f"atalaia_sim: {exc}\n\n"
              "No C compiler on this machine? Run the same command in the dev container\n"
              "(Docker must be running):\n\n"
              f"  python {subprocess.list2cmdline([launcher, *rest])}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
