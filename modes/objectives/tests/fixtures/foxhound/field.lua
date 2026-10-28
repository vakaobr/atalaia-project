-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Foxhound, on the field controller: a hand-written example of a scenario's
-- field.lua (kind: scenario, decision P4R7), as the scenario compiler (plan
-- phase 7) will write them. Objectives map to nodes by the names they have in
-- the game (P4R8); each node runs org.atalaia.objectives and is told what it
-- is for with the mode command "setup", at the start, when it first appears,
-- and again after a reboot (node.rebooted). The nodes only report: this script
-- decides what completes or fails an objective, reveals the next ones, and
-- scores. Nothing secret goes into state.field, which players can read: the
-- vault's code travels only in the setup command to its node.

local OBJECTIVES = {
  -- Red holds the bridge: completed, and the vault is revealed to red.
  {
    id = "bridge",
    node = "alpha",
    to = "red",
    points = 50,
    setup = { kind = "capture", team = "red", hold_ms = 3000, label = "Ponte" },
  },
  -- Two players of a team scan their tags at the intel point: the first team to do it.
  {
    id = "intel",
    node = "bravo",
    points = 20,
    setup = { kind = "tags", count = 2, label = "Informações" },
  },
  -- Hidden until the bridge is red's; red types the code.
  {
    id = "vault",
    node = "charlie",
    to = "red",
    after = "bridge",
    setup = { kind = "code", code = "4711", team = "red", label = "Cofre" },
  },
  -- Red arms site A (completed when it explodes); blue defusing it fails it for red.
  {
    id = "site_a",
    node = "site",
    points = 30,
    setup = { kind = "bomb", team = "red", hold_ms = 5000, fuse_s = 60, label = "Local A" },
  },
}

