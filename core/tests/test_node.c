/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Tests for the node runtime: event bus, timers, script API and sandbox.
 */
#include <stdio.h>
#include <string.h>

#include "atalaia/codec.h"
#include "atalaia/node.h"
#include "check.h"

#define MAX_RECORDS 64
#define RECORD_TEXT 160

typedef struct {
    int events;
    char type[MAX_RECORDS][ATALAIA_EVENT_TYPE_MAX];
    char data[MAX_RECORDS][RECORD_TEXT];
    uint8_t team[MAX_RECORDS];
    uint32_t t_ms[MAX_RECORDS];
    atalaia_prio_t prio[MAX_RECORDS];
    uint16_t seq[MAX_RECORDS];

    int commands;
    char command[MAX_RECORDS][RECORD_TEXT]; /* "target.method args" */

    int logs;
    char log[MAX_RECORDS][RECORD_TEXT];
} recorder_t;

static void on_event(void *user, const atalaia_event_t *ev, const char *data)
{
    recorder_t *r = user;
    if (r->events < MAX_RECORDS) {
        int i = r->events;
        snprintf(r->type[i], sizeof(r->type[i]), "%s", ev->type);
        snprintf(r->data[i], sizeof(r->data[i]), "%s", data);
        r->team[i] = ev->team;
        r->t_ms[i] = ev->t_ms;
        r->prio[i] = ev->prio;
        r->seq[i] = ev->seq;
    }
    r->events++;
}

static void on_command(void *user, const char *target, const char *method, const char *args)
{
    recorder_t *r = user;
    if (r->commands < MAX_RECORDS) {
        snprintf(r->command[r->commands], RECORD_TEXT, "%s.%s %s", target, method, args);
    }
    r->commands++;
}

static void on_log(void *user, const char *message)
{
    recorder_t *r = user;
    if (r->logs < MAX_RECORDS) {
        snprintf(r->log[r->logs], RECORD_TEXT, "%s", message);
    }
    r->logs++;
}

/* Index of the first recorded event of this type, or -1. */
static int find_event(const recorder_t *r, const char *type)
{
    for (int i = 0; i < r->events && i < MAX_RECORDS; i++) {
        if (strcmp(r->type[i], type) == 0) {
            return i;
        }
    }
    return -1;
}

static int count_events(const recorder_t *r, const char *type)
{
    int count = 0;
    for (int i = 0; i < r->events && i < MAX_RECORDS; i++) {
        count += strcmp(r->type[i], type) == 0;
    }
    return count;
}

static atalaia_node_t *make_node(recorder_t *r, uint32_t seed, size_t mem_limit)
{
    memset(r, 0, sizeof(*r));
    atalaia_node_config_t cfg = {0};
    cfg.node_id = 3;
    cfg.game_seed = seed;
    cfg.mem_limit = mem_limit;
    cfg.instr_limit = 200000;
    cfg.callbacks.event = on_event;
    cfg.callbacks.command = on_command;
    cfg.callbacks.log = on_log;
    cfg.callbacks.user = r;
    atalaia_node_t *n = atalaia_node_create(&cfg);
    static const char *const teams[] = {"red", "blue"};
    CHECK(n != NULL);
    CHECK(atalaia_node_set_teams(n, teams, 2));
    return n;
}

static bool load(atalaia_node_t *n, const char *src)
{
    return atalaia_node_load(n, src, strlen(src), "=test");
}

static void test_emit_and_handlers(void)
{
    recorder_t r;
    atalaia_node_t *n = make_node(&r, 1, 0);
    CHECK(load(n, "on('team_input.press', function(e)\n"
                  "  emit('zone.captured', { team = e.team, zone = 'A', z = 1 },\n"
                  "       { prio = 'critical' })\n"
                  "end)\n"
                  "on('zone.captured', function(e) log('saw', e.type, e.zone, e.t) end)\n"));
    CHECK(atalaia_node_status(n) == ATALAIA_NODE_RUNNING);

    atalaia_node_advance(n, 1500);
    CHECK(atalaia_node_input(n, "team_input.press", "{\"team\":\"blue\"}"));
    CHECK(r.events == 1);
    CHECK(strcmp(r.type[0], "zone.captured") == 0);
    CHECK(strcmp(r.data[0], "{\"team\":\"blue\",\"z\":1,\"zone\":\"A\"}") == 0);
    CHECK(r.team[0] == 2);
    CHECK(r.t_ms[0] == 1500);
    CHECK(r.prio[0] == ATALAIA_PRIO_CRITICAL);
    /* The node's own handlers see the event it emitted. */
    CHECK(r.logs == 1 && strcmp(r.log[0], "saw zone.captured A 1500") == 0);

    /* Bad input is refused without hurting the node. */
    CHECK(!atalaia_node_input(n, "team_input.press", "{\"team\":"));
    CHECK(!atalaia_node_input(n, "team_input.press", "[1,2]"));
    CHECK(atalaia_node_status(n) == ATALAIA_NODE_RUNNING);
    atalaia_node_destroy(n);
}

