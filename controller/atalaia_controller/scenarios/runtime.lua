-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- The scenario runtime: the code of every compiled scenario's field.lua,
-- after the SCENARIO table that the compiler writes (lua.py). It is GPL, as
-- the game modes are, because it is copied into every scenario package; the
-- compiler that copies it is AGPL. Everything above "@runtime" stays here.
--
-- The data (one entry of SCENARIO.objectives):
--   id, type      the objective's id (data key 34) and type
--   team, squad   the assignee (squad as text, as events carry it); nil: any
--   hidden        revealed only when it opens, or by another's reveals
--   depends_on    ids that must be completed before it opens
--   reveals       ids revealed when it is completed
--   start_s       it opens no earlier than this (time_window.start_min)
--   end_s         nil, or when it fails if still open (survive: is judged)
--   points        points for the team that completes it, or points_param:
--                 the name of a scenario parameter that holds them
--   win           completing it wins the game for that team
--   node, setup   a box's objective: the node's name and its setup command
--   duration_s    capture_and_hold: how long to hold (0: the capture);
--                 defend: how long to keep it from when it opens
--   role, zone,   escort: the player's check-in role, the destination
--   max_acc_m     (geo.in_zone), the worst GPS accuracy that counts
--   minimum_lives survive
--
-- An objective is waiting, then open, then done or failed ("off": its team
-- is not in this game). It opens when it is revealed (at the start unless
-- hidden; a hidden one when it could open, or by a reveals), its time window
-- has started and what it depends on is done. A failed one fails what
-- depends on it ("blocked"). Events about an objective that was never
-- revealed are not sent (P4R24). The boxes only report; this script decides,
-- scores and tells each box what it is for (the mode command "setup") at the
-- start, when the box first appears, and again after a reboot. Nothing
-- secret goes into state.field (players read it); positions stay in this
-- script (P4R6).
-- @runtime
local OBJ = SCENARIO.objectives
local by_id = {}
for _, o in ipairs(OBJ) do
  by_id[o.id] = o
end

local status = {} -- id -> waiting, open, done, failed, off
local revealed = {} -- id -> true once scenario.objective.revealed was sent
local started = {} -- id -> true once its time window started
local winner = {} -- id -> the team that completed it
local configured = {} -- id -> the node id its setup reached
local holder = {} -- capture_and_hold, defend: id -> the team holding its node
local scanned = {} -- scan_tags: id -> { counts = { team -> n }, team -> { tag -> true } }
local armed = {} -- destroy: id -> { team, explode_at }
local timer = {} -- capture_and_hold, defend: id -> the timer that completes it
local lives = {} -- survive: team -> lives left, as Respawn last reported them

local function in_game(team)
  if team == nil then
    return true
  end
  for _, t in ipairs(game.teams()) do
    if t == team then
      return true
    end
  end
  return false
end

local function node_id(o)
  if o.node == nil then
    return nil
  end
  for _, n in ipairs(field.nodes()) do
    if n.name == o.node then
      return n.id
    end
  end
end

local function objective_at(id)
  for _, o in ipairs(OBJ) do
    if o.node and (configured[o.id] == id or node_id(o) == id) then
      return o
    end
  end
end

local function open_at(id, type_)
  local o = objective_at(id)
  if o and status[o.id] == "open" and (type_ == nil or type_[o.type]) then
    return o
  end
end

local function setup(o)
  local id = node_id(o)
  if id == nil then
    return
  end
  local st = status[o.id]
  local p = { name = "setup", label = o.setup.label, lang = o.setup.lang }
  if st == "done" or st == "failed" then
    p.kind, p.team = st, winner[o.id]
  elseif st ~= "open" then
    p.kind = "off"
  else
    for k, v in pairs(o.setup) do
      p[k] = v
    end
    p.holder = holder[o.id]
    local s = scanned[o.id]
    if s and o.team then
      p.have = s.counts[o.team]
    end
    local a = armed[o.id]
    if a then
      p.armed, p.left = a.team, math.max(1, math.ceil(a.explode_at - game.time()))
    end
  end
  if field.send(id, "mode", p) then
    configured[o.id] = id
  end
