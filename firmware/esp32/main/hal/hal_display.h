/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

#ifndef HAL_DISPLAY_H
#define HAL_DISPLAY_H

#include <stdint.h>

typedef void (*hal_display_flush_ready_cb_t)(void);

typedef void (*hal_display_flush_cb_t)(int x1, int y1, int x2, int y2, const void *color_p,
                                       hal_display_flush_ready_cb_t ready_cb);

typedef struct {
    int (*init)(void);
    hal_display_flush_cb_t flush;
    void (*set_brightness)(uint8_t brightness);
    void (*deinit)(void);
} hal_display_ops_t;

#endif /* HAL_DISPLAY_H */
