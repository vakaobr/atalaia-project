/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * Tests for the shell-owned game countdown timer (game_timer.h).
 * Uses a real atalaia_node_t to verify that game.end is delivered.
 */
#include <stdio.h>
#include <string.h>

#include "check.h"
#include "game_timer.h"
#include "atalaia/node.h"

/* ---- recorder wired to the node's log callback ---- */

static int timer_test_logs;
static char timer_test_log[256];

static void timer_on_log(void *user, const char *msg)
{
    (void)user;
    timer_test_logs++;
    snprintf(timer_test_log, sizeof(timer_test_log), "%s", msg);
}

static int timer_test_events;
static char timer_test_last_event[64];

static void timer_on_event(void *user, const atalaia_event_t *ev, const char *data)
{
    (void)user;
    (void)data;
    timer_test_events++;
    snprintf(timer_test_last_event, sizeof(timer_test_last_event), "%s", ev->type);
}

static void timer_on_command(void *user, const char *target, const char *method, const char *args)
{
    (void)user;
    (void)target;
    (void)method;
    (void)args;
}

static atalaia_node_t *make_timer_node(void)
{
    timer_test_logs = 0;
    timer_test_events = 0;
    memset(timer_test_log, 0, sizeof(timer_test_log));
    memset(timer_test_last_event, 0, sizeof(timer_test_last_event));

    atalaia_node_config_t cfg = {0};
    cfg.node_id = 1;
    cfg.game_seed = 1;
    cfg.mem_limit = 0;
    cfg.instr_limit = 200000;
    cfg.callbacks.event = timer_on_event;
    cfg.callbacks.command = timer_on_command;
    cfg.callbacks.log = timer_on_log;
    cfg.callbacks.user = NULL;

    atalaia_node_t *n = atalaia_node_create(&cfg);
    static const char *const teams[] = {"red", "blue"};
    atalaia_node_set_teams(n, teams, 2);
    return n;
}

/* ---- tests ---- */

static void test_timer_fires_at_expiry(void)
{
    atalaia_node_t *n = make_timer_node();
    CHECK(atalaia_node_load(n, "on('game.end', function() log('ended') end)",
                            strlen("on('game.end', function() log('ended') end)"), "=timer_test"));

    game_timer_t t;
    game_timer_init(&t, 10000);

    /* Half-way: should NOT fire. */
    bool fired = game_timer_tick(&t, 5000, n);
    atalaia_node_advance(n, 5000);
    CHECK(!fired);
    CHECK(timer_test_logs == 0);

    /* Reach the boundary: should fire exactly once. */
    fired = game_timer_tick(&t, 5000, n);
    atalaia_node_advance(n, 5000);
    CHECK(fired);
    CHECK(timer_test_logs == 1);
    CHECK(strcmp(timer_test_log, "ended") == 0);

    atalaia_node_destroy(n);
}

static void test_unlimited_timer_never_expires(void)
{
    atalaia_node_t *n = make_timer_node();
    CHECK(atalaia_node_load(n, "on('game.end', function() log('ended') end)",
                            strlen("on('game.end', function() log('ended') end)"), "=timer_test"));

    game_timer_t t;
    game_timer_init(&t, 0); /* unlimited */

    /* Advance a very long time. */
    for (int i = 0; i < 100; i++) {
        bool fired = game_timer_tick(&t, 10000, n);
        atalaia_node_advance(n, 10000);
        CHECK(!fired);
    }
    CHECK(timer_test_logs == 0);
    CHECK(game_timer_remaining_ms(&t) == UINT32_MAX);

    atalaia_node_destroy(n);
}

static void test_remaining_ms(void)
{
    game_timer_t t;
    game_timer_init(&t, 10000);

    CHECK(game_timer_remaining_ms(&t) == 10000);

    game_timer_tick(&t, 3000, NULL);
    CHECK(game_timer_remaining_ms(&t) == 7000);

    game_timer_tick(&t, 5000, NULL);
    CHECK(game_timer_remaining_ms(&t) == 2000);

    game_timer_tick(&t, 2000, NULL);
    CHECK(game_timer_remaining_ms(&t) == 0);

    /* After expiry, remains zero. */
    game_timer_tick(&t, 1000, NULL);
    CHECK(game_timer_remaining_ms(&t) == 0);
}

static void test_timer_fires_only_once(void)
{
    atalaia_node_t *n = make_timer_node();
    CHECK(atalaia_node_load(n, "on('game.end', function() log('ended') end)",
                            strlen("on('game.end', function() log('ended') end)"), "=timer_test"));

    game_timer_t t;
    game_timer_init(&t, 5000);

    /* First tick crosses the boundary. */
    bool fired = game_timer_tick(&t, 6000, n);
    atalaia_node_advance(n, 6000);
    CHECK(fired);
    CHECK(timer_test_logs == 1);

    /* Subsequent ticks should NOT fire again. */
    fired = game_timer_tick(&t, 1000, n);
    atalaia_node_advance(n, 1000);
    CHECK(!fired);

    fired = game_timer_tick(&t, 5000, n);
    atalaia_node_advance(n, 5000);
    CHECK(!fired);

    CHECK(timer_test_logs == 1); /* still only once */

    atalaia_node_destroy(n);
}

void run_game_timer_tests(void)
{
    test_timer_fires_at_expiry();
    test_unlimited_timer_never_expires();
    test_remaining_ms();
    test_timer_fires_only_once();
}
