-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Progressive Domination, on the field controller (decisions PD-MODE-1 to
-- PD-MODE-20): one box is capturable at a time, in an order fixed at the start.
--
-- * The order: the boxes named in params.order first, as the GM wrote them,
--   then the others (every box with the role zone) by box id, or shuffled with
--   the game's seeded rand() when params.random_order, so a replay picks the same.
-- * The active box: the first of the order at the start; field.lua announces it
--   (progressive.activated, to both teams) and tells every box its phase (the
--   mode command "pd": phase wait, active or done, and n, which grows with each
--   change; node.lua ignores an older or repeated word). The word is said again
--   every REMIND_S seconds in case a radio word was lost, and to a box that rebooted.
-- * Holding: the active box's own events say who holds it (zone.captured and
--   zone.neutralized from that box; a stale owner on the controller's list of
--   boxes is never read). A team holding it for each full minute scores
--   params.points_per_min, the first points one minute after the capture. When
--   it has held it for params.complete_min minutes (and so been paid for each),
--   the box is completed for that team (progressive.completed, plus
--   params.complete_bonus), locked, and the next box in the order is announced.
-- * Another team taking the box before that starts its own count from zero; what
--   the first team earned stays its own.
-- * The end: when the last box is completed, the game ends won by the team with
--   the most points (a tie ends it without a winner), or earlier when a team
--   reaches params.target_score (0: no score target).

local REMIND_S = 10
local MINUTE_S = 60

local fs = state.field { active = nil, step = 0, of = 0, done = 0, holder = nil }
local order = {} -- { id, name } in the order of play
local results = {} -- step -> the team that completed it
local pos = 0 -- the active box's place in order; #order + 1 when all are completed
local ver = 0 -- grows with each change of what the boxes are told
local owner, since, credited = nil, 0, 0 -- the holder of the active box, since when, minutes paid
local over = false

local function trim(text)
  return (text:gsub("^%s+", ""):gsub("%s+$", ""))
end

local function build_order()
  local boxes = field.nodes("zone")
  table.sort(boxes, function(a, b)
    return a.id < b.id
  end)
  local taken = {}
  order = {}
  for name in string.gmatch(params.order, "[^,]+") do
    name = trim(name)
    for _, n in ipairs(boxes) do
      if n.name == name and not taken[n.id] then
        taken[n.id] = true
        order[#order + 1] = { id = n.id, name = n.name }
        break
      end
    end
  end
  local rest = {}
  for _, n in ipairs(boxes) do
    if not taken[n.id] then
      rest[#rest + 1] = { id = n.id, name = n.name }
    end
  end
  if params.random_order then
    for i = #rest, 2, -1 do
      local j = rand(1, i)
      rest[i], rest[j] = rest[j], rest[i]
    end
  end
  for _, box in ipairs(rest) do
    order[#order + 1] = box
  end
end

local function tell(i)
  local word = { name = "pd", n = ver, of = #order, step = i }
  if i < pos then
    word.phase, word.team = "done", results[i]
  elseif i == pos then
    word.phase = "active"
  else
    word.phase = "wait"
  end
  word.done = pos - 1
  field.send(order[i].id, "mode", word)
end

local function tell_all()
  for i = 1, #order do
    tell(i)
  end
end

local function publish()
  local box = order[pos]
  fs.active = box and box.name or nil
  fs.step = box and pos or 0
  fs.of = #order
  fs.done = pos - 1
  fs.holder = owner
end

local function activate(i)
  pos, owner, since, credited = i, nil, 0, 0
  ver = ver + 1
  publish()
  tell_all()
  emit("progressive.activated", { zone = order[i].name, step = i })
end

local function leader()
  local best, tied
  for team, points in pairs(field.score()) do
    if best == nil or points > best.points then
      best, tied = { team = team, points = points }, false
    elseif points == best.points then
      tied = true
    end
  end
  return best and not tied and best.team or nil
end

local function finish(reason, team)
  over = true
  owner = nil
  publish()
  if team then
    game.win(team)
  else
    game.finish(reason)
  end
end

local function reached_target(team)
  if params.target_score > 0 and field.score()[team] >= params.target_score then
    log("progressive: " .. team .. " reached " .. params.target_score)
    finish("target", team)
    return true
  end
  return false
end

local function complete()
  local team, box = owner, order[pos]
  results[pos] = team
  if params.complete_bonus > 0 then
    score.add(team, params.complete_bonus, "progressive_complete")
  end
  emit("progressive.completed", { team = team, zone = box.name, step = pos })
  if reached_target(team) then
    return
  end
  if pos < #order then
    activate(pos + 1)
  else
    pos, owner = #order + 1, nil
    ver = ver + 1
    tell_all()
    finish("all_completed", leader())
  end
end

-- Pays each full minute the holder has held the active box, and completes it.
local function check()
  if over or owner == nil or pos < 1 or pos > #order then
    return
  end
  local minutes = math.floor((game.time() - since + 1e-6) / MINUTE_S)
  while credited < minutes and credited < params.complete_min do
    credited = credited + 1
    if params.points_per_min > 0 then
      score.add(owner, params.points_per_min, "progressive")
      if reached_target(owner) then
        return
      end
    end
  end
  if credited >= params.complete_min then
    complete()
  end
end

on("game.start", function()
  build_order()
  if #order == 0 then
    log("progressive: no box with the role zone joined")
    return
  end
  activate(1)
end)

on("zone.captured", function(e)
  local box = order[pos]
  if over or box == nil or e.node ~= box.id or e.team == nil or e.team == owner then
    return
  end
  owner, since, credited = e.team, game.time(), 0
  publish()
end)

on("zone.neutralized", function(e)
  local box = order[pos]
  if over or box == nil or e.node ~= box.id or owner == nil then
    return
  end
  owner, since, credited = nil, 0, 0
  publish()
end)

on("node.rebooted", function(e)
  for i = 1, #order do
    if order[i].id == e.node then
      tell(i)
    end
  end
end)

on("game.end", function()
  over = true
end)

every(1, check)

every(REMIND_S, function()
  if not over and #order > 0 then
    tell_all()
  end
end)
