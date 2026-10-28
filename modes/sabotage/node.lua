-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Sabotage: Bomb / Rush rounds until the game time runs out. The attackers
-- arm, the defenders defuse before the fuse runs out; an explosion scores a
-- point for the attackers, a defuse one for the defenders, then the box shows
-- the result, rests for params.pause_s and goes back to standby. At
-- params.game_time_min the game ends and the team with more points wins (equal:
-- a draw). A bomb still armed at that moment does not count (decision SAB-3).
-- With team codes (params.team_codes, e.g. "red=1234,blue=5678") the keypad
-- arms and defuses instead of the team buttons, as in Bomb.
-- Phases: standby, armed, defused / exploded (the result, RESULT_S), pause.

local RESULT_S = 5 -- how long the result of a round stays on the screen

local s = state.node {
  phase = "standby",
  explode_at = 0,
  resume_at = 0,
  armed_by = nil,
  defused_by = nil,
  round = 0,
  over = false,
  last = "",
}
local fuse_timer, phase_timer

local team_of = {} -- code -> team
local use_codes = false
for team, code in string.gmatch(params.team_codes or "", "([^=,%s]+)=(%d+)") do
  team_of[code] = team
  use_codes = true
end
-- Scripts on this box that read keypad codes list a check here (see the
-- Codes modifier), so a code meant for another script is not "wrong" here.
keypad_codes = keypad_codes or {}
local function mine(c)
  return team_of[c] ~= nil
