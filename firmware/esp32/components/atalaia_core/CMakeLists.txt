# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# IDF component wrapper for the Atalaia core library.
# Sources live in core/ at the repository root; this CMakeLists.txt
# references them via a relative path so the IDF build picks them up
# without copying.

get_filename_component(CORE_ROOT "${CMAKE_CURRENT_LIST_DIR}/../../../../core" ABSOLUTE)
get_filename_component(LUA_DIR "${CORE_ROOT}/third_party/lua" ABSOLUTE)

set(CORE_SOURCES
    "${CORE_ROOT}/src/version.c"
    "${CORE_ROOT}/src/protocol.c"
    "${CORE_ROOT}/src/event.c"
    "${CORE_ROOT}/src/codec.c"
    "${CORE_ROOT}/src/score.c"
    "${CORE_ROOT}/src/rand.c"
    "${CORE_ROOT}/src/json.c"
    "${CORE_ROOT}/src/sandbox.c"
    "${CORE_ROOT}/src/script_api.c"
    "${CORE_ROOT}/src/node.c"
    "${CORE_ROOT}/src/packet.c"
    "${CORE_ROOT}/src/flood.c"
    "${CORE_ROOT}/src/ack.c"
    "${CORE_ROOT}/src/duty_cycle.c"
    "${CORE_ROOT}/src/msg_codec.c"
    "${CORE_ROOT}/src/crypto_mbedtls.c"
)

# Vendored Lua 5.4 -- only the libraries the sandbox opens.
# lstate.c is replaced by core/src/lua_lstate.c (deterministic hash seed).
set(LUA_SOURCES
    "${LUA_DIR}/lapi.c"
    "${LUA_DIR}/lcode.c"
    "${LUA_DIR}/lctype.c"
    "${LUA_DIR}/ldebug.c"
    "${LUA_DIR}/ldo.c"
    "${LUA_DIR}/ldump.c"
    "${LUA_DIR}/lfunc.c"
    "${LUA_DIR}/lgc.c"
    "${LUA_DIR}/llex.c"
    "${LUA_DIR}/lmem.c"
    "${LUA_DIR}/lobject.c"
    "${LUA_DIR}/lopcodes.c"
    "${LUA_DIR}/lparser.c"
    "${LUA_DIR}/lstring.c"
    "${LUA_DIR}/ltable.c"
    "${LUA_DIR}/ltm.c"
    "${LUA_DIR}/lundump.c"
    "${LUA_DIR}/lvm.c"
    "${LUA_DIR}/lzio.c"
    "${LUA_DIR}/lauxlib.c"
    "${LUA_DIR}/lbaselib.c"
    "${LUA_DIR}/lcorolib.c"
    "${LUA_DIR}/lmathlib.c"
    "${LUA_DIR}/lstrlib.c"
    "${LUA_DIR}/ltablib.c"
    "${LUA_DIR}/lutf8lib.c"
    "${CORE_ROOT}/src/lua_lstate.c"
)

idf_component_register(
    SRCS
        ${CORE_SOURCES}
        ${LUA_SOURCES}
    INCLUDE_DIRS
        "${CORE_ROOT}/include"
        "${LUA_DIR}"
    PRIV_INCLUDE_DIRS
        "${CORE_ROOT}/src"
    REQUIRES
        mbedtls
)

# The IDF build always has mbedtls; enable the real AES-CCM backend.
target_compile_definitions(${COMPONENT_LIB} PUBLIC ATALAIA_HAVE_MBEDTLS)

# Lua runs with its default 64-bit integers and doubles, matching the
# desktop core and the simulator.  This guarantees scripts behave
# identically everywhere (replays, scores, integer overflow).
# The cost is ~4 bytes more per Lua number; with 2 MB PSRAM this is
# not a concern.  See ADR-P1-8 and IMPLEMENTATION.md.
