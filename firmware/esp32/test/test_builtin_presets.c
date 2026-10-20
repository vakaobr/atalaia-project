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
#include "screen_template.h"
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

/* The game task drains the screen queue every tick; keep only the latest
 * screen here, as the display would show it (a hold draws its progress). */
static void drain_screens(node_runner_t *r)
{
    if (r->queues.screen_count > 1) {
        r->queues.screens[0] = r->queues.screens[r->queues.screen_count - 1];
        r->queues.screen_count = 1;
    }
}

static void hold(node_runner_t *r, button_tracker_t *t, uint8_t mask, uint32_t ms)
{
    for (uint32_t t_ms = 0; t_ms < ms; t_ms += 10) {
        button_tracker_update(t, mask, 10, r);
        node_runner_tick(r, 10);
        drain_screens(r);
    }
    button_tracker_update(t, 0, 10, r);
    node_runner_tick(r, 10);
    drain_screens(r);
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

/* Every built-in mode, as main/CMakeLists.txt puts them in the image (shell.c's order). */
static const char *const builtin_folders[][2] = {
    {"bomb", "org.atalaia.bomb"},
    {"domination", "org.atalaia.domination"},
    {"holdall", "org.atalaia.holdall"},
    {"laststand", "org.atalaia.laststand"},
    {"codes", "org.atalaia.codes"},
    {"kill_confirmed", "org.atalaia.kill_confirmed"},
    {"respawn", "org.atalaia.respawn"},
    {"player_checkin", "org.atalaia.player_checkin"},
    {"medic", "org.atalaia.medic"},
    {"master_satellites", "org.atalaia.master_satellites"},
    {"hacking_terminal", "org.atalaia.hacking_terminal"},
    {"vip_payload", "org.atalaia.vip_payload"},
    {"objectives", "org.atalaia.objectives"},
};
enum { BUILTIN_N = sizeof(builtin_folders) / sizeof(builtin_folders[0]) };

/* Seeds a fresh store with every built-in mode; fills list. */
static void seed_every_builtin(preset_summary_t *list)
{
    setup();
    static char src[BUILTIN_N][PRESET_SOURCE_MAX];
    builtin_source_t sources[BUILTIN_N];
    for (int i = 0; i < BUILTIN_N; i++) {
        char path[200];
        snprintf(path, sizeof(path), MODES_DIR "/%s/node.lua", builtin_folders[i][0]);
        sources[i].mode_id = builtin_folders[i][1];
        sources[i].source = src[i];
        sources[i].source_len = read_file(path, src[i], sizeof(src[i]));
        CHECK(sources[i].source_len > 0);
    }
    CHECK(builtin_presets_seed(sources, BUILTIN_N) == BUILTIN_N);
    CHECK(preset_store_list(list, PRESET_MAX_SLOTS) == BUILTIN_N);
}

/* Master and Satellites takes the tenth slot, the picker's second page, and on its own (no
 * controller) a box of it only captures. */
static void test_every_builtin_and_master_satellites(void)
{
    preset_summary_t list[PRESET_MAX_SLOTS];
    seed_every_builtin(list);
    CHECK(list[9].index == 10);
    CHECK(strcmp(list[9].mode_id, "org.atalaia.master_satellites") == 0);
    CHECK(strcmp(list[9].label, "Master and Satellites") == 0);

    /* Picked on the box itself: PIN, '0' for the second page, its first entry (M2-1). */
    preset_ui_t ui;
    preset_ui_init(&ui, "1234", BUILTIN_N);
    for (const char *k = "1234#0###"; *k; k++) preset_ui_handle_key(&ui, *k);
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_GAME_STARTED);
    CHECK(preset_ui_selected_preset(&ui) == 10);

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

static void keys(node_runner_t *r, const char *k)
{
    for (; *k; k++) {
        char json[16];
        snprintf(json, sizeof(json), "{\"key\":\"%c\"}", *k);
        node_runner_input(r, "keypad.key", json);
        node_runner_tick(r, 10);
    }
}

/* The Hacking Terminal, the eleventh slot: picked on the box (second page, second entry), it
 * runs on the keypad alone. With game seed 2 and node id 1 its code is 8517, as in the
 * simulator (modes/hacking_terminal/tests/code_solved.yaml): the same core, the same rand(). */
static void test_hacking_terminal_from_the_picker(void)
{
    preset_summary_t list[PRESET_MAX_SLOTS];
    seed_every_builtin(list);
    CHECK(strcmp(list[10].mode_id, "org.atalaia.hacking_terminal") == 0);
    CHECK(strcmp(list[10].label, "Hacking Terminal") == 0);

    preset_ui_t ui;
    preset_ui_init(&ui, "1234", BUILTIN_N);
    for (const char *k = "1234#02###"; *k; k++) preset_ui_handle_key(&ui, *k);
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_GAME_STARTED);
    CHECK(preset_ui_selected_preset(&ui) == 11);

    static preset_t p;
    CHECK(preset_store_load(list[preset_ui_selected_preset(&ui) - 1].index, &p));
    CHECK(strcmp(p.mode_id, "org.atalaia.hacking_terminal") == 0);
    CHECK(strstr(p.params_json, "\"puzzle\":\"code\"") != NULL);
    CHECK(strstr(p.params_json, "\"lockout_s\":10") != NULL);

    hal_t hal;
    hal_stub_init(&hal);
    static node_runner_t runner;
    node_runner_init(&runner, &hal, 0);
    runner.game_seed = 2;
    const char *teams[] = {"red", "blue"};
    CHECK(node_runner_start(&runner, &p, teams, 2));
    /* The mode's announcement comes first: the display then finds the mode's templates. */
    CHECK(strcmp(runner.queues.screens[0].template_name, SCREEN_MODE_MESSAGE) == 0);
    CHECK(screen_render(SCREEN_MODE_MESSAGE, runner.queues.screens[0].data_json));
    button_tracker_t buttons;
    button_tracker_init(&buttons, teams, 2);
    const screen_update_t *su = last_screen(&runner);
    CHECK(su && strcmp(su->template_name, "hack_code") == 0);
    if (su) CHECK(screen_render(su->template_name, su->data_json));

    /* Blue presses its button, then guesses wrong: the counts, and the lock. */
    runner.queues.screen_count = 0;
    hold(&runner, &buttons, 0x2, 100);
    keys(&runner, "1234#");
    su = last_screen(&runner);
    CHECK(su && strcmp(su->template_name, "hack_code") == 0);
    CHECK(su && strstr(su->data_json, "\"g1\":\"1234\"") != NULL);
    CHECK(su && strstr(su->data_json, "\"r1\":0") != NULL);
    CHECK(su && strstr(su->data_json, "\"c1\":1") != NULL);
    CHECK(su && strstr(su->data_json, "\"locked\":10") != NULL);
    CHECK(su && strstr(su->data_json, "\"team\":\"blue\"") != NULL);
    if (su) CHECK(screen_render(su->template_name, su->data_json));
    CHECK(strcmp(runner.last_event_type, "hacking.solved") != 0);

    for (int i = 0; i < 1010; i++) node_runner_tick(&runner, 10); /* the 10 s lock */
    runner.queues.screen_count = 0;
    keys(&runner, "8517#");
    CHECK(strcmp(runner.last_event_type, "hacking.solved") == 0);
    su = last_screen(&runner);
    CHECK(su && strcmp(su->template_name, "hack_solved") == 0);
    CHECK(su && strstr(su->data_json, "\"team\":\"blue\"") != NULL);
    if (su) CHECK(screen_render(su->template_name, su->data_json));
    node_runner_stop(&runner);
}

