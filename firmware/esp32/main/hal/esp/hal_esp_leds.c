/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

#ifdef ESP_PLATFORM

#include "../hal_leds.h"

#include "driver/rmt_tx.h"
#include "led_strip.h"

/* ---- Kconfig pins ---- */

#ifndef CONFIG_ATALAIA_LED_PIN
#define CONFIG_ATALAIA_LED_PIN 48
#endif
#ifndef CONFIG_ATALAIA_LED_COUNT
#define CONFIG_ATALAIA_LED_COUNT 12
#endif

static led_strip_handle_t strip;

/* ---- ops implementation ---- */

static int esp_leds_init(void)
{
    led_strip_config_t strip_cfg = {
        .strip_gpio_num = CONFIG_ATALAIA_LED_PIN,
        .max_leds = CONFIG_ATALAIA_LED_COUNT,
        .led_model = LED_MODEL_WS2812,
    };

    led_strip_rmt_config_t rmt_cfg = {
        .clk_src = RMT_CLK_SRC_DEFAULT,
        .resolution_hz = 10 * 1000 * 1000, /* 10 MHz */
        .flags.with_dma = false,
    };

    esp_err_t err = led_strip_new_rmt_device(&strip_cfg, &rmt_cfg, &strip);
    if (err != ESP_OK) {
        strip = NULL;
        return -1;
    }

    led_strip_clear(strip);
    return 0;
}

static void esp_leds_fill(uint8_t r, uint8_t g, uint8_t b)
{
    if (!strip) return;
    for (int i = 0; i < CONFIG_ATALAIA_LED_COUNT; i++) {
        led_strip_set_pixel(strip, i, r, g, b);
    }
}

static void esp_leds_set(int index, uint8_t r, uint8_t g, uint8_t b)
{
    if (strip && index >= 0 && index < CONFIG_ATALAIA_LED_COUNT) {
        led_strip_set_pixel(strip, index, r, g, b);
    }
}

static void esp_leds_show(void)
{
    if (strip) led_strip_refresh(strip);
}

static void esp_leds_set_brightness(uint8_t brightness)
{
    /*
     * The WS2812 protocol has no native brightness control.
     * A proper implementation would scale r/g/b values before show().
     * For now this is a placeholder -- the shell can pre-scale colours.
     */
    (void)brightness;
}

static void esp_leds_deinit(void)
{
    if (strip) {
        led_strip_clear(strip);
        led_strip_del(strip);
        strip = NULL;
    }
}

const hal_led_ops_t hal_esp_led_ops = {
    .init = esp_leds_init,
    .fill = esp_leds_fill,
    .set = esp_leds_set,
    .show = esp_leds_show,
    .set_brightness = esp_leds_set_brightness,
    .deinit = esp_leds_deinit,
};

#endif /* ESP_PLATFORM */
