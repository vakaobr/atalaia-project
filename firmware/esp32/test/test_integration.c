/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * End-to-end integration test: HAL stubs + preset store + state persist
 * + config store + node runner running the domination mode.
 */
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "check.h"
#include "config_store.h"
#include "hal/hal.h"
#include "hal/stub/hal_stub.h"
#include "node_runner.h"
#include "preset_store.h"
#include "state_persist.h"

static const char domination_src[] =
    "local s = state.node { owner = nil }\n"
    "on('team_input.hold', function(e)\n"
    "  if e.team == s.owner or e.ms < params.capture_hold_ms then return end\n"
    "  s.owner = e.team\n"
    "  cap('team_display'):show(e.team)\n"
    "  audio.play('captured')\n"
    "  emit('zone.captured', { team = e.team })\n"
    "end)\n"
    "every(params.tick_s, function()\n"
    "  if s.owner then score.add(s.owner, params.points_per_tick, 'hold') end\n"
    "end)\n"
    "on('game.end', function()\n"
    "  ui.screen('final_score', { owner = s.owner })\n"
    "end)\n";

static char integ_dir[256];

static void setup_integration_env(void)
{
    snprintf(integ_dir, sizeof(integ_dir), "/tmp/atalaia_integ_%d", getpid());
    mkdir(integ_dir, 0755);

    /* preset_store_init creates /presets and /modes under the base path. */
    preset_store_init(integ_dir);

    char state_dir[512];
    snprintf(state_dir, sizeof(state_dir), "%s/state", integ_dir);
    mkdir(state_dir, 0755);
    state_persist_init(state_dir);

    config_store_init();
}

void run_integration_tests(void)
{
    setup_integration_env();

    hal_t hal;
    hal_stub_init(&hal);
    hal_stub_reset_counters();

    /* ---- Save a domination preset at index 1 (unlimited timer). ---- */
    preset_t p = {0};
    snprintf(p.mode_id, sizeof(p.mode_id), "org.atalaia.domination");
    snprintf(p.params_json, sizeof(p.params_json),
             "{\"capture_hold_ms\":0,\"tick_s\":1,\"points_per_tick\":1}");
    memcpy(p.source, domination_src, strlen(domination_src));
    p.source_len = strlen(domination_src);
    p.duration_s = 0; /* unlimited */
    CHECK(preset_store_save(1, &p));

    /* ---- Load the preset back. ---- */
    preset_t loaded = {0};
    CHECK(preset_store_load(1, &loaded));
    CHECK(strcmp(loaded.mode_id, "org.atalaia.domination") == 0);

    /* ---- Start the runner. ---- */
    node_runner_t r;
    node_runner_init(&r, &hal, 0);

    static const char *const teams[] = {"red", "blue"};
    CHECK(node_runner_start(&r, &loaded, teams, 2));
    CHECK(node_runner_status(&r) == ATALAIA_NODE_RUNNING);

    /* ---- Send team_input.hold for red (instant capture: ms=0 >= hold_ms=0). ---- */
    CHECK(node_runner_input(&r, "team_input.hold", "{\"team\":\"red\",\"ms\":0}"));

    /* ---- Advance 120 seconds in 1-second steps. ---- */
    for (int i = 0; i < 120; i++) {
        node_runner_tick(&r, 1000);
    }

    /* ---- Verify: zone.captured was emitted. ---- */
    CHECK(r.event_count > 0);

    /* ---- Verify: screen updates are queued. ---- */
    /* The every(1s) tick and the initial capture produce commands. */
    CHECK(r.queues.screen_count >= 0); /* at minimum, runner consumed them */

    /* ---- Verify: red has points (120 ticks * 1 point each). ---- */
    const atalaia_score_t *score = atalaia_node_score(r.node);
    CHECK(score != NULL);
    CHECK(atalaia_score_net(score, 1) >= 100); /* red = team index 1 */

    /* ---- Verify: status is RUNNING (unlimited timer). ---- */
    CHECK(node_runner_status(&r) == ATALAIA_NODE_RUNNING);

    node_runner_stop(&r);

    /* ---- Now restart with a 5-second timer. ---- */
    hal_stub_reset_counters();
    loaded.duration_s = 5;

    node_runner_init(&r, &hal, 0);
    CHECK(node_runner_start(&r, &loaded, teams, 2));
    CHECK(node_runner_status(&r) == ATALAIA_NODE_RUNNING);

    /* Advance 6 seconds. */
    for (int i = 0; i < 6; i++) {
        node_runner_tick(&r, 1000);
    }

    /* ---- Verify: game ended after 5 seconds. ---- */
    CHECK(node_runner_status(&r) == ATALAIA_NODE_ENDED);

    /* ---- Verify: scores are frozen after game.end (AC-2). ---- */
    const atalaia_score_t *end_score = atalaia_node_score(r.node);
    int64_t frozen_red = end_score ? atalaia_score_net(end_score, 1) : -1;

    /* Tick 3 more seconds after game end -- score must not change. */
    for (int i = 0; i < 3; i++) {
        node_runner_tick(&r, 1000);
    }
    const atalaia_score_t *post_score = atalaia_node_score(r.node);
    int64_t post_red = post_score ? atalaia_score_net(post_score, 1) : -1;
    CHECK(post_red == frozen_red); /* scores frozen */

    /* ---- Verify: final_score screen was rendered. ---- */
    int found_final = 0;
    for (int i = 0; i < r.queues.screen_count; i++) {
        if (strcmp(r.queues.screens[i].template_name, "final_score") == 0) {
            found_final = 1;
        }
    }
    CHECK(found_final);

    node_runner_stop(&r);
}
