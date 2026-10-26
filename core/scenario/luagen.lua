-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- A scenario's field.lua: a data table, SCENARIO, followed by the scenario
-- runtime (runtime.lua, the same text for every scenario; decision M7-2).
-- Nothing the GM wrote is ever pasted into Lua code: every value from the
-- manifest reaches the script only through value(), which writes it as a Lua
-- literal (a string in double quotes with every quote, backslash and control
-- character escaped; numbers that must be finite; keys that are names or
-- quoted strings; decision M7-3). Comments hold only names the validator
-- restricted to [a-z0-9_.-].
local luagen = {}

local py = need("py")
local m = need("manifest")
local unicode = need("unicode")

local byte, find, format, rep = string.byte, string.find, string.format, string.rep
local concat = table.concat

luagen.LICENSE = "GPL-3.0-or-later" -- the runtime's (runtime.lua), copied into every package
-- The SPDX tag, split so that REUSE does not read this source line as a licence expression.
luagen.SPDX_TAG = "SPDX-" .. "License-Identifier:"

local KEYWORDS = {}
for word in
  (
    "and break do else elseif end false for function goto if in local nil not or repeat return then "
    .. "true until while"
  ):gmatch("[a-z]+")
do
  KEYWORDS[word] = true
end

local SHORT = { ["\\"] = "\\\\", ['"'] = '\\"', ["\n"] = "\\n", ["\r"] = "\\r", ["\t"] = "\\t" }

-- A Lua error that is the manifest's (a value Lua cannot hold), not a bug.
local function lua_error(message)
  error({ lua = message }, 0)
end

local function escape_bytes(s)
  return (s:gsub(".", function(c)
    return format("\\%03d", byte(c))
  end))
end

-- A Lua string literal for any text: printable characters as they are (so
-- names stay readable), quotes and backslashes escaped, and every control,
-- format (bidi) or separator character, or anything else not printable, as
-- decimal byte escapes of its UTF-8 (\ddd).
function luagen.string(text)
  if type(text) ~= "string" then
    lua_error("not a text: " .. py.repr(text))
  end
  local body = text:gsub("[\0-\127\192-\255][\128-\191]*", function(ch)
    local b = byte(ch)
    if b < 0x80 then
      if SHORT[ch] then
        return SHORT[ch]
      elseif b >= 0x20 and b <= 0x7E then
        return ch
      end
      return format("\\%03d", b)
    end
    local c = py.decode_cp(ch, 1)
    if unicode.class(c) == "P" then
      return ch
    end
    return escape_bytes(ch)
  end)
  return '"' .. body .. '"'
end

local LUA_INT_MAX = math.maxinteger

local function is_name(k)
  return find(k, "^[A-Za-z_][A-Za-z0-9_]*$") ~= nil and not KEYWORDS[k]
end

