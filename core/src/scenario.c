/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The scenario compiler's entry points (atalaia/scenario.h): a Lua state of
 * its own per call, with a memory limit and an instruction limit, running the
 * Lua sources the build embedded from core/scenario/ (scenario_sources.h,
 * written by core/cmake/embed_scenario.cmake). The sources are the program;
 * the manifest's data tree is only ever read as data (scenario/tree.lua).
 */
#include "atalaia/scenario.h"

#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "atalaia/protocol.h"
#include "lauxlib.h"
#include "lua.h"
#include "lualib.h"
#include "scenario_internal.h"
#include "scenario_sources.h"

/* The watchdog counts instructions in steps of this many. */
#define HOOK_STEP 1000

typedef struct {
    size_t used;
    size_t peak;
    size_t limit;
    uint64_t instructions;
    uint64_t instr_limit;
    bool tripped;       /* the instruction limit was passed */
    bool out_of_memory; /* an allocation was refused */
} budget_t;

static void *limited_alloc(void *ud, void *ptr, size_t osize, size_t nsize)
{
    budget_t *b = (budget_t *)ud;
    size_t old = ptr != NULL ? osize : 0; /* osize is a type tag when ptr is NULL */

    if (nsize == 0) {
        free(ptr);
        b->used -= old;
        return NULL;
    }
    /* Lua requires shrinking to succeed, so only growth is checked. */
    if (nsize > old && b->used - old + nsize > b->limit) {
        b->out_of_memory = true;
        return NULL;
    }
    void *p = realloc(ptr, nsize);
    if (p == NULL) {
        b->out_of_memory = nsize > old;
        return NULL;
    }
    b->used = b->used - old + nsize;
    if (b->used > b->peak) {
        b->peak = b->used;
    }
    return p;
}

static budget_t *budget(lua_State *L)
{
    void *ud = NULL;
    lua_getallocf(L, &ud);
    return (budget_t *)ud;
}

static void count_hook(lua_State *L, lua_Debug *ar)
{
    (void)ar;
    budget_t *b = budget(L);
    b->instructions += HOOK_STEP;
    if (b->tripped || b->instructions > b->instr_limit) {
        /* Fail on every instruction from now on, so that no pcall goes on. */
        b->tripped = true;
        lua_sethook(L, count_hook, LUA_MASKCOUNT, 1);
        luaL_error(L, "instruction limit exceeded");
    }
}

/* -- What the Lua sources see besides the standard libraries -- */

static const atalaia_scenario_source_t *find_source(const char *name)
{
    for (size_t i = 0; i < atalaia_scenario_source_count; i++) {
        if (strcmp(atalaia_scenario_sources[i].name, name) == 0) {
            return &atalaia_scenario_sources[i];
        }
    }
    return NULL;
}

/* need(name): the module core/scenario/<name>.lua returns, run once. */
static int need(lua_State *L)
{
    const char *name = luaL_checkstring(L, 1);
    lua_getfield(L, LUA_REGISTRYINDEX, "atalaia.scenario.modules");
    if (lua_getfield(L, -1, name) != LUA_TNIL) {
        return 1;
    }
    lua_pop(L, 1);
    const atalaia_scenario_source_t *src = find_source(name);
    if (src == NULL || strcmp(name, "runtime") == 0) {
        return luaL_error(L, "no scenario module %s", name);
    }
    lua_pushfstring(L, "=scenario/%s.lua", name);
    if (luaL_loadbufferx(L, src->text, src->len, lua_tostring(L, -1), "t") != LUA_OK) {
        return lua_error(L);
    }
    lua_call(L, 0, 1);
    lua_pushvalue(L, -1);
    lua_setfield(L, -4, name); /* modules[name] */
    return 1;
}

/* PROTOCOL.event(name): the standard event's id and default priority, or nil. */
static int protocol_event(lua_State *L)
{
    const atalaia_event_def_t *def = atalaia_event_def(luaL_checkstring(L, 1));
    if (def == NULL) {
        lua_pushnil(L);
        lua_pushinteger(L, ATALAIA_PRIO_NORMAL);
        return 2;
    }
    lua_pushinteger(L, def->id);
    lua_pushinteger(L, def->prio);
    return 2;
}

/* PROTOCOL.data_key(name): the standard data field's key, or nil. */
static int protocol_data_key(lua_State *L)
{
    size_t len = 0;
    const char *name = luaL_checklstring(L, 1, &len);
    const atalaia_data_field_def_t *def = atalaia_data_field(name, len);
    if (def == NULL) {
        lua_pushnil(L);
    } else {
        lua_pushinteger(L, def->key);
    }
    return 1;
}

