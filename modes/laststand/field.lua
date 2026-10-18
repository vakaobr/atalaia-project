-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Last Stand, on the field controller. Once the defence is set up (the
-- defenders have held more than params.last_zones zones, or 30 s have
-- passed: box owners come from STATE reports, which can lag), a countdown of
-- params.countdown_s seconds runs whenever they hold params.last_zones
-- zones or fewer. Retaking a zone stops it; it starts over (params.reset)
-- or carries on where it stopped. When it runs out the defenders are
-- defeated, and with params.end_game the attackers win the game.

local fs = state.field { held = 0, countdown = false, defeated = false }
local ready = false -- the defence is set up
local timer -- the defeat timer, while the countdown runs
local left = params.countdown_s -- seconds the next countdown starts from
local deadline = 0

local function defeat()
  timer = nil
  fs.countdown = false
  fs.defeated = true
  emit("laststand.defeated", { team = params.defenders })
  if params.end_game then
    game.win(params.attackers)
  end
end

local function check()
  if fs.defeated then
    return
  end
  local zones = field.nodes("zone")
  local held = 0
  for _, n in ipairs(zones) do
    if field.owner(n.id) == params.defenders then
      held = held + 1
    end
  end
  if fs.held ~= held then
    fs.held = held -- state.field changes reach the console, so write only changes
  end
  if held > params.last_zones or game.time() >= 30 then
    ready = true
  end
  local danger = ready and #zones >= params.min_zones and held <= params.last_zones
  if danger and timer == nil then
    deadline = game.time() + left
    timer = after(left, defeat)
    fs.countdown = true
    emit("laststand.countdown_start", { team = params.defenders, duration_s = math.ceil(left) })
  elseif not danger and timer ~= nil then
    cancel(timer)
    timer = nil
    fs.countdown = false
    local remaining = deadline - game.time()
    emit(
      "laststand.countdown_cancel",
      { team = params.defenders, duration_s = math.ceil(remaining) }
    )
    left = params.reset and params.countdown_s or math.max(remaining, 0.1)
  end
end

on("zone.captured", check)
on("zone.neutralized", check)
every(1, check)
