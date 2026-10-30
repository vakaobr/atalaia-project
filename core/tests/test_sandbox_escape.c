/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The sandbox-escape battery (phase 5 plan phase 5, ADR-P5-8, decisions P5R-13
 * and P5C-14 to P5C-16): scripts that try to leave the Lua sandbox, to crash
 * the runtime or to run without limits, each run as a box's script (Reduced
 * tier, 64 KB, and Full, 256 KB) and as a field controller's script (with
 * field ops). For every case: no "escaped" line in the log, the runtime
 * survives (and is destroyed) without a crash, and the node ends in the state
 * the case expects. CI runs it under AddressSanitizer and UBSan (the
 * sanitizers job) and on its own (the sandbox-escape job), so a leak, an
 * out-of-bounds access or undefined behaviour anywhere on these paths fails
 * the build. A signed community mode (plan phase 13) runs inside exactly this
 * sandbox: the signature says who vouches for it, this battery what it
 * cannot do.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "atalaia/field_ops.h"
#include "atalaia/node.h"
#include "check.h"

int check_failures = 0;

#define LOG_LINES 32
#define LOG_TEXT  200

typedef struct {
    int logs;
    char log[LOG_LINES][LOG_TEXT];
    int events;
    int script_errors;
    int sends;
} record_t;

static void on_event(void *user, const atalaia_event_t *ev, const char *data)
{
    record_t *r = user;
    (void)data;
    r->events++;
    if (strcmp(ev->type, "script.error") == 0) {
        r->script_errors++;
    }
}

static void on_command(void *user, const char *target, const char *method, const char *args)
{
    (void)user;
    (void)target;
    (void)method;
    (void)args;
}

static void on_log(void *user, const char *message)
{
    record_t *r = user;
    if (r->logs < LOG_LINES) {
        snprintf(r->log[r->logs], LOG_TEXT, "%s", message);
    }
    r->logs++;
}

static void on_field_state(void *user, const char *key, const char *value)
{
    (void)user;
    (void)key;
    (void)value;
}

/* Field ops answering what a controller would, plus odd answers a host could give. */
static char *ops_nodes(void *user, const char *role)
{
    (void)user;
    const char *json =
        role != NULL && strcmp(role, "odd") == 0
            ? "[{\"id\":70000},{\"id\":-1},{\"id\":\"x\"},{\"role\":\"zone\"},{\"id\":1.5}]"
            : "[{\"id\":1,\"role\":\"zone\"},{\"id\":2,\"role\":\"zone\"}]";
    char *out = malloc(strlen(json) + 1);
    if (out != NULL) {
        memcpy(out, json, strlen(json) + 1);
    }
    return out;
}

static const char *ops_owner(void *user, uint16_t node_id)
{
    (void)user;
    return node_id == 1 ? "red" : NULL;
}

static bool ops_send(void *user, uint16_t node_id, const char *cmd, const char *params)
{
    record_t *r = user;
    (void)node_id;
    (void)cmd;
    (void)params;
    r->sends++;
    return true;
}

static const atalaia_field_ops_t FIELD_OPS = {ops_nodes, ops_owner, ops_send};

typedef enum {
    SAFE,   /* still running, and its "ok" line was logged: nothing reached */
    HALTED, /* stopped by the sandbox (instruction or memory limit) */
    ANY     /* an error or a halt, as long as nothing escapes or crashes */
} expect_t;

typedef struct {
    const char *name;
    const char *script; /* "go" is the input each case gets after loading */
    expect_t expect;
} escape_case_t;

/* Every name a Lua 5.1-5.4 script could reach the host through. */
#define REMOVED_NAMES                                                                              \
    "'io', 'os', 'require', 'package', 'debug', 'load', 'loadfile', 'dofile', 'loadstring', "      \
    "'collectgarbage', 'setfenv', 'getfenv', 'newproxy', 'module', 'warn', 'gcinfo'"

