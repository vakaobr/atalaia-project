# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

cmake_minimum_required(VERSION 3.18)
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
    ${CORE_DIR}/src/packet.c
    ${CORE_DIR}/src/flood.c
    ${CORE_DIR}/src/lbt.c
    ${CORE_DIR}/src/ack.c
    ${CORE_DIR}/src/duty_cycle.c
    ${CORE_DIR}/src/msg_codec.c
    ${CORE_DIR}/src/join.c
    ${CORE_DIR}/src/field_frame.c
    ${CORE_DIR}/src/pair_frame.c
    ${CORE_DIR}/src/tag.c
    ${CORE_DIR}/src/screen_template.c
    ${CORE_DIR}/src/proxy.c
    ${CORE_DIR}/src/geo.c
)
# As in core/CMakeLists.txt (decision M3-1).
set_source_files_properties(${CORE_DIR}/src/geo.c PROPERTIES COMPILE_OPTIONS -ffp-contract=off)
add_library(atalaia_core_fw STATIC ${CORE_SOURCES})
target_include_directories(atalaia_core_fw PUBLIC ${CORE_DIR}/include PRIVATE ${CORE_DIR}/src)
target_link_libraries(atalaia_core_fw PRIVATE atalaia_lua_fw)
if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(atalaia_core_fw PRIVATE -Wall -Wextra -Wpedantic -Werror)
endif()

# ---- LVGL 9.2.2 (fetched; the version the device builds) ---------------------
# The device gets LVGL from the ESP component registry (dependencies.lock);
# the host fetches the same release from the official GitHub tag, checked by
# hash. The GitHub tag's src/ is identical to the registry package's.
set(ATALAIA_LVGL_VERSION 9.2.2)
set(ATALAIA_LVGL_SHA256 129b4e00e06639fa79d7e8a6cab3c1ecce2445b1a246652ccd34f22e7b17ad6f)
file(READ "${CMAKE_CURRENT_LIST_DIR}/../dependencies.lock" FW_LOCK)
string(FIND "${FW_LOCK}" "\n  lvgl/lvgl:" LOCK_LVGL_POS)
if(LOCK_LVGL_POS LESS 0)
    message(FATAL_ERROR "lvgl/lvgl is missing from firmware/esp32/dependencies.lock")
endif()
string(SUBSTRING "${FW_LOCK}" ${LOCK_LVGL_POS} -1 FW_LOCK_LVGL)
string(REGEX MATCH "\n    version: ([0-9.]+)" _ "${FW_LOCK_LVGL}")
if(NOT CMAKE_MATCH_1 STREQUAL ATALAIA_LVGL_VERSION)
    message(FATAL_ERROR "The device uses LVGL ${CMAKE_MATCH_1} (dependencies.lock) but the "
        "host tests fetch ${ATALAIA_LVGL_VERSION}; update ATALAIA_LVGL_VERSION and its hash.")
endif()

if(POLICY CMP0135)
    cmake_policy(SET CMP0135 NEW)
endif()
include(FetchContent)
FetchContent_Declare(lvgl
    URL "https://github.com/lvgl/lvgl/archive/refs/tags/v${ATALAIA_LVGL_VERSION}.tar.gz"
    URL_HASH SHA256=${ATALAIA_LVGL_SHA256}
    # Only download: the sources are built below with the shared lv_conf.h.
    SOURCE_SUBDIR do-not-add-subdirectory
)
FetchContent_MakeAvailable(lvgl)

# One lv_conf.h for the device and the host, so both render alike.
set(LVGL_CONF_DIR "${CMAKE_CURRENT_LIST_DIR}/../lvgl_conf")
file(GLOB_RECURSE LVGL_SOURCES CONFIGURE_DEPENDS "${lvgl_SOURCE_DIR}/src/*.c")
# lv_conf.h's LV_FONT_CUSTOM_DECLARE: the box's fonts (main/fonts, tools/gen_box_fonts.py).
file(GLOB ATALAIA_FONTS CONFIGURE_DEPENDS "${CMAKE_CURRENT_LIST_DIR}/../main/fonts/*.c")
add_library(atalaia_lvgl_host STATIC ${LVGL_SOURCES} ${ATALAIA_FONTS})
target_include_directories(atalaia_lvgl_host SYSTEM PUBLIC "${lvgl_SOURCE_DIR}" "${LVGL_CONF_DIR}")
target_compile_definitions(atalaia_lvgl_host PUBLIC LV_CONF_INCLUDE_SIMPLE LV_KCONFIG_IGNORE)
# Third-party code: built without the project's warning flags, like the vendored Lua.
target_compile_options(atalaia_lvgl_host PRIVATE -w)