end

local function event(type_, o, team, reason)
  local d = { objective = o.id, team = team, reason = reason }
  if o.squad and team ~= nil and team == o.team then
    d.squad = o.squad
  end
  emit(type_, d)
end

local function stop_timer(o)
  if timer[o.id] then
    cancel(timer[o.id])
    timer[o.id] = nil
  end
end

local refresh -- below: opens an objective when it can

local function reveal(o)
  if revealed[o.id] or status[o.id] == "off" then
    return
  end
  revealed[o.id] = true
  event("scenario.objective.revealed", o, o.team)
end

local function depends_on(o, id)
  for _, d in ipairs(o.depends_on) do
    if d == id then
      return true
    end
  end
  return false
end

local function fail(o, team, reason)
  local st = status[o.id]
  if st ~= "waiting" and st ~= "open" then
    return
  end
  status[o.id] = "failed"
  stop_timer(o)
  armed[o.id] = nil
  if revealed[o.id] then
    event("scenario.objective.failed", o, team, reason)
  end
  if o.node then
    setup(o)
  end
  for _, d in ipairs(OBJ) do
    if depends_on(d, o.id) then
      fail(d, d.team, "blocked")
    end
  end
end

local function finish(o, team)
  if status[o.id] ~= "open" then
    return
  end
  status[o.id], winner[o.id] = "done", team
  stop_timer(o)
  armed[o.id] = nil
  event("scenario.objective.completed", o, team)
  local points = o.points
  if o.points_param then
    points = params[o.points_param]
  end
  if team and points and points > 0 then
    score.add(team, points, "objective")
  end
  if o.node then
    setup(o)
  end
  for _, id in ipairs(o.reveals) do
    reveal(by_id[id])
    refresh(by_id[id])
  end
  for _, d in ipairs(OBJ) do
    if depends_on(d, o.id) then
      refresh(d)
    end
  end
  if o.win and team then
    game.win(team)
  end
end

local function hold_for(o, team, seconds)
  stop_timer(o)
  timer[o.id] = after(seconds, function()
    timer[o.id] = nil
    if holder[o.id] == team then
      finish(o, team)
    end
  end)
end

local function opened(o)
  if o.type == "defend" then
    holder[o.id] = o.team -- the defenders hold it; an enemy capture fails it
    timer[o.id] = after(o.duration_s, function()
      timer[o.id] = nil
      finish(o, o.team)
    end)
  end
end

refresh = function(o)
  if status[o.id] ~= "waiting" or not started[o.id] then
    return
  end
  for _, d in ipairs(o.depends_on) do
    if status[d] ~= "done" then
      return
    end
  end
  reveal(o)
  status[o.id] = "open"
  opened(o)
  if o.node then
    setup(o)
  end
end

local function judge(o)
  if o.type == "survive" then
    if status[o.id] == "open" then
      finish(o, o.team)
    else
      fail(o, o.team, "time")
    end
  else
    fail(o, o.team, "time")
  end
end

on("game.start", function()
  emit("scenario.started", { scenario = SCENARIO.id })
  for _, o in ipairs(OBJ) do
    if in_game(o.team) then
      status[o.id] = "waiting"
      started[o.id] = o.start_s == 0
    else
      status[o.id] = "off"
      log("scenario: " .. o.id .. " is off: its team is not in this game")
    end
  end
  for _, o in ipairs(OBJ) do
    if status[o.id] == "waiting" and not o.hidden then
      reveal(o)
    end
  end
  for _, o in ipairs(OBJ) do
    refresh(o)
    if o.node and status[o.id] ~= "open" then
      setup(o)
    end
    if status[o.id] ~= "off" then
      if o.start_s > 0 then
        after(o.start_s, function()
          started[o.id] = true
          refresh(o)
        end)
      end
      if o.end_s then
        after(o.end_s, function()
          judge(o)
        end)
      end
    end
  end
end)

-- A node that joins later is set up when it first appears.
every(1, function()
  for _, o in ipairs(OBJ) do
    if o.node and status[o.id] and not configured[o.id] then
      setup(o)
    end
  end
end)

