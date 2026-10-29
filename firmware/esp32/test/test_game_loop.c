/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * Integration tests with real mode scripts read from disk.
 * MODES_DIR must be defined via -DMODES_DIR=".../modes" at build time.
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

static char gl_temp_dir[256];
static int gl_temp_id;

static void setup_gl_env(void)
{
    snprintf(gl_temp_dir, sizeof(gl_temp_dir), "/tmp/atalaia_gl_%d_%d", getpid(), gl_temp_id++);
    mkdir(gl_temp_dir, 0755);
    preset_store_init(gl_temp_dir);

    char state_dir[512];
    snprintf(state_dir, sizeof(state_dir), "%s/state", gl_temp_dir);
    mkdir(state_dir, 0755);
    state_persist_init(state_dir);
}

static bool read_file(const char *path, char *buf, size_t buf_sz, size_t *len_out)
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

/* ---- test_domination_game ---- */

static void test_domination_game(void)
{
    setup_gl_env();
    hal_t hal;
    hal_stub_init(&hal);
    hal_stub_reset_counters();
    screen_renderer_reset();

    /* 1. Read modes/domination/node.lua from disk. */
    char source[PRESET_SOURCE_MAX];
    size_t source_len = 0;
    CHECK(read_file(MODES_DIR "/domination/node.lua", source, sizeof(source), &source_len));
    CHECK(source_len > 0);

    /* 2. Create a preset with the domination source. */
    preset_t p = {0};
    snprintf(p.mode_id, sizeof(p.mode_id), "org.atalaia.domination");
    snprintf(p.params_json, sizeof(p.params_json),
             "{\"capture_hold_ms\":0,\"tick_s\":1,\"points_per_tick\":1}");
    memcpy(p.source, source, source_len);
    p.source_len = source_len;
    p.duration_s = 5;

    /* 3. Start via node_runner_start. */
    node_runner_t r;
    node_runner_init(&r, &hal, 0);

    static const char *const teams[] = {"red", "blue"};
    CHECK(node_runner_start(&r, &p, teams, 2));
    CHECK(node_runner_status(&r) == ATALAIA_NODE_RUNNING);

    /* 4. Send team_input.hold for red (ms=0 for instant capture). */
    CHECK(node_runner_input(&r, "team_input.hold", "{\"team\":\"red\",\"ms\":0}"));

    /* zone.captured should have been emitted. */
    CHECK(r.event_count > 0);
    CHECK(strcmp(r.last_event_type, "zone.captured") == 0);

    /* 5. Tick 3 seconds. */
    for (int i = 0; i < 3; i++) {
        node_runner_tick(&r, 1000);
    }

    /* Red should have >= 2 points from the every(1s) timer. */
    const atalaia_score_t *score = atalaia_node_score(r.node);
    CHECK(score != NULL);
    CHECK(atalaia_score_net(score, 1) >= 2); /* team index 1 = red */

    /* 6. Send team_input.hold for blue -> verify takeover. */
    int events_before = r.event_count;
    CHECK(node_runner_input(&r, "team_input.hold", "{\"team\":\"blue\",\"ms\":0}"));
    CHECK(r.event_count > events_before);
    CHECK(strcmp(r.last_event_type, "zone.captured") == 0);

    /* 7. Tick 2 more seconds -> timer expires, game ends. */
    for (int i = 0; i < 2; i++) {
        node_runner_tick(&r, 1000);
    }

    /* 8. Verify ATALAIA_NODE_ENDED. */
    CHECK(node_runner_status(&r) == ATALAIA_NODE_ENDED);

    /* Verify final_score screen queued. */
    int found_final = 0;
    for (int i = 0; i < r.queues.screen_count; i++) {
        if (strcmp(r.queues.screens[i].template_name, "final_score") == 0) {
            found_final = 1;
        }
    }
    CHECK(found_final);

    /* Verify scores are frozen. */
    const atalaia_score_t *end_score = atalaia_node_score(r.node);
    int64_t frozen_red = end_score ? atalaia_score_net(end_score, 1) : -1;
    int64_t frozen_blue = end_score ? atalaia_score_net(end_score, 2) : -1;

    /* Tick a few more seconds -- scores must not change. */
    for (int i = 0; i < 3; i++) {
        node_runner_tick(&r, 1000);
    }
    const atalaia_score_t *post_score = atalaia_node_score(r.node);
    CHECK(post_score != NULL);
    CHECK(atalaia_score_net(post_score, 1) == frozen_red);
    CHECK(atalaia_score_net(post_score, 2) == frozen_blue);

    node_runner_stop(&r);
}

/* ---- test_bomb_arm_explode ---- */

