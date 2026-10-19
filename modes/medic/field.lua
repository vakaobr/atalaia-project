-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Medic Kit, on the field controller: counts every kit's heals per player for
-- the whole game and tells the kits ("heals" mode command), so a player with a
-- limit of 2 is not healed twice at every kit. A kit out of reach heals with
-- its own count; its medic.heal arrives later (the box resends it) and carries
-- the count the kit knew, so the total here is the larger of the two. A kit
-- that rebooted is told every count again.

local used = {} -- player -> heals in the game, at every kit
local last = {} -- player -> game time (s) the controller heard of their last heal

local function tell(node_id, player)
  field.send(
    node_id,
    "mode",
    { name = "heals", player = player, used = used[player], at = last[player] }
  )
end

on("medic.heal", function(e)
  if type(e.player) ~= "string" then
    return
  end
  local n = (used[e.player] or 0) + 1
  local kit_knew = math.tointeger(e.player_heals_used) or 0
  if kit_knew > n then
    n = kit_knew
  end
  -- Whole seconds keep the command short (a box takes 127 bytes of parameters).
  used[e.player], last[e.player] = n, math.floor(game.time())
  for _, kit in ipairs(field.nodes("medic")) do
    -- The kit that healed knows its own count unless it was behind.
    if kit.id ~= e.node or kit_knew < n then
      tell(kit.id, e.player)
    end
  end
end)

on("node.rebooted", function(e)
  for _, kit in ipairs(field.nodes("medic")) do
    if kit.id == e.node then
      for player in pairs(used) do
        tell(kit.id, player)
      end
    end
  end
end)
