/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * Tests for builtin_presets and the picker screens, ending with the flow a
 * player follows on the box (and in the Wokwi scenario): PIN, pick Bomb,
 * start, red arms, blue defuses.
 */
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "builtin_presets.h"
#include "button_tracker.h"
#include "check.h"
#include "hal/stub/hal_stub.h"
#include "node_runner.h"
#include "preset_store.h"
#include "preset_ui.h"
#include "screen_renderer.h"
#include "state_persist.h"

#ifndef MODES_DIR
#define MODES_DIR "modes"
#endif

static char bp_dir[256];
static int bp_id;
static char bomb_src[PRESET_SOURCE_MAX];
static char dom_src[PRESET_SOURCE_MAX];
static size_t bomb_len, dom_len;

static size_t read_file(const char *path, char *buf, size_t sz)
{
    FILE *f = fopen(path, "rb");
    if (!f) return 0;
    size_t n = fread(buf, 1, sz - 1, f);
    fclose(f);
    buf[n] = '\0';
    return n;
}

static void setup(void)
{
    snprintf(bp_dir, sizeof(bp_dir), "/tmp/atalaia_bp_%d_%d", getpid(), bp_id++);
    mkdir(bp_dir, 0755);
    preset_store_init(bp_dir);
    char state_dir[300];
    snprintf(state_dir, sizeof(state_dir), "%s/state", bp_dir);
    state_persist_init(state_dir);
    bomb_len = read_file(MODES_DIR "/bomb/node.lua", bomb_src, sizeof(bomb_src));
    dom_len = read_file(MODES_DIR "/domination/node.lua", dom_src, sizeof(dom_src));
}

static int seed(void)
{
    builtin_source_t sources[] = {
        {"org.atalaia.bomb", bomb_src, bomb_len},
        {"org.atalaia.domination", dom_src, dom_len},
    };
    return builtin_presets_seed(sources, 2);
}

static void test_seed_empty_store(void)
{
    setup();
    CHECK(bomb_len > 0 && dom_len > 0);
    CHECK(seed() == 2);

    preset_summary_t list[PRESET_MAX_SLOTS];
    CHECK(preset_store_list(list, PRESET_MAX_SLOTS) == 2);
    CHECK(strcmp(list[0].label, "Bomb") == 0);
    CHECK(strcmp(list[1].label, "Domination") == 0);

    static preset_t p;
    CHECK(preset_store_load(1, &p));
    CHECK(strcmp(p.mode_id, "org.atalaia.bomb") == 0);
    CHECK(strcmp(p.label, "Bomb") == 0);
    CHECK(strstr(p.params_json, "\"fuse_s\":300") != NULL);
    CHECK(p.source_len == bomb_len);

    /* Seeding again changes nothing: the store is no longer empty. */
    CHECK(seed() == 0);
    CHECK(preset_store_list(list, PRESET_MAX_SLOTS) == 2);
}

static void test_seed_skips_missing_source(void)
{
    setup();
    builtin_source_t only_bomb[] = {{"org.atalaia.bomb", bomb_src, bomb_len}};
    CHECK(builtin_presets_seed(only_bomb, 1) == 1);
    static preset_t p;
    CHECK(preset_store_load(1, &p));
    CHECK(strcmp(p.mode_id, "org.atalaia.bomb") == 0);
    CHECK(!preset_store_load(2, &p));
}

/* A box updated to a firmware with more built-in modes gets them, in free slots, and the
 * stored script of a built-in mode follows the image. */
