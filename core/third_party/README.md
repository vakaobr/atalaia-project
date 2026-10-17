# Third-party code

Vendored dependencies live here, each in its own folder, unmodified, under its original licence.

| Folder | Project | Version | Licence |
| --- | --- | --- | --- |
| [`lua/`](lua/) | [Lua](https://www.lua.org) | 5.4.9 | MIT (notice at the end of `lua.h`) |

## Lua

The files are the `src/` folder of the official `lua-5.4.9.tar.gz` (SHA-256 `2335b6c582a52654f94612bf10d2f4672805d05329aa6568b1d8cd9e5c6fb8e6`, as published on lua.org). The build compiles only the parts the sandbox uses: no `io`, `os`, `package` or `debug` library, and no standalone interpreter. `lstate.c` is compiled through [`../src/lua_lstate.c`](../src/lua_lstate.c), which fixes the string-hash seed so games replay exactly.

To update: download the new 5.4.x release from <https://www.lua.org/ftp/>, check its SHA-256 against that page, replace the files in `lua/`, update the version and checksum above, and run the full test suite.