-- A rebooted node lost its setup (no script state survives a reboot): send it again.
on("node.rebooted", function(e)
  for _, o in ipairs(OBJ) do
    if o.node and configured[o.id] == e.node then
      configured[o.id] = nil
      setup(o)
    end
  end
end)

-- capture_and_hold and defend.

local CAPTURE = { capture_and_hold = true, defend = true }

on("zone.captured", function(e)
  local o = open_at(e.node, CAPTURE)
  if o == nil then
    return
  end
  holder[o.id] = e.team
  if o.type == "defend" then
    if e.team ~= o.team then
      fail(o, o.team, "captured")
    end
  elseif o.team == nil or e.team == o.team then
    if o.duration_s == 0 then
      finish(o, e.team)
    else
      hold_for(o, e.team, o.duration_s)
    end
  end
end)

on("zone.neutralized", function(e)
  local o = open_at(e.node, CAPTURE)
  if o then
    holder[o.id] = nil
    if o.type == "capture_and_hold" then
      stop_timer(o)
    end
  end
end)

-- enter_code: the box checks the code; code.used never carries it.

on("code.used", function(e)
  local o = open_at(e.node, { enter_code = true })
  if o then
    finish(o, e.team or o.team)
  end
end)

-- scan_tags: each tag counts once per team, even if the box rebooted and forgot it.

on("tag.scanned", function(e)
  local o = open_at(e.node, { scan_tags = true })
  if o == nil or type(e.team) ~= "string" or (o.team and e.team ~= o.team) then
    return
  end
  local s = scanned[o.id] or { counts = {} }
  scanned[o.id] = s
  s[e.team] = s[e.team] or {}
  if s[e.team][e.tag] then
    return
  end
  s[e.team][e.tag] = true
  s.counts[e.team] = (s.counts[e.team] or 0) + 1
  if s.counts[e.team] >= o.setup.count then
    finish(o, e.team)
  end
end)

-- destroy: completed when the bomb explodes, failed when it is defused.

on("bomb.armed", function(e)
  local o = open_at(e.node, { destroy = true })
  if o then
    armed[o.id] = { team = e.team, explode_at = game.time() + (e.fuse_s or o.setup.fuse_s or 60) }
  end
end)

on("bomb.defused", function(e)
  local o = open_at(e.node, { destroy = true })
  if o then
    local a = armed[o.id]
    fail(o, o.team or (a and a.team), "defused")
  end
end)

on("bomb.exploded", function(e)
  local o = open_at(e.node, { destroy = true })
  if o then
    local a = armed[o.id]
    finish(o, e.team or o.team or (a and a.team))
  end
end)

-- escort: the controller hands this script the positions of checked-in players
-- (position.fix, P4R6); a fix of the escorted role inside the zone completes it.

on("position.fix", function(e)
  if type(e.lat) ~= "number" or type(e.lon) ~= "number" then
    return
  end
  for _, o in ipairs(OBJ) do
    if
      o.type == "escort"
      and status[o.id] == "open"
      and e.role == o.role
      and (o.team == nil or e.team == o.team)
      and not (type(e.acc) == "number" and e.acc > o.max_acc_m)
      and geo.in_zone(e.lat, e.lon, o.zone)
    then
      finish(o, e.team)
    end
  end
end)

-- survive: Respawn and Lives' reports (lives per team; per-player lives say
-- nothing about a team's).

local function lives_changed(team)
  for _, o in ipairs(OBJ) do
    if o.type == "survive" and o.team == team and status[o.id] ~= "done" then
      local left = lives[team]
      if left ~= nil and (left < 0 or left < o.minimum_lives) then
        fail(o, team, "lives")
      end
    end
  end
end

on("player.respawn", function(e)
  if params.per_player or type(e.team) ~= "string" or math.type(e.lives_left) ~= "integer" then
    return
  end
  lives[e.team] = e.lives_left
  lives_changed(e.team)
end)

on("team.eliminated", function(e)
  if type(e.team) == "string" then
    lives[e.team] = -1
    lives_changed(e.team)
  end
end)
