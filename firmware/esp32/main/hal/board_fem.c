/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * Pin steps for the Heltec V4 radio front-end module (see board_fem.h).
 */
#include "board_fem.h"

static size_t add(board_pin_step_t *steps, size_t n, size_t max, int pin, uint8_t level,
                  uint16_t delay_us)
{
    if (pin < 0 || n >= max) return n;
    steps[n].pin = pin;
    steps[n].level = level;
    steps[n].delay_us = delay_us;
    return n + 1;
}

size_t board_fem_power_on(const board_fem_pins_t *p, board_pin_step_t *steps, size_t max)
{
    if (p->fem == BOARD_FEM_NONE) return 0;
    size_t n = 0;
    n = add(steps, n, max, p->power_pin, 1, BOARD_FEM_LDO_SETTLE_US);
    if (p->fem == BOARD_FEM_GC1109) n = add(steps, n, max, p->pa_pin, 1, 0);
    if (p->fem == BOARD_FEM_KCT8103L) n = add(steps, n, max, p->ctx_pin, 0, 0);
    n = add(steps, n, max, p->enable_pin, 1, 0);
    return n;
}

size_t board_fem_power_off(const board_fem_pins_t *p, board_pin_step_t *steps, size_t max)
{
    if (p->fem == BOARD_FEM_NONE) return 0;
    size_t n = 0;
    n = add(steps, n, max, p->enable_pin, 0, 0);
    if (p->fem == BOARD_FEM_GC1109) n = add(steps, n, max, p->pa_pin, 0, 0);
    if (p->fem == BOARD_FEM_KCT8103L) n = add(steps, n, max, p->ctx_pin, 0, 0);
    n = add(steps, n, max, p->power_pin, 0, 0);
    return n;
}

int board_fem_conflict(const board_fem_pins_t *p, const int *pins, size_t n)
{
    if (p->fem == BOARD_FEM_NONE) return -1;
    int used[4] = {p->power_pin, p->enable_pin, p->fem == BOARD_FEM_GC1109 ? p->pa_pin : -1,
                   p->fem == BOARD_FEM_KCT8103L ? p->ctx_pin : -1};
    for (size_t i = 0; i < n; i++) {
        if (pins[i] < 0) continue;
        for (size_t k = 0; k < 4; k++) {
            if (pins[i] == used[k]) return pins[i];
        }
    }
    return -1;
}

const char *board_fem_name(board_fem_t fem)
{
    switch (fem) {
    case BOARD_FEM_GC1109: return "GC1109 (Heltec V4.2)";
    case BOARD_FEM_KCT8103L: return "KCT8103L (Heltec V4.3)";
    default: return "none";
    }
}
