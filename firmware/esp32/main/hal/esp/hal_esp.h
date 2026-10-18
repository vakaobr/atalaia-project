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
 * Heltec V4: the on-board OLED and the LoRa front end). Call first.
 */
void hal_esp_board_power_on(void);

#ifdef __cplusplus
}
#endif

#endif /* HAL_ESP_H */
