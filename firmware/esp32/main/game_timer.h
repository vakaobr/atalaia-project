/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Shell-owned game countdown timer. When the timer expires it sends
 * game.end to the node via atalaia_node_input (ADR-P1-3).
 */
#ifndef ATALAIA_GAME_TIMER_H
#define ATALAIA_GAME_TIMER_H

#include <stdbool.h>
#include <stdint.h>

#include "atalaia/node.h"

typedef struct {
    uint32_t duration_ms; /* 0 = unlimited (never expires) */
    uint32_t elapsed_ms;
    bool expired;
} game_timer_t;

/* Initialise the timer. duration_ms == 0 means unlimited. */
void game_timer_init(game_timer_t *t, uint32_t duration_ms);

/*
 * Advance the timer by delta_ms. If the timer crosses the duration
 * boundary, calls atalaia_node_input(node, "game.end", NULL) exactly
 * once and returns true. Subsequent calls return false.
 */
bool game_timer_tick(game_timer_t *t, uint32_t delta_ms, atalaia_node_t *node);

/* Milliseconds remaining; 0 when expired; UINT32_MAX when unlimited. */
uint32_t game_timer_remaining_ms(const game_timer_t *t);

#endif /* ATALAIA_GAME_TIMER_H */