end
if use_codes then
  keypad_codes[#keypad_codes + 1] = mine
end
local typed = ""
local typing -- while a code prompt is up: the timer that gives the screen back to the phase
local note, note_failed -- the prompt's message
-- How far the team holding its button now is with arming or defusing
-- (0-1), nil while nobody holds: the phase screen shows it as it fills.
local holding

local limit_s = params.game_time_min * 60

local function game_left()
  return math.max(0, math.ceil(limit_s - game.time()))
end

local function points()
  return score.get(params.attackers), score.get(params.defenders)
end

-- The leading team, nil for a draw.
local function leader()
  local a, d = points()
  if a > d then
    return params.attackers
  elseif d > a then
    return params.defenders
  end
  return nil
end

local function show_countdown()
  local left = math.ceil(s.explode_at - game.time())
  if use_codes then
    ui.screen("countdown", { left = left, team = s.armed_by })
  else
    ui.screen("countdown", { left = left, defuse = holding })
  end
end

local function show_standby()
  local a, d = points()
  if use_codes then
    local message = string.upper(params.attackers)
      .. " "
      .. a
      .. " - "
      .. d
      .. " "
      .. string.upper(params.defenders)
    ui.screen("code_entry", { title = "ARM", digits = 0, message = message })
  else
    ui.screen("standby", {
      arm = params.attackers,
      defend = params.defenders,
      progress = holding,
      a_points = a,
      d_points = d,
      round = s.round + 1,
      game_left = game_left(),
    })
  end
end

local function show_pause()
  local a, d = points()
  ui.screen("pause", {
    a_points = a,
    d_points = d,
    attackers = params.attackers,
    defenders = params.defenders,
    left = math.max(0, math.ceil(s.resume_at - game.time())),
    exploded = s.last == "exploded",
    game_left = game_left(),
  })
end

local function show_phase()
  if typing then
    cancel(typing)
  end
  typed, typing = "", nil
  if s.over then
    return
  end
  if s.phase == "standby" then
    show_standby()
  elseif s.phase == "armed" then
    show_countdown()
  elseif s.phase == "defused" then
    ui.screen("defused", { team = s.defused_by })
  elseif s.phase == "exploded" then
    ui.screen("exploded", { team = s.armed_by })
  else
    show_pause()
  end
end

local function to_standby()
  phase_timer = nil
  s.phase = "standby"
  show_phase()
end

local function to_pause()
  phase_timer = nil
  if params.pause_s <= 0 then
    return to_standby()
  end
  s.phase = "pause"
  s.resume_at = game.time() + params.pause_s
  phase_timer = after(params.pause_s, to_standby)
  show_phase()
end

-- A round ended: the result on screen for RESULT_S, then the pause.
local function end_round(result)
  s.round = s.round + 1
  s.phase = result
  s.last = result
  phase_timer = after(math.min(RESULT_S, math.max(params.pause_s, 1)), to_pause)
  show_phase()
end

local function explode()
  if s.over then
    return
  end
  score.add(s.armed_by, 1, "sabotage")
  audio.play("explosion")
  emit("bomb.exploded", { team = s.armed_by }, { prio = "critical" })
  end_round("exploded")
end

local function arm(team, how)
  holding = nil
  s.phase = "armed"
  s.armed_by = team
  s.explode_at = game.time() + params.fuse_s
  -- The explosion is its own timer, so it lands exactly on time no matter
  -- when the bomb was armed relative to the display tick below.
  fuse_timer = after(params.fuse_s, explode)
  audio.play("armed")
  show_phase()
  emit("bomb.armed", { team = team, fuse_s = params.fuse_s, reason = how }, { prio = "critical" })
end

local function defuse(team, how)
  holding = nil
  cancel(fuse_timer)
  score.add(team, 1, "sabotage")
  audio.play("defused")
  s.defused_by = team
  emit("bomb.defused", { team = team, reason = how }, { prio = "critical" })
  end_round("defused")
end

-- The game's end: by the time limit (here) or from the console. The leader
-- wins; a bomb still armed is dropped and scores nothing.
local function finish()
  if s.over then
    return
  end
  s.over = true
  if s.phase == "armed" then
    cancel(fuse_timer)
  end
  local a, d = points()
  ui.screen("game_over", {
    winner = leader(),
    attackers = params.attackers,
    defenders = params.defenders,
    a_points = a,
    d_points = d,
  })
end

on("game.end", finish)

on("game.start", show_standby)

-- After a power loss a box picked for a game on its own gives the state back
-- (decision HB-7): an armed bomb goes on with the fuse it had left (or
-- explodes at once when it ran out meanwhile), a result or pause goes on with
-- what it had left, and the screen shows the phase again. In a field game the
-- state starts afresh: standby.
on("node.rebooted", function()
  holding = nil
  if s.over then
    return finish()
  end
  if s.phase == "armed" then
    local left = s.explode_at - game.time()
    if left > 0 then
      fuse_timer = after(left, explode)
    else
      return explode()
    end
  elseif s.phase == "defused" or s.phase == "exploded" then
    phase_timer = after(1, to_pause)
  elseif s.phase == "pause" then
    phase_timer = after(math.max(0.1, s.resume_at - game.time()), to_standby)
  end
  show_phase()
end)

-- The share of a hold, in hundredths, so the screen gets few distinct values.
local function share(ms, total)
  return math.floor(ms * 100 / total) / 100
end

on("team_input.hold", function(e)
  if use_codes or s.over then
    return
  end
  if s.phase == "standby" and e.team == params.attackers then
    if e.ms >= params.arm_hold_ms then
      arm(e.team)
    else
      holding = share(e.ms, params.arm_hold_ms)
      show_standby()
    end
  elseif s.phase == "armed" and e.team == params.defenders then
    if e.ms >= params.defuse_hold_ms then
      defuse(e.team)
    else
      holding = share(e.ms, params.defuse_hold_ms)
      show_countdown()
    end
  end
end)

-- Letting go early empties the bar.
on("team_input.release", function(e)
  if holding == nil then
    return
  end
  local holder = (s.phase == "standby" and e.team == params.attackers)
    or (s.phase == "armed" and e.team == params.defenders)
  if holder then
    holding = nil
    show_phase()
  end
end)

-- Team codes: the prompt shows the digits typed (and the fuse while armed).
local function draw()
  local title = s.phase == "armed" and "DEFUSE" or "ARM"
  local data = { title = title, digits = #typed, message = note, error = note_failed }
  if s.phase == "armed" then
    data.left = math.ceil(s.explode_at - game.time())
  end
  ui.screen("code_entry", data)
end

local function prompt(message, failed, linger_s)
  note, note_failed = message, failed
  draw()
  if typing then
    cancel(typing)
  end
  typing = after(linger_s, show_phase)
end

local function enter(c)
  local team = team_of[c]
  typed = ""
  if team == nil then
    if c ~= "" and keypad_codes and #keypad_codes > 1 then
      for _, knows in ipairs(keypad_codes) do
        if knows ~= mine and knows(c) then
          return show_phase() -- another script's code
        end
      end
    end
    return prompt("Wrong code", true, 3)
  end
  if s.phase == "standby" then
    arm(team, "code")
  elseif s.phase == "armed" and team ~= s.armed_by then
    defuse(team, "code")
  elseif s.phase == "armed" then
    prompt("Your team armed it", true, 3)
  else
    prompt("Next round soon", true, 3)
  end
end

on("keypad.key", function(e)
  if not use_codes or s.over then
    return
  end
  local k = e.key
  if k == "#" then
    enter(typed)
  elseif k == "*" then
    typed = ""
    prompt(nil, false, 10)
  elseif string.match(k or "", "^%d$") and #typed < 8 then
    typed = typed .. k
    prompt(nil, false, 10)
  end
end)

-- The time limit, by the game's clock (a timer made at load would start over
-- after a power loss).
every(1, function()
  if s.over then
    return
  end
  if game.time() >= limit_s then
    local winner = leader()
    if winner then
      return game.win(winner)
    end
    return game.finish("draw")
  end
  if s.phase == "armed" then
    if typing == nil then
      show_countdown()
    else
      draw()
    end
  elseif s.phase == "standby" and typing == nil and holding == nil then
    show_standby()
  elseif s.phase == "pause" then
    show_pause()
  end
end)
