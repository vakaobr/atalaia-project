# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

idf_component_register(
    SRCS
        "shell.c"
        "game_timer.c"
        "command_dispatch.c"
        "preset_store.c"
        "builtin_presets.c"
        "state_persist.c"
        "node_runner.c"
        "screen_renderer.c"
        "display_port.c"
        "preset_ui.c"
        "key_filter.c"
        "wifi_setup.c"
        "config_store.c"
        "mem_monitor.c"
        "button_tracker.c"
        "hal/esp/hal_esp.c"
        "hal/esp/hal_esp_i2c.c"
        "hal/esp/hal_esp_buttons.c"
        "hal/esp/hal_esp_keypad.c"
        "hal/esp/hal_esp_keypad_gpio.c"
        "hal/esp/hal_esp_leds.c"
        "hal/esp/hal_esp_display.c"
        "hal/esp/hal_esp_nfc.c"
        "hal/esp/hal_esp_audio.c"
        "hal/esp/hal_esp_battery.c"
    INCLUDE_DIRS
        "."
        "hal"
    PRIV_INCLUDE_DIRS
        "hal/esp"
    REQUIRES
        atalaia_core
        driver
        esp_psram
        esp_timer
        nvs_flash
        esp_wifi
        esp_http_server
        esp_event
        esp_netif
    EMBED_FILES
        "wifi_setup.html"
)

# The screen templates build LVGL widgets on the device (ADR-P1-2), with the
# same code and the same lv_conf.h as the host reference-image tests.
target_compile_definitions(${COMPONENT_LIB} PRIVATE ATALAIA_SCREEN_LVGL=1)

# LVGL takes its configuration from lvgl_conf/lv_conf.h, not from Kconfig, so
# the device and the host tests (firmware/esp32/test) build it identically.
idf_component_get_property(lvgl_lib lvgl__lvgl COMPONENT_LIB)
target_include_directories(${lvgl_lib} PUBLIC "${CMAKE_CURRENT_LIST_DIR}/../lvgl_conf")
target_compile_definitions(${lvgl_lib} PUBLIC LV_KCONFIG_IGNORE)

# Built-in presets: the mode scripts from modes/ are compiled into the image
# and written to the preset store when it is empty (builtin_presets.c). They
# are copied first because both files are called node.lua.
set(ATALAIA_MODES_DIR "${CMAKE_CURRENT_LIST_DIR}/../../../modes")
foreach(mode bomb domination)
    configure_file("${ATALAIA_MODES_DIR}/${mode}/node.lua"
                   "${CMAKE_CURRENT_BINARY_DIR}/${mode}_node.lua" COPYONLY)
    target_add_binary_data(${COMPONENT_LIB} "${CMAKE_CURRENT_BINARY_DIR}/${mode}_node.lua" TEXT)
endforeach()
