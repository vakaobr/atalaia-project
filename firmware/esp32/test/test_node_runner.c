/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * Tests for node_runner: the game loop driver that owns the node,
 * timer, command dispatcher and persistence.
 */
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "box_text.h"
#include "check.h"
#include "node_runner.h"
#include "hal/hal.h"
#include "hal/stub/hal_stub.h"
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

static char nr_temp_dir[256];

static void setup_runner_env(void)
{
    snprintf(nr_temp_dir, sizeof(nr_temp_dir), "/tmp/atalaia_runner_%d", getpid());
    mkdir(nr_temp_dir, 0755);

    char preset_dir[512];
    snprintf(preset_dir, sizeof(preset_dir), "%s/presets", nr_temp_dir);
    mkdir(preset_dir, 0755);
    preset_store_init(preset_dir);

    char state_dir[512];
    snprintf(state_dir, sizeof(state_dir), "%s/state", nr_temp_dir);
    mkdir(state_dir, 0755);
    state_persist_init(state_dir);
}

static preset_t make_domination_preset(uint32_t duration_s)
{
    preset_t p = {0};
    snprintf(p.mode_id, sizeof(p.mode_id), "org.atalaia.domination");
    snprintf(p.params_json, sizeof(p.params_json),
             "{\"capture_hold_ms\":0,\"tick_s\":1,\"points_per_tick\":1}");
    memcpy(p.source, domination_src, strlen(domination_src));
    p.source_len = strlen(domination_src);
    p.duration_s = duration_s;
    return p;
}

/* ---- tests ---- */

static void test_load_and_start(void)
{
    setup_runner_env();
    hal_t hal;
    hal_stub_init(&hal);
    hal_stub_reset_counters();

    node_runner_t r;
    node_runner_init(&r, &hal, 0);

    preset_t p = make_domination_preset(0); /* unlimited */
    static const char *const teams[] = {"red", "blue"};
    CHECK(node_runner_start(&r, &p, teams, 2));
    CHECK(node_runner_status(&r) == ATALAIA_NODE_RUNNING);

    node_runner_stop(&r);
}

static void test_event_processing(void)
{
    setup_runner_env();
    hal_t hal;
    hal_stub_init(&hal);
    hal_stub_reset_counters();

    node_runner_t r;
    node_runner_init(&r, &hal, 0);

    preset_t p = make_domination_preset(0);
    static const char *const teams[] = {"red", "blue"};
    CHECK(node_runner_start(&r, &p, teams, 2));

    /* Send a hold event with ms >= capture_hold_ms (0). */
    CHECK(node_runner_input(&r, "team_input.hold", "{\"team\":\"red\",\"ms\":100}"));
    node_runner_tick(&r, 100);

    /* zone.captured should have been emitted. */
    CHECK(r.event_count > 0);
    CHECK(strcmp(r.last_event_type, "zone.captured") == 0);

    node_runner_stop(&r);
}

static void test_timer_expiry(void)
{
    setup_runner_env();
    hal_t hal;
    hal_stub_init(&hal);
    hal_stub_reset_counters();

    node_runner_t r;
    node_runner_init(&r, &hal, 0);

    preset_t p = make_domination_preset(10); /* 10 seconds */
    static const char *const teams[] = {"red", "blue"};
    CHECK(node_runner_start(&r, &p, teams, 2));

    /* Advance 11 seconds in 1-second steps. */
    for (int i = 0; i < 11; i++) {
        node_runner_tick(&r, 1000);
    }

    CHECK(node_runner_status(&r) == ATALAIA_NODE_ENDED);

    node_runner_stop(&r);
}

static void test_screen_updates(void)
{
    setup_runner_env();
    hal_t hal;
    hal_stub_init(&hal);
    hal_stub_reset_counters();

    node_runner_t r;
    node_runner_init(&r, &hal, 0);

    preset_t p = make_domination_preset(5); /* 5 seconds */
    static const char *const teams[] = {"red", "blue"};
    CHECK(node_runner_start(&r, &p, teams, 2));

    /* Capture a zone so the mode has an owner for game.end screen. */
    node_runner_input(&r, "team_input.hold", "{\"team\":\"blue\",\"ms\":0}");

    /* Advance past the timer so game.end fires and ui.screen is called. */
    for (int i = 0; i < 6; i++) {
        node_runner_tick(&r, 1000);
    }

    /* The domination mode calls ui.screen('final_score', ...) on game.end.
     * Check that the screen queue has at least one entry. */
    CHECK(r.queues.screen_count > 0);
    /* Find the final_score screen update. */
    int found = 0;
    for (int i = 0; i < r.queues.screen_count; i++) {
        if (strcmp(r.queues.screens[i].template_name, "final_score") == 0) {
            found = 1;
        }
    }
    CHECK(found);

    node_runner_stop(&r);
}

