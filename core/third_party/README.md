# Third-party code

Vendored dependencies live here, each in its own folder, under its original licence. Unmodified, except for the local patches listed under Lua.

| Folder | Project | Version | Licence |
| --- | --- | --- | --- |
| [`lua/`](lua/) | [Lua](https://www.lua.org) | 5.4.9 | MIT (notice at the end of `lua.h`) |

## Lua

The files are the `src/` folder of the official `lua-5.4.9.tar.gz` (SHA-256 `2335b6c582a52654f94612bf10d2f4672805d05329aa6568b1d8cd9e5c6fb8e6`, as published on lua.org). The build compiles only the parts the sandbox uses: no `io`, `os`, `package` or `debug` library, and no standalone interpreter. `lstate.c` is compiled through [`../src/lua_lstate.c`](../src/lua_lstate.c), which fixes the string-hash seed so games replay exactly and clears the main thread's extra space (the patched `ltablib.c` keeps a counter there).

**Local patches**, every changed line marked `ATALAIA PATCH` (`grep -n 'ATALAIA PATCH' lua/*.c lua/*.h` finds them all):

1. **`lstrlib.c`, pattern matching is metered** (decision SR-41): `lua/lstrlib.c` meters pattern matching. The marked `ATALAIA PATCH` lines add a step counter to `MatchState`, a `meter_charge()` that calls the installed count hook by hand every 1000 matching steps (so the sandbox's instruction budget, or the scenario compiler's, pays for the work and an exhausted budget raises its error), and a charge in proportion to `(subject / 1024) * pattern` before a plain search. Without it a hostile pattern runs inside a C function where the VM's instruction hook never fires (review finding FLD-8). `core/tests/test_sandbox_escape.c` has the cases that fail without it. `string.rep` is capped in `core/src/sandbox.c`, not here. The same file's pattern recursion limit `MAXCCALLS` is 32 instead of 200 (see 4).
2. **`ltablib.c`, the table functions are metered** (decision SR-130, review finding LIVE2-S2): `table.move`, `insert`, `remove`, `concat`, `unpack` and each partition of `sort` call `meter_work()`, which charges the installed count hook (the sandbox's instruction budget, or the scenario compiler's) in proportion to the elements touched (two units for a move, one for a read) before the loop runs; the remainder below one hook step is kept in the thread's extra space. Without it a script ran a billion-element `table.move`, or `table.insert(t, 1, x)` over a big table in a loop, in C with no hook. `sort`'s pivot, which came from `clock()` and `time()` and so made two runs of a game differ, is a fixed value (`l_randomizePivot`); a bad input is paid for by the metering instead.
3. **`luaconf.h`, `LUAL_BUFFERSIZE` 64** (was 512 on the ESP32): the buffer sits on the C stack of every function that builds a string, and `string.gsub`'s frame was 912 bytes on the Xtensa (464 now).
4. **`luaconf.h`, `LUAI_MAXCCALLS` 20** (was 200; decision SR-132, review finding LIVE2-S3): the C stack a script can use by nesting `pcall`, metamethods, `gsub` callbacks, sort comparators or coroutines (and the parser's nesting) is about 0.8 KB a level on the Xtensa at the worst. The built-in modes need up to 14 levels. With `lstrlib.c`'s pattern depth of 32 this fits the game task's 24 KB stack (`firmware/esp32/main/shell.c`).

To update: download the new 5.4.x release from <https://www.lua.org/ftp/>, check its SHA-256 against that page, replace the files in `lua/` and carry the `ATALAIA PATCH` lines of `lstrlib.c`, `ltablib.c` and `luaconf.h` over (`grep -n 'ATALAIA PATCH' lua/*.c lua/*.h` finds them all), update the version and checksum above, and run the full test suite.
