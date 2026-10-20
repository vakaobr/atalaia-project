/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * The Heltec V4's on-board 0.96" OLED: an SSD1306 (128x64) on the shared
 * I2C bus (hal_esp_i2c.h), reset on GPIO 21, powered from Vext (switched on
 * by hal_esp_board before the peripherals are probed).
 *
 * A frame is sent page by page (8 pages of 128 bytes) and only the pages
 * that changed: at the bus's 100 kHz a full frame takes ~100 ms, a
 * countdown tick one or two pages.
 */
#ifdef ESP_PLATFORM

#include "../hal_oled.h"

#include <stdbool.h>
#include <string.h>

#include "driver/gpio.h"
#include "driver/i2c.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "hal_esp_i2c.h"
#include "sdkconfig.h"

#ifndef CONFIG_ATALAIA_OLED_ADDR
#define CONFIG_ATALAIA_OLED_ADDR 0x3C
#endif
#ifndef CONFIG_ATALAIA_OLED_RST_PIN
#define CONFIG_ATALAIA_OLED_RST_PIN 21
#endif

#define CTRL_CMD  0x00 /* the bytes that follow are commands */
#define CTRL_DATA 0x40 /* the bytes that follow are display RAM */
#define PAGES     (HAL_OLED_HEIGHT / 8)

static const char *TAG = "hal_oled";

static uint8_t sent[HAL_OLED_FB_SIZE];
static bool sent_valid;
static bool ready;

static int send(const uint8_t *buf, size_t len)
{
    esp_err_t err = i2c_master_write_to_device(HAL_ESP_I2C_PORT, CONFIG_ATALAIA_OLED_ADDR, buf, len,
                                               pdMS_TO_TICKS(100));
    return err == ESP_OK ? 0 : -1;
}

static int commands(const uint8_t *cmds, size_t n)
{
    uint8_t buf[32];
    if (n + 1 > sizeof(buf)) return -1;
    buf[0] = CTRL_CMD;
    memcpy(buf + 1, cmds, n);
    return send(buf, n + 1);
}

static int esp_oled_init(void)
{
    ready = false;
    sent_valid = false;
    if (hal_esp_i2c_init() != 0) return -1;

    if (CONFIG_ATALAIA_OLED_RST_PIN >= 0) {
        gpio_config_t cfg = {
            .pin_bit_mask = 1ULL << (unsigned)CONFIG_ATALAIA_OLED_RST_PIN,
            .mode = GPIO_MODE_OUTPUT,
        };
        gpio_config(&cfg);
        gpio_set_level((gpio_num_t)CONFIG_ATALAIA_OLED_RST_PIN, 0);
        vTaskDelay(pdMS_TO_TICKS(10));
        gpio_set_level((gpio_num_t)CONFIG_ATALAIA_OLED_RST_PIN, 1);
        vTaskDelay(pdMS_TO_TICKS(10));
    }

    if (!hal_esp_i2c_probe(CONFIG_ATALAIA_OLED_ADDR)) {
        ESP_LOGW(TAG, "SSD1306 OLED not found at 0x%02X: OLED status off",
                 CONFIG_ATALAIA_OLED_ADDR);
        return -1;
    }

    static const uint8_t init_seq[] = {
        0xAE,       /* display off */
        0xD5, 0x80, /* clock divide */
        0xA8, 0x3F, /* multiplex: 64 rows */
        0xD3, 0x00, /* no display offset */
        0x40,       /* start line 0 */
        0x8D, 0x14, /* charge pump on */
        0x20, 0x00, /* horizontal addressing */
#if CONFIG_ATALAIA_OLED_FLIP
        0xA0, 0xC0, /* columns and rows in panel order */
#else
        0xA1, 0xC8, /* mirrored: upright with the USB port on the left */
#endif
        0xDA, 0x12, /* COM pins: alternative */
        0x81, 0xCF, /* contrast */
        0xD9, 0xF1, /* pre-charge */
        0xDB, 0x40, /* VCOMH */
        0xA4,       /* show RAM */
        0xA6,       /* not inverted */
        0xAF,       /* display on */
    };
    if (commands(init_seq, sizeof(init_seq)) != 0) {
        ESP_LOGW(TAG, "SSD1306 OLED did not take its set-up: OLED status off");
        return -1;
    }
    ready = true;
    ESP_LOGI(TAG, "SSD1306 OLED at 0x%02X (128x64)", CONFIG_ATALAIA_OLED_ADDR);
    return 0;
}

static int esp_oled_write(const uint8_t fb[HAL_OLED_FB_SIZE])
{
    if (!ready) return -1;
    for (int p = 0; p < PAGES; p++) {
        const uint8_t *page = fb + p * HAL_OLED_WIDTH;
        if (sent_valid && memcmp(page, sent + p * HAL_OLED_WIDTH, HAL_OLED_WIDTH) == 0) continue;
        const uint8_t window[] = {0x21, 0, HAL_OLED_WIDTH - 1, 0x22, (uint8_t)p, (uint8_t)p};
        uint8_t data[1 + HAL_OLED_WIDTH];
        data[0] = CTRL_DATA;
        memcpy(data + 1, page, HAL_OLED_WIDTH);
        if (commands(window, sizeof(window)) != 0 || send(data, sizeof(data)) != 0) {
            sent_valid = false; /* resend everything next time */
            return -1;
        }
        memcpy(sent + p * HAL_OLED_WIDTH, page, HAL_OLED_WIDTH);
    }
    sent_valid = true;
    return 0;
}

static void esp_oled_deinit(void)
{
    if (!ready) return;
    static const uint8_t off[] = {0xAE};
    commands(off, sizeof(off));
    ready = false;
}

const hal_oled_ops_t hal_esp_oled_ops = {
    .init = esp_oled_init,
    .write = esp_oled_write,
    .deinit = esp_oled_deinit,
};

#endif /* ESP_PLATFORM */