static void test_bomb_arm_explode(void)
{
    setup_gl_env();
    hal_t hal;
    hal_stub_init(&hal);
    hal_stub_reset_counters();
    screen_renderer_reset();

    /* 1. Read modes/bomb/node.lua from disk. */
    char source[PRESET_SOURCE_MAX];
    size_t source_len = 0;
    CHECK(read_file(MODES_DIR "/bomb/node.lua", source, sizeof(source), &source_len));
    CHECK(source_len > 0);

    /* 2. Create preset with bomb params, duration 0 (unlimited). */
    preset_t p = {0};
    snprintf(p.mode_id, sizeof(p.mode_id), "org.atalaia.bomb");
    snprintf(p.params_json, sizeof(p.params_json),
             "{\"fuse_s\":3,\"attackers\":\"red\",\"defenders\":\"blue\","
             "\"arm_hold_ms\":0,\"defuse_hold_ms\":0}");
    memcpy(p.source, source, source_len);
    p.source_len = source_len;
    p.duration_s = 0; /* unlimited */

    /* 3. Start game. */
    node_runner_t r;
    node_runner_init(&r, &hal, 0);

    static const char *const teams[] = {"red", "blue"};
    CHECK(node_runner_start(&r, &p, teams, 2));
    CHECK(node_runner_status(&r) == ATALAIA_NODE_RUNNING);

    /* Send team_input.hold for red (arm). */
    CHECK(node_runner_input(&r, "team_input.hold", "{\"team\":\"red\",\"ms\":0}"));

    /* bomb.armed should have been emitted. */
    CHECK(r.event_count > 0);
    CHECK(strcmp(r.last_event_type, "bomb.armed") == 0);
    int events_after_arm = r.event_count;

    /* 4. Tick 4 seconds -> bomb should explode (fuse_s=3). */
    for (int i = 0; i < 4; i++) {
        node_runner_tick(&r, 1000);
    }

    /* 5. Verify bomb.exploded event. */
    CHECK(r.event_count > events_after_arm);
    /* The explosion ends the game (GE-10): bomb.exploded, then game.end. */
    CHECK(r.event_count >= events_after_arm + 2);
    CHECK(strcmp(r.last_event_type, "game.end") == 0);

    /* Verify exploded screen was queued. */
    int found_exploded = 0;
    for (int i = 0; i < r.queues.screen_count; i++) {
        if (strcmp(r.queues.screens[i].template_name, "exploded") == 0) {
            found_exploded = 1;
        }
    }
    CHECK(found_exploded);

    node_runner_stop(&r);
}

/* ---- test_bomb_arm_defuse ---- */

static void test_bomb_arm_defuse(void)
{
    setup_gl_env();
    hal_t hal;
    hal_stub_init(&hal);
    hal_stub_reset_counters();
    screen_renderer_reset();

    /* 1. Read modes/bomb/node.lua from disk. */
    char source[PRESET_SOURCE_MAX];
    size_t source_len = 0;
    CHECK(read_file(MODES_DIR "/bomb/node.lua", source, sizeof(source), &source_len));
    CHECK(source_len > 0);

    /* 2. Same setup as bomb_arm_explode. */
    preset_t p = {0};
    snprintf(p.mode_id, sizeof(p.mode_id), "org.atalaia.bomb");
    snprintf(p.params_json, sizeof(p.params_json),
             "{\"fuse_s\":3,\"attackers\":\"red\",\"defenders\":\"blue\","
             "\"arm_hold_ms\":0,\"defuse_hold_ms\":0}");
    memcpy(p.source, source, source_len);
    p.source_len = source_len;
    p.duration_s = 0;

    node_runner_t r;
    node_runner_init(&r, &hal, 0);

    static const char *const teams[] = {"red", "blue"};
    CHECK(node_runner_start(&r, &p, teams, 2));

    /* 3. Arm with red hold. */
    CHECK(node_runner_input(&r, "team_input.hold", "{\"team\":\"red\",\"ms\":0}"));
    CHECK(strcmp(r.last_event_type, "bomb.armed") == 0);
    int events_after_arm = r.event_count;

    /* Tick 1 second (fuse is 3s, so bomb is still ticking). */
    node_runner_tick(&r, 1000);

    /* 4. Send team_input.hold for blue (defuse). */
    CHECK(node_runner_input(&r, "team_input.hold", "{\"team\":\"blue\",\"ms\":0}"));

    /* Verify bomb.defused event. */
    CHECK(r.event_count > events_after_arm);
    CHECK(strcmp(r.last_event_type, "bomb.defused") == 0);

    /* Verify defused screen was queued. */
    int found_defused = 0;
    for (int i = 0; i < r.queues.screen_count; i++) {
        if (strcmp(r.queues.screens[i].template_name, "defused") == 0) {
            found_defused = 1;
        }
    }
    CHECK(found_defused);

    /* Tick 3 more seconds to confirm bomb does NOT explode. */
    for (int i = 0; i < 3; i++) {
        node_runner_tick(&r, 1000);
    }
    /* Last event should still be bomb.defused, not bomb.exploded. */
    CHECK(strcmp(r.last_event_type, "bomb.defused") == 0);

    node_runner_stop(&r);
}

/* ---- entry point ---- */

void run_game_loop_tests(void)
{
    test_domination_game();
    test_bomb_arm_explode();
    test_bomb_arm_defuse();
}
