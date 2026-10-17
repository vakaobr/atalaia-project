/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

#ifndef HAL_BUTTONS_H
#define HAL_BUTTONS_H

#include <stdint.h>

#define HAL_BUTTON_1 (1u << 0)
#define HAL_BUTTON_2 (1u << 1)
#define HAL_BUTTON_3 (1u << 2)
#define HAL_BUTTON_4 (1u << 3)

typedef struct {
    int (*init)(void);
    uint8_t (*poll)(void); /* returns bitmask of pressed buttons */
    void (*deinit)(void);
} hal_button_ops_t;

#endif /* HAL_BUTTONS_H */
