/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The expansion port's bus on the ESP32 (expansion_esp.h). A read is one transaction: the
 * pointer write, a repeated start and the read (i2c_master_transmit_receive). At 100 kHz a
 * STATUS read takes about 1.2 ms; each transaction may take EXP_ESP_TIMEOUT_MS at most.
 */

#ifdef ESP_PLATFORM

#include "expansion_esp.h"

#include "hal_esp_i2c.h"

#define EXP_ESP_TIMEOUT_MS 10

static int result(int r)
{
    if (r == HAL_ESP_I2C_OK) return EXP_BUS_OK;
    return r == HAL_ESP_I2C_SUSPENDED ? EXP_BUS_SUSPENDED : EXP_BUS_FAIL;
}

static bool esp_probe(void *ctx, uint8_t addr)
{
    (void)ctx;
    return hal_esp_i2c_probe(addr);
}

static int esp_write(void *ctx, uint8_t addr, const uint8_t *data, size_t len)
{
    (void)ctx;
    return result(hal_esp_i2c_write(addr, data, len, EXP_ESP_TIMEOUT_MS));
}

static int esp_write_read(void *ctx, uint8_t addr, const uint8_t *out, size_t out_len, uint8_t *in,
                          size_t in_len)
{
    (void)ctx;
    return result(hal_esp_i2c_write_read(addr, out, out_len, in, in_len, EXP_ESP_TIMEOUT_MS));
}

bool expansion_esp_bus(exp_bus_t *bus)
{
    bus->ctx = NULL;
    bus->probe = esp_probe;
    bus->write = esp_write;
    bus->write_read = esp_write_read;
    return hal_esp_i2c_init() == 0;
}

#endif /* ESP_PLATFORM */