static const escape_case_t CASES[] = {
    /* ---- what is not there ---- */
    {"globals",
     "for _, name in ipairs({" REMOVED_NAMES "}) do\n"
     "  if _G[name] ~= nil or rawget(_G, name) ~= nil or _ENV[name] ~= nil then log('escaped ' .. "
     "name) end\n"
     "end\n"
     "on('go', function() log('ok') end)\n",
     SAFE},
    {"library_members",
     "if string.dump or math.random or math.randomseed or ('').dump or "
     "getmetatable('').__index.dump then\n"
     "  log('escaped')\n"
     "end\n"
     "for _, lib in ipairs({string, math, table, coroutine, utf8}) do\n"
     "  for k, v in pairs(lib) do\n"
     "    if k == 'dump' or k == 'random' or k == 'randomseed' or k == 'execute' then log('escaped "
     "' .. k) end\n"
     "  end\n"
     "end\n"
     "on('go', function() log('ok') end)\n",
     SAFE},
    {"loaders_by_other_names",
     /* Every function reachable from _G: none of them may load text or bytecode as code. */
     "local seen = {}\n"
     "local function walk(t, path)\n"
     "  if seen[t] then return end\n"
     "  seen[t] = true\n"
     "  for k, v in pairs(t) do\n"
     "    if type(v) == 'table' then walk(v, path .. '.' .. tostring(k))\n"
     "    elseif type(v) == 'function' then\n"
     "      local ok, f = pcall(v, 'return 4242')\n"
     "      if ok and type(f) == 'function' then\n"
     "        local ran, result = pcall(f)\n"
     "        if ran and result == 4242 then log('escaped ' .. path .. '.' .. tostring(k)) end\n"
     "      end\n"
     "    end\n"
     "  end\n"
     "end\n"
     "on('go', function() walk(_G, '_G') log('ok') end)\n",
     ANY},
    {"string_metatable",
     "local mt = getmetatable('')\n"
     "if mt.__index ~= string then log('escaped') end\n"
     "mt.__index = { upper = function() return 'mine' end }\n"
     "if ('x'):upper() ~= 'mine' then log('odd') end\n"
     "mt.__index = string\n"
     "on('go', function() log('ok') end)\n",
     SAFE},
    {"environment_swaps",
     "local _ENV = setmetatable({}, { __index = _G })\n"
     "if io or os or debug or require then log('escaped') end\n"
     "on('go', function() log('ok') end)\n",
     SAFE},

    /* ---- running without limits ---- */
    {"busy_loop", "on('go', function() while true do end end)\n", HALTED},
    {"tail_call_loop", "local function f() return f() end\non('go', function() f() end)\n", HALTED},
    {"loop_in_coroutine",
     "on('go', function() coroutine.wrap(function() while true do end end)() end)\n", HALTED},
    {"resume_loop",
     "on('go', function()\n"
     "  local co = coroutine.create(function() while true do end end)\n"
     "  while true do coroutine.resume(co) end\n"
     "end)\n",
     HALTED},
    {"pcall_watchdog",
     "on('go', function() for i = 1, 1e9 do pcall(function() while true do end end) end end)\n",
     HALTED},
    /* Lua calls xpcall's handler for the watchdog's own error with hooks off: the sandbox's
     * xpcall calls it after unwinding, with the watchdog on (decision P5C-15). */
    {"error_handler_loop",
     "on('go', function() xpcall(function() error('x') end, function() while true do end end) "
     "end)\n",
     HALTED},
    {"error_handler_after_watchdog",
     "on('go', function() xpcall(function() while true do end end, function() while true do end "
     "end) end)\n",
     HALTED},
    {"error_handler_recursion",
     "local h\nh = function() return select(2, xpcall(error, h)) end\n"
     "on('go', function() xpcall(error, h) end)\n",
     ANY},
    {"loop_in_tostring",
     "on('go', function() log(setmetatable({}, { __tostring = function() while true do end end })) "
     "end)\n",
     HALTED},
    {"loop_in_sort",
     "on('go', function() local t = {} for i = 1, 100 do t[i] = i end\n"
     "  table.sort(t, function(a, b) while true do end end) end)\n",
     HALTED},
    {"loop_in_gsub",
     "on('go', function() string.gsub(string.rep('a', 100), 'a', function() while true do end end) "
     "end)\n",
     HALTED},
    /* Lua runs __gc metamethods with hooks off, where the watchdog cannot stop them: the
     * sandbox refuses them (decision P5C-15), also when the metatable gets __gc later. */
    {"loop_in_finalizer",
     "local loop = function() while true do end end\n"
     "if pcall(setmetatable, {}, { __gc = loop }) then log('escaped __gc') end\n"
     "if pcall(setmetatable, {}, { __gc = false }) then log('escaped __gc false') end\n"
     "local mt = {}\n"
     "local late = setmetatable({}, mt)\n"
     "mt.__gc = loop\n"
     "late = nil\n"
     "local keep = {}\n"
     "on('go', function() for i = 1, 5000 do keep[i % 8] = { i } end log('ok') end)\n",
     SAFE},
    {"finalizer_at_close",
     "local mt = {}\nlocal t = setmetatable({}, mt)\nmt.__gc = function() while true do end end\n"
     "on('go', function() log('ok') end)\n",
     SAFE},
    {"close_variables",
     /* To-be-closed variables run their __close as the block is left, and while an error
      * unwinds: with the watchdog on either way. */
     "on('go', function()\n"
     "  local x <close> = setmetatable({}, { __close = function() while true do end end })\n"
     "end)\n"
     "on('x.club.two', function()\n"
     "  local y <close> = setmetatable({}, { __close = function() while true do end end })\n"
     "  while true do end\n"
     "end)\n",
     HALTED},
    {"safe_replacements",
     /* xpcall and setmetatable still work as scripts expect. */
     "on('go', function()\n"
     "  local ok, msg = xpcall(function(a) error('bad ' .. a, 0) end, function(m) return 'handled "
     "' .. m end, 'x')\n"
     "  local fine, a, b = xpcall(function(p, q) return p + q, 'two' end, print, 1, 2)\n"
     "  local t = setmetatable({}, { __index = function() return 7 end })\n"
     "  if ok == false and msg == 'handled bad x' and fine and a == 3 and b == 'two' and t.z == 7 "
     "then\n"
     "    log('ok')\n"
     "  end\n"
     "  if pcall(xpcall, print) then log('escaped') end\n"
     "end)\n",
     SAFE},
    /* string.rep refuses a result over 32 KB before it allocates (decision SR-41): an error the
     * script can catch, not a halt. */
    {"memory_string", "on('go', function() local s = string.rep('x', 100000000) end)\n", ANY},
    {"memory_table", "on('go', function() local t = {} for i = 1, 1e7 do t[i] = { i } end end)\n",
     HALTED},
    {"memory_coroutines",
     "on('go', function() local t = {} for i = 1, 1e6 do t[i] = coroutine.create(print) end end)\n",
     HALTED},
    {"memory_concat", "on('go', function() local s = 'x' for i = 1, 40 do s = s .. s end end)\n",
     HALTED},
    {"memory_handlers",
     "on('go', function() for i = 1, 1e6 do on('x.club.' .. i, function() end) end end)\n", HALTED},

    /* ---- string work in C functions: patterns and rep are metered (decision SR-41, FLD-8) ---- */
    {"rep_limits",
     "on('go', function()\n"
     "  local ok1, e1 = pcall(string.rep, 'x', 1e8)\n"
     "  local ok2 = pcall(string.rep, 'ab', 20000, 'cd')\n"
     "  local ok3, e3 = pcall(string.rep, 'x', math.maxinteger)\n"
     "  if not ok1 and e1:find('too large', 1, true) and not ok2 and not ok3 and\n"
     "     #string.rep('xy', 3, '-') == 8 and string.rep('ab', 3) == 'ababab' and\n"
     "     string.rep('x', 0) == '' and string.rep('x', -5) == '' and #string.rep('x', 20000) == "
     "20000 then\n"
     "    log('ok')\n"
     "  end\n"
     "end)\n",
     SAFE},
    {"rep_empty_forever",
     /* Lua loops once per repeat even when nothing is repeated: a hang without a hook. */
     "on('go', function()\n"
     "  if string.rep('', 1e18) == '' and string.rep('', 1e18, '') == '' then log('ok') end\n"
     "end)\n",
     SAFE},
    {"pattern_find_backtracking",
     "on('go', function() local s = string.rep('a', 2000) .. 'c'\n"
     "  string.find(s, '.-.-.-.-.-.-b') end)\n",
     HALTED},
    {"pattern_match_backtracking",
     "on('go', function() local s = string.rep('a', 3000)\n"
     "  string.match(s, '(.-)(.-)(.-)(.-)(.-)x') end)\n",
     HALTED},
    {"pattern_gsub_backtracking",
     "on('go', function() local s = string.rep('a', 3000)\n"
     "  string.gsub(s, 'a*a*a*a*a*b', 'x') end)\n",
     HALTED},
    {"pattern_gmatch_backtracking",
     "on('go', function() local s = string.rep('a', 3000)\n"
     "  for w in string.gmatch(s, '.-.-.-.-.-z') do end end)\n",
     HALTED},
    {"pattern_in_pcall_loop",
     "on('go', function() local s = string.rep('a', 3000)\n"
     "  for i = 1, 1e9 do pcall(string.find, s, '.-.-.-.-.-b') end end)\n",
     HALTED},
    {"plain_find_quadratic",
     /* Plain search is O(subject * pattern) when the first character keeps matching. */
     "on('go', function() local s = string.rep('a', 30000)\n"
     "  local big = s .. s .. s .. s\n"
     "  local p = string.rep('a', 30000) .. 'b'\n"
     "  for i = 1, 100 do string.find(big, p, 1, true) end end)\n",
     HALTED},
    {"patterns_still_work",
     "on('go', function()\n"
     "  local text = string.rep('key=value; ', 200)\n"
     "  local n = 0\n"
     "  for k, v in string.gmatch(text, '(%w+)=(%w+)') do n = n + 1 end\n"
     "  local r, c = string.gsub(text, '%s+', ' ')\n"
     "  if n == 200 and c == 200 and string.find('hello world', 'o w') == 5 and\n"
     "     string.match('2026-10-30', '(%d+)-(%d+)-(%d+)') == '2026' and\n"
     "     string.find(text, 'nope', 1, true) == nil and ('x'):rep(3) == 'xxx' then\n"
     "    log('ok')\n"
     "  end\n"
     "end)\n",
     SAFE},

    /* ---- crashing the runtime ---- */
    {"deep_recursion",
     "on('go', function() local function f(n) return 1 + f(n + 1) end f(1) end)\n"
     "every(1, function() log('alive') end)\n",
     ANY},
    {"c_stack", "on('go', function() local function f() pcall(f) end f() end)\n", ANY},
    {"c_stack_in_metamethods",
     "on('go', function()\n"
     "  local t = setmetatable({}, {})\n"
     "  getmetatable(t).__index = function(s, k) return s[k] end\n"
     "  return t.x\n"
     "end)\n",
     ANY},
    {"yield_outside",
     "on('go', function() coroutine.yield() end)\n"
     "every(1, function() coroutine.wrap(function() coroutine.yield(game.time()) end)() end)\n",
     ANY},
    {"yield_across_api",
     "on('go', function()\n"
     "  local co = coroutine.wrap(function()\n"
     "    emit('x.club.y', setmetatable({}, { __index = function() coroutine.yield() end }))\n"
     "    table.sort({3, 2, 1}, function(a, b) coroutine.yield() return a < b end)\n"
     "  end)\n"
     "  co()\n"
     "end)\n",
     ANY},
    {"error_objects",
     "on('go', function()\n"
     "  error(setmetatable({}, { __tostring = function() error('again') end }))\n"
     "end)\n"
     "on('x.club.two', function() error(setmetatable({}, { __tostring = function() while true do "
     "end end })) end)\n"
     "on('x.club.three', function() error(setmetatable({}, { __index = function() error('idx') end "
     "})) end)\n"
     "on('x.club.four', function() error() end)\n"
     "on('x.club.five', function() error(string.rep('e', 100000)) end)\n",
     ANY},
    {"emit_cycle", "local t = {} t.self = t\non('go', function() emit('x.club.cycle', t) end)\n",
     ANY},
    {"emit_deep",
     "on('go', function() local t = {} local c = t for i = 1, 100000 do c.x = {} c = c.x end\n"
     "  emit('x.club.deep', t) end)\n",
     ANY},
    {"emit_metamethods",
     "on('go', function()\n"
     "  local mm = { __index = function() error('boom') end, __pairs = function() error('boom') "
     "end,\n"
     "               __len = function() error('boom') end, __tostring = function() error('boom') "
     "end }\n"
     "  pcall(emit, 'x.club.mm', setmetatable({ a = 1 }, mm))\n"
     "  pcall(emit, 'x.club.mm', { k = setmetatable({}, mm) })\n"
     "  pcall(emit, 'x.club.mm', { [setmetatable({}, mm)] = 1 })\n"
     "  pcall(emit, 'x.club.mm', { [1.5] = 1, [true] = 2, [print] = 3 })\n"
     "  pcall(emit, 'x.club.mm', { f = print, c = coroutine.create(print) })\n"
     "  log('ok')\n"
     "end)\n",
     SAFE},
    {"api_data_cycles",
     "local t = {} t.self = t\n"
     "on('go', function()\n"
     "  pcall(ui.screen, 'x', t)\n"
     "  pcall(function() cap('team_display'):show(t) end)\n"
     "  pcall(function() cap('ring'):fill(t, t, t) end)\n"
     "  pcall(state.node, t)\n"
     "  log('ok')\n"
     "end)\n",
     SAFE},
    {"state_cycle",
     "local s = state.node { a = 1 }\n"
     "on('go', function() local t = {} t.t = t pcall(function() s.a = t end) s.b = function() end "
     "log('ok') end)\n",
     ANY},
    {"strings_with_nul",
     "on('go', function()\n"
     "  pcall(emit, 'x.club\\0evil')\n"
     "  pcall(emit, 'x.club.n', { ['k\\0'] = 'v\\0w' })\n"
     "  log('a\\0b')\n"
     "  pcall(ui.screen, 'a\\0b', { t = '\\0' })\n"
     "  pcall(audio.play, 'x\\0y')\n"
     "  pcall(on, 'a\\0b', print)\n"
     "  pcall(function() cap('a\\0b'):x('\\0') end)\n"
     "  pcall(score.add, 'red\\0', 1)\n"
     "  log('ok')\n"
     "end)\n",
     SAFE},
    {"long_strings",
     "on('go', function()\n"
     "  local long = string.rep('a', 20000)\n"
     "  pcall(emit, long)\n"
     "  pcall(emit, 'x.club.long', { v = long })\n"
     "  pcall(ui.screen, long, { v = long })\n"
     "  pcall(audio.play, long)\n"
     "  pcall(function() cap(long):show(long) end)\n"
     "  pcall(score.add, long, 1)\n"
     "  pcall(log, long)\n"
     "  log('ok')\n"
     "end)\n",
     SAFE},
    {"timers",
     "on('go', function()\n"
     "  for _, s in ipairs({0, -1, 0/0, 1/0, -1/0, 1e300, 2^53, math.mininteger, 0.0001}) do\n"
     "    pcall(every, s, print)\n"
     "    pcall(after, s, print)\n"
     "  end\n"
     "  pcall(cancel, 'x') pcall(cancel, -1) pcall(cancel, 1e300) pcall(cancel, 0/0)\n"
     "  for i = 1, 100 do pcall(every, 1, function() end) end\n"
     "  log('ok')\n"
     "end)\n",
     SAFE},
    {"numbers",
     "on('go', function()\n"
     "  local odd = {math.maxinteger, math.mininteger, 0/0, 1/0, -1/0, 1e308, -0.0, 2^63, -2^63}\n"
     "  for _, a in ipairs(odd) do\n"
     "    pcall(score.add, 'red', a) pcall(score.add, a, 1) pcall(score.get, a)\n"
     "    for _, b in ipairs(odd) do pcall(rand, a, b) end\n"
     "    pcall(geo.distance, a, a, a, a)\n"
     "    pcall(geo.in_zone, a, a, { type = 'circle', lat = a, lon = a, radius_m = a })\n"
     "    pcall(game.win, a) pcall(game.finish, a)\n"
     "    pcall(string.format, '%d', a) pcall(math.tointeger, a) pcall(utf8.char, a)\n"
     "    pcall(string.rep, 'x', a) pcall(table.unpack, {}, 1, a) pcall(table.move, {}, 1, a, 2)\n"
     "  end\n"
     "  score.add('red', math.maxinteger) score.add('red', math.maxinteger)\n"
     "  log('ok')\n"
     "end)\n",
     ANY},
    {"geo_shapes",
     "on('go', function()\n"
     "  local pts = {} for i = 1, 40 do pts[i] = {i % 90, i % 180} end\n"
     "  pcall(geo.in_zone, 1, 1, { type = 'polygon', points = pts })\n"
     "  pcall(geo.in_zone, 1, 1, { type = 'polygon', points = { {1}, {2}, {3} } })\n"
     "  pcall(geo.in_zone, 1, 1, { type = 'polygon', points = setmetatable({}, { __len = "
     "function() return 1e9 end }) })\n"
     "  pcall(geo.in_zone, 1, 1, setmetatable({}, { __index = function() error('x') end }))\n"
     "  pcall(geo.in_zone, 1, 1, { type = 'polygon', points = { 1, 2, 3 } })\n"
     "  log('ok')\n"
     "end)\n",
     SAFE},
    {"patterns_and_formats",
     "on('go', function()\n"
     "  pcall(string.find, 'aaaa', string.rep('(', 300))\n"
     "  pcall(string.find, 'aaaa', string.rep('%', 101))\n"
     "  pcall(string.format, '%' .. string.rep('9', 100) .. 'd', 1)\n"
     "  pcall(string.format, '%q', 0/0)\n"
     "  pcall(string.pack, 'i17', 1)\n"
     "  pcall(string.unpack, 'z', 'abc', 100)\n"
     "  pcall(utf8.codepoint, '\\xff\\xfe', 1, -1)\n"
     "  pcall(string.rep, 'ab', 1e9, 'cd')\n"
     "  log('ok')\n"
     "end)\n",
     SAFE},
    {"field_ops",
     /* Only a controller has field.*; on a box the calls fail and are caught. */
     "local t = {} t.self = t\n"
     "on('go', function()\n"
     "  if field then\n"
     "    pcall(field.send, 1, 'mode', t)\n"
     "    pcall(field.send, 1, string.rep('c', 10000), { v = string.rep('v', 10000) })\n"
     "    for _, id in ipairs({-1, 0, 65535, 65536, 1e300, 0/0, 'x', math.mininteger}) do\n"
     "      pcall(field.owner, id) pcall(field.send, id, 'set_owner', {})\n"
     "    end\n"
     "    pcall(field.nodes, string.rep('r', 5000))\n"
     "    pcall(field.nodes, 'odd')\n"
     "    pcall(field.common_owner, { 1, 2, 'x', 1e300, t })\n"
     "    pcall(field.common_owner, setmetatable({}, { __len = function() return 1e9 end }))\n"
     "    local fs = state.field { a = 1 }\n"
     "    pcall(function() fs.a = t end)\n"
     "  end\n"
     "  log('ok')\n"
     "end)\n",
     SAFE},
};

