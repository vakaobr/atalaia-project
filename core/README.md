# Core

The shared C11 core runs on every full node: ESP32, Raspberry Pi/Linux and Android (through `dart:ffi`). Only platform shells and hardware drivers live elsewhere.

| Component | Purpose | Files | Status |
| --- | --- | --- | --- |
| Events | Event structure, identity and ordering | `event.h` | Done |
| Protocol tables | Message types, event ids and priorities, CBOR keys; generated from `protocol/schema` | `protocol.h`, `protocol.c` | Done |
| Event bus | Dispatches hardware, game and system events to script handlers, in order | `node.c` | Done |
| Timers | `every`, `after` and `cancel` on game time, fired in a deterministic order | `node.c` | Done |
| State store | `state.node{}`, `state.field{}` and grow-only, mergeable score counters | `score.h`, `script_api.c` | Done |
| Lua sandbox | Lua 5.4 with a memory cap, an instruction watchdog, no `io`/`os`/`load`, and a seeded `rand` | `sandbox.c`, `rand.c` | Done |
| Script API | The functions modes call | `script_api.c` | Done (including `field.*` from Phase C) |
| Event codec | An event and its JSON data to the CBOR payload of an EVENT message, and back; plain JSON objects to CBOR maps (CMD parameters) | `codec.h`, `codec.c` | Done |
| Packet layer | Header, nonce, AAD, AES-128-CCM (mbedtls), flood dedupe, ACK tracker, duty cycle | `packet.h`, `flood.h`, `ack.h`, `duty_cycle.h` | Done (phase 2A) |
| Message codec | The payloads of HELLO, ACK, STATE, CMD, TIME, CONFIG and CLAIM, exactly as `protocol/schema/messages.yaml` defines them: required fields always written and checked, schema types (arrays, maps), duplicate keys and oversize values rejected | `msg_codec.h`, `msg_codec.c` | Done (made schema-exact in phase 2D: it had disagreed with the shared vectors for HELLO, STATE, CMD, TIME and CLAIM) |
| Join payload | The payload that brings a box or a standby controller into a game (`protocol/join.md`): CBOR body, HMAC-SHA256 tag with the field join key, NFC (NDEF on a Type 2 tag) and text (`atalaia:join:` base64url) forms, with its own SHA-256 and HMAC (no crypto library needed) | `join.h`, `join.c` | Done (phase 2E; RFC 4231 known answers and the shared vectors in `protocol/vectors/join.json`) |
| Player tags | The signed NFC tag of a player (`protocol/nfc-tag.md`): payload with a 16-byte HMAC-SHA256 under the game key, NDEF record, and the `nfc.tag` data a host gives the node after checking a tag (scripts never see the key) | `tag.h`, `tag.c` | Done (phase 3, plan phase A; shared vectors `protocol/vectors/tag.json`) |
| Screen templates | Declarative screens (ADR-P3-4): a parser for the YAML subset the templates use, the template checks, and the `{expressions}` (data, `params.*`, arithmetic, comparisons, `&&`/`||`, `|clock`/`|upper`/`|int`). No allocation: a template lives in its `atalaia_tpl_t` (about 6 KB). The Field Box's LVGL renderer and the simulator's checks use it | `screen_template.h`, `screen_template.c` | Done (phase 3, plan phase A) |
| Capability proxy | The I/O pod's IDENT, EVT, CMD and ACK payloads (`protocol/capability-proxy.md`); the frames around them are the USB modem's | `proxy.h`, `proxy.c` | Done (phase 3, plan phase A; shared vectors `protocol/vectors/capability_proxy.yaml`; RADIO_NOISE `0x0B` added in plan phase F; RADIO_FIELD_TX/RX/ACK `0x0C`-`0x0E` and IDENT keys 6-8 `field_frames`, `pair_frames`, `measure` added by PE24-100/101); the pod firmware: `firmware/esp32/main/pod/` (plan phase F) |
| Geo utilities | `geo.distance()` (haversine, metres) and `geo.in_zone()` (circle or polygon of up to 32 points) for node and field scripts (ADR-P4-9). Only `+ - * /` and `sqrt`, with its own sine, cosine and arc tangent and `-ffp-contract=off`, so every platform gives the same bits (decision M3-1) | `geo.h`, `geo.c` | Done (phase 4, plan phase 3; known answers from Rosetta Code and GeographicLib and determinism pins in `protocol/vectors/geo.json`; the same bits checked on x86-64, arm64 and armv7 with gcc and clang, and on the ESP32 and ESP32-S3 in QEMU) |
| Event log | Append-only log with merge and replay | | Planned |

## How a host uses it

One `atalaia_node_t` runs one mode's `node.lua`. The host owns the clock and the hardware. It feeds the node input events and game time, and the node calls back with emitted events, hardware commands and log lines. The core never reads a real clock and never blocks, which is what makes a game replayable from its inputs. The full API is in [`include/atalaia/node.h`](include/atalaia/node.h).