static void test_seed_adds_missing_modes_and_refreshes_scripts(void)
{
    setup();
    builtin_source_t only_dom[] = {{"org.atalaia.domination", dom_src, dom_len}};
    CHECK(builtin_presets_seed(only_dom, 1) == 1);
    static preset_t p;
    CHECK(preset_store_load(1, &p));
    snprintf(p.label, sizeof(p.label), "My domination");
    CHECK(preset_store_save(3, &p)); /* a preset of the user's in slot 3 */

    static const char newer[] = "-- a newer Domination\n";
    builtin_source_t sources[] = {
        {"org.atalaia.bomb", bomb_src, bomb_len},
        {"org.atalaia.domination", newer, sizeof(newer) - 1},
        {"org.atalaia.codes", "local x = 1\n", 12},
    };
    CHECK(builtin_presets_seed(sources, 3) == 2); /* Bomb and Codes; Domination is there */
    preset_summary_t list[PRESET_MAX_SLOTS];
    CHECK(preset_store_list(list, PRESET_MAX_SLOTS) == 4);
    CHECK(list[1].index == 2 && strcmp(list[1].mode_id, "org.atalaia.bomb") == 0);
    CHECK(list[3].index == 4 && strcmp(list[3].mode_id, "org.atalaia.codes") == 0);
    CHECK(preset_store_load(3, &p) && strcmp(p.label, "My domination") == 0);
    CHECK(p.source_len == sizeof(newer) - 1 && strcmp(p.source, newer) == 0);

    char buf[16];
    CHECK(preset_store_read_source("org.atalaia.codes", buf, sizeof(buf)) == 12);
    CHECK(preset_store_read_source("org.atalaia.codes", buf, 12) == -1); /* does not fit */
    CHECK(preset_store_read_source("org.atalaia.nope", buf, sizeof(buf)) == -1);
    CHECK(builtin_presets_seed(sources, 3) == 0);
}

static void test_picker_screens(void)
{
    preset_ui_t ui;
    preset_ui_init(&ui, "1234", 2);
    const char *labels[] = {"Bomb", "Domi\"nation"};
    screen_update_t su;

    CHECK(preset_ui_screen(&ui, labels, 2, &su));
    CHECK(strcmp(su.template_name, "pin_entry") == 0);
    CHECK(strcmp(su.data_json, "{\"digits\":0,\"error\":false}") == 0);

    preset_ui_handle_key(&ui, '1');
    preset_ui_handle_key(&ui, '2');
    preset_ui_screen(&ui, labels, 2, &su);
    CHECK(strcmp(su.data_json, "{\"digits\":2,\"error\":false}") == 0);

    preset_ui_handle_key(&ui, '#'); /* wrong PIN */
    preset_ui_screen(&ui, labels, 2, &su);
    CHECK(strcmp(su.data_json, "{\"digits\":0,\"error\":true}") == 0);
    preset_ui_handle_key(&ui, '1'); /* the next key clears the error */
    preset_ui_screen(&ui, labels, 2, &su);
    CHECK(strcmp(su.data_json, "{\"digits\":1,\"error\":false}") == 0);

    for (const char *k = "234#"; *k; k++) preset_ui_handle_key(&ui, *k);
    preset_ui_screen(&ui, labels, 2, &su);
    CHECK(strcmp(su.template_name, "preset_select") == 0);
    /* Labels are escaped for JSON. */
    CHECK(strcmp(su.data_json, "{\"presets\":[\"Bomb\",\"Domi\\\"nation\"],\"selected\":1}") == 0);
    CHECK(screen_render(su.template_name, su.data_json));

    preset_ui_handle_key(&ui, '#');
    preset_ui_screen(&ui, labels, 2, &su);
    CHECK(strcmp(su.template_name, "timer_adjust") == 0);
    CHECK(strcmp(su.data_json, "{\"timer_s\":600}") == 0);

    preset_ui_handle_key(&ui, '#');
    preset_ui_screen(&ui, labels, 2, &su);
    CHECK(strcmp(su.template_name, "start_confirm") == 0);
    CHECK(strcmp(su.data_json, "{\"label\":\"Bomb\",\"timer_s\":600}") == 0);

    preset_ui_handle_key(&ui, '#');
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_GAME_STARTED);
    CHECK(!preset_ui_screen(&ui, labels, 2, &su));
}

static void test_picker_lists_at_most_nine(void)
{
    preset_ui_t ui;
    preset_ui_init(&ui, "1", 12);
    preset_ui_handle_key(&ui, '1');
    preset_ui_handle_key(&ui, '#');
    const char *labels[12];
    for (int i = 0; i < 12; i++) labels[i] = "A rather long preset label for the list";
    screen_update_t su;
    CHECK(preset_ui_screen(&ui, labels, 12, &su));
    CHECK(strlen(su.data_json) < sizeof(su.data_json));
    CHECK(su.data_json[strlen(su.data_json) - 1] == '}');
    CHECK(strstr(su.data_json, "\"selected\":1,\"page\":1,\"pages\":2}") != NULL);
    CHECK(screen_render(su.template_name, su.data_json));

    /* Labels full of characters to escape still leave a whole JSON object. */
    for (int i = 0; i < 12; i++)
        labels[i] = "\"\"\"\"\"\"\"\"\"\"\"\"\"\"\"\"\"\"\"\"\"\"\"\"\"\"\"\"\"\"";
    CHECK(preset_ui_screen(&ui, labels, 12, &su));
    CHECK(su.data_json[strlen(su.data_json) - 1] == '}');
    CHECK(strstr(su.data_json, "\"pages\":2}") != NULL);
}

