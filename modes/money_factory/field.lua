-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Money Factory, on the field controller: the state shared between boxes
-- (decision A1's blocker). It
--
-- * tells every node of the role bank that it is one (the mode command
--   "bank"): at the start, within a second for a bank that joins late, again
--   every REMIND_S seconds in case a word was lost, and after it rebooted;
-- * keeps what each player carries (wallets): money.collected adds to it,
--   money.deposited takes from it, and with params.drop_on_heal a heal at a
--   medic kit (medic.heal, from the Medic Kit's role package in the same game)
--   empties it. After each change it tells every bank, and every factory when
--   carrying has a limit, the player's money (the mode command "wallet",
--   with n, which grows with each change of that player's wallet);
-- * counts the money each team banked (state.field.banked) and, with a
--   params.target, ends the game won by the first team to bank it.
--
-- A node out of reach misses words; its events arrive later (a box resends
-- them), and the wallet follows them: a deposit takes at most what the player
-- carries here, never below 0.

local REMIND_S = 30

local fs = state.field {}
local banked = {} -- team -> money banked at every bank
local wallets = {} -- player -> { amount, n }
local told = {} -- bank node id -> true once told it is a bank
local won = false

local function tell(node_id, player)
  local w = wallets[player]
  field.send(node_id, "mode", { name = "wallet", player = player, amount = w.amount, n = w.n })
end

-- The nodes that need to know what a player carries.
local function money_nodes()
  local nodes = field.nodes("bank")
  if params.carry_max > 0 then
    for _, n in ipairs(field.nodes("factory")) do
      nodes[#nodes + 1] = n
    end
  end
  return nodes
end

local function set_wallet(player, amount)
  local w = wallets[player] or { amount = 0, n = 0 }
  w.amount, w.n = math.max(0, amount), w.n + 1
  wallets[player] = w
  for _, n in ipairs(money_nodes()) do
    tell(n.id, player)
  end
end

local function tell_banks(all)
  for _, n in ipairs(field.nodes("bank")) do
    if all or not told[n.id] then
      if field.send(n.id, "mode", { name = "bank" }) then
        told[n.id] = true
      end
    end
  end
end

on("game.start", function()
  tell_banks(true)
end)

local since_reminder = 0
every(1, function()
  since_reminder = since_reminder + 1
  if since_reminder >= REMIND_S then
    since_reminder = 0
    tell_banks(true)
  else
    tell_banks(false)
  end
end)

on("money.collected", function(e)
  local amount = math.tointeger(e.amount)
  if type(e.player) ~= "string" or amount == nil or amount <= 0 then
    return
  end
  local w = wallets[e.player]
  set_wallet(e.player, (w and w.amount or 0) + amount)
end)

on("money.deposited", function(e)
  local amount = math.tointeger(e.amount)
  if type(e.player) ~= "string" or amount == nil or amount <= 0 then
    return
  end
  local w = wallets[e.player]
  set_wallet(e.player, (w and w.amount or 0) - amount)
  if type(e.team) == "string" then
    banked[e.team] = (banked[e.team] or 0) + amount
    -- state.field reaches the console when a key is set: a new table each time.
    local copy = {}
    for team, money in pairs(banked) do
      copy[team] = money
    end
    fs.banked = copy
    if params.target > 0 and banked[e.team] >= params.target and not won then
      won = true
      log("money: " .. e.team .. " banked " .. banked[e.team] .. " of " .. params.target)
      game.win(e.team)
    end
  end
end)

on("medic.heal", function(e)
  if not params.drop_on_heal or type(e.player) ~= "string" then
    return
  end
  local w = wallets[e.player]
  if w and w.amount > 0 then
    log("money: " .. e.player .. " was healed and lost " .. w.amount)
    set_wallet(e.player, 0)
  end
end)

-- A node that rebooted knows nothing: a bank is told again what it is, and
-- every node that needs them every player's money.
on("node.rebooted", function(e)
  for _, n in ipairs(field.nodes("bank")) do
    if n.id == e.node then
      told[n.id] = nil
      tell_banks(false)
    end
  end
  for _, n in ipairs(money_nodes()) do
    if n.id == e.node then
      for player, w in pairs(wallets) do
        if w.amount > 0 then
          tell(n.id, player)
        end
      end
    end
  end
end)
