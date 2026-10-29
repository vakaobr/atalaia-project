/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * Tests for reboot resume: save game state, destroy the runner (simulate
 * power loss), then resume from the persisted data and verify continuity.
 *
 * A game picked on the box gets its mode's state.node, scores and seed back
 * (decision HB-7): an armed bomb stays armed and its fuse goes on from the
 * mode's node.rebooted handler. A field game (restore_mode_state false)
 * starts its mode afresh: its controller sets it up again.
 */
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "check.h"
#include "hal/hal.h"
#include "hal/stub/hal_stub.h"
#include "node_runner.h"
#include "preset_store.h"
#include "screen_renderer.h"
#include "state_persist.h"

#include "atalaia/score.h"

/* MODES_DIR is set by test/CMakeLists.txt (defaults to repo-relative path). */
#ifndef MODES_DIR
#define MODES_DIR "modes"
#endif

/* ---- helpers ---- */

static char rb_temp_dir[256];
static int rb_temp_id;

static void setup_rb_env(void)
{
    snprintf(rb_temp_dir, sizeof(rb_temp_dir), "/tmp/atalaia_rb_%d_%d", getpid(), rb_temp_id++);
    mkdir(rb_temp_dir, 0755);
    preset_store_init(rb_temp_dir);

    char state_dir[512];
    snprintf(state_dir, sizeof(state_dir), "%s/state", rb_temp_dir);
    mkdir(state_dir, 0755);
    state_persist_init(state_dir);
}

static bool read_rb_file(const char *path, char *buf, size_t buf_sz, size_t *len_out)
{
    FILE *f = fopen(path, "rb");
    if (!f) {
        fprintf(stderr, "  cannot open: %s\n", path);
        return false;
    }
    *len_out = fread(buf, 1, buf_sz - 1, f);
    fclose(f);
    buf[*len_out] = '\0';
    return *len_out > 0;
}

/* ---- test_bomb_resume_after_reboot ---- */

static void test_bomb_resume_after_reboot(void)
{
    setup_rb_env();
    hal_t hal;
    hal_stub_init(&hal);
    hal_stub_reset_counters();
    screen_renderer_reset();

    /* 1. Read modes/bomb/node.lua from disk. */
    char source[PRESET_SOURCE_MAX];
    size_t source_len = 0;
    CHECK(read_rb_file(MODES_DIR "/bomb/node.lua", source, sizeof(source), &source_len));
    CHECK(source_len > 0);

    /* 2. Create a preset: fuse_s=5, red attacks, blue defends. */
    preset_t p = {0};
    snprintf(p.mode_id, sizeof(p.mode_id), "org.atalaia.bomb");
    snprintf(p.params_json, sizeof(p.params_json),
             "{\"fuse_s\":5,\"attackers\":\"red\",\"defenders\":\"blue\","
             "\"arm_hold_ms\":0,\"defuse_hold_ms\":0}");
    memcpy(p.source, source, source_len);
    p.source_len = source_len;
    p.duration_s = 0; /* unlimited */

    /* Save the preset so we can load it after "reboot". */
    CHECK(preset_store_save(1, &p));

    /* 3. Start game, arm, tick 2 seconds. */
    node_runner_t r;
    node_runner_init(&r, &hal, 0);
    r.preset_index = 1;

    static const char *const teams[] = {"red", "blue"};
    CHECK(node_runner_start(&r, &p, teams, 2));
    CHECK(node_runner_status(&r) == ATALAIA_NODE_RUNNING);

    /* Arm the bomb. */
    CHECK(node_runner_input(&r, "team_input.hold", "{\"team\":\"red\",\"ms\":0}"));
    CHECK(strcmp(r.last_event_type, "bomb.armed") == 0);

    /* Tick 2 seconds. */
    for (int i = 0; i < 2; i++) {
        node_runner_tick(&r, 1000);
    }

    /* 4. Save state. */
    r.game_seed = 0xC0FFEE;
    CHECK(state_persist_save(r.node, &r.timer, r.preset_index, r.team_count, r.game_seed));

    /* 5. Destroy the runner (simulate power loss). */
    node_runner_stop(&r);
    CHECK(r.node == NULL);

    /* 6. Load persisted state. */
    state_persist_data_t saved;
    CHECK(state_persist_load(&saved));
    CHECK(saved.game_time_ms >= 2000);
    CHECK(saved.game_seed == 0xC0FFEE);
    CHECK(strstr(saved.node_state, "\"phase\":\"armed\"") != NULL);

    /* 7. Resume from saved state. */
    preset_t loaded;
    CHECK(preset_store_load(saved.preset_index, &loaded));

    node_runner_t r2;
    node_runner_init(&r2, &hal, 0);
    CHECK(node_runner_resume(&r2, &saved, loaded.source, loaded.source_len, loaded.params_json,
                             teams, 2, true));
    CHECK(r2.running);
    CHECK(r2.game_time_ms >= 2000);
    CHECK(r2.game_seed == 0xC0FFEE);

    /* 8. Still armed, no new bomb.armed: the screen shows the fuse left. */
    CHECK(strcmp(r2.last_event_type, "bomb.armed") != 0);
    const screen_update_t *last = &r2.queues.screens[r2.queues.screen_count - 1];
    CHECK(r2.queues.screen_count > 0 && strcmp(last->template_name, "countdown") == 0);
    CHECK(strstr(last->data_json, "\"left\":3") != NULL);

    /* 9. Tick 4 seconds -> the bomb explodes on its own fuse (armed at 0, fuse_s=5). */
    r2.queues.screen_count = 0;
    for (int i = 0; i < 4; i++) {
        node_runner_tick(&r2, 1000);
    }

    /* The explosion ends the game (GE-10): bomb.exploded, then game.end. */
    CHECK(strcmp(r2.last_event_type, "game.end") == 0);

    /* Verify exploded screen was queued. */
    int found_exploded = 0;
    for (int i = 0; i < r2.queues.screen_count; i++) {
        if (strcmp(r2.queues.screens[i].template_name, "exploded") == 0) {
            found_exploded = 1;
        }
    }
    CHECK(found_exploded);

    /* Verify game time is cumulative (pre-reboot + post-reboot). */
    CHECK(r2.game_time_ms >= 6000); /* 2s before + 4s after */
    node_runner_stop(&r2);

    /* A field game's resume starts the mode afresh: the bomb is in standby. */
    node_runner_t r3;
    node_runner_init(&r3, &hal, 0);
    CHECK(node_runner_resume(&r3, &saved, loaded.source, loaded.source_len, loaded.params_json,
                             teams, 2, false));
    last = &r3.queues.screens[r3.queues.screen_count - 1];
    CHECK(r3.queues.screen_count > 0 && strcmp(last->template_name, "standby") == 0);
    for (int i = 0; i < 6; i++) {
        node_runner_tick(&r3, 1000);
    }
    CHECK(strcmp(r3.last_event_type, "bomb.exploded") != 0);
    node_runner_stop(&r3);
}

