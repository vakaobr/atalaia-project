/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Assembles the real ESP-IDF HAL drivers into a single hal_t.
 */

#ifdef ESP_PLATFORM

#include "hal_esp.h"

/* Ops structs defined in each driver file. */
extern const hal_button_ops_t hal_esp_button_ops;
extern const hal_keypad_ops_t hal_esp_keypad_ops;
extern const hal_led_ops_t hal_esp_led_ops;
extern const hal_display_ops_t hal_esp_display_ops;
extern const hal_nfc_ops_t hal_esp_nfc_ops;
extern const hal_audio_ops_t hal_esp_audio_ops;
extern const hal_battery_ops_t hal_esp_battery_ops;
extern const hal_radio_ops_t hal_esp_radio_ops;

int hal_esp_init(hal_t *hal)
{
    hal->buttons = &hal_esp_button_ops;
    hal->keypad = &hal_esp_keypad_ops;
    hal->leds = &hal_esp_led_ops;
    hal->display = &hal_esp_display_ops;
    hal->nfc = &hal_esp_nfc_ops;
    hal->audio = &hal_esp_audio_ops;
    hal->battery = &hal_esp_battery_ops;
    hal->radio = &hal_esp_radio_ops;
    return 0;
}

#endif /* ESP_PLATFORM */
