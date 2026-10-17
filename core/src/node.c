/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Node lifecycle, the event bus and timers.
 *
 * Every entry point that touches the Lua state runs in protected mode, and
 * every script callback runs in its own protected call with a fresh
 * instruction budget, so one failing handler cannot stop the others.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "json.h"
#include "lauxlib.h"
#include "node_internal.h"

/* An event storm (a handler that keeps emitting what it handles) halts the
 * node after this many events in one input or timer step. */
#define MAX_EVENTS_PER_STEP 256

static void *default_alloc(void *ud, void *ptr, size_t old_size, size_t new_size)
{
    (void)ud;
    (void)old_size;
    if (new_size == 0) {
        free(ptr);
        return NULL;
    }
    return realloc(ptr, new_size);
}

static void set_error(atalaia_node_t *n, const char *message)
{
    if (message == n->error) {
        return; /* already there; snprintf must not copy onto itself */
    }
    snprintf(n->error, sizeof(n->error), "%s", message != NULL ? message : "unknown error");
}

/* ---- Delivery to the host ------------------------------------------------ */

void atalaia_node_deliver(atalaia_node_t *n, const char *type, uint8_t team, uint8_t squad,
                          atalaia_prio_t prio, const char *data_json)
{
    atalaia_event_t ev;
    if (!atalaia_event_init(&ev, n->cfg.node_id, n->next_seq, n->now_ms, type, team, squad, prio)) {
        return;
    }
    n->next_seq++;
    if (n->cfg.callbacks.event != NULL) {
        n->cfg.callbacks.event(n->cfg.callbacks.user, &ev, data_json != NULL ? data_json : "{}");
    }
}

void atalaia_node_command(atalaia_node_t *n, const char *target, const char *method,
                          const char *args_json)
{
    if (n->cfg.callbacks.command != NULL) {
        n->cfg.callbacks.command(n->cfg.callbacks.user, target, method, args_json);
    }
}

void atalaia_node_log(atalaia_node_t *n, const char *message)
{
    if (n->cfg.callbacks.log != NULL) {
        n->cfg.callbacks.log(n->cfg.callbacks.user, message);
    }
}

/* Stops the script for good and shows the safe paused screen. */
static void halt(atalaia_node_t *n, const char *reason)
{
    if (n->status == ATALAIA_NODE_HALTED) {
        return;
    }
    n->status = ATALAIA_NODE_HALTED;
    set_error(n, reason);

    char quoted[NODE_ERROR_MAX + 16];
    char json[NODE_ERROR_MAX + 64];
    atalaia_json_quote(quoted, sizeof(quoted), n->error);
    snprintf(json, sizeof(json), "{\"reason\":%s}", quoted);
    atalaia_node_deliver(n, "script.halted", ATALAIA_TEAM_NONE, ATALAIA_SQUAD_NONE,
                         ATALAIA_PRIO_CRITICAL, json);
    snprintf(json, sizeof(json), "[\"paused\",{\"reason\":%s}]", quoted);
    atalaia_node_command(n, "ui", "screen", json);
}

static void report_script_error(atalaia_node_t *n, const char *message)
{
    set_error(n, message);
    char quoted[NODE_ERROR_MAX + 16];
    char json[NODE_ERROR_MAX + 32];
    atalaia_json_quote(quoted, sizeof(quoted), n->error);
    snprintf(json, sizeof(json), "{\"message\":%s}", quoted);
    atalaia_node_deliver(n, "script.error", ATALAIA_TEAM_NONE, ATALAIA_SQUAD_NONE,
                         ATALAIA_PRIO_NORMAL, json);
}

/* ---- Calling into Lua ---------------------------------------------------- */

/* Calls the script function below nargs arguments with a fresh budget. */
static bool call_script(lua_State *L, atalaia_node_t *n, int nargs)
{
    n->instr_used = 0;
    int rc = lua_pcall(L, nargs, 0, 0);
    if (rc == LUA_OK) {
        return true;
    }
    if (n->watchdog_tripped) {
        halt(n, "instruction limit exceeded");
    } else if (rc == LUA_ERRMEM) {
        halt(n, "memory limit exceeded");
    } else {
        const char *msg = lua_tostring(L, -1);
        report_script_error(n, msg != NULL ? msg : "error object is not a string");
    }
    lua_pop(L, 1);
    return false;
}

/* Runs one of the runtime's own C functions in protected mode. */
static bool run_protected(atalaia_node_t *n, lua_CFunction fn, void *arg)
{
    lua_State *L = n->L;
    lua_pushcfunction(L, fn);
    lua_pushlightuserdata(L, arg);
    int rc = lua_pcall(L, 1, 0, 0);
    if (rc == LUA_OK) {
        return true;
    }
    if (rc == LUA_ERRMEM) {
        halt(n, "memory limit exceeded");
    } else {
        set_error(n, lua_tostring(L, -1));
    }
    lua_pop(L, 1);
    return false;
}

