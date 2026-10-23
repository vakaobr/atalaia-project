-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Money Factory, on each node: a factory or a bank. Players identify
-- themselves with their signed NFC tag (protocol/nfc-tag.md).
--
-- * A factory makes params.production money every params.tick_s seconds, up
--   to params.capacity. With params.capture (the default) a team captures it
--   by holding its input for params.capture_hold_ms, as in Domination: it
--   makes money only while a team holds it, and only that team's players
--   collect. Without capture it always makes money and anyone collects.
--   A scan takes all the factory holds, up to what the player may still carry
--   (params.carry_max; 0: no limit): money.collected.
-- * A bank takes all a player carries: money.deposited, and as many points
--   for the player's team, on this box.
--
-- One script plays both roles, and a script does not know its role (decision
-- M5-5): a node is a factory until the controller's field.lua tells it it is a
-- bank (the mode command "bank"). What a player carries lives in field.lua,
-- which tells every bank (and every factory, when carrying has a limit) each
-- player's money with the mode command "wallet" (amount, and n, which grows
-- with each change, so an older or repeated word is ignored). A node out of the
-- controller's reach goes on with what it knows and what it did itself.
-- Refusals say why on the screen (`reason`); the texts are in the templates.
-- Screens (assets/screens/): neutral, captured, factory, collected, bank,
-- deposited, refused; final_score at the end (the Field Box's built-in one).

local SHOW_S = 4 -- a result stays on the screen this long

local tag_refusals = {
  mac = "forged", -- signed with another key
  game = "game", -- a tag from another game
  no_game = "no_game", -- this box is not in a controller's game
  team = "no_team", -- a team this game does not have
}

local s = state.node { owner = nil, since = 0, stock = 0 }
local bank = false -- told by field.lua
local wallets = {} -- player -> { amount, n }: what each player carries
local banked = {} -- team -> money deposited at this bank
local order = {} -- teams in the order they first banked here
local taker, progress -- a team holding its input to take the factory, and how far (0-1)
local back -- the timer that brings the main screen back after a result

local function carried(player)
  local w = wallets[player]
  return w and w.amount or 0
end

-- This node's own change: the controller's next word (a larger n) overrides it.
local function set_carried(player, amount)
  local w = wallets[player]
  wallets[player] = { amount = amount, n = w and w.n or 0 }
end

local function counts()
  local parts = {}
  for _, team in ipairs(order) do
    parts[#parts + 1] = string.upper(team) .. " " .. banked[team]
  end
  return table.concat(parts, "  ")
end

local function draw()
  if bank then
    local total = 0
    for _, team in ipairs(order) do
      total = total + banked[team]
    end
    ui.screen("bank", { total = total, counts = counts() })
  elseif not params.capture then
    ui.screen("factory", { stock = s.stock })
  elseif s.owner then
    ui.screen(
      "captured",
      { team = s.owner, since = s.since, stock = s.stock, taker = taker, progress = progress }
    )
  else
    ui.screen("neutral", { stock = s.stock, taker = taker, progress = progress })
  end
end

-- The main screen again, unless a result is still showing.
local function refresh()
  if back == nil then
    draw()
  end
end

-- A result screen, then the main screen again after SHOW_S.
local function show(name, data)
  if back then
    cancel(back)
  end
  ui.screen(name, data)
  back = after(SHOW_S, function()
    back = nil
    draw()
  end)
end

local function refuse(reason, data)
  data = data or {}
  data.reason = reason
  log("money: refused (" .. reason .. ")" .. (data.player and (" for " .. data.player) or ""))
  show("refused", data)
end

local function collect(e)
  local who = { player = e.player, team = e.team, carrying = carried(e.player) }
  if params.capture then
    if s.owner == nil then
      return refuse("neutral", who)
    end
    if e.team ~= s.owner then
      return refuse("not_yours", who)
    end
  end
  local room = s.stock
  if params.carry_max > 0 then
    room = params.carry_max - who.carrying
    if room <= 0 then
      return refuse("full", who)
    end
  end
  if s.stock <= 0 then
    return refuse("empty", who)
  end
  local take = math.min(s.stock, room)
  s.stock = s.stock - take
  set_carried(e.player, who.carrying + take)
  emit("money.collected", { team = e.team, player = e.player, amount = take })
  audio.play("collected")
  show("collected", {
    player = e.player,
    team = e.team,
    amount = take,
    carrying = who.carrying + take,
    stock = s.stock,
  })
end

local function deposit(e)
  local amount = carried(e.player)
  if amount <= 0 then
    return refuse("nothing", { player = e.player, team = e.team, carrying = 0 })
  end
  set_carried(e.player, 0)
  if banked[e.team] == nil then
    banked[e.team] = 0
    order[#order + 1] = e.team
  end
  banked[e.team] = banked[e.team] + amount
  emit("money.deposited", { team = e.team, player = e.player, amount = amount })
  score.add(e.team, amount, "deposit")
  audio.play("deposited")
  show("deposited", { player = e.player, team = e.team, amount = amount, total = banked[e.team] })
end

on("game.start", draw)

-- After a power loss the script starts again: the factory's holder (kept in
-- state.node in a game picked on the box) gets its colour back. In a field
-- game field.lua tells a bank again what it is and what players carry.
on("node.rebooted", function()
  if s.owner and not bank then
    cap("team_display"):show(s.owner)
  end
  draw()
end)

on("nfc.tag", function(e)
  if not e.valid then
    log("money: tag " .. tostring(e.uid) .. " refused: " .. tostring(e.reason))
    -- unsigned, format and version: not a player tag of this system
    return refuse(tag_refusals[e.reason] or "not_tag")
  end
  if e.team == nil then
    return refuse("no_team", { player = e.player })
  end
  if bank then
    deposit(e)
  else
    collect(e)
  end
end)

every(params.tick_s, function()
  if bank or (params.capture and s.owner == nil) or s.stock >= params.capacity then
    return
  end
  s.stock = math.min(params.capacity, s.stock + params.production)
  refresh()
end)

local function capture(team, squad)
  local previous = s.owner
  s.owner = team
  s.since = math.floor(game.time())
  taker, progress = nil, nil
  cap("team_display"):show(team)
  audio.play("captured")
  emit("zone.captured", { team = team, squad = squad, previous_team = previous })
  refresh()
end

on("team_input.hold", function(e)
  if bank or not params.capture or e.team == s.owner then
    return
  end
  if e.ms < params.capture_hold_ms then
    taker = e.team
    -- In hundredths, so the screen gets few distinct values to redraw.
    progress = math.floor(e.ms * 100 / math.max(1, params.capture_hold_ms)) / 100
    return refresh()
  end
  capture(e.team, e.squad)
end)

-- Letting go too soon empties the bar.
on("team_input.release", function(e)
  if e.team == taker then
    taker, progress = nil, nil
    refresh()
  end
end)

-- The GM's owner override from the console: a team, or none to free the factory.
on("cmd.set_owner", function(e)
  if bank or not params.capture then
    return
  end
  local free = e.team == nil or e.team == "" or e.team == "none"
  if e.team == s.owner or (free and s.owner == nil) then
    return
  end
  if free then
    emit("zone.neutralized", { previous_team = s.owner })
    s.owner = nil
    cap("team_display"):show("none")
    refresh()
  else
    capture(e.team)
  end
end)

-- From field.lua: this node is a bank, and what a player carries.
on("cmd.mode", function(e)
  if e.name == "bank" then
    if not bank then
      bank = true
      taker, progress = nil, nil
      cap("team_display"):show("none")
      refresh()
    end
  elseif e.name == "wallet" and type(e.player) == "string" then
    local n = math.tointeger(e.n) or 0
    local w = wallets[e.player]
    if w == nil or n > w.n then
      wallets[e.player] = { amount = math.max(0, math.tointeger(e.amount) or 0), n = n }
    end
  end
end)

on("game.end", function()
  if back then
    cancel(back)
    back = nil
  end
  ui.screen("final_score", { owner = not bank and s.owner or nil })
end)
