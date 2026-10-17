/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

#ifdef ESP_PLATFORM

#include "hal_esp_i2c.h"

#include "driver/i2c.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"

static const char *TAG = "hal_i2c";

#ifndef CONFIG_ATALAIA_NFC_SDA_PIN
#define CONFIG_ATALAIA_NFC_SDA_PIN 17
#endif
#ifndef CONFIG_ATALAIA_NFC_SCL_PIN
#define CONFIG_ATALAIA_NFC_SCL_PIN 18
#endif

static int init_result = 1; /* 1 = not tried yet */

int hal_esp_i2c_init(void)
{
    if (init_result != 1) return init_result;

    i2c_config_t conf = {
        .mode = I2C_MODE_MASTER,
        .sda_io_num = CONFIG_ATALAIA_NFC_SDA_PIN,
        .scl_io_num = CONFIG_ATALAIA_NFC_SCL_PIN,
        .sda_pullup_en = GPIO_PULLUP_ENABLE,
        .scl_pullup_en = GPIO_PULLUP_ENABLE,
        .master.clk_speed = 100000, /* 100 kHz: the PN532 is the slowest device */
    };
    esp_err_t err = i2c_param_config(HAL_ESP_I2C_PORT, &conf);
    if (err == ESP_OK) err = i2c_driver_install(HAL_ESP_I2C_PORT, conf.mode, 0, 0, 0);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "I2C bus init failed: %s", esp_err_to_name(err));
        init_result = -1;
    } else {
        ESP_LOGI(TAG, "I2C bus on SDA %d, SCL %d", CONFIG_ATALAIA_NFC_SDA_PIN,
                 CONFIG_ATALAIA_NFC_SCL_PIN);
        init_result = 0;
    }
    return init_result;
}

bool hal_esp_i2c_probe(uint8_t addr)
{
    if (init_result != 0) return false;
    i2c_cmd_handle_t cmd = i2c_cmd_link_create();
    if (!cmd) return false;
    i2c_master_start(cmd);
    i2c_master_write_byte(cmd, (uint8_t)((addr << 1) | I2C_MASTER_WRITE), true);
    i2c_master_stop(cmd);
    esp_err_t err = i2c_master_cmd_begin(HAL_ESP_I2C_PORT, cmd, pdMS_TO_TICKS(50));
    i2c_cmd_link_delete(cmd);
    return err == ESP_OK;
}

#endif /* ESP_PLATFORM */
