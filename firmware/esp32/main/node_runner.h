/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Node runner: owns the atalaia_node_t and game timer, wires the
 * core callbacks to the command dispatcher, and drives the game loop.
 */
#ifndef ATALAIA_NODE_RUNNER_H
#define ATALAIA_NODE_RUNNER_H

#include <stdbool.h>
#include <stdint.h>

#include "atalaia/node.h"
#include "command_dispatch.h"
#include "game_timer.h"
#include "hal/hal.h"
#include "preset_store.h"
#include "state_persist.h"

typedef struct {
    atalaia_node_t *node;
    game_timer_t timer;
    hal_t *hal;
    command_queues_t queues;
    int preset_index;
    uint8_t team_count;
    uint32_t game_time_ms;
    uint32_t persist_accum_ms;
    size_t mem_limit;
    bool running;
    /* The running mode's id: its screen templates (screen_template.h) apply. */
    char mode_id[PRESET_MODE_ID_MAX];
    /* Identity in a joined game (1 and 42 for a stand-alone game). */
    uint16_t node_id;
    uint32_t game_seed;
    /* Every event the node emits also goes here (the radio link); may be NULL. */
    void (*event_hook)(void *ctx, const atalaia_event_t *ev, const char *data_json);
    void *event_ctx;
    /* Event recording for tests. */
    int event_count;
    char last_event_type[64];
} node_runner_t;

/*
 * Initialise the runner. Does not start the game yet.
 */
/*
 * Initialise the runner. mem_limit is the Lua heap cap in bytes
 * (256 KB for Full tier, 64 KB for Reduced; 0 = core default).
 */
void node_runner_init(node_runner_t *r, hal_t *hal, size_t mem_limit);

/*
 * The mode whose screen templates the display uses. node_runner_start takes
 * it from the preset; call this before node_runner_resume.
 */
void node_runner_set_mode(node_runner_t *r, const char *mode_id);

/*
 * Load and start a game from a preset. Creates the node, loads the mode
 * source, sets teams and params, starts the game timer, sends game.start.
 * teams is an array of team_count C strings.
 */
bool node_runner_start(node_runner_t *r, const preset_t *preset, const char *const *teams,
                       uint8_t team_count);

/*
 * Advance the game by delta_ms. Polls no hardware (the caller does
 * that); advances the core's game time, ticks the game timer, and
 * persists state every second.
 */
void node_runner_tick(node_runner_t *r, uint32_t delta_ms);

/*
 * Feed a hardware event to the node (e.g. "team_input.hold").
 */
bool node_runner_input(node_runner_t *r, const char *type, const char *data_json);

/* Get the underlying node status. */
atalaia_node_status_t node_runner_status(const node_runner_t *r);

/*
 * Resume a game from persisted state after a reboot. Creates the node,
 * loads the mode source, sets params, restores game time and timer,
 * then sends "node.rebooted". params_json may be NULL.
 * Returns true on success.
 */
bool node_runner_resume(node_runner_t *r, const state_persist_data_t *saved, const char *source,
                        size_t source_len, const char *params_json, const char *const *teams,
                        uint8_t team_count);

/* Destroy the node and reset the runner. */
void node_runner_stop(node_runner_t *r);

#endif /* ATALAIA_NODE_RUNNER_H */
