/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Listen before talk (atalaia/lbt.h).
 */
#include "atalaia/lbt.h"

#include <stddef.h>

void atalaia_lbt_init(atalaia_lbt_t *l, atalaia_lbt_rand_fn rand, void *rand_ctx)
{
    l->rand = rand;
    l->rand_ctx = rand_ctx;
    l->tries = 0;
}

bool atalaia_lbt_should_listen(const atalaia_lbt_t *l)
{
    return l->tries < ATALAIA_LBT_MAX_TRIES;
}

atalaia_lbt_verdict_t atalaia_lbt_decide(atalaia_lbt_t *l, bool busy, uint32_t *wait_ms)
{
    if (!busy) {
        l->tries = 0;
        return ATALAIA_LBT_SEND;
    }
    if (l->tries >= ATALAIA_LBT_MAX_TRIES) {
        l->tries = 0;
        return ATALAIA_LBT_SEND_ANYWAY;
    }
    l->tries++;
    if (wait_ms != NULL) {
        uint32_t span = ATALAIA_LBT_WAIT_MAX_MS - ATALAIA_LBT_WAIT_MIN_MS + 1u;
        *wait_ms = ATALAIA_LBT_WAIT_MIN_MS + l->rand(l->rand_ctx) % span;
    }
    return ATALAIA_LBT_WAIT;
}

void atalaia_lbt_reset(atalaia_lbt_t *l)
{
    l->tries = 0;
}
