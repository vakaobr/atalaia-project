/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Shared between node.c (lifecycle, event bus, timers), sandbox.c (the Lua
 * state and its limits) and script_api.c (the functions scripts call).
 */
#ifndef ATALAIA_NODE_INTERNAL_H
#define ATALAIA_NODE_INTERNAL_H

#include "atalaia/node.h"
#include "lua.h"
#include "rand.h"

#define NODE_ERROR_MAX 200

/* Registry keys for tables the runtime keeps inside the Lua state. */
#define REG_HANDLERS "atalaia.handlers" /* event type -> list of functions */
#define REG_QUEUE    "atalaia.queue"    /* events waiting for dispatch */
#define REG_CAPS     "atalaia.caps"     /* capability id -> proxy */
#define REG_STATE    "atalaia.state"    /* the state.node table */

typedef struct {
    bool active;
    uint32_t id;
    uint32_t due_ms;
    uint32_t interval_ms; /* 0 for one-shot timers */
    int fn_ref;
} node_timer_t;

struct atalaia_node {
    atalaia_node_config_t cfg;
    lua_State *L;
    atalaia_node_status_t status;
    bool paused;

    size_t mem_used;
    uint32_t instr_used; /* in the current callback */
    bool watchdog_tripped;

    uint32_t now_ms;
    uint16_t next_seq;
    uint32_t next_timer_id;
    lua_Integer queue_head; /* last dispatched index */
    lua_Integer queue_tail; /* last queued index */

    atalaia_rand_t rng;
    atalaia_score_t score;
    node_timer_t timers[ATALAIA_NODE_MAX_TIMERS];

    char (*team_names)[ATALAIA_TEAM_NAME_MAX];
    size_t team_count;

    char error[NODE_ERROR_MAX];
};

/* sandbox.c */
lua_State *atalaia_sandbox_open(atalaia_node_t *node);
atalaia_node_t *atalaia_node_from_lua(lua_State *L);

/* script_api.c */
int atalaia_script_api_open(lua_State *L);

/* node.c */
void atalaia_node_deliver(atalaia_node_t *node, const char *type, uint8_t team, uint8_t squad,
                          atalaia_prio_t prio, const char *data_json);
void atalaia_node_command(atalaia_node_t *node, const char *target, const char *method,
                          const char *args_json);
void atalaia_node_log(atalaia_node_t *node, const char *message);
void atalaia_node_enqueue(lua_State *L, atalaia_node_t *node); /* pops event */
uint32_t atalaia_node_add_timer(atalaia_node_t *node, lua_State *L, int fn_idx, uint32_t delay_ms,
                                uint32_t interval_ms);
void atalaia_node_cancel_timer(atalaia_node_t *node, lua_State *L, uint32_t id);

#endif /* ATALAIA_NODE_INTERNAL_H */
