/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * PCF8574 I2C keypad expander driver.
 *
 * Wiring: rows on P0-P3 (active-low output), columns on P4-P6 (input
 * with internal pull-up), P7 kept high: an input for a team button to GND
 * (CONFIG_ATALAIA_KP_P7_BUTTON), read with every scan. The PCF8574 sits on
 * the shared OLED I2C bus (GPIO 17/18) at CONFIG_ATALAIA_KP_I2C_ADDR
 * (default 0x20), or wherever it answers: a PCF8574 at 0x20-0x27, a
 * PCF8574A (sold under the same name) at 0x38-0x3F. The other parts on the
 * bus are never probed: the NFC reader (0x24) and the board's OLED (0x3C).
 *
 * Uses the legacy driver/i2c.h API so NFC, battery and keypad can
 * share the same I2C port without conflicts.
 */

#include "sdkconfig.h"

#if defined(ESP_PLATFORM) && !CONFIG_ATALAIA_KP_GPIO_MATRIX

#include "../hal_keypad.h"
#include "hal_esp.h"
#include "hal_esp_i2c.h"

#include "driver/gpio.h"
#include "driver/i2c.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"

static const char *TAG = "hal_kp";

/* ---- Kconfig defaults ---- */

#ifndef CONFIG_ATALAIA_KP_I2C_ADDR
#define CONFIG_ATALAIA_KP_I2C_ADDR 0x20
#endif
#ifndef CONFIG_ATALAIA_KP_INT_PIN
#define CONFIG_ATALAIA_KP_INT_PIN -1
#endif
#define CONFIG_ATALAIA_KP_I2C_PORT HAL_ESP_I2C_PORT

#define NUM_ROWS 4
#define NUM_COLS 3

/*
 * Standard 3x4 telephone keypad layout:
 *
 *        COL0(P4) COL1(P5) COL2(P6)
 * ROW0(P0)  1        2        3
 * ROW1(P1)  4        5        6
 * ROW2(P2)  7        8        9
 * ROW3(P3)  *        0        #
 */
static const char keymap[NUM_ROWS][NUM_COLS] = {
    {'1', '2', '3'},
    {'4', '5', '6'},
    {'7', '8', '9'},
    {'*', '0', '#'},
};

/* ---- ops implementation ---- */

static bool present;
static uint8_t kp_addr = CONFIG_ATALAIA_KP_I2C_ADDR;
static volatile int p7_pressed = -1; /* -1 until the expander answers */

int hal_esp_keypad_p7_pressed(void)
{
    return p7_pressed;
}

/* Addresses of the bus's other parts, never taken for the keypad. */
static bool reserved(uint8_t addr)
{
    return addr == 0x24 /* PN532 NFC */ || addr == 0x36 /* MAX17048 */ ||
           addr == 0x3C /* SSD1306 OLED */;
}

/* The configured address first, then the PCF8574's and the PCF8574A's. */
static bool find_expander(void)
{
    if (hal_esp_i2c_probe(CONFIG_ATALAIA_KP_I2C_ADDR)) {
        kp_addr = CONFIG_ATALAIA_KP_I2C_ADDR;
        return true;
    }
    static const uint8_t bases[] = {0x20, 0x38};
    for (size_t b = 0; b < sizeof(bases); b++) {
        for (uint8_t a = bases[b]; a < bases[b] + 8; a++) {
            if (a == CONFIG_ATALAIA_KP_I2C_ADDR || reserved(a)) continue;
            if (hal_esp_i2c_probe(a)) {
                kp_addr = a;
                return true;
            }
        }
    }
    return false;
}

