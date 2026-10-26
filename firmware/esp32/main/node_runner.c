/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#include "node_runner.h"

#include <stdio.h>
#include <string.h>

#include "box_text.h"
#include "screen_template.h"
#include "state_persist.h"

#ifdef ESP_PLATFORM
#include "esp_log.h"
static const char *TAG = "game";
#endif

/* ---------- Core callbacks (static, wire to the runner context) ---------- */

static void on_event(void *user, const atalaia_event_t *ev, const char *data_json)
{
    node_runner_t *r = (node_runner_t *)user;
#ifdef ESP_PLATFORM
    /* The serial log is the bring-up checklist's (and Wokwi's) view of the game. */
    ESP_LOGI(TAG, "event %s %s", ev->type, data_json ? data_json : "{}");
#else
    (void)data_json;
#endif
    r->event_count++;
    snprintf(r->last_event_type, sizeof(r->last_event_type), "%s", ev->type);
    if (r->event_hook != NULL) r->event_hook(r->event_ctx, ev, data_json);
}

static void on_command(void *user, const char *target, const char *method, const char *args_json)
{
    node_runner_t *r = (node_runner_t *)user;
    command_dispatch(target, method, args_json, r->hal, &r->queues);
}

static void on_log(void *user, const char *message)
{
    (void)user;
#ifdef ESP_PLATFORM
    ESP_LOGI(TAG, "mode: %s", message);
#else
    (void)message;
#endif
}

/* Tells the display which mode runs, first in the screen queue (screen_template.h). */
static void announce_mode(node_runner_t *r, const char *params_json)
{
    if (r->queues.screen_count >= CMD_SCREEN_QUEUE_MAX) return;
    screen_update_t *su = &r->queues.screens[r->queues.screen_count];
    snprintf(su->template_name, sizeof(su->template_name), "%s", SCREEN_MODE_MESSAGE);
    const char *params = params_json && params_json[0] ? params_json : "{}";
    int n = snprintf(su->data_json, sizeof(su->data_json), "%s %s", r->mode_id, params);
    if (n < 0 || (size_t)n >= sizeof(su->data_json)) {
        /* Parameters too long for the message: the templates go without them. */
        snprintf(su->data_json, sizeof(su->data_json), "%s {}", r->mode_id);
    }
    r->queues.screen_count++;
}

/* ------------------------------------------------------------------ */

void node_runner_set_mode(node_runner_t *r, const char *mode_id)
{
    if (!r) return;
    snprintf(r->mode_id, sizeof(r->mode_id), "%s", mode_id ? mode_id : "");
}

/* A mode that nearly fills the script memory may run out mid-game: on a
 * Reduced box (Heltec V3, 64 KB) some combinations come close, e.g. the
 * Hacking Terminal with the Codes modifier (decision M4-8). */
#define MEM_WARN_PCT 85

static void warn_if_memory_tight(node_runner_t *r)
{
    r->memory_tight = false;
    if (!r->node || r->mem_limit == 0) return;
    size_t used = atalaia_node_mem_used(r->node);
    if (used * 100u >= r->mem_limit * MEM_WARN_PCT) {
        r->memory_tight = true;
#ifdef ESP_PLATFORM
        ESP_LOGW(TAG,
                 "the mode uses %u KB of this box's %u KB script memory after loading: it may run "
                 "out during the game (a Reduced box: Heltec V3); prefer a lighter combination",
                 (unsigned)(used / 1024u), (unsigned)(r->mem_limit / 1024u));
#endif
    }
}

void node_runner_init(node_runner_t *r, hal_t *hal, size_t mem_limit)
{
    memset(r, 0, sizeof(*r));
    r->hal = hal;
    r->mem_limit = mem_limit;
    r->node_id = 1;
    r->game_seed = 42;
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
    node_runner_set_mode(r, preset->mode_id);
    /* A mode's `lang` parameter left empty follows the game's language (box_text.h). */
    static char filled[PRESET_PARAMS_MAX + 8];
    const char *params = box_text_fill_lang(preset->params_json, filled, sizeof(filled));
    announce_mode(r, params);

    /* Create the node. */
    atalaia_node_config_t cfg = {0};
    cfg.node_id = r->node_id;
    cfg.game_seed = r->game_seed;
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
    if (params[0]) {
        atalaia_node_set_params(r->node, params);
    }

    /* Load mode source. */
    if (!atalaia_node_load(r->node, preset->source, preset->source_len, "mode/node.lua")) {
        atalaia_node_destroy(r->node);
        r->node = NULL;
        return false;
    }
    warn_if_memory_tight(r);

    /* Initialise the game timer. */
    game_timer_init(&r->timer, preset->duration_s * 1000u);

    /* Start the game. */
    atalaia_node_input(r->node, "game.start", NULL);
    r->running = true;

    return true;
}

bool node_runner_resume(node_runner_t *r, const state_persist_data_t *saved, const char *source,
                        size_t source_len, const char *params_json, const char *const *teams,
                        uint8_t team_count, bool restore_mode_state)
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
    if (restore_mode_state && saved->game_seed != 0) r->game_seed = saved->game_seed;
    static char filled[PRESET_PARAMS_MAX + 8];
    params_json = box_text_fill_lang(params_json, filled, sizeof(filled));
    announce_mode(r, params_json);

    /* Create the node. */
    atalaia_node_config_t cfg = {0};
    cfg.node_id = r->node_id;
    cfg.game_seed = r->game_seed;
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

    /* The mode's state (HB-7) goes in before the script runs: its
     * state.node { defaults } then fills only what is missing. */
    if (restore_mode_state) {
        /* A state the core rejects is not set: the mode starts from its defaults. */
        if (saved->node_state[0]) atalaia_node_state_restore(r->node, saved->node_state);
        atalaia_score_t score;
        atalaia_score_init(&score);
        for (uint8_t t = 1; t <= team_count && t <= 8; t++) {
            score.gained[t] = saved->gained[t - 1];
            score.lost[t] = saved->lost[t - 1];
        }
        atalaia_node_score_restore(r->node, &score);
    }

    /* Load mode source. */
    if (!atalaia_node_load(r->node, source, source_len, "mode/node.lua")) {
        atalaia_node_destroy(r->node);
        r->node = NULL;
        return false;
    }
    warn_if_memory_tight(r);

    /* Restore the game timer from saved state. */
    game_timer_init(&r->timer, saved->timer_duration_ms);
    /* Fast-forward the timer's elapsed counter without firing game.end. */
    r->timer.elapsed_ms = saved->timer_elapsed_ms;

    /* Start the game. */
    atalaia_node_input(r->node, "game.start", NULL);

    /* Advance game time to where we left off. */
    r->game_time_ms = saved->game_time_ms;
    if (restore_mode_state) {
        /* The state already holds what happened: do not replay the time. */
        atalaia_node_resume_at(r->node, saved->game_time_ms);
    } else {
        atalaia_node_advance(r->node, saved->game_time_ms);
    }

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
        state_persist_save(r->node, &r->timer, r->preset_index, r->team_count, r->game_seed);
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