/* VIP / Payload, the twelfth slot (second page, third entry): a box is a checkpoint. On its
 * own it only captures: the controller's field.lua scores it and extracts the VIP. */
static void test_vip_payload_checkpoint_from_the_picker(void)
{
    preset_summary_t list[PRESET_MAX_SLOTS];
    seed_every_builtin(list);
    CHECK(strcmp(list[11].mode_id, "org.atalaia.vip_payload") == 0);
    CHECK(strcmp(list[11].label, "VIP") == 0);

    preset_ui_t ui;
    preset_ui_init(&ui, "1234", BUILTIN_N);
    for (const char *k = "1234#03###"; *k; k++) preset_ui_handle_key(&ui, *k);
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_GAME_STARTED);
    CHECK(preset_ui_selected_preset(&ui) == 12);

    static preset_t p;
    CHECK(preset_store_load(list[preset_ui_selected_preset(&ui) - 1].index, &p));
    CHECK(strcmp(p.mode_id, "org.atalaia.vip_payload") == 0);
    CHECK(strstr(p.params_json, "\"checkpoint_points\":1") != NULL);
    CHECK(strstr(p.params_json, "extraction") == NULL); /* no zone: a box has no GPS */

    hal_t hal;
    hal_stub_init(&hal);
    static node_runner_t runner;
    node_runner_init(&runner, &hal, 0);
    const char *teams[] = {"red", "blue"};
    CHECK(node_runner_start(&runner, &p, teams, 2));
    CHECK(strcmp(runner.queues.screens[0].template_name, SCREEN_MODE_MESSAGE) == 0);
    CHECK(screen_render(SCREEN_MODE_MESSAGE, runner.queues.screens[0].data_json));
    button_tracker_t buttons;
    button_tracker_init(&buttons, teams, 2);
    const screen_update_t *su = last_screen(&runner);
    CHECK(su && strcmp(su->template_name, "checkpoint_free") == 0);
    if (su) CHECK(screen_render(su->template_name, su->data_json));

    runner.queues.screen_count = 0;
    hold(&runner, &buttons, 0x2, 3100); /* blue holds 3 s: captured, no score on the box */
    CHECK(strcmp(runner.last_event_type, "zone.captured") == 0);
    su = last_screen(&runner);
    CHECK(su && strcmp(su->template_name, "checkpoint_held") == 0);
    CHECK(su && strstr(su->data_json, "\"team\":\"blue\"") != NULL);
    if (su) CHECK(screen_render(su->template_name, su->data_json));
    for (int i = 0; i < 2000; i++) node_runner_tick(&runner, 10); /* 20 s held */
    const atalaia_score_t *score = atalaia_node_score(runner.node);
    CHECK(score && score->gained[1] == 0 && score->gained[2] == 0);
    node_runner_stop(&runner);
}

