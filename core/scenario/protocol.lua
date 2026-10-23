-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- The size of a scenario event on the radio: the CBOR payload of an EVENT
-- message (protocol/README.md, core/src/codec.c), from the schema's numbers as
-- the core's generated tables hold them (PROTOCOL, set by core/src/scenario.c).
local protocol = {}

local C = PROTOCOL

-- The bytes of a CBOR head for an unsigned number or a length.
local function head(n)
  if n < 24 then
    return 1
  elseif n < 256 then
    return 2
  elseif n < 65536 then
    return 3
  elseif n < 4294967296 then
    return 5
  end
  return 9
end

local function text(s)
  return head(#s) + #s
end

-- The payload of an event from node 0 with the largest sequence number and
-- game time, of team `team`, with the data `fields` ({ name, text, ... }: text
-- values), at priority critical: what the controller's codec would encode.
function protocol.event_size(type_name, team, fields)
  local id, default_prio = C.event(type_name)
  local entries, size = 4, 0
  size = size + 1 + head(0) -- node
  size = size + 1 + head(0xFFFF) -- seq
  size = size + 1 + head(0xFFFFFFFF) -- t
  size = size + 1 + (id and head(id) or text(type_name)) -- type: its id, or a custom event's name
  if team ~= 0 then
    entries = entries + 1
    size = size + 1 + head(team)
  end
  if default_prio ~= C.CRITICAL then
    entries = entries + 1
    size = size + 1 + head(C.CRITICAL)
  end
  if #fields > 0 then
    entries = entries + 1
    local data = head(#fields // 2)
    for i = 1, #fields, 2 do
      local key = C.data_key(fields[i])
      data = data + (key and head(key) or text(fields[i])) + text(fields[i + 1])
    end
    size = size + 1 + data
  end
  return head(entries) + size
end

return protocol
