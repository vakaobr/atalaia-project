-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- mode.yaml's text, as the Pi first wrote it with PyYAML 6:
-- yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100).
-- A port of the parts of PyYAML's representer, serializer and emitter such a
-- document uses (decision PE24-109): block maps and lists in their order, []
-- and {} for empty ones, None, booleans, ints and floats as PyYAML writes
-- them, and texts plain, single-quoted or double-quoted by PyYAML's choice
-- (its scalar analysis and its YAML 1.1 implicit resolvers), folded at 100
-- columns counted in code points; a list or map that appears twice is written
-- once with an anchor (&id001) and then as its alias (*id001).
local yaml = {}

local py = need("py")

local find, sub, format = string.find, string.sub, string.format
local concat = table.concat

local BEST_INDENT = 2
local BEST_WIDTH = 100

-- -- The YAML 1.1 implicit resolvers (resolver.py): a text that would read back
-- -- as something else is not written plain. --

local BOOLS = {}
for _, w in ipairs({
  "yes",
  "Yes",
  "YES",
  "no",
  "No",
  "NO",
  "true",
  "True",
  "TRUE",
  "false",
  "False",
  "FALSE",
  "on",
  "On",
  "ON",
  "off",
  "Off",
  "OFF",
}) do
  BOOLS[w] = true
end

-- [0-5]?[0-9] groups after a colon, from position i: where they end, or nil.
local function sexagesimal(s, i)
  local any = false
  while sub(s, i, i) == ":" do
    local two = find(s, "^[0-5][0-9]", i + 1)
    if two then
      i = i + 3
    elseif find(s, "^[0-9]", i + 1) then
      i = i + 2
    else
      return nil
    end
    any = true
  end
  return any and i or nil
end

local function is_float(s)
  if
    find(s, "^[+%-]?[0-9][0-9_]*%.[0-9_]*$")
    or find(s, "^[+%-]?[0-9][0-9_]*%.[0-9_]*[eE][+%-][0-9]+$")
  then
    return true
  end
  if find(s, "^%.[0-9][0-9_]*$") or find(s, "^%.[0-9][0-9_]*[eE][+%-][0-9]+$") then
    return true
  end
  local _, e = find(s, "^[+%-]?[0-9][0-9_]*")
  if e then
    local after = sexagesimal(s, e + 1)
    if after and find(s, "^%.[0-9_]*$", after) then
      return true
    end
  end
  local inf = s:match("^[+%-]?%.(.*)$")
  if inf == "inf" or inf == "Inf" or inf == "INF" then
    return true
  end
  return s == ".nan" or s == ".NaN" or s == ".NAN"
end

local function is_int(s)
  if
    find(s, "^[+%-]?0b[01_]+$")
    or find(s, "^[+%-]?0[0-7_]+$")
    or find(s, "^[+%-]?0$")
    or find(s, "^[+%-]?[1-9][0-9_]*$")
    or find(s, "^[+%-]?0x[0-9a-fA-F_]+$")
  then
    return true
  end
  local _, e = find(s, "^[+%-]?[1-9][0-9_]*")
  if e then
    local after = sexagesimal(s, e + 1)
    return after ~= nil and after == #s + 1
  end
  return false
end

local function is_timestamp(s)
  if find(s, "^[0-9][0-9][0-9][0-9]%-[0-9][0-9]%-[0-9][0-9]$") then
    return true
  end
  local _, e = find(s, "^[0-9][0-9][0-9][0-9]%-[0-9][0-9]?%-[0-9][0-9]?[Tt]")
  if not e then
    _, e = find(s, "^[0-9][0-9][0-9][0-9]%-[0-9][0-9]?%-[0-9][0-9]?[ \t]+")
  end
  if not e then
    return false
  end
  local _, t = find(s, "^[0-9][0-9]?:[0-9][0-9]:[0-9][0-9]", e + 1)
  if not t then
    return false
  end
  local rest = sub(s, t + 1)
  rest = rest:gsub("^%.[0-9]*", "", 1)
  return rest == ""
    or find(rest, "^[ \t]*Z$") ~= nil
    or find(rest, "^[ \t]*[+%-][0-9][0-9]?$") ~= nil
    or find(rest, "^[ \t]*[+%-][0-9][0-9]?:[0-9][0-9]$") ~= nil
end

