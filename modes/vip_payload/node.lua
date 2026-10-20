-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- VIP / Payload, on each node. Two roles run this script:
--
-- * checkpoint: a team captures the box by holding its input, as in
--   Domination. Boxes do not score: the controller's field.lua scores the
--   holder of each checkpoint every params.tick_s seconds.
-- * payload: an Android prop with GPS. The app gives it gps.fix (lat, lon,
--   acc) from the phone's location; it checks the extraction zone itself with
--   geo.in_zone() and emits only vip.extracted, once: positions never leave
--   the phone (decision P4R6). Its screen shows the metres left to the zone.
--
-- A script does not know its role: only a role that uses gps gets gps.fix (the
-- app sends one without lat and lon when the game starts, before the phone's
-- first fix), and team inputs reach only checkpoints, so each part answers its
-- own inputs (decision M5-5). Screens (assets/screens/): checkpoint_free,
-- checkpoint_held, payload; final_score at the end (the Field Box's built-in).

local s = state.node { owner = nil, since = 0, extracted = false }
local payload = false -- set by the first gps.fix: this node is the payload

-- "lat,lon" in degrees; nil when empty or unreadable (field.lua refuses those at load).
local zone
do
  local lat, lon =
    string.match(params.extraction or "", "^%s*([%-+]?[%d.]+)%s*,%s*([%-+]?[%d.]+)%s*$")
  lat, lon = tonumber(lat), tonumber(lon)
  if lat and lon and lat >= -90 and lat <= 90 and lon >= -180 and lon <= 180 then
    zone = { type = "circle", lat = lat + 0.0, lon = lon + 0.0, radius_m = params.radius_m }
  end
end

local function show()
  if s.owner then
    ui.screen("checkpoint_held", { team = s.owner, since = s.since })
  else
    ui.screen("checkpoint_free", {})
  end
end

local function show_payload(state, metres)
  ui.screen("payload", { team = params.vip_team, state = state, metres = metres })
end

on("game.start", show)

-- Checkpoints.

local function capture(team, squad)
  emit("zone.captured", { team = team, squad = squad, previous_team = s.owner })
  s.owner = team
  s.since = math.floor(game.time())
  cap("team_display"):show(team)
  audio.play("captured")
  show()
end

on("team_input.hold", function(e)
  if not payload and e.team ~= s.owner and e.ms >= params.capture_hold_ms then
    capture(e.team, e.squad)
  end
end)

-- The GM's owner override: a team, or none to free the checkpoint.
on("cmd.set_owner", function(e)
  if payload then
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
    show()
  else
    capture(e.team)
  end
end)

-- The payload.

on("gps.fix", function(e)
  payload = true
  if s.extracted then
    return
  end
  if zone == nil then
    return show_payload("no_zone", 0)
  end
  if type(e.lat) ~= "number" or type(e.lon) ~= "number" then
    return show_payload("searching", 0)
  end
  -- A fix less precise than the zone's radius could put the payload in it by chance.
  if type(e.acc) == "number" and e.acc > params.radius_m then
    return show_payload("weak", math.floor(e.acc))
  end
  if geo.in_zone(e.lat, e.lon, zone) then
    s.extracted = true
    emit("vip.extracted", { team = params.vip_team })
    audio.play("captured")
    return show_payload("extracted", 0)
  end
  show_payload("moving", math.ceil(geo.distance(e.lat, e.lon, zone.lat, zone.lon) - zone.radius_m))
end)

on("game.end", function()
  ui.screen("final_score", { owner = s.owner })
end)
