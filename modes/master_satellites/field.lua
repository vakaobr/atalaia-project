-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Master and Satellites, on the field controller: while a team holds the
-- master box, it scores every params.tick_s seconds (the first points one
-- full tick after the capture): params.points_per_tick, plus
-- params.satellite_bonus_pct % of that for each satellite it holds too,
-- rounded down (score.add takes whole points), and nothing while it holds
-- fewer than params.min_satellites. When the master leaves a team's hands
-- (to another team, or freed by the GM), every satellite is freed. Box owners
-- come from the boxes' STATE reports, which can arrive a little after the
-- capture event, so the check also runs every second. A satellite that
-- rebooted is freed at the next change of the master, as on the field.
-- With more than one master box, the first one (the lowest node id) counts.
-- With params.siren_all_s, the master box's siren sounds for that many seconds
-- when one team comes to hold every satellite (CMD 12 through field.send; a box
-- without a siren output ignores it), again only after that team lost one.

local fs = state.field { master = nil, held = 0 }
local tick
local told -- the last status sent to the master box
local roled = {} -- when each box was last told what it is (master or satellite): node id -> game s
local all_held -- the team the siren last sounded for, while it still holds every satellite

local function master_id()
  local m = field.nodes("master")[1]
  return m and m.id
end

local function satellites_of(team)
  local held, of = 0, 0
  for _, n in ipairs(field.nodes("satellite")) do
    of = of + 1
    if team ~= nil and field.owner(n.id) == team then
      held = held + 1
    end
  end
  return held, of
end

local function points(held)
  if held < params.min_satellites then
    return 0
  end
  return params.points_per_tick + params.points_per_tick * held * params.satellite_bonus_pct // 100
end

local function free_satellites()
  for _, n in ipairs(field.nodes("satellite")) do
    field.send(n.id, "set_owner", { team = "none" })
  end
end

-- Tell each box what it is, at the start, every 30 s again (a radio command can be lost) and after
-- it rebooted: a script does not know its role, and a free box shows "master" or "satellite"
-- instead of a plain zone. The box redraws only when the answer changes.
local function tell_roles()
  local now = game.time()
  for _, role in ipairs({ "master", "satellite" }) do
    for _, n in ipairs(field.nodes(role)) do
      if roled[n.id] == nil or now - roled[n.id] >= 30 then
        roled[n.id] = now
        field.send(n.id, "mode", { name = "role", role = role })
      end
    end
  end
end

-- The team holding every satellite (at least one), or nil.
local function holds_all()
  local sats = field.nodes("satellite")
  local team = sats[1] and field.owner(sats[1].id)
  for _, n in ipairs(sats) do
    if field.owner(n.id) ~= team then
      return nil
    end
  end
  return team
end

local function siren_all()
  if (params.siren_all_s or 0) <= 0 then
    return
  end
  local team = holds_all()
  if team == all_held then
    return
  end
  local id = master_id()
  -- A refused send (the controller sends a box at most one start every 2 s) is tried again
  -- at the next check, a second later.
  if team == nil or id == nil then
    all_held = team
  else
    local siren = { capability = "siren", act = "pulse", ms = params.siren_all_s * 1000 }
    if field.send(id, "output", siren) then
      all_held = team
    end
  end
end

local function check()
  tell_roles()
  local id = master_id()
  local owner = id and field.owner(id)
  if owner ~= fs.master then
    if tick then
      cancel(tick)
      tick = nil
    end
    if fs.master ~= nil then
      free_satellites()
    end
    fs.master = owner
    told = nil
    if owner ~= nil then
      tick = every(params.tick_s, function()
        local amount = points(satellites_of(owner))
        if amount > 0 then
          score.add(owner, amount, "master")
        end
      end)
    end
  end
  local held, of = satellites_of(owner)
  if fs.held ~= held then
    fs.held = held -- state.field changes reach the console, so write only changes
  end
  if owner ~= nil then
    local total = score.get(owner)
    local status = owner .. " " .. held .. " " .. of .. " " .. points(held) .. " " .. total
    if status ~= told then
      told = status
      field.send(id, "mode", {
        name = "status",
        team = owner,
        held = held,
        of = of,
        points = points(held),
        total = total,
      })
    end
  end
  siren_all()
end

on("node.rebooted", function(e)
  roled[e.node] = nil
end)
on("zone.captured", check)
on("zone.neutralized", check)
every(1, check)