static int esp_keypad_init(void)
{
    if (hal_esp_i2c_init() != 0) return -1;

        /* Optional interrupt pin (active-low from PCF8574 INT). */
#if CONFIG_ATALAIA_KP_INT_PIN >= 0
    gpio_config_t int_cfg = {
        .pin_bit_mask = 1ULL << (unsigned)CONFIG_ATALAIA_KP_INT_PIN,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_config(&int_cfg);
#endif

    if (!find_expander()) {
        /* Non-fatal: scan returns KEY_NONE and the box runs on its buttons. */
        present = false;
        ESP_LOGW(TAG, "PCF8574 keypad not found (0x%02X, 0x20-0x27, 0x38-0x3F): keypad disabled",
                 CONFIG_ATALAIA_KP_I2C_ADDR);
        return -1;
    }

    /* Set all pins high (idle / pull-up state). */
    uint8_t all_high = 0xFF;
    esp_err_t err = i2c_master_write_to_device(CONFIG_ATALAIA_KP_I2C_PORT, kp_addr, &all_high, 1,
                                               pdMS_TO_TICKS(100));
    present = err == ESP_OK;
    if (!present) {
        ESP_LOGW(TAG, "PCF8574 keypad at 0x%02X did not take a write (%s): keypad disabled",
                 kp_addr, esp_err_to_name(err));
        return -1;
    }
    ESP_LOGI(TAG, "PCF8574 keypad at 0x%02X%s", kp_addr, kp_addr >= 0x38 ? " (PCF8574A)" : "");
    uint8_t in = 0xFF;
    if (i2c_master_read_from_device(CONFIG_ATALAIA_KP_I2C_PORT, kp_addr, &in, 1,
                                    pdMS_TO_TICKS(100)) == ESP_OK) {
        p7_pressed = (in & 0x80) ? 0 : 1;
    } else {
        p7_pressed = 0;
    }
    return 0;
}

static char esp_keypad_scan(void)
{
    if (!present) return HAL_KEY_NONE;

    for (int r = 0; r < NUM_ROWS; r++) {
        /*
         * Drive row r low (P0-P3), keep columns P4-P6 and P7 high.
         * Byte layout: P7 P6 P5 P4 P3 P2 P1 P0
         */
        uint8_t out = (uint8_t)(0xFF & ~(1u << r));
        esp_err_t err = i2c_master_write_to_device(CONFIG_ATALAIA_KP_I2C_PORT, kp_addr, &out, 1,
                                                   pdMS_TO_TICKS(10));
        if (err != ESP_OK) continue;

        /* Read back the port to see which columns were pulled low. */
        uint8_t in = 0xFF;
        err = i2c_master_read_from_device(CONFIG_ATALAIA_KP_I2C_PORT, kp_addr, &in, 1,
                                          pdMS_TO_TICKS(10));
        if (err != ESP_OK) continue;
        p7_pressed = (in & 0x80) ? 0 : 1; /* P7: a team button to GND */

        for (int c = 0; c < NUM_COLS; c++) {
            if (!(in & (1u << (c + 4)))) {
                /* Key found -- restore idle state before returning. */
                uint8_t idle = 0xFF;
                i2c_master_write_to_device(CONFIG_ATALAIA_KP_I2C_PORT, kp_addr, &idle, 1,
                                           pdMS_TO_TICKS(10));
                return keymap[r][c];
            }
        }
    }

    /* No key pressed -- restore idle state. */
    uint8_t idle = 0xFF;
    i2c_master_write_to_device(CONFIG_ATALAIA_KP_I2C_PORT, kp_addr, &idle, 1, pdMS_TO_TICKS(10));
    return HAL_KEY_NONE;
}

static void esp_keypad_deinit(void)
{
    /* Bus is shared; we do not uninstall the I2C driver here. */
#if CONFIG_ATALAIA_KP_INT_PIN >= 0
    gpio_reset_pin((gpio_num_t)CONFIG_ATALAIA_KP_INT_PIN);
#endif
}

const hal_keypad_ops_t hal_esp_keypad_ops = {
    .init = esp_keypad_init,
    .scan = esp_keypad_scan,
    .deinit = esp_keypad_deinit,
};

#endif /* ESP_PLATFORM && !CONFIG_ATALAIA_KP_GPIO_MATRIX */
