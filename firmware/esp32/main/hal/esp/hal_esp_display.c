/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

#ifdef ESP_PLATFORM

#include "../hal_display.h"

#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include <string.h>

static const char *TAG = "hal_disp";

/* ---- Kconfig pins (-1 = unassigned) ---- */

#ifndef CONFIG_ATALAIA_DISP_MOSI_PIN
#define CONFIG_ATALAIA_DISP_MOSI_PIN 40
#endif
#ifndef CONFIG_ATALAIA_DISP_CLK_PIN
#define CONFIG_ATALAIA_DISP_CLK_PIN 41
#endif
#ifndef CONFIG_ATALAIA_DISP_CS_PIN
#define CONFIG_ATALAIA_DISP_CS_PIN 42
#endif
#ifndef CONFIG_ATALAIA_DISP_DC_PIN
#define CONFIG_ATALAIA_DISP_DC_PIN 3
#endif
#ifndef CONFIG_ATALAIA_DISP_RST_PIN
#define CONFIG_ATALAIA_DISP_RST_PIN 38 /* GPIO freed from keypad; GNSS header */
#endif
#ifndef CONFIG_ATALAIA_DISP_BL_PIN
#define CONFIG_ATALAIA_DISP_BL_PIN 47
#endif
#ifndef CONFIG_ATALAIA_DISP_WIDTH
#define CONFIG_ATALAIA_DISP_WIDTH 320
#endif
#ifndef CONFIG_ATALAIA_DISP_HEIGHT
#define CONFIG_ATALAIA_DISP_HEIGHT 240
#endif

static spi_device_handle_t spi_dev;
static hal_display_flush_ready_cb_t pending_ready_cb;

/* ---- SPI DMA completion callback ---- */

static void IRAM_ATTR spi_post_transfer_cb(spi_transaction_t *trans)
{
    (void)trans;
    if (pending_ready_cb) {
        pending_ready_cb();
        pending_ready_cb = NULL;
    }
}

/* ---- helpers ---- */

static void disp_send_cmd(uint8_t cmd)
{
    spi_transaction_t t;
    memset(&t, 0, sizeof(t));
    t.length = 8;
    t.tx_buffer = &cmd;

    gpio_set_level(CONFIG_ATALAIA_DISP_DC_PIN, 0); /* command mode */
    spi_device_polling_transmit(spi_dev, &t);
}

static void disp_send_data(const uint8_t *data, int len)
{
    if (len == 0) return;

    spi_transaction_t t;
    memset(&t, 0, sizeof(t));
    t.length = (size_t)len * 8;
    t.tx_buffer = data;

    gpio_set_level(CONFIG_ATALAIA_DISP_DC_PIN, 1); /* data mode */
    spi_device_polling_transmit(spi_dev, &t);
}

static void disp_set_window(int x1, int y1, int x2, int y2)
{
    disp_send_cmd(0x2A);
    uint8_t col[4] = {
        (uint8_t)(x1 >> 8),
        (uint8_t)(x1 & 0xFF),
        (uint8_t)(x2 >> 8),
        (uint8_t)(x2 & 0xFF),
    };
    disp_send_data(col, 4);

    disp_send_cmd(0x2B);
    uint8_t row[4] = {
        (uint8_t)(y1 >> 8),
        (uint8_t)(y1 & 0xFF),
        (uint8_t)(y2 >> 8),
        (uint8_t)(y2 & 0xFF),
    };
    disp_send_data(row, 4);

    disp_send_cmd(0x2C);
}

/* ---- ops implementation ---- */

