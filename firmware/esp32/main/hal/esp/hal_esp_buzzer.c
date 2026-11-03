/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The optional passive piezo buzzer (CONFIG_ATALAIA_BUZZER, decisions BZR-1 to BZR-8): a square
 * wave from LEDC on CONFIG_ATALAIA_BUZZER_PIN. A passive piezo element only: an "active" buzzer
 * (with its own oscillator) would sound one pitch whatever the tone. The pin idles low, as the
 * GPIO 45 strap needs at reset (the circuit holds it low before the firmware runs).
 */

#ifdef ESP_PLATFORM

#include "sdkconfig.h"

#if CONFIG_ATALAIA_BUZZER

#include "../hal_buzzer.h"

#include "driver/ledc.h"
#include "esp_log.h"

static const char *TAG = "hal_buzzer";

#define BZ_MODE     LEDC_LOW_SPEED_MODE
#define BZ_TIMER    LEDC_TIMER_0
#define BZ_CHANNEL  LEDC_CHANNEL_0
#define BZ_RES      LEDC_TIMER_10_BIT
#define BZ_DUTY_MAX 512u /* 50 %: the loudest square wave */
/* What LEDC makes at 10 bits from its 80 MHz clock, and what a small piezo can sound. */
#define BZ_MIN_HZ 100u
#define BZ_MAX_HZ 10000u

static bool ready;
static uint8_t volume = 80;

static uint32_t duty_for_volume(void)
{
    return BZ_DUTY_MAX * volume / 100u;
}

static int esp_buzzer_init(void)
{
    ledc_timer_config_t timer = {
        .speed_mode = BZ_MODE,
        .duty_resolution = BZ_RES,
        .timer_num = BZ_TIMER,
        .freq_hz = 2000,
        .clk_cfg = LEDC_AUTO_CLK,
    };
    esp_err_t err = ledc_timer_config(&timer);
    if (err == ESP_OK) {
        ledc_channel_config_t channel = {
            .gpio_num = CONFIG_ATALAIA_BUZZER_PIN,
            .speed_mode = BZ_MODE,
            .channel = BZ_CHANNEL,
            .timer_sel = BZ_TIMER,
            .duty = 0,
            .hpoint = 0,
        };
        err = ledc_channel_config(&channel);
    }
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "LEDC setup on GPIO %d failed: %s", CONFIG_ATALAIA_BUZZER_PIN,
                 esp_err_to_name(err));
        return -1;
    }
    ready = true;
    ESP_LOGI(TAG, "piezo buzzer on GPIO %d", CONFIG_ATALAIA_BUZZER_PIN);
    return 0;
}

static void esp_buzzer_tone(uint32_t freq_hz)
{
    if (!ready) return;
    uint32_t duty = duty_for_volume();
    if (freq_hz == 0 || duty == 0) {
        ledc_stop(BZ_MODE, BZ_CHANNEL, 0); /* idle low */
        return;
    }
    if (freq_hz < BZ_MIN_HZ) freq_hz = BZ_MIN_HZ;
    if (freq_hz > BZ_MAX_HZ) freq_hz = BZ_MAX_HZ;
    if (ledc_set_freq(BZ_MODE, BZ_TIMER, freq_hz) != ESP_OK) return;
    ledc_set_duty(BZ_MODE, BZ_CHANNEL, duty);
    ledc_update_duty(BZ_MODE, BZ_CHANNEL);
}

static void esp_buzzer_set_volume(uint8_t v)
{
    volume = v > 100 ? 100 : v;
}

static void esp_buzzer_deinit(void)
{
    if (!ready) return;
    ledc_stop(BZ_MODE, BZ_CHANNEL, 0);
    ready = false;
}

const hal_buzzer_ops_t hal_esp_buzzer_ops = {
    .init = esp_buzzer_init,
    .tone = esp_buzzer_tone,
    .set_volume = esp_buzzer_set_volume,
    .deinit = esp_buzzer_deinit,
};

#endif /* CONFIG_ATALAIA_BUZZER */

#endif /* ESP_PLATFORM */
