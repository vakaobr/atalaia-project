# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# The host box: a Field Box's game and radio logic (main/box_game.c,
# main/radio/field_link.c and what they use) with the real core and
# mbedtls AES-CCM, on Linux, for the controller's end-to-end tests.
#   cmake -S firmware/esp32/test/box_host -B build/box_host
#   cmake --build build/box_host
cmake_minimum_required(VERSION 3.18)
project(atalaia_box_host LANGUAGES C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

get_filename_component(CORE_DIR "${CMAKE_CURRENT_LIST_DIR}/../../../../core" ABSOLUTE)
get_filename_component(MAIN_DIR "${CMAKE_CURRENT_LIST_DIR}/../../main" ABSOLUTE)

find_library(MBEDCRYPTO_LIB mbedcrypto)
find_path(MBEDTLS_INCLUDE_DIR mbedtls/ccm.h)
if(NOT MBEDCRYPTO_LIB OR NOT MBEDTLS_INCLUDE_DIR)
    message(FATAL_ERROR "The host box needs mbedtls for real AES-CCM "
        "(Debian/Ubuntu: apt install libmbedtls-dev; the atalaia-dev image has it).")
endif()

# The core as the device builds it (mbedtls found above, so AES-CCM is real).
set(BUILD_TESTING OFF CACHE BOOL "" FORCE)
# The core's own default is off on macOS (Homebrew's mbedtls is not 2.28); this
# program needs the real AES-CCM, so it asks (Linux's default is already ON).
set(ATALAIA_MBEDTLS ON CACHE BOOL "" FORCE)
add_subdirectory(${CORE_DIR} core)

add_executable(box_host
    box_host.c
    ${MAIN_DIR}/box_game.c
    ${MAIN_DIR}/box_lobby.c
    ${MAIN_DIR}/box_text.c
    ${MAIN_DIR}/serial_console.c
    ${MAIN_DIR}/node_runner.c
    ${MAIN_DIR}/command_dispatch.c
    ${MAIN_DIR}/game_timer.c
    ${MAIN_DIR}/state_persist.c
    ${MAIN_DIR}/preset_store.c
    ${MAIN_DIR}/builtin_presets.c
    ${MAIN_DIR}/button_tracker.c
    ${MAIN_DIR}/radio/field_link.c
    ${MAIN_DIR}/radio/radio_protocol.c
    ${MAIN_DIR}/radio/radio_task.c
    ${MAIN_DIR}/radio/radio_lbt.c
    ${MAIN_DIR}/radio/event_log.c
    ${MAIN_DIR}/radio/time_sync.c
    ${MAIN_DIR}/radio/noise_stats.c
    ${MAIN_DIR}/radio/radio_stats.c
    ${MAIN_DIR}/radio/channel_busy.c
    ${MAIN_DIR}/hal/stub/hal_stub.c
    ${MAIN_DIR}/hal/stub/hal_radio_stub.c
    ${MAIN_DIR}/fw_update.c
    ${MAIN_DIR}/mode_package.c
    ${MAIN_DIR}/mode_store.c
    ${MAIN_DIR}/mode_fetch.c
    ${MAIN_DIR}/admin_pin.c
    ${MAIN_DIR}/adoption.c
    ${MAIN_DIR}/cpace.c
    ${MAIN_DIR}/box_pair.c
    ${MAIN_DIR}/screen_json.c
)
# Monocypher (components/monocypher): fw_update.c's Ed25519.
set(MONOCYPHER_DIR ${CMAKE_CURRENT_LIST_DIR}/../../components/monocypher/src)
add_library(box_host_monocypher STATIC ${MONOCYPHER_DIR}/monocypher.c
    ${MONOCYPHER_DIR}/optional/monocypher-ed25519.c)
target_include_directories(box_host_monocypher PUBLIC ${MONOCYPHER_DIR} ${MONOCYPHER_DIR}/optional)
target_link_libraries(box_host PRIVATE box_host_monocypher)
target_include_directories(box_host PRIVATE ${MAIN_DIR} ${MAIN_DIR}/radio ${CORE_DIR}/src)
target_link_libraries(box_host PRIVATE atalaia_core)
if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(box_host PRIVATE -Wall -Wextra -Wpedantic)
    # Not an error on macOS: Apple's Clang is not a compiler CI builds with
    # (as the core's ATALAIA_WERROR). Linux is unchanged.
    if(NOT APPLE)
        target_compile_options(box_host PRIVATE -Werror)
    endif()
endif()
