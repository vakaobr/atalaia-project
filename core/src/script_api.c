/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The functions game mode scripts call. The table "Script API surface" in
 * the design specification lists them; keep the two in step.
 */
#include <string.h>

#include "json.h"
#include "lauxlib.h"
#include "node_internal.h"

/* ---- Helpers ------------------------------------------------------------- */

static uint8_t check_team(lua_State *L, atalaia_node_t *n, int idx,
                          const char *fn)
{
    const char *name = lua_type(L, idx) == LUA_TSTRING ? lua_tostring(L, idx) : NULL;
    if (name == NULL) {
        luaL_error(L, "%s: team must be a team name", fn);
    }
    uint8_t team = atalaia_node_team_id(n, name);
    if (team == ATALAIA_TEAM_NONE) {
        luaL_error(L, "%s: unknown team '%s'", fn, name);
    }
    return team;
}

/* opts.prio, or the event's default priority from the protocol schema
 * (normal for custom events). */
static atalaia_prio_t check_prio(lua_State *L, int opts_idx, const char *type)
{
    const atalaia_event_def_t *def = atalaia_event_def(type);
    atalaia_prio_t result = def != NULL ? def->prio : ATALAIA_PRIO_NORMAL;
    if (lua_isnoneornil(L, opts_idx)) {
        return result;
    }
    luaL_checktype(L, opts_idx, LUA_TTABLE);
    lua_getfield(L, opts_idx, "prio");
    const char *prio = lua_tostring(L, -1);
    if (prio == NULL) {
        /* keep the default */
    } else if (strcmp(prio, "normal") == 0) {
        result = ATALAIA_PRIO_NORMAL;
    } else if (strcmp(prio, "critical") == 0) {
        result = ATALAIA_PRIO_CRITICAL;
    } else if (strcmp(prio, "telemetry") == 0) {
        result = ATALAIA_PRIO_TELEMETRY;
    } else {
        luaL_error(L, "emit: unknown priority '%s'", prio);
    }
    lua_pop(L, 1);
    return result;
}

/* Builds the table handlers receive: a copy of data plus type, t and node. */
static void push_event_table(lua_State *L, atalaia_node_t *n, const char *type,
                             int data_idx)
{
    lua_newtable(L);
    if (data_idx != 0) {
        lua_pushnil(L);
        while (lua_next(L, data_idx)) {
            lua_pushvalue(L, -2);
            lua_insert(L, -2);
            lua_rawset(L, -4);
        }
    }
    lua_pushstring(L, type);
    lua_setfield(L, -2, "type");
    lua_pushinteger(L, (lua_Integer)n->now_ms);
    lua_setfield(L, -2, "t");
    lua_pushinteger(L, (lua_Integer)n->cfg.node_id);
    lua_setfield(L, -2, "node");
}

/*
 * Sends an event to the host and queues it for this node's own handlers.
 * data_idx is 0 for an event without data.
 */
static void emit_event(lua_State *L, atalaia_node_t *n, const char *type,
                       int data_idx, atalaia_prio_t prio, const char *fn)
{
    if (n->status != ATALAIA_NODE_RUNNING) {
        luaL_error(L, "%s: the game is not running", fn);
    }
    size_t len = strlen(type);
    if (len == 0 || len >= ATALAIA_EVENT_TYPE_MAX) {
        luaL_error(L, "%s: event type must be 1 to %d characters", fn,
                   ATALAIA_EVENT_TYPE_MAX - 1);
    }

    uint8_t team = ATALAIA_TEAM_NONE;
    if (data_idx != 0) {
        data_idx = lua_absindex(L, data_idx);
        if (lua_getfield(L, data_idx, "team") != LUA_TNIL) {
            team = check_team(L, n, -1, fn);
        }
        lua_pop(L, 1);
        atalaia_json_push_encoded(L, data_idx);
    } else {
        lua_pushliteral(L, "{}");
    }
    /* Squad ids arrive with squad support; the squad name stays in data. */
    atalaia_node_deliver(n, type, team, ATALAIA_SQUAD_NONE, prio,
                         lua_tostring(L, -1));
    lua_pop(L, 1);

    push_event_table(L, n, type, data_idx);
    atalaia_node_enqueue(L, n);
}

