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

/*
 * One host entry (an input event, an advance of time, the load) may run its callbacks (the
 * handlers of the event and of every event they emit, the due timers) for at most this many
 * times the per-callback instruction limit in all (review finding LIVE2-S4, decision SR-133):
 * without it a script could chain callbacks, each within its own limit, for minutes inside one
 * call of the box's game task. An advance of game time also gets one per-callback limit for
 * every 100 ms it moves the clock (a host that jumps a minute ahead, as the simulator's fast
 * forward does, has that many timers to run; the box ticks every 10 ms and gets the factor only).
 */
#define NODE_ENTRY_LIMIT_FACTOR 4u
/*
 * The hook only counts whole steps of 1000 instructions, so a callback of a few hundred
 * instructions was free: a timer every millisecond, advanced by a long jump of time, or a chain
 * of tiny handlers, ran for as long as it had callbacks. Each callback costs the entry at least
 * this many instructions, so one entry runs at most 4 million / 250 = 16,000 of them at the
 * default limit.
 */
#define NODE_CALLBACK_MIN_COST 250u
/*
 * field.send hands a command to the radio: at most this many in one host entry (a controller sets
 * every zone of a big field at the start, which is well under it); the rest return false
 * (decision SR-138).
 */
#define NODE_FIELD_SENDS_PER_ENTRY 256u

/* Registry keys for tables the runtime keeps inside the Lua state. */
#define REG_HANDLERS    "atalaia.handlers"    /* event type -> list of functions */
#define REG_QUEUE       "atalaia.queue"       /* events waiting for dispatch */
#define REG_CAPS        "atalaia.caps"        /* capability id -> proxy */
#define REG_STATE       "atalaia.state"       /* the state.node table */
#define REG_FIELD_STATE "atalaia.field_state" /* the state.field table */

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
    uint32_t instr_used;  /* in the current callback */
    uint64_t entry_used;  /* in the callbacks of this host entry that have finished */
    uint64_t entry_extra; /* what the entry may use besides the factor: game time it advances */
    bool watchdog_tripped;
    uint32_t field_sends; /* field.send calls in this host entry */
    bool entry_tripped;   /* ... because of the per-entry cap, not the per-callback one */

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

static inline uint64_t atalaia_node_entry_limit(const atalaia_node_t *n)
{
    return (uint64_t)n->cfg.instr_limit * NODE_ENTRY_LIMIT_FACTOR + n->entry_extra;
}

/* sandbox.c */
lua_State *atalaia_sandbox_open(atalaia_node_t *node);
/* Stops every thread of the state from running any more instructions (after a watchdog trip). */
void atalaia_sandbox_trip(atalaia_node_t *node);
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
