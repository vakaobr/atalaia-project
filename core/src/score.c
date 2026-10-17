/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#include "atalaia/score.h"

#include <string.h>

static uint32_t add_saturating(uint32_t a, uint32_t b)
{
    return a > UINT32_MAX - b ? UINT32_MAX : a + b;
}

void atalaia_score_init(atalaia_score_t *score)
{
    memset(score, 0, sizeof(*score));
}

bool atalaia_score_add(atalaia_score_t *score, uint8_t team, int32_t amount)
{
    if (team == ATALAIA_TEAM_NONE || team > ATALAIA_TEAM_MAX) {
        return false;
    }
    if (amount >= 0) {
        score->gained[team] = add_saturating(score->gained[team], (uint32_t)amount);
    } else {
        /* Negate in 64 bits so INT32_MIN does not overflow. */
        uint32_t penalty = (uint32_t)(-(int64_t)amount);
        score->lost[team] = add_saturating(score->lost[team], penalty);
    }
    return true;
}

int64_t atalaia_score_net(const atalaia_score_t *score, uint8_t team)
{
    if (team == ATALAIA_TEAM_NONE || team > ATALAIA_TEAM_MAX) {
        return 0;
    }
    return (int64_t)score->gained[team] - (int64_t)score->lost[team];
}

void atalaia_score_merge(atalaia_score_t *into, const atalaia_score_t *from)
{
    for (unsigned t = 1; t <= ATALAIA_TEAM_MAX; t++) {
        if (from->gained[t] > into->gained[t]) {
            into->gained[t] = from->gained[t];
        }
        if (from->lost[t] > into->lost[t]) {
            into->lost[t] = from->lost[t];
        }
    }
}
