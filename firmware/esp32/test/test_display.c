/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Headless LVGL display for the host tests: 320x240 RGB565, rendered in
 * full into an in-memory framebuffer. No SDL, no window.
 */
#include "test_display.h"

#include <string.h>

#include "lvgl.h"

_Alignas(64) static uint8_t framebuffer[TEST_DISPLAY_W * TEST_DISPLAY_H * 2];
static lv_display_t *display;
static uint32_t fake_ms;

static uint32_t tick_cb(void)
{
    return fake_ms;
}

static void flush_cb(lv_display_t *disp, const lv_area_t *area, uint8_t *px_map)
{
    /* Full render mode: LVGL draws straight into the framebuffer. */
    (void)area;
    (void)px_map;
    lv_display_flush_ready(disp);
}

void test_display_init(void)
{
    if (display) return;
    lv_init();
    lv_tick_set_cb(tick_cb);
    display = lv_display_create(TEST_DISPLAY_W, TEST_DISPLAY_H);
    lv_display_set_color_format(display, LV_COLOR_FORMAT_RGB565);
    lv_display_set_buffers(display, framebuffer, NULL, sizeof(framebuffer),
                           LV_DISPLAY_RENDER_MODE_FULL);
    lv_display_set_flush_cb(display, flush_cb);
}

const uint16_t *test_display_render(void)
{
    fake_ms += 1000;
    lv_obj_invalidate(lv_screen_active());
    lv_refr_now(display);
    return (const uint16_t *)framebuffer;
}

void test_display_rgb888(uint8_t *rgb)
{
    const uint16_t *px = (const uint16_t *)framebuffer;
    for (int i = 0; i < TEST_DISPLAY_W * TEST_DISPLAY_H; i++) {
        uint16_t c = px[i];
        uint8_t r = (uint8_t)((c >> 11) & 0x1F);
        uint8_t g = (uint8_t)((c >> 5) & 0x3F);
        uint8_t b = (uint8_t)(c & 0x1F);
        rgb[3 * i + 0] = (uint8_t)((r << 3) | (r >> 2));
        rgb[3 * i + 1] = (uint8_t)((g << 2) | (g >> 4));
        rgb[3 * i + 2] = (uint8_t)((b << 3) | (b >> 2));
    }
}