/* Decision M2-1: '0' shows the next nine; the second page is numbered 1-9 again. */
static void test_picker_second_page(void)
{
    preset_ui_t ui;
    preset_ui_init(&ui, "1", 12);
    const char *labels[12] = {"A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L"};
    for (const char *k = "1#0"; *k; k++) preset_ui_handle_key(&ui, *k);
    screen_update_t su;
    CHECK(preset_ui_screen(&ui, labels, 12, &su));
    CHECK(strcmp(su.template_name, "preset_select") == 0);
    CHECK(strcmp(su.data_json,
                 "{\"presets\":[\"J\",\"K\",\"L\"],\"selected\":1,\"page\":2,\"pages\":2}") == 0);
    CHECK(screen_render(su.template_name, su.data_json));

    preset_ui_handle_key(&ui, '3');
    preset_ui_handle_key(&ui, '#');
    preset_ui_handle_key(&ui, '#');
    CHECK(preset_ui_screen(&ui, labels, 12, &su));
    CHECK(strcmp(su.template_name, "start_confirm") == 0);
    CHECK(strstr(su.data_json, "\"label\":\"L\"") != NULL);

    /* Back on the list after the timer: still the second page. */
    preset_ui_handle_key(&ui, '*');
    preset_ui_handle_key(&ui, '*');
    CHECK(preset_ui_screen(&ui, labels, 12, &su));
    CHECK(strstr(su.data_json, "\"selected\":3,\"page\":2") != NULL);
}

/* The last screen the mode queued, or NULL. */
static const screen_update_t *last_screen(const node_runner_t *r)
{
    return r->queues.screen_count ? &r->queues.screens[r->queues.screen_count - 1] : NULL;
}

static void hold(node_runner_t *r, button_tracker_t *t, uint8_t mask, uint32_t ms)
{
    for (uint32_t t_ms = 0; t_ms < ms; t_ms += 10) {
        button_tracker_update(t, mask, 10, r);
        node_runner_tick(r, 10);
    }
    button_tracker_update(t, 0, 10, r);
    node_runner_tick(r, 10);
}

static void test_bomb_from_the_picker(void)
{
    setup();
    CHECK(seed() == 2);
    preset_summary_t list[PRESET_MAX_SLOTS];
    int count = preset_store_list(list, PRESET_MAX_SLOTS);

    preset_ui_t ui;
    preset_ui_init(&ui, "1234", count);
    for (const char *k = "1234#1###"; *k; k++) preset_ui_handle_key(&ui, *k);
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_GAME_STARTED);

    static preset_t p;
    CHECK(preset_store_load(list[preset_ui_selected_preset(&ui) - 1].index, &p));
    CHECK(strcmp(p.mode_id, "org.atalaia.bomb") == 0);
    p.duration_s = preset_ui_timer_duration(&ui);

    hal_t hal;
    hal_stub_init(&hal);
    static node_runner_t runner;
    node_runner_init(&runner, &hal, 0);
    const char *teams[] = {"red", "blue"};
    CHECK(node_runner_start(&runner, &p, teams, 2));
    button_tracker_t buttons;
    button_tracker_init(&buttons, teams, 2);

    const screen_update_t *su = last_screen(&runner);
    CHECK(su && strcmp(su->template_name, "standby") == 0);
    CHECK(su && strcmp(su->data_json, "{\"arm\":\"red\"}") == 0);

    /* Red (button 1) holds 5 s: armed, 300 s on the clock. */
    runner.queues.screen_count = 0;
    hold(&runner, &buttons, 0x1, 5100);
    su = last_screen(&runner);
    CHECK(su && strcmp(su->template_name, "countdown") == 0);
    CHECK(su && strcmp(su->data_json, "{\"left\":300}") == 0);
    if (su) CHECK(screen_render(su->template_name, su->data_json));

    /* Blue (button 2) holds 10 s: defused. */
    runner.queues.screen_count = 0;
    hold(&runner, &buttons, 0x2, 10100);
    su = last_screen(&runner);
    CHECK(su && strcmp(su->template_name, "defused") == 0);
    CHECK(su && strcmp(su->data_json, "{\"team\":\"blue\"}") == 0);
    if (su) CHECK(screen_render(su->template_name, su->data_json));

    node_runner_stop(&runner);
}

