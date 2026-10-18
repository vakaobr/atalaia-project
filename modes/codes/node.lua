-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Codes (a modifier): keypad codes grant points, hints or unlocks, alongside
-- any main mode on the same box. params.codes lists them as
-- digits:kind[:points][:team], comma-separated, for example
-- "4711:points:50,0815:hint,2222:unlock:red". Type the digits, then #;
-- * clears. Each code works once per game. code.used tells the game master
-- which code (its place in the list), what it gave, the team it counted for
-- (the code's team, else the team holding the box) and the holding team.

local codes = {} -- digits -> { id, kind, amount, team }
local used = {}
local kinds = { p = "points", h = "hint", u = "unlock" }
local index = 0
for entry in string.gmatch(params.codes or "", "[^,]+") do
  index = index + 1
  local f = {}
  for part in string.gmatch(entry, "[^:%s]+") do
    f[#f + 1] = part
  end
  local kind = f[2] and kinds[string.sub(f[2], 1, 1)]
  local amount = kind == "points" and math.tointeger(tonumber(f[3] or "")) or nil
  if
    f[1]
    and string.match(f[1], "^%d+$")
    and kind
    and (kind ~= "points" or (amount and amount > 0))
  then
    local team = f[3]
    if kind == "points" then
      team = f[4]
    end
    codes[f[1]] = { id = tostring(index), kind = kind, amount = amount, team = team }
  else
    log("codes: entry " .. index .. " is not digits:kind[:points][:team]; it is ignored")
  end
end

-- Other scripts on this box that read keypad codes (Bomb's team codes) list
-- a check here, so that a code meant for one of them is not "wrong" here.
keypad_codes = keypad_codes or {}
local function mine(c)
  return codes[c] ~= nil
end
keypad_codes[#keypad_codes + 1] = mine
local function known_elsewhere(c)
  for _, knows in ipairs(keypad_codes) do
    if knows ~= mine and knows(c) then
      return true
    end
  end
  return false
end

-- The team holding the box: the main mode's last capture.
local holder
on("zone.captured", function(e)
  holder = e.team
end)
on("zone.neutralized", function()
  holder = nil
end)

-- While a code is being typed, this prompt owns the screen: the main mode's
-- screens wait, and the newest one comes back when the prompt closes.
local show = ui.screen
local last -- the main mode's newest screen
local open = false
local typed = ""
local closer

ui.screen = function(template, data)
  last = { template, data }
  if not open then
    show(template, data)
  end
end

local function close()
  open, typed, closer = false, "", nil
  if last then
    show(last[1], last[2])
  else
    show("code_entry", { title = "CODE", digits = 0 })
  end
end

local function prompt(message, failed, linger_s)
  open = true
  show("code_entry", { title = "CODE", digits = #typed, message = message, error = failed })
  if closer then
    cancel(closer)
  end
  closer = after(linger_s, close)
end

local function use(c)
  local code = codes[c]
  if used[c] then
    return prompt("Code already used", true, 3)
  end
  local team = code.team or holder
  if code.kind == "points" and team == nil then
    return prompt("No team holds this box", true, 3)
  end
  used[c] = true
  emit(
    "code.used",
    { team = team, code = code.id, kind = code.kind, amount = code.amount, holder = holder }
  )
  if code.kind == "points" then
    score.add(team, code.amount, "code")
    prompt("+" .. code.amount .. " points for " .. string.upper(team), false, 3)
  elseif code.kind == "hint" then
    prompt("Hint: the game master is told", false, 3)
  else
    prompt("Unlocked", false, 3)
  end
end

on("keypad.key", function(e)
  local k = e.key
  if k == "#" then
    local c = typed
    typed = ""
    if codes[c] then
      use(c)
    elseif c ~= "" and known_elsewhere(c) then
      close()
    elseif c ~= "" then
      prompt("Wrong code", true, 3)
    end
  elseif k == "*" then
    typed = ""
    prompt(nil, false, 10)
  elseif string.match(k or "", "^%d$") and #typed < 8 then
    typed = typed .. k
    prompt(nil, false, 10)
  end
end)

on("game.start", function()
  if last == nil then
    show("code_entry", { title = "CODE", digits = 0 })
  end
end)

on("game.end", function()
  if closer then
    cancel(closer)
  end
  if open then
    close()
  end
end)
