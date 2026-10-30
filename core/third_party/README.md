# Third-party code

Vendored dependencies live here, each in its own folder, under its original licence. Unmodified, except for the one local patch listed under Lua.

| Folder | Project | Version | Licence |
| --- | --- | --- | --- |
| [`lua/`](lua/) | [Lua](https://www.lua.org) | 5.4.9 | MIT (notice at the end of `lua.h`) |

## Lua

The files are the `src/` folder of the official `lua-5.4.9.tar.gz` (SHA-256 `2335b6c582a52654f94612bf10d2f4672805d05329aa6568b1d8cd9e5c6fb8e6`, as published on lua.org). The build compiles only the parts the sandbox uses: no `io`, `os`, `package` or `debug` library, and no standalone interpreter. `lstate.c` is compiled through [`../src/lua_lstate.c`](../src/lua_lstate.c), which fixes the string-hash seed so games replay exactly.

**One local patch** (decision SR-41): `lua/lstrlib.c` meters pattern matching. The marked `ATALAIA PATCH` lines add a step counter to `MatchState`, a `meter_charge()` that calls the installed count hook by hand every 1000 matching steps (so the sandbox's instruction budget, or the scenario compiler's, pays for the work and an exhausted budget raises its error), and a charge in proportion to `(subject / 1024) * pattern` before a plain search. Without it a hostile pattern runs inside a C function where the VM's instruction hook never fires (review finding FLD-8). `core/tests/test_sandbox_escape.c` has the cases that fail without it. `string.rep` is capped in `core/src/sandbox.c`, not here.

To update: download the new 5.4.x release from <https://www.lua.org/ftp/>, check its SHA-256 against that page, replace the files in `lua/` and carry the `ATALAIA PATCH` lines of `lstrlib.c` over (`grep -n 'ATALAIA PATCH' lua/lstrlib.c` finds them all), update the version and checksum above, and run the full test suite.
