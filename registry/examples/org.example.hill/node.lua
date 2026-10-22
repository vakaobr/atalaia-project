-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: MIT
--
-- King of the Hill: the last team to hold the box long enough owns the hill
-- and scores a point every tick_s seconds while it keeps it.

local s = state.node({ owner = nil })

on("team_input.hold", function(e)
  if e.team == s.owner or e.ms < params.hold_ms then
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
    score.add(s.owner, 1, "hill")
  end
end)
