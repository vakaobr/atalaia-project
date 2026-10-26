-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Domination (draft): the last team to claim the box scores while it holds it.
-- Screens (assets/screens/): neutral until the first capture, then captured
-- (the holding team, its points on this box and when it took it), and
-- final_score when the game ends.

local s = state.node { owner = nil, since = 0 }

local function show()
  if s.owner then
    ui.screen("captured", { team = s.owner, points = score.get(s.owner), since = s.since })
  else
    ui.screen("neutral", {})
  end
end

on("game.start", show)

local function capture(team, squad)
  emit("zone.captured", { team = team, squad = squad, previous_team = s.owner })
  s.owner = team
  s.since = math.floor(game.time())
  cap("team_display"):show(team)
  audio.play("captured")
  show()
end

on("team_input.hold", function(e)
  if e.team ~= s.owner and e.ms >= params.capture_hold_ms then
    capture(e.team, e.squad)
  end
end)

-- The GM's owner override from the console (decision E7): a team, or none to
-- free the box. Same as Hold-All and Last Stand; scoring follows the owner.
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
