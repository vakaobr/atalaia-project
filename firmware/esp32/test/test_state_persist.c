/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * Tests for state_persist: save, load and clear game state across
 * simulated reboots.
 */
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "check.h"
#include "state_persist.h"
#include "game_timer.h"
#include "atalaia/node.h"

static char temp_dir[256];

static void setup_state_dir(void)
{
    snprintf(temp_dir, sizeof(temp_dir), "/tmp/atalaia_state_%d", getpid());
    mkdir(temp_dir, 0755);
    state_persist_init(temp_dir);
}

/* ---- node helper (mirrors core/tests/test_node.c pattern) ---- */

static int sp_logs;
static char sp_log[256];

static void sp_on_log(void *user, const char *msg)
{
    (void)user;
    sp_logs++;
    snprintf(sp_log, sizeof(sp_log), "%s", msg);
}

static void sp_on_event(void *user, const atalaia_event_t *ev, const char *data)
{
    (void)user;
    (void)ev;
    (void)data;
}

static void sp_on_command(void *user, const char *target, const char *method, const char *args)
{
    (void)user;
    (void)target;
    (void)method;
    (void)args;
}

static atalaia_node_t *make_sp_node(void)
{
    sp_logs = 0;
    memset(sp_log, 0, sizeof(sp_log));

    atalaia_node_config_t cfg = {0};
    cfg.node_id = 1;
    cfg.game_seed = 42;
    cfg.mem_limit = 0;
    cfg.instr_limit = 200000;
    cfg.callbacks.event = sp_on_event;
    cfg.callbacks.command = sp_on_command;
    cfg.callbacks.log = sp_on_log;
    cfg.callbacks.user = NULL;

    atalaia_node_t *n = atalaia_node_create(&cfg);
    static const char *const teams[] = {"red", "blue"};
    atalaia_node_set_teams(n, teams, 2);
    return n;
}

/* ---- tests ---- */

static void test_save_load_roundtrip(void)
{
    setup_state_dir();

    atalaia_node_t *n = make_sp_node();
    const char *src = "every(1, function() score.add('red', 1, 'tick') end)";
    CHECK(atalaia_node_load(n, src, strlen(src), "=state_test"));
    atalaia_node_advance(n, 5000);

    game_timer_t t;
    game_timer_init(&t, 60000);
    game_timer_tick(&t, 5000, NULL);

    CHECK(state_persist_save(n, &t, 3, 2, 77));

    state_persist_data_t data = {0};
    CHECK(state_persist_load(&data));
    CHECK(data.magic == STATE_PERSIST_MAGIC);
    CHECK(data.version == STATE_PERSIST_VERSION);
    CHECK(data.game_time_ms == 5000);
    CHECK(data.timer_duration_ms == 60000);
    CHECK(data.timer_elapsed_ms == 5000);
    CHECK(data.preset_index == 3);
    CHECK(data.team_count == 2);
    /* Red should have gained points from the every(1s) timer. */
    CHECK(data.gained[0] >= 4); /* at least 4 ticks in 5s */
    CHECK(data.game_seed == 77);
    CHECK(data.node_state[0] == '\0'); /* no state.node in this script */

    atalaia_node_destroy(n);
}

/* The mode's state.node travels as JSON (HB-7); one that cannot is left out. */
static void test_node_state_saved(void)
{
    setup_state_dir();
    atalaia_node_t *n = make_sp_node();
    const char *src = "local s = state.node { phase = 'armed', at = 12 }";
    CHECK(atalaia_node_load(n, src, strlen(src), "=node_state"));
    game_timer_t t;
    game_timer_init(&t, 0);
    CHECK(state_persist_save(n, &t, 1, 2, 0));
    state_persist_data_t data = {0};
    CHECK(state_persist_load(&data));
    CHECK(strcmp(data.node_state, "{\"at\":12,\"phase\":\"armed\"}") == 0);
    atalaia_node_destroy(n);

    n = make_sp_node();
    src = "local s = state.node {}\n s.f = print";
    CHECK(atalaia_node_load(n, src, strlen(src), "=node_state_fn"));
    CHECK(state_persist_save(n, &t, 1, 2, 0));
    CHECK(state_persist_load(&data));
    CHECK(data.node_state[0] == '\0');
    atalaia_node_destroy(n);
}

