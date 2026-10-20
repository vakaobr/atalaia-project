-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Bomb / Rush: attackers arm, defenders defuse before the fuse runs out.
-- With team codes (params.team_codes, e.g. "red=1234,blue=5678") the keypad
-- arms and defuses instead of the team buttons: in standby a team's code
-- arms the bomb for that team; once armed, another team's code defuses it.

local s = state.node { phase = "standby", explode_at = 0, armed_by = nil, defused_by = nil }
local fuse_timer

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

-- The prop's screen follows the phase: standby, countdown, defused, exploded.
local function show_countdown()
  local left = math.ceil(s.explode_at - game.time())
  if use_codes then
    ui.screen("countdown", { left = left, team = s.armed_by })
  else
    ui.screen("countdown", { left = left, defuse = holding })
  end
end

local function show_standby()
  if use_codes then
    ui.screen("code_entry", { title = "ARM", digits = 0, message = "Enter your team code" })
  else
    ui.screen("standby", { arm = params.attackers, progress = holding })
  end
end

local function show_phase()
  if typing then
    cancel(typing)
  end
  typed, typing = "", nil
  if s.phase == "standby" then
    show_standby()
  elseif s.phase == "armed" then
    show_countdown()
  elseif s.phase == "defused" then
    ui.screen("defused", { team = s.defused_by })
  else
    ui.screen("exploded", { team = s.armed_by })
  end
end

local function explode()
  s.phase = "exploded"
  audio.play("explosion")
  show_phase()
  emit("bomb.exploded", { team = s.armed_by }, { prio = "critical" })
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
  audio.play("defused")
  s.defused_by = team
  s.phase = params.reset_after_defuse and "standby" or "defused"
  show_phase()
  emit("bomb.defused", { team = team, reason = how }, { prio = "critical" })
end

on("game.start", show_standby)

-- The share of a hold, in hundredths, so the screen gets few distinct values.
local function share(ms, total)
  return math.floor(ms * 100 / total) / 100
end

on("team_input.hold", function(e)
  if use_codes then
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
    prompt("The bomb is " .. s.phase, true, 3)
  end
end

on("keypad.key", function(e)
  if not use_codes then
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

if params.auto_arm_after_s then
  after(params.auto_arm_after_s, function()
    if s.phase == "standby" then
      arm(params.attackers)
    end
  end)
end

every(1, function()
  if s.phase ~= "armed" then
    return
  end
  if typing == nil then
    show_countdown()
  else
    draw()
  end
end)
