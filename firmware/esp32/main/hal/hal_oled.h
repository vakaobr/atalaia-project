/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

#ifndef HAL_OLED_H
#define HAL_OLED_H

#include <stdint.h>

/* The Heltec V4's on-board 0.96" SSD1306: 128x64, one bit per pixel. */
#define HAL_OLED_WIDTH  128
#define HAL_OLED_HEIGHT 64
/* SSD1306 page layout: 8 pages of 8 rows; byte x of page p holds column x,
 * rows 8p (bit 0) to 8p+7 (bit 7). */
#define HAL_OLED_FB_SIZE (HAL_OLED_WIDTH * HAL_OLED_HEIGHT / 8)

typedef struct {
    /* 0 = ok; -1 = no panel (the box runs without it). */
    int (*init)(void);
    /* Sends the pages of fb that differ from the last frame sent. 0 = ok. */
    int (*write)(const uint8_t fb[HAL_OLED_FB_SIZE]);
    void (*deinit)(void);
} hal_oled_ops_t;

#endif /* HAL_OLED_H */