-- Whether PyYAML's resolver reads a plain text as something other than a text
-- (its "$" also matches before a final line feed).
function yaml.resolves_to_other(s)
  if sub(s, -1) == "\n" then
    s = sub(s, 1, -2)
  end
  return BOOLS[s]
    or is_float(s)
    or is_int(s)
    or s == "<<"
    or s == "~"
    or s == "null"
    or s == "Null"
    or s == "NULL"
    or s == ""
    or is_timestamp(s)
    or s == "="
    or s == "!"
    or s == "&"
    or s == "*"
    or false
end

-- -- The representer: the text of a scalar, and whether it is a text --

local function float_text(f)
  if f ~= f then
    return ".nan"
  elseif f == math.huge then
    return ".inf"
  elseif f == -math.huge then
    return "-.inf"
  end
  local v = py.float_repr(f)
  if not find(v, ".", 1, true) and find(v, "e", 1, true) then
    v = v:gsub("e", ".0e", 1)
  end
  return v
end

-- The scalar text of a value, and whether it is a str (only a str may need quotes).
local function scalar(v)
  local t = type(v)
  if t == "string" then
    return v, true
  elseif t == "nil" then
    return "null", false
  elseif t == "boolean" then
    return v and "true" or "false", false
  elseif t == "number" then
    if math.type(v) == "integer" then
      return format("%d", v), false
    end
    return float_text(v), false
  elseif getmetatable(v) == py.Big then
    return v.digits, false
  elseif getmetatable(v) == py.Stamp then
    return v.text, false
  end
  error("mode.yaml cannot hold " .. py.kind(v))
end

-- -- The emitter --

local SPECIAL_BREAKS =
  { ["\n"] = true, ["\194\133"] = true, ["\226\128\168"] = true, ["\226\128\169"] = true }
local WHITESPACE = {
  ["\0"] = true,
  [" "] = true,
  ["\t"] = true,
  ["\r"] = true,
  ["\n"] = true,
  ["\194\133"] = true,
  ["\226\128\168"] = true,
  ["\226\128\169"] = true,
}

local Emitter = {}
Emitter.__index = Emitter

local function new_emitter()
  return setmetatable({
    out = {},
    indents = {},
    indent = nil,
    flow_level = 0,
    root_context = false,
    sequence_context = false,
    mapping_context = false,
    simple_key_context = false,
    column = 0,
    whitespace = true,
    indention = true,
    open_ended = false,
  }, Emitter)
end

