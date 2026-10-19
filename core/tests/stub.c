/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The FFI stub (ADR-P3-11): every function of atalaia/node.h with small,
 * predictable behaviour and no Lua, built as libatalaia_core_stub with
 * -DATALAIA_STUB=ON. The app's Dart tests load it to check the bridge
 * itself (struct layouts, strings, callbacks, the game loop isolate)
 * without depending on what a mode script does; the mode tests load the
 * real core.
 *
 * What it does:
 *   - load: running, unless the source is empty (halted, with an error).
 *   - input: refused unless running, or while paused for anything but
 *     game.*, or when data_json is not an object. Otherwise game.pause,
 *     game.resume and game.end change the state, and the node answers with
 *     an event of the same type and data (team 1 if the data has
 *     "team":"<first team>"), a ui.screen command ["stub",{"inputs":N}] and
 *     the log line "stub: <type>". "stub.field" also calls every field
 *     operation and the field_state callback, and logs what they returned.
 *   - advance: game time only moves forward; each call that crosses a
 *     multiple of 100 ms emits one "stub.tick" event.
 *   - score: every accepted input adds one point to team 1.
 *   - atalaia_stub_layout(): the sizes and field offsets of the structs the
 *     FFI bindings mirror, as JSON, compiled from the real headers.
 */
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "atalaia/node.h"
#include "atalaia/screen_template.h"
#include "atalaia/version.h"

#define STUB_TEAMS_MAX  8
#define STUB_ERROR_MAX  64
#define STUB_TICK_MS    100u
#define STUB_JSON_MAX   512
#define STUB_LAYOUT_MAX 2048

struct atalaia_node {
    atalaia_node_config_t cfg;
    atalaia_node_status_t status;
    bool paused;
    uint32_t now_ms;
    uint16_t next_seq;
    uint32_t inputs;
    size_t team_count;
    char teams[STUB_TEAMS_MAX][ATALAIA_TEAM_NAME_MAX];
    char error[STUB_ERROR_MAX];
    atalaia_score_t score;
};

const char *atalaia_version(void)
{
    return "stub";
}

atalaia_node_t *atalaia_node_create(const atalaia_node_config_t *cfg)
{
    if (cfg == NULL) return NULL;
    atalaia_node_t *n = calloc(1, sizeof(*n));
    if (n == NULL) return NULL;
    n->cfg = *cfg;
    n->status = ATALAIA_NODE_EMPTY;
    return n;
}

void atalaia_node_destroy(atalaia_node_t *node)
{
    free(node);
}

bool atalaia_node_set_teams(atalaia_node_t *node, const char *const *names, size_t count)
{
    if (node == NULL || names == NULL || count == 0 || count > STUB_TEAMS_MAX) return false;
    for (size_t i = 0; i < count; i++) {
        if (names[i] == NULL || names[i][0] == '\0' || strlen(names[i]) >= ATALAIA_TEAM_NAME_MAX) {
            return false;
        }
    }
    for (size_t i = 0; i < count; i++) {
        snprintf(node->teams[i], sizeof(node->teams[i]), "%s", names[i]);
    }
    node->team_count = count;
    return true;
}

bool atalaia_node_set_params(atalaia_node_t *node, const char *params_json)
{
    return node != NULL && params_json != NULL && params_json[0] == '{';
}

bool atalaia_node_load(atalaia_node_t *node, const char *source, size_t len, const char *chunk_name)
{
    (void)chunk_name;
    if (node == NULL) return false;
    if (source == NULL || len == 0) {
        node->status = ATALAIA_NODE_HALTED;
        snprintf(node->error, sizeof(node->error), "stub: empty script");
        return false;
    }
    node->status = ATALAIA_NODE_RUNNING;
    return true;
}

