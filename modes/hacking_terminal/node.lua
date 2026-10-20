-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Hacking Terminal: a puzzle on the keypad (decision P4R5; modes/README.md).
-- code: guess params.digits different digits, then #; the terminal counts
-- the digits in place and elsewhere (* clears). wires: press the wires'
-- numbers in the right order. sequence: a key shows params.digits keys
-- (1-9), one a second, then type them back (* shows them again). A wrong answer locks it for
-- params.lockout_s (the wires join again, the sequence is shown again; the
-- puzzle stays). Puzzles come from rand() (the game's seed and the node's id),
-- so a replay gets the same ones. The solving team: the last to press its
-- button since the last solve, else params.team. Solving
-- emits hacking.solved, scores params.points and shows params.reveal_code;
-- with params.capture the terminal becomes that team's (zone.captured) and,
-- after the solved screen, sets a new puzzle for the other teams. The
-- screens' texts are in their templates, in params.lang (note: which line).

local SOLVED_SHOW_S = 10

local puzzle = ({ wires = "wires", sequence = "sequence" })[params.puzzle] or "code" -- or unknown
local n = params.digits

local owner, solved -- the team holding a captured terminal; solved, until a new puzzle
local secret -- code: a string of digits; wires and sequence: a list of numbers
local typed, history, tries = "", {}, 0 -- code: the guess, the last three { guess, right, close }
local cut = {} -- wires: cut so far, in order
local phase, step = "idle", 0 -- sequence: idle, show or input; the key shown or typed
local locked_until, hacker, note
local lock_t, tick_t, show_t, again_t = 0, 0, 0, 0 -- timers (cancel(0) does nothing)

local function new_puzzle()
  local list = {}
  for i = 1, (puzzle == "code" and 10 or n) do
    list[i] = puzzle == "code" and i - 1 or (puzzle == "wires" and i or rand(1, 9))
  end
  if puzzle ~= "sequence" then
    for i = #list, 2, -1 do
      local j = rand(1, i)
      list[i], list[j] = list[j], list[i]
    end
  end
  secret = puzzle == "code" and table.concat(list, "", 1, n) or list
  typed, history, tries, cut, phase, step, note = "", {}, 0, {}, "idle", 0, nil
end

