-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Target Windows, on each target (decision P4R4): the target stays dark for
-- params.interval_s seconds, then lights up in a random team's colour (one of
-- game.teams(), with the game's seeded rand(), so a replay picks the same
-- teams) for params.window_s seconds. A hit (the hit capability's input
-- hit.hit, with strength 0-255) of at least params.min_strength while the
-- window is open scores params.hit_points for the window's team and logs
-- target.hit with window_open = true; the first such hit closes the window
-- unless params.multi_hit. A hit while the target is dark scores nothing and
-- logs target.hit with window_open = false. Weaker hits are ignored. The
-- target is armed (it reports hits) from the start of the game to its end.
-- Owner overrides (cmd.set_owner) mean nothing here and are ignored.
-- Screens (assets/screens/): standby while dark (with the last scoring hit),
-- window while open; final_score at the end (the Field Box's built-in screen).

local s = state.node { team = nil, left = 0, last_team = nil, hits = 0 }
local timer = nil -- the timer that opens or closes the next window
local tick = nil -- the per-second countdown while a window is open
local running = false

local function show()
  if s.team then
    ui.screen("window", { team = s.team, left = s.left })
  else
    ui.screen("standby", { team = s.last_team, hits = s.hits })
  end
end

local open_window

local function close_window()
  if tick then
    cancel(tick)
    tick = nil
  end
  if timer then
    cancel(timer)
    timer = nil
  end
  s.team = nil
  cap("ring"):off()
  show()
  if running then
    timer = after(params.interval_s, open_window)
  end
end

open_window = function()
  timer = nil
  local teams = game.teams()
  if #teams == 0 then
    return
  end
  s.team = teams[rand(1, #teams)]
  s.left = params.window_s
  cap("ring"):fill(s.team)
  audio.play("window")
  show()
  timer = after(params.window_s, close_window)
  tick = every(1, function()
    if s.left > 1 then
      s.left = s.left - 1
      show()
    end
  end)
end

on("game.start", function()
  if running then
    return
  end
  running = true
  cap("hit"):arm()
  show()
  timer = after(params.interval_s, open_window)
end)

on("hit.hit", function(e)
  local strength = tonumber(e.strength) or 0
  if not running or strength < params.min_strength then
    return
  end
  local team = s.team
  if team == nil then
    emit("target.hit", { window_open = false })
    return
  end
  emit("target.hit", { team = team, window_open = true })
  score.add(team, params.hit_points, "target")
  s.last_team, s.hits = team, s.hits + 1
  audio.play("hit")
  if not params.multi_hit then
    close_window()
  end
end)

on("game.end", function()
  running = false
  if tick then
    cancel(tick)
    tick = nil
  end
  if timer then
    cancel(timer)
    timer = nil
  end
  s.team = nil
  cap("hit"):disarm()
  cap("ring"):off()
  ui.screen("final_score", {})
end)
