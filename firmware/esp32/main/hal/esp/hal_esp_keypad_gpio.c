/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * Direct GPIO matrix keypad driver, for the Wokwi emulator build
 * (CONFIG_ATALAIA_KP_GPIO_MATRIX, see sdkconfig.wokwi). Wokwi has no
 * PCF8574 part, so its 4x3 membrane keypad is wired straight to GPIOs
 * that the emulator leaves free (the audio pins, among others). The
 * Field Box itself uses the PCF8574 driver in hal_esp_keypad.c.
 *
 * Rows are outputs, driven low one at a time; columns are inputs with
 * pull-ups. A pressed key pulls its column low while its row is low.
 */

#include "sdkconfig.h"

#if defined(ESP_PLATFORM) && CONFIG_ATALAIA_KP_GPIO_MATRIX

#include "../hal_keypad.h"

#include "driver/gpio.h"
#include "esp_log.h"
#include "esp_rom_sys.h"

static const char *TAG = "hal_kp";

#define NUM_ROWS 4
#define NUM_COLS 3

static const int row_pins[NUM_ROWS] = {
    CONFIG_ATALAIA_KP_ROW0_PIN,
    CONFIG_ATALAIA_KP_ROW1_PIN,
    CONFIG_ATALAIA_KP_ROW2_PIN,
    CONFIG_ATALAIA_KP_ROW3_PIN,
};
static const int col_pins[NUM_COLS] = {
    CONFIG_ATALAIA_KP_COL0_PIN,
    CONFIG_ATALAIA_KP_COL1_PIN,
    CONFIG_ATALAIA_KP_COL2_PIN,
};

static const char keymap[NUM_ROWS][NUM_COLS] = {
    {'1', '2', '3'},
    {'4', '5', '6'},
    {'7', '8', '9'},
    {'*', '0', '#'},
};

static int esp_keypad_gpio_init(void)
{
    uint64_t rows = 0, cols = 0;
    for (int r = 0; r < NUM_ROWS; r++) rows |= 1ULL << (unsigned)row_pins[r];
    for (int c = 0; c < NUM_COLS; c++) cols |= 1ULL << (unsigned)col_pins[c];

    gpio_config_t out = {
        .pin_bit_mask = rows,
        .mode = GPIO_MODE_OUTPUT, /* push-pull: simplest for the emulator */
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_config_t in = {
        .pin_bit_mask = cols,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    if (gpio_config(&out) != ESP_OK || gpio_config(&in) != ESP_OK) {
        ESP_LOGW(TAG, "keypad GPIO setup failed: keypad disabled");
        return -1;
    }
    for (int r = 0; r < NUM_ROWS; r++) gpio_set_level((gpio_num_t)row_pins[r], 1);
    ESP_LOGI(TAG, "GPIO matrix keypad (rows %d %d %d %d, columns %d %d %d)", row_pins[0],
             row_pins[1], row_pins[2], row_pins[3], col_pins[0], col_pins[1], col_pins[2]);
    return 0;
}

static char esp_keypad_gpio_scan(void)
{
    char key = HAL_KEY_NONE;
    for (int r = 0; r < NUM_ROWS && key == HAL_KEY_NONE; r++) {
        gpio_set_level((gpio_num_t)row_pins[r], 0);
        esp_rom_delay_us(5); /* let the column lines settle */
        for (int c = 0; c < NUM_COLS; c++) {
            if (gpio_get_level((gpio_num_t)col_pins[c]) == 0) {
                key = keymap[r][c];
                break;
            }
        }
        gpio_set_level((gpio_num_t)row_pins[r], 1);
    }
    return key;
}

static void esp_keypad_gpio_deinit(void)
{
    for (int r = 0; r < NUM_ROWS; r++) gpio_reset_pin((gpio_num_t)row_pins[r]);
    for (int c = 0; c < NUM_COLS; c++) gpio_reset_pin((gpio_num_t)col_pins[c]);
}

const hal_keypad_ops_t hal_esp_keypad_ops = {
    .init = esp_keypad_gpio_init,
    .scan = esp_keypad_gpio_scan,
    .deinit = esp_keypad_gpio_deinit,
};

#endif /* ESP_PLATFORM && CONFIG_ATALAIA_KP_GPIO_MATRIX */
