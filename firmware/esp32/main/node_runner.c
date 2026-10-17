/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#include "node_runner.h"

#include <stdio.h>
#include <string.h>

#include "state_persist.h"

/* ---------- Core callbacks (static, wire to the runner context) ---------- */

static void on_event(void *user, const atalaia_event_t *ev, const char *data_json)
{
    node_runner_t *r = (node_runner_t *)user;
    (void)data_json;
    r->event_count++;
    snprintf(r->last_event_type, sizeof(r->last_event_type), "%s", ev->type);
}

static void on_command(void *user, const char *target, const char *method, const char *args_json)
{
    node_runner_t *r = (node_runner_t *)user;
    command_dispatch(target, method, args_json, r->hal, &r->queues);
}

static void on_log(void *user, const char *message)
{
    (void)user;
    (void)message;
}

/* ------------------------------------------------------------------ */

void node_runner_init(node_runner_t *r, hal_t *hal, size_t mem_limit)
{
    memset(r, 0, sizeof(*r));
    r->hal = hal;
    r->mem_limit = mem_limit;
    command_queues_init(&r->queues);
}

bool node_runner_start(node_runner_t *r, const preset_t *preset, const char *const *teams,
                       uint8_t team_count)
{
    if (!r || !preset || !teams || team_count == 0) return false;

    /* Destroy any previous node. */
    if (r->node) {
        atalaia_node_destroy(r->node);
        r->node = NULL;
    }

    /* Reset state. */
    command_queues_init(&r->queues);
    r->event_count = 0;
    r->last_event_type[0] = '\0';
    r->game_time_ms = 0;
    r->persist_accum_ms = 0;
    r->team_count = team_count;

    /* Create the node. */
    atalaia_node_config_t cfg = {0};
    cfg.node_id = 1;
    cfg.game_seed = 42;
    cfg.mem_limit = r->mem_limit;
    cfg.instr_limit = 1000000;
    cfg.callbacks.event = on_event;
    cfg.callbacks.command = on_command;
    cfg.callbacks.log = on_log;
    cfg.callbacks.user = r;

    r->node = atalaia_node_create(&cfg);
    if (!r->node) return false;

    /* Configure teams. */
    if (!atalaia_node_set_teams(r->node, teams, team_count)) {
        atalaia_node_destroy(r->node);
        r->node = NULL;
        return false;
    }

    /* Set params. */
    if (preset->params_json[0]) {
        atalaia_node_set_params(r->node, preset->params_json);
    }

    /* Load mode source. */
    if (!atalaia_node_load(r->node, preset->source, preset->source_len, "mode/node.lua")) {
        atalaia_node_destroy(r->node);
        r->node = NULL;
        return false;
    }

    /* Initialise the game timer. */
    game_timer_init(&r->timer, preset->duration_s * 1000u);

    /* Start the game. */
    atalaia_node_input(r->node, "game.start", NULL);
    r->running = true;

    return true;
}

bool node_runner_resume(node_runner_t *r, const state_persist_data_t *saved, const char *source,
                        size_t source_len, const char *params_json, const char *const *teams,
                        uint8_t team_count)
{
    if (!r || !saved || !source || !teams || team_count == 0) return false;

    /* Destroy any previous node. */
    if (r->node) {
        atalaia_node_destroy(r->node);
        r->node = NULL;
    }

    /* Reset state. */
    command_queues_init(&r->queues);
    r->event_count = 0;
    r->last_event_type[0] = '\0';
    r->game_time_ms = 0;
    r->persist_accum_ms = 0;
    r->team_count = team_count;
    r->preset_index = saved->preset_index;

    /* Create the node. */
    atalaia_node_config_t cfg = {0};
    cfg.node_id = 1;
    cfg.game_seed = 42;
    cfg.mem_limit = r->mem_limit;
    cfg.instr_limit = 1000000;
    cfg.callbacks.event = on_event;
    cfg.callbacks.command = on_command;
    cfg.callbacks.log = on_log;
    cfg.callbacks.user = r;

    r->node = atalaia_node_create(&cfg);
    if (!r->node) return false;

    /* Configure teams. */
    if (!atalaia_node_set_teams(r->node, teams, team_count)) {
        atalaia_node_destroy(r->node);
        r->node = NULL;
        return false;
    }

    /* Set params before loading source (mode top-level code reads params). */
    if (params_json && params_json[0]) {
        atalaia_node_set_params(r->node, params_json);
    }

    /* Load mode source. */
    if (!atalaia_node_load(r->node, source, source_len, "mode/node.lua")) {
        atalaia_node_destroy(r->node);
        r->node = NULL;
        return false;
    }

    /* Restore the game timer from saved state. */
    game_timer_init(&r->timer, saved->timer_duration_ms);
    /* Fast-forward the timer's elapsed counter without firing game.end. */
    r->timer.elapsed_ms = saved->timer_elapsed_ms;

    /* Start the game. */
    atalaia_node_input(r->node, "game.start", NULL);

    /* Advance game time to where we left off. */
    r->game_time_ms = saved->game_time_ms;
    atalaia_node_advance(r->node, saved->game_time_ms);

    /* Notify the mode that we resumed from a reboot. */
    atalaia_node_input(r->node, "node.rebooted", NULL);

    r->running = true;
    return true;
}

void node_runner_tick(node_runner_t *r, uint32_t delta_ms)
{
    if (!r || !r->node || !r->running) return;

    r->game_time_ms += delta_ms;

    /* Advance the core's game time. */
    atalaia_node_advance(r->node, r->game_time_ms);

    /* Tick the game timer (may send game.end). */
    game_timer_tick(&r->timer, delta_ms, r->node);

    /* Persist state every second. */
    r->persist_accum_ms += delta_ms;
    if (r->persist_accum_ms >= 1000) {
        r->persist_accum_ms -= 1000;
        state_persist_save(r->node, &r->timer, r->preset_index, r->team_count);
    }
}

bool node_runner_input(node_runner_t *r, const char *type, const char *data_json)
{
    if (!r || !r->node || !r->running) return false;
    return atalaia_node_input(r->node, type, data_json);
}

atalaia_node_status_t node_runner_status(const node_runner_t *r)
{
    if (!r || !r->node) return ATALAIA_NODE_EMPTY;
    return atalaia_node_status(r->node);
}

void node_runner_stop(node_runner_t *r)
{
    if (!r) return;
    if (r->node) {
        atalaia_node_destroy(r->node);
        r->node = NULL;
    }
    r->running = false;
}
