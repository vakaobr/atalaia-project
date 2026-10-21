/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

#ifndef HAL_ESP_H
#define HAL_ESP_H

#include "../hal.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Initialise the HAL with real ESP-IDF peripheral drivers.
 * Returns 0 on success, negative errno on failure.
 */
int hal_esp_init(hal_t *hal);

/**
 * Board power at boot: switches on Vext (GPIO 36, active low on the
 * Heltec V4: the on-board OLED and the LoRa front end) and sets the GNSS
 * module's power (GPIO 34, active low: off unless
 * CONFIG_ATALAIA_GNSS_POWER_ON). Call first.
 */
void hal_esp_board_power_on(void);

/**
 * The keypad expander's spare pin P7 (a team button to GND), as the last
 * keypad scan read it: 1 = pressed, 0 = released, -1 = no PCF8574 keypad.
 */
int hal_esp_keypad_p7_pressed(void);

#ifdef __cplusplus
}
#endif

#endif /* HAL_ESP_H */