function Emitter:write(data, len)
  self.out[#self.out + 1] = data
  self.column = self.column + (len or py.len(data))
end

function Emitter:increase_indent(flow, indentless)
  self.indents[#self.indents + 1] = self.indent or false
  if self.indent == nil then
    self.indent = flow and BEST_INDENT or 0
  elseif not indentless then
    self.indent = self.indent + BEST_INDENT
  end
end

function Emitter:pop_indent()
  local v = self.indents[#self.indents]
  self.indents[#self.indents] = nil
  if v == false then
    v = nil
  end
  self.indent = v
end

function Emitter:write_indicator(indicator, need_whitespace, whitespace, indention)
  local data
  if self.whitespace or not need_whitespace then
    data = indicator
  else
    data = " " .. indicator
  end
  self.whitespace = whitespace or false
  self.indention = self.indention and (indention or false)
  self.open_ended = false
  self:write(data)
end

function Emitter:write_line_break(data)
  self.whitespace = true
  self.indention = true
  self.column = 0
  self.out[#self.out + 1] = data or "\n"
end

function Emitter:write_indent()
  local indent = self.indent or 0
  if
    not self.indention
    or self.column > indent
    or (self.column == indent and not self.whitespace)
  then
    self:write_line_break()
  end
  if self.column < indent then
    self.whitespace = true
    self.out[#self.out + 1] = string.rep(" ", indent - self.column)
    self.column = indent
  end
end

-- PyYAML's analyze_scalar, for allow_unicode=True.
local function analyze(text)
  local chars, n = py.chars(text)
  if n == 0 then
    return {
      chars = chars,
      n = 0,
      empty = true,
      multiline = false,
      allow_flow_plain = false,
      allow_block_plain = true,
      allow_single_quoted = true,
      allow_double_quoted = true,
      allow_block = false,
    }
  end
  local block_indicators, flow_indicators, line_breaks, special_characters =
    false, false, false, false
  local leading_space, leading_break, trailing_space, trailing_break = false, false, false, false
  local break_space, space_break = false, false
  if sub(text, 1, 3) == "---" or sub(text, 1, 3) == "..." then
    block_indicators = true
    flow_indicators = true
  end
  local preceded_by_whitespace = true
  local followed_by_whitespace = n == 1 or WHITESPACE[chars[2]] == true
  local previous_space, previous_break = false, false
  for index = 1, n do
    local ch = chars[index]
    if index == 1 then
      if find("#,[]{}&*!|>'\"%@`", ch, 1, true) and #ch == 1 then
        flow_indicators = true
        block_indicators = true
      end
      if ch == "?" or ch == ":" then
        flow_indicators = true
        if followed_by_whitespace then
          block_indicators = true
        end
      end
      if ch == "-" and followed_by_whitespace then
        flow_indicators = true
        block_indicators = true
      end
    else
      if ch == "," or ch == "?" or ch == "[" or ch == "]" or ch == "{" or ch == "}" then
        flow_indicators = true
      end
      if ch == ":" then
        flow_indicators = true
        if followed_by_whitespace then
          block_indicators = true
        end
      end
      if ch == "#" and preceded_by_whitespace then
        flow_indicators = true
        block_indicators = true
      end
    end
    if SPECIAL_BREAKS[ch] then
      line_breaks = true
    end
    local c = py.decode_cp(ch, 1)
    if not (ch == "\n" or (c >= 0x20 and c <= 0x7E)) then
      if
        not (
          (
            c == 0x85
            or (c >= 0xA0 and c <= 0xD7FF)
            or (c >= 0xE000 and c <= 0xFFFD)
            or (c >= 0x10000 and c < 0x10FFFF)
          ) and c ~= 0xFEFF
        )
      then
        special_characters = true
      end
    end
    if ch == " " then
      if index == 1 then
        leading_space = true
      end
      if index == n then
        trailing_space = true
      end
      if previous_break then
        break_space = true
      end
      previous_space = true
      previous_break = false
    elseif SPECIAL_BREAKS[ch] then
      if index == 1 then
        leading_break = true
      end
      if index == n then
        trailing_break = true
      end
      if previous_space then
        space_break = true
      end
      previous_space = false
      previous_break = true
    else
      previous_space = false
      previous_break = false
    end
    preceded_by_whitespace = WHITESPACE[ch] == true
    followed_by_whitespace = index + 1 >= n or WHITESPACE[chars[index + 2]] == true
  end
  local a = {
    chars = chars,
    n = n,
    empty = false,
    multiline = line_breaks,
    allow_flow_plain = true,
    allow_block_plain = true,
    allow_single_quoted = true,
    allow_double_quoted = true,
    allow_block = true,
  }
  if leading_space or leading_break or trailing_space or trailing_break then
    a.allow_flow_plain = false
    a.allow_block_plain = false
  end
  if trailing_space then
    a.allow_block = false
  end
  if break_space then
    a.allow_flow_plain = false
    a.allow_block_plain = false
    a.allow_single_quoted = false
  end
  if space_break or special_characters then
    a.allow_flow_plain = false
    a.allow_block_plain = false
    a.allow_single_quoted = false
    a.allow_block = false
  end
  if line_breaks then
    a.allow_flow_plain = false
    a.allow_block_plain = false
  end
  if flow_indicators then
    a.allow_flow_plain = false
  end
  if block_indicators then
    a.allow_block_plain = false
  end
  return a
end

function Emitter:choose_scalar_style(a, implicit)
  if implicit then
    if
      not (self.simple_key_context and (a.empty or a.multiline))
      and (
        (self.flow_level > 0 and a.allow_flow_plain)
        or (self.flow_level == 0 and a.allow_block_plain)
      )
    then
      return ""
    end
  end
  if a.allow_single_quoted and not (self.simple_key_context and a.multiline) then
    return "'"
  end
  return '"'
end

local function slice(chars, i, j)
  -- chars[i..j-1] (1-based, j exclusive), as text
  return concat(chars, "", i, j - 1)
end

function Emitter:write_plain(a, split)
  if self.root_context then
    self.open_ended = true
  end
  local chars, n = a.chars, a.n
  if n == 0 then
    return
  end
  if not self.whitespace then
    self:write(" ", 1)
  end
  self.whitespace = false
  self.indention = false
  local spaces, breaks = false, false
  local start, e = 1, 1
  while e <= n + 1 do
    local ch = e <= n and chars[e] or nil
    if spaces then
      if ch ~= " " then
        if start + 1 == e and self.column > BEST_WIDTH and split then
          self:write_indent()
          self.whitespace = false
          self.indention = false
        else
          self:write(slice(chars, start, e), e - start)
        end
        start = e
      end
    elseif breaks then
      if not SPECIAL_BREAKS[ch] then
        if chars[start] == "\n" then
          self:write_line_break()
        end
        for k = start, e - 1 do
          local br = chars[k]
          self:write_line_break(br == "\n" and nil or br)
        end
        self:write_indent()
        self.whitespace = false
        self.indention = false
        start = e
      end
    else
      if ch == nil or ch == " " or SPECIAL_BREAKS[ch] then
        self:write(slice(chars, start, e), e - start)
        start = e
      end
    end
    if ch ~= nil then
      spaces = ch == " "
      breaks = SPECIAL_BREAKS[ch] == true
    end
    e = e + 1
  end
end

function Emitter:write_single_quoted(a, split)
  self:write_indicator("'", true)
  local chars, n = a.chars, a.n
  local spaces, breaks = false, false
  local start, e = 1, 1
  while e <= n + 1 do
    local ch = e <= n and chars[e] or nil
    if spaces then
      if ch == nil or ch ~= " " then
        if start + 1 == e and self.column > BEST_WIDTH and split and start ~= 1 and e ~= n + 1 then
          self:write_indent()
        else
          self:write(slice(chars, start, e), e - start)
        end
        start = e
      end
    elseif breaks then
      if ch == nil or not SPECIAL_BREAKS[ch] then
        if chars[start] == "\n" then
          self:write_line_break()
        end
        for k = start, e - 1 do
          local br = chars[k]
          self:write_line_break(br == "\n" and nil or br)
        end
        self:write_indent()
        start = e
      end
    else
      if ch == nil or ch == " " or SPECIAL_BREAKS[ch] or ch == "'" then
        if start < e then
          self:write(slice(chars, start, e), e - start)
          start = e
        end
      end
    end
    if ch == "'" then
      self:write("''", 2)
      start = e + 1
    end
    if ch ~= nil then
      spaces = ch == " "
      breaks = SPECIAL_BREAKS[ch] == true
    end
    e = e + 1
  end
  self:write_indicator("'", false)
end

local ESCAPES = {
  [0x00] = "0",
  [0x07] = "a",
  [0x08] = "b",
  [0x09] = "t",
  [0x0A] = "n",
  [0x0B] = "v",
  [0x0C] = "f",
  [0x0D] = "r",
  [0x1B] = "e",
  [0x22] = '"',
  [0x5C] = "\\",
  [0x85] = "N",
  [0xA0] = "_",
  [0x2028] = "L",
  [0x2029] = "P",
}

function Emitter:write_double_quoted(a, split)
  self:write_indicator('"', true)
  local chars, n = a.chars, a.n
  local start, e = 1, 1
  while e <= n + 1 do
    local ch = e <= n and chars[e] or nil
    local c = ch and py.decode_cp(ch, 1)
    if
      ch == nil
      or c == 0x22
      or c == 0x5C
      or c == 0x85
      or c == 0x2028
      or c == 0x2029
      or c == 0xFEFF
      or not (
        (c >= 0x20 and c <= 0x7E)
        or (c >= 0xA0 and c <= 0xD7FF)
        or (c >= 0xE000 and c <= 0xFFFD)
      )
    then
      if start < e then
        self:write(slice(chars, start, e), e - start)
        start = e
      end
      if ch ~= nil then
        local data
        if ESCAPES[c] then
          data = "\\" .. ESCAPES[c]
        elseif c <= 0xFF then
          data = format("\\x%02X", c)
        elseif c <= 0xFFFF then
          data = format("\\u%04X", c)
        else
          data = format("\\U%08X", c)
        end
        self:write(data, #data)
        start = e + 1
      end
    end
    if
      1 < e
      and e < n
      and (ch == " " or start >= e)
      and self.column + (e - start) > BEST_WIDTH
      and split
    then
      local data = slice(chars, start, e) .. "\\"
      if start < e then
        start = e
      end
      self:write(data)
      self:write_indent()
      self.whitespace = false
      self.indention = false
      if chars[start] == " " then
        self:write("\\", 1)
      end
    end
    e = e + 1
  end
  self:write_indicator('"', false)
end

-- -- Nodes --

-- Which lists and maps appear more than once: their anchors, in the order a
-- second sight finds them (serializer.py, anchor_node).
local function anchors(doc)
  local seen, anchor, count = {}, {}, 0
  local function walk(v)
    local mt = getmetatable(v)
    if mt ~= py.List and mt ~= py.Map then
      return
    end
    if seen[v] then
      if not anchor[v] then
        count = count + 1
        anchor[v] = format("id%03d", count)
      end
      return
    end
    seen[v] = true
    if mt == py.List then
      for i = 1, v.n do
        walk(v[i])
      end
    else
      for i = 1, v.n do
        walk(v.k[i])
        walk(v.v[i])
      end
    end
  end
  walk(doc)
  return anchor
end

function Emitter:node(v, root, sequence, mapping, simple_key, analysis)
  self.root_context = root or false
  self.sequence_context = sequence or false
  self.mapping_context = mapping or false
  self.simple_key_context = simple_key or false
  local mt = getmetatable(v)
  if (mt == py.List or mt == py.Map) and self.done[v] then
    self:write_indicator("*" .. self.anchor[v], true)
    return
  end
  if mt == py.List or mt == py.Map then
    self.done[v] = true
    if self.anchor[v] then
      self:write_indicator("&" .. self.anchor[v], true)
    end
  end
  if mt == py.List then
    if self.flow_level > 0 or v.n == 0 then
      self:write_indicator("[", true, true)
      self.flow_level = self.flow_level + 1
      self:increase_indent(true)
      self:pop_indent()
      self.flow_level = self.flow_level - 1
      self:write_indicator("]", false)
      return
    end
    local indentless = self.mapping_context and not self.indention
    self:increase_indent(false, indentless)
    for i = 1, v.n do
      self:write_indent()
      self:write_indicator("-", true, false, true)
      self:node(v[i], false, true)
    end
    self:pop_indent()
    return
  elseif mt == py.Map then
    if self.flow_level > 0 or v.n == 0 then
      self:write_indicator("{", true, true)
      self.flow_level = self.flow_level + 1
      self:increase_indent(true)
      self:pop_indent()
      self.flow_level = self.flow_level - 1
      self:write_indicator("}", false)
      return
    end
    self:increase_indent(false)
    for i = 1, v.n do
      local k, val = v.k[i], v.v[i]
      self:write_indent()
      local simple, ka = self:check_simple_key(k)
      if simple then
        self:node(k, false, false, true, true, ka)
        self:write_indicator(":", false)
        self:node(val, false, false, true)
      else
        self:write_indicator("?", true, false, true)
        self:node(k, false, false, true, false, ka)
        self:write_indent()
        self:write_indicator(":", true, false, true)
        self:node(val, false, false, true)
      end
    end
    self:pop_indent()
    return
  end
  -- A scalar: its style is chosen before the indent grows (process_tag), then written.
  local text, is_str = scalar(v)
  local a = analysis or analyze(text)
  local implicit = not (is_str and yaml.resolves_to_other(text))
  local style = self:choose_scalar_style(a, implicit)
  self:increase_indent(true)
  local split = not self.simple_key_context
  if style == '"' then
    self:write_double_quoted(a, split)
  elseif style == "'" then
    self:write_single_quoted(a, split)
  else
    self:write_plain(a, split)
  end
  self:pop_indent()
end

-- check_simple_key: a key written as "key:" (a scalar on one line, shorter
-- than 128 code points, or an empty list or map); else "? key".
function Emitter:check_simple_key(k)
  local mt = getmetatable(k)
  if mt == py.List or mt == py.Map then
    local length = 0
    if self.anchor[k] then
      length = #self.anchor[k]
    end
    return length < 128 and (self.done[k] or k.n == 0), nil
  end
  local text = scalar(k)
  local a = analyze(text)
  return a.n < 128 and not a.empty and not a.multiline, a
end

-- The document's text: a map at its root.
function yaml.dump(doc)
  local e = new_emitter()
  e.anchor = anchors(doc)
  e.done = {}
  e:node(doc, true)
  -- The document's end: a line break, and "..." only after a plain root scalar.
  e:write_indent()
  if e.open_ended then
    e:write_indicator("...", true)
    e:write_indent()
  end
  return concat(e.out)
end

return yaml
