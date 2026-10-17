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

#ifdef __cplusplus
}
#endif

#endif /* HAL_ESP_H */