/* ---- Event bus ----------------------------------------------------------- */

void atalaia_node_enqueue(lua_State *L, atalaia_node_t *n)
{
    lua_getfield(L, LUA_REGISTRYINDEX, REG_QUEUE);
    lua_insert(L, -2);
    lua_rawseti(L, -2, ++n->queue_tail);
    lua_pop(L, 1);
}

static void apply_lifecycle(atalaia_node_t *n, const char *type)
{
    if (strcmp(type, "game.end") == 0) {
        n->status = ATALAIA_NODE_ENDED;
    } else if (strcmp(type, "game.pause") == 0) {
        n->paused = true;
    } else if (strcmp(type, "game.resume") == 0) {
        n->paused = false;
    }
}

/* Dispatches queued events in order until the queue is empty. */
static void drain(lua_State *L, atalaia_node_t *n)
{
    int processed = 0;
    lua_getfield(L, LUA_REGISTRYINDEX, REG_QUEUE);
    lua_getfield(L, LUA_REGISTRYINDEX, REG_HANDLERS);
    int queue = lua_gettop(L) - 1;
    int handlers = queue + 1;

    while (n->queue_head < n->queue_tail && n->status == ATALAIA_NODE_RUNNING) {
        if (++processed > MAX_EVENTS_PER_STEP) {
            halt(n, "too many events in one step (does a handler emit the event it handles?)");
            break;
        }
        lua_Integer index = ++n->queue_head;
        lua_rawgeti(L, queue, index);
        lua_pushnil(L);
        lua_rawseti(L, queue, index);
        int event = lua_gettop(L);

        lua_getfield(L, event, "type");
        const char *type = lua_tostring(L, -1); /* anchored in the event table */
        lua_pushvalue(L, -1);
        if (lua_rawget(L, handlers) == LUA_TTABLE) {
            int list = lua_gettop(L);
            lua_Integer count = (lua_Integer)lua_rawlen(L, list);
            for (lua_Integer i = 1; i <= count && n->status == ATALAIA_NODE_RUNNING; i++) {
                lua_rawgeti(L, list, i);
                lua_pushvalue(L, event);
                call_script(L, n, 1);
            }
        }
        if (n->status == ATALAIA_NODE_RUNNING && type != NULL) {
            apply_lifecycle(n, type);
        }
        lua_settop(L, event - 1);
    }

    if (n->queue_head >= n->queue_tail || n->status != ATALAIA_NODE_RUNNING) {
        /* Drop anything left over and restart the indices. */
        lua_newtable(L);
        lua_setfield(L, LUA_REGISTRYINDEX, REG_QUEUE);
        n->queue_head = n->queue_tail = 0;
    }
    lua_pop(L, 2);
}

/* ---- Timers -------------------------------------------------------------- */

uint32_t atalaia_node_add_timer(atalaia_node_t *n, lua_State *L, int fn_idx, uint32_t delay_ms,
                                uint32_t interval_ms)
{
    for (int i = 0; i < ATALAIA_NODE_MAX_TIMERS; i++) {
        node_timer_t *t = &n->timers[i];
        if (t->active) {
            continue;
        }
        lua_pushvalue(L, fn_idx);
        t->fn_ref = luaL_ref(L, LUA_REGISTRYINDEX);
        t->active = true;
        t->id = ++n->next_timer_id;
        t->due_ms = n->now_ms + delay_ms;
        t->interval_ms = interval_ms;
        return t->id;
    }
    return 0;
}

void atalaia_node_cancel_timer(atalaia_node_t *n, lua_State *L, uint32_t id)
{
    for (int i = 0; i < ATALAIA_NODE_MAX_TIMERS; i++) {
        node_timer_t *t = &n->timers[i];
        if (t->active && t->id == id) {
            luaL_unref(L, LUA_REGISTRYINDEX, t->fn_ref);
            t->active = false;
            return;
        }
    }
}

/* The earliest timer due at or before limit_ms; creation order breaks ties. */
static node_timer_t *next_due(atalaia_node_t *n, uint32_t limit_ms)
{
    node_timer_t *best = NULL;
    for (int i = 0; i < ATALAIA_NODE_MAX_TIMERS; i++) {
        node_timer_t *t = &n->timers[i];
        if (!t->active || t->due_ms > limit_ms) {
            continue;
        }
        if (best == NULL || t->due_ms < best->due_ms ||
            (t->due_ms == best->due_ms && t->id < best->id)) {
            best = t;
        }
    }
    return best;
}

