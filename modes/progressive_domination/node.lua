-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Progressive Domination, on each box (decisions PD-MODE-1 to PD-MODE-20).
-- All the boxes run this script; the field controller's field.lua decides
-- which one is capturable and tells each box with the mode command "pd":
--
--   phase "wait"   not its turn (or finished before it): ignores its buttons,
--                  LED off, shows how many boxes are completed;
--   phase "active" the only box capturable now: a team captures it by holding
--                  its input for params.capture_hold_ms, as in Domination, and
--                  another team takes it over the same way; the LED is white
--                  while nobody holds it, the holder's colour after;
--   phase "done"   completed by a team (the word's "team"): locked for good,
--                  in that team's colour, buttons ignored.
--
-- A box never scores and never decides: points per minute held, the hold
-- time that completes a box, the order and the end of the game are field.lua's.
-- The box only reports its captures (zone.captured and zone.neutralized, as
-- Domination does) and shows what it was told. The word carries n, which grows
-- with every change, so an older or repeated word is ignored; field.lua says it
-- again every few seconds and when this box reboots. Before its first word
-- (a box picked on its own, without a controller) a box waits.
-- Screens (assets/screens/): inactive, neutral (the active box nobody holds),
-- captured (the active box and its holder), completed; final_score at the end
-- (the Field Box's built-in screen).

local REFRESH_S = 5 -- the held time on the screen follows the game's clock this often

local s = state.node {
  phase = "wait",
  owner = nil,
  since = 0,
  n = 0,
  step = 0,
  of = 0,
  done = 0,
  team = nil,
}
local taker, progress -- a team holding its input to take the active box, and how far (0-1)

local function final()
  return s.of > 0 and s.step == s.of
end

local function draw()
  if s.phase == "active" then
    if s.owner then
      local held_s = math.max(0, math.floor(game.time()) - s.since)
      local need_s = params.complete_min * 60
      ui.screen("captured", {
        team = s.owner,
        since = s.since,
        step = s.step,
        of = s.of,
        final = final(),
        held_min = held_s // 60,
        need_min = params.complete_min,
        points = (held_s // 60) * params.points_per_min,
        share = math.min(100, held_s * 100 // need_s) / 100,
        taker = taker,
        progress = progress,
      })
    else
      ui.screen(
        "neutral",
        { step = s.step, of = s.of, final = final(), taker = taker, progress = progress }
      )
    end
  elseif s.phase == "done" then
    ui.screen("completed", { team = s.team, step = s.step, of = s.of, done = s.done })
  else
    ui.screen("inactive", { done = s.of > 0 and s.done or nil, of = s.of > 0 and s.of or nil })
  end
end

local function light()
  if s.phase == "active" then
    cap("team_display"):show(s.owner or "white")
  elseif s.phase == "done" then
    cap("team_display"):show(s.team or "none")
  else
    cap("team_display"):show("none")
  end
end

local function capture(team, squad)
  local previous = s.owner
  s.owner = team
  s.since = math.floor(game.time())
  taker, progress = nil, nil
  audio.play("captured")
  emit("zone.captured", { team = team, squad = squad, previous_team = previous })
  light()
  draw()
end

on("game.start", function()
  light()
  draw()
end)

-- After a power loss the script starts again, with what state.node kept in a
-- game picked on the box; in a field game field.lua says it all again.
on("node.rebooted", function()
  light()
  draw()
end)

on("team_input.hold", function(e)
  if s.phase ~= "active" or e.team == s.owner then
    return
  end
  if e.ms < params.capture_hold_ms then
    taker = e.team
    -- In hundredths, so the screen gets few distinct values to redraw.
    progress = math.floor(e.ms * 100 / math.max(1, params.capture_hold_ms)) / 100
    return draw()
  end
  capture(e.team, e.squad)
end)

-- Letting go too soon empties the bar.
on("team_input.release", function(e)
  if e.team == taker then
    taker, progress = nil, nil
    if s.phase == "active" then
      draw()
    end
  end
end)

-- The GM's owner override from the console: only the active box takes it.
on("cmd.set_owner", function(e)
  if s.phase ~= "active" then
    return
  end
  local free = e.team == nil or e.team == "" or e.team == "none"
  if e.team == s.owner or (free and s.owner == nil) then
    return
  end
  if free then
    emit("zone.neutralized", { previous_team = s.owner })
    s.owner = nil
    taker, progress = nil, nil
    light()
    draw()
  else
    capture(e.team)
  end
end)

-- From field.lua: this box's phase and the progress of the game.
on("cmd.mode", function(e)
  if e.name ~= "pd" then
    return
  end
  local n = math.tointeger(e.n) or 0
  local phase = e.phase
  if n <= s.n or (phase ~= "wait" and phase ~= "active" and phase ~= "done") then
    return
  end
  local was = s.phase
  s.n, s.phase = n, phase
  s.step = math.tointeger(e.step) or 0
  s.of = math.tointeger(e.of) or 0
  s.done = math.tointeger(e.done) or 0
  s.team = type(e.team) == "string" and e.team or nil
  if phase == "active" and was ~= "active" then
    -- A new turn: the box starts free, and says so loud.
    s.owner, s.since = nil, 0
    taker, progress = nil, nil
    audio.play("alarm")
  elseif phase ~= "active" then
    taker, progress = nil, nil
    if phase == "done" and was ~= "done" then
      audio.play("defused")
    end
  end
  light()
  draw()
end)

every(REFRESH_S, function()
  if s.phase == "active" and s.owner then
    draw()
  end
end)

on("game.end", function()
  taker, progress = nil, nil
  ui.screen("final_score", { owner = s.owner or s.team })
end)
