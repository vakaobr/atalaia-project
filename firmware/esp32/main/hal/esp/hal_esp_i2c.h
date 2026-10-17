/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * The board's shared I2C bus (GPIO 17/18 on the Heltec V4.3): on-board
 * OLED (0x3C), PCF8574 keypad expander (0x20), PN532 NFC (0x24) and
 * MAX17048 battery gauge (0x36), all on I2C port 0.
 */
#ifndef HAL_ESP_I2C_H
#define HAL_ESP_I2C_H

#include <stdbool.h>
#include <stdint.h>

#define HAL_ESP_I2C_PORT 0 /* I2C_NUM_0 */

/* Install the I2C driver once; later calls return the first result. 0 = ok. */
int hal_esp_i2c_init(void);

/* True when a device answers (ACKs) at the 7-bit address. */
bool hal_esp_i2c_probe(uint8_t addr);

#endif /* HAL_ESP_I2C_H */