/* Decision M4-8: a mode that nearly fills a Reduced box's 64 KB is flagged
 * (and logged on the device) right after it loads. Memory grows in 1 KB
 * strings, so loading never needs a large temporary copy. */
static bool start_with_strings(node_runner_t *r, hal_t *hal, unsigned count)
{
    static const char src[] =
        "big = {}\nfor i = 1, params.k do big[i] = string.rep('x', 1000) .. i end\n";
    preset_t p = {0};
    snprintf(p.mode_id, sizeof(p.mode_id), "org.atalaia.test_memory");
    snprintf(p.params_json, sizeof(p.params_json), "{\"k\":%u}", count);
    memcpy(p.source, src, sizeof(src) - 1);
    p.source_len = sizeof(src) - 1;
    static const char *const teams[] = {"red", "blue"};
    node_runner_init(r, hal, 64u * 1024u);
    return node_runner_start(r, &p, teams, 2);
}

static void test_memory_warning_on_a_reduced_box(void)
{
    setup_runner_env();
    hal_t hal;
    hal_stub_init(&hal);
    node_runner_t r;

    CHECK(start_with_strings(&r, &hal, 0));
    size_t base = atalaia_node_mem_used(r.node);
    CHECK(!r.memory_tight);
    node_runner_stop(&r);
    CHECK(start_with_strings(&r, &hal, 10));
    size_t per = (atalaia_node_mem_used(r.node) - base) / 10;
    CHECK(!r.memory_tight);
    node_runner_stop(&r);

    /* Step up from the estimate until the flag goes up: it must do so while the
     * mode still loads, and exactly when the use crosses 85%. */
    size_t warn_at = 64u * 1024u * 85u / 100u;
    CHECK(per > 0 && base < warn_at);
    bool flagged = false;
    for (unsigned k = (unsigned)((warn_at - base) / per); k < 64 && !flagged; k++) {
        if (!start_with_strings(&r, &hal, k)) break; /* past the limit: no flag seen in time */
        size_t used = atalaia_node_mem_used(r.node);
        CHECK(r.memory_tight == (used >= warn_at));
        flagged = r.memory_tight;
        node_runner_stop(&r);
    }
    CHECK(flagged);
}

/* A mode's `lang` parameter left empty follows the game's language: the script sees it in
 * params.lang and the templates in the "@mode" message (box_text_fill_lang); one that has a
 * value keeps it. */
static void test_lang_param_follows_the_game(void)
{
    setup_runner_env();
    static const char src[] =
        "on('game.start', function() ui.screen('lang_seen', { lang = params.lang }) end)\n";
    static const char *const teams[] = {"red", "blue"};
    static const struct {
        const char *params;
        const char *game_lang;
        const char *seen;
    } cases[] = {
        {"{\"lang\":\"\"}", "de", "de"},
        {"{\"k\":1,\"lang\":\"\"}", "pt", "pt"},
        {"{\"lang\":\"\"}", "", "en"},     /* no game language: the box's English */
        {"{\"lang\":\"en\"}", "pt", "en"}, /* the GM's own choice stays */
    };
    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        box_lang_set_code(cases[i].game_lang);
        hal_t hal;
        hal_stub_init(&hal);
        node_runner_t r;
        node_runner_init(&r, &hal, 0);
        preset_t p = {0};
        snprintf(p.mode_id, sizeof(p.mode_id), "org.atalaia.test_lang");
        snprintf(p.params_json, sizeof(p.params_json), "%s", cases[i].params);
        memcpy(p.source, src, sizeof(src) - 1);
        p.source_len = sizeof(src) - 1;
        CHECK(node_runner_start(&r, &p, teams, 2));
        char want[32];
        snprintf(want, sizeof(want), "\"lang\":\"%s\"", cases[i].seen);
        /* The templates' message ... */
        CHECK(r.queues.screen_count > 0);
        CHECK(strcmp(r.queues.screens[0].template_name, "@mode") == 0);
        CHECK(strstr(r.queues.screens[0].data_json, want) != NULL);
        /* ... and the script's params. */
        bool seen = false;
        for (int j = 0; j < r.queues.screen_count; j++) {
            if (strcmp(r.queues.screens[j].template_name, "lang_seen") == 0) {
                seen = strstr(r.queues.screens[j].data_json, want) != NULL;
            }
        }
        CHECK(seen);
        node_runner_stop(&r);
    }
    box_lang_set_code("");
}

void run_node_runner_tests(void)
{
    test_lang_param_follows_the_game();
    test_memory_warning_on_a_reduced_box();
    test_load_and_start();
    test_event_processing();
    test_timer_expiry();
    test_screen_updates();
}
