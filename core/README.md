# Core

The shared C11 core runs on every full node: ESP32, Raspberry Pi/Linux and Android (through `dart:ffi`). Only platform shells and hardware drivers live elsewhere.

Planned components:

| Component | Purpose | Status |
| --- | --- | --- |
| Events | Event structure, identity and ordering | Skeleton |
| Event bus | Dispatch hardware, game and system events to scripts | Planned |
| State store | Node-local and replicated state, grow-only score counters | Planned |
| Lua sandbox | Lua 5.4 with memory and instruction limits, seeded `rand` | Planned |
| Protocol codec | Skirmesh-RF CBOR and JSON encodings from `protocol/schema` | Planned |
| Event log | Append-only log with merge and replay | Planned |

## Build and test

```sh
cmake -S core -B build
cmake --build build
ctest --test-dir build --output-on-failure
```

Rules: C11, no dynamic allocation outside the Lua allocator on microcontrollers, public symbols prefixed `atalaia_`, warnings are errors.
