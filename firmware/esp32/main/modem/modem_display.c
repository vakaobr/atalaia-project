/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The USB radio modem's on-board OLED task (modem_display.h).
 *
 * The modem task publishes a copy of its state (modem_task_screen_state);
 * this task alone runs LVGL (LV_USE_OS is none) and the I2C bus, which on a
 * bare modem board carries nothing but the OLED. At the bus's 100 kHz a full
 * frame takes ~100 ms and a changed line or two a few ms, all at priority 1,
 * below the radio (3) and the modem (4) tasks.
 */
#include "modem_display.h"

#include <stdbool.h>
#include <string.h>

#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "lvgl.h"
#include "modem_screen.h"
#include "modem_task.h"
#include "oled_view.h"
#include "sdkconfig.h"

#ifndef CONFIG_ATALAIA_OLED_SPLASH_MS
#define CONFIG_ATALAIA_OLED_SPLASH_MS 2000
#endif

#define DISPLAY_TASK_STACK 6144
#define DISPLAY_TASK_PRIO  1
#define DISPLAY_PERIOD_MS  500

static const char *TAG = "modem_oled";

static const hal_oled_ops_t *oled;
static const char *fw_version;
static const char *fault;
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
            /* hal_esp_oled resends the whole frame next time. */
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
        /* hal_esp_oled has said why; the modem runs without its screen. */
        vTaskDelete(NULL);
        return;
    }
    lv_init();
    lv_tick_set_cb(tick_ms);
    const size_t buf_size = HAL_OLED_WIDTH * HAL_OLED_HEIGHT * 2;
    void *buf = heap_caps_malloc(buf_size, MALLOC_CAP_8BIT);
    if (!buf) {
        ESP_LOGW(TAG, "no memory for the OLED frame: OLED status off");
        oled->deinit();
        vTaskDelete(NULL);
        return;
    }
    lv_display_t *disp = lv_display_create(HAL_OLED_WIDTH, HAL_OLED_HEIGHT);
    lv_display_set_color_format(disp, LV_COLOR_FORMAT_RGB565);
    lv_display_set_buffers(disp, buf, NULL, buf_size, LV_DISPLAY_RENDER_MODE_FULL);
    lv_display_set_flush_cb(disp, flush);
    lv_obj_t *scr = lv_display_get_screen_active(disp);

    if (CONFIG_ATALAIA_OLED_SPLASH_MS > 0) {
        modem_screen_splash(scr, fw_version); /* the whole version, shown short (FV-8) */
        lv_refr_now(disp);
        vTaskDelay(pdMS_TO_TICKS(CONFIG_ATALAIA_OLED_SPLASH_MS));
    }
    ESP_LOGI(TAG, "OLED status on");

    static modem_screen_text_t shown;
    bool first = true;
    for (;;) {
        modem_screen_state_t state;
        modem_task_screen_state(&state, fault);
        modem_screen_text_t text;
        modem_screen_text(&state, &text);
        if (first || memcmp(&text, &shown, sizeof(text)) != 0) {
            modem_screen_draw(scr, &text);
            lv_refr_now(disp);
            shown = text;
            first = false;
        }
        vTaskDelay(pdMS_TO_TICKS(DISPLAY_PERIOD_MS));
    }
}

void modem_display_start(const hal_oled_ops_t *ops, const char *version, const char *radio_fault)
{
    if (!ops || !ops->init || !ops->write) return;
    oled = ops;
    fw_version = version;
    fault = radio_fault;
    /* Core 0 with the radio task (priority 3), which preempts it; the modem
     * task has core 1 to itself. */
    if (xTaskCreatePinnedToCore(display_loop, "modem_oled", DISPLAY_TASK_STACK, NULL,
                                DISPLAY_TASK_PRIO, NULL, 0) != pdPASS) {
        ESP_LOGW(TAG, "no memory for the OLED task: OLED status off");
    }
}