static void emit(atalaia_node_t *n, const char *type, uint8_t team, const char *data_json)
{
    atalaia_event_t ev;
    if (!atalaia_event_init(&ev, n->cfg.node_id, n->next_seq, n->now_ms, type, team,
                            ATALAIA_SQUAD_NONE, ATALAIA_PRIO_NORMAL)) {
        return;
    }
    n->next_seq++;
    if (n->cfg.callbacks.event != NULL) {
        n->cfg.callbacks.event(n->cfg.callbacks.user, &ev, data_json);
    }
}

static void log_line(atalaia_node_t *n, const char *message)
{
    if (n->cfg.callbacks.log != NULL) n->cfg.callbacks.log(n->cfg.callbacks.user, message);
}

/* Calls each field operation once, as a field script would, and logs the answers. */
static void probe_field(atalaia_node_t *n)
{
    const atalaia_field_ops_t *ops = n->cfg.field_ops;
    char line[STUB_JSON_MAX];
    if (ops == NULL) {
        log_line(n, "stub: no field ops");
        return;
    }
    char *nodes = ops->nodes != NULL ? ops->nodes(n->cfg.callbacks.user, "zone") : NULL;
    snprintf(line, sizeof(line), "nodes: %s", nodes != NULL ? nodes : "null");
    free(nodes); /* the host allocates it with malloc; the core frees it */
    log_line(n, line);
    const char *owner = ops->owner != NULL ? ops->owner(n->cfg.callbacks.user, 1) : NULL;
    snprintf(line, sizeof(line), "owner: %s", owner != NULL ? owner : "null");
    log_line(n, line);
    bool sent =
        ops->send != NULL && ops->send(n->cfg.callbacks.user, 1, "message", "{\"text\":\"hello\"}");
    snprintf(line, sizeof(line), "send: %s", sent ? "true" : "false");
    log_line(n, line);
    if (n->cfg.callbacks.field_state != NULL) {
        n->cfg.callbacks.field_state(n->cfg.callbacks.user, "probe", "{\"n\":1}");
    }
}

/* Team 1 when the data names the first team, as "team":"<name>". */
static uint8_t data_team(const atalaia_node_t *n, const char *data_json)
{
    char pattern[ATALAIA_TEAM_NAME_MAX + 12];
    if (n->team_count == 0) return ATALAIA_TEAM_NONE;
    snprintf(pattern, sizeof(pattern), "\"team\":\"%s\"", n->teams[0]);
    return strstr(data_json, pattern) != NULL ? 1 : ATALAIA_TEAM_NONE;
}

bool atalaia_node_input(atalaia_node_t *node, const char *type, const char *data_json)
{
    if (node == NULL || type == NULL || node->status != ATALAIA_NODE_RUNNING) return false;
    bool game = strncmp(type, "game.", 5) == 0;
    if (node->paused && !game) return false;
    if (data_json == NULL) data_json = "{}";
    if (data_json[0] != '{') return false;

    if (strcmp(type, "game.pause") == 0) node->paused = true;
    if (strcmp(type, "game.resume") == 0) node->paused = false;
    node->inputs++;
    atalaia_score_add(&node->score, 1, 1);

    emit(node, type, data_team(node, data_json), data_json);
    char args[64];
    snprintf(args, sizeof(args), "[\"stub\",{\"inputs\":%lu}]", (unsigned long)node->inputs);
    if (node->cfg.callbacks.command != NULL) {
        node->cfg.callbacks.command(node->cfg.callbacks.user, "ui", "screen", args);
    }
    char line[ATALAIA_EVENT_TYPE_MAX + 8];
    snprintf(line, sizeof(line), "stub: %s", type);
    log_line(node, line);
    if (strcmp(type, "stub.field") == 0) probe_field(node);
    if (strcmp(type, "game.end") == 0) node->status = ATALAIA_NODE_ENDED;
    return true;
}

void atalaia_node_advance(atalaia_node_t *node, uint32_t now_ms)
{
    if (node == NULL || now_ms <= node->now_ms) return;
    bool tick = now_ms / STUB_TICK_MS != node->now_ms / STUB_TICK_MS;
    node->now_ms = now_ms;
    if (tick && node->status == ATALAIA_NODE_RUNNING) emit(node, "stub.tick", 0, "{}");
}

