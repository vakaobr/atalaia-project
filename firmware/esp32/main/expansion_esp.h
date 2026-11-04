/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The expansion port's bus on the ESP32 (expansion.h's exp_bus_t): the board's shared I2C bus
 * through hal/esp/hal_esp_i2c.h, so modules get the same timeouts, health records and back-off
 * as the keypad, the NFC reader and the gauge (protocol/expansion-port.md, section 5: a
 * suspended module's skipped polls count as failed reads). Nothing calls it yet: the game task
 * starts the driver in increment 8 of the draft RFC "The expansion port".
 */
#ifndef ATALAIA_EXPANSION_ESP_H
#define ATALAIA_EXPANSION_ESP_H

#include <stdbool.h>

#include "expansion.h"

/* Fills *bus with the ESP32's I2C bus; false when the bus could not be installed. */
bool expansion_esp_bus(exp_bus_t *bus);

#endif /* ATALAIA_EXPANSION_ESP_H */