#define CASE_COUNT (sizeof(CASES) / sizeof(CASES[0]))

/* Runs one case; returns the node's status at the end. */
static atalaia_node_status_t run_case(const escape_case_t *c, size_t mem_limit, bool controller,
                                      record_t *r)
{
    memset(r, 0, sizeof(*r));
    atalaia_node_config_t cfg = {0};
    cfg.node_id = controller ? 0 : 3;
    cfg.game_seed = 7;
    cfg.mem_limit = mem_limit;
    cfg.instr_limit = 200000;
    cfg.callbacks.event = on_event;
    cfg.callbacks.command = on_command;
    cfg.callbacks.log = on_log;
    cfg.callbacks.field_state = on_field_state;
    cfg.callbacks.user = r;
    cfg.field_ops = controller ? &FIELD_OPS : NULL;
    atalaia_node_t *n = atalaia_node_create(&cfg);
    CHECK(n != NULL);
    if (n == NULL) {
        return ATALAIA_NODE_EMPTY;
    }
    static const char *const teams[] = {"red", "blue"};
    CHECK(atalaia_node_set_teams(n, teams, 2));
    CHECK(atalaia_node_set_params(n, "{\"tick_s\":10}"));
    char chunk[64];
    snprintf(chunk, sizeof(chunk), "=escape/%s", c->name);
    bool loaded = atalaia_node_load(n, c->script, strlen(c->script), chunk);
    if (loaded) {
        atalaia_node_advance(n, 1000);
        (void)atalaia_node_input(n, "go", NULL);
        for (const char *const *type = (const char *const[]){"x.club.two", "x.club.three",
                                                             "x.club.four", "x.club.five", NULL};
             *type != NULL; type++) {
            (void)atalaia_node_input(n, *type, NULL);
        }
        atalaia_node_advance(n, 5000);
        char state[4096];
        (void)atalaia_node_state_save(n, state, sizeof(state));
    }
    atalaia_node_status_t status = atalaia_node_status(n);
    atalaia_node_destroy(n); /* must return: finalizers run here too */
    return loaded ? status : ATALAIA_NODE_EMPTY;
}