atalaia_node_status_t atalaia_node_status(const atalaia_node_t *node)
{
    return node != NULL ? node->status : ATALAIA_NODE_EMPTY;
}

const char *atalaia_node_status_name(atalaia_node_status_t status)
{
    switch (status) {
    case ATALAIA_NODE_EMPTY: return "empty";
    case ATALAIA_NODE_RUNNING: return "running";
    case ATALAIA_NODE_ENDED: return "ended";
    case ATALAIA_NODE_HALTED: return "halted";
    }
    return "unknown";
}

bool atalaia_node_paused(const atalaia_node_t *node)
{
    return node != NULL && node->paused;
}

uint32_t atalaia_node_time(const atalaia_node_t *node)
{
    return node != NULL ? node->now_ms : 0;
}

const char *atalaia_node_last_error(const atalaia_node_t *node)
{
    return node != NULL ? node->error : "";
}

size_t atalaia_node_mem_used(const atalaia_node_t *node)
{
    return node != NULL ? 4096u + 64u * node->inputs : 0;
}

const atalaia_score_t *atalaia_node_score(const atalaia_node_t *node)
{
    return node != NULL ? &node->score : NULL;
}

uint8_t atalaia_node_team_id(const atalaia_node_t *node, const char *name)
{
    if (node == NULL || name == NULL) return ATALAIA_TEAM_NONE;
    for (size_t i = 0; i < node->team_count; i++) {
        if (strcmp(node->teams[i], name) == 0) return (uint8_t)(i + 1);
    }
    return ATALAIA_TEAM_NONE;
}

const char *atalaia_node_team_name(const atalaia_node_t *node, uint8_t team)
{
    if (node == NULL || team == ATALAIA_TEAM_NONE || team > node->team_count) return NULL;
    return node->teams[team - 1];
}

/* The few helpers of event.h and score.h the stub and its callers use. */

bool atalaia_event_init(atalaia_event_t *ev, uint16_t node, uint16_t seq, uint32_t t_ms,
                        const char *type, uint8_t team, uint8_t squad, atalaia_prio_t prio)
{
    memset(ev, 0, sizeof(*ev));
    if (type == NULL || type[0] == '\0' || strlen(type) >= sizeof(ev->type) ||
        team > ATALAIA_TEAM_MAX) {
        return false;
    }
    ev->node = node;
    ev->seq = seq;
    ev->t_ms = t_ms;
    ev->team = team;
    ev->squad = squad;
    ev->prio = prio;
    memcpy(ev->type, type, strlen(type) + 1);
    return true;
}

bool atalaia_score_add(atalaia_score_t *score, uint8_t team, int32_t amount)
{
    if (team == ATALAIA_TEAM_NONE || team > ATALAIA_TEAM_MAX) return false;
    if (amount >= 0) {
        score->gained[team] += (uint32_t)amount;
    } else {
        score->lost[team] += (uint32_t)(-(int64_t)amount);
    }
    return true;
}

int64_t atalaia_score_net(const atalaia_score_t *score, uint8_t team)
{
    if (score == NULL || team > ATALAIA_TEAM_MAX) return 0;
    return (int64_t)score->gained[team] - (int64_t)score->lost[team];
}

/* ---- Struct layouts ------------------------------------------------------ */

#define LAYOUT_FIELD(type, field) "\"" #field "\":%lu", (unsigned long)offsetof(type, field)
#define LAYOUT_HEAD(type)                                                                          \
    "\"" #type "\":{\"size\":%lu,\"align\":%lu,\"fields\":{", (unsigned long)sizeof(type),         \
        (unsigned long)_Alignof(type)

static size_t append(char *buf, size_t used, const char *fmt, ...)
    __attribute__((format(printf, 3, 4)));

static size_t append(char *buf, size_t used, const char *fmt, ...)
{
    if (used >= STUB_LAYOUT_MAX) return used;
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(buf + used, STUB_LAYOUT_MAX - used, fmt, ap);
    va_end(ap);
    return n < 0 ? STUB_LAYOUT_MAX : used + (size_t)n;
}

