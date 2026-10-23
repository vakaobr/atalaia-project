-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Checks a scenario manifest before it is compiled (ADR-P4-6's rules, as
-- amended; decision M7-6).
--
-- validate(manifest) returns every problem it finds, each with the path of the
-- value (objectives[2].params.code), a short code that programs match
-- (protocol/vectors/scenario.json) and a sentence for the GM. Errors stop the
-- compiler; warnings do not.
local validator = {}

local py = need("py")
local m = need("manifest")
local luagen = need("luagen")
local protocol = need("protocol")

local concat = table.concat
local format = string.format

local ERROR, WARNING = "error", "warning"
validator.ERROR, validator.WARNING = ERROR, WARNING

local repr, str = py.repr, py.str

local function join(list, sep)
  return concat(list, sep or ", ")
end

-- -- Problems --

local Checker = {}
Checker.__index = Checker

function Checker:add(path, code, message, level)
  local p = { path = path, code = code, message = message, level = level }
  self.problems[#self.problems + 1] = p
  if level == ERROR then
    self.error_count = self.error_count + 1
  end
end

function Checker:err(path, code, message)
  self:add(path, code, message, ERROR)
end

function Checker:warn(path, code, message)
  self:add(path, code, message, WARNING)
end

local function in_list(v, list)
  return py.one_of(v, list)
end

function Checker:unknown_keys(value, allowed, path)
  for i = 1, value.n do
    local key = value.k[i]
    if not in_list(key, allowed) then
      local where = path ~= "" and (path .. "." .. str(key)) or str(key)
      self:err(
        where,
        "unknown_key",
        "unknown key " .. repr(key) .. " (allowed: " .. join(allowed) .. ")"
      )
    end
  end
end

function Checker:text(value, path, max_bytes, required, one_line)
  if one_line == nil then
    one_line = true
  end
  if value == nil then
    if required then
      self:err(path, "missing", "required")
    end
    return false
  end
  if type(value) ~= "string" or (required and py.blank(value)) then
    self:err(path, "bad_text", "must be a non-empty text")
    return false
  end
  if #value > max_bytes then
    self:err(path, "too_long", format("at most %d bytes", max_bytes))
    return false
  end
  if one_line and py.has_controls(value) then
    self:err(path, "bad_text", "must be one line, without control characters")
    return false
  end
  return true
end

-- Texts (and keys) with a surrogate code point: half of a UTF-16 pair, which
-- no UTF-8 text holds (decision PE24-107). A manifest read from JSON or YAML
-- text has its pairs joined by its reader, so only a lone half is left; a map
-- built in code may still hold one.
local function surrogates(self, value, path, seen)
  if type(value) == "string" then
    if py.has_surrogate(value) then
      self:err(
        path,
        "bad_unicode",
        "not valid Unicode: half of a surrogate pair (a character past U+FFFF "
          .. "needs both halves, \\ud83d\\ude00)"
      )
    end
    return
  end
  local mt = getmetatable(value)
  if (mt ~= py.List and mt ~= py.Map) or seen[value] then
    return
  end
  seen[value] = true
  if mt == py.List then
    for i = 1, value.n do
      surrogates(self, value[i], path .. "[" .. (i - 1) .. "]", seen)
    end
    return
  end
  for i = 1, value.n do
    local key = value.k[i]
    if type(key) == "string" and py.has_surrogate(key) then
      self:err(path, "bad_unicode", "a key that is not valid Unicode: half of a surrogate pair")
    else
      surrogates(self, value.v[i], path ~= "" and (path .. "." .. str(key)) or str(key), seen)
    end
  end
end

-- -- The manifest --

function Checker:run()
  local mf = self.m
  -- Half a surrogate pair anywhere: said alone, since no text with one can be
  -- measured or written as UTF-8 (decision PE24-107).
  surrogates(self, mf, "", {})
  if #self.problems > 0 then
    return self.problems
  end
  self:unknown_keys(mf, m.TOP_KEYS, "")
  self:check_id()
  local version = py.get(mf, "version")
  if py.is_int(version) or py.is_float(version) then
    version = str(version)
  end
  self:text(version, "version", m.VERSION_MAX, true)
  self:text(py.get(mf, "name"), "name", m.NAME_MAX, true)
  self:text(py.get(mf, "description"), "description", m.DESCRIPTION_MAX, false, false)
  self:text(py.get(mf, "author"), "author", m.NAME_MAX, false)
  local lang = py.getd(mf, "lang", "pt")
  if not in_list(lang, m.LANGS) then
    self:err("lang", "bad_lang", "the boxes' screens are in " .. join(m.LANGS, " or "))
  end
  self.teams = self:check_teams()
  local squads = py.getd(mf, "squads", 0)
  if not py.int_in(squads, 0, m.SQUADS_MAX) then
    self:err(
      "squads",
      "bad_squads",
      format("a number of squads per team, 0 (none) to %d", m.SQUADS_MAX)
    )
    squads = 0
  end
  self.squads = squads
  self.params = self:check_params()
  self:check_i18n(py.get(mf, "i18n"), "i18n", { "name", "description", "params" })
  self.nodes, self.node_names = self:check_nodes()
  local objectives = py.get(mf, "objectives")
  if not py.is_list(objectives) or objectives.n == 0 then
    self:err(
      "objectives",
      objectives == nil and "missing" or "bad_objectives",
      "a list of at least one objective"
    )
    return self.problems
  end
  if objectives.n > m.OBJECTIVES_MAX then
    self:err("objectives", "too_many", format("at most %d objectives", m.OBJECTIVES_MAX))
  end
  self.ids = {}
  for i = 1, objectives.n do
    local o = objectives[i]
    local oid = py.is_map(o) and py.get(o, "id") or nil
    if m.objective_id(oid) then
      if self.ids[oid] ~= nil then
        self:err(
          format("objectives[%d].id", i - 1),
          "duplicate_id",
          repr(oid) .. format(" is already the id of objectives[%d]", self.ids[oid])
        )
      else
        self.ids[oid] = i - 1
      end
    end
  end
  self.revealed_by = {}
  for i = 1, objectives.n do
    local o = objectives[i]
    local effect = py.is_map(o) and py.get(o, "effect") or nil
    if py.is_map(effect) and py.is_list(py.get(effect, "reveal")) then
      local reveal = py.get(effect, "reveal")
      for j = 1, reveal.n do
        if type(reveal[j]) == "string" then
          self.revealed_by[reveal[j]] = true
        end
      end
    end
  end
  local targeted = {}
  for i = 1, objectives.n do
    self:check_objective(i - 1, objectives[i], targeted)
  end
  self:check_cycles(objectives)
  for _, name in ipairs(self.node_names) do
    if targeted[name] == nil then
      self:warn("nodes." .. name, "unused_node", "no objective targets this node")
    end
  end
  return self.problems
end

function Checker:check_id()
  local sid = py.get(self.m, "id")
  if sid == nil then
    self:err("id", "missing", "required: the package id, like org.club.foxhound")
  elseif not m.scenario_id(sid) then
    self:err(
      "id",
      "bad_id",
      "a package id like org.club.foxhound: lowercase letters, digits, - and _, in at "
        .. "least two parts joined by dots"
    )
  elseif #sid > m.SCENARIO_ID_MAX then
    self:err(
      "id",
      "id_too_long",
      format(
        "at most %d bytes, so that %s+%s fits a join's %d",
        m.SCENARIO_ID_MAX,
        sid,
        m.OBJECTIVES_PACKAGE,
        m.MODE_ID_MAX
      )
    )
  elseif sid == m.OBJECTIVES_PACKAGE or sid:sub(1, #"org.atalaia.") == "org.atalaia." then
    self:err("id", "bad_id", "org.atalaia. is the built-in modes' namespace: use your club's")
  end
end

function Checker:check_teams()
  local teams = py.getd(self.m, "teams", py.list({ "red", "blue" }, 2))
  local ok = py.is_list(teams) and teams.n >= 1 and teams.n <= m.TEAMS_MAX
  if ok then
    for i = 1, teams.n do
      local t = teams[i]
      if
        not (type(t) == "string" and #t > 0 and #t <= m.TEAM_NAME_MAX and not py.has_controls(t))
      then
        ok = false
        break
      end
    end
  end
  if not ok then
    self:err(
      "teams",
      "bad_teams",
      format(
        "a list of 1 to %d team names of 1 to %d bytes, as the game names its "
          .. "teams (red, blue, ...)",
        m.TEAMS_MAX,
        m.TEAM_NAME_MAX
      )
    )
    local out = {}
    if py.is_list(teams) then
      for i = 1, teams.n do
        if type(teams[i]) == "string" then
          out[#out + 1] = teams[i]
        end
      end
    end
    return out
  end
  local seen, out = {}, {}
  local twice = false
  for i = 1, teams.n do
    if seen[teams[i]] then
      twice = true
    end
    seen[teams[i]] = true
    out[i] = teams[i]
  end
  if twice then
    self:err("teams", "bad_teams", "a team is named twice")
  end
  return out
end

function Checker:check_params()
  local params = py.get(self.m, "params")
  if params == nil then
    return {}
  end
  if not py.is_map(params) then
    self:err("params", "bad_params", "a map of parameter names to their schema")
    return {}
  end
  local good = {}
  for i = 1, params.n do
    local name, spec = params.k[i], params.v[i]
    local path = "params." .. str(name)
    if not m.param_name(name) then
      self:err(path, "bad_name", "1-32 of a-z, 0-9 and _, starting with a letter")
    elseif not py.is_map(spec) then
      self:err(path, "bad_params", "a map: { type: int, min, max, default, label }")
    else
      self:unknown_keys(spec, { "type", "min", "max", "default", "label", "gm_only" }, path)
      if py.get(spec, "type") ~= "int" then
        self:err(
          path .. ".type",
          "bad_param_type",
          "a scenario's parameters are int (whole numbers): objectives' " .. "points"
        )
      else
        local lo, hi = py.getd(spec, "min", 0), py.getd(spec, "max", m.POINTS_MAX)
        local default = py.get(spec, "default")
        if not py.int_in(lo, 0, m.POINTS_MAX) or not py.int_in(hi, 0, m.POINTS_MAX) or lo > hi then
          self:err(
            path,
            "bad_range",
            format("min and max are whole numbers from 0 to %d, min <= max", m.POINTS_MAX)
          )
        elseif not py.int_in(default, lo, hi) then
          self:err(
            path .. ".default",
            "bad_default",
            format("a whole number from %d to %d", lo, hi)
          )
        else
          self:text(py.get(spec, "label"), path .. ".label", m.NAME_MAX * 2, false)
          if type(py.getd(spec, "gm_only", false)) ~= "boolean" then
            self:err(path .. ".gm_only", "bad_bool", "true or false")
          end
          good[name] = spec
        end
      end
    end
  end
  return good
end

function Checker:check_i18n(i18n, path, keys)
  if i18n == nil then
    return
  end
  if not py.is_map(i18n) then
    self:err(path, "bad_i18n", "a map of a language (pt) to its texts")
    return
  end
  for i = 1, i18n.n do
    local lang, strings = i18n.k[i], i18n.v[i]
    local where = path .. "." .. str(lang)
    if not in_list(lang, m.TRANSLATIONS) then
      self:err(
        where,
        "bad_lang",
        "texts are in English with translations in " .. join(m.TRANSLATIONS)
      )
    elseif not py.is_map(strings) then
      self:err(where, "bad_i18n", "a map of " .. join(keys))
    else
      self:unknown_keys(strings, keys, where)
      self:text(py.get(strings, "name"), where .. ".name", m.NAME_MAX, false)
      self:text(
        py.get(strings, "description"),
        where .. ".description",
        m.DESCRIPTION_MAX,
        false,
        false
      )
      local labels = py.get(strings, "params")
      if labels ~= nil and in_list("params", keys) then
        if not py.is_map(labels) then
          self:err(where .. ".params", "bad_i18n", "a map of parameter names to labels")
        else
          local params = py.get(self.m, "params")
          for j = 1, labels.n do
            local name, label = labels.k[j], labels.v[j]
            if not py.is_map(params) or not py.has(params, name) then
              self:err(
                where .. ".params." .. str(name),
                "unknown_param",
                repr(name) .. " is not a parameter"
              )
            else
              self:text(label, where .. ".params." .. str(name), m.NAME_MAX * 2, true)
            end
          end
        end
      end
    end
  end
end

function Checker:check_nodes()
  local nodes = py.get(self.m, "nodes")
  if nodes == nil then
    return {}, {}
  end
  if not py.is_map(nodes) then
    self:err(
      "nodes",
      "bad_nodes",
      "a map of node names to { role: objective } or { role: bomb_site }"
    )
    return {}, {}
  end
  if nodes.n > m.NODES_MAX then
    self:err("nodes", "too_many", format("at most %d nodes", m.NODES_MAX))
  end
  local good, names = {}, {}
  for i = 1, nodes.n do
    local name, spec = nodes.k[i], nodes.v[i]
    local path = "nodes." .. str(name)
    if
      type(name) ~= "string"
      or py.blank(name)
      or #name > m.NODE_NAME_MAX
      or py.has_controls(name)
    then
      self:err(
        path,
        "bad_name",
        format(
          "a node's name: 1 to %d bytes on one line, as the GM names the box in the " .. "console",
          m.NODE_NAME_MAX
        )
      )
    elseif not py.is_map(spec) then
      self:err(
        path,
        "bad_node",
        "a map: { role: objective }, { role: bomb_site } or { player: true, role: vip }"
      )
    else
      self:unknown_keys(spec, { "role", "player", "level" }, path)
      local player = py.getd(spec, "player", false)
      local role = py.get(spec, "role")
      local ok = true
      if type(player) ~= "boolean" then
        self:err(path .. ".player", "bad_bool", "true or false")
        ok = false
      elseif player then
        role = py.getd(spec, "role", "vip")
        if not m.player_role(role) then
          self:err(path .. ".role", "bad_role", "a player's check-in role: 1-24 of a-z, 0-9 and _")
          ok = false
        end
      elseif not in_list(role, m.NODE_ROLES) then
        self:err(
          path .. ".role",
          "bad_role",
          "a box runs "
            .. m.OBJECTIVES_PACKAGE
            .. ": role "
            .. join(m.NODE_ROLES, " or ")
            .. " (a player: player: true)"
        )
        ok = false
      end
      if ok then
        local level = py.get(spec, "level")
        if level ~= nil and (player or not py.int_in(level, 0, m.LEVELS_MAX - 1)) then
          -- The level of a multi-story field the box goes on (decision ML-8); a player has none.
          self:err(
            path .. ".level",
            "bad_level",
            format("a box's level of the field, 0 to %d", m.LEVELS_MAX - 1)
          )
        else
          good[name] = { role = role, player = player }
          names[#names + 1] = name
        end
      end
    end
  end
  return good, names
end

-- -- One objective --

function Checker:check_objective(i, o, targeted)
  local path = format("objectives[%d]", i)
  if not py.is_map(o) then
    self:err(path, "bad_objective", "an objective is a map: { id, type, name, ... }")
    return
  end
  local before = self.error_count
  self:unknown_keys(o, m.OBJECTIVE_KEYS, path)
  local oid = py.get(o, "id")
  if oid == nil then
    self:err(path .. ".id", "missing", "required")
  elseif not m.objective_id(oid) then
    self:err(
      path .. ".id",
      "bad_id",
      "1-24 of a-z, 0-9 and _, starting with a letter (it goes in every scenario " .. "event)"
    )
  end
  self:text(py.get(o, "name"), path .. ".name", m.NAME_MAX, true)
  self:text(py.get(o, "description"), path .. ".description", m.DESCRIPTION_MAX, false, false)
  self:check_i18n(py.get(o, "i18n"), path .. ".i18n", { "name", "description" })
  local kind = py.get(o, "type")
  local otype = type(kind) == "string" and m.TYPES[kind] or nil
  if kind == nil then
    self:err(path .. ".type", "missing", "required: one of " .. join(m.TYPE_NAMES))
  elseif otype == nil then
    self:err(
      path .. ".type",
      "unknown_type",
      repr(kind) .. " is not an objective type (" .. join(m.TYPE_NAMES) .. ")"
    )
  end
  local team = self:check_assignee(o, path, otype)
  if otype ~= nil then
    self:check_target(o, path, otype, targeted, i)
    self:check_type_params(o, path, otype)
  end
  self:check_visibility(o, path, team)
  self:check_refs(py.get(o, "depends_on"), path .. ".depends_on", oid)
  self:check_window(o, path, otype)
  self:check_effect(o, path, oid)
  if otype ~= nil and in_list(otype.target, m.NODE_ROLES) and self.error_count == before then
    self:check_sizes(o, path) -- only for an objective with no other error: its setup can be built
  end
  if m.objective_id(oid) then
    self:check_events(oid, path)
  end
end

function Checker:check_assignee(o, path, otype)
  local assignee = py.get(o, "assignee")
  if assignee == nil then
    assignee = py.map()
  elseif not py.is_map(assignee) then
    self:err(path .. ".assignee", "bad_assignee", "a map: { team, squad }")
    return nil
  end
  self:unknown_keys(assignee, { "team", "squad" }, path .. ".assignee")
  local team, squad = py.get(assignee, "team"), py.get(assignee, "squad")
  if team == nil then
    if otype ~= nil and otype.needs_team then
      self:err(
        path .. ".assignee.team",
        "missing_team",
        str(py.get(o, "type")) .. " is for one team: name it (" .. join(self.teams) .. ")"
      )
    end
  elseif not in_list(team, self.teams) then
    self:err(
      path .. ".assignee.team",
      "unknown_team",
      repr(team) .. " is not one of the scenario's teams (" .. join(self.teams) .. ")"
    )
    team = nil
  end
  if squad ~= nil then
    if team == nil and py.get(assignee, "team") == nil then
      self:err(
        path .. ".assignee.squad",
        "squad_needs_team",
        "a squad belongs to a team: name the team"
      )
    elseif self.squads == 0 then
      self:err(path .. ".assignee.squad", "unknown_squad", "the scenario has no squads (squads: 0)")
    elseif not py.int_in(squad, 1, self.squads) then
      self:err(
        path .. ".assignee.squad",
        "unknown_squad",
        format("squads are numbers, 1 to %d", self.squads)
      )
    end
  end
  return team
end

function Checker:check_target(o, path, otype, targeted, i)
  local target = py.get(o, "target")
  local tname = str(py.get(o, "type"))
  if otype.target == nil then
    if target ~= nil then
      self:err(path .. ".target", "unexpected_target", tname .. " has no target")
    end
    return
  end
  if target == nil then
    self:err(path .. ".target", "missing_target", "required: a node of the nodes map")
    return
  end
  local node = type(target) == "string" and self.nodes[target] or nil
  if node == nil then
    local raw = py.get(self.m, "nodes")
    if type(target) ~= "string" or not py.is_map(raw) or not py.has(raw, target) then
      self:err(path .. ".target", "unknown_node", repr(target) .. " is not in the nodes map")
    end
    return
  end
  if otype.target == "player" then
    if not node.player then
      self:err(
        path .. ".target",
        "wrong_role",
        tname .. " targets a player (nodes." .. target .. ": { player: true, role: vip })"
      )
    end
  elseif node.player or node.role ~= otype.target then
    self:err(
      path .. ".target",
      "wrong_role",
      tname .. " needs a node with the role " .. otype.target
    )
  elseif targeted[target] ~= nil then
    self:err(
      path .. ".target",
      "node_shared",
      repr(target)
        .. format(
          " is already the target of objectives[%d]: a " .. "box serves one objective",
          targeted[target]
        )
    )
  else
    targeted[target] = i
  end
  if node.player and targeted[target] == nil then
    targeted[target] = i -- a VIP may be escorted to more than one place
  end
end

function Checker:check_type_params(o, path, otype)
  local params = py.get(o, "params")
  if params == nil then
    params = py.map()
  end
  if not py.is_map(params) then
    self:err(path .. ".params", "bad_params", "a map of the type's parameters")
    return
  end
  local tname = str(py.get(o, "type"))
  for i = 1, params.n do
    local name = params.k[i]
    if type(name) ~= "string" or otype.params[name] == nil then
      local takes = #otype.param_names > 0 and join(otype.param_names) or "no parameters"
      self:err(path .. ".params." .. str(name), "unknown_param", tname .. " takes " .. takes)
    end
  end
  for _, name in ipairs(otype.param_names) do
    local spec = otype.params[name]
    local where = path .. ".params." .. name
    if not py.has(params, name) then
      if spec.required then
        self:err(where, "missing_param", tname .. " needs " .. name)
      end
    else
      local value = py.get(params, name)
      if spec.kind == "int" then
        if not py.int_in(value, spec.lo, spec.hi) then
          self:err(where, "bad_param", format("a whole number from %d to %d", spec.lo, spec.hi))
        end
      elseif spec.kind == "bool" then
        if type(value) ~= "boolean" then
          self:err(where, "bad_param", "true or false")
        end
      elseif spec.kind == "code" then
        if py.is_int(value) then
          self:err(
            where,
            "bad_param",
            'write the code in quotes ("0815"), so that leading zeros stay'
          )
        elseif not m.code(value) then
          self:err(where, "bad_param", "1 to 8 digits")
        end
      elseif spec.kind == "destination" then
        self:check_destination(value, where)
      end
    end
  end
end

function Checker:check_destination(d, path)
  if not py.is_map(d) then
    self:err(path, "bad_destination", "{ lat, lon, radius_m } or { points: [[lat, lon], ...] }")
    return
  end
  if py.has(d, "points") then
    self:unknown_keys(d, { "points" }, path)
    self:check_polygon(py.get(d, "points"), path .. ".points")
    return
  end
  self:unknown_keys(d, { "lat", "lon", "radius_m" }, path)
  for _, kl in ipairs({ { "lat", 90 }, { "lon", 180 } }) do
    local key, limit = kl[1], kl[2]
    local v = py.get(d, key)
    if not py.is_number(v) or not py.num_in(v, -limit, limit) then
      self:err(path .. "." .. key, "bad_destination", format("degrees, -%d to %d", limit, limit))
    end
  end
  local r = py.get(d, "radius_m")
  if not py.is_number(r) or not py.num_in(r, -math.huge, 10000) or not (r > 0) then
    self:err(
      path .. ".radius_m",
      "bad_destination",
      "a radius in metres, more than 0 and at most 10000"
    )
  elseif r < m.RADIUS_WARN_M then
    self:warn(
      path .. ".radius_m",
      "small_radius",
      format(
        "under %d m: a phone's GPS is rarely that precise, so the "
          .. "VIP may never be seen inside",
        m.RADIUS_WARN_M
      )
    )
  end
end

-- A simple polygon: no two edges cross or touch (except neighbours at their
-- shared corner), and an area.
local function simple(points)
  local n = #points
  -- The shoelace sum, added as Python 3.12's sum() adds floats (Neumaier's
  -- compensated summation), which the rule was first checked with (PE24-111).
  local area, c = nil, 0.0
  for i = 1, n do
    local p, q = points[i], points[i % n + 1]
    local x = p[2] * q[1] - q[2] * p[1]
    if area == nil then
      area = x
    else
      local t = area + x
      if math.abs(area) >= math.abs(x) then
        c = c + ((area - t) + x)
      else
        c = c + ((x - t) + area)
      end
      area = t
    end
  end
  if c ~= 0 and c == c and c ~= math.huge and c ~= -math.huge then
    area = area + c
  end
  if math.abs(area) < 1e-12 then
    return false
  end
  for i = 1, n do
    for j = i + 1, n do
      if points[i][1] == points[j][1] and points[i][2] == points[j][2] then
        return false
      end
    end
  end
  local function orient(a, b, c)
    local v = (b[1] - a[1]) * (c[2] - a[2]) - (b[2] - a[2]) * (c[1] - a[1])
    if math.abs(v) < 1e-15 then
      return 0
    end
    return v > 0 and 1 or -1
  end
  local function on_segment(a, b, c)
    return math.min(a[1], b[1]) <= c[1]
      and c[1] <= math.max(a[1], b[1])
      and math.min(a[2], b[2]) <= c[2]
      and c[2] <= math.max(a[2], b[2])
  end
  local function intersect(p1, p2, p3, p4)
    local d1, d2, d3, d4 =
      orient(p3, p4, p1), orient(p3, p4, p2), orient(p1, p2, p3), orient(p1, p2, p4)
    if d1 ~= d2 and d3 ~= d4 then
      return true
    end
    return (d1 == 0 and on_segment(p3, p4, p1))
      or (d2 == 0 and on_segment(p3, p4, p2))
      or (d3 == 0 and on_segment(p1, p2, p3))
      or (d4 == 0 and on_segment(p1, p2, p4))
  end
  local edges = {}
  for i = 1, n do
    edges[i] = { points[i], points[i % n + 1] }
  end
  -- Python's indices i, j (0-based) are a, b here (1-based).
  for a = 1, n do
    for b = a + 1, n do
      if b == a + 1 or (a == 1 and b == n) then
        -- Neighbours share a corner s; collinear, they must not fold back over each other.
        local p, s, q
        if b == a + 1 then
          p, s, q = edges[a][1], edges[a][2], edges[b][2]
        else
          p, s, q = edges[b][1], edges[a][1], edges[a][2]
        end
        if orient(p, s, q) == 0 and (on_segment(p, s, q) or on_segment(s, q, p)) then
          return false
        end
      elseif intersect(edges[a][1], edges[a][2], edges[b][1], edges[b][2]) then
        return false
      end
    end
  end
  return true
end

function Checker:check_polygon(points, path)
  if not py.is_list(points) or points.n < 3 or points.n > m.POLYGON_MAX then
    self:err(path, "bad_polygon", format("a list of 3 to %d [lat, lon] points", m.POLYGON_MAX))
    return
  end
  local good = {}
  for j = 1, points.n do
    local p = points[j]
    if
      not py.is_list(p)
      or p.n ~= 2
      or not py.is_number(p[1])
      or not py.is_number(p[2])
      or not py.num_in(p[1], -90, 90)
      or not py.num_in(p[2], -180, 180)
    then
      self:err(format("%s[%d]", path, j - 1), "bad_polygon", "[lat, lon] in degrees")
      return
    end
    good[j] = { luagen.float(p[1]), luagen.float(p[2]) }
  end
  if not simple(good) then
    self:err(
      path,
      "polygon_not_simple",
      "the polygon's edges cross or touch, or it has no area: list its corners "
        .. "in order around it"
    )
  end
end

function Checker:check_visibility(o, path, team)
  local _ = team
  local vis = py.getd(o, "visibility", m.default_visibility(o))
  local assignee = py.get(o, "assignee")
  if not py.is_map(assignee) then
    assignee = py.map()
  end
  if not in_list(vis, m.VISIBILITY) then
    self:err(path .. ".visibility", "bad_visibility", "one of " .. join(m.VISIBILITY))
  elseif vis == "team" and py.get(assignee, "team") == nil then
    self:err(path .. ".visibility", "visibility_needs_team", "team: name the assignee's team")
  elseif vis == "squad" and py.get(assignee, "squad") == nil then
    self:err(path .. ".visibility", "visibility_needs_squad", "squad: name the assignee's squad")
  elseif vis == "hidden" and not py.truthy(py.get(o, "depends_on")) then
    local id = py.get(o, "id")
    if not (type(id) == "string" and self.revealed_by[id]) then
      self:err(
        path .. ".visibility",
        "never_revealed",
        "a hidden objective is revealed when what it depends_on "
          .. "is completed, or by another's effect.reveal: it has neither"
      )
    end
  end
end

function Checker:check_refs(refs, path, oid)
  if refs == nil then
    return
  end
  if not py.is_list(refs) then
    self:err(path, "bad_reference", "a list of objective ids")
    return
  end
  local seen = {}
  for j = 1, refs.n do
    local ref = refs[j]
    local where = format("%s[%d]", path, j - 1)
    if py.eq(ref, oid) then
      self:err(where, "self_reference", "an objective cannot name itself")
    elseif type(ref) ~= "string" or self.ids[ref] == nil then
      self:err(where, "unknown_reference", repr(ref) .. " is not an objective id")
    elseif seen[ref] then
      self:err(where, "bad_reference", repr(ref) .. " is named twice")
    end
    if type(ref) == "string" then
      seen[ref] = true
    end
  end
end

function Checker:check_window(o, path, otype)
  local w = py.get(o, "time_window")
  local where = path .. ".time_window"
  local tname = str(py.get(o, "type"))
  if w == nil then
    if otype ~= nil and otype.needs_end then
      self:err(
        where,
        "missing_end",
        tname .. " is judged at its time window's end: give time_window.end_min"
      )
    end
    return
  end
  if not py.is_map(w) then
    self:err(where, "bad_time_window", "a map: { start_min, end_min }")
    return
  end
  self:unknown_keys(w, { "start_min", "end_min" }, where)
  local start, finish = py.getd(w, "start_min", 0), py.get(w, "end_min")
  if not py.int_in(start, 0, m.WINDOW_MAX_MIN) then
    self:err(
      where .. ".start_min",
      "bad_time_window",
      format("minutes from the game's start, 0 to %d", m.WINDOW_MAX_MIN)
    )
    return
  end
  if finish == nil then
    if otype ~= nil and otype.needs_end then
      self:err(where .. ".end_min", "missing_end", tname .. " is judged at its time window's end")
    end
    return
  end
  if not py.int_in(finish, 1, m.WINDOW_MAX_MIN) then
    self:err(
      where .. ".end_min",
      "bad_time_window",
      format("minutes from the game's start, 1 to %d", m.WINDOW_MAX_MIN)
    )
  elseif start >= finish then
    self:err(where, "bad_time_window", "start_min must be before end_min")
  end
end

function Checker:check_effect(o, path, oid)
  local effect = py.get(o, "effect")
  local where = path .. ".effect"
  if effect == nil then
    return
  end
  if not py.is_map(effect) then
    self:err(where, "bad_effect", "a map: { points, win, reveal }")
    return
  end
  self:unknown_keys(effect, { "points", "win", "reveal" }, where)
  local points = py.get(effect, "points")
  if py.is_map(points) then
    self:unknown_keys(points, { "param" }, where .. ".points")
    local name = py.get(points, "param")
    if type(name) ~= "string" or self.params[name] == nil then
      self:err(
        where .. ".points.param",
        "unknown_param",
        repr(name) .. " is not one of the scenario's params"
      )
    end
  elseif points ~= nil and not py.int_in(points, 0, m.POINTS_MAX) then
    self:err(
      where .. ".points",
      "bad_points",
      format(
        "whole points, 0 to %d (score.add takes integers), or " .. "{ param: name }",
        m.POINTS_MAX
      )
    )
  end
  if type(py.getd(effect, "win", false)) ~= "boolean" then
    self:err(where .. ".win", "bad_bool", "true or false")
  end
  self:check_refs(py.get(effect, "reveal"), where .. ".reveal", oid)
end

-- -- The dependency graph --

local function sorted_keys(set)
  local out = {}
  for k in pairs(set) do
    out[#out + 1] = k
  end
  table.sort(out, py.str_lt)
  return out
end

local function reaches(start, goal, graph)
  local seen = {}
  local stack = {}
  for k in pairs(graph[start] or {}) do
    stack[#stack + 1] = k
  end
  while #stack > 0 do
    local n = stack[#stack]
    stack[#stack] = nil
    if n == goal then
      return true
    end
    if not seen[n] and graph[n] then
      seen[n] = true
      for k in pairs(graph[n]) do
        stack[#stack + 1] = k
      end
    end
  end
  return false
end

-- One cycle through start, for the message: start -> ... -> start.
local function cycle(start, graph)
  local path = { start }
  local seen = { [start] = true }
  local function walk(n)
    for _, nxt in ipairs(sorted_keys(graph[n] or {})) do
      if nxt == start then
        path[#path + 1] = start
        return true
      end
      if not seen[nxt] and graph[nxt] then
        seen[nxt] = true
        path[#path + 1] = nxt
        if walk(nxt) then
          return true
        end
        path[#path] = nil
      end
    end
    return false
  end
  walk(start)
  return path
end

-- The depends_on graph is a DAG (Kahn's topological sort); every objective on
-- a cycle is named.
function Checker:check_cycles(objectives)
  local deps, order = {}, {}
  for i = 1, objectives.n do
    local o = objectives[i]
    local id = py.is_map(o) and py.get(o, "id") or nil
    if type(id) == "string" and self.ids[id] ~= nil then
      local refs = py.get(o, "depends_on")
      if deps[id] == nil then
        deps[id] = {}
        order[#order + 1] = id
      end
      if py.is_list(refs) then
        for j = 1, refs.n do
          local r = refs[j]
          if type(r) == "string" and self.ids[r] ~= nil and r ~= id then
            deps[id][r] = true
          end
        end
      end
    end
  end
  -- What Kahn's removal leaves: the objectives on a cycle or waiting for one,
  -- each with what it still waits for among them.
  local waiting, dependents = {}, {}
  for _, id in ipairs(order) do
    local count = 0
    for r in pairs(deps[id]) do
      count = count + 1
      dependents[r] = dependents[r] or {}
      dependents[r][#dependents[r] + 1] = id
    end
    waiting[id] = count
  end
  local removed, ready = {}, {}
  for _, id in ipairs(order) do
    if waiting[id] == 0 then
      ready[#ready + 1] = id
    end
  end
  while #ready > 0 do
    local done = ready[#ready]
    ready[#ready] = nil
    removed[done] = true
    for _, k in ipairs(dependents[done] or {}) do
      waiting[k] = waiting[k] - 1
      if waiting[k] == 0 then
        ready[#ready + 1] = k
      end
    end
  end
  local left = {}
  local left_ids = {}
  for _, id in ipairs(order) do
    if not removed[id] then
      local rest = {}
      for r in pairs(deps[id]) do
        if not removed[r] then
          rest[r] = true
        end
      end
      left[id] = rest
      left_ids[#left_ids + 1] = id
    end
  end
  table.sort(left_ids, function(a, b)
    return self.ids[a] < self.ids[b]
  end)
  for _, id in ipairs(left_ids) do
    if reaches(id, id, left) then
      local quoted = {}
      for k, name in ipairs(cycle(id, left)) do
        quoted[k] = name
      end
      self:err(
        format("objectives[%d].depends_on", self.ids[id]),
        "cycle",
        repr(id) .. " depends on itself through " .. concat(quoted, " -> ")
      )
    end
  end
end

-- -- Sizes --

-- The setup command, as it is sent after a reboot (the longest), fits a box's
-- CMD buffer.
function Checker:check_sizes(o, path)
  local longest = "red"
  local best = -1
  for _, t in ipairs(self.teams) do
    if #t > best then
      longest, best = t, #t
    end
  end
  local lang_raw = py.get(self.m, "lang")
  local label = m.translated(
    o,
    in_list(lang_raw, m.LANGS) and py.getd(self.m, "lang", "pt") or "pt"
  ) or ""
  local setup = luagen.setup_command(o, py.getd(self.m, "lang", "pt"), label)
  local kind = py.get(setup, "kind")
  -- What the runtime adds after a reboot, by kind (runtime.lua, setup()).
  local full = luagen.ordered("name", "setup")
  for i = 1, setup.n do
    py.put(full, setup.k[i], setup.v[i])
  end
  if kind == "capture" then
    py.put(full, "holder", longest)
  elseif kind == "tags" then
    if py.has(setup, "team") then
      py.put(full, "have", 100)
    end
  elseif kind == "bomb" then
    py.put(full, "armed", longest)
    py.put(full, "left", 3600)
  end
  local text = py.json(full)
  if text == nil then
    return -- a value JSON cannot hold (a date as the language): its own problem says so (PE24-112)
  end
  local size = #text
  if size > m.CMD_PARAMS_MAX then
    self:err(
      path .. ".name",
      "setup_too_large",
      format(
        "the box's setup takes %d bytes, more than the %d of a "
          .. "command: shorten the name in the boxes' language",
        size,
        m.CMD_PARAMS_MAX
      )
    )
  end
end

-- Every scenario event about this objective fits a LoRa payload, as the
-- controller's codec would send it from any node, at any time, to the last team.
function Checker:check_events(oid, path)
  local sid = py.get(self.m, "id")
  if type(sid) ~= "string" then
    sid = ""
  end
  local events = {
    { "scenario.objective.completed", { "objective", oid, "squad", "16" } },
    { "scenario.objective.failed", { "objective", oid, "squad", "16", "reason", "captured" } },
    { "scenario.objective.revealed", { "objective", oid, "squad", "16" } },
    { "scenario.started", { "scenario", sid } },
  }
  for _, ev in ipairs(events) do
    local size = protocol.event_size(ev[1], m.TEAMS_MAX, ev[2])
    if size > m.RF_PAYLOAD_MAX then
      self:err(
        path,
        "event_too_large",
        format("%s takes %d bytes, more than a LoRa payload's %d", ev[1], size, m.RF_PAYLOAD_MAX)
      )
    end
  end
end

-- Every problem in the manifest (a parsed map), errors and warnings, in the
-- manifest's order.
function validator.validate(manifest)
  if not py.is_map(manifest) then
    return {
      {
        path = "",
        code = "bad_manifest",
        message = "a scenario manifest is a map (id, version, name, nodes, " .. "objectives)",
        level = ERROR,
      },
    }
  end
  local checker = setmetatable({ m = manifest, problems = {}, error_count = 0 }, Checker)
  return checker:run()
end

function validator.errors(problems)
  local out = {}
  for _, p in ipairs(problems) do
    if p.level == ERROR then
      out[#out + 1] = p
    end
  end
  return out
end

return validator
