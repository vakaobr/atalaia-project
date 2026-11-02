/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#include "rand.h"

#include <string.h>

#include "atalaia/join.h"

static uint64_t splitmix64(uint64_t *x)
{
    uint64_t z = (*x += 0x9E3779B97F4A7C15u);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9u;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBu;
    return z ^ (z >> 31);
}

static uint32_t rotl(uint32_t x, int k)
{
    return (x << k) | (x >> (32 - k));
}

void atalaia_rand_seed(atalaia_rand_t *r, uint32_t game_seed, uint16_t node_id)
{
    uint64_t x = ((uint64_t)game_seed << 16) | node_id;
    uint64_t a = splitmix64(&x);
    uint64_t b = splitmix64(&x);
    r->s[0] = (uint32_t)a;
    r->s[1] = (uint32_t)(a >> 32);
    r->s[2] = (uint32_t)b;
    r->s[3] = (uint32_t)(b >> 32);
    if ((r->s[0] | r->s[1] | r->s[2] | r->s[3]) == 0) {
        r->s[0] = 1; /* the all-zero state never leaves zero */
    }
}

void atalaia_rand_seed_keyed(atalaia_rand_t *r, const uint8_t key[ATALAIA_RAND_KEY_SIZE],
                             uint32_t game_seed, uint16_t node_id)
{
    static const char label[] = "atalaia/rand/v1";
    uint8_t msg[sizeof(label) - 1 + 6];
    size_t n = sizeof(label) - 1;
    memcpy(msg, label, n);
    msg[n++] = (uint8_t)(game_seed >> 24);
    msg[n++] = (uint8_t)(game_seed >> 16);
    msg[n++] = (uint8_t)(game_seed >> 8);
    msg[n++] = (uint8_t)game_seed;
    msg[n++] = (uint8_t)(node_id >> 8);
    msg[n++] = (uint8_t)node_id;
    uint8_t mac[32];
    atalaia_hmac_sha256(key, ATALAIA_RAND_KEY_SIZE, msg, n, mac);
    for (int i = 0; i < 4; i++) {
        r->s[i] = (uint32_t)mac[4 * i] | (uint32_t)mac[4 * i + 1] << 8 |
                  (uint32_t)mac[4 * i + 2] << 16 | (uint32_t)mac[4 * i + 3] << 24;
    }
    if ((r->s[0] | r->s[1] | r->s[2] | r->s[3]) == 0) {
        r->s[0] = 1;
    }
}

uint32_t atalaia_rand_next(atalaia_rand_t *r)
{
    uint32_t *s = r->s;
    uint32_t result = rotl(s[1] * 5, 7) * 9;
    uint32_t t = s[1] << 9;
    s[2] ^= s[0];
    s[3] ^= s[1];
    s[1] ^= s[2];
    s[0] ^= s[3];
    s[2] ^= t;
    s[3] = rotl(s[3], 11);
    return result;
}

uint32_t atalaia_rand_below(atalaia_rand_t *r, uint32_t bound)
{
    /* Reject the low values that would make the modulo biased. */
    uint32_t threshold = (uint32_t)(0u - bound) % bound;
    for (;;) {
        uint32_t x = atalaia_rand_next(r);
        if (x >= threshold) {
            return x % bound;
        }
    }
}

double atalaia_rand_unit(atalaia_rand_t *r)
{
    uint64_t hi = atalaia_rand_next(r);
    uint64_t lo = atalaia_rand_next(r);
    return (double)(((hi << 32) | lo) >> 11) * 0x1.0p-53;
}