/* emit() defaults to the schema's priority, and what a node emits survives
 * the wire codec unchanged. */
static void test_default_priority(void)
{
    recorder_t r;
    atalaia_node_t *n = make_node(&r, 1, 0);
    CHECK(load(n, "on('team_input.press', function(e)\n"
                  "  emit('bomb.exploded', { team = e.team })\n"
                  "  emit('battery.low', { percent = 5 })\n"
                  "  emit('x.club.thing', { list = { 1, 2.5, 'x' }, nested = { ok = true } })\n"
                  "  emit('bomb.exploded', {}, { prio = 'normal' })\n"
                  "end)\n"));
    CHECK(atalaia_node_input(n, "team_input.press", "{\"team\":\"red\"}"));
    CHECK(r.events == 4);
    CHECK(r.prio[0] == ATALAIA_PRIO_CRITICAL);
    CHECK(r.prio[1] == ATALAIA_PRIO_TELEMETRY);
    CHECK(r.prio[2] == ATALAIA_PRIO_NORMAL);
    CHECK(r.prio[3] == ATALAIA_PRIO_NORMAL);

    for (int i = 0; i < r.events && i < MAX_RECORDS; i++) {
        atalaia_event_t ev, back;
        atalaia_event_init(&ev, 3, r.seq[i], r.t_ms[i], r.type[i], r.team[i], 0, r.prio[i]);
        uint8_t payload[ATALAIA_RF_PAYLOAD_MAX];
        char json[RECORD_TEXT];
        size_t len = atalaia_event_encode(&ev, r.data[i], payload, sizeof(payload), NULL);
        CHECK(len > 0);
        CHECK(atalaia_event_decode(payload, len, &back, json, sizeof(json), NULL));
        CHECK(atalaia_event_compare(&ev, &back) == 0 && back.prio == ev.prio &&
              strcmp(back.type, ev.type) == 0 && back.team == ev.team);
        CHECK(strcmp(json, r.data[i]) == 0);
    }
    atalaia_node_destroy(n);
}

static void test_timers(void)
{
    recorder_t r;
    atalaia_node_t *n = make_node(&r, 1, 0);
    CHECK(load(n,
               "ticks = 0\n"
               "local id = every(1, function() ticks = ticks + 1; log('tick', game.time()) end)\n"
               "after(2.5, function() log('after', game.time()) end)\n"
               "after(3.5, function() cancel(id) end)\n"));
    atalaia_node_advance(n, 10000);
    CHECK(r.logs == 4);
    CHECK(strcmp(r.log[0], "tick 1.0") == 0);
    CHECK(strcmp(r.log[1], "tick 2.0") == 0);
    CHECK(strcmp(r.log[2], "after 2.5") == 0);
    CHECK(strcmp(r.log[3], "tick 3.0") == 0);
    CHECK(atalaia_node_time(n) == 10000);
    atalaia_node_destroy(n);

    n = make_node(&r, 1, 0);
    CHECK(!load(n, "for i = 1, 40 do every(1, function() end) end"));
    CHECK(strstr(atalaia_node_last_error(n), "too many timers") != NULL);
    atalaia_node_destroy(n);
}

