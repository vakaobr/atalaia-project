-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- The manifest's data tree, as JSON (core/scenario/README.md): how a
-- controller hands the compiler a manifest it has read, and how the answer
-- goes back.
--
-- Every value is typed, as protocol/vectors/scenario_compile.json's "loads"
-- write them, so that 1, 1.0, True and "1" stay apart:
--   {"str": s} {"int": "decimal"} {"float": "Python's repr"} {"bool": b}
--   {"null": null} {"timestamp": "Python's str()"} {"list": [values]}
--   {"map": [[key, value], ...]}
-- {"other": {"repr": "Python's repr()", "truthy": b}} for a value of a kind
-- no rule takes (a set or bytes, which PyYAML's !!set and !!binary build),
-- and {"alias": n}: the n-th list or map again (0 the first one begun, in the
-- text's order), for a YAML anchor's alias or a Python object in two places
-- (a map shared by two objectives is written once in mode.yaml, with an
-- anchor, as PyYAML does; a list may hold itself).
--
-- Texts are UTF-8. A \u escape is one code point and is never joined with the
-- next: a surrogate (half of a UTF-16 pair, \ud83d) stays one, as its three
-- bytes, and so does one written raw that way; the validator says where
-- (bad_unicode). A manifest's readers join the halves of a pair the text
-- itself wrote (PE24-107) before they write the tree.
local tree = {}

local py = need("py")

local byte, sub, find, format = string.byte, string.sub, string.find, string.format
local concat = table.concat

tree.MAX_DEPTH = 100

local Reader = {}
Reader.__index = Reader

local function fail(r, what)
  error({ tree = format("the manifest's data tree is not valid at byte %d: %s", r.pos, what) }, 0)
end

local function skip(r)
  local _, e = find(r.text, "^[ \t\r\n]*", r.pos)
  r.pos = e + 1
end

local function expect(r, c)
  skip(r)
  if sub(r.text, r.pos, r.pos) ~= c then
    fail(r, "expected " .. c)
  end
  r.pos = r.pos + 1
end

local function peek(r)
  skip(r)
  return sub(r.text, r.pos, r.pos)
end

local function utf8_text(c)
  return py.cp_text(c)
end

local ESC =
  { ['"'] = '"', ["\\"] = "\\", ["/"] = "/", b = "\b", f = "\f", n = "\n", r = "\r", t = "\t" }

-- A JSON string at r.pos: its text.
local function read_string(r)
  skip(r)
  local text = r.text
  if sub(text, r.pos, r.pos) ~= '"' then
    fail(r, "expected a string")
  end
  local pos = r.pos + 1
  local parts, n = {}, 0
  while true do
    local s = find(text, '["\\\0-\31]', pos)
    if not s then
      r.pos = #text + 1
      fail(r, "a string that does not end")
    end
    if s > pos then
      local chunk = sub(text, pos, s - 1)
      -- UTF-8 with surrogates (Lua's lax decoding takes them) up to U+10FFFF.
      if find(chunk, "[\128-\255]") then
        if
          not utf8.len(chunk, 1, -1, true)
          or find(chunk, "[\245-\255]")
          or find(chunk, "\244[\144-\191]")
        then
          r.pos = pos
          fail(r, "a text that is not UTF-8")
        end
      end
      n = n + 1
      parts[n] = chunk
    end
    local c = sub(text, s, s)
    if c == '"' then
      r.pos = s + 1
      return concat(parts)
    elseif c == "\\" then
      local e = sub(text, s + 1, s + 1)
      if e == "u" then
        local hex = sub(text, s + 2, s + 5)
        if not find(hex, "^[0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f][0-9A-Fa-f]$") then
          r.pos = s
          fail(r, "a bad \\u escape")
        end
        n = n + 1
        parts[n] = utf8_text(tonumber(hex, 16))
        pos = s + 6
      elseif ESC[e] then
        n = n + 1
        parts[n] = ESC[e]
        pos = s + 2
      else
        r.pos = s
        fail(r, "a bad escape")
      end
    else
      r.pos = s
      fail(r, "a control character in a string")
    end
  end
end

local INT64_MAX = "9223372036854775807"
local INT64_MIN = "9223372036854775808"

local function read_int(r, s)
  if not find(s, "^%-?[0-9]+$") then
    fail(r, "an int that is not a decimal number")
  end
  local neg = sub(s, 1, 1) == "-"
  local digits = neg and sub(s, 2) or s
  digits = digits:gsub("^0+", "")
  if digits == "" then
    return 0
  end
  local limit = neg and INT64_MIN or INT64_MAX
  if #digits > 19 or (#digits == 19 and py.str_lt(limit, digits)) then
    return py.big((neg and "-" or "") .. digits)
  end
  if neg and digits == INT64_MIN then
    return math.mininteger
  end
  local v = math.tointeger(tonumber(digits))
  return neg and -v or v
end

local function read_float(r, s)
  if s == "nan" then
    return 0.0 / 0.0
  elseif s == "inf" then
    return math.huge
  elseif s == "-inf" then
    return -math.huge
  end
  if not find(s, "^%-?[0-9]+%.?[0-9]*e?[+%-]?[0-9]*$") then
    fail(r, "a float that is not a number")
  end
  local v = tonumber(s)
  if v == nil then
    fail(r, "a float that is not a number")
  end
  if math.type(v) == "integer" then
    v = v + 0.0 -- "1e5" style texts read as floats already; this keeps every float a float
  end
  return v
end

local read_value

local function read_list(r, depth)
  local list = py.list({}, 0)
  r.shared[#r.shared + 1] = list
  expect(r, "[")
  if peek(r) == "]" then
    r.pos = r.pos + 1
    return list
  end
  local n = 0
  while true do
    n = n + 1
    list[n] = read_value(r, depth + 1)
    list.n = n
    local c = peek(r)
    r.pos = r.pos + 1
    if c == "]" then
      return list
    elseif c ~= "," then
      r.pos = r.pos - 1
      fail(r, "expected , or ]")
    end
  end
end

local function read_map(r, depth)
  local map = py.map()
  r.shared[#r.shared + 1] = map
  expect(r, "[")
  if peek(r) == "]" then
    r.pos = r.pos + 1
    return map
  end
  while true do
    expect(r, "[")
    local k = read_value(r, depth + 1)
    expect(r, ",")
    local v = read_value(r, depth + 1)
    expect(r, "]")
    py.put(map, k, v)
    local c = peek(r)
    r.pos = r.pos + 1
    if c == "]" then
      return map
    elseif c ~= "," then
      r.pos = r.pos - 1
      fail(r, "expected , or ]")
    end
  end
end

local function literal(r, word)
  skip(r)
  if sub(r.text, r.pos, r.pos + #word - 1) ~= word then
    fail(r, "expected " .. word)
  end
  r.pos = r.pos + #word
end

function read_value(r, depth)
  if depth > tree.MAX_DEPTH then
    error({ deep = true }, 0)
  end
  expect(r, "{")
  local kind = read_string(r)
  expect(r, ":")
  local value
  if kind == "str" then
    value = read_string(r)
  elseif kind == "int" then
    value = read_int(r, read_string(r))
  elseif kind == "float" then
    value = read_float(r, read_string(r))
  elseif kind == "bool" then
    if peek(r) == "t" then
      literal(r, "true")
      value = true
    else
      literal(r, "false")
      value = false
    end
  elseif kind == "null" then
    literal(r, "null")
  elseif kind == "timestamp" then
    local s = read_string(r)
    if not find(s, "^[0-9][0-9][0-9][0-9]%-[0-9][0-9]%-[0-9][0-9]") then
      fail(r, "a timestamp that is not a date")
    end
    value = py.stamp(s)
  elseif kind == "list" then
    value = read_list(r, depth)
  elseif kind == "map" then
    value = read_map(r, depth)
  elseif kind == "other" then
    -- A value of a kind no rule takes (a set, bytes): its repr() and its truth.
    expect(r, "{")
    local repr_, truthy
    for i = 1, 2 do
      local key = read_string(r)
      expect(r, ":")
      if key == "repr" then
        repr_ = read_string(r)
      elseif key == "truthy" then
        truthy = peek(r) == "t"
        literal(r, truthy and "true" or "false")
      else
        fail(r, "an unknown key in an other value")
      end
      if i == 1 then
        expect(r, ",")
      end
    end
    expect(r, "}")
    if repr_ == nil or truthy == nil then
      fail(r, "an other value without its repr and truthy")
    end
    value = py.other(repr_, truthy)
  elseif kind == "alias" then
    skip(r)
    local _, e, digits = find(r.text, "^([0-9]+)", r.pos)
    if not e then
      fail(r, "an alias that is not a number")
    end
    r.pos = e + 1
    value = r.shared[tonumber(digits) + 1]
    if value == nil then
      fail(r, "an alias of a list or map not begun yet")
    end
  else
    fail(r, "an unknown kind of value")
  end
  expect(r, "}")
  return value
end

-- The manifest in a data tree's JSON text. Raises { tree = why } when the text
-- is not one, or { deep = true } past MAX_DEPTH levels.
function tree.read(text)
  local r = setmetatable({ text = text, pos = 1, shared = {} }, Reader)
  local value = read_value(r, 0)
  skip(r)
  if r.pos <= #text then
    fail(r, "text after the value")
  end
  return value
end

-- -- The answer's JSON (texts, numbers, booleans, lists and objects) --

local function quote(s)
  return '"'
    .. s:gsub('[\0-\31"\\]', function(c)
      if c == '"' then
        return '\\"'
      elseif c == "\\" then
        return "\\\\"
      elseif c == "\n" then
        return "\\n"
      elseif c == "\t" then
        return "\\t"
      elseif c == "\r" then
        return "\\r"
      end
      return format("\\u%04x", byte(c))
    end)
    .. '"'
end
tree.quote = quote

-- A plain Lua value as JSON: a table with an `order` list is an object written
-- in that order; an array (`n` or #) is a list.
function tree.json(v)
  local t = type(v)
  if t == "string" then
    return quote(v)
  elseif t == "boolean" then
    return v and "true" or "false"
  elseif t == "nil" then
    return "null"
  elseif t == "number" then
    return format("%d", v)
  end
  local parts = {}
  if v.order then
    for i, key in ipairs(v.order) do
      parts[i] = quote(key) .. ":" .. tree.json(v[key])
    end
    return "{" .. concat(parts, ",") .. "}"
  end
  for i = 1, v.n or #v do
    parts[i] = tree.json(v[i])
  end
  return "[" .. concat(parts, ",") .. "]"
end

function tree.object(...)
  local o = { order = {} }
  local args = table.pack(...)
  for i = 1, args.n, 2 do
    o.order[#o.order + 1] = args[i]
    o[args[i]] = args[i + 1]
  end
  return o
end

return tree
