# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

if(CONFIG_ATALAIA_MODEM_MODE)
    # USB radio modem (ADR-P2-4): radio, serial link and modem logic only.
    set(ATALAIA_SRCS
        "modem/modem_main.c"
        "modem/modem_task.c"
        "modem/modem.c"
        "modem/modem_framing.c"
        "hal/esp/hal_esp_radio.c"
        "hal/esp/hal_esp_board.c"
        "hal/board_fem.c"
        "radio/radio_task.c"
        "radio/radio_protocol.c"
        "radio/radio_limits.c"
        "radio/noise_stats.c"
    )
    set(ATALAIA_EMBED)
else()
    set(ATALAIA_SRCS
        "shell.c"
        "game_timer.c"
        "command_dispatch.c"
        "preset_store.c"
        "builtin_presets.c"
        "state_persist.c"
        "node_runner.c"
        "screen_renderer.c"
        "screen_template.c"
        "display_port.c"
        "preset_ui.c"
        "key_filter.c"
        "wifi_setup.c"
        "config_store.c"
        "mem_monitor.c"
        "button_tracker.c"
        "hal/esp/hal_esp.c"
        "hal/esp/hal_esp_board.c"
        "hal/esp/hal_esp_i2c.c"
        "hal/esp/hal_esp_buttons.c"
        "hal/esp/hal_esp_keypad.c"
        "hal/esp/hal_esp_keypad_gpio.c"
        "hal/esp/hal_esp_leds.c"
        "hal/esp/hal_esp_display.c"
        "hal/esp/hal_esp_nfc.c"
        "hal/esp/hal_esp_audio.c"
        "hal/esp/hal_esp_battery.c"
        "hal/esp/hal_esp_radio.c"
        "hal/board_fem.c"
        "radio/radio_task.c"
        "radio/event_log.c"
        "radio/time_sync.c"
        "radio/radio_protocol.c"
        "radio/radio_nvs_esp.c"
        "radio/radio_limits.c"
        "radio/noise_stats.c"
        "radio/field_link.c"
        "box_game.c"
        "serial_console.c"
    )
    set(ATALAIA_EMBED EMBED_FILES "wifi_setup.html")
endif()

idf_component_register(
    SRCS
        ${ATALAIA_SRCS}
    INCLUDE_DIRS
        "."
        "hal"
    PRIV_INCLUDE_DIRS
        "hal/esp"
    REQUIRES
        atalaia_core
        driver
        esp_app_format
        esp_psram
        esp_timer
        nvs_flash
        esp_wifi
        esp_http_server
        esp_event
        esp_netif
        mbedtls
    ${ATALAIA_EMBED}
)

# The screen templates build LVGL widgets on the device (ADR-P1-2), with the
# same code and the same lv_conf.h as the host reference-image tests.
target_compile_definitions(${COMPONENT_LIB} PRIVATE ATALAIA_SCREEN_LVGL=1)

# LVGL takes its configuration from lvgl_conf/lv_conf.h, not from Kconfig, so
# the device and the host tests (firmware/esp32/test) build it identically.
idf_component_get_property(lvgl_lib lvgl__lvgl COMPONENT_LIB)
target_include_directories(${lvgl_lib} PUBLIC "${CMAKE_CURRENT_LIST_DIR}/../lvgl_conf")
target_compile_definitions(${lvgl_lib} PUBLIC LV_KCONFIG_IGNORE)

# Screen templates (ADR-P3-4): every modes/<mode>/assets/screens/*.yaml is
# compiled into the image (builtin_screens.c, generated here).
if(NOT CONFIG_ATALAIA_MODEM_MODE)
    include("${CMAKE_CURRENT_LIST_DIR}/builtin_screens.cmake")
    atalaia_builtin_screens("${CMAKE_CURRENT_LIST_DIR}/../../../modes"
                            "${CMAKE_CURRENT_BINARY_DIR}/builtin_screens.c")
    target_sources(${COMPONENT_LIB} PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/builtin_screens.c")
endif()

# Built-in presets: the mode scripts from modes/ are compiled into the image
# and written to the preset store when it is empty (builtin_presets.c). They
# are copied first because both files are called node.lua.
if(NOT CONFIG_ATALAIA_MODEM_MODE)
    set(ATALAIA_MODES_DIR "${CMAKE_CURRENT_LIST_DIR}/../../../modes")
    foreach(mode bomb domination holdall laststand codes kill_confirmed respawn player_checkin)
        configure_file("${ATALAIA_MODES_DIR}/${mode}/node.lua"
                       "${CMAKE_CURRENT_BINARY_DIR}/${mode}_node.lua" COPYONLY)
        target_add_binary_data(${COMPONENT_LIB} "${CMAKE_CURRENT_BINARY_DIR}/${mode}_node.lua" TEXT)
    endforeach()
endif()