-- A Lua literal for a manifest value: nil, booleans, finite numbers, texts,
-- lists and maps (writing on one line what fits in 80 columns).
function luagen.value(value, indent)
  indent = indent or 0
  local pad = rep("  ", indent + 1)
  local kind = py.kind(value)
  if kind == "None" then
    return "nil"
  elseif kind == "bool" then
    return value and "true" or "false"
  elseif kind == "int" then
    if not py.small_int(value) or value < -LUA_INT_MAX then
      lua_error(py.str(value) .. " does not fit a Lua integer")
    end
    return format("%d", value)
  elseif kind == "float" then
    if value ~= value or value == math.huge or value == -math.huge then
      lua_error(py.repr(value) .. " is not a finite number")
    end
    return py.float_repr(value)
  elseif kind == "str" then
    return luagen.string(value)
  elseif kind == "list" then
    if value.n == 0 then
      return "{}"
    end
    local items, width, multi = {}, 0, false
    for i = 1, value.n do
      local item = luagen.value(value[i], indent + 1)
      items[i] = item
      width = width + py.len(item) + 2
      multi = multi or find(item, "\n", 1, true) ~= nil
    end
    if not multi and width < 80 then
      return "{ " .. concat(items, ", ") .. " }"
    end
    local out = { "{\n" }
    for i = 1, #items do
      out[#out + 1] = pad .. items[i] .. ",\n"
    end
    out[#out + 1] = rep("  ", indent) .. "}"
    return concat(out)
  elseif kind == "dict" then
    local lines, width, multi = {}, 0, false
    for i = 1, value.n do
      local k, v = value.k[i], value.v[i]
      if v ~= nil then
        if type(k) ~= "string" then
          lua_error("a key must be text: " .. py.repr(k))
        end
        local key = is_name(k) and k or ("[" .. luagen.string(k) .. "]")
        local line = key .. " = " .. luagen.value(v, indent + 1)
        lines[#lines + 1] = line
        width = width + py.len(line) + 2
        multi = multi or find(line, "\n", 1, true) ~= nil
      end
    end
    if #lines == 0 then
      return "{}"
    end
    if not multi and width < 80 then
      return "{ " .. concat(lines, ", ") .. " }"
    end
    local out = { "{\n" }
    for i = 1, #lines do
      out[#out + 1] = pad .. lines[i] .. ",\n"
    end
    out[#out + 1] = rep("  ", indent) .. "}"
    return concat(out)
  end
  lua_error("cannot write " .. kind .. " as Lua")
end

-- A comment line: only for names the validator restricted (never a free text).
function luagen.comment(text)
  if type(text) ~= "string" or not find(text, "^[a-z0-9_.+%-]*$") then
    lua_error(py.repr(text) .. " cannot go in a comment")
  end
  return "-- " .. text
end

-- -- The objectives package's setup (modes/objectives/node.lua) --

local KINDS = {
  capture_and_hold = "capture",
  defend = "capture",
  enter_code = "code",
  scan_tags = "tags",
  destroy = "bomb",
}
luagen.KINDS = KINDS

local function ordered(...)
  local map = py.map()
  local args = table.pack(...)
  for i = 1, args.n, 2 do
    py.put(map, args[i], args[i + 1])
  end
  return map
end
luagen.ordered = ordered

local function or_map(v)
  return py.truthy(v) and v or py.map()
end
luagen.or_map = or_map

-- What the box of an open objective is told (the mode command setup, without
-- its name): only what the manifest gives, so the box's defaults apply to the rest.
function luagen.setup_command(o, lang, label)
  local otype = py.get(o, "type")
  local kind = KINDS[otype]
  local params = or_map(py.get(o, "params"))
  local team = py.get(or_map(py.get(o, "assignee")), "team")
  local setup = ordered("kind", kind, "label", label)
  if not py.eq(lang, "pt") then
    py.put(setup, "lang", lang)
  end
  if team ~= nil and otype ~= "defend" then -- anyone may take a point from its defenders
    py.put(setup, "team", team)
  end
  if (kind == "capture" or kind == "bomb") and py.has(params, "hold_ms") then
    py.put(setup, "hold_ms", py.get(params, "hold_ms"))
  end
  if kind == "bomb" then
    for _, key in ipairs({ "defuse_ms", "fuse_s" }) do
      if py.has(params, key) then
        py.put(setup, key, py.get(params, key))
      end
    end
  end
  if kind == "code" then
    py.put(setup, "code", py.get(params, "code"))
  end
  if kind == "tags" then
    py.put(setup, "count", py.get(params, "tag_count"))
    if py.truthy(py.get(params, "any")) then
      py.put(setup, "any", true)
    end
  end
  return setup
end

-- Python's float(v): an int as a float, a float as it is (-0.0 stays -0.0).
local function float(v)
  return math.type(v) == "float" and v or v + 0.0
end
luagen.float = float

local function zone(destination)
  if py.has(destination, "points") then
    local points = py.list({}, 0)
    local src = py.get(destination, "points")
    for i = 1, src.n do
      points[i] = py.list({ float(src[i][1]), float(src[i][2]) }, 2)
    end
    points.n = src.n
    return ordered("type", "polygon", "points", points)
  end
  return ordered(
    "type",
    "circle",
    "lat",
    float(py.get(destination, "lat")),
    "lon",
    float(py.get(destination, "lon")),
    "radius_m",
    float(py.get(destination, "radius_m"))
  )
end

local function copy_list(v)
  local out = py.list({}, 0)
  if v ~= nil then
    for i = 1, v.n do
      out[i] = v[i]
    end
    out.n = v.n
  end
  return out
end
luagen.copy_list = copy_list

-- One objective as the runtime reads it (runtime.lua, "The data").
function luagen.objective_data(o, manifest)
  local lang = py.getd(manifest, "lang", "pt")
  local nodes = or_map(py.get(manifest, "nodes"))
  local params = or_map(py.get(o, "params"))
  local assignee = or_map(py.get(o, "assignee"))
  local effect = or_map(py.get(o, "effect"))
  local window = or_map(py.get(o, "time_window"))
  local points = py.get(effect, "points")
  local squad = py.get(assignee, "squad")
  local otype = py.get(o, "type")
  local end_min = py.get(window, "end_min")
  local data = ordered(
    "id",
    py.get(o, "id"),
    "type",
    otype,
    "team",
    py.get(assignee, "team"),
    "squad",
    squad ~= nil and py.str(squad) or nil, -- the events' squad is text (data key 2)
    "hidden",
    py.getd(o, "visibility", m.default_visibility(o, manifest)) == "hidden",
    "depends_on",
    copy_list(py.truthy(py.get(o, "depends_on")) and py.get(o, "depends_on") or nil),
    "reveals",
    copy_list(py.truthy(py.get(effect, "reveal")) and py.get(effect, "reveal") or nil),
    "start_s",
    py.getd(window, "start_min", 0) * 60,
    "end_s",
    end_min ~= nil and end_min * 60 or nil,
    "points",
    py.is_int(points) and points or nil,
    "points_param",
    py.is_map(points) and py.get(points, "param") or nil,
    "win",
    py.truthy(py.getd(effect, "win", false))
  )
  local target = py.get(o, "target")
  if KINDS[otype] then
    py.put(data, "node", target)
    py.put(data, "setup", luagen.setup_command(o, lang, m.translated(o, lang) or py.get(o, "id")))
  end
  if otype == "capture_and_hold" or otype == "defend" then
    py.put(data, "duration_s", py.getd(params, "duration_s", 0))
  end
  if otype == "escort" then
    local z = zone(py.get(params, "destination"))
    py.put(data, "role", py.getd(or_map(py.get(nodes, target)), "role", "vip"))
    py.put(data, "zone", z)
    py.put(data, "max_acc_m", py.getd(params, "max_acc_m", py.getd(z, "radius_m", 25.0)))
  end
  if otype == "survive" then
    py.put(data, "minimum_lives", py.get(params, "minimum_lives"))
  end
  return data
end

-- The scenario's field.lua: a header, the data table and the runtime.
function luagen.field_lua(manifest, runtime)
  local sid = py.get(manifest, "id")
  local objectives = py.list({}, 0)
  local src = py.get(manifest, "objectives")
  for i = 1, src.n do
    objectives[i] = luagen.objective_data(src[i], manifest)
  end
  objectives.n = src.n
  local teams = py.getd(manifest, "teams", nil)
  local data = ordered(
    "id",
    sid,
    "teams",
    teams ~= nil and copy_list(teams) or py.list({ "red", "blue" }, 2),
    "objectives",
    objectives
  )
  local lines = {
    "-- " .. luagen.SPDX_TAG .. " " .. luagen.LICENSE,
    "--",
    "-- Generated by the Atalaia scenario compiler (controller/atalaia_controller/scenarios)",
    "-- from the scenario manifest of:",
    luagen.comment(sid),
    "-- Edit the manifest and compile it again rather than this file. The objectives and",
    "-- their texts are in the table below; the code after it is the same for every scenario.",
    "",
    "local SCENARIO = " .. luagen.value(data),
    "",
  }
  local at = find(runtime, "-- @runtime\n", 1, true)
  local body = runtime:sub(at + #"-- @runtime\n")
  return concat(lines, "\n") .. body
end

return luagen
