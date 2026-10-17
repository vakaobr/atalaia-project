# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

cmake_minimum_required(VERSION 3.16)
project(atalaia_firmware_test LANGUAGES C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

# Default to repository-relative paths so `cmake -S firmware/esp32/test -B build`
# works from the repo root without extra -D flags, as CI does.
set(CORE_DIR "${CMAKE_CURRENT_LIST_DIR}/../../../core" CACHE PATH "Path to core/")
set(MODES_DIR "${CMAKE_CURRENT_LIST_DIR}/../../../modes" CACHE PATH "Path to modes/")

# ---- Lua 5.4 (vendored, MIT) ------------------------------------------------
# Built as a separate static library without -Wpedantic because Lua uses
# GCC computed gotos (goto *expr) which are a non-standard extension.
# lstate.c is replaced by core/src/lua_lstate.c (deterministic hash seed).
set(LUA_DIR ${CORE_DIR}/third_party/lua)
add_library(atalaia_lua_fw STATIC
    ${LUA_DIR}/lapi.c ${LUA_DIR}/lcode.c ${LUA_DIR}/lctype.c ${LUA_DIR}/ldebug.c
    ${LUA_DIR}/ldo.c ${LUA_DIR}/ldump.c ${LUA_DIR}/lfunc.c ${LUA_DIR}/lgc.c
    ${LUA_DIR}/llex.c ${LUA_DIR}/lmem.c ${LUA_DIR}/lobject.c ${LUA_DIR}/lopcodes.c
    ${LUA_DIR}/lparser.c ${CORE_DIR}/src/lua_lstate.c ${LUA_DIR}/lstring.c
    ${LUA_DIR}/ltable.c ${LUA_DIR}/ltm.c ${LUA_DIR}/lundump.c ${LUA_DIR}/lvm.c
    ${LUA_DIR}/lzio.c ${LUA_DIR}/lauxlib.c ${LUA_DIR}/lbaselib.c
    ${LUA_DIR}/lcorolib.c ${LUA_DIR}/lmathlib.c ${LUA_DIR}/lstrlib.c
    ${LUA_DIR}/ltablib.c ${LUA_DIR}/lutf8lib.c
)
target_include_directories(atalaia_lua_fw PUBLIC ${LUA_DIR})
find_library(MATH_LIBRARY m)
if(MATH_LIBRARY)
    target_link_libraries(atalaia_lua_fw PUBLIC ${MATH_LIBRARY})
endif()

# ---- Core sources (static library) ------------------------------------------
set(CORE_SOURCES
    ${CORE_DIR}/src/version.c
    ${CORE_DIR}/src/protocol.c
    ${CORE_DIR}/src/event.c
    ${CORE_DIR}/src/codec.c
    ${CORE_DIR}/src/score.c
    ${CORE_DIR}/src/rand.c
    ${CORE_DIR}/src/json.c
    ${CORE_DIR}/src/sandbox.c
    ${CORE_DIR}/src/script_api.c
    ${CORE_DIR}/src/node.c
)
add_library(atalaia_core_fw STATIC ${CORE_SOURCES})
target_include_directories(atalaia_core_fw PUBLIC ${CORE_DIR}/include PRIVATE ${CORE_DIR}/src)
target_link_libraries(atalaia_core_fw PRIVATE atalaia_lua_fw)
if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(atalaia_core_fw PRIVATE -Wall -Wextra -Wpedantic -Werror)
endif()

# ---- Shell sources (testable subset) -----------------------------------------
set(SHELL_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../main)
set(SHELL_SOURCES
    ${SHELL_DIR}/game_timer.c
    ${SHELL_DIR}/command_dispatch.c
    ${SHELL_DIR}/preset_store.c
    ${SHELL_DIR}/state_persist.c
    ${SHELL_DIR}/node_runner.c
    ${SHELL_DIR}/screen_renderer.c
    ${SHELL_DIR}/preset_ui.c
    ${SHELL_DIR}/config_store.c
    ${SHELL_DIR}/wifi_setup.c
    ${SHELL_DIR}/button_tracker.c
)

# ---- HAL stub ----------------------------------------------------------------
set(HAL_SOURCES
    ${SHELL_DIR}/hal/stub/hal_stub.c
)

# ---- Test sources ------------------------------------------------------------
set(TEST_SOURCES
    test_main.c
    test_game_timer.c
    test_command_dispatch.c
    test_preset_store.c
    test_state_persist.c
    test_node_runner.c
    test_preset_ui.c
    test_config_store.c
    test_integration.c
    test_game_loop.c
    test_wifi_setup.c
    test_reboot_resume.c
    test_screen_renderer.c
)

# ---- Executable --------------------------------------------------------------
add_executable(firmware_test
    ${SHELL_SOURCES}
    ${HAL_SOURCES}
    ${TEST_SOURCES}
)

target_include_directories(firmware_test PRIVATE
    ${CORE_DIR}/include
    ${CORE_DIR}/third_party/lua
    ${CORE_DIR}/src
    ${SHELL_DIR}
    ${CMAKE_CURRENT_SOURCE_DIR}
)

target_link_libraries(firmware_test PRIVATE atalaia_core_fw atalaia_lua_fw)

if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(firmware_test PRIVATE -Wall -Wextra -Wpedantic -Werror)
endif()

# MODES_DIR is needed by test_game_loop.c to find the real mode scripts.
if(MODES_DIR)
    target_compile_definitions(firmware_test PRIVATE "MODES_DIR=\"${MODES_DIR}\"")
endif()

# ---- CTest -------------------------------------------------------------------
include(CTest)
add_test(NAME firmware COMMAND firmware_test)