/* Every built-in mode, as main/CMakeLists.txt puts them in the image: Master and Satellites,
 * the newest, takes the tenth slot, the picker's second page, and on its own (no controller) a
 * box of it only captures. */
static void test_every_builtin_and_master_satellites(void)
{
    setup();
    static const char *const folders[][2] = {
        {"bomb", "org.atalaia.bomb"},       {"domination", "org.atalaia.domination"},
        {"holdall", "org.atalaia.holdall"}, {"laststand", "org.atalaia.laststand"},
        {"codes", "org.atalaia.codes"},     {"kill_confirmed", "org.atalaia.kill_confirmed"},
        {"respawn", "org.atalaia.respawn"}, {"player_checkin", "org.atalaia.player_checkin"},
        {"medic", "org.atalaia.medic"},     {"master_satellites", "org.atalaia.master_satellites"},
    };
    enum { N = sizeof(folders) / sizeof(folders[0]) };
    static char src[N][PRESET_SOURCE_MAX];
    builtin_source_t sources[N];
    for (int i = 0; i < N; i++) {
        char path[200];
        snprintf(path, sizeof(path), MODES_DIR "/%s/node.lua", folders[i][0]);
        sources[i].mode_id = folders[i][1];
        sources[i].source = src[i];
        sources[i].source_len = read_file(path, src[i], sizeof(src[i]));
        CHECK(sources[i].source_len > 0);
    }
    CHECK(builtin_presets_seed(sources, N) == N);
    preset_summary_t list[PRESET_MAX_SLOTS];
    CHECK(preset_store_list(list, PRESET_MAX_SLOTS) == N);
    CHECK(list[N - 1].index == N);
    CHECK(strcmp(list[N - 1].mode_id, "org.atalaia.master_satellites") == 0);
    CHECK(strcmp(list[N - 1].label, "Master and Satellites") == 0);

    /* Picked on the box itself: PIN, '0' for the second page, its first entry (M2-1). */
    preset_ui_t ui;
    preset_ui_init(&ui, "1234", N);
    for (const char *k = "1234#0###"; *k; k++) preset_ui_handle_key(&ui, *k);
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_GAME_STARTED);
    CHECK(preset_ui_selected_preset(&ui) == N);

    static preset_t p;
    CHECK(preset_store_load(list[preset_ui_selected_preset(&ui) - 1].index, &p));
    CHECK(strcmp(p.mode_id, "org.atalaia.master_satellites") == 0);
    CHECK(strstr(p.params_json, "\"points_per_tick\":2") != NULL);
    CHECK(strstr(p.params_json, "\"satellite_bonus_pct\":50") != NULL);

    hal_t hal;
    hal_stub_init(&hal);
    static node_runner_t runner;
    node_runner_init(&runner, &hal, 0);
    const char *teams[] = {"red", "blue"};
    CHECK(node_runner_start(&runner, &p, teams, 2));
    button_tracker_t buttons;
    button_tracker_init(&buttons, teams, 2);
    const screen_update_t *su = last_screen(&runner);
    CHECK(su && strcmp(su->template_name, "standby") == 0);

    runner.queues.screen_count = 0;
    hold(&runner, &buttons, 0x2, 3100); /* blue holds 3 s: captured, no score on the box */
    su = last_screen(&runner);
    CHECK(su && strcmp(su->template_name, "captured") == 0);
    CHECK(su && strstr(su->data_json, "\"team\":\"blue\"") != NULL);
    node_runner_stop(&runner);
}

void run_builtin_presets_tests(void)
{
    test_seed_empty_store();
    test_seed_skips_missing_source();
    test_seed_adds_missing_modes_and_refreshes_scripts();
    test_picker_screens();
    test_picker_lists_at_most_nine();
    test_picker_second_page();
    test_bomb_from_the_picker();
    test_every_builtin_and_master_satellites();
}
