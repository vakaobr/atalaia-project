/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Deterministic random numbers for scripts (xoshiro128**). Seeded from the
 * game's secret key, the game seed and the node id: every node gets its own
 * sequence, a game can be replayed exactly by anyone who holds the key, and
 * nobody else can predict it (the seed and the node ids are public: LIVE2-2).
 */
#ifndef ATALAIA_RAND_H
#define ATALAIA_RAND_H

#include <stdint.h>

typedef struct {
    uint32_t s[4];
} atalaia_rand_t;

/* The state is the first 16 bytes of HMAC-SHA256(key, "atalaia/rand/v1" || game_seed (4 bytes,
 * big-endian) || node_id (2 bytes, big-endian)), read as four little-endian words (an all-zero
 * state becomes {1,0,0,0}). Every platform derives it the same way:
 * protocol/vectors/rand.json. */
#define ATALAIA_RAND_KEY_SIZE 16
void atalaia_rand_seed_keyed(atalaia_rand_t *r, const uint8_t key[ATALAIA_RAND_KEY_SIZE],
                             uint32_t game_seed, uint16_t node_id);

/* Without a key (a stand-alone game, a test): the seed and the node id alone. Predictable by
 * anyone who sees them, so a joined game never uses it. */
void atalaia_rand_seed(atalaia_rand_t *r, uint32_t game_seed, uint16_t node_id);

uint32_t atalaia_rand_next(atalaia_rand_t *r);

/* Uniform integer in [0, bound). bound must be greater than zero. */
uint32_t atalaia_rand_below(atalaia_rand_t *r, uint32_t bound);

/* Uniform number in [0, 1). */
double atalaia_rand_unit(atalaia_rand_t *r);

#endif /* ATALAIA_RAND_H */