static uint32_t check_seconds(lua_State *L, int idx, uint32_t min_ms)
{
    lua_Number s = luaL_checknumber(L, idx);
    /* 40 days keeps every game time inside 32-bit milliseconds. */
    luaL_argcheck(L, s >= 0 && s <= 40.0 * 86400.0, idx, "seconds out of range");
    uint32_t ms = (uint32_t)(s * 1000.0 + 0.5);
    luaL_argcheck(L, ms >= min_ms, idx, "interval is too short");
    return ms;
}

/* ---- Events and time ----------------------------------------------------- */

static int l_on(lua_State *L)
{
    luaL_checkstring(L, 1);
    luaL_checktype(L, 2, LUA_TFUNCTION);
    lua_getfield(L, LUA_REGISTRYINDEX, REG_HANDLERS);
    lua_pushvalue(L, 1);
    if (lua_rawget(L, -2) != LUA_TTABLE) {
        lua_pop(L, 1);
        lua_newtable(L);
        lua_pushvalue(L, 1);
        lua_pushvalue(L, -2);
        lua_rawset(L, -4);
    }
    lua_pushvalue(L, 2);
    lua_rawseti(L, -2, (lua_Integer)lua_rawlen(L, -2) + 1);
    return 0;
}

static int l_emit(lua_State *L)
{
    atalaia_node_t *n = atalaia_node_from_lua(L);
    const char *type = luaL_checkstring(L, 1);
    int data_idx = 0;
    if (!lua_isnoneornil(L, 2)) {
        luaL_checktype(L, 2, LUA_TTABLE);
        data_idx = 2;
    }
    atalaia_prio_t prio = check_prio(L, 3, type);
    emit_event(L, n, type, data_idx, prio, "emit");
    return 0;
}

static int l_every(lua_State *L)
{
    atalaia_node_t *n = atalaia_node_from_lua(L);
    uint32_t ms = check_seconds(L, 1, ATALAIA_NODE_MIN_INTERVAL_MS);
    luaL_checktype(L, 2, LUA_TFUNCTION);
    uint32_t id = atalaia_node_add_timer(n, L, 2, ms, ms);
    if (id == 0) {
        return luaL_error(L, "every: too many timers (at most %d)", ATALAIA_NODE_MAX_TIMERS);
    }
    lua_pushinteger(L, (lua_Integer)id);
    return 1;
}

static int l_after(lua_State *L)
{
    atalaia_node_t *n = atalaia_node_from_lua(L);
    uint32_t ms = check_seconds(L, 1, 0);
    luaL_checktype(L, 2, LUA_TFUNCTION);
    uint32_t id = atalaia_node_add_timer(n, L, 2, ms, 0);
    if (id == 0) {
        return luaL_error(L, "after: too many timers (at most %d)", ATALAIA_NODE_MAX_TIMERS);
    }
    lua_pushinteger(L, (lua_Integer)id);
    return 1;
}

static int l_cancel(lua_State *L)
{
    atalaia_node_t *n = atalaia_node_from_lua(L);
    lua_Integer id = luaL_checkinteger(L, 1);
    if (id > 0 && id <= (lua_Integer)UINT32_MAX) {
        atalaia_node_cancel_timer(n, L, (uint32_t)id);
    }
    return 0;
}

/* ---- game ---------------------------------------------------------------- */

static int l_game_time(lua_State *L)
{
    atalaia_node_t *n = atalaia_node_from_lua(L);
    lua_pushnumber(L, (lua_Number)n->now_ms / 1000.0);
    return 1;
}

static int l_game_start(lua_State *L)
{
    emit_event(L, atalaia_node_from_lua(L), "game.start", 0,
               ATALAIA_PRIO_CRITICAL, "game.start");
    return 0;
}

static int l_game_finish(lua_State *L)
{
    const char *reason = luaL_optstring(L, 1, "finished");
    lua_createtable(L, 0, 1);
    lua_pushstring(L, reason);
    lua_setfield(L, -2, "reason");
    emit_event(L, atalaia_node_from_lua(L), "game.end", -1,
               ATALAIA_PRIO_CRITICAL, "game.finish");
    return 0;
}

static int l_game_win(lua_State *L)
{
    atalaia_node_t *n = atalaia_node_from_lua(L);
    check_team(L, n, 1, "game.win");
    lua_createtable(L, 0, 2);
    lua_pushliteral(L, "win");
    lua_setfield(L, -2, "reason");
    lua_pushvalue(L, 1);
    lua_setfield(L, -2, "winner");
    emit_event(L, n, "game.end", -1, ATALAIA_PRIO_CRITICAL, "game.win");
    return 0;
}

