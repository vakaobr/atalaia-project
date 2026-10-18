-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Player Check-in: players check in at a checkpoint with their signed NFC
-- tag (protocol/nfc-tag.md). The box counts check-ins per team and gives the
-- player's team `points` for each. A player counts once per game, or again
-- after repeat_after_s seconds; a scan before that is a duplicate and is
-- refused. Forged tags, tags from another game and tags without a team are
-- refused (the shell checks the signature and says why in nfc.tag's reason).

local refused = {
  unsigned = "Not a game tag",
  no_game = "No game: join one first",
  game = "Tag from another game",
  mac = "Forged tag",
  team = "Unknown team",
  format = "Damaged tag",
  version = "Unknown tag version",
}

local seen = {} -- player -> game time of their last check-in that counted
local count = {} -- team -> check-ins
local order = {} -- teams in the order they first checked in
local total = 0
local last_team
local message, failed, fade

local function counts()
  local parts = {}
  for _, team in ipairs(order) do
    parts[#parts + 1] = string.upper(team) .. " " .. count[team]
  end
  return table.concat(parts, "  ")
end

local function show()
  ui.screen("checkin", {
    total = total,
    counts = counts(),
    team = last_team,
    message = message,
    error = failed,
  })
end

-- A message under the counts, cleared after 4 s.
local function say(text, bad)
  message, failed = text, bad
  show()
  if fade then
    cancel(fade)
  end
  fade = after(4, function()
    fade = nil
    message, failed = nil, false
    show()
  end)
end

on("game.start", show)

on("nfc.tag", function(e)
  if not e.valid then
    log("check-in: tag " .. tostring(e.uid) .. " refused: " .. tostring(e.reason))
    return say(refused[e.reason] or "Not a game tag", true)
  end
  if e.team == nil then
    return say("This tag has no team", true)
  end
  local t = seen[e.player]
  if t and (params.repeat_after_s == 0 or game.time() - t < params.repeat_after_s) then
    return say("Already checked in", true)
  end
  seen[e.player] = game.time()
  if count[e.team] == nil then
    count[e.team] = 0
    order[#order + 1] = e.team
  end
  count[e.team] = count[e.team] + 1
  total = total + 1
  last_team = e.team
  emit("player.checkin", { team = e.team, player = e.player })
  score.add(e.team, params.points, "checkin")
  say("Checked in: " .. e.player, false)
end)
