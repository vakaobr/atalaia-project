/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The Lua sandbox: a memory-capped allocator, an instruction-count
 * watchdog, and only the safe standard libraries (no io, os, package,
 * debug, load or bytecode).
 *
 * Known limit: time spent inside C library functions (for example a slow
 * string pattern) is not counted by the instruction hook.
 */
#include <stdlib.h>

#include "lauxlib.h"
#include "lualib.h"
#include "node_internal.h"

/* The watchdog checks the instruction budget every this many instructions. */
#define HOOK_STEP 1000

atalaia_node_t *atalaia_node_from_lua(lua_State *L)
{
    void *ud = NULL;
    lua_getallocf(L, &ud);
    return (atalaia_node_t *)ud;
}

static void *limited_alloc(void *ud, void *ptr, size_t osize, size_t nsize)
{
    atalaia_node_t *n = (atalaia_node_t *)ud;
    size_t old = ptr != NULL ? osize : 0; /* osize is a type tag when ptr is NULL */

    if (nsize == 0) {
        if (ptr != NULL) {
            n->cfg.alloc(n->cfg.alloc_ud, ptr, old, 0);
            n->mem_used -= old;
        }
        return NULL;
    }
    /* Lua requires shrinking to succeed, so only growth is checked. */
    if (nsize > old && n->mem_used - old + nsize > n->cfg.mem_limit) {
        return NULL;
    }
    void *p = n->cfg.alloc(n->cfg.alloc_ud, ptr, old, nsize);
    if (p != NULL) {
        n->mem_used = n->mem_used - old + nsize;
    }
    return p;
}

static void count_hook(lua_State *L, lua_Debug *ar)
{
    (void)ar;
    atalaia_node_t *n = atalaia_node_from_lua(L);
    n->instr_used += HOOK_STEP;
    if (n->watchdog_tripped || n->instr_used > n->cfg.instr_limit) {
        /* Fail on every instruction from now on, so a script cannot keep
         * running by catching the error with pcall. */
        n->watchdog_tripped = true;
        lua_sethook(L, count_hook, LUA_MASKCOUNT, 1);
        luaL_error(L, "instruction limit exceeded");
    }
}

static int panic(lua_State *L)
{
    (void)L;
    /* Only reachable through a bug in the runtime: every call into Lua is
     * protected. There is no safe way to continue. */
    abort();
}

static void remove_field(lua_State *L, const char *table, const char *field)
{
    if (table == NULL) {
        lua_pushglobaltable(L);
    } else {
        lua_getglobal(L, table);
    }
    lua_pushnil(L);
    lua_setfield(L, -2, field);
    lua_pop(L, 1);
}

static int init_state(lua_State *L)
{
    static const luaL_Reg libs[] = {
        {LUA_GNAME, luaopen_base},
        {LUA_COLIBNAME, luaopen_coroutine},
        {LUA_TABLIBNAME, luaopen_table},
        {LUA_STRLIBNAME, luaopen_string},
        {LUA_MATHLIBNAME, luaopen_math},
        {LUA_UTF8LIBNAME, luaopen_utf8},
        {NULL, NULL},
    };
    for (const luaL_Reg *lib = libs; lib->func != NULL; lib++) {
        luaL_requiref(L, lib->name, lib->func, 1);
        lua_pop(L, 1);
    }

    /* Loading code, touching the collector, printing to stdout and
     * unseeded randomness are not allowed. print and rand are replaced by
     * the script API. */
    static const char *const base_removed[] = {
        "dofile", "loadfile", "load", "collectgarbage", "print", "warn", NULL,
    };
    for (const char *const *name = base_removed; *name != NULL; name++) {
        remove_field(L, NULL, *name);
    }
    remove_field(L, LUA_STRLIBNAME, "dump");
    remove_field(L, LUA_MATHLIBNAME, "random");
    remove_field(L, LUA_MATHLIBNAME, "randomseed");

    static const char *const registry_tables[] = {
        REG_HANDLERS,
        REG_QUEUE,
        REG_CAPS,
        NULL,
    };
    for (const char *const *key = registry_tables; *key != NULL; key++) {
        lua_newtable(L);
        lua_setfield(L, LUA_REGISTRYINDEX, *key);
    }

    return atalaia_script_api_open(L);
}

lua_State *atalaia_sandbox_open(atalaia_node_t *node)
{
    lua_State *L = lua_newstate(limited_alloc, node);
    if (L == NULL) {
        return NULL;
    }
    lua_atpanic(L, panic);
    lua_pushcfunction(L, init_state);
    if (lua_pcall(L, 0, 0, 0) != LUA_OK) {
        lua_close(L);
        return NULL;
    }
    lua_sethook(L, count_hook, LUA_MASKCOUNT, HOOK_STEP);
    return L;
}
