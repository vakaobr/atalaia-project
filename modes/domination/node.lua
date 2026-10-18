-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Domination (draft): the last team to claim the box scores while it holds it.
-- Screens (assets/screens/): standby until the first capture, then captured
-- (the holding team, its points on this box and when it took it), and
-- final_score when the game ends.

local s = state.node { owner = nil, since = 0 }

local function show()
  if s.owner then
    ui.screen("captured", { team = s.owner, points = score.get(s.owner), since = s.since })
  else
    ui.screen("standby", {})
  end
end

on("game.start", show)

on("team_input.hold", function(e)
  if e.team == s.owner or e.ms < params.capture_hold_ms then
    return
  end
  local previous = s.owner
  s.owner = e.team
  s.since = math.floor(game.time())
  cap("team_display"):show(e.team)
  audio.play("captured")
  emit("zone.captured", { team = e.team, squad = e.squad, previous_team = previous })
  show()
end)

every(params.tick_s, function()
  if s.owner then
    score.add(s.owner, params.points_per_tick, "hold")
    show()
  end
end)

-- The core freezes scores on game.end; show the final result on the prop.
on("game.end", function()
  ui.screen("final_score", { owner = s.owner, points = s.owner and score.get(s.owner) or nil })
end)
