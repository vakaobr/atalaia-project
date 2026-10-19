/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Tests for the field operations API: state.field{} and field.* functions.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "atalaia/node.h"
#include "check.h"

#define MAX_RECORDS 64
#define RECORD_TEXT 160

typedef struct {
    int events;
    char type[MAX_RECORDS][ATALAIA_EVENT_TYPE_MAX];
    char data[MAX_RECORDS][RECORD_TEXT];

    int commands;
    char command[MAX_RECORDS][RECORD_TEXT];

    int logs;
    char log[MAX_RECORDS][RECORD_TEXT];

    /* field_state callback records */
    int field_states;
    char field_key[MAX_RECORDS][64];
    char field_value[MAX_RECORDS][RECORD_TEXT];

    /* mock field_ops data */
    const char *mock_owner;
    bool mock_send_result;
    int send_count;
    char send_cmd[64];
    char send_params[RECORD_TEXT];
    uint16_t send_node_id;
} field_recorder_t;

static void on_event(void *user, const atalaia_event_t *ev, const char *data)
{
    field_recorder_t *r = user;
    if (r->events < MAX_RECORDS) {
        snprintf(r->type[r->events], sizeof(r->type[0]), "%s", ev->type);
        snprintf(r->data[r->events], sizeof(r->data[0]), "%s", data);
    }
    r->events++;
}

static void on_command(void *user, const char *target, const char *method, const char *args)
{
    field_recorder_t *r = user;
    if (r->commands < MAX_RECORDS) {
        snprintf(r->command[r->commands], RECORD_TEXT, "%s.%s %s", target, method, args);
    }
    r->commands++;
}

static void on_log(void *user, const char *message)
{
    field_recorder_t *r = user;
    if (r->logs < MAX_RECORDS) {
        snprintf(r->log[r->logs], RECORD_TEXT, "%s", message);
    }
    r->logs++;
}

static void on_field_state(void *user, const char *key, const char *value_json)
{
    field_recorder_t *r = user;
    if (r->field_states < MAX_RECORDS) {
        snprintf(r->field_key[r->field_states], 64, "%s", key);
        snprintf(r->field_value[r->field_states], RECORD_TEXT, "%s", value_json);
    }
    r->field_states++;
}

/* ---- Mock field_ops ------------------------------------------------------ */

static char *mock_nodes(void *user, const char *role)
{
    (void)user;
    char *result;
    if (role != NULL && strcmp(role, "bomb") == 0) {
        result = malloc(32);
        if (result) snprintf(result, 32, "[{\"id\":1}]");
    } else {
        result = malloc(48);
        if (result) snprintf(result, 48, "[{\"id\":1},{\"id\":2},{\"id\":3}]");
    }
    return result;
}

static const char *mock_owner(void *user, uint16_t node_id)
{
    field_recorder_t *r = user;
    (void)node_id;
    return r->mock_owner;
}

static bool mock_send(void *user, uint16_t node_id, const char *cmd, const char *params_json)
{
    field_recorder_t *r = user;
    r->send_count++;
    r->send_node_id = node_id;
    snprintf(r->send_cmd, sizeof(r->send_cmd), "%s", cmd);
    if (params_json) {
        snprintf(r->send_params, sizeof(r->send_params), "%s", params_json);
    } else {
        r->send_params[0] = '\0';
    }
    return r->mock_send_result;
}

static const atalaia_field_ops_t mock_field_ops = {
    .nodes = mock_nodes,
    .owner = mock_owner,
    .send = mock_send,
};

/* ---- Helpers ------------------------------------------------------------- */

static atalaia_node_t *make_field_node(field_recorder_t *r, bool controller)
{
    memset(r, 0, sizeof(*r));
    r->mock_owner = "red";
    r->mock_send_result = true;
    atalaia_node_config_t cfg = {0};
    cfg.node_id = 1;
    cfg.game_seed = 42;
    cfg.instr_limit = 200000;
    cfg.callbacks.event = on_event;
    cfg.callbacks.command = on_command;
    cfg.callbacks.log = on_log;
    cfg.callbacks.field_state = on_field_state;
    cfg.callbacks.user = r;
    if (controller) {
        cfg.field_ops = &mock_field_ops;
    }
    atalaia_node_t *n = atalaia_node_create(&cfg);
    static const char *const teams[] = {"red", "blue"};
    CHECK(n != NULL);
    CHECK(atalaia_node_set_teams(n, teams, 2));
    return n;
}

