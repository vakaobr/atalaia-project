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

/*
 * Field ops answering what a controller would, plus odd answers a host could give. The host owns
 * the buffer it returns (the core frees it): "bad", "deep" and "big" make the decoder raise a
 * Lua error (a syntax error, nesting over the cap, the memory cap) while the core still holds it
 * (review finding LIVE2-S1: the error skipped the free; ASan/LSan sees the leak).
 */
static char *dup_text(const char *text, size_t len)
{
    char *out = malloc(len + 1);
    if (out != NULL) {
        memcpy(out, text, len);
        out[len] = '\0';
    }
    return out;
}

static char *ops_nodes(void *user, const char *role)
{
    (void)user;
    if (role != NULL && strcmp(role, "bad") == 0) {
        return dup_text("[{\"id\":1},{\"id\":", 17);
    }
    if (role != NULL && strcmp(role, "deep") == 0) {
        char deep[80];
        memset(deep, '[', 40);
        memset(deep + 40, ']', 40);
        return dup_text(deep, 80);
    }
    if (role != NULL && strcmp(role, "big") == 0) {
        size_t count = 60000;
        char *out = malloc(2 * count + 2);
        if (out == NULL) {
            return NULL;
        }
        out[0] = '[';
        for (size_t i = 0; i < count; i++) {
            out[1 + 2 * i] = '1';
            out[2 + 2 * i] = i + 1 < count ? ',' : ']';
        }
        out[2 * count + 1] = '\0';
        return out;
    }
    const char *json =
        role != NULL && strcmp(role, "odd") == 0
            ? "[{\"id\":70000},{\"id\":-1},{\"id\":\"x\"},{\"role\":\"zone\"},{\"id\":1.5}]"
            : "[{\"id\":1,\"role\":\"zone\"},{\"id\":2,\"role\":\"zone\"}]";
    return dup_text(json, strlen(json));
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
    /* ---- review 2026-10-30 (LIVE2-S1): the host's JSON buffer survives a decoder error ---- */
    {"field_nodes_decode_errors",
     /* On a controller each call raises while the core holds the host's buffer; the error is
      * caught here. A leak fails the ASan/LSan run, not the case's status. */
     "on('go', function()\n"
     "  if field then\n"
     "    for _, role in ipairs({'bad', 'deep', 'big'}) do\n"
     "      for i = 1, 3 do\n"
     "        if pcall(field.nodes, role) then log('escaped ' .. role .. ' decoded') end\n"
     "      end\n"
     "    end\n"
     "    if #field.nodes() ~= 2 then log('escaped ok-path') end\n"
     "  end\n"
     "  log('ok')\n"
     "end)\n",
     SAFE},

    /* ---- review 2026-10-30 (LIVE2-S2): table functions are metered like string ones ---- */
    {"table_move_huge", "on('go', function() local t = {1, 2, 3} table.move(t, 1, 1e9, 2) end)\n",
     HALTED},
    {"table_move_nothing_forever",
     /* No allocation and no VM instruction: a plain C loop for as long as the range. */
     "on('go', function() table.move({}, 1, math.maxinteger // 2, 1, {}) end)\n", HALTED},
    {"table_insert_front_loop",
     "on('go', function() local t = {} for i = 1, 3000 do t[i] = i end\n"
     "  for i = 1, 1e6 do table.insert(t, 1, i) end end)\n",
     HALTED},
    {"table_remove_front_loop",
     "on('go', function() local t = {} for i = 1, 3000 do t[i] = i end\n"
     "  for i = 1, 1e6 do table.insert(t, i) table.remove(t, 1) end end)\n",
     HALTED},
    {"table_insert_huge_length",
     "on('go', function()\n"
     "  local t = setmetatable({}, { __len = function() return 1e12 end })\n"
     "  table.insert(t, 1, 'x') end)\n",
     HALTED},
    {"table_unpack_loop",
     "on('go', function() local t = {} for i = 1, 4000 do t[i] = i end\n"
     "  for i = 1, 1e6 do select('#', table.unpack(t)) end end)\n",
     HALTED},
    {"table_concat_loop",
     "on('go', function() local t = {} for i = 1, 4000 do t[i] = 'ab' end\n"
     "  for i = 1, 1e6 do local s = table.concat(t, ',') end end)\n",
     HALTED},
    {"table_sort_loop",
     "on('go', function() local t = {} for i = 1, 4000 do t[i] = (i * 7919) % 4001 end\n"
     "  for i = 1, 1e6 do table.sort(t, function(a, b) return a > b end) table.sort(t) end end)\n",
     HALTED},
    {"table_sort_no_comparator_loop",
     "on('go', function() local t = {} for i = 1, 4000 do t[i] = (i * 7919) % 4001 end\n"
     "  for i = 1, 1e6 do table.sort(t) t[1], t[4000] = t[4000], t[1] end end)\n",
     HALTED},
    {"table_functions_still_work",
     "on('go', function()\n"
     "  local t = {5, 3, 8, 1}\n"
     "  table.insert(t, 9) table.insert(t, 1, 0)\n"
     "  local removed = table.remove(t, 2) table.remove(t)\n"
     "  local m = table.move(t, 1, 3, 2, {})\n"
     "  table.sort(t, function(a, b) return a > b end)\n"
     "  local big = {} for i = 1, 500 do big[i] = (i * 37) % 501 end\n"
     "  table.sort(big)\n"
     "  local sorted = true for i = 2, #big do if big[i - 1] > big[i] then sorted = false end end\n"
     "  local a, b, c = table.unpack({1, 2, 3})\n"
     "  if removed == 5 and #t == 4 and t[1] == 8 and t[4] == 0 and m[2] == 0 and m[4] == 8 and\n"
     "     table.concat({1, 2, 3}, '-') == '1-2-3' and a + b + c == 6 and sorted then\n"
     "    log('ok')\n"
     "  end\n"
     "end)\n",
     SAFE},

    /* ---- review 2026-10-30 (LIVE2-S3): the C stack is bounded at 20 levels (luaconf.h) ---- */
    {"nesting_pcall",
     "on('go', function() local function f() local ok, e = pcall(f) if not ok then error(e, 0) end "
     "end f() end)\n",
     ANY},
    {"nesting_gsub_callbacks",
     "on('go', function() local function f() return (string.gsub('a', 'a', f)) end f() end)\n",
     ANY},
    {"nesting_tostring_format",
     "on('go', function()\n"
     "  local t = setmetatable({}, { __tostring = function(s) return string.format('%s', s) end "
     "})\n"
     "  tostring(t) end)\n",
     ANY},
    {"nesting_concat_index",
     "on('go', function()\n"
     "  local t = setmetatable({}, { __index = function(s, i) return table.concat(s, ',', 1, 2) "
     "end "
     "})\n"
     "  table.concat(t, ',', 1, 2) end)\n",
     ANY},
    {"nesting_sort_comparators",
     "on('go', function()\n"
     "  local function f(a, b) table.sort({3, 2, 1}, f) return a < b end\n"
     "  table.sort({3, 2, 1}, f) end)\n",
     ANY},
    {"nesting_coroutines",
     "on('go', function() local function f() coroutine.wrap(f)() end f() end)\n", ANY},
    {"nesting_metamethods_mixed",
     "on('go', function()\n"
     "  local mt = {}\n"
     "  mt.__index = function(t, k) return pcall(string.gsub, 'a', 'a', function() return t[k] "
     "end) "
     "end\n"
     "  mt.__add = function(a, b) return a.x + b end\n"
     "  local t = setmetatable({}, mt)\n"
     "  local _ = t.x, t + 1 end)\n",
     ANY},
    {"nesting_legit",
     /* What a mode may do: a few levels of pcall, callbacks and metamethods all work. */
     "on('go', function()\n"
     "  local function down(n) if n == 0 then return 'ok' end local ok, v = pcall(down, n - 1) "
     "return v end\n"
     "  local t = setmetatable({}, { __index = function(_, k) return k * 2 end })\n"
     "  local s = string.gsub('abc', '%w', function(c) return pcall(string.upper, c) and c:upper() "
     "end)\n"
     "  if down(8) == 'ok' and t[21] == 42 and s == 'ABC' then log('ok') end\n"
     "end)\n",
     SAFE},

    /* ---- review 2026-10-30, low notes (decisions SR-137, SR-138) ---- */
    {"field_ids_do_not_wrap",
     /* A node id is 16 bits: 65537 used to be node 1. */
     "on('go', function()\n"
     "  if field then\n"
     "    if field.owner(65537) ~= nil or field.owner(-65535) ~= nil or field.owner(1) ~= 'red' "
     "or\n"
     "       field.send(65537, 'x', {}) ~= false or field.send(-1, 'x') ~= false or\n"
     "       field.common_owner({1, 65537}) ~= nil then\n"
     "      log('escaped id wrapped')\n"
     "    end\n"
     "  end\n"
     "  log('ok')\n"
     "end)\n",
     SAFE},
    {"field_send_is_rate_limited",
     "on('go', function()\n"
     "  if field then\n"
     "    local sent = 0\n"
     "    for i = 1, 1000 do if field.send(1, 'x') then sent = sent + 1 end end\n"
     "    if sent ~= 256 then log('escaped sent ' .. sent) end\n"
     "  end\n"
     "  log('ok')\n"
     "end)\n"
     "on('x.club.two', function()\n"
     "  if field and not field.send(1, 'x') then log('escaped no new budget') end\n"
     "end)\n",
     SAFE},
    {"emit_refuses_script_events",
     "on('go', function()\n"
     "  local a = pcall(emit, 'script.halted', { reason = 'fake' })\n"
     "  local b = pcall(emit, 'script.error', { message = 'fake' })\n"
     "  local c = pcall(emit, 'script.', {})\n"
     "  local d = pcall(emit, 'scripts.fine', {})\n"
     "  local e = pcall(emit, 'x.club.y', {})\n"
     "  if a or b or c or not d or not e then log('escaped emit ' .. tostring(a) .. tostring(b)) "
     "end\n"
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

/*
 * Coroutines are metered (review finding LIVE2-S5): each Lua thread counts its own instructions
 * towards its next hook call, so a script that makes a coroutine, runs a few hundred instructions
 * in it and drops it was charged for the loop around it only. The script below runs about 410
 * instructions inside each coroutine and about 20 in the loop; with instr_limit 200000 it ran
 * about 10,000 coroutines (4 million instructions, 20 times the limit) before the fix. It logs
 * once per 10 coroutines and ends halted: the count of lines times 10 bounds what ran.
 */
static void test_coroutine_metering(void)
{
    static const char *const makers[] = {
        "coroutine.wrap(function() local x = 0 for i = 1, 200 do x = x + i end end)()",
        "local co = coroutine.create(function() local x = 0 for i = 1, 200 do x = x + i end end)\n"
        "      coroutine.resume(co)",
    };
    for (size_t m = 0; m < sizeof(makers) / sizeof(makers[0]); m++) {
        record_t r;
        memset(&r, 0, sizeof(r));
        atalaia_node_config_t cfg = {0};
        cfg.node_id = 3;
        cfg.instr_limit = 200000;
        cfg.callbacks.log = on_log;
        cfg.callbacks.event = on_event;
        cfg.callbacks.user = &r;
        atalaia_node_t *n = atalaia_node_create(&cfg);
        CHECK(n != NULL);
        char src[512];
        snprintf(src, sizeof(src),
                 "on('go', function()\n"
                 "  local n = 0\n"
                 "  while true do\n"
                 "    %s\n"
                 "    n = n + 1\n"
                 "    if n %% 10 == 0 then log('n') end\n"
                 "  end\n"
                 "end)\n",
                 makers[m]);
        CHECK(atalaia_node_load(n, src, strlen(src), "=coroutine_metering"));
        (void)atalaia_node_input(n, "go", NULL);
        CHECK(atalaia_node_status(n) == ATALAIA_NODE_HALTED);
        double ran = (double)r.logs * 10.0 * 410.0;
        if (getenv("ATALAIA_ESCAPE_TIMES") != NULL) {
            printf("coroutine metering %zu: %d coroutines, about %.0f instructions for a limit of "
                   "200000\n",
                   m, r.logs * 10, ran);
        }
        /* One hook step per coroutine plus its loop: at most about 1/2 of what ran unmetered. */
        CHECK(ran < 2.0 * 200000.0);
        atalaia_node_destroy(n);
    }
}

/* A halted node's coroutines stop too: the hook of the main thread trips with the others. */
static void test_trip_reaches_every_thread(void)
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
    /* The coroutine trips the watchdog and resume catches it; the resumer must not go on. */
    const char *src = "on('go', function()\n"
                      "  local co = coroutine.create(function() while true do end end)\n"
                      "  coroutine.resume(co)\n"
                      "  for i = 1, 100000 do log('after') end\n"
                      "end)\n";
    CHECK(atalaia_node_load(n, src, strlen(src), "=trip"));
    (void)atalaia_node_input(n, "go", NULL);
    CHECK(atalaia_node_status(n) == ATALAIA_NODE_HALTED);
    CHECK(r.logs == 0);
    atalaia_node_destroy(n);
}

/* One host entry cannot chain callbacks past its cap (review finding LIVE2-S4, decision SR-133). */
static void test_entry_cap(void)
{
    record_t r;
    memset(&r, 0, sizeof(r));
    atalaia_node_config_t cfg = {0};
    cfg.node_id = 3;
    cfg.instr_limit = 100000; /* the entry cap is 4 times this */
    cfg.callbacks.log = on_log;
    cfg.callbacks.event = on_event;
    cfg.callbacks.user = &r;
    atalaia_node_t *n = atalaia_node_create(&cfg);
    CHECK(n != NULL);
    /* Each handler spends about 55,000 instructions, under its own limit, and emits the next
     * event: a chain of 50 of them is 2.7 million instructions inside one input. */
    const char *src = "local function spend() local x = 0 for i = 1, 27000 do x = x + i end end\n"
                      "local count = 0\n"
                      "on('go', function() count = 0 emit('x.club.chain', {}) end)\n"
                      "on('x.club.chain', function()\n"
                      "  spend() count = count + 1 log('step')\n"
                      "  if count < 50 then emit('x.club.chain', {}) end\n"
                      "end)\n"
                      "on('calm', function() spend() log('calm') end)\n";
    CHECK(atalaia_node_load(n, src, strlen(src), "=entry_cap"));
    (void)atalaia_node_input(n, "go", NULL);
    CHECK(atalaia_node_status(n) == ATALAIA_NODE_HALTED);
    CHECK(strstr(atalaia_node_last_error(n), "in one step") != NULL);
    CHECK(r.logs >= 3 && r.logs < 10); /* seven callbacks of about 55,000 fit under 400,000 */
    atalaia_node_destroy(n);

    /* The cap is per entry: many entries, each within it, run for as long as the game does. */
    memset(&r, 0, sizeof(r));
    n = atalaia_node_create(&cfg);
    CHECK(n != NULL);
    CHECK(atalaia_node_load(n, src, strlen(src), "=entry_cap"));
    for (int i = 0; i < 30; i++) {
        CHECK(atalaia_node_input(n, "calm", NULL));
    }
    CHECK(atalaia_node_status(n) == ATALAIA_NODE_RUNNING);
    CHECK(r.logs == 30);
    atalaia_node_destroy(n);

    /* Callbacks too short for the hook to count still cost the entry something: a timer that
     * sets the next one for "now" would run for ever inside one advance. */
    memset(&r, 0, sizeof(r));
    n = atalaia_node_create(&cfg);
    CHECK(n != NULL);
    const char *tiny =
        "local n = 0\nevery(0.01, function() n = n + 1 end)\n"
        "every(1, function() log('tick') end)\n"
        "on('chain', function() local function again() after(0, again) end again() end)\n";
    CHECK(atalaia_node_load(n, tiny, strlen(tiny), "=tiny_timers"));
    CHECK(atalaia_node_input(n, "chain", NULL));
    atalaia_node_advance(n, 10);
    CHECK(atalaia_node_status(n) == ATALAIA_NODE_HALTED);
    CHECK(strstr(atalaia_node_last_error(n), "in one step") != NULL);
    atalaia_node_destroy(n);

    /* A long jump of game time (the simulator's fast forward) may run what the time holds. */
    memset(&r, 0, sizeof(r));
    n = atalaia_node_create(&cfg);
    CHECK(n != NULL);
    CHECK(atalaia_node_load(n, tiny, strlen(tiny), "=tiny_timers"));
    atalaia_node_advance(n, 600000); /* 10 minutes: 60,000 calls of the 10 ms timer */
    CHECK(atalaia_node_status(n) == ATALAIA_NODE_RUNNING);
    CHECK(r.logs == 600);
    atalaia_node_destroy(n);

    /* The same timers advanced the way a game does, in steps of 100 ms, never reach it. */
    memset(&r, 0, sizeof(r));
    n = atalaia_node_create(&cfg);
    CHECK(n != NULL);
    CHECK(atalaia_node_load(n, tiny, strlen(tiny), "=tiny_timers"));
    for (uint32_t t = 100; t <= 60000; t += 100) {
        atalaia_node_advance(n, t);
    }
    CHECK(atalaia_node_status(n) == ATALAIA_NODE_RUNNING);
    CHECK(r.logs == 60);
    atalaia_node_destroy(n);
}

/*
 * The parser counts its nesting in the same C levels (luaconf.h LUAI_MAXCCALLS, decision SR-132):
 * a source nested over the limit fails to load with an error, a plainly nested one loads.
 */
static void test_parser_nesting(void)
{
    char src[512];
    for (int depth = 4; depth <= 60; depth += 4) {
        size_t n = 0;
        n += (size_t)snprintf(src + n, sizeof(src) - n, "local x = ");
        for (int i = 0; i < depth; i++) src[n++] = '(';
        src[n++] = '1';
        for (int i = 0; i < depth; i++) src[n++] = ')';
        src[n] = '\0';
        record_t r;
        memset(&r, 0, sizeof(r));
        atalaia_node_config_t cfg = {0};
        cfg.node_id = 3;
        cfg.callbacks.log = on_log;
        cfg.callbacks.event = on_event;
        cfg.callbacks.user = &r;
        atalaia_node_t *node = atalaia_node_create(&cfg);
        CHECK(node != NULL);
        bool loaded = atalaia_node_load(node, src, n, "=nesting");
        if (depth <= 8) {
            CHECK(loaded);
        }
        if (depth >= 24) {
            CHECK(!loaded);
            CHECK(strstr(atalaia_node_last_error(node), "overflow") != NULL ||
                  strstr(atalaia_node_last_error(node), "levels") != NULL);
        }
        atalaia_node_destroy(node);
    }
}

/* A timer set late in a very long game does not wrap round to the start (decision SR-137). */
static void test_timer_does_not_wrap(void)
{
    record_t r;
    memset(&r, 0, sizeof(r));
    atalaia_node_config_t cfg = {0};
    cfg.node_id = 3;
    cfg.callbacks.log = on_log;
    cfg.callbacks.event = on_event;
    cfg.callbacks.user = &r;
    atalaia_node_t *n = atalaia_node_create(&cfg);
    CHECK(n != NULL);
    const char *src = "on('go', function()\n"
                      "  after(3456000, function() log('fired after') end)\n"
                      "  every(3456000, function() log('fired every') end)\n"
                      "end)\n";
    CHECK(atalaia_node_load(n, src, strlen(src), "=wrap"));
    atalaia_node_advance(n, 4000000000u); /* 46 days in: 40 days more is past 2^32 ms */
    CHECK(atalaia_node_input(n, "go", NULL));
    atalaia_node_advance(n, 4100000000u);
    CHECK(r.logs == 0);
    atalaia_node_advance(n, 4294967295u); /* the very end: they stop there, once at most */
    CHECK(atalaia_node_status(n) == ATALAIA_NODE_RUNNING);
    CHECK(r.logs <= 2);
    atalaia_node_destroy(n);
}

int main(void)
{
    setvbuf(stdout, NULL, _IONBF, 0); /* each case's line as it ends */
    test_battery();
    test_bytecode();
    test_halt_is_final();
    test_coroutine_metering();
    test_trip_reaches_every_thread();
    test_entry_cap();
    test_parser_nesting();
    test_timer_does_not_wrap();
    printf("sandbox escape battery: %zu cases x 2 memory limits x box and controller, %s\n",
           CASE_COUNT, check_failures ? "FAILED" : "all held");
    return check_failures == 0 ? 0 : 1;
}