# ---- Screen renderer (same source and LVGL widget trees as the device) -------
# With the screen templates of modes/ built in, as main/CMakeLists.txt does.
include(${CMAKE_CURRENT_LIST_DIR}/../main/builtin_screens.cmake)
atalaia_builtin_screens("${MODES_DIR}" "${CMAKE_CURRENT_BINARY_DIR}/builtin_screens.c")
add_library(atalaia_screens_fw STATIC
    ${CMAKE_CURRENT_SOURCE_DIR}/../main/screen_renderer.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../main/box_text.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../main/screen_json.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../main/screen_template.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../main/oled_view.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../main/oled_logo.c
    ${CMAKE_CURRENT_SOURCE_DIR}/../main/modem/modem_screen.c
    ${CMAKE_CURRENT_BINARY_DIR}/builtin_screens.c
)
target_include_directories(atalaia_screens_fw PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/../main
    ${CMAKE_CURRENT_SOURCE_DIR}/../main/hal)
target_compile_definitions(atalaia_screens_fw PUBLIC ATALAIA_SCREEN_LVGL=1)
target_link_libraries(atalaia_screens_fw PUBLIC atalaia_lvgl_host atalaia_core_fw)
if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(atalaia_screens_fw PRIVATE -Wall -Wextra -Wpedantic -Werror)
endif()

# ---- Monocypher 4.0.2 (vendored, components/monocypher): Ed25519 for firmware releases
set(MONOCYPHER_DIR ${CMAKE_CURRENT_LIST_DIR}/../components/monocypher/src)
add_library(atalaia_monocypher_host STATIC ${MONOCYPHER_DIR}/monocypher.c
    ${MONOCYPHER_DIR}/optional/monocypher-ed25519.c)
target_include_directories(atalaia_monocypher_host PUBLIC ${MONOCYPHER_DIR} ${MONOCYPHER_DIR}/optional)
if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(atalaia_monocypher_host PRIVATE -Wall -Wextra -Werror)
endif()

# ---- Shell sources (testable subset) -----------------------------------------
set(SHELL_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../main)
set(SHELL_SOURCES
    ${SHELL_DIR}/game_timer.c
    ${SHELL_DIR}/command_dispatch.c
    ${SHELL_DIR}/preset_store.c
    ${SHELL_DIR}/state_persist.c
    ${SHELL_DIR}/node_runner.c
    ${SHELL_DIR}/preset_ui.c
    ${SHELL_DIR}/config_store.c
    ${SHELL_DIR}/wifi_setup.c
    ${SHELL_DIR}/button_tracker.c
    ${SHELL_DIR}/builtin_presets.c
    ${SHELL_DIR}/key_filter.c
    ${SHELL_DIR}/radio/radio_task.c
    ${SHELL_DIR}/radio/radio_lbt.c
    ${SHELL_DIR}/radio/event_log.c
    ${SHELL_DIR}/radio/time_sync.c
    ${SHELL_DIR}/radio/radio_protocol.c
    ${SHELL_DIR}/radio/field_link.c
    ${SHELL_DIR}/radio/radio_limits.c
    ${SHELL_DIR}/radio/noise_stats.c
    ${SHELL_DIR}/radio/radio_stats.c
    ${SHELL_DIR}/radio/channel_busy.c
    ${SHELL_DIR}/radio/lbt_stats.c
    ${SHELL_DIR}/radio/lbt_profile.c
    ${SHELL_DIR}/box_game.c
    ${SHELL_DIR}/box_lobby.c
    ${SHELL_DIR}/serial_console.c
    ${SHELL_DIR}/fw_update.c
    ${SHELL_DIR}/mode_package.c
    ${SHELL_DIR}/mode_store.c
    ${SHELL_DIR}/mode_fetch.c
    ${SHELL_DIR}/admin_pin.c
    ${SHELL_DIR}/adoption.c
    ${SHELL_DIR}/cpace.c
    ${SHELL_DIR}/box_pair.c
    ${SHELL_DIR}/target_addon.c
    ${SHELL_DIR}/hal/board_fem.c
    ${SHELL_DIR}/modem/modem.c
    ${SHELL_DIR}/modem/modem_framing.c
    ${SHELL_DIR}/pod/pod.c
    ${SHELL_DIR}/pod/pod_caps.c
    ${SHELL_DIR}/pod/pod_json.c
    ${SHELL_DIR}/pod/pod_ble.c
)

# ---- HAL stub ----------------------------------------------------------------
set(HAL_SOURCES
    ${SHELL_DIR}/hal/stub/hal_stub.c
    ${SHELL_DIR}/hal/stub/hal_radio_stub.c
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
    test_oled_view.c
    test_modem_screen.c
    test_builtin_presets.c
    test_key_filter.c
    test_display.c
    test_event_log.c
    test_time_sync.c
    test_radio_stub.c
    test_radio_protocol.c
    test_radio_power.c
    test_radio_limits.c
    test_radio_stats.c
    test_lbt.c
    test_radio_lbt.c
    test_modem_framing.c
    test_modem.c
    test_field_link.c
    test_box_game.c
    test_box_text.c
    test_serial_console.c
    test_board_fem.c
    test_screen_template.c
    test_pod.c
    test_fw_update.c
    test_mode_package.c
    test_mode_fetch.c
    test_adoption.c
    test_admin_pin.c
    test_box_pair.c
    test_target_addon.c
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
    ${SHELL_DIR}/radio
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CORE_DIR}/tests # proxy_vectors.h
)