local status = {} -- objective id -> hidden, open, done, failed
local winner = {} -- objective id -> the team that completed it
local configured = {} -- objective id -> the node id its setup reached
local sent = {} -- objective id -> { kind, tries, due, acked }: the last setup sent (as the runtime's, PKB-3)
local holder = {} -- capture: objective id -> the team holding its node
local scanned = {} -- tags: objective id -> { team -> { tag -> true }, counts }
local armed = {} -- bomb: objective id -> { team, explode_at }

local function node_id(o)
  for _, n in ipairs(field.nodes()) do
    if n.name == o.node then
      return n.id
    end
  end
end

local function objective_at(id)
  for _, o in ipairs(OBJECTIVES) do
    if configured[o.id] == id or node_id(o) == id then
      return o
    end
  end
end

-- The waits, in seconds, before a setup is sent again until the box says node.setup_applied.
local RESEND_S = { 8, 16, 32, 64, 128 }

local function setup(o, again)
  local id = node_id(o)
  if id == nil then
    return
  end
  local st = status[o.id]
  local p = { name = "setup", label = o.setup.label }
  if st == "hidden" then
    p.kind = "off"
  elseif st == "done" or st == "failed" then
    p.kind, p.team = st, winner[o.id]
  else
    for k, v in pairs(o.setup) do
      p[k] = v
    end
    p.holder = holder[o.id]
    local s = scanned[o.id]
    if s and o.setup.team then
      p.have = s.counts[o.setup.team]
    end
    local a = armed[o.id]
    if a then
      p.armed, p.left = a.team, math.max(1, math.ceil(a.explode_at - game.time()))
    end
  end
  if field.send(id, "mode", p) then
    configured[o.id] = id
    local s = sent[o.id]
    if again and s and s.kind == p.kind then
      s.tries = s.tries + 1
    else
      s = { kind = p.kind, tries = 0, acked = false }
      sent[o.id] = s
    end
    s.due = game.time() + (RESEND_S[s.tries + 1] or 0)
  end
end

local function reveal(o)
  status[o.id] = "open"
  emit("scenario.objective.revealed", { team = o.to, objective = o.id })
  setup(o)
end

local function finish(o, team, failed, reason)
  if status[o.id] ~= "open" then
    return
  end
  status[o.id], winner[o.id] = failed and "failed" or "done", not failed and team or nil
  if failed then
    emit("scenario.objective.failed", { team = team, objective = o.id, reason = reason })
  else
    emit("scenario.objective.completed", { team = team, objective = o.id })
    local points = o.id == "vault" and params.vault_points or o.points
    if team and points and points > 0 then
      score.add(team, points, "objective")
    end
  end
  setup(o)
  for _, next in ipairs(OBJECTIVES) do
    if next.after == o.id and status[next.id] == "hidden" and not failed then
      reveal(next)
    end
  end
end

on("game.start", function()
  emit("scenario.started", { scenario = "org.club.foxhound" })
  for _, o in ipairs(OBJECTIVES) do
    status[o.id] = o.after and "hidden" or "open"
  end
  for _, o in ipairs(OBJECTIVES) do
    if status[o.id] == "open" then
      emit("scenario.objective.revealed", { team = o.to, objective = o.id })
    end
    setup(o)
  end
end)

-- A node that joins later is set up when it first appears, and one that has not said it took its setup
-- is sent it again, a bounded number of times.
every(1, function()
  for _, o in ipairs(OBJECTIVES) do
    if status[o.id] then
      local s = sent[o.id]
      if not configured[o.id] then
        setup(o)
      elseif s and not s.acked and s.tries < #RESEND_S and game.time() >= s.due then
        setup(o, true)
      end
    end
  end
end)

-- The box took the setup: no more repeats of it.
on("node.setup_applied", function(e)
  local o = objective_at(e.node)
  local s = o and sent[o.id]
  if s and e.kind == s.kind then
    s.acked = true
  end
end)

-- A rebooted node lost its setup (no script state survives a reboot): send it again.
on("node.rebooted", function(e)
  for _, o in ipairs(OBJECTIVES) do
    if configured[o.id] == e.node then
      configured[o.id] = nil
      setup(o)
    end
  end
end)

on("zone.captured", function(e)
  local o = objective_at(e.node)
  if o == nil or o.setup.kind ~= "capture" then
    return
  end
  holder[o.id] = e.team
  if e.team == o.setup.team then
    finish(o, e.team)
  end
end)

on("zone.neutralized", function(e)
  local o = objective_at(e.node)
  if o then
    holder[o.id] = nil
  end
end)

on("code.used", function(e)
  local o = objective_at(e.node)
  if o and o.setup.kind == "code" then
    finish(o, e.team or o.setup.team)
  end
end)

on("tag.scanned", function(e)
  local o = objective_at(e.node)
  if o == nil or o.setup.kind ~= "tags" or type(e.team) ~= "string" then
    return
  end
  local s = scanned[o.id] or { counts = {} }
  scanned[o.id] = s
  s[e.team] = s[e.team] or {}
  if s[e.team][e.tag] then
    return -- a node that rebooted may count a tag again
  end
  s[e.team][e.tag] = true
  s.counts[e.team] = (s.counts[e.team] or 0) + 1
  if s.counts[e.team] >= o.setup.count then
    finish(o, e.team)
  end
end)

on("bomb.armed", function(e)
  local o = objective_at(e.node)
  if o and o.setup.kind == "bomb" then
    armed[o.id] = { team = e.team, explode_at = game.time() + (e.fuse_s or o.setup.fuse_s) }
  end
end)

on("bomb.defused", function(e)
  local o = objective_at(e.node)
  if o and o.setup.kind == "bomb" then
    armed[o.id] = nil
    finish(o, o.setup.team, true, "defused")
  end
end)

on("bomb.exploded", function(e)
  local o = objective_at(e.node)
  if o and o.setup.kind == "bomb" then
    armed[o.id] = nil
    finish(o, e.team or o.setup.team)
  end
end)
