/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Game state persistence: saves and restores game time, scores and the
 * current preset index so the node can resume after a reboot.
 */
#ifndef ATALAIA_STATE_PERSIST_H
#define ATALAIA_STATE_PERSIST_H

#include <stdbool.h>
#include <stdint.h>

#include "atalaia/node.h"
#include "game_timer.h"

#define STATE_PERSIST_MAGIC   0x41544C53u /* "ATLS" */
#define STATE_PERSIST_VERSION 1

typedef struct {
    uint32_t magic;
    uint32_t version;
    uint32_t timer_duration_ms;
    uint32_t timer_elapsed_ms;
    uint32_t game_time_ms;
    int preset_index;
    uint32_t gained[8]; /* scores for up to 8 teams */
    uint32_t lost[8];
    uint8_t team_count;
} state_persist_data_t;

/*
 * Initialise the persistence layer. base_path is the directory for
 * the state file (e.g. "/littlefs/state" or a temp dir in tests).
 */
int state_persist_init(const char *base_path);

/*
 * Save current game state. Extracts scores from the node and timer state.
 */
bool state_persist_save(const atalaia_node_t *node, const game_timer_t *timer, int preset_index,
                        uint8_t team_count);

/*
 * Load previously saved state. Returns true if valid state was found.
 */
bool state_persist_load(state_persist_data_t *out);

/* Clear the persisted state file. */
void state_persist_clear(void);

#endif /* ATALAIA_STATE_PERSIST_H */