/* ---- test_reboot_emits_node_rebooted ---- */

/*
 * Uses a synthetic script that handles node.rebooted by emitting an
 * event. This verifies that node_runner_resume sends the input and the
 * mode can observe it.
 */
static void test_reboot_emits_node_rebooted(void)
{
    setup_rb_env();
    hal_t hal;
    hal_stub_init(&hal);
    hal_stub_reset_counters();
    screen_renderer_reset();

    /* Synthetic mode: emits "rebooted.ack" when it receives node.rebooted,
     * and scores red once per second so we can verify game time. */
    static const char src[] = "on('node.rebooted', function()\n"
                              "  emit('rebooted.ack', {})\n"
                              "end)\n"
                              "every(1, function() score.add('red', 1, 'tick') end)\n";

    /* Save as a preset. */
    preset_t p = {0};
    snprintf(p.mode_id, sizeof(p.mode_id), "org.atalaia.test_reboot");
    p.params_json[0] = '\0'; /* no params needed */
    memcpy(p.source, src, sizeof(src) - 1);
    p.source_len = sizeof(src) - 1;
    p.duration_s = 30;

    CHECK(preset_store_save(1, &p));

    /* Start a game and advance 3 seconds. */
    node_runner_t r;
    node_runner_init(&r, &hal, 0);
    r.preset_index = 1;

    static const char *const teams[] = {"red", "blue"};
    CHECK(node_runner_start(&r, &p, teams, 2));

    for (int i = 0; i < 3; i++) {
        node_runner_tick(&r, 1000);
    }

    /* Save and destroy. */
    CHECK(state_persist_save(r.node, &r.timer, r.preset_index, r.team_count, r.game_seed));
    node_runner_stop(&r);

    /* Resume. */
    state_persist_data_t saved;
    CHECK(state_persist_load(&saved));

    preset_t loaded;
    CHECK(preset_store_load(saved.preset_index, &loaded));

    node_runner_t r2;
    node_runner_init(&r2, &hal, 0);

    CHECK(node_runner_resume(&r2, &saved, loaded.source, loaded.source_len, loaded.params_json,
                             teams, 2, true));

    /* The scores come back: red had 3 points, and keeps scoring from there. */
    CHECK(atalaia_score_net(atalaia_node_score(r2.node), 1) == 3);

    /* Verify that node.rebooted was received by the mode and it
     * emitted rebooted.ack in response. */
    CHECK(r2.event_count >= 1);
    CHECK(strcmp(r2.last_event_type, "rebooted.ack") == 0);

    /* Verify game time was restored. */
    CHECK(r2.game_time_ms >= 3000);

    /* Verify shell timer was restored (27s should remain of 30s). */
    uint32_t remaining = game_timer_remaining_ms(&r2.timer);
    CHECK(remaining <= 27000);
    CHECK(remaining > 0);

    node_runner_stop(&r2);
}

/* ---- entry point ---- */

void run_reboot_resume_tests(void)
{
    test_bomb_resume_after_reboot();
    test_reboot_emits_node_rebooted();
}