/* The protected part of a call: libraries, globals, then main.run. */
static int entry(lua_State *L)
{
    const char *op = (const char *)lua_touserdata(L, 1);
    const char *text = (const char *)lua_touserdata(L, 2);
    size_t len = (size_t)lua_tointeger(L, 3);
    lua_settop(L, 0);

    static const luaL_Reg libs[] = {
        {LUA_GNAME, luaopen_base},       {LUA_STRLIBNAME, luaopen_string},
        {LUA_TABLIBNAME, luaopen_table}, {LUA_MATHLIBNAME, luaopen_math},
        {LUA_UTF8LIBNAME, luaopen_utf8},
    };
    for (size_t i = 0; i < sizeof(libs) / sizeof(libs[0]); i++) {
        luaL_requiref(L, libs[i].name, libs[i].func, 1);
        lua_pop(L, 1);
    }
    /* No loading of other code, from text or files. */
    static const char *const removed[] = {"dofile", "loadfile", "load", "require",
                                          "collectgarbage"};
    for (size_t i = 0; i < sizeof(removed) / sizeof(removed[0]); i++) {
        lua_pushnil(L);
        lua_setglobal(L, removed[i]);
    }
    lua_newtable(L);
    lua_setfield(L, LUA_REGISTRYINDEX, "atalaia.scenario.modules");
    lua_pushcfunction(L, need);
    lua_setglobal(L, "need");

    lua_createtable(L, 0, 3);
    lua_pushcfunction(L, protocol_event);
    lua_setfield(L, -2, "event");
    lua_pushcfunction(L, protocol_data_key);
    lua_setfield(L, -2, "data_key");
    lua_pushinteger(L, ATALAIA_PRIO_CRITICAL);
    lua_setfield(L, -2, "CRITICAL");
    lua_setglobal(L, "PROTOCOL");

    lua_pushcfunction(L, need);
    lua_pushliteral(L, "main");
    lua_call(L, 1, 1);
    lua_getfield(L, -1, "run");
    lua_pushstring(L, op);
    lua_pushlstring(L, text, len);
    const atalaia_scenario_source_t *runtime = find_source("runtime");
    lua_pushlstring(L, runtime->text, runtime->len);
    lua_call(L, 3, 1);
    return 1;
}

static char *copy_answer(const char *text, size_t len, size_t *out_len)
{
    char *out = malloc(len + 1);
    if (out == NULL) {
        return NULL;
    }
    memcpy(out, text, len);
    out[len] = '\0';
    if (out_len != NULL) {
        *out_len = len;
    }
    return out;
}

static const char TOO_COMPLEX[] =
    "{\"ok\":false,\"problems\":[{\"path\":\"\",\"code\":\"too_complex\",\"message\":\"the "
    "manifest is "
    "too large or too complex to check: it needs more memory or time than the compiler may take\","
    "\"level\":\"error\"}]}";

/* What Lua said when the compiler itself failed (a bug, or a tree that is not one), as JSON. */
static char *error_answer(const char *why, size_t *out_len)
{
    size_t n = strlen(why);
    char *buf = malloc(n * 6 + 16);
    if (buf == NULL) {
        return NULL;
    }
    size_t k = 0;
    memcpy(buf, "{\"error\":\"", 10);
    k = 10;
    for (size_t i = 0; i < n; i++) {
        unsigned char c = (unsigned char)why[i];
        if (c == '"' || c == '\\') {
            buf[k++] = '\\';
            buf[k++] = (char)c;
        } else if (c < 0x20) {
            static const char hex[] = "0123456789abcdef";
            memcpy(buf + k, "\\u00", 4);
            buf[k + 4] = hex[c >> 4];
            buf[k + 5] = hex[c & 15];
            k += 6;
        } else {
            buf[k++] = (char)c;
        }
    }
    memcpy(buf + k, "\"}", 2);
    k += 2;
    char *answer = copy_answer(buf, k, out_len);
    free(buf);
    return answer;
}

char *atalaia_scenario_run_limited(const char *op, const char *tree, size_t len, size_t *out_len,
                                   size_t mem_limit, uint64_t instr_limit,
                                   atalaia_scenario_usage_t *usage)
{
    if (out_len != NULL) {
        *out_len = 0;
    }
    if (tree == NULL) {
        tree = "";
        len = 0;
    }
    budget_t b = {0, 0, mem_limit, 0, instr_limit, false, false};
    char *answer;
    lua_State *L = lua_newstate(limited_alloc, &b);
    if (L == NULL) {
        answer = copy_answer(TOO_COMPLEX, sizeof(TOO_COMPLEX) - 1, out_len);
    } else {
        lua_sethook(L, count_hook, LUA_MASKCOUNT, HOOK_STEP);
        lua_pushcfunction(L, entry);
        lua_pushlightuserdata(L, (void *)op);
        lua_pushlightuserdata(L, (void *)tree);
        lua_pushinteger(L, (lua_Integer)len);
        int status = lua_pcall(L, 3, 1, 0);
        if (status == LUA_OK && lua_type(L, -1) == LUA_TSTRING) {
            size_t n = 0;
            const char *text = lua_tolstring(L, -1, &n);
            answer = copy_answer(text, n, out_len);
        } else if (b.tripped || b.out_of_memory || status == LUA_ERRMEM) {
            answer = copy_answer(TOO_COMPLEX, sizeof(TOO_COMPLEX) - 1, out_len);
        } else {
            answer = error_answer(lua_type(L, -1) == LUA_TSTRING ? lua_tostring(L, -1)
                                                                 : "the compiler failed",
                                  out_len);
        }
        lua_close(L);
    }
    if (usage != NULL) {
        usage->mem_peak = b.peak;
        usage->instructions = b.instructions;
    }
    return answer;
}

static char *run(const char *op, const char *tree, size_t len, size_t *out_len)
{
    return atalaia_scenario_run_limited(op, tree, len, out_len, ATALAIA_SCENARIO_MEM_LIMIT,
                                        ATALAIA_SCENARIO_INSTR_LIMIT, NULL);
}

char *atalaia_scenario_check(const char *tree, size_t len, size_t *out_len)
{
    return run("check", tree, len, out_len);
}

char *atalaia_scenario_compile(const char *tree, size_t len, size_t *out_len)
{
    return run("compile", tree, len, out_len);
}

char *atalaia_scenario_literal(const char *tree, size_t len, size_t *out_len)
{
    return run("literal", tree, len, out_len);
}

void atalaia_scenario_free(char *answer)
{
    free(answer);
}
