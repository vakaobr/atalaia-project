-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Master and Satellites, on each box (the master and the satellites run the
-- same script): a team captures the box by holding its input, as in
-- Domination. Boxes do not score: the field controller's field.lua scores the
-- master's holder, with a bonus for the satellites it holds too, and frees
-- every satellite when the master changes hands. It also tells the master box
-- how many satellites its holder has (the mode command "status"), so the
-- master shows them; a box that was never told is a satellite, or a box
-- picked from its own preset list, and shows only who holds it.
-- Screens (assets/screens/): standby, captured, master_status; final_score at
-- the end (the Field Box's built-in screen).

local s = state.node { owner = nil, since = 0 }
local master = nil -- the last status from the controller: { held, of, points }

local function show()
  if s.owner == nil then
    ui.screen("standby", {})
  elseif master then
    ui.screen("master_status", {
      team = s.owner,
      since = s.since,
      held = master.held,
      of = master.of,
      points = master.points,
    })
  else
    ui.screen("captured", { team = s.owner, since = s.since })
  end
end

local function capture(team, squad)
  emit("zone.captured", { team = team, squad = squad, previous_team = s.owner })
  s.owner = team
  s.since = math.floor(game.time())
  cap("team_display"):show(team)
  audio.play("captured")
  if master then
    -- A new holder of the master starts with no satellites (they are freed);
    -- the controller's next status confirms it.
    master.held, master.points = 0, params.points_per_tick
  end
  show()
end

on("game.start", show)

on("team_input.hold", function(e)
  if e.team ~= s.owner and e.ms >= params.capture_hold_ms then
    capture(e.team, e.squad)
  end
end)

-- The GM's owner override from the console, and the controller freeing the
-- satellites: a team, or none to free the box (a free box stays as it is).
on("cmd.set_owner", function(e)
  local free = e.team == nil or e.team == "" or e.team == "none"
  if e.team == s.owner or (free and s.owner == nil) then
    return
  end
  if free then
    emit("zone.neutralized", { previous_team = s.owner })
    s.owner = nil
    cap("team_display"):show("none")
    show()
  else
    capture(e.team)
  end
end)

-- From field.lua, to the master box only: its holder's satellites and points per tick.
on("cmd.mode", function(e)
  if e.name ~= "status" or e.team ~= s.owner then
    return
  end
  master = {
    held = math.tointeger(e.held) or 0,
    of = math.tointeger(e.of) or 0,
    points = math.tointeger(e.points) or 0,
  }
  show()
end)

on("game.end", function()
  ui.screen("final_score", { owner = s.owner })
end)