/* ---- Protected steps ----------------------------------------------------- */

typedef struct {
    atalaia_node_t *n;
    const char *a;
    const char *b;
    size_t len;
    uint32_t ms;
} step_args_t;

/* Raises an error unless the text starts with a JSON object. */
static void check_object_text(lua_State *L, const char *text, const char *what)
{
    while (*text == ' ' || *text == '\t' || *text == '\n' || *text == '\r') {
        text++;
    }
    if (*text != '{') {
        luaL_error(L, "%s must be a JSON object", what);
    }
}

static int p_set_params(lua_State *L)
{
    step_args_t *args = (step_args_t *)lua_touserdata(L, 1);
    if (args->a == NULL) {
        lua_newtable(L);
    } else {
        check_object_text(L, args->a, "parameters");
        atalaia_json_push_decoded(L, args->a);
    }
    lua_setglobal(L, "params");
    return 0;
}

static int p_load(lua_State *L)
{
    step_args_t *args = (step_args_t *)lua_touserdata(L, 1);
    atalaia_node_t *n = args->n;
    /* Text only: precompiled bytecode can crash the VM. */
    if (luaL_loadbufferx(L, args->a, args->len, args->b, "t") != LUA_OK) {
        halt(n, lua_tostring(L, -1));
        return 0;
    }
    n->status = ATALAIA_NODE_RUNNING;
    if (!call_script(L, n, 0)) {
        halt(n, n->error); /* a script that fails at load cannot run */
        return 0;
    }
    drain(L, n);
    return 0;
}

static int p_input(lua_State *L)
{
    step_args_t *args = (step_args_t *)lua_touserdata(L, 1);
    atalaia_node_t *n = args->n;
    if (args->b != NULL) {
        check_object_text(L, args->b, "event data");
        atalaia_json_push_decoded(L, args->b);
    } else {
        lua_newtable(L);
    }
    lua_pushstring(L, args->a);
    lua_setfield(L, -2, "type");
    lua_pushinteger(L, (lua_Integer)n->now_ms);
    lua_setfield(L, -2, "t");
    atalaia_node_enqueue(L, n);
    drain(L, n);
    return 0;
}

static int p_advance(lua_State *L)
{
    step_args_t *args = (step_args_t *)lua_touserdata(L, 1);
    atalaia_node_t *n = args->n;
    for (;;) {
        node_timer_t *t = next_due(n, args->ms);
        if (t == NULL) {
            break;
        }
        n->now_ms = t->due_ms;
        lua_rawgeti(L, LUA_REGISTRYINDEX, t->fn_ref);
        /* Update the timer before the call so it may cancel itself. */
        if (t->interval_ms != 0) {
            t->due_ms += t->interval_ms;
        } else {
            luaL_unref(L, LUA_REGISTRYINDEX, t->fn_ref);
            t->active = false;
        }
        call_script(L, n, 0);
        drain(L, n);
        if (n->status != ATALAIA_NODE_RUNNING || n->paused) {
            return 0; /* time stops at the event that ended or paused it */
        }
    }
    n->now_ms = args->ms;
    return 0;
}

/* ---- Public API ---------------------------------------------------------- */

atalaia_node_t *atalaia_node_create(const atalaia_node_config_t *cfg)
{
    if (cfg == NULL) {
        return NULL;
    }
    atalaia_alloc_fn alloc = cfg->alloc != NULL ? cfg->alloc : default_alloc;
    atalaia_node_t *n = (atalaia_node_t *)alloc(cfg->alloc_ud, NULL, 0, sizeof(*n));
    if (n == NULL) {
        return NULL;
    }
    memset(n, 0, sizeof(*n));
    n->cfg = *cfg;
    n->cfg.alloc = alloc;
    if (n->cfg.mem_limit == 0) {
        n->cfg.mem_limit = ATALAIA_NODE_DEFAULT_MEM_LIMIT;
    }
    if (n->cfg.instr_limit == 0) {
        n->cfg.instr_limit = ATALAIA_NODE_DEFAULT_INSTR_LIMIT;
    }
    n->status = ATALAIA_NODE_EMPTY;
    n->next_seq = 1;
    atalaia_rand_seed(&n->rng, cfg->game_seed, cfg->node_id);
    atalaia_score_init(&n->score);

    n->L = atalaia_sandbox_open(n);
    if (n->L == NULL) {
        alloc(cfg->alloc_ud, n, sizeof(*n), 0);
        return NULL;
    }
    return n;
}