local function draw()
  if solved then
    return
  end
  local d = {
    team = hacker or params.team,
    owner = owner,
    locked = locked_until and math.max(1, math.ceil(locked_until - game.time())) or 0,
    note = note,
  }
  if puzzle == "code" then
    d.typed = (typed .. string.rep("_", n - #typed)):gsub(".", "%0 "):sub(1, 2 * n - 1)
    d.digits, d.tries, d.note = n, tries, note or "enter"
    for i, h in ipairs(history) do
      d["g" .. i], d["r" .. i], d["c" .. i] = h[1], h[2], h[3]
    end
    return ui.screen("hack_code", d)
  end
  d.of = n
  if puzzle == "wires" then
    local w = { 1, 2, 3, 4, 5, 6 }
    for _, c in ipairs(cut) do
      w[c] = "-"
    end
    d.wires, d.cut = table.concat(w, " ", 1, n), #cut
    return ui.screen("hack_wires", d)
  end
  d.phase, d.step, d.key = phase, step, phase == "show" and secret[step] or nil
  ui.screen("hack_sequence", d)
end

local function wrong()
  audio.play("armed") -- the warning tone
  cut, phase, step = {}, "idle", 0
  cancel(show_t)
  if params.lockout_s > 0 then
    locked_until = game.time() + params.lockout_s
    lock_t = after(params.lockout_s, function()
      cancel(tick_t)
      locked_until = nil
      draw()
    end)
    tick_t = every(1, draw)
  end
  draw()
end

local function solve()
  local team = hacker or params.team
  cancel(show_t)
  hacker = nil
  audio.play("defused") -- the success tone
  emit("hacking.solved", { team = team, puzzle = puzzle, code = params.reveal_code })
  if team and params.points > 0 then
    score.add(team, params.points, "hacking")
  end
  local capture = params.capture and team ~= nil
  ui.screen("hack_solved", { team = team, code = params.reveal_code, capture = capture })
  solved = true
  if capture then
    emit("zone.captured", { team = team, previous_team = owner })
    owner = team
    cap("team_display"):show(team)
    new_puzzle()
    again_t = after(SOLVED_SHOW_S, function()
      solved = false
      draw()
    end)
  end
end

-- The holder of a captured terminal cannot solve it again.
local function mine()
  if params.capture and owner and (hacker or params.team) == owner then
    note = "yours"
    return true
  end
end

local keys = {}

function keys.code(k)
  if k == "*" then
    typed = ""
  elseif k:match("^%d$") and #typed < n then
    typed = typed .. k
  elseif k == "#" and #typed < n then
    note = "short"
  elseif k == "#" then
    local guess = typed
    typed = ""
    if mine() then
      return draw()
    end
    tries = tries + 1
    if guess == secret then
      return solve()
    end
    local right, close, a, b = 0, 0, {}, {}
    for i = 1, n do
      local x, y = secret:sub(i, i), guess:sub(i, i)
      if x == y then
        right = right + 1
      else
        a[x], b[y] = (a[x] or 0) + 1, (b[y] or 0) + 1
      end
    end
    for digit, count in pairs(b) do
      close = close + math.min(count, a[digit] or 0)
    end
    table.insert(history, 1, { guess, right, close })
    history[4] = nil
    return wrong()
  end
  draw()
end

function keys.wires(k)
  local w = k:match("^%d$") and tonumber(k)
  if not w or w < 1 or w > n then
    return
  end
  for _, c in ipairs(cut) do
    if c == w then
      return
    end
  end
  if mine() then
    return draw()
  elseif secret[#cut + 1] ~= w then
    return wrong()
  end
  cut[#cut + 1] = w
  if #cut == n then
    return solve()
  end
  draw()
end

local function show_next()
  step = step + 1
  if step > n then
    cancel(show_t)
    phase, step = "input", 0
  end
  draw()
end

function keys.sequence(k)
  if phase == "idle" or (phase == "input" and k == "*") then
    if mine() then
      return draw()
    end
    phase, step = "show", 0
    show_t = every(1, show_next)
    return show_next()
  elseif phase ~= "input" or not k:match("^[1-9]$") then
    return
  elseif secret[step + 1] ~= tonumber(k) then
    return wrong()
  end
  step = step + 1
  if step == n then
    return solve()
  end
  draw()
end

local function stop_all()
  cancel(lock_t)
  cancel(tick_t)
  cancel(show_t)
  cancel(again_t)
end

on("game.start", function()
  new_puzzle()
  draw()
end)

on("team_input.press", function(e)
  hacker = e.team
  draw()
end)

on("keypad.key", function(e)
  if type(e.key) ~= "string" or solved or locked_until or not secret then
    return
  end
  note = nil
  keys[puzzle](e.key)
end)

-- The GM's "reset": a new puzzle, unlocked and unsolved; the holder stays.
on("cmd.mode", function(e)
  if e.name == "reset" then
    stop_all()
    locked_until, hacker, solved = nil, nil, false
    new_puzzle()
    log("hacking_terminal: new puzzle")
    draw()
  end
end)

-- The GM's owner override, when solving captures the terminal.
on("cmd.set_owner", function(e)
  local free = e.team == nil or e.team == "" or e.team == "none"
  if not params.capture or e.team == owner or (free and owner == nil) then
    return
  elseif free then
    emit("zone.neutralized", { previous_team = owner })
  else
    emit("zone.captured", { team = e.team, previous_team = owner })
  end
  owner = not free and e.team or nil
  cap("team_display"):show(owner or "none")
  draw()
end)

on("game.end", function()
  stop_all()
  ui.screen("final_score", { owner = owner })
end)
