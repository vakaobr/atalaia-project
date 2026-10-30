/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The Lua sandbox: a memory-capped allocator, an instruction-count
 * watchdog, and only the safe standard libraries (no io, os, package,
 * debug, load or bytecode); setmetatable without __gc and an xpcall whose
 * handler runs with the watchdog on. core/tests/test_sandbox_escape.c is the
 * battery every change here must pass (phase 5 plan phase 5).
 *
 * String work inside C library functions is metered too (decision SR-41,
 * review finding FLD-8): the vendored lstrlib.c calls the instruction hook by
 * hand while it matches a pattern (find, match, gmatch, gsub), so a hostile
 * pattern spends the same budget as a loop and ends in "instruction limit
 * exceeded"; string.rep refuses a result over STRING_REP_MAX bytes and an
 * empty result of any count (safe_rep). Other C functions are bounded by the
 * memory cap.
 */
#include <stdint.h>
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

/*
 * Lua runs two kinds of script code with debug hooks switched off, where the
 * instruction watchdog cannot stop it (found by the sandbox-escape battery,
 * core/tests/test_sandbox_escape.c, decision P5C-15):
 *
 * - __gc metamethods (lgc.c GCTM: "stop debug hooks during GC metamethod"),
 *   so setmetatable() refuses a metatable with a __gc field. Lua marks a table
 *   for finalization only when its metatable has __gc at that moment, so a
 *   __gc added later is never called. Scripts cannot make userdata.
 * - xpcall()'s message handler when the error came from the watchdog itself
 *   (the hook raises it while hooks are off, and Lua calls the handler right
 *   there), so xpcall() is replaced by one that calls the handler after the
 *   protected call has unwound, with the watchdog on. Unlike Lua's, it cannot
 *   yield across the call; the handler sees the error but no traceback (the
 *   debug library is not there anyway).
 */
static int safe_setmetatable(lua_State *L)
{
    if (lua_type(L, 2) == LUA_TTABLE) {
        lua_pushliteral(L, "__gc");
        if (lua_rawget(L, 2) != LUA_TNIL) {
            return luaL_error(L, "setmetatable: __gc metamethods are not allowed in the sandbox");
        }
        lua_pop(L, 1);
    }
    lua_pushvalue(L, lua_upvalueindex(1)); /* the standard setmetatable */
    lua_insert(L, 1);
    lua_call(L, lua_gettop(L) - 1, 1);
    return 1;
}

static int safe_xpcall(lua_State *L)
{
    int args = lua_gettop(L) - 2;
    luaL_checktype(L, 2, LUA_TFUNCTION);
    luaL_checkany(L, 1);
    lua_pushboolean(L, 1); /* the first result if all goes well */
    lua_pushvalue(L, 1);
    lua_rotate(L, 3, 2); /* f, handler, true, f, args... */
    if (lua_pcall(L, args, LUA_MULTRET, 0) == LUA_OK) {
        return lua_gettop(L) - 2;
    }
    /* f, handler, true, error: the handler runs now, as any script code. */
    lua_pushvalue(L, 2);
    lua_insert(L, -2);
    lua_call(L, 1, 1);
    lua_pushboolean(L, 0);
    lua_insert(L, -2);
    return 2;
}

/* The longest string.rep result: a box has 64 to 256 KB for everything. */
#define STRING_REP_MAX 32768u

/*
 * string.rep(s, n [, sep]): Lua's loops n times even when s and sep are empty (a hang no
 * instruction hook sees) and only fails on memory afterwards, so the size is checked first.
 */
static int safe_rep(lua_State *L)
{
    size_t l, lsep;
    (void)luaL_checklstring(L, 1, &l);
    lua_Integer n = luaL_checkinteger(L, 2);
    (void)luaL_optlstring(L, 3, "", &lsep);
    if (n <= 0 || l + lsep == 0) {
        lua_pushliteral(L, "");
        return 1;
    }
    if ((uint64_t)n > STRING_REP_MAX ||
        (uint64_t)n * (l + lsep) > (uint64_t)STRING_REP_MAX + lsep) {
        return luaL_error(L, "string.rep: resulting string too large (over %d bytes)",
                          (int)STRING_REP_MAX);
    }
    lua_pushvalue(L, lua_upvalueindex(1)); /* the standard rep */
    lua_insert(L, 1);
    lua_call(L, lua_gettop(L) - 1, 1);
    return 1;
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

    /* No script code where the watchdog cannot reach (see safe_setmetatable). */
    lua_getglobal(L, "setmetatable");
    lua_pushcclosure(L, safe_setmetatable, 1);
    lua_setglobal(L, "setmetatable");
    lua_pushcfunction(L, safe_xpcall);
    lua_setglobal(L, "xpcall");

    lua_getglobal(L, LUA_STRLIBNAME);
    lua_getfield(L, -1, "rep");
    lua_pushcclosure(L, safe_rep, 1);
    lua_setfield(L, -2, "rep");
    lua_pop(L, 1);

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