/* A write cut short leaves the temporary file, never a torn current.bin. */
static void test_torn_write_keeps_last_state(void)
{
    setup_state_dir();
    atalaia_node_t *n = make_sp_node();
    CHECK(atalaia_node_load(n, "-- noop", 7, "=torn"));
    game_timer_t t;
    game_timer_init(&t, 10000);
    t.elapsed_ms = 4000;
    CHECK(state_persist_save(n, &t, 1, 2, 0));

    char path[512];
    snprintf(path, sizeof(path), "%s/current.tmp", temp_dir);
    FILE *f = fopen(path, "wb");
    CHECK(f != NULL);
    fwrite("half", 1, 4, f);
    fclose(f);

    state_persist_data_t data = {0};
    CHECK(state_persist_load(&data));
    CHECK(data.timer_elapsed_ms == 4000);
    state_persist_clear();
    CHECK(access(path, F_OK) != 0); /* clear removes the leftover too */
    atalaia_node_destroy(n);
}

static void test_clear(void)
{
    setup_state_dir();

    atalaia_node_t *n = make_sp_node();
    const char *src = "-- noop";
    CHECK(atalaia_node_load(n, src, strlen(src), "=clear_test"));

    game_timer_t t;
    game_timer_init(&t, 10000);

    CHECK(state_persist_save(n, &t, 1, 2, 0));

    state_persist_data_t data = {0};
    CHECK(state_persist_load(&data));

    state_persist_clear();
    CHECK(!state_persist_load(&data));

    atalaia_node_destroy(n);
}

static void test_invalid_magic(void)
{
    setup_state_dir();

    /* Write garbage to the state file. */
    char path[512];
    snprintf(path, sizeof(path), "%s/current.bin", temp_dir);
    FILE *f = fopen(path, "wb");
    CHECK(f != NULL);
    const char garbage[] = "this is not valid state data!!!!";
    fwrite(garbage, 1, sizeof(garbage), f);
    fclose(f);

    state_persist_data_t data = {0};
    CHECK(!state_persist_load(&data));
}

static void test_resume_after_reboot(void)
{
    setup_state_dir();

    /* First "session": start a game, advance to 5s of a 10s timer. */
    atalaia_node_t *n = make_sp_node();
    const char *src = "every(1, function() score.add('red', 2, 'hold') end)\n"
                      "on('game.end', function() log('ended') end)\n";
    CHECK(atalaia_node_load(n, src, strlen(src), "=resume_test"));
    atalaia_node_advance(n, 5000);

    game_timer_t t;
    game_timer_init(&t, 10000);
    game_timer_tick(&t, 5000, n);

    CHECK(state_persist_save(n, &t, 1, 2, 0));
    atalaia_node_destroy(n);

    /* Simulate reboot: load state. */
    state_persist_data_t data = {0};
    CHECK(state_persist_load(&data));
    CHECK(data.timer_duration_ms == 10000);
    CHECK(data.timer_elapsed_ms == 5000);
    CHECK(data.game_time_ms == 5000);

    /* Recreate timer from persisted state, verify remaining time. */
    game_timer_t t2;
    game_timer_init(&t2, data.timer_duration_ms);
    game_timer_tick(&t2, data.timer_elapsed_ms, NULL);
    CHECK(game_timer_remaining_ms(&t2) == 5000);

    /* Advance the restored timer by another 5s -- should fire. */
    atalaia_node_t *n2 = make_sp_node();
    CHECK(atalaia_node_load(n2, src, strlen(src), "=resume_test"));
    atalaia_node_advance(n2, data.game_time_ms); /* catch up game time */

    bool fired = game_timer_tick(&t2, 5000, n2);
    atalaia_node_advance(n2, 5000);
    CHECK(fired);
    CHECK(sp_logs >= 1);
    CHECK(strcmp(sp_log, "ended") == 0);

    atalaia_node_destroy(n2);
}

void run_state_persist_tests(void)
{
    test_save_load_roundtrip();
    test_clear();
    test_invalid_magic();
    test_resume_after_reboot();
    test_node_state_saved();
    test_torn_write_keeps_last_state();
}