target_link_libraries(firmware_test PRIVATE atalaia_core_fw atalaia_lua_fw atalaia_screens_fw
    atalaia_monocypher_host)

if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(firmware_test PRIVATE -Wall -Wextra -Wpedantic -Werror)
endif()

# test_wifi_setup.c reads the setup page to check its texts.
target_compile_definitions(firmware_test PRIVATE "WIFI_SETUP_HTML=\"${SHELL_DIR}/wifi_setup.html\"")

# MODES_DIR is needed by test_game_loop.c to find the real mode scripts.
if(MODES_DIR)
    target_compile_definitions(firmware_test PRIVATE "MODES_DIR=\"${MODES_DIR}\"")
endif()

# ---- Screen reference images -------------------------------------------------
# Renders every template into <build>/screens/ and compares it with
# test/screens/<name>.png. ATALAIA_UPDATE_SCREENS=1 rewrites the references.
add_library(atalaia_png_test STATIC png_io.c)
target_include_directories(atalaia_png_test PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_compile_options(atalaia_png_test PRIVATE -w)
find_library(MATH_LIBRARY_PNG m)
if(MATH_LIBRARY_PNG)
    target_link_libraries(atalaia_png_test PRIVATE ${MATH_LIBRARY_PNG})
endif()

add_executable(screen_test test_screens.c test_display.c)
target_include_directories(screen_test PRIVATE ${SHELL_DIR} ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(screen_test PRIVATE atalaia_screens_fw atalaia_png_test)
target_compile_definitions(screen_test PRIVATE
    "SCREENS_REF_DIR=\"${CMAKE_CURRENT_SOURCE_DIR}/screens\""
    "SCREENS_OUT_DIR=\"${CMAKE_CURRENT_BINARY_DIR}/screens\"")
if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(screen_test PRIVATE -Wall -Wextra -Wpedantic -Werror)
endif()

# The on-board OLED's status view (and the USB radio modem's screens, modem_*),
# on its own 128x64 display: references in test/screens/oled/.
add_executable(oled_screen_test test_oled_screens.c)
target_link_libraries(oled_screen_test PRIVATE atalaia_screens_fw atalaia_png_test)
target_compile_definitions(oled_screen_test PRIVATE
    "OLED_REF_DIR=\"${CMAKE_CURRENT_SOURCE_DIR}/screens/oled\""
    "OLED_OUT_DIR=\"${CMAKE_CURRENT_BINARY_DIR}/screens/oled\"")
if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(oled_screen_test PRIVATE -Wall -Wextra -Wpedantic -Werror)
endif()

# Frames for the project page's animated game-mode pictures (tools/gen_mode_gifs.py): a script
# of screen updates drawn on the TFT and the OLED through the same code as the two tests above.
# Not a test; built with the rest so that CI's firmware-test job can run the generator's check.
add_executable(mode_gif_frames mode_gif_frames.c test_display.c)
target_include_directories(mode_gif_frames PRIVATE ${SHELL_DIR} ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(mode_gif_frames PRIVATE atalaia_screens_fw)
if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(mode_gif_frames PRIVATE -Wall -Wextra -Wpedantic -Werror)
endif()

# ---- Capability proxy frames (protocol/capability-proxy.md) ------------------
# The shared vectors through the modem framing the I/O pod reuses.
add_executable(proxy_codec_test test_proxy_codec.c ${SHELL_DIR}/modem/modem_framing.c)
target_include_directories(proxy_codec_test PRIVATE ${SHELL_DIR} ${CORE_DIR}/tests)
target_link_libraries(proxy_codec_test PRIVATE atalaia_core_fw)
if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(proxy_codec_test PRIVATE -Wall -Wextra -Wpedantic -Werror)
endif()

# ---- The I/O pod's GATT service with the Bluetooth stack stubbed --------------
add_executable(ble_gatt_stub_test test_ble_gatt_stub.c
    ${SHELL_DIR}/pod/pod.c ${SHELL_DIR}/pod/pod_ble.c ${SHELL_DIR}/pod/pod_caps.c
    ${SHELL_DIR}/pod/pod_json.c ${SHELL_DIR}/key_filter.c ${SHELL_DIR}/modem/modem.c
    ${SHELL_DIR}/modem/modem_framing.c ${SHELL_DIR}/radio/radio_protocol.c
    ${SHELL_DIR}/radio/radio_task.c ${SHELL_DIR}/radio/noise_stats.c)
target_include_directories(ble_gatt_stub_test PRIVATE ${SHELL_DIR} ${CORE_DIR}/tests)
target_link_libraries(ble_gatt_stub_test PRIVATE atalaia_core_fw)
if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(ble_gatt_stub_test PRIVATE -Wall -Wextra -Wpedantic -Werror)
endif()

# ---- CTest -------------------------------------------------------------------
include(CTest)
add_test(NAME firmware COMMAND firmware_test)
add_test(NAME screens COMMAND screen_test)
add_test(NAME oled_screens COMMAND oled_screen_test)
add_test(NAME proxy_codec COMMAND proxy_codec_test)
add_test(NAME ble_gatt_stub COMMAND ble_gatt_stub_test)
