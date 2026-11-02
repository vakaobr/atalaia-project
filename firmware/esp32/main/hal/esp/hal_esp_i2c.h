/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * The board's shared I2C bus (GPIO 17/18 on the Heltec V4.3): on-board
 * OLED (0x3C), PCF8574 keypad expander (0x20), PN532 NFC (0x24) and
 * MAX17048 battery gauge (0x36), all on I2C port 0.
 *
 * Every part goes through this file, on ESP-IDF's i2c_master driver (decision I2C-1): its
 * interrupt handler clears what it reads, every transaction has a timeout and a failed one
 * resets the controller. The legacy driver's handler could leave an interrupt asserted and spin
 * past the interrupt watchdog on a noisy bus (bench, 2026-10-31). On top of that each device has
 * a health record (i2c_health.h): after a few failures in a row the device is skipped with a
 * quick failure and tried again after a growing wait, so a bad joint costs the box a part, never
 * a reboot.
 */
#ifndef HAL_ESP_I2C_H
#define HAL_ESP_I2C_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "i2c_health.h"

#define HAL_ESP_I2C_PORT 0 /* I2C_NUM_0 */

#define HAL_ESP_I2C_OK        0
#define HAL_ESP_I2C_FAIL      (-1) /* the transaction failed (NACK, timeout, bus error) */
#define HAL_ESP_I2C_SUSPENDED (-2) /* not tried: the device is in back-off */

/* Install the bus once; later calls return the first result. 0 = ok. */
int hal_esp_i2c_init(void);

/* True when a device answers (ACKs) at the 7-bit address. Not tracked: absent parts are normal
 * at start-up. */
bool hal_esp_i2c_probe(uint8_t addr);

/* One transaction with the device at addr, timeout_ms for the whole transaction. Tracked in the
 * device's health: HAL_ESP_I2C_OK, _FAIL, or _SUSPENDED (nothing sent). */
int hal_esp_i2c_write(uint8_t addr, const uint8_t *data, size_t len, int timeout_ms);
int hal_esp_i2c_read(uint8_t addr, uint8_t *data, size_t len, int timeout_ms);
int hal_esp_i2c_write_read(uint8_t addr, const uint8_t *out, size_t out_len, uint8_t *in,
                           size_t in_len, int timeout_ms);

/* A read that may fail without meaning anything (the PN532 NACKs while busy): not counted, never
 * suspended. */
int hal_esp_i2c_read_quiet(uint8_t addr, uint8_t *data, size_t len, int timeout_ms);

/* False while the device is suspended and its back-off has not passed. */
bool hal_esp_i2c_usable(uint8_t addr);

/* The device's counters (zeros for a device never used); the bus's reset count when bus is not
 * NULL. */
void hal_esp_i2c_stats(uint8_t addr, i2c_health_t *out, uint32_t *bus_resets);

#endif /* HAL_ESP_I2C_H */
