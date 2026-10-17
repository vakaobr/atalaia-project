-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Domination (draft): the last team to claim the box scores while it holds it.

local s = state.node { owner = nil }

on("team_input.hold", function(e)
  if e.team == s.owner or e.ms < params.capture_hold_ms then
    return
  end
  local previous = s.owner
  s.owner = e.team
  cap("team_display"):show(e.team)
  audio.play("captured")
  emit("zone.captured", { team = e.team, squad = e.squad, previous_team = previous })
end)

every(params.tick_s, function()
  if s.owner then
    score.add(s.owner, params.points_per_tick, "hold")
  end
end)

-- The core freezes scores on game.end; show the final result on the prop.
on("game.end", function()
  ui.screen("final_score", { owner = s.owner })
end)
