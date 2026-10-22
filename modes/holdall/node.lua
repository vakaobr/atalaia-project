-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Hold-All Domination, on each box: a team captures the box by holding its
-- input, as in Domination. The box does not score by itself: the field
-- controller's field.lua scores a team only while it holds every box.

local s = state.node { owner = nil, since = 0 }

-- The box's screen (decision BN-11): the Field Box's built-in neutral and captured
-- screens (screen_renderer.c), as Domination's.
local function show()
  if s.owner then
    ui.screen("captured", { team = s.owner, since = s.since })
  else
    ui.screen("neutral", { hold_s = params.capture_hold_ms // 1000 })
  end
end

local function capture(team, squad)
  emit("zone.captured", { team = team, squad = squad, previous_team = s.owner })
  s.owner = team
  s.since = math.floor(game.time())
  cap("team_display"):show(team)
  audio.play("captured")
  show()
end

on("game.start", show)

on("team_input.hold", function(e)
  if e.team ~= s.owner and e.ms >= params.capture_hold_ms then
    capture(e.team, e.squad)
  end
end)

-- The GM's owner override from the console: a team, or none to free the box.
on("cmd.set_owner", function(e)
  if e.team == s.owner then
    return
  end
  if e.team == nil or e.team == "" or e.team == "none" then
    emit("zone.neutralized", { previous_team = s.owner })
    s.owner = nil
    cap("team_display"):show("none")
    show()
  else
    capture(e.team)
  end
end)

on("game.end", function()
  ui.screen("final_score", { owner = s.owner })
end)
