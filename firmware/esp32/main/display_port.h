/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * LVGL display port for the ESP-IDF build (ADR-P1-2): two DMA-capable
 * draw buffers of 1/10 screen, flushed through hal_display_ops_t, with
 * the DMA-done interrupt calling lv_display_flush_ready(). Every call
 * here must come from the LVGL task.
 */
#ifndef ATALAIA_DISPLAY_PORT_H
#define ATALAIA_DISPLAY_PORT_H

#include <stdbool.h>

#include "lvgl.h"

#include "hal/hal_display.h"
#include "hal/hal_oled.h"

/*
 * Initialise LVGL and the display. If the display driver fails, LVGL still
 * runs on a display that discards its pixels, so the game goes on without
 * a screen. Returns true when the panel driver came up.
 */
bool display_port_init(const hal_display_ops_t *ops);

/*
 * Add the on-board OLED as a second LVGL display (128x64, rendered in
 * RGB565 and packed to one bit per pixel on flush), after
 * display_port_init(). Returns its screen, or NULL when there is no OLED.
 * The TFT stays LVGL's default display.
 */
lv_obj_t *display_port_oled_init(const hal_oled_ops_t *ops);

/* Run LVGL's timers and redraw what changed. Returns ms until the next call is due. */
unsigned display_port_handle(void);

#endif /* ATALAIA_DISPLAY_PORT_H */
