/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#include "display_port.h"

#ifdef ESP_PLATFORM

#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "lvgl.h"

static const char *TAG = "display";

static lv_display_t *display;
static const hal_display_ops_t *panel;

static uint32_t tick_ms(void)
{
    return (uint32_t)(esp_timer_get_time() / 1000);
}

/* Called from the SPI DMA-done interrupt. */
static void flush_done(void)
{
    lv_display_flush_ready(display);
}

static void flush_to_panel(lv_display_t *disp, const lv_area_t *area, uint8_t *px_map)
{
    (void)disp;
    /* LVGL renders little-endian RGB565; the panel takes it big-endian over SPI. */
    lv_draw_sw_rgb565_swap(px_map, lv_area_get_size(area));
    panel->flush(area->x1, area->y1, area->x2, area->y2, px_map, flush_done);
}

static void flush_discard(lv_display_t *disp, const lv_area_t *area, uint8_t *px_map)
{
    (void)area;
    (void)px_map;
    lv_display_flush_ready(disp);
}

bool display_port_init(const hal_display_ops_t *ops)
{
    lv_init();
    lv_tick_set_cb(tick_ms);

    bool panel_ok = ops && ops->init && ops->init() == 0;
    if (!panel_ok) {
        ESP_LOGW(TAG, "display driver failed: running without a screen");
    }
    panel = ops;

    const size_t buf_size = HAL_DISPLAY_WIDTH * HAL_DISPLAY_BUF_LINES * 2;
    void *buf1 = heap_caps_malloc(buf_size, MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL);
    void *buf2 = heap_caps_malloc(buf_size, MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL);
    if (!buf1 || !buf2) {
        ESP_LOGE(TAG, "no DMA memory for the draw buffers");
        heap_caps_free(buf1);
        heap_caps_free(buf2);
        return false;
    }

    display = lv_display_create(HAL_DISPLAY_WIDTH, HAL_DISPLAY_HEIGHT);
    lv_display_set_color_format(display, LV_COLOR_FORMAT_RGB565);
    lv_display_set_buffers(display, buf1, buf2, buf_size, LV_DISPLAY_RENDER_MODE_PARTIAL);
    lv_display_set_flush_cb(display, panel_ok ? flush_to_panel : flush_discard);
    ESP_LOGI(TAG, "LVGL %d.%d.%d on %dx%d, 2 x %u byte draw buffers", LVGL_VERSION_MAJOR,
             LVGL_VERSION_MINOR, LVGL_VERSION_PATCH, HAL_DISPLAY_WIDTH, HAL_DISPLAY_HEIGHT,
             (unsigned)buf_size);
    return panel_ok;
}

unsigned display_port_handle(void)
{
    if (!display) return 100;
    int64_t start = esp_timer_get_time();
    unsigned next = lv_timer_handler();
    /* A redraw blocks the LVGL task; log slow ones for bring-up. */
    int64_t ms = (esp_timer_get_time() - start) / 1000;
    if (ms > 100) ESP_LOGW(TAG, "slow redraw: %d ms", (int)ms);
    return next;
}

#endif /* ESP_PLATFORM */
