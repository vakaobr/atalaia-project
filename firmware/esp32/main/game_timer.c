/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#include "game_timer.h"

void game_timer_init(game_timer_t *t, uint32_t duration_ms)
{
    t->duration_ms = duration_ms;
    t->elapsed_ms = 0;
    t->expired = false;
}

bool game_timer_tick(game_timer_t *t, uint32_t delta_ms, atalaia_node_t *node)
{
    if (t->expired || t->duration_ms == 0) return false;

    t->elapsed_ms += delta_ms;

    if (t->elapsed_ms >= t->duration_ms) {
        t->expired = true;
        if (node) {
            atalaia_node_input(node, "game.end", NULL);
        }
        return true;
    }
    return false;
}

uint32_t game_timer_remaining_ms(const game_timer_t *t)
{
    if (t->duration_ms == 0) return UINT32_MAX;
    if (t->expired || t->elapsed_ms >= t->duration_ms) return 0;
    return t->duration_ms - t->elapsed_ms;
}
