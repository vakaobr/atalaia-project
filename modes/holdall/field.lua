-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Hold-All Domination, on the field controller: while one team holds every
-- zone box (and at least params.min_zones of them are in play), it scores
-- params.points_per_tick every params.tick_s seconds. Box owners come from
-- the boxes' STATE reports, which can arrive a little after the capture
-- event, so the check also runs every second.

local fs = state.field { holder = nil }
local tick

local function zone_ids()
  local ids = {}
  for _, n in ipairs(field.nodes("zone")) do
    ids[#ids + 1] = n.id
  end
  return ids
end

local function check()
  local ids = zone_ids()
  local team = nil
  if #ids >= params.min_zones then
    team = field.common_owner(ids)
  end
  if team == fs.holder then
    return
  end
  if fs.holder ~= nil then
    cancel(tick)
    tick = nil
    emit("holdall.scoring_stop", { team = fs.holder })
  end
  fs.holder = team
  if team ~= nil then
    emit("holdall.scoring_start", { team = team })
    -- The first points come one full tick after the last box fell.
    tick = every(params.tick_s, function()
      score.add(team, params.points_per_tick, "holdall")
    end)
  end
end

on("zone.captured", check)
on("zone.neutralized", check)
every(1, check)
