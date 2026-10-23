# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

cmake_minimum_required(VERSION 3.16)
# The numbers of core/include/atalaia/version.h (CMake keeps no pre-release).
project(atalaia_core VERSION 0.4.0 LANGUAGES C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

option(ATALAIA_SHARED "Also build the core as a shared library (used by the simulator and the app)" OFF)
option(ATALAIA_STUB "Also build libatalaia_core_stub, the FFI stub the app's Dart tests load" OFF)
option(ATALAIA_MBEDTLS "Use mbedtls for real AES-128-CCM when it is installed" ON)
# The scenario validator and compiler (decision PE24-109): Lua sources in core/scenario/, embedded.
# The Pi's and the phone's controllers use it; the Field Box does not compile scenarios, and its
# firmware (firmware/esp32/components/atalaia_core) lists the core's sources without it.
option(ATALAIA_SCENARIO "Build the scenario compiler (core/scenario) into the core" ON)

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

# ---- Optional: mbedtls for real AES-128-CCM --------------------------------
# -DATALAIA_MBEDTLS=OFF leaves it out even when it is installed: the shared
# library the app's tests load then runs where libmbedcrypto is missing, and
# the Android build (which has no mbedtls) is the same on every machine.
if(ATALAIA_MBEDTLS)
    find_library(MBEDCRYPTO_LIB mbedcrypto)
    find_path(MBEDTLS_INCLUDE_DIR mbedtls/ccm.h)
endif()
if(ATALAIA_MBEDTLS AND MBEDCRYPTO_LIB AND MBEDTLS_INCLUDE_DIR)
    set(ATALAIA_HAVE_MBEDTLS ON)
    message(STATUS "mbedtls found: real AES-CCM backend enabled")
else()
    set(ATALAIA_HAVE_MBEDTLS OFF)
    message(STATUS "mbedtls not found: building without real AES-CCM (test stub only)")
endif()

# ---- Core ------------------------------------------------------------------
set(ATALAIA_CORE_SOURCES
    src/version.c
    src/protocol.c
    src/event.c
    src/codec.c
    src/score.c
    src/rand.c
    src/json.c
    src/sandbox.c
    src/script_api.c
    src/node.c
    src/packet.c
    src/flood.c
    src/ack.c
    src/duty_cycle.c
    src/msg_codec.c
    src/join.c
    src/field_frame.c
    src/pair_frame.c
    src/tag.c
    src/screen_template.c
    src/proxy.c
    src/geo.c
)
if(ATALAIA_HAVE_MBEDTLS)
    list(APPEND ATALAIA_CORE_SOURCES src/crypto_mbedtls.c)
endif()
if(ATALAIA_SCENARIO)
    # The Lua sources become a C file in the build folder whenever one changes.
    set(ATALAIA_SCENARIO_LUA
        scenario/unicode.lua scenario/py.lua scenario/tree.lua scenario/manifest.lua
        scenario/protocol.lua scenario/luagen.lua scenario/yaml.lua scenario/package.lua
        scenario/validator.lua scenario/main.lua scenario/runtime.lua)
    list(TRANSFORM ATALAIA_SCENARIO_LUA PREPEND ${CMAKE_CURRENT_SOURCE_DIR}/)
    string(REPLACE ";" "|" ATALAIA_SCENARIO_ARG "${ATALAIA_SCENARIO_LUA}")
    set(ATALAIA_SCENARIO_C ${CMAKE_CURRENT_BINARY_DIR}/scenario_sources.c)
    add_custom_command(
        OUTPUT ${ATALAIA_SCENARIO_C}
        COMMAND ${CMAKE_COMMAND} -DOUT=${ATALAIA_SCENARIO_C} -DSOURCES=${ATALAIA_SCENARIO_ARG}
                -P ${CMAKE_CURRENT_SOURCE_DIR}/cmake/embed_scenario.cmake
        DEPENDS ${ATALAIA_SCENARIO_LUA} ${CMAKE_CURRENT_SOURCE_DIR}/cmake/embed_scenario.cmake
        COMMENT "Embedding the scenario compiler's Lua sources"
        VERBATIM)
    # One target writes it, so that the static and the shared core never write it at once.
    add_custom_target(atalaia_scenario_embed DEPENDS ${ATALAIA_SCENARIO_C})
    list(APPEND ATALAIA_CORE_SOURCES src/scenario.c ${ATALAIA_SCENARIO_C})
endif()
# geo.c must give the same bits everywhere (decision M3-1): no fused
# multiply-add (clang contracts a * b + c by default, and arm64 has FMA).
if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    set_source_files_properties(src/geo.c PROPERTIES COMPILE_OPTIONS -ffp-contract=off)
endif()

function(atalaia_core_target name type)
    add_library(${name} ${type} ${ATALAIA_CORE_SOURCES})
    if(ATALAIA_SCENARIO)
        add_dependencies(${name} atalaia_scenario_embed)
    endif()
    target_include_directories(${name} PUBLIC include PRIVATE src)
    target_link_libraries(${name} PRIVATE atalaia_lua)
    if(MATH_LIBRARY)
        target_link_libraries(${name} PRIVATE ${MATH_LIBRARY}) # sqrt in geo.c
    endif()
    if(ATALAIA_HAVE_MBEDTLS)
        target_compile_definitions(${name} PUBLIC ATALAIA_HAVE_MBEDTLS)
        target_include_directories(${name} PRIVATE ${MBEDTLS_INCLUDE_DIR})
        target_link_libraries(${name} PRIVATE ${MBEDCRYPTO_LIB})
    endif()
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

# ---- FFI stub (ADR-P3-11) ---------------------------------------------------
# Every function of node.h with predictable behaviour and no Lua (tests/stub.c),
# for the app's Dart tests of the bridge itself.
if(ATALAIA_STUB)
    add_library(atalaia_core_stub SHARED tests/stub.c)
    target_include_directories(atalaia_core_stub PRIVATE include)
    if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
        target_compile_options(atalaia_core_stub PRIVATE -Wall -Wextra -Wpedantic -Werror)
    endif()
endif()

# ---- Tests -----------------------------------------------------------------
include(CTest)
if(BUILD_TESTING)
    add_executable(test_core
        tests/test_core.c tests/test_node.c tests/test_codec.c
        tests/test_packet.c tests/test_flood.c tests/test_ack.c
        tests/test_duty_cycle.c tests/test_msg_codec.c
        tests/test_crypto_mbedtls.c tests/test_field_api.c tests/test_join.c
        tests/test_tag.c tests/test_field_frame.c tests/test_pair_frame.c tests/test_screen_template.c
        tests/test_proxy.c tests/test_geo.c)
    target_include_directories(test_core PRIVATE src)
    target_link_libraries(test_core PRIVATE atalaia_core)
    if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
        target_compile_options(test_core PRIVATE -Wall -Wextra -Wpedantic -Werror)
    endif()
    add_test(NAME core COMMAND test_core)

    # The sandbox-escape battery (phase 5 plan phase 5): its own program, so that CI's
    # sandbox-escape job can run it alone.
    add_executable(test_sandbox_escape tests/test_sandbox_escape.c)
    target_include_directories(test_sandbox_escape PRIVATE src)
    target_link_libraries(test_sandbox_escape PRIVATE atalaia_core)
    if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
        target_compile_options(test_sandbox_escape PRIVATE -Wall -Wextra -Wpedantic -Werror)
    endif()
    add_test(NAME sandbox_escape COMMAND test_sandbox_escape)

    # The scenario compiler's entry points, limits and malformed or mutated data trees.
    if(ATALAIA_SCENARIO)
        add_executable(test_scenario tests/test_scenario.c)
        target_include_directories(test_scenario PRIVATE src)
        target_link_libraries(test_scenario PRIVATE atalaia_core)
        if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
            target_compile_options(test_scenario PRIVATE -Wall -Wextra -Wpedantic -Werror)
        endif()
        add_test(NAME scenario COMMAND test_scenario)
    endif()
endif()
