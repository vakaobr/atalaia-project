/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

#ifdef ESP_PLATFORM

#include "../hal_leds.h"

#include "driver/rmt_tx.h"
#include "led_strip.h"

/* ---- Kconfig pins ---- */

#ifndef CONFIG_ATALAIA_LED_PIN
#define CONFIG_ATALAIA_LED_PIN 35
#endif
#ifndef CONFIG_ATALAIA_LED_COUNT
#define CONFIG_ATALAIA_LED_COUNT 24
#endif
#ifndef CONFIG_ATALAIA_LED_BRIGHTNESS_PCT
#define CONFIG_ATALAIA_LED_BRIGHTNESS_PCT 40
#endif

static led_strip_handle_t strip;
/* The colours as set, before the brightness: show() scales them. */
static uint8_t pixels[CONFIG_ATALAIA_LED_COUNT][3];
static uint8_t brightness_pct = CONFIG_ATALAIA_LED_BRIGHTNESS_PCT;

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

static void esp_leds_set(int index, uint8_t r, uint8_t g, uint8_t b)
{
    if (index >= 0 && index < CONFIG_ATALAIA_LED_COUNT) {
        pixels[index][0] = r;
        pixels[index][1] = g;
        pixels[index][2] = b;
    }
}

static void esp_leds_fill(uint8_t r, uint8_t g, uint8_t b)
{
    for (int i = 0; i < CONFIG_ATALAIA_LED_COUNT; i++) esp_leds_set(i, r, g, b);
}

static void esp_leds_show(void)
{
    if (!strip) return;
    /* WS2812 has no brightness control of its own: scale every channel. At
     * full white a 24-LED ring draws about 1.4 A, so the default is lower. */
    for (int i = 0; i < CONFIG_ATALAIA_LED_COUNT; i++) {
        led_strip_set_pixel(strip, i, hal_led_scale(pixels[i][0], brightness_pct),
                            hal_led_scale(pixels[i][1], brightness_pct),
                            hal_led_scale(pixels[i][2], brightness_pct));
    }
    led_strip_refresh(strip);
}

static void esp_leds_set_brightness(uint8_t brightness)
{
    brightness_pct = brightness > 100 ? 100 : brightness;
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
