-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- VIP / Payload, on the field controller.
--
-- * The VIP: the controller hands this script position.fix (player, team,
--   role, lat, lon, acc, src) for each new position report of a player whose
--   check-in role is vip, and to no other script (decision P4R6). A fix of the
--   escorting team's VIP inside the extraction zone extracts it: vip.extracted
--   with the player. A fix less precise than the zone's radius does not count.
--   Coordinates stay here: never in an event, a log line or state.field.
-- * The payload: its own phone checks the zone and emits vip.extracted; this
--   script takes that as the extraction (and emits nothing more).
-- * The extraction, once per game: params.vip_points for the escorting team,
--   and with params.end_on_extract the game ends, won by that team.
-- * Checkpoints: every second, the holder of each checkpoint (the boxes' own
--   reports, field.owner) is counted; a team that has held one for
--   params.tick_s seconds in a row scores params.checkpoint_points, and counts
--   again from zero.

local fs = state.field { extracted = false, by = nil }

-- "lat,lon" in degrees. A malformed one stops the game from starting, with this message.
local zone
if params.extraction ~= nil and params.extraction ~= "" then
  local lat, lon = string.match(params.extraction, "^%s*([%-+]?[%d.]+)%s*,%s*([%-+]?[%d.]+)%s*$")
  lat, lon = tonumber(lat), tonumber(lon)
  if not (lat and lon and lat >= -90 and lat <= 90 and lon >= -180 and lon <= 180) then
    error("extraction: latitude,longitude in degrees, e.g. 38.722345,-9.139312", 0)
  end
  zone = { type = "circle", lat = lat + 0.0, lon = lon + 0.0, radius_m = params.radius_m }
end

local function extract(by, player)
  fs.extracted = true
  fs.by = by
  if by == "vip" then
    emit("vip.extracted", { team = params.vip_team, player = player })
  end
  if params.vip_points > 0 then
    score.add(params.vip_team, params.vip_points, "extraction")
  end
  if params.end_on_extract then
    game.win(params.vip_team)
  end
end

on("position.fix", function(e)
  if fs.extracted or zone == nil or e.role ~= "vip" or e.team ~= params.vip_team then
    return
  end
  if type(e.lat) ~= "number" or type(e.lon) ~= "number" then
    return
  end
  if type(e.acc) == "number" and e.acc > params.radius_m then
    return
  end
  if geo.in_zone(e.lat, e.lon, zone) then
    extract("vip", type(e.player) == "string" and e.player or nil)
  end
end)

-- From the payload prop, which checked the zone itself.
on("vip.extracted", function(e)
  if not fs.extracted and e.team == params.vip_team then
    extract("payload")
  end
end)

local held = {} -- checkpoint node id -> { team, s }

every(1, function()
  if params.checkpoint_points <= 0 then
    return
  end
  for _, n in ipairs(field.nodes("checkpoint")) do
    local owner = field.owner(n.id)
    local h = held[n.id]
    if owner == nil then
      held[n.id] = nil
    elseif h == nil or h.team ~= owner then
      held[n.id] = { team = owner, s = 0 }
    else
      h.s = h.s + 1
      if h.s >= params.tick_s then
        h.s = 0
        score.add(owner, params.checkpoint_points, "checkpoint")
      end
    end
  end
end)
