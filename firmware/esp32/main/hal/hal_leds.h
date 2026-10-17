/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

#ifndef HAL_LEDS_H
#define HAL_LEDS_H

#include <stdint.h>

typedef struct {
    int (*init)(void);
    void (*fill)(uint8_t r, uint8_t g, uint8_t b);
    void (*set)(int index, uint8_t r, uint8_t g, uint8_t b);
    void (*show)(void);
    void (*set_brightness)(uint8_t brightness);
    void (*deinit)(void);
} hal_led_ops_t;

#endif /* HAL_LEDS_H */
