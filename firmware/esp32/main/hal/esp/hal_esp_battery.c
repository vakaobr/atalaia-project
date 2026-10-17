/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

#ifdef ESP_PLATFORM

#include "../hal_battery.h"

#include "driver/i2c.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"

static const char *TAG = "hal_bat";

/* ---- Kconfig pins ---- */

#ifndef CONFIG_ATALAIA_BATT_SDA_PIN
#define CONFIG_ATALAIA_BATT_SDA_PIN 17
#endif
#ifndef CONFIG_ATALAIA_BATT_SCL_PIN
#define CONFIG_ATALAIA_BATT_SCL_PIN 18
#endif
#ifndef CONFIG_ATALAIA_BATT_I2C_PORT
#define CONFIG_ATALAIA_BATT_I2C_PORT I2C_NUM_1
#endif

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

static int esp_battery_init(void)
{
    i2c_config_t conf = {
        .mode = I2C_MODE_MASTER,
        .sda_io_num = CONFIG_ATALAIA_BATT_SDA_PIN,
        .scl_io_num = CONFIG_ATALAIA_BATT_SCL_PIN,
        .sda_pullup_en = GPIO_PULLUP_ENABLE,
        .scl_pullup_en = GPIO_PULLUP_ENABLE,
        .master.clk_speed = 400000, /* 400 kHz */
    };

    esp_err_t err = i2c_param_config(CONFIG_ATALAIA_BATT_I2C_PORT, &conf);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "I2C param config failed: %s", esp_err_to_name(err));
        return -1;
    }

    err = i2c_driver_install(CONFIG_ATALAIA_BATT_I2C_PORT, conf.mode, 0, 0, 0);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "I2C driver install failed: %s", esp_err_to_name(err));
        return -1;
    }

    /* Verify the chip is present by reading VCELL */
    uint16_t vcell;
    err = max17048_read_reg(REG_VCELL, &vcell);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "MAX17048 not detected (VCELL read failed)");
        /* Non-fatal: battery gauge is optional */
    } else {
        ESP_LOGI(TAG, "MAX17048 detected, VCELL raw=0x%04X", vcell);
    }

    return 0;
}

static hal_battery_info_t esp_battery_read(void)
{
    hal_battery_info_t info = {
        .voltage_mv = 0,
        .percent = 0,
        .charging = false,
    };

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
    i2c_driver_delete(CONFIG_ATALAIA_BATT_I2C_PORT);
}

const hal_battery_ops_t hal_esp_battery_ops = {
    .init = esp_battery_init,
    .read = esp_battery_read,
    .deinit = esp_battery_deinit,
};

#endif /* ESP_PLATFORM */