void atalaia_node_destroy(atalaia_node_t *n)
{
    if (n == NULL) {
        return;
    }
    lua_close(n->L);
    if (n->team_names != NULL) {
        n->cfg.alloc(n->cfg.alloc_ud, n->team_names, n->team_count * sizeof(*n->team_names), 0);
    }
    n->cfg.alloc(n->cfg.alloc_ud, n, sizeof(*n), 0);
}

bool atalaia_node_set_teams(atalaia_node_t *n, const char *const *names, size_t count)
{
    if (n == NULL || n->status != ATALAIA_NODE_EMPTY || count > ATALAIA_TEAM_MAX ||
        (count > 0 && names == NULL)) {
        return false;
    }
    for (size_t i = 0; i < count; i++) {
        size_t len = names[i] != NULL ? strlen(names[i]) : 0;
        if (len == 0 || len >= ATALAIA_TEAM_NAME_MAX) {
            set_error(n, "team names must be 1 to 23 characters");
            return false;
        }
        for (size_t j = 0; j < i; j++) {
            if (strcmp(names[i], names[j]) == 0) {
                set_error(n, "team names must be unique");
                return false;
            }
        }
    }

    char(*copy)[ATALAIA_TEAM_NAME_MAX] = NULL;
    if (count > 0) {
        copy = n->cfg.alloc(n->cfg.alloc_ud, NULL, 0, count * sizeof(*copy));
        if (copy == NULL) {
            set_error(n, "out of memory");
            return false;
        }
        for (size_t i = 0; i < count; i++) {
            snprintf(copy[i], ATALAIA_TEAM_NAME_MAX, "%s", names[i]);
        }
    }
    if (n->team_names != NULL) {
        n->cfg.alloc(n->cfg.alloc_ud, n->team_names, n->team_count * sizeof(*n->team_names), 0);
    }
    n->team_names = copy;
    n->team_count = count;
    return true;
}

bool atalaia_node_set_params(atalaia_node_t *n, const char *params_json)
{
    if (n == NULL || n->status != ATALAIA_NODE_EMPTY) {
        return false;
    }
    step_args_t args = {n, params_json, NULL, 0, 0};
    return run_protected(n, p_set_params, &args);
}

bool atalaia_node_load(atalaia_node_t *n, const char *source, size_t len, const char *chunk_name)
{
    if (n == NULL || source == NULL || n->status != ATALAIA_NODE_EMPTY) {
        return false;
    }
    step_args_t args = {n, source, chunk_name != NULL ? chunk_name : "=node", len, 0};
    if (!run_protected(n, p_load, &args)) {
        halt(n, n->error);
    }
    return n->status == ATALAIA_NODE_RUNNING || n->status == ATALAIA_NODE_ENDED;
}

bool atalaia_node_input(atalaia_node_t *n, const char *type, const char *data_json)
{
    if (n == NULL || type == NULL || n->status != ATALAIA_NODE_RUNNING) {
        return false;
    }
    if (n->paused && strncmp(type, "game.", 5) != 0) {
        return false;
    }
    step_args_t args = {n, type, data_json, 0, 0};
    return run_protected(n, p_input, &args);
}

void atalaia_node_advance(atalaia_node_t *n, uint32_t now_ms)
{
    if (n == NULL || n->status != ATALAIA_NODE_RUNNING || n->paused || now_ms <= n->now_ms) {
        return;
    }
    step_args_t args = {n, NULL, NULL, 0, now_ms};
    run_protected(n, p_advance, &args);
}

atalaia_node_status_t atalaia_node_status(const atalaia_node_t *n)
{
    return n->status;
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

bool atalaia_node_paused(const atalaia_node_t *n)
{
    return n->paused;
}

uint32_t atalaia_node_time(const atalaia_node_t *n)
{
    return n->now_ms;
}

const char *atalaia_node_last_error(const atalaia_node_t *n)
{
    return n->error;
}

size_t atalaia_node_mem_used(const atalaia_node_t *n)
{
    return n->mem_used;
}

const atalaia_score_t *atalaia_node_score(const atalaia_node_t *n)
{
    return &n->score;
}

uint8_t atalaia_node_team_id(const atalaia_node_t *n, const char *name)
{
    if (name == NULL) {
        return ATALAIA_TEAM_NONE;
    }
    for (size_t i = 0; i < n->team_count; i++) {
        if (strcmp(n->team_names[i], name) == 0) {
            return (uint8_t)(i + 1);
        }
    }
    return ATALAIA_TEAM_NONE;
}

const char *atalaia_node_team_name(const atalaia_node_t *n, uint8_t team)
{
    if (team == ATALAIA_TEAM_NONE || team > n->team_count) {
        return NULL;
    }
    return n->team_names[team - 1];
}
