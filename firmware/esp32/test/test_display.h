/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Headless LVGL display for the host tests (no SDL): the same 320x240
 * RGB565 display the Field Box drives, rendered into memory.
 */
#ifndef ATALAIA_FW_TEST_DISPLAY_H
#define ATALAIA_FW_TEST_DISPLAY_H

#include <stdint.h>

#define TEST_DISPLAY_W 320
#define TEST_DISPLAY_H 240

/* Initialise LVGL and the display once; later calls do nothing. */
void test_display_init(void);

/* Redraw the whole active screen now and return the RGB565 framebuffer. */
const uint16_t *test_display_render(void);

/* Convert the framebuffer to 8-bit RGB (TEST_DISPLAY_W * TEST_DISPLAY_H * 3 bytes). */
void test_display_rgb888(uint8_t *rgb);

#endif /* ATALAIA_FW_TEST_DISPLAY_H */
