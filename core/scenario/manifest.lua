-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- The scenario manifest (ADR-P4-6 as amended): its names (decision P4R8), its
-- limits and the objective types. What each key means is in
-- controller/README.md, "Scenarios".
local m = {}

local py = need("py")
local find = string.find

-- The names (P4R8), each matched whole (a final line feed is not part of a
-- name, decision PE24-106). An objective id goes into every scenario event
-- (data key 34), so it is short.
function m.objective_id(s)
  return type(s) == "string" and #s <= 24 and find(s, "^[a-z][a-z0-9_]*$") ~= nil
end

-- A mode id, as the controllers check it on upload: two or more parts of
-- [a-z0-9][a-z0-9_-]* joined by dots.
function m.scenario_id(s)
  if type(s) ~= "string" or not find(s, "^[a-z0-9][a-z0-9_%-]*%.") then
    return false
  end
  for part in (s .. "."):gmatch("([^.]*)%.") do
    if not find(part, "^[a-z0-9][a-z0-9_%-]*$") then
      return false
    end
  end
  return true
end

function m.param_name(s)
  return type(s) == "string" and #s <= 32 and find(s, "^[a-z][a-z0-9_]*$") ~= nil
end

function m.player_role(s)
  return type(s) == "string" and #s <= 24 and find(s, "^[a-z][a-z0-9_]*$") ~= nil
end

-- The objectives package takes up to 8 digits, then #.
function m.code(s)
  return type(s) == "string" and #s >= 1 and #s <= 8 and find(s, "^[0-9]+$") ~= nil
end

m.OBJECTIVES_PACKAGE = "org.atalaia.objectives"
m.MODE_ID_MAX = 63 -- a game's id in a join (protocol/join.md)
-- The scenario leads the game's id and the objectives package follows (decision M6-1).
m.SCENARIO_ID_MAX = m.MODE_ID_MAX - #("+" .. m.OBJECTIVES_PACKAGE)
m.TEAM_NAME_MAX = 23 -- the core's ATALAIA_TEAM_NAME_MAX - 1
m.TEAMS_MAX = 8
m.SQUADS_MAX = 16
m.NODE_NAME_MAX = 24 -- a box's name in its HELLO (protocol/schema/messages.yaml)
m.NAME_MAX = 64 -- bytes: a scenario's or an objective's name
m.DESCRIPTION_MAX = 2000
m.VERSION_MAX = 32
m.OBJECTIVES_MAX = 64
m.NODES_MAX = 64
m.LEVELS_MAX = 10 -- a box's optional level on a multi-story field (ML-8)
m.POINTS_MAX = 100000
m.WINDOW_MAX_MIN = 7 * 24 * 60 -- a week, in minutes
m.LANGS = { "pt", "en", "de", "zh-tw" } -- the objectives package's screens (modes/objectives/node.lua; PKB-9)
m.TRANSLATIONS = { "pt", "de", "zh-tw" } -- texts are in English, with i18n.<lang> for these (P4R8; PKB-9 opened de and zh-tw)
m.NODE_ROLES = { "objective", "bomb_site" } -- org.atalaia.objectives' roles
m.VISIBILITY = { "public", "team", "squad", "hidden" }
-- When the objectives that depend on others become known (SQ-1): `all` at the start (unless hidden), `active`
-- when each opens, so a squad knows only its current objective and the ones it has done.
m.REVEALS = { "all", "active" }
-- Who of an objective's assignee is told it (SQ-3): `members` all of them, `leader` only the squad leaders (the
-- others are told their leader has orders).
m.DISCLOSURES = { "members", "leader" }
m.POLYGON_MAX = 32 -- ATALAIA_GEO_POLYGON_MAX (core/include/atalaia/geo.h)
m.RADIUS_WARN_M = 10 -- a phone's GPS is rarely better than this
m.CMD_PARAMS_MAX = 127 -- a box's CMD buffer (the simulator's field_controller.CMD_PARAMS_MAX)
m.RF_PAYLOAD_MAX = 200 -- a LoRa payload (protocol.RF_PAYLOAD_MAX)

-- One parameter of an objective type: its kind (int, bool, code, destination),
-- whether it is required, and an int's range.
local function param(kind, required, lo, hi)
  return { kind = kind, required = required or false, lo = lo or 0, hi = hi or 0 }
