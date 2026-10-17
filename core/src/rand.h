/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Deterministic random numbers for scripts (xoshiro128**). Seeded from the
 * game seed and the node id, so every node gets its own sequence and a game
 * log can be replayed exactly.
 */
#ifndef ATALAIA_RAND_H
#define ATALAIA_RAND_H

#include <stdint.h>

typedef struct {
    uint32_t s[4];
} atalaia_rand_t;

void atalaia_rand_seed(atalaia_rand_t *r, uint32_t game_seed, uint16_t node_id);

uint32_t atalaia_rand_next(atalaia_rand_t *r);

/* Uniform integer in [0, bound). bound must be greater than zero. */
uint32_t atalaia_rand_below(atalaia_rand_t *r, uint32_t bound);

/* Uniform number in [0, 1). */
double atalaia_rand_unit(atalaia_rand_t *r);

#endif /* ATALAIA_RAND_H */
