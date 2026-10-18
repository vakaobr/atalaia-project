-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Last Stand, on each zone box: the defenders hold the box when the game
-- starts; any team captures it by holding its input. The field controller's
-- field.lua counts the defenders' zones and runs the countdown to defeat.

local s = state.node { owner = nil }

local function capture(team, squad)
  emit("zone.captured", { team = team, squad = squad, previous_team = s.owner })
  s.owner = team
  cap("team_display"):show(team)
  audio.play("captured")
end

on("game.start", function()
  if s.owner == nil then
    capture(params.defenders)
  end
end)

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
  else
    capture(e.team)
  end
end)

on("game.end", function()
  ui.screen("final_score", { owner = s.owner })
end)