```c
atalaia_node_config_t cfg = {
    .node_id = 1, .game_seed = seed, .callbacks = cb,
    .field_ops = &my_field_ops  /* Phase 2: field-level state and comms */
};
atalaia_node_t *node = atalaia_node_create(&cfg);
atalaia_node_set_teams(node, (const char *[]){"red", "blue"}, 2);
atalaia_node_set_params(node, "{\"fuse_s\": 300}");
atalaia_node_load(node, source, source_len, "@bomb/node.lua");
atalaia_node_input(node, "game.start", NULL);
atalaia_node_input(node, "team_input.hold", "{\"team\":\"red\",\"ms\":5000}");
atalaia_node_advance(node, now_ms);
```

A host that keeps a game across a power loss saves the script's `state.node` with `atalaia_node_state_save` (JSON) and the score counters, and on resume calls `atalaia_node_state_restore` before `atalaia_node_load`, then `atalaia_node_resume_at` to set the time without replaying it, and `atalaia_node_score_restore` (decision HB-7; modes/README.md, "After a power loss").

## Sandbox limits

| Limit | Default | When it trips |
| --- | --- | --- |
| Script memory | 256 KB (set 64 KB for the Reduced tier) | The node halts with "memory limit exceeded" |
| Instructions per callback | 1,000,000 | The node halts; catching the error with `pcall` does not help |
| Events per input or timer step | 256 | The node halts (a handler that emits what it handles) |
| Timers | 32 | `every`/`after` raise an error |

`emit()` gives a standard event the priority the schema sets for it unless the script passes `{ prio = ... }`; custom events default to `normal`.

A halted node emits `script.halted` and shows the `paused` screen. An ordinary error in a handler emits `script.error` and the node keeps running. Time spent inside Lua's C library functions (for example a very slow string pattern) is not counted by the instruction watchdog yet.

Two of Lua's own features run script code with debug hooks off, where the watchdog cannot stop it, so the sandbox changes them (decision P5C-15): `setmetatable` refuses a metatable with a `__gc` field (finalizers run with hooks off; a `__gc` added later is never called, as in Lua), and `xpcall` calls its message handler after the protected call has unwound, with the watchdog on (Lua calls it at the error, with hooks off when the error is the watchdog's own); unlike Lua's, this `xpcall` cannot yield across the call.

**The sandbox-escape battery** ([`tests/test_sandbox_escape.c`](tests/test_sandbox_escape.c), its own program and ctest `sandbox_escape`; phase 5 plan phase 5): 43 scripts that try to leave the sandbox (removed globals by any name, loaders hidden in other functions, the string metatable, environment swaps, bytecode however it is wrapped), to run without limits (busy and tail-call loops, coroutines, `pcall` and `xpcall` around the watchdog, loops in `__tostring`, `__close`, sort comparators, `gsub` callbacks and finalizers, memory by strings, tables, coroutines, concatenation and handlers) or to crash the runtime (deep recursion, the C stack through `pcall` and metamethods, yields from where they cannot go, odd error objects, cycles, deep tables and metamethods in what the API encodes, NUL bytes and long strings, extreme timers and numbers, polygon shapes, patterns and formats, field ops with odd ids and answers), each as a box's script (64 KB and 256 KB) and as a field controller's; nothing may escape, crash or leak, and each ends as expected (running, or halted by the sandbox). CI runs it under ASan and UBSan (jobs `sanitizers` and `sandbox-escape`); `simulator/tests/test_sandbox_escape.py` runs escape attempts through the ctypes bindings and a whole mode in the simulator.

## Build and test

```sh
cmake -S core -B build -DATALAIA_SHARED=ON
cmake --build build
ctest --test-dir build --output-on-failure
```

`ATALAIA_SHARED=ON` also builds the shared library the [simulator](../simulator/) and the [app](../app/) load. To run everything CI runs, including the game mode tests, use [`tools/check.sh`](../tools/check.sh). On a machine without a C compiler, run it in the [dev container](../tools/dev/Dockerfile).

Other options: `ATALAIA_STUB=ON` builds `libatalaia_core_stub`, the FFI stub ([`tests/stub.c`](tests/stub.c)): every function of `node.h` with fixed behaviour and no Lua, plus `atalaia_stub_layout()`, the C structs' sizes and offsets that the Dart and Python bindings are checked against. `ATALAIA_MBEDTLS=OFF` leaves mbedtls out even when it is installed (the app's test libraries and Android).

For Android, [`CMakePresets.json`](CMakePresets.json) cross-compiles the shared library with the NDK in `$ANDROID_NDK_HOME` (presets `android-arm64-v8a`, `android-armeabi-v7a`, `android-x86_64`; `python tools/docker_app.py ndk` runs them in Docker with the pinned NDK); the app's Gradle build compiles the same way into the APK.

A host's callbacks run inside the core's calls, and the pointers they receive (the event, the JSON strings) are only valid until the callback returns; a field operation's `owner()` answer must stay valid until the next `owner()` call ([`field_ops.h`](include/atalaia/field_ops.h)).

`protocol.h`, `protocol.c`, `tests/protocol_vectors.h`, `tests/packet_vectors.h`, `tests/proxy_vectors.h` and `tests/geo_vectors.h` are generated by [`tools/protogen.py`](../tools/protogen.py); edit the schema instead (see [protocol/README.md](../protocol/README.md#changing-the-schema)).

Rules: C11, no dynamic allocation outside the configured allocator (the host can point it at PSRAM on ESP32), public symbols prefixed `atalaia_`, warnings are errors.