static bool load_src(atalaia_node_t *n, const char *src)
{
    return atalaia_node_load(n, src, strlen(src), "=field_test");
}

/* ---- Tests --------------------------------------------------------------- */

static void test_state_field_rw_controller(void)
{
    field_recorder_t r;
    atalaia_node_t *n = make_field_node(&r, true);
    CHECK(load_src(n, "local f = state.field { phase = 'idle', count = 0 }\n"
                      "f.phase = 'active'\n"
                      "f.count = 42\n"
                      "log(f.phase, f.count)\n"));
    CHECK(r.logs == 1);
    CHECK(strcmp(r.log[0], "active 42") == 0);
    /* field_state callback was called for each write. */
    CHECK(r.field_states == 2);
    CHECK(strcmp(r.field_key[0], "phase") == 0);
    CHECK(strcmp(r.field_value[0], "\"active\"") == 0);
    CHECK(strcmp(r.field_key[1], "count") == 0);
    CHECK(strcmp(r.field_value[1], "42") == 0);
    atalaia_node_destroy(n);
}

static void test_state_field_readonly_regular(void)
{
    field_recorder_t r;
    atalaia_node_t *n = make_field_node(&r, false);
    /* Writing to state.field on a regular node should error. */
    CHECK(load_src(n, "local ok, err = pcall(function()\n"
                      "  local f = state.field { x = 1 }\n"
                      "  f.x = 2\n"
                      "end)\n"
                      "log(ok, err)\n"));
    CHECK(r.logs == 1);
    CHECK(strstr(r.log[0], "false") != NULL);
    CHECK(strstr(r.log[0], "read-only") != NULL);
    atalaia_node_destroy(n);
}

static void test_field_nodes(void)
{
    field_recorder_t r;
    atalaia_node_t *n = make_field_node(&r, true);
    CHECK(load_src(n, "local all = field.nodes()\n"
                      "log(#all)\n"
                      "local bombs = field.nodes('bomb')\n"
                      "log(#bombs, bombs[1].id)\n"));
    CHECK(r.logs == 2);
    CHECK(strcmp(r.log[0], "3") == 0);
    CHECK(strcmp(r.log[1], "1 1") == 0);
    atalaia_node_destroy(n);
}

static void test_field_owner(void)
{
    field_recorder_t r;
    atalaia_node_t *n = make_field_node(&r, true);
    CHECK(load_src(n, "log(field.owner(1))\n"));
    CHECK(r.logs == 1);
    CHECK(strcmp(r.log[0], "red") == 0);

    /* Test nil owner. */
    r.mock_owner = NULL;
    CHECK(atalaia_node_input(n, "game.start", NULL));
    r.logs = 0;
    atalaia_node_advance(n, 100);
    /* Need to trigger from an event handler to call owner after start. */
    atalaia_node_destroy(n);

    n = make_field_node(&r, true);
    r.mock_owner = NULL;
    CHECK(load_src(n, "log(field.owner(5))\n"));
    CHECK(r.logs == 1);
    CHECK(strcmp(r.log[0], "nil") == 0);
    atalaia_node_destroy(n);
}

static void test_field_send(void)
{
    field_recorder_t r;
    atalaia_node_t *n = make_field_node(&r, true);
    CHECK(load_src(n, "local ok = field.send(7, 'reset', { force = true })\n"
                      "log(ok)\n"));
    CHECK(r.logs == 1);
    CHECK(strcmp(r.log[0], "true") == 0);
    CHECK(r.send_count == 1);
    CHECK(r.send_node_id == 7);
    CHECK(strcmp(r.send_cmd, "reset") == 0);
    CHECK(strcmp(r.send_params, "{\"force\":true}") == 0);
    atalaia_node_destroy(n);
}

