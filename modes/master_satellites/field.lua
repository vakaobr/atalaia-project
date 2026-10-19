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

local fs = state.field { master = nil, held = 0 }
local tick
local told -- the last status sent to the master box

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

local function check()
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
    local status = owner .. " " .. held .. " " .. of .. " " .. points(held)
    if status ~= told then
      told = status
      field.send(
        id,
        "mode",
        { name = "status", team = owner, held = held, of = of, points = points(held) }
      )
    end
  end
end

on("zone.captured", check)
on("zone.neutralized", check)
every(1, check)
