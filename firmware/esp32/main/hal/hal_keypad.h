/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

#ifndef HAL_KEYPAD_H
#define HAL_KEYPAD_H

#define HAL_KEY_NONE 0

typedef struct {
    int (*init)(void);
    char (*scan)(void); /* returns key character '0'-'9','*','#' or HAL_KEY_NONE */
    void (*deinit)(void);
} hal_keypad_ops_t;

#endif /* HAL_KEYPAD_H */
