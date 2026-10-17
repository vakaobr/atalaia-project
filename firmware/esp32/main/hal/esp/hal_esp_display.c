/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

#ifdef ESP_PLATFORM

#include "../hal_display.h"

#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include <stdbool.h>
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
#define CONFIG_ATALAIA_DISP_WIDTH  HAL_DISPLAY_WIDTH
#define CONFIG_ATALAIA_DISP_HEIGHT HAL_DISPLAY_HEIGHT

/*
 * MADCTL (0x36): landscape 320x240. ILI9341: MV | BGR. ST7789: MX | MV
 * (RGB order). Check the orientation and colours at bring-up; flip MX/MY
 * here if the picture is mirrored on a particular panel.
 */
#if CONFIG_ATALAIA_DISP_ST7789
#define DISP_MADCTL 0x60
#else
#define DISP_MADCTL 0x28
#endif

static spi_device_handle_t spi_dev;
static hal_display_flush_ready_cb_t pending_ready_cb;
/* The queued pixel transfer must outlive esp_display_flush(), so it is static. */
static spi_transaction_t pixel_trans;
static bool pixel_trans_queued;

/* ---- SPI DMA completion callback ---- */

static void IRAM_ATTR spi_post_transfer_cb(spi_transaction_t *trans)
{
    /* Only the pixel transfer completes an LVGL flush, not the commands. */
    if (trans == &pixel_trans && pending_ready_cb) {
        hal_display_flush_ready_cb_t cb = pending_ready_cb;
        pending_ready_cb = NULL;
        cb();
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
        .max_transfer_sz = CONFIG_ATALAIA_DISP_WIDTH * HAL_DISPLAY_BUF_LINES * 2,
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

    /* Memory access control: landscape orientation. */
    disp_send_cmd(0x36);
    uint8_t madctl = DISP_MADCTL;
    disp_send_data(&madctl, 1);

#if CONFIG_ATALAIA_DISP_ST7789
    /* Most ST7789 TFT modules need colour inversion on. */
    disp_send_cmd(0x21);
#endif

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
    /*
     * Collect the previous pixel transfer first: polling transactions
     * (the window commands) cannot start while a queued one is pending.
     * LVGL only flushes again after ready_cb, so this does not block.
     */
    if (pixel_trans_queued) {
        spi_transaction_t *done;
        spi_device_get_trans_result(spi_dev, &done, portMAX_DELAY);
        pixel_trans_queued = false;
    }

    disp_set_window(x1, y1, x2, y2);

    int pixel_count = (x2 - x1 + 1) * (y2 - y1 + 1);

    memset(&pixel_trans, 0, sizeof(pixel_trans));
    pixel_trans.length = (size_t)pixel_count * 2 * 8;
    pixel_trans.tx_buffer = color_p;

    pending_ready_cb = ready_cb;

    gpio_set_level(CONFIG_ATALAIA_DISP_DC_PIN, 1);
    if (spi_device_queue_trans(spi_dev, &pixel_trans, portMAX_DELAY) == ESP_OK) {
        pixel_trans_queued = true;
    } else {
        pending_ready_cb = NULL;
        ready_cb();
    }
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
        if (pixel_trans_queued) {
            spi_transaction_t *done;
            spi_device_get_trans_result(spi_dev, &done, portMAX_DELAY);
            pixel_trans_queued = false;
        }
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
