/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

#ifndef HAL_BATTERY_H
#define HAL_BATTERY_H

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    uint16_t voltage_mv;
    uint8_t percent;
    bool charging;
} hal_battery_info_t;

typedef struct {
    int (*init)(void);
    hal_battery_info_t (*read)(void);
    void (*deinit)(void);
} hal_battery_ops_t;

#endif /* HAL_BATTERY_H */