static int esp_display_init(void)
{
    /* Configure DC pin (always needed). */
    uint64_t pin_mask = 1ULL << CONFIG_ATALAIA_DISP_DC_PIN;
#if CONFIG_ATALAIA_DISP_BL_PIN >= 0
    pin_mask |= 1ULL << CONFIG_ATALAIA_DISP_BL_PIN;
#endif
#if CONFIG_ATALAIA_DISP_RST_PIN >= 0
    pin_mask |= 1ULL << CONFIG_ATALAIA_DISP_RST_PIN;
#endif
    gpio_config_t io_cfg = {
        .pin_bit_mask = pin_mask,
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_config(&io_cfg);

    /* Hardware reset (skip if RST is tied to Vext). */
#if CONFIG_ATALAIA_DISP_RST_PIN >= 0
    gpio_set_level(CONFIG_ATALAIA_DISP_RST_PIN, 0);
    vTaskDelay(pdMS_TO_TICKS(20));
    gpio_set_level(CONFIG_ATALAIA_DISP_RST_PIN, 1);
#endif
    vTaskDelay(pdMS_TO_TICKS(120));

    /* SPI bus */
    spi_bus_config_t bus_cfg = {
        .mosi_io_num = CONFIG_ATALAIA_DISP_MOSI_PIN,
        .miso_io_num = -1,
        .sclk_io_num = CONFIG_ATALAIA_DISP_CLK_PIN,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .max_transfer_sz = CONFIG_ATALAIA_DISP_WIDTH * CONFIG_ATALAIA_DISP_HEIGHT * 2,
    };
    esp_err_t err = spi_bus_initialize(SPI2_HOST, &bus_cfg, SPI_DMA_CH_AUTO);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "SPI bus init failed: %s", esp_err_to_name(err));
        return -1;
    }

    spi_device_interface_config_t dev_cfg = {
        .clock_speed_hz = 40 * 1000 * 1000,
        .mode = 0,
        .spics_io_num = CONFIG_ATALAIA_DISP_CS_PIN,
        .queue_size = 2,
        .post_cb = spi_post_transfer_cb,
    };
    err = spi_bus_add_device(SPI2_HOST, &dev_cfg, &spi_dev);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "SPI add device failed: %s", esp_err_to_name(err));
        return -1;
    }

    /* Basic ILI9341/ST7789 init sequence */
    disp_send_cmd(0x01); /* Software reset */
    vTaskDelay(pdMS_TO_TICKS(120));
    disp_send_cmd(0x11); /* Sleep out */
    vTaskDelay(pdMS_TO_TICKS(120));

    /* Pixel format: 16-bit RGB565 */
    disp_send_cmd(0x3A);
    uint8_t pix_fmt = 0x55;
    disp_send_data(&pix_fmt, 1);

    /* Display on */
    disp_send_cmd(0x29);

    /* Backlight on */
#if CONFIG_ATALAIA_DISP_BL_PIN >= 0
    gpio_set_level(CONFIG_ATALAIA_DISP_BL_PIN, 1);
#endif

    ESP_LOGI(TAG, "Display initialised (%dx%d)", CONFIG_ATALAIA_DISP_WIDTH,
             CONFIG_ATALAIA_DISP_HEIGHT);

    return 0;
}

static void esp_display_flush(int x1, int y1, int x2, int y2, const void *color_p,
                              hal_display_flush_ready_cb_t ready_cb)
{
    disp_set_window(x1, y1, x2, y2);

    int pixel_count = (x2 - x1 + 1) * (y2 - y1 + 1);
    int byte_count = pixel_count * 2;

    spi_transaction_t t;
    memset(&t, 0, sizeof(t));
    t.length = (size_t)byte_count * 8;
    t.tx_buffer = color_p;

    pending_ready_cb = ready_cb;

    gpio_set_level(CONFIG_ATALAIA_DISP_DC_PIN, 1);
    spi_device_queue_trans(spi_dev, &t, portMAX_DELAY);
}

static void esp_display_set_brightness(uint8_t brightness)
{
#if CONFIG_ATALAIA_DISP_BL_PIN >= 0
    gpio_set_level(CONFIG_ATALAIA_DISP_BL_PIN, brightness > 0 ? 1 : 0);
#else
    (void)brightness;
#endif
}

static void esp_display_deinit(void)
{
#if CONFIG_ATALAIA_DISP_BL_PIN >= 0
    gpio_set_level(CONFIG_ATALAIA_DISP_BL_PIN, 0);
#endif
    if (spi_dev) {
        spi_bus_remove_device(spi_dev);
        spi_dev = NULL;
    }
    spi_bus_free(SPI2_HOST);
}

const hal_display_ops_t hal_esp_display_ops = {
    .init = esp_display_init,
    .flush = esp_display_flush,
    .set_brightness = esp_display_set_brightness,
    .deinit = esp_display_deinit,
};

#endif /* ESP_PLATFORM */
