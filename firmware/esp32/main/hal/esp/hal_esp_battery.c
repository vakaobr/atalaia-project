/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

#ifdef ESP_PLATFORM

#include "../hal_battery.h"
#include "hal_esp_i2c.h"

#include "driver/i2c.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"

static const char *TAG = "hal_bat";

/* ---- Kconfig pins ---- */

/*
 * The MAX17048 shares the board bus with the PN532 and the keypad
 * expander (hal_esp_i2c.c). The ATALAIA_BATT_SDA/SCL Kconfig pins must
 * match the NFC pins; one I2C port drives all of them.
 */
#define CONFIG_ATALAIA_BATT_I2C_PORT HAL_ESP_I2C_PORT

/* MAX17048 register addresses */
#define MAX17048_I2C_ADDR 0x36
#define REG_VCELL         0x02 /* Voltage */
#define REG_SOC           0x04 /* State of Charge */
#define REG_STATUS        0x1A /* Status register */

/* ---- helpers ---- */

static esp_err_t max17048_read_reg(uint8_t reg, uint16_t *value)
{
    uint8_t data[2];
    esp_err_t err = i2c_master_write_read_device(CONFIG_ATALAIA_BATT_I2C_PORT, MAX17048_I2C_ADDR,
                                                 &reg, 1, data, 2, pdMS_TO_TICKS(100));
    if (err != ESP_OK) return err;

    /* MAX17048 returns MSB first */
    *value = ((uint16_t)data[0] << 8) | data[1];
    return ESP_OK;
}

/* ---- ops implementation ---- */

static bool present;

static int esp_battery_init(void)
{
    uint16_t vcell = 0;
    present = hal_esp_i2c_init() == 0 && hal_esp_i2c_probe(MAX17048_I2C_ADDR) &&
              max17048_read_reg(REG_VCELL, &vcell) == ESP_OK;
    if (!present) {
        /* Not fatal: the gauge is optional (and Wokwi has no MAX17048). */
        ESP_LOGW(TAG, "MAX17048 battery gauge not found at 0x%02X: battery level unknown",
                 MAX17048_I2C_ADDR);
        return -1;
    }
    ESP_LOGI(TAG, "MAX17048 detected, VCELL raw=0x%04X", vcell);
    return 0;
}

static hal_battery_info_t esp_battery_read(void)
{
    hal_battery_info_t info = {
        .voltage_mv = 0,
        .percent = 0,
        .charging = false,
    };

    if (!present) return info;

    /* Read voltage: register value * 78.125 uV */
    uint16_t vcell;
    if (max17048_read_reg(REG_VCELL, &vcell) == ESP_OK) {
        /* VCELL is a 16-bit value; LSB = 78.125 uV */
        info.voltage_mv = (uint16_t)((uint32_t)vcell * 78125 / 1000000);
    }

    /* Read state of charge: register value / 256 = percent */
    uint16_t soc;
    if (max17048_read_reg(REG_SOC, &soc) == ESP_OK) {
        uint8_t pct = (uint8_t)(soc >> 8);
        info.percent = pct > 100 ? 100 : pct;
    }

    /*
     * Charging detection: MAX17048 does not directly report charging
     * status. A real implementation would read a charge-controller GPIO
     * (e.g. TP4056 CHRG pin). For now, report false.
     */
    info.charging = false;

    return info;
}

static void esp_battery_deinit(void)
{
    /* The bus is shared; it stays installed. */
    present = false;
}

const hal_battery_ops_t hal_esp_battery_ops = {
    .init = esp_battery_init,
    .read = esp_battery_read,
    .deinit = esp_battery_deinit,
};

#endif /* ESP_PLATFORM */