/*
 * {"atalaia_event_t":{"size":56,"align":4,"fields":{"node":0,...}},...}: what
 * this compiler makes of the public structs, for the Dart and Python bindings
 * to compare with their own declarations. Not part of the real core.
 */
const char *atalaia_stub_layout(void)
{
    static char buf[STUB_LAYOUT_MAX];
    size_t u = 0;
    u = append(buf, u, "{");
    u = append(buf, u, LAYOUT_HEAD(atalaia_event_t));
    u = append(buf, u, LAYOUT_FIELD(atalaia_event_t, node));
    u = append(buf, u, "," LAYOUT_FIELD(atalaia_event_t, seq));
    u = append(buf, u, "," LAYOUT_FIELD(atalaia_event_t, t_ms));
    u = append(buf, u, "," LAYOUT_FIELD(atalaia_event_t, team));
    u = append(buf, u, "," LAYOUT_FIELD(atalaia_event_t, squad));
    u = append(buf, u, "," LAYOUT_FIELD(atalaia_event_t, prio));
    u = append(buf, u, "," LAYOUT_FIELD(atalaia_event_t, type));
    u = append(buf, u, "}},");
    u = append(buf, u, LAYOUT_HEAD(atalaia_node_callbacks_t));
    u = append(buf, u, LAYOUT_FIELD(atalaia_node_callbacks_t, event));
    u = append(buf, u, "," LAYOUT_FIELD(atalaia_node_callbacks_t, command));
    u = append(buf, u, "," LAYOUT_FIELD(atalaia_node_callbacks_t, log));
    u = append(buf, u, "," LAYOUT_FIELD(atalaia_node_callbacks_t, field_state));
    u = append(buf, u, "," LAYOUT_FIELD(atalaia_node_callbacks_t, user));
    u = append(buf, u, "}},");
    u = append(buf, u, LAYOUT_HEAD(atalaia_field_ops_t));
    u = append(buf, u, LAYOUT_FIELD(atalaia_field_ops_t, nodes));
    u = append(buf, u, "," LAYOUT_FIELD(atalaia_field_ops_t, owner));
    u = append(buf, u, "," LAYOUT_FIELD(atalaia_field_ops_t, send));
    u = append(buf, u, "}},");
    u = append(buf, u, LAYOUT_HEAD(atalaia_node_config_t));
    u = append(buf, u, LAYOUT_FIELD(atalaia_node_config_t, node_id));
    u = append(buf, u, "," LAYOUT_FIELD(atalaia_node_config_t, game_seed));
    u = append(buf, u, "," LAYOUT_FIELD(atalaia_node_config_t, mem_limit));
    u = append(buf, u, "," LAYOUT_FIELD(atalaia_node_config_t, instr_limit));
    u = append(buf, u, "," LAYOUT_FIELD(atalaia_node_config_t, callbacks));
    u = append(buf, u, "," LAYOUT_FIELD(atalaia_node_config_t, alloc));
    u = append(buf, u, "," LAYOUT_FIELD(atalaia_node_config_t, alloc_ud));
    u = append(buf, u, "," LAYOUT_FIELD(atalaia_node_config_t, field_ops));
    u = append(buf, u, "}},");
    u = append(buf, u, LAYOUT_HEAD(atalaia_score_t));
    u = append(buf, u, LAYOUT_FIELD(atalaia_score_t, gained));
    u = append(buf, u, "," LAYOUT_FIELD(atalaia_score_t, lost));
    u = append(buf, u, "}},");
    u = append(buf, u, LAYOUT_HEAD(atalaia_tpl_scope_t));
    u = append(buf, u, LAYOUT_FIELD(atalaia_tpl_scope_t, data));
    u = append(buf, u, "," LAYOUT_FIELD(atalaia_tpl_scope_t, params));
    u = append(buf, u, "}}}");
    return u < STUB_LAYOUT_MAX ? buf : "{}";
}
