-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- The manifest's values as the scenario rules were first written for them, in
-- Python (decision PE24-109): a manifest is what PyYAML (on the Pi) or the
-- phone's PyYAML-compatible reader reads, and the validator's paths and
-- messages print its values as Python's str() and repr() do. This module is
-- that data model and those semantics, for the rest of the compiler.
--
-- A value is one of:
--   nil              None
--   boolean          bool
--   integer          int (64 bits); a larger one is a Big { digits = "-123..." }
--   float            float
--   string           str, as UTF-8 (a surrogate code point as its three bytes,
--                    ED A0-BF xx, which only the validator's bad_unicode reads)
--   List             { n = count, [1..n] = values } (a value may be nil)
--   Map              { n = count, k = { keys }, v = { values } }, in order, with
--                    a lookup by Python's equality of keys
--   Stamp            { text = "2026-10-23 10:00:00+01:00" } (a YAML timestamp)
--
-- Nothing here depends on the process's locale: no %a, %d, %s or %c pattern
-- classes, no string.lower, no "<" between strings (Lua's uses strcoll).
local py = {}

local unicode = need("unicode")

local List = { __name = "List" }
local Map = { __name = "Map" }
local Big = { __name = "Big" }
local Stamp = { __name = "Stamp" }
local Other = { __name = "Other" }
local NONE = setmetatable({}, { __name = "None" }) -- None as a lookup key

py.List, py.Map, py.Big, py.Stamp, py.Other = List, Map, Big, Stamp, Other

local mtype = math.type
local byte, char, sub, find, format =
  string.byte, string.char, string.sub, string.find, string.format
local concat = table.concat

-- -- Types --

function py.list(items, n)
  items = items or {}
  items.n = n or #items
  return setmetatable(items, List)
end

function py.map()
  return setmetatable({ n = 0, k = {}, v = {}, s = {}, o = {} }, Map)
end

function py.big(digits)
  return setmetatable({ digits = digits }, Big)
end

function py.stamp(text)
  return setmetatable({ text = text }, Stamp)
end

-- A value of a kind no rule takes (a set, bytes): only its repr() and its truth.
function py.other(repr_text, truthy)
  return setmetatable({ repr = repr_text, truthy = truthy }, Other)
end

-- What Python's type() would say: None, bool, int, float, str, list, dict, timestamp.
function py.kind(v)
  local t = type(v)
  if t == "nil" then
    return "None"
  elseif t == "boolean" then
    return "bool"
  elseif t == "number" then
    return mtype(v) == "integer" and "int" or "float"
  elseif t == "string" then
    return "str"
  end
  local mt = getmetatable(v)
  if mt == List then
    return "list"
  elseif mt == Map then
    return "dict"
  elseif mt == Big then
    return "int"
  elseif mt == Stamp then
    return "timestamp"
  end
  return "other"
end

function py.is_list(v)
  return getmetatable(v) == List
end

function py.is_map(v)
  return getmetatable(v) == Map
end

function py.is_str(v)
  return type(v) == "string"
end

-- isinstance(v, int) and not isinstance(v, bool)
function py.is_int(v)
  return mtype(v) == "integer" or getmetatable(v) == Big
end

-- An int that is a 64-bit integer (every range the rules check is inside).
local function small_int(v)
  return mtype(v) == "integer"
end
py.small_int = small_int

function py.is_float(v)
  return mtype(v) == "float"
end

-- isinstance(v, (int, float)) and not bool and math.isfinite(v)
function py.is_number(v)
  if mtype(v) == "integer" or getmetatable(v) == Big then
    return true
  end
  return mtype(v) == "float" and v == v and v ~= math.huge and v ~= -math.huge
end

-- lo <= v <= hi for an int (a Big is past every range the rules use).
function py.int_in(v, lo, hi)
  return small_int(v) and v >= lo and v <= hi
end

-- lo <= v <= hi for an int or a float (a Big is past every such range).
function py.num_in(v, lo, hi)
  local t = mtype(v)
  return (t == "integer" or t == "float") and v >= lo and v <= hi
end

-- -- Maps --

-- The lookup key of a map key: Python's equal keys (1, 1.0, True) share one.
local function norm(k)
  local t = type(k)
  if t == "number" then
    if mtype(k) == "float" then
      if k ~= k then
        return nil -- NaN equals nothing, not even itself
      end
      return math.tointeger(k) or k
    end
    return k
  elseif t == "boolean" then
    return k and 1 or 0
  elseif t == "nil" then
    return NONE
  end
  local mt = getmetatable(k)
  if mt == Big then
    return "b" .. k.digits
  elseif mt == Stamp then
    return "t" .. py.stamp_key(k)
  end
  return k -- a list or a map: by identity (Python refuses them as keys)
end

-- Adds a key (or replaces the value of an equal one, keeping the first key, as
-- a Python dict does).
function py.put(m, k, v)
  local i
  if type(k) == "string" then
    i = m.s[k]
  else
    local nk = norm(k)
    if nk ~= nil then
      i = m.o[nk]
    end
  end
  if i == nil then
    i = m.n + 1
    m.n = i
    m.k[i] = k
    if type(k) == "string" then
      m.s[k] = i
    else
      local nk = norm(k)
      if nk ~= nil then
        m.o[nk] = i
      end
    end
  end
  m.v[i] = v
end

local function index(m, k)
  if type(k) == "string" then
    return m.s[k]
  end
  local nk = norm(k)
  return nk ~= nil and m.o[nk] or nil
end

-- key in m
function py.has(m, k)
  return index(m, k) ~= nil
end

-- m.get(k): nil when absent or None
function py.get(m, k)
  local i = index(m, k)
  return i and m.v[i]
end

-- m.get(k, default): the default only when the key is absent
function py.getd(m, k, default)
  local i = index(m, k)
  if i == nil then
    return default
  end
  return m.v[i]
end

-- m.get(k) when m may not be a map (nil then)
function py.mget(m, k)
  if getmetatable(m) ~= Map then
    return nil
  end
  return py.get(m, k)
end

-- -- Truth and equality --

function py.truthy(v)
  if v == nil or v == false or v == 0 or v == "" then
    return false
  end
  local mt = getmetatable(v)
  if mt == List or mt == Map then
    return v.n > 0
  elseif mt == Other then
    return v.truthy
  end
  return true -- NaN, a Big and a timestamp are true
end

-- Two timestamps compare as Python's dates and datetimes do: a date only with a
-- date; a datetime without a zone only with one without; with zones, as instants.
function py.stamp_key(s)
  local t = s.text
  if #t == 10 then
    return "d" .. t
  end
  local zone = find(t, "[+-][0-9][0-9]:[0-9][0-9]$", 20)
  if not zone then
    return "n" .. t
  end
  local y, mo, d = tonumber(sub(t, 1, 4)), tonumber(sub(t, 6, 7)), tonumber(sub(t, 9, 10))
  local h, mi, se = tonumber(sub(t, 12, 13)), tonumber(sub(t, 15, 16)), tonumber(sub(t, 18, 19))
  local frac = sub(t, 20, zone - 1)
  local sign = sub(t, zone, zone) == "-" and -1 or 1
  local off = sign
    * (tonumber(sub(t, zone + 1, zone + 2)) * 60 + tonumber(sub(t, zone + 4, zone + 5)))
  -- Days from the civil date (proleptic Gregorian), then seconds, minus the offset.
  local yy = mo <= 2 and y - 1 or y
  local era = yy // 400
  local yoe = yy - era * 400
  local doy = (153 * (mo + (mo > 2 and -3 or 9)) + 2) // 5 + d - 1
  local days = era * 146097 + yoe * 365 + yoe // 4 - yoe // 100 + doy
  local secs = days * 86400 + h * 3600 + mi * 60 + se - off * 60
  return "a" .. format("%d", secs) .. frac
end

local function exact_float_digits(f)
  -- An integral float's exact decimal digits.
  return format("%.0f", f)
end

local function num_eq(a, b)
  local ba, bb = getmetatable(a) == Big, getmetatable(b) == Big
  if ba or bb then
    if ba and bb then
      return a.digits == b.digits
    end
    local other = ba and b or a
    local big = ba and a or b
    if mtype(other) == "float" and other == math.floor(other) and other == other then
      return exact_float_digits(other) == big.digits
    end
    return false -- a 64-bit integer, or a float with a fraction, is never a Big
  end
  return a == b
end

local function numeric(v)
  local t = type(v)
  if t == "number" then
    return v
  elseif t == "boolean" then
    return v and 1 or 0
  elseif getmetatable(v) == Big then
    return v
  end
  return nil
end

-- Python's a == b.
function py.eq(a, b, depth)
  depth = depth or 0
  if depth > 200 then
    return false
  end
  if rawequal(a, b) and not (mtype(a) == "float" and a ~= a) then
    return true
  end
  local na, nb = numeric(a), numeric(b)
  if na ~= nil or nb ~= nil then
    return na ~= nil and nb ~= nil and num_eq(na, nb)
  end
  local ta, tb = type(a), type(b)
  if ta ~= tb then
    return false
  end
  if ta == "string" then
    return a == b
  end
  local ma, mb = getmetatable(a), getmetatable(b)
  if ma ~= mb then
    return false
  end
  if ma == List then
    if a.n ~= b.n then
      return false
    end
    for i = 1, a.n do
      if not py.eq(a[i], b[i], depth + 1) then
        return false
      end
    end
    return true
  elseif ma == Map then
    if a.n ~= b.n then
      return false
    end
    for i = 1, a.n do
      local j = index(b, a.k[i])
      if j == nil or not py.eq(a.v[i], b.v[j], depth + 1) then
        return false
      end
    end
    return true
  elseif ma == Stamp then
    return py.stamp_key(a) == py.stamp_key(b)
  end
  return false
end

-- x in (a, b, ...): one of the texts
function py.one_of(v, texts)
  if type(v) ~= "string" then
    return false
  end
  for _, t in ipairs(texts) do
    if v == t then
      return true
    end
  end
  return false
end

-- -- Texts --

-- The code points of a UTF-8 text, as an array (a surrogate's three bytes are
-- one code point).
local function decode_cp(s, i)
  local c = byte(s, i)
  if c < 0x80 then
    return c, i + 1
  elseif c < 0xE0 then
    return ((c & 0x1F) << 6) | (byte(s, i + 1) & 0x3F), i + 2
  elseif c < 0xF0 then
    return ((c & 0x0F) << 12) | ((byte(s, i + 1) & 0x3F) << 6) | (byte(s, i + 2) & 0x3F), i + 3
  end
  return ((c & 0x07) << 18)
    | ((byte(s, i + 1) & 0x3F) << 12)
    | ((byte(s, i + 2) & 0x3F) << 6)
    | (byte(s, i + 3) & 0x3F),
    i + 4
end
py.decode_cp = decode_cp

function py.codepoints(s)
  local out, n, i, len = {}, 0, 1, #s
  while i <= len do
    local c
    c, i = decode_cp(s, i)
    n = n + 1
    out[n] = c
  end
  return out, n
end

-- The text of one code point.
local function cp_text(c)
  if c < 0x80 then
    return char(c)
  elseif c < 0x800 then
    return char(0xC0 | (c >> 6), 0x80 | (c & 0x3F))
  elseif c < 0x10000 then
    return char(0xE0 | (c >> 12), 0x80 | ((c >> 6) & 0x3F), 0x80 | (c & 0x3F))
  end
  return char(
    0xF0 | (c >> 18),
    0x80 | ((c >> 12) & 0x3F),
    0x80 | ((c >> 6) & 0x3F),
    0x80 | (c & 0x3F)
  )
end
py.cp_text = cp_text

-- The characters of a text, each as its own string, and their count.
function py.chars(s)
  local out, n, i, len = {}, 0, 1, #s
  while i <= len do
    local c = byte(s, i)
    local w = c < 0x80 and 1 or c < 0xE0 and 2 or c < 0xF0 and 3 or 4
    n = n + 1
    out[n] = sub(s, i, i + w - 1)
    i = i + w
  end
  return out, n
end

-- len(text): code points
function py.len(s)
  local n = 0
  for _ in string.gmatch(s, "[^\128-\191]") do
    n = n + 1
  end
  return n
end

-- Whether a text holds a surrogate code point (half of a UTF-16 pair).
function py.has_surrogate(s)
  return find(s, "\237[\160-\191]") ~= nil
end

-- text.strip() == "": only Python's whitespace (str.isspace)
function py.blank(s)
  if not find(s, "[^\t-\r\28- ]") then
    return true
  end
  if not find(s, "[\128-\255]") then
    return false
  end
  for _, c in ipairs((py.codepoints(s))) do
    if not unicode.space(c) then
      return false
    end
  end
  return true
end

-- Control characters in a one-line text (Cc, Cf, Zl, Zp): newlines, escapes,
-- bidi overrides.
function py.has_controls(s)
  if find(s, "[\0-\31\127]") then
    return true
  end
  if not find(s, "[\128-\255]") then
    return false
  end
  for _, c in ipairs((py.codepoints(s))) do
    if unicode.class(c) == "C" then
      return true
    end
  end
  return false
end

-- Byte-wise order of two texts (code point order for UTF-8), whatever the locale.
function py.str_lt(a, b)
  local n = math.min(#a, #b)
  for i = 1, n do
    local x, y = byte(a, i), byte(b, i)
    if x ~= y then
      return x < y
    end
  end
  return #a < #b
end

-- -- str() and repr() --

local repr

-- Python's repr of a float: the shortest digits that read back the same, in
-- exponent form below 1e-4 and from 1e16 on (1e-05, 1e+16), else with at least
-- one decimal (38.0).
local function shortest(x)
  -- The digits and exponent of the shortest %e form that reads back as x
  -- (David Gay's, which Python uses: the nearest of the shortest).
  for p = 0, 16 do
    local s = format("%." .. p .. "e", x)
    s = s:gsub("[^0-9eE+%-]", ".")
    if tonumber(s) == x then
      return s
    end
    -- The nearest p-digit decimal may fall outside x's interval where its
    -- neighbour does not (at a power of two); try the neighbours too.
    local m, e = s:match("^%-?([0-9.]+)e([+%-][0-9]+)$")
    if m then
      local digits = m:gsub("%.", "")
      local v = math.tointeger(tonumber(digits))
      if v then
        for _, d in ipairs({ v - 1, v + 1 }) do
          local ds = format("%d", d)
          if #ds == #digits and d > 0 then
            local cand = (x < 0 and "-" or "")
              .. sub(ds, 1, 1)
              .. (#ds > 1 and "." .. sub(ds, 2) or "")
              .. "e"
              .. e
            if tonumber(cand) == x then
              return cand
            end
          end
        end
      end
    end
  end
  return (format("%.16e", x):gsub("[^0-9eE+%-]", "."))
end

function py.float_repr(x)
  if x ~= x then
    return "nan"
  elseif x == math.huge then
    return "inf"
  elseif x == -math.huge then
    return "-inf"
  end
  local sign = (x < 0 or (x == 0 and 1 / x < 0)) and "-" or ""
  if x == 0 then
    return sign .. "0.0"
  end
  local s = shortest(math.abs(x))
  local m, e = s:match("^([0-9.]+)e([+%-][0-9]+)$")
  local digits = m:gsub("%.", "")
  digits = digits:gsub("0+$", "")
  if digits == "" then
    digits = "0"
  end
  local exponent = tonumber(e)
  local point = exponent + 1 -- the digits are 0.ddd * 10^point
  if point <= -4 or point > 16 then
    local mantissa = #digits > 1 and (sub(digits, 1, 1) .. "." .. sub(digits, 2)) or digits
    local es = exponent < 0 and "-" or "+"
    local ea = format("%d", math.abs(exponent))
    if #ea < 2 then
      ea = "0" .. ea
    end
    return sign .. mantissa .. "e" .. es .. ea
  end
  if point <= 0 then
    return sign .. "0." .. string.rep("0", -point) .. digits
  end
  if point >= #digits then
    return sign .. digits .. string.rep("0", point - #digits) .. ".0"
  end
  return sign .. sub(digits, 1, point) .. "." .. sub(digits, point + 1)
end

-- repr() of a text: in single quotes unless it holds one and no double quote;
-- \\, the quote, \t \n \r, other controls as \xNN, and what Python does not
-- print (str.isprintable) as \xNN, \uNNNN or \UNNNNNNNN.
local function str_repr(s)
  local quote = (find(s, "'", 1, true) and not find(s, '"', 1, true)) and '"' or "'"
  if not find(s, "[\0-\31\127-\255\\'\"]") then
    return quote .. s .. quote
  end
  local out, n = { quote }, 1
  local i, len = 1, #s
  while i <= len do
    local c
    local start = i
    c, i = decode_cp(s, i)
    local piece
    if c == 0x5C then
      piece = "\\\\"
    elseif c == byte(quote) then
      piece = "\\" .. quote
    elseif c == 0x09 then
      piece = "\\t"
    elseif c == 0x0A then
      piece = "\\n"
    elseif c == 0x0D then
      piece = "\\r"
    elseif c < 0x20 or c == 0x7F then
      piece = format("\\x%02x", c)
    elseif c < 0x7F then
      piece = sub(s, start, i - 1)
    elseif unicode.class(c) == "P" then
      piece = sub(s, start, i - 1)
    elseif c <= 0xFF then
      piece = format("\\x%02x", c)
    elseif c <= 0xFFFF then
      piece = format("\\u%04x", c)
    else
      piece = format("\\U%08x", c)
    end
    n = n + 1
    out[n] = piece
  end
  n = n + 1
  out[n] = quote
  return concat(out)
end
py.str_repr = str_repr

local function two(v)
  return format("%d", tonumber(v))
end

-- repr() of a timestamp, from its str(): datetime.date(2026, 10, 23),
-- datetime.datetime(2026, 10, 23, 10, 0[, s[, us]][, tzinfo=...]).
local function stamp_repr(s)
  local t = s.text
  local y, mo, d = two(sub(t, 1, 4)), two(sub(t, 6, 7)), two(sub(t, 9, 10))
  if #t == 10 then
    return "datetime.date(" .. y .. ", " .. mo .. ", " .. d .. ")"
  end
  local h, mi, se = two(sub(t, 12, 13)), two(sub(t, 15, 16)), two(sub(t, 18, 19))
  local rest = sub(t, 20)
  local us = rest:match("^%.([0-9]+)")
  local zone = rest:match("([+%-][0-9][0-9]:[0-9][0-9])$")
  local parts = { y, mo, d, h, mi }
  if us or se ~= "0" then
    parts[#parts + 1] = se
  end
  if us then
    parts[#parts + 1] = two(us)
  end
  local text = "datetime.datetime(" .. concat(parts, ", ")
  if zone then
    local sign = sub(zone, 1, 1) == "-" and -1 or 1
    local mins = sign * (tonumber(sub(zone, 2, 3)) * 60 + tonumber(sub(zone, 5, 6)))
    if mins == 0 then
      text = text .. ", tzinfo=datetime.timezone.utc"
    else
      local secs = mins * 60
      local days = secs // 86400
      local rem = secs - days * 86400
      local delta
      if days == 0 then
        delta = "seconds=" .. format("%d", rem)
      elseif rem == 0 then
        delta = "days=" .. format("%d", days)
      else
        delta = "days=" .. format("%d", days) .. ", seconds=" .. format("%d", rem)
      end
      text = text .. ", tzinfo=datetime.timezone(datetime.timedelta(" .. delta .. "))"
    end
  end
  return text .. ")"
end

local function container_repr(v, busy)
  local mt = getmetatable(v)
  busy = busy or {}
  if busy[v] then
    return mt == List and "[...]" or "{...}"
  end
  busy[v] = true
  local parts = {}
  if mt == List then
    for i = 1, v.n do
      parts[i] = repr(v[i], busy)
    end
    busy[v] = nil
    return "[" .. concat(parts, ", ") .. "]"
  end
  for i = 1, v.n do
    parts[i] = repr(v.k[i], busy) .. ": " .. repr(v.v[i], busy)
  end
  busy[v] = nil
  return "{" .. concat(parts, ", ") .. "}"
end

function repr(v, busy)
  local t = type(v)
  if t == "nil" then
    return "None"
  elseif t == "boolean" then
    return v and "True" or "False"
  elseif t == "string" then
    return str_repr(v)
  elseif t == "number" then
    if mtype(v) == "integer" then
      return format("%d", v)
    end
    return py.float_repr(v)
  end
  local mt = getmetatable(v)
  if mt == Big then
    return v.digits
  elseif mt == Stamp then
    return stamp_repr(v)
  elseif mt == List or mt == Map then
    return container_repr(v, busy)
  elseif mt == Other then
    return v.repr
  end
  return "<?>"
end
py.repr = repr

-- str(): a text as it is, a timestamp as its text, the rest as repr().
function py.str(v)
  if type(v) == "string" then
    return v
  end
  if getmetatable(v) == Stamp then
    return v.text
  end
  return repr(v)
end

-- -- Python's json.dumps(v, separators=(",", ":"), ensure_ascii=False) --

local JSON_ESCAPES = {
  ['"'] = '\\"',
  ["\\"] = "\\\\",
  ["\n"] = "\\n",
  ["\r"] = "\\r",
  ["\t"] = "\\t",
  ["\b"] = "\\b",
  ["\f"] = "\\f",
}

local function json_str(s)
  return '"'
    .. s:gsub('[\0-\31"\\]', function(c)
      return JSON_ESCAPES[c] or format("\\u%04x", byte(c))
    end)
    .. '"'
end

local function json_float(f)
  if f ~= f then
    return "NaN"
  elseif f == math.huge then
    return "Infinity"
  elseif f == -math.huge then
    return "-Infinity"
  end
  return py.float_repr(f)
end

local function json_key(k)
  local t = type(k)
  if t == "string" then
    return k
  elseif t == "boolean" then
    return k and "true" or "false"
  elseif t == "nil" then
    return "null"
  elseif t == "number" then
    return mtype(k) == "integer" and format("%d", k) or json_float(k)
  elseif getmetatable(k) == Big then
    return k.digits
  end
  return nil
end

-- The JSON text of a value, or nil where Python's json raises (a timestamp, a
-- key that is not a scalar, a container inside itself).
function py.json(v, busy)
  local t = type(v)
  if t == "nil" then
    return "null"
  elseif t == "boolean" then
    return v and "true" or "false"
  elseif t == "string" then
    return json_str(v)
  elseif t == "number" then
    return mtype(v) == "integer" and format("%d", v) or json_float(v)
  end
  local mt = getmetatable(v)
  if mt == Big then
    return v.digits
  end
  if mt ~= List and mt ~= Map then
    return nil
  end
  busy = busy or {}
  if busy[v] then
    return nil
  end
  busy[v] = true
  local parts = {}
  for i = 1, v.n do
    local item
    if mt == List then
      item = py.json(v[i], busy)
    else
      local k = json_key(v.k[i])
      local val = k ~= nil and py.json(v.v[i], busy)
      item = val and (json_str(k) .. ":" .. val)
    end
    if not item then
      return nil
    end
    parts[i] = item
  end
  busy[v] = nil
  if mt == List then
    return "[" .. concat(parts, ",") .. "]"
  end
  return "{" .. concat(parts, ",") .. "}"
end

return py