/* ---- score --------------------------------------------------------------- */

static int l_score_add(lua_State *L)
{
    atalaia_node_t *n = atalaia_node_from_lua(L);
    uint8_t team = check_team(L, n, 1, "score.add");
    lua_Integer amount = luaL_checkinteger(L, 2);
    luaL_argcheck(L, amount >= INT32_MIN && amount <= INT32_MAX, 2, "out of range");
    const char *reason = luaL_optstring(L, 3, "");
    if (n->status != ATALAIA_NODE_RUNNING || amount == 0) {
        return 0; /* scores are frozen once the game has ended */
    }
    atalaia_score_add(&n->score, team, (int32_t)amount);

    /* Gains travel in STATE snapshots as counters. Penalties are explicit
     * events so the GM sees them. */
    if (amount < 0) {
        lua_createtable(L, 0, 4);
        lua_pushvalue(L, 1);
        lua_setfield(L, -2, "team");
        lua_pushinteger(L, amount);
        lua_setfield(L, -2, "amount");
        lua_pushstring(L, reason);
        lua_setfield(L, -2, "reason");
        if (!lua_isnoneornil(L, 4)) {
            lua_pushvalue(L, 4);
            lua_setfield(L, -2, "squad");
        }
        emit_event(L, n, "score.delta", -1, ATALAIA_PRIO_NORMAL, "score.add");
    }
    return 0;
}

static int l_score_get(lua_State *L)
{
    atalaia_node_t *n = atalaia_node_from_lua(L);
    uint8_t team = check_team(L, n, 1, "score.get");
    lua_pushinteger(L, (lua_Integer)atalaia_score_net(&n->score, team));
    return 1;
}

/* ---- state --------------------------------------------------------------- */

static int l_state_node(lua_State *L)
{
    bool has_defaults = !lua_isnoneornil(L, 1);
    if (has_defaults) {
        luaL_checktype(L, 1, LUA_TTABLE);
    }
    if (lua_getfield(L, LUA_REGISTRYINDEX, REG_STATE) != LUA_TTABLE) {
        lua_pop(L, 1);
        lua_newtable(L);
        lua_pushvalue(L, -1);
        lua_setfield(L, LUA_REGISTRYINDEX, REG_STATE);
    }
    int state = lua_gettop(L);
    if (has_defaults) {
        lua_pushnil(L);
        while (lua_next(L, 1)) {
            lua_pushvalue(L, -2);
            int existing = lua_rawget(L, state);
            lua_pop(L, 1);
            if (existing == LUA_TNIL) {
                lua_pushvalue(L, -2);
                lua_pushvalue(L, -2);
                lua_rawset(L, state);
            }
            lua_pop(L, 1);
        }
    }
    return 1;
}

static int l_state_field(lua_State *L)
{
    return luaL_error(L, "state.field is not available yet: it arrives with "
                         "the field controller (phase 2)");
}

/* ---- Utilities ----------------------------------------------------------- */

static int l_rand(lua_State *L)
{
    atalaia_node_t *n = atalaia_node_from_lua(L);
    int top = lua_gettop(L);
    if (top == 0) {
        lua_pushnumber(L, (lua_Number)atalaia_rand_unit(&n->rng));
        return 1;
    }
    lua_Integer lo = 1;
    lua_Integer hi;
    if (top == 1) {
        hi = luaL_checkinteger(L, 1);
    } else {
        lo = luaL_checkinteger(L, 1);
        hi = luaL_checkinteger(L, 2);
    }
    luaL_argcheck(L, lo <= hi, top, "interval is empty");
    lua_Unsigned span = (lua_Unsigned)hi - (lua_Unsigned)lo;
    luaL_argcheck(L, span < UINT32_MAX, top, "interval is too large");
    uint32_t offset = atalaia_rand_below(&n->rng, (uint32_t)span + 1u);
    lua_pushinteger(L, (lua_Integer)((lua_Unsigned)lo + offset));
    return 1;
}

static int l_log(lua_State *L)
{
    int top = lua_gettop(L);
    for (int i = 1; i <= top; i++) {
        luaL_tolstring(L, i, NULL);
        if (i < top) {
            lua_pushliteral(L, " ");
        }
    }
    if (top == 0) {
        lua_pushliteral(L, "");
    } else {
        lua_concat(L, 2 * top - 1);
    }
    atalaia_node_log(atalaia_node_from_lua(L), lua_tostring(L, -1));
    return 0;
}