static void test_scores_and_end(void)
{
    recorder_t r;
    atalaia_node_t *n = make_node(&r, 1, 0);
    CHECK(load(
        n, "every(1, function() score.add('red', 2, 'hold') end)\n"
           "on('penalty', function() score.add('blue', -5, 'moved', 'blue-2') end)\n"
           "on('game.end', function(e) log('final', score.get('red'), score.get('blue')) end)\n"));
    atalaia_node_advance(n, 3000);
    CHECK(atalaia_node_input(n, "penalty", NULL));
    const atalaia_score_t *s = atalaia_node_score(n);
    CHECK(atalaia_score_net(s, 1) == 6);
    CHECK(atalaia_score_net(s, 2) == -5);
    /* Gains travel as counters; only the penalty is an event. */
    CHECK(r.events == 1 && strcmp(r.type[0], "score.delta") == 0);
    CHECK(strcmp(r.data[0],
                 "{\"amount\":-5,\"reason\":\"moved\",\"squad\":\"blue-2\",\"team\":\"blue\"}") ==
          0);

    CHECK(atalaia_node_input(n, "game.end", "{\"reason\":\"time\"}"));
    CHECK(atalaia_node_status(n) == ATALAIA_NODE_ENDED);
    CHECK(r.logs == 1 && strcmp(r.log[0], "final 6 -5") == 0);
    /* Frozen: no more timers, inputs or score changes. */
    atalaia_node_advance(n, 60000);
    CHECK(atalaia_score_net(s, 1) == 6);
    CHECK(!atalaia_node_input(n, "penalty", NULL));
    atalaia_node_destroy(n);

    /* A penalty with a reason and no squad, and one with neither: the
     * three-argument form once put the data table inside itself, so the
     * event could not be encoded (found by Kill Confirmed). */
    n = make_node(&r, 1, 0);
    CHECK(load(n, "on('foul', function() score.add('red', -1, 'killed') end)\n"
                  "on('foul2', function() score.add('red', -2) end)\n"));
    CHECK(atalaia_node_input(n, "foul", NULL));
    CHECK(atalaia_node_input(n, "foul2", NULL));
    CHECK(atalaia_score_net(atalaia_node_score(n), 1) == -3);
    CHECK(r.events == 2 && strcmp(r.type[0], "score.delta") == 0);
    CHECK(strcmp(r.data[0], "{\"amount\":-1,\"reason\":\"killed\",\"team\":\"red\"}") == 0);
    CHECK(strcmp(r.data[1], "{\"amount\":-2,\"reason\":\"\",\"team\":\"red\"}") == 0);
    CHECK(find_event(&r, "script.error") < 0);
    atalaia_node_destroy(n);

    /* A script can end the game itself. */
    n = make_node(&r, 1, 0);
    CHECK(load(n, "after(5, function() game.win('blue') end)"));
    atalaia_node_advance(n, 9000);
    CHECK(atalaia_node_status(n) == ATALAIA_NODE_ENDED);
    CHECK(atalaia_node_time(n) == 5000);
    int i = find_event(&r, "game.end");
    CHECK(i >= 0 && strcmp(r.data[i], "{\"reason\":\"win\",\"winner\":\"blue\"}") == 0);
    CHECK(i >= 0 && r.prio[i] == ATALAIA_PRIO_CRITICAL && r.team[i] == 0);
    atalaia_node_destroy(n);
}

static void test_pause(void)
{
    recorder_t r;
    atalaia_node_t *n = make_node(&r, 1, 0);
    CHECK(load(n, "on('btn', function() log('pressed') end)"));
    CHECK(atalaia_node_input(n, "game.pause", NULL));
    CHECK(atalaia_node_paused(n));
    CHECK(!atalaia_node_input(n, "btn", NULL));
    CHECK(atalaia_node_input(n, "game.resume", NULL));
    CHECK(atalaia_node_input(n, "btn", NULL));
    CHECK(r.logs == 1);
    atalaia_node_destroy(n);
}