end

local HOLD = param("int", false, 0, 600000)

-- An objective type (ADR-P4-6's table): what it targets ("objective" or
-- "bomb_site", a box's role; "player"; or none), its parameters in order, and
-- whether it needs an assignee team or a time window's end (it is judged then).
local function otype(target, params, needs_team, needs_end)
  local names, by = {}, {}
  for i = 1, #params, 2 do
    names[#names + 1] = params[i]
    by[params[i]] = params[i + 1]
  end
  return {
    target = target,
    param_names = names,
    params = by,
    needs_team = needs_team or false,
    needs_end = needs_end or false,
  }
end

m.TYPE_NAMES =
  { "capture_and_hold", "enter_code", "scan_tags", "escort", "destroy", "defend", "survive" }
m.TYPES = {
  -- Hold the target: completed when the team has held it for duration_s (0: at the capture).
  capture_and_hold = otype(
    "objective",
    { "hold_ms", HOLD, "duration_s", param("int", false, 0, 86400) }
  ),
  -- Type the code on the target's keypad.
  enter_code = otype("objective", { "code", param("code", true) }),
  -- Scan tag_count tags at the target: players' own tags, or with any, any cards (intel).
  scan_tags = otype("objective", { "tag_count", param("int", true, 1, 100), "any", param("bool") }),
  -- A player with the target's role (the VIP) reaches the destination, by position.fix.
  escort = otype(
    "player",
    { "destination", param("destination", true), "max_acc_m", param("int", false, 1, 1000) }
  ),
  -- Arm the bomb at the target and let it explode; a defuse fails it.
  destroy = otype(
    "bomb_site",
    { "hold_ms", HOLD, "defuse_ms", HOLD, "fuse_s", param("int", false, 10, 3600) }
  ),
  -- Keep the target for duration_s from when the objective opens; an enemy capture fails it.
  defend = otype(
    "objective",
    { "duration_s", param("int", true, 1, 86400), "hold_ms", HOLD },
    true
  ),
  -- Keep at least minimum_lives of Respawn's lives until the time window's end.
  survive = otype(nil, { "minimum_lives", param("int", true, 0, 1000) }, true, true),
}

m.TOP_KEYS = {
  "id",
  "version",
  "name",
  "description",
  "author",
  "lang",
  "teams",
  "squads",
  "reveal",
  "disclosure",
  "params",
  "i18n",
  "nodes",
  "objectives",
}
m.OBJECTIVE_KEYS = {
  "id",
  "type",
  "name",
  "description",
  "i18n",
  "target",
  "assignee",
  "params",
  "visibility",
  "depends_on",
  "time_window",
  "effect",
}

-- A text in the language: i18n.<lang>.<key>, else the English one.
function m.translated(entry, lang, key)
  key = key or "name"
  if lang ~= "en" then
    local i18n = py.get(entry, "i18n")
    if py.is_map(i18n) and py.is_map(py.get(i18n, lang)) then
      local value = py.get(py.get(i18n, lang), key)
      if type(value) == "string" and value ~= "" then
        return value
      end
    end
  end
  local value = py.get(entry, key)
  return type(value) == "string" and value or nil
end

-- Whether an objective follows the game's reveal setting (RVL-1): it depends on others and gives
-- no visibility of its own. The runtime (and the controllers' views) hide it until it opens when
-- the game's reveal is "active"; an explicit visibility always wins.
function m.follows_reveal(objective)
  return py.truthy(py.get(objective, "depends_on")) and py.get(objective, "visibility") == nil
end

-- An objective's visibility when the manifest gives none (what it is once revealed: "hidden" is
-- only ever written by a manifest, the game's reveal setting does not change this).
function m.default_visibility(objective, manifest)
  local _ = manifest
  local assignee = py.get(objective, "assignee")
  if not py.truthy(assignee) then
    assignee = py.map()
  end
  if py.is_map(assignee) and py.get(assignee, "squad") ~= nil then
    return "squad"
  end
  if py.is_map(assignee) and py.get(assignee, "team") ~= nil then
    return "team"
  end
  return "public"
end

return m
