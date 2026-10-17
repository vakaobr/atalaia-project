# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

cmake_minimum_required(VERSION 3.16)
project(atalaia_core VERSION 0.1.0 LANGUAGES C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

option(ATALAIA_SHARED "Also build the core as a shared library (used by the simulator)" OFF)

# ---- Lua 5.4 (vendored, MIT) -----------------------------------------------
# Only the libraries the sandbox opens are compiled: no io, os, package,
# debug or the standalone interpreter.
set(LUA_DIR third_party/lua)
# lstate.c is built through src/lua_lstate.c, which fixes the hash seed.
add_library(atalaia_lua STATIC
    ${LUA_DIR}/lapi.c ${LUA_DIR}/lcode.c ${LUA_DIR}/lctype.c ${LUA_DIR}/ldebug.c
    ${LUA_DIR}/ldo.c ${LUA_DIR}/ldump.c ${LUA_DIR}/lfunc.c ${LUA_DIR}/lgc.c
    ${LUA_DIR}/llex.c ${LUA_DIR}/lmem.c ${LUA_DIR}/lobject.c ${LUA_DIR}/lopcodes.c
    ${LUA_DIR}/lparser.c src/lua_lstate.c ${LUA_DIR}/lstring.c ${LUA_DIR}/ltable.c
    ${LUA_DIR}/ltm.c ${LUA_DIR}/lundump.c ${LUA_DIR}/lvm.c ${LUA_DIR}/lzio.c
    ${LUA_DIR}/lauxlib.c ${LUA_DIR}/lbaselib.c ${LUA_DIR}/lcorolib.c
    ${LUA_DIR}/lmathlib.c ${LUA_DIR}/lstrlib.c ${LUA_DIR}/ltablib.c
    ${LUA_DIR}/lutf8lib.c
)
target_include_directories(atalaia_lua PUBLIC ${LUA_DIR})
find_library(MATH_LIBRARY m)
if(MATH_LIBRARY)
    target_link_libraries(atalaia_lua PUBLIC ${MATH_LIBRARY})
endif()

# ---- Core ------------------------------------------------------------------
set(ATALAIA_CORE_SOURCES
    src/version.c
    src/event.c
    src/score.c
    src/rand.c
    src/json.c
    src/sandbox.c
    src/script_api.c
    src/node.c
)

function(atalaia_core_target name type)
    add_library(${name} ${type} ${ATALAIA_CORE_SOURCES})
    target_include_directories(${name} PUBLIC include PRIVATE src)
    target_link_libraries(${name} PRIVATE atalaia_lua)
    if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
        target_compile_options(${name} PRIVATE -Wall -Wextra -Wpedantic -Werror)
    endif()
endfunction()

atalaia_core_target(atalaia_core STATIC)

if(ATALAIA_SHARED)
    atalaia_core_target(atalaia_core_shared SHARED)
    set_target_properties(atalaia_core_shared PROPERTIES
        OUTPUT_NAME atalaia_core
        WINDOWS_EXPORT_ALL_SYMBOLS ON)
endif()

# ---- Tests -----------------------------------------------------------------
include(CTest)
if(BUILD_TESTING)
    add_executable(test_core tests/test_core.c tests/test_node.c)
    target_include_directories(test_core PRIVATE src)
    target_link_libraries(test_core PRIVATE atalaia_core)
    if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
        target_compile_options(test_core PRIVATE -Wall -Wextra -Wpedantic -Werror)
    endif()
    add_test(NAME core COMMAND test_core)
endif()