static bool logged(const record_t *r, const char *prefix)
{
    for (int i = 0; i < r->logs && i < LOG_LINES; i++) {
        if (strncmp(r->log[i], prefix, strlen(prefix)) == 0) {
            return true;
        }
    }
    return false;
}

static void test_battery(void)
{
    static const size_t limits[] = {64u * 1024u, 256u * 1024u};
    for (size_t i = 0; i < CASE_COUNT; i++) {
        const escape_case_t *c = &CASES[i];
        for (size_t l = 0; l < sizeof(limits) / sizeof(limits[0]); l++) {
            for (int controller = 0; controller <= 1; controller++) {
                record_t r;
                clock_t start = clock();
                atalaia_node_status_t status = run_case(c, limits[l], controller != 0, &r);
                if (getenv("ATALAIA_ESCAPE_TIMES") != NULL) {
                    printf("%-24s %3zu KB %-10s %6.2f s %s\n", c->name, limits[l] / 1024u,
                           controller ? "controller" : "box",
                           (double)(clock() - start) / CLOCKS_PER_SEC,
                           atalaia_node_status_name(status));
                }
                bool escaped = logged(&r, "escaped");
                bool ok = !escaped;
                if (c->expect == SAFE) {
                    ok = ok && status == ATALAIA_NODE_RUNNING && logged(&r, "ok");
                } else if (c->expect == HALTED) {
                    ok = ok && status == ATALAIA_NODE_HALTED;
                }
                if (!ok) {
                    fprintf(stderr,
                            "sandbox escape case %s (%zu KB, %s): status %s, %d log lines%s%s\n",
                            c->name, limits[l] / 1024u, controller ? "controller" : "box",
                            atalaia_node_status_name(status), r.logs, r.logs ? ", first: " : "",
                            r.logs ? r.log[0] : "");
                }
                CHECK(ok);
            }
        }
    }
}

