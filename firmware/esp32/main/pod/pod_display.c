/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The I/O pod's on-board OLED task (pod_display.h). This task alone runs
 * LVGL (LV_USE_OS is none); the I2C bus is shared with the keypad expander,
 * the NFC reader and the battery gauge, and hal_esp_i2c takes one
 * transaction at a time. A changed passkey screen is two or three pages
 * (~40 ms at 100 kHz); the countdown, one.
 */
#include "pod_display.h"

#include <stdbool.h>
#include <string.h>

#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "lvgl.h"

#define DISPLAY_TASK_STACK 6144
#define DISPLAY_TASK_PRIO  1
#define DISPLAY_PERIOD_MS  200

static const char *TAG = "pod_oled";

static const hal_oled_ops_t *oled;
static void (*reader)(oled_pair_view_t *out);
static bool write_failed_logged;

static uint32_t tick_ms(void)
{
    return (uint32_t)(esp_timer_get_time() / 1000);
}

/* Full render mode: px_map is the whole 128x64 RGB565 frame. */
static void flush(lv_display_t *disp, const lv_area_t *area, uint8_t *px_map)
{
    (void)area;
    if (lv_display_flush_is_last(disp)) {
        static uint8_t fb[HAL_OLED_FB_SIZE];
        oled_pack((const uint16_t *)px_map, fb);
        if (oled->write(fb) != 0 && !write_failed_logged) {
            ESP_LOGW(TAG, "OLED write failed (logged once)");
            write_failed_logged = true;
        }
    }
    lv_display_flush_ready(disp);
}

static void display_loop(void *arg)
{
    (void)arg;
    if (oled->init() != 0) {
        /* hal_esp_oled has said why; the passkey is in the log only. */
        ESP_LOGW(TAG, "no OLED: Bluetooth passkeys are shown in the log only");
        vTaskDelete(NULL);
        return;
    }
    lv_init();
    lv_tick_set_cb(tick_ms);
    const size_t buf_size = HAL_OLED_WIDTH * HAL_OLED_HEIGHT * 2;
    void *buf = heap_caps_malloc(buf_size, MALLOC_CAP_8BIT);
    if (!buf) {
        ESP_LOGW(TAG, "no memory for the OLED frame: passkeys in the log only");
        oled->deinit();
        vTaskDelete(NULL);
        return;
    }
    lv_display_t *disp = lv_display_create(HAL_OLED_WIDTH, HAL_OLED_HEIGHT);
    lv_display_set_color_format(disp, LV_COLOR_FORMAT_RGB565);
    lv_display_set_buffers(disp, buf, NULL, buf_size, LV_DISPLAY_RENDER_MODE_FULL);
    lv_display_set_flush_cb(disp, flush);
    lv_obj_t *scr = lv_display_get_screen_active(disp);
    oled_view_clear(scr);
    lv_refr_now(disp);
    ESP_LOGI(TAG, "OLED ready for pairing");

    static oled_text_t shown;
    bool dark = true;
    for (;;) {
        oled_pair_view_t v;
        reader(&v);
        oled_text_t text;
        if (!oled_text_pair(&v, &text)) {
            if (!dark) {
                oled_view_clear(scr);
                lv_refr_now(disp);
                dark = true;
            }
        } else if (dark || memcmp(&text, &shown, sizeof(text)) != 0) {
            oled_view_draw(scr, &text);
            lv_refr_now(disp);
            shown = text;
            dark = false;
        }
        vTaskDelay(pdMS_TO_TICKS(DISPLAY_PERIOD_MS));
    }
}

void pod_display_start(const hal_oled_ops_t *ops, void (*read)(oled_pair_view_t *out))
{
    if (!ops || !ops->init || !ops->write || !read) return;
    oled = ops;
    reader = read;
    /* Core 0, below the radio task (priority 3); the pod task has core 1. */
    if (xTaskCreatePinnedToCore(display_loop, "pod_oled", DISPLAY_TASK_STACK, NULL,
                                DISPLAY_TASK_PRIO, NULL, 0) != pdPASS) {
        ESP_LOGW(TAG, "no memory for the OLED task: passkeys in the log only");
    }
}
