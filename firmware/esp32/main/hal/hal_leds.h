/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

#ifndef HAL_LEDS_H
#define HAL_LEDS_H

#include <stdint.h>

/* A colour channel at a brightness in percent (0-100, clamped), rounded. */
static inline uint8_t hal_led_scale(uint8_t value, int percent)
{
    if (percent < 0) percent = 0;
    if (percent > 100) percent = 100;
    return (uint8_t)((value * percent + 50) / 100);
}

typedef struct {
    int (*init)(void);
    void (*fill)(uint8_t r, uint8_t g, uint8_t b);
    void (*set)(int index, uint8_t r, uint8_t g, uint8_t b);
    void (*show)(void);
    void (*set_brightness)(uint8_t brightness); /* percent, 0-100; applied at the next show() */
    void (*deinit)(void);
} hal_led_ops_t;

#endif /* HAL_LEDS_H */