/* ---- Hardware: cap(id), ui and audio -------------------------------------
 * A proxy turns any method call into a command for the host, so the core
 * needs no change when a new capability type is added. Both cap("ring"):fill()
 * and ui.screen() work: the proxy itself is dropped from the arguments.
 */

static int forward_call(lua_State *L)
{
    atalaia_node_t *n = atalaia_node_from_lua(L);
    int top = lua_gettop(L);
    int first = (top >= 1 && lua_rawequal(L, 1, lua_upvalueindex(3))) ? 2 : 1;
    if (first > top) {
        lua_pushliteral(L, "[]");
    } else {
        lua_createtable(L, top - first + 1, 0);
        for (int i = first; i <= top; i++) {
            lua_pushvalue(L, i);
            lua_rawseti(L, -2, i - first + 1);
        }
        atalaia_json_push_encoded(L, -1);
    }
    atalaia_node_command(n, lua_tostring(L, lua_upvalueindex(1)),
                         lua_tostring(L, lua_upvalueindex(2)), lua_tostring(L, -1));
    return 0;
}

static int proxy_index(lua_State *L)
{
    luaL_checkstring(L, 2);
    lua_pushvalue(L, lua_upvalueindex(1)); /* target */
    lua_pushvalue(L, 2);                   /* method */
    lua_pushvalue(L, 1);                   /* the proxy, to recognise self */
    lua_pushcclosure(L, forward_call, 3);
    lua_pushvalue(L, 2);
    lua_pushvalue(L, -2);
    lua_rawset(L, 1); /* cache for the next call */
    return 1;
}

static void push_proxy(lua_State *L, int target_idx)
{
    target_idx = lua_absindex(L, target_idx);
    lua_newtable(L);
    lua_createtable(L, 0, 1);
    lua_pushvalue(L, target_idx);
    lua_pushcclosure(L, proxy_index, 1);
    lua_setfield(L, -2, "__index");
    lua_setmetatable(L, -2);
}

static int l_cap(lua_State *L)
{
    luaL_checkstring(L, 1);
    lua_getfield(L, LUA_REGISTRYINDEX, REG_CAPS);
    lua_pushvalue(L, 1);
    if (lua_rawget(L, -2) == LUA_TTABLE) {
        return 1;
    }
    lua_pop(L, 1);
    push_proxy(L, 1);
    lua_pushvalue(L, 1);
    lua_pushvalue(L, -2);
    lua_rawset(L, -4);
    return 1;
}

/* ---- Registration -------------------------------------------------------- */

static void set_lib(lua_State *L, const char *name, const luaL_Reg *fns)
{
    lua_newtable(L);
    luaL_setfuncs(L, fns, 0);
    lua_setfield(L, -2, name);
}

int atalaia_script_api_open(lua_State *L)
{
    static const luaL_Reg globals[] = {
        {"on", l_on},       {"emit", l_emit},   {"every", l_every},
        {"after", l_after}, {"cancel", l_cancel}, {"rand", l_rand},
        {"log", l_log},     {"print", l_log},   {"cap", l_cap},
        {NULL, NULL},
    };
    static const luaL_Reg game[] = {
        {"time", l_game_time},     {"start", l_game_start},
        {"finish", l_game_finish}, {"win", l_game_win},
        {NULL, NULL},
    };
    static const luaL_Reg score[] = {
        {"add", l_score_add}, {"get", l_score_get}, {NULL, NULL},
    };
    static const luaL_Reg state[] = {
        {"node", l_state_node}, {"field", l_state_field}, {NULL, NULL},
    };

    lua_pushglobaltable(L);
    luaL_setfuncs(L, globals, 0);
    set_lib(L, "game", game);
    set_lib(L, "score", score);
    set_lib(L, "state", state);

    lua_pushliteral(L, "ui");
    push_proxy(L, -1);
    lua_setfield(L, -3, "ui");
    lua_pop(L, 1);
    lua_pushliteral(L, "audio");
    push_proxy(L, -1);
    lua_setfield(L, -3, "audio");
    lua_pop(L, 1);

    lua_newtable(L);
    lua_setfield(L, -2, "params");
    lua_pop(L, 1);
    return 0;
}
