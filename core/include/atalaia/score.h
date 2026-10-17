/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Per-node score counters. Each team has two counters that only ever grow:
 * points gained and points lost to penalties. Two copies of the same node's
 * counters merge by taking the maximum of each counter, so a node that was
 * cut off from the field can reconnect without any conflict to resolve.
 * Field totals are the sum over all nodes. See "State, scores and
 * partitions" in the design specification.
 */
#ifndef ATALAIA_SCORE_H
#define ATALAIA_SCORE_H

#include <stdbool.h>
#include <stdint.h>

#include "atalaia/event.h"

typedef struct {
    uint32_t gained[ATALAIA_TEAM_MAX + 1]; /* index 0 (no team) is unused */
    uint32_t lost[ATALAIA_TEAM_MAX + 1];
} atalaia_score_t;

void atalaia_score_init(atalaia_score_t *score);

/*
 * Adds points (amount > 0) or a penalty (amount < 0) for a team.
 * Counters saturate instead of wrapping. Returns false if the team id is
 * ATALAIA_TEAM_NONE or out of range.
 */
bool atalaia_score_add(atalaia_score_t *score, uint8_t team, int32_t amount);

/* Points gained minus points lost for one team on this node. */
int64_t atalaia_score_net(const atalaia_score_t *score, uint8_t team);

/* Merges another copy of the same node's counters into this one. */
void atalaia_score_merge(atalaia_score_t *into, const atalaia_score_t *from);

#endif /* ATALAIA_SCORE_H */