/* Bytecode never loads, wherever it hides. */
static void test_bytecode(void)
{
    static const struct {
        const char *source;
        size_t len;
    } chunks[] = {
        {"\x1bLua", 4},
        {"\x1bLuaT\x00\x19\x93\r\n\x1a\n", 15},
        {"#!/usr/bin/lua\n\x1bLua", 19},
        {"\xef\xbb\xbf\x1bLua", 7},
    };
    for (size_t i = 0; i < sizeof(chunks) / sizeof(chunks[0]); i++) {
        record_t r;
        memset(&r, 0, sizeof(r));
        atalaia_node_config_t cfg = {0};
        cfg.node_id = 3;
        cfg.callbacks.log = on_log;
        cfg.callbacks.event = on_event;
        cfg.callbacks.user = &r;
        atalaia_node_t *n = atalaia_node_create(&cfg);
        CHECK(n != NULL);
        CHECK(!atalaia_node_load(n, chunks[i].source, chunks[i].len, "=bytecode"));
        CHECK(atalaia_node_status(n) != ATALAIA_NODE_RUNNING);
        atalaia_node_destroy(n);
    }
}

/* A halted node stays halted: nothing it registered runs again. */
static void test_halt_is_final(void)
{
    record_t r;
    memset(&r, 0, sizeof(r));
    atalaia_node_config_t cfg = {0};
    cfg.node_id = 3;
    cfg.instr_limit = 100000;
    cfg.callbacks.log = on_log;
    cfg.callbacks.event = on_event;
    cfg.callbacks.user = &r;
    atalaia_node_t *n = atalaia_node_create(&cfg);
    CHECK(n != NULL);
    const char *src = "every(1, function() log('tick') end)\n"
                      "on('go', function() while true do end end)\n"
                      "on('again', function() log('again') end)\n";
    CHECK(atalaia_node_load(n, src, strlen(src), "=halt"));
    CHECK(atalaia_node_input(n, "go", NULL) == false ||
          atalaia_node_status(n) == ATALAIA_NODE_HALTED);
    CHECK(atalaia_node_status(n) == ATALAIA_NODE_HALTED);
    int before = r.logs;
    atalaia_node_advance(n, 10000);
    CHECK(!atalaia_node_input(n, "again", NULL));
    CHECK(r.logs == before);
    atalaia_node_destroy(n);
}

int main(void)
{
    setvbuf(stdout, NULL, _IONBF, 0); /* each case's line as it ends */
    test_battery();
    test_bytecode();
    test_halt_is_final();
    printf("sandbox escape battery: %zu cases x 2 memory limits x box and controller, %s\n",
           CASE_COUNT, check_failures ? "FAILED" : "all held");
    return check_failures == 0 ? 0 : 1;
}
