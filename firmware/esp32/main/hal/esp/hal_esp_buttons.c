/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

#ifdef ESP_PLATFORM

#include "../hal_buttons.h"
#include "hal_esp.h"

#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_timer.h"

#include <string.h>

/* ---- Pin assignments from Kconfig (-1 = unassigned) ---- */

#ifndef CONFIG_ATALAIA_BTN1_PIN
#define CONFIG_ATALAIA_BTN1_PIN 4
#endif
#ifndef CONFIG_ATALAIA_BTN2_PIN
#define CONFIG_ATALAIA_BTN2_PIN 48
#endif
#ifndef CONFIG_ATALAIA_BTN3_PIN
#define CONFIG_ATALAIA_BTN3_PIN 44
#endif
#ifndef CONFIG_ATALAIA_BTN4_PIN
#define CONFIG_ATALAIA_BTN4_PIN -1
#endif
/* The button on the keypad expander's spare pin P7 (1-4; 0 = none). */
#ifndef CONFIG_ATALAIA_KP_P7_BUTTON
#define CONFIG_ATALAIA_KP_P7_BUTTON 0
#endif
#define P7_INDEX (CONFIG_ATALAIA_KP_P7_BUTTON - 1)

#define DEBOUNCE_US (30 * 1000) /* 30 ms */
#define MAX_BUTTONS 4

static const int btn_pins[MAX_BUTTONS] = {
    CONFIG_ATALAIA_BTN1_PIN,
    CONFIG_ATALAIA_BTN2_PIN,
    CONFIG_ATALAIA_BTN3_PIN,
    CONFIG_ATALAIA_BTN4_PIN,
};

/* A button is either on a GPIO or on the keypad expander's P7, not both. */
#if CONFIG_ATALAIA_KP_P7_BUTTON == 1 && CONFIG_ATALAIA_BTN1_PIN >= 0
#error "Button 1 is on a GPIO and on P7: set ATALAIA_KP_P7_BUTTON to 0 or its GPIO to -1"
#elif CONFIG_ATALAIA_KP_P7_BUTTON == 2 && CONFIG_ATALAIA_BTN2_PIN >= 0
#error "Button 2 is on a GPIO and on P7: set ATALAIA_KP_P7_BUTTON to 0 or its GPIO to -1"
#elif CONFIG_ATALAIA_KP_P7_BUTTON == 3 && CONFIG_ATALAIA_BTN3_PIN >= 0
#error "Button 3 is on a GPIO and on P7: set ATALAIA_KP_P7_BUTTON to 0 or its GPIO to -1"
#elif CONFIG_ATALAIA_KP_P7_BUTTON == 4 && CONFIG_ATALAIA_BTN4_PIN >= 0
#error "Button 4 is on a GPIO and on P7: set ATALAIA_KP_P7_BUTTON to 0 or its GPIO to -1"
#endif

static const char *TAG = "hal_btn";

static int64_t last_change_us[MAX_BUTTONS];
static uint8_t stable_state;

/* P7 as the last keypad scan read it; released without a keypad. */
static int p7_raw(void)
{
#if CONFIG_ATALAIA_KP_P7_BUTTON > 0
    return hal_esp_keypad_p7_pressed() == 1 ? 1 : 0;
#else
    return 0;
#endif
}

/* ---- ops implementation ---- */

static int esp_buttons_init(void)
{
    memset(last_change_us, 0, sizeof(last_change_us));
    stable_state = 0;

    for (int i = 0; i < MAX_BUTTONS; i++) {
        if (btn_pins[i] < 0) continue; /* unassigned */
        gpio_config_t cfg = {
            .pin_bit_mask = 1ULL << (unsigned)btn_pins[i],
            .mode = GPIO_MODE_INPUT,
            .pull_up_en = GPIO_PULLUP_ENABLE,
            .pull_down_en = GPIO_PULLDOWN_DISABLE,
            .intr_type = GPIO_INTR_DISABLE,
        };
        esp_err_t err = gpio_config(&cfg);
        if (err != ESP_OK) {
            return -1;
        }
    }

#if CONFIG_ATALAIA_KP_P7_BUTTON > 0
    ESP_LOGI(TAG, "button %d on the keypad expander's P7 (read with the keypad scan)",
             CONFIG_ATALAIA_KP_P7_BUTTON);
#endif
    /* Bring-up (BRING_UP.md step 4): a button that reads pressed at rest
     * is wired to the switch's NC tab or shorted to ground. */
    for (int i = 0; i < MAX_BUTTONS; i++) {
        if (btn_pins[i] < 0) continue;
        int level = gpio_get_level((gpio_num_t)btn_pins[i]);
        if (level == 0) {
            ESP_LOGW(TAG, "button %d (GPIO %d) reads pressed at rest: NC tab or short to ground?",
                     i + 1, btn_pins[i]);
        } else {
            ESP_LOGI(TAG, "button %d (GPIO %d) released at rest", i + 1, btn_pins[i]);
        }
    }
    return 0;
}

static uint8_t esp_buttons_poll(void)
{
    int64_t now = esp_timer_get_time();

    for (int i = 0; i < MAX_BUTTONS; i++) {
        int raw;
        if (i == P7_INDEX) {
            raw = p7_raw();
        } else if (btn_pins[i] < 0) {
            continue; /* unassigned */
        } else {
            /* Active-low: pressed when GPIO reads 0 */
            raw = gpio_get_level((gpio_num_t)btn_pins[i]) == 0 ? 1 : 0;
        }
        int cur = (stable_state >> i) & 1;

        if (raw != cur) {
            if (now - last_change_us[i] >= DEBOUNCE_US) {
                if (raw) {
                    stable_state |= (uint8_t)(1u << i);
                } else {
                    stable_state &= (uint8_t) ~(1u << i);
                }
                last_change_us[i] = now;
                ESP_LOGI(TAG, "button %d (%s%d) %s", i + 1, i == P7_INDEX ? "P" : "GPIO ",
                         i == P7_INDEX ? 7 : btn_pins[i], raw ? "pressed" : "released");
            }
        } else {
            last_change_us[i] = now;
        }
    }

    return stable_state;
}

static void esp_buttons_deinit(void)
{
    for (int i = 0; i < MAX_BUTTONS; i++) {
        if (btn_pins[i] < 0) continue;
        gpio_reset_pin((gpio_num_t)btn_pins[i]);
    }
}

const hal_button_ops_t hal_esp_button_ops = {
    .init = esp_buttons_init,
    .poll = esp_buttons_poll,
    .deinit = esp_buttons_deinit,
};

#endif /* ESP_PLATFORM */
