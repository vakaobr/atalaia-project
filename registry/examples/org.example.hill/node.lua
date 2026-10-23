-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: MIT
--
-- King of the Hill: the last team to hold the box long enough owns the hill
-- and scores a point every tick_s seconds while it keeps it.
--
-- The box's screen comes from this mode's own templates (assets/screens/):
--   neutral      nobody owns the hill yet
--   captured     a team owns it: its points on this box and when it took it
--   final_score  the game is over
-- While a team holds its button, neutral and captured also fill a bar.
-- Using the names neutral, captured and final_score also gives a box's small
-- OLED its own words for them; any other name works on the big screen.

-- state.node survives a box's power loss (modes/README.md, "After a power
-- loss"); keep only plain values in it.
local s = state.node({ owner = nil, since = 0 })
-- Who is holding a button right now and how far they are (0-1). A local:
-- after a power loss nobody is holding anything.
local taker, progress

-- Draws the hill as it is now. Call it after every change: the box redraws
-- only the parts of the screen whose data changed.
local function show()
  local data = { taker = taker, progress = progress }
  if s.owner then
    data.team = s.owner -- `team` gives the template its colour (`color: team`)
    data.points = score.get(s.owner)
    data.since = s.since
    ui.screen("captured", data)
  else
    ui.screen("neutral", data)
  end
end

on("game.start", show)

-- After a power loss the script starts again: light the owner's colour and
-- draw the screen again.
on("node.rebooted", function()
  if s.owner then
    cap("team_display"):show(s.owner)
  end
  show()
end)

-- team_input.hold arrives every 250 ms while a team holds its button; e.ms is
-- how long it has held so far.
on("team_input.hold", function(e)
  if e.team == s.owner then
    return
  end
  if e.ms < params.hold_ms then
    taker = e.team
    -- In hundredths, so the screen gets few distinct values to redraw.
    progress = math.floor(e.ms * 100 / params.hold_ms) / 100
    return show()
  end
  local previous = s.owner
  s.owner = e.team
  s.since = math.floor(game.time())
  taker, progress = nil, nil
  -- Optional capabilities (mode.yaml's roles): on a box without an LED ring or
  -- a speaker these calls do nothing.
  cap("team_display"):show(e.team)
  audio.play("captured")
  emit("zone.captured", { team = e.team, squad = e.squad, previous_team = previous })
  show()
end)

-- Letting go too soon empties the bar.
on("team_input.release", function(e)
  if e.team == taker then
    taker, progress = nil, nil
    show()
  end
end)

every(params.tick_s, function()
  if s.owner then
    score.add(s.owner, 1, "hill")
    show()
  end
end)

-- Scores are frozen when the game ends: show who kept the hill.
on("game.end", function()
  ui.screen("final_score", { owner = s.owner, points = s.owner and score.get(s.owner) or nil })
end)
