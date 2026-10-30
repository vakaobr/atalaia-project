/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The per-source replay window (atalaia/replay.h).
 */
#include "atalaia/replay.h"

#include <string.h>

void atalaia_replay_init(atalaia_replay_t *w)
{
    memset(w, 0, sizeof(*w));
}

atalaia_replay_verdict_t atalaia_replay_check(const atalaia_replay_t *w, uint32_t ctr)
{
    if (!w->have || ctr > w->high) return ATALAIA_REPLAY_FRESH;
    uint32_t back = w->high - ctr;
    if (back >= ATALAIA_REPLAY_WIDTH) return ATALAIA_REPLAY_TOO_OLD;
    return (w->seen >> back) & 1u ? ATALAIA_REPLAY_DUPLICATE : ATALAIA_REPLAY_FRESH;
}

atalaia_replay_verdict_t atalaia_replay_accept(atalaia_replay_t *w, uint32_t ctr)
{
    atalaia_replay_verdict_t v = atalaia_replay_check(w, ctr);
    if (v != ATALAIA_REPLAY_FRESH) return v;
    if (!w->have) {
        w->have = true;
        w->high = ctr;
        w->seen = 1u;
    } else if (ctr > w->high) {
        uint32_t ahead = ctr - w->high;
        w->seen = ahead >= ATALAIA_REPLAY_WIDTH ? 0u : w->seen << ahead;
        w->seen |= 1u;
        w->high = ctr;
    } else {
        w->seen |= (uint64_t)1 << (w->high - ctr);
    }
    return v;
}
