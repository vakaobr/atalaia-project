# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

if(CONFIG_ATALAIA_MODEM_MODE)
    # USB radio modem (ADR-P2-4): radio, serial link and modem logic, and
    # the on-board OLED's status screen (modem_screen.c, LVGL).
    set(ATALAIA_SRCS
        "modem/modem_main.c"
        "modem/modem_task.c"
        "modem/modem.c"
        "modem/modem_framing.c"
        "modem/modem_screen.c"
        "modem/modem_display.c"
        "oled_view.c"
        "oled_logo.c"
        "box_text.c"
        "screen_json.c"
        "fonts/lv_font_atalaia_14.c"
        "fonts/lv_font_atalaia_20.c"
        "fonts/lv_font_atalaia_28.c"
        "fonts/lv_font_atalaia_48.c"
        "hal/esp/hal_esp_radio.c"
        "hal/esp/hal_esp_board.c"
        "hal/esp/hal_esp_i2c.c"
        "hal/esp/hal_esp_oled.c"
        "hal/board_fem.c"
        "radio/radio_task.c"
        "radio/radio_protocol.c"
        "radio/radio_limits.c"
        "radio/noise_stats.c"
    )
    set(ATALAIA_EMBED)
elseif(CONFIG_ATALAIA_POD_MODE)
    # I/O pod (ADR-P3-3): the capability proxy for a phone over USB and
    # Bluetooth LE, the Field Box's input and output parts, and the modem's
    # radio logic. No Lua, screens, presets or Wi-Fi.
    set(ATALAIA_SRCS
        "pod/pod_main.c"
        "pod/pod_task.c"
        "pod/pod.c"
        "pod/pod_caps.c"
        "pod/pod_json.c"
        "pod/pod_ble.c"
        "modem/modem.c"
        "modem/modem_framing.c"
        "key_filter.c"
        "hal/esp/hal_esp_board.c"
        "hal/esp/hal_esp_i2c.c"
        "hal/esp/hal_esp_buttons.c"
        "hal/esp/hal_esp_keypad.c"
        "hal/esp/hal_esp_keypad_gpio.c"
        "hal/esp/hal_esp_leds.c"
        "hal/esp/hal_esp_nfc.c"
        "hal/esp/hal_esp_audio.c"
        "hal/esp/hal_esp_battery.c"
        "hal/esp/hal_esp_radio.c"
        "hal/board_fem.c"
        "radio/radio_task.c"
        "radio/radio_protocol.c"
        "radio/radio_limits.c"
        "radio/noise_stats.c"
    )
    if(CONFIG_ATALAIA_POD_BLE)
        list(APPEND ATALAIA_SRCS "pod/pod_ble_nimble.c")
    endif()
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
        "box_text.c"
        "screen_json.c"
        "screen_template.c"
        "display_port.c"
        "oled_view.c"
        "oled_logo.c"
        "fonts/lv_font_atalaia_14.c"
        "fonts/lv_font_atalaia_20.c"
        "fonts/lv_font_atalaia_28.c"
        "fonts/lv_font_atalaia_48.c"
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
        "hal/esp/hal_esp_oled.c"
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
        "box_lobby.c"
        "serial_console.c"
        "fw_update.c"
        "fw_update_esp.c"
        "fw_desc.c"
        "adoption.c"
        "cpace.c"
        "box_pair.c"
    )
    set(ATALAIA_EMBED EMBED_FILES "wifi_setup.html")
endif()

set(ATALAIA_REQUIRES
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
    # bootloader_random_enable() for the boot entropy of the field frames' tokens (RJ-15).
    bootloader_support
    # Firmware updates over the air (fw_update_esp.c): the OTA slots, HTTPS, and
    # Monocypher's Ed25519 for the release signatures (components/monocypher).
    app_update
    esp_http_client
    monocypher
    # NimBLE (part of ESP-IDF) for the I/O pod's Bluetooth link. Always listed:
    # requirements are expanded before the sdkconfig is read. Without
    # CONFIG_BT_ENABLED (the Field Box, the modem) it builds and links nothing.
    bt
)

idf_component_register(
    SRCS
        ${ATALAIA_SRCS}
    INCLUDE_DIRS
        "."
        "hal"
    PRIV_INCLUDE_DIRS
        "hal/esp"
    REQUIRES
        ${ATALAIA_REQUIRES}
    ${ATALAIA_EMBED}
)

# The image's Atalaia descriptor (fw_desc.c, right after esp_app_desc_t) stays in
# the image even where nothing would reference it.
if(NOT CONFIG_ATALAIA_MODEM_MODE AND NOT CONFIG_ATALAIA_POD_MODE)
    target_link_libraries(${COMPONENT_LIB} INTERFACE "-u atalaia_fw_desc")
endif()

# The screen templates build LVGL widgets on the device (ADR-P1-2), with the
# same code and the same lv_conf.h as the host reference-image tests.
target_compile_definitions(${COMPONENT_LIB} PRIVATE ATALAIA_SCREEN_LVGL=1)

# LVGL takes its configuration from lvgl_conf/lv_conf.h, not from Kconfig, so
# the device and the host tests (firmware/esp32/test) build it identically.
idf_component_get_property(lvgl_lib lvgl__lvgl COMPONENT_LIB)
target_include_directories(${lvgl_lib} PUBLIC "${CMAKE_CURRENT_LIST_DIR}/../lvgl_conf")
target_compile_definitions(${lvgl_lib} PUBLIC LV_KCONFIG_IGNORE)

# Screen templates (ADR-P3-4): every modes/<mode>/assets/screens/*.yaml is
# compiled into the image (builtin_screens.c, generated here). The Field Box only.
if(NOT CONFIG_ATALAIA_MODEM_MODE AND NOT CONFIG_ATALAIA_POD_MODE)
    include("${CMAKE_CURRENT_LIST_DIR}/builtin_screens.cmake")
    atalaia_builtin_screens("${CMAKE_CURRENT_LIST_DIR}/../../../modes"
                            "${CMAKE_CURRENT_BINARY_DIR}/builtin_screens.c")
    target_sources(${COMPONENT_LIB} PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/builtin_screens.c")
endif()

# Built-in presets: the mode scripts from modes/ are compiled into the image
# and written to the preset store when it is empty (builtin_presets.c). They
# are copied first because both files are called node.lua.
if(NOT CONFIG_ATALAIA_MODEM_MODE AND NOT CONFIG_ATALAIA_POD_MODE)
    set(ATALAIA_MODES_DIR "${CMAKE_CURRENT_LIST_DIR}/../../../modes")
    foreach(mode bomb domination holdall laststand codes kill_confirmed respawn player_checkin medic
                 master_satellites hacking_terminal vip_payload objectives)
        configure_file("${ATALAIA_MODES_DIR}/${mode}/node.lua"
                       "${CMAKE_CURRENT_BINARY_DIR}/${mode}_node.lua" COPYONLY)
        target_add_binary_data(${COMPONENT_LIB} "${CMAKE_CURRENT_BINARY_DIR}/${mode}_node.lua" TEXT)
    endforeach()
endif()