static void test_params_state_and_teams(void)
{
    recorder_t r;
    atalaia_node_t *n = make_node(&r, 1, 0);
    CHECK(atalaia_node_set_params(
        n, "{\"fuse_s\": 300, \"reset\": true, \"label\": \"Caf\\u00e9 \\ud83d\\udca3\", "
           "\"list\": [1, 2.5, null], \"skip\": null}"));
    CHECK(load(n, "local s = state.node { phase = 'standby', fuse = 0 }\n"
                  "s.phase = 'armed'\n"
                  "local again = state.node { phase = 'x', extra = 1 }\n"
                  "log(params.fuse_s, math.type(params.fuse_s), params.reset, params.label,\n"
                  "    params.list[2], params.skip, again.phase, again.extra, s == again)\n"));
    CHECK(r.logs == 1);
    CHECK(strcmp(r.log[0], "300 integer true Caf\xc3\xa9 \xf0\x9f\x92\xa3 2.5 nil armed 1 true") ==
          0);
    CHECK(atalaia_node_team_id(n, "blue") == 2);
    CHECK(atalaia_node_team_id(n, "green") == ATALAIA_TEAM_NONE);
    CHECK(strcmp(atalaia_node_team_name(n, 1), "red") == 0);
    /* Teams and params are fixed once the script is loaded. */
    CHECK(!atalaia_node_set_params(n, "{}"));
    CHECK(!atalaia_node_set_teams(n, NULL, 0));
    atalaia_node_destroy(n);

    /* An unknown team is a script error, reported and survived. */
    n = make_node(&r, 1, 0);
    CHECK(load(n, "on('x', function() score.add('green', 1) end)"));
    CHECK(atalaia_node_input(n, "x", NULL));
    int i = find_event(&r, "script.error");
    CHECK(i >= 0 && strstr(r.data[i], "unknown team 'green'") != NULL);
    CHECK(atalaia_node_status(n) == ATALAIA_NODE_RUNNING);
    atalaia_node_destroy(n);
}

static void test_hardware_commands(void)
{
    recorder_t r;
    atalaia_node_t *n = make_node(&r, 1, 0);
    CHECK(load(n, "cap('ring'):fill('red')\n"
                  "cap('ring'):progress(0.5)\n"
                  "ui.screen('countdown', { left = 30 })\n"
                  "audio.play('armed')\n"
                  "audio.stop()\n"));
    CHECK(r.commands == 5);
    CHECK(strcmp(r.command[0], "ring.fill [\"red\"]") == 0);
    CHECK(strcmp(r.command[1], "ring.progress [0.5]") == 0);
    CHECK(strcmp(r.command[2], "ui.screen [\"countdown\",{\"left\":30}]") == 0);
    CHECK(strcmp(r.command[3], "audio.play [\"armed\"]") == 0);
    CHECK(strcmp(r.command[4], "audio.stop []") == 0);
    atalaia_node_destroy(n);
}

static void test_rand_replays(void)
{
    const char *src = "log(rand(1, 1000000), rand(6), rand() < 1)";
    recorder_t a, b, c;
    atalaia_node_t *na = make_node(&a, 99, 0);
    atalaia_node_t *nb = make_node(&b, 99, 0);
    atalaia_node_t *nc = make_node(&c, 100, 0);
    CHECK(load(na, src) && load(nb, src) && load(nc, src));
    CHECK(strcmp(a.log[0], b.log[0]) == 0);
    CHECK(strcmp(a.log[0], c.log[0]) != 0);
    atalaia_node_destroy(na);
    atalaia_node_destroy(nb);
    atalaia_node_destroy(nc);
}

static void test_sandbox(void)
{
    recorder_t r;
    atalaia_node_t *n = make_node(&r, 1, 0);
    CHECK(load(n, "log(io, os, require, load, loadfile, dofile, collectgarbage, debug,\n"
                  "    package, string.dump, math.random)\n"));
    CHECK(r.logs == 1 && strcmp(r.log[0], "nil nil nil nil nil nil nil nil nil nil nil") == 0);
    atalaia_node_destroy(n);

    /* Bytecode is refused. */
    n = make_node(&r, 1, 0);
    CHECK(!atalaia_node_load(n, "\x1bLua", 4, "=bytecode"));
    CHECK(atalaia_node_status(n) == ATALAIA_NODE_HALTED);
    atalaia_node_destroy(n);
}