static void test_field_score(void)
{
    field_recorder_t r;
    atalaia_node_t *n = make_field_node(&r, true);
    CHECK(load_src(n, "score.add('red', 10)\n"
                      "score.add('blue', 5)\n"
                      "local s = field.score()\n"
                      "log(s.red, s.blue)\n"));
    CHECK(r.logs == 1);
    CHECK(strcmp(r.log[0], "10 5") == 0);
    atalaia_node_destroy(n);
}

/* game.teams() on the controller too (P4R26). */
static void test_field_game_teams(void)
{
    field_recorder_t r;
    atalaia_node_t *n = make_field_node(&r, true);
    CHECK(load_src(n, "log(table.concat(game.teams(), ','))\n"));
    CHECK(r.logs == 1);
    CHECK(strcmp(r.log[0], "red,blue") == 0);
    atalaia_node_destroy(n);
}

static void test_field_common_owner(void)
{
    field_recorder_t r;
    atalaia_node_t *n = make_field_node(&r, true);
    CHECK(load_src(n, "log(field.common_owner({1, 2, 3}))\n"));
    CHECK(r.logs == 1);
    /* All nodes return "red" from the mock. */
    CHECK(strcmp(r.log[0], "red") == 0);
    atalaia_node_destroy(n);

    /* Test nil when no owner. */
    n = make_field_node(&r, true);
    r.mock_owner = NULL;
    CHECK(load_src(n, "log(field.common_owner({1}))\n"));
    CHECK(r.logs == 1);
    CHECK(strcmp(r.log[0], "nil") == 0);
    atalaia_node_destroy(n);
}

/* A host that answers owner() in one buffer it rewrites on every call (as
 * the Dart and Python bindings do): node 1 is red, the others blue. */
static char reused_owner_buf[8];

static const char *reused_owner(void *user, uint16_t node_id)
{
    (void)user;
    snprintf(reused_owner_buf, sizeof(reused_owner_buf), "%s", node_id == 1 ? "red" : "blue");
    return reused_owner_buf;
}

static const atalaia_field_ops_t reused_owner_ops = {
    .nodes = mock_nodes,
    .owner = reused_owner,
    .send = mock_send,
};

static void test_field_common_owner_reused_buffer(void)
{
    field_recorder_t r;
    memset(&r, 0, sizeof(r));
    atalaia_node_config_t cfg = {0};
    cfg.node_id = 1;
    cfg.instr_limit = 200000;
    cfg.callbacks.log = on_log;
    cfg.callbacks.user = &r;
    cfg.field_ops = &reused_owner_ops;
    atalaia_node_t *n = atalaia_node_create(&cfg);
    static const char *const teams[] = {"red", "blue"};
    CHECK(n != NULL);
    CHECK(atalaia_node_set_teams(n, teams, 2));
    /* The first answer must be copied before owner() is asked again. */
    CHECK(load_src(n, "log(tostring(field.common_owner({1, 2})))\n"
                      "log(tostring(field.common_owner({2, 3})))\n"
                      "log(tostring(field.common_owner({1, 1})))\n"));
    CHECK(r.logs == 3);
    CHECK(strcmp(r.log[0], "nil") == 0);
    CHECK(strcmp(r.log[1], "blue") == 0);
    CHECK(strcmp(r.log[2], "red") == 0);
    atalaia_node_destroy(n);
}

static void test_field_not_available_regular(void)
{
    field_recorder_t r;
    atalaia_node_t *n = make_field_node(&r, false);
    /* field.* functions should not exist on regular nodes. */
    CHECK(load_src(n, "log(field)\n"));
    CHECK(r.logs == 1);
    CHECK(strcmp(r.log[0], "nil") == 0);
    atalaia_node_destroy(n);
}

void run_field_api_tests(void)
{
    test_state_field_rw_controller();
    test_state_field_readonly_regular();
    test_field_nodes();
    test_field_owner();
    test_field_send();
    test_field_score();
    test_field_game_teams();
    test_field_common_owner();
    test_field_common_owner_reused_buffer();
    test_field_not_available_regular();
}