/* Objectives, the thirteenth slot (second page, fourth entry): the role package of custom
 * scenarios (decision P4R7). The box waits for the scenario's "setup" (a mode command, as
 * box_game.c gives it: cmd.mode with the command's params), then plays what it was told: here
 * a red-only capture, then a bomb site, with no score on the box. */
static void test_objectives_from_the_picker(void)
{
    preset_summary_t list[PRESET_MAX_SLOTS];
    seed_every_builtin(list);
    CHECK(strcmp(list[12].mode_id, "org.atalaia.objectives") == 0);
    CHECK(strcmp(list[12].label, "Objectives") == 0);

    preset_ui_t ui;
    preset_ui_init(&ui, "1234", BUILTIN_N);
    for (const char *k = "1234#04###"; *k; k++) preset_ui_handle_key(&ui, *k);
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_GAME_STARTED);
    CHECK(preset_ui_selected_preset(&ui) == 13);

    static preset_t p;
    CHECK(preset_store_load(list[preset_ui_selected_preset(&ui) - 1].index, &p));
    CHECK(strcmp(p.mode_id, "org.atalaia.objectives") == 0);
    CHECK(strcmp(p.params_json, "{}") == 0);

    hal_t hal;
    hal_stub_init(&hal);
    static node_runner_t runner;
    node_runner_init(&runner, &hal, 0);
    const char *teams[] = {"red", "blue"};
    CHECK(node_runner_start(&runner, &p, teams, 2));
    /* The mode's announcement comes first: the display then finds the mode's templates. */
    CHECK(strcmp(runner.queues.screens[0].template_name, SCREEN_MODE_MESSAGE) == 0);
    CHECK(screen_render(SCREEN_MODE_MESSAGE, runner.queues.screens[0].data_json));
    button_tracker_t buttons;
    button_tracker_init(&buttons, teams, 2);
    const screen_update_t *su = last_screen(&runner);
    CHECK(su && strcmp(su->template_name, "obj_status") == 0);
    CHECK(su && strstr(su->data_json, "\"state\":\"wait\"") != NULL);
    if (su) CHECK(screen_render(su->template_name, su->data_json));
    hold(&runner, &buttons, 0x1, 5100); /* nothing to capture yet */
    CHECK(runner.event_count == 0);

    node_runner_input(&runner, "cmd.mode",
                      "{\"name\":\"setup\",\"kind\":\"capture\",\"team\":\"red\",\"hold_ms\":3000,"
                      "\"label\":\"Ponte\"}");
    su = last_screen(&runner);
    CHECK(su && strcmp(su->template_name, "obj_capture") == 0);
    CHECK(su && strstr(su->data_json, "\"only\":\"red\"") != NULL);
    if (su) CHECK(screen_render(su->template_name, su->data_json));
    hold(&runner, &buttons, 0x2, 3100); /* blue: not its objective */
    CHECK(runner.event_count == 0);
    hold(&runner, &buttons, 0x1, 3100);
    CHECK(strcmp(runner.last_event_type, "zone.captured") == 0);
    su = last_screen(&runner);
    CHECK(su && strstr(su->data_json, "\"team\":\"red\"") != NULL);
    if (su) CHECK(screen_render(su->template_name, su->data_json));

    node_runner_input(&runner, "cmd.mode",
                      "{\"name\":\"setup\",\"kind\":\"bomb\",\"team\":\"red\",\"hold_ms\":2000,"
                      "\"fuse_s\":30}");
    hold(&runner, &buttons, 0x1, 2100);
    CHECK(strcmp(runner.last_event_type, "bomb.armed") == 0);
    su = last_screen(&runner);
    CHECK(su && strcmp(su->template_name, "obj_bomb") == 0);
    CHECK(su && strstr(su->data_json, "\"phase\":\"armed\"") != NULL);
    if (su) CHECK(screen_render(su->template_name, su->data_json));
    for (int i = 0; i < 3100; i++) node_runner_tick(&runner, 10); /* the 30 s fuse */
    CHECK(strcmp(runner.last_event_type, "bomb.exploded") == 0);
    const atalaia_score_t *score = atalaia_node_score(runner.node);
    CHECK(score && score->gained[1] == 0 && score->gained[2] == 0);
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
    test_hacking_terminal_from_the_picker();
    test_vip_payload_checkpoint_from_the_picker();
    test_objectives_from_the_picker();
}