static void test_watchdog(void)
{
    recorder_t r;
    atalaia_node_t *n = make_node(&r, 1, 0);
    CHECK(!load(n, "while true do end"));
    CHECK(atalaia_node_status(n) == ATALAIA_NODE_HALTED);
    CHECK(strcmp(atalaia_node_last_error(n), "instruction limit exceeded") == 0);
    CHECK(find_event(&r, "script.halted") >= 0);
    CHECK(r.commands == 1 &&
          strcmp(r.command[0],
                 "ui.screen [\"paused\",{\"reason\":\"instruction limit exceeded\"}]") == 0);
    atalaia_node_destroy(n);

    /* Catching the watchdog error with pcall does not keep a script alive. */
    n = make_node(&r, 1, 0);
    CHECK(load(n, "on('go', function()\n"
                  "  while true do pcall(function() while true do end end) end\n"
                  "end)\n"
                  "every(1, function() log('still here') end)\n"));
    CHECK(atalaia_node_input(n, "go", NULL));
    CHECK(atalaia_node_status(n) == ATALAIA_NODE_HALTED);
    atalaia_node_advance(n, 5000);
    CHECK(r.logs == 0);
    CHECK(!atalaia_node_input(n, "go", NULL));
    atalaia_node_destroy(n);

    /* A long but finite handler is fine: the budget is per callback. */
    n = make_node(&r, 1, 0);
    CHECK(load(n, "every(1, function() local x = 0 for i = 1, 20000 do x = x + i end end)"));
    atalaia_node_advance(n, 30000);
    CHECK(atalaia_node_status(n) == ATALAIA_NODE_RUNNING);
    atalaia_node_destroy(n);
}

static void test_memory_limit(void)
{
    recorder_t r;
    atalaia_node_t *n = make_node(&r, 1, 64u * 1024u);
    CHECK(load(n, "on('grow', function() local t = {} for i = 1, 1e7 do t[i] = i end end)\n"
                  "on('small', function() log('ok') end)\n"));
    CHECK(atalaia_node_mem_used(n) < 64u * 1024u);
    CHECK(atalaia_node_input(n, "small", NULL));
    CHECK(atalaia_node_input(n, "grow", NULL));
    CHECK(atalaia_node_status(n) == ATALAIA_NODE_HALTED);
    CHECK(strcmp(atalaia_node_last_error(n), "memory limit exceeded") == 0);
    CHECK(atalaia_node_mem_used(n) <= 64u * 1024u);
    atalaia_node_destroy(n);
}

static void test_event_storm(void)
{
    recorder_t r;
    atalaia_node_t *n = make_node(&r, 1, 0);
    CHECK(load(n, "on('ping', function() emit('ping') end)"));
    atalaia_node_input(n, "ping", NULL);
    CHECK(atalaia_node_status(n) == ATALAIA_NODE_HALTED);
    CHECK(strstr(atalaia_node_last_error(n), "too many events") != NULL);
    CHECK(count_events(&r, "ping") <= 257);
    atalaia_node_destroy(n);
}

static void test_load_errors(void)
{
    recorder_t r;
    atalaia_node_t *n = make_node(&r, 1, 0);
    /* The Lua keyword problem the design spec once had. */
    CHECK(!load(n, "local s = state.local { x = 1 }"));
    CHECK(atalaia_node_status(n) == ATALAIA_NODE_HALTED);
    CHECK(strstr(atalaia_node_last_error(n), "test:1:") != NULL);
    atalaia_node_destroy(n);

    n = make_node(&r, 1, 0);
    CHECK(!load(n, "error('boom')"));
    CHECK(find_event(&r, "script.error") >= 0);
    CHECK(find_event(&r, "script.halted") >= 0);
    atalaia_node_destroy(n);

    /* state.field{} on a regular node is now read-only (not an error to call,
     * but writing to it errors). Verify the read-only table works. */
    n = make_node(&r, 1, 0);
    CHECK(load(n, "local f = state.field { x = 1 }\n"
                  "log(f.x)\n"));
    CHECK(r.logs > 0);
    CHECK(strcmp(r.log[r.logs - 1], "1") == 0);
    atalaia_node_destroy(n);
}

static void test_sequence_numbers(void)
{
    recorder_t r;
    atalaia_node_t *n = make_node(&r, 1, 0);
    CHECK(load(n, "for i = 1, 3 do emit('x.test.e', { i = i }) end"));
    CHECK(r.events == 3);
    CHECK(r.seq[0] == 1 && r.seq[1] == 2 && r.seq[2] == 3);
    atalaia_node_destroy(n);
}

void run_node_tests(void)
{
    test_emit_and_handlers();
    test_default_priority();
    test_timers();
    test_scores_and_end();
    test_pause();
    test_params_state_and_teams();
    test_hardware_commands();
    test_rand_replays();
    test_sandbox();
    test_watchdog();
    test_memory_limit();
    test_event_storm();
    test_load_errors();
    test_sequence_numbers();
}
