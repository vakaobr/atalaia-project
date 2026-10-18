-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Kill Confirmed: players carry signed NFC tags (protocol/nfc-tag.md). A team
-- presses its button at the station, then scans the tags it collected within
-- turn_in_s seconds (each scan keeps the station open). An enemy's tag
-- confirms the kill: confirm_points for the team, penalty_points off the
-- tag's team. A teammate's tag denies the kill: no points. The same player's
-- tag counts again only after retag_after_s. Forged tags, tags from another
-- game and tags without a team are refused; the shell checks the signature
-- with the game key and says why in nfc.tag's reason.

local refused = {
  unsigned = "Not a game tag",
  no_game = "No game: join one first",
  game = "Tag from another game",
  mac = "Forged tag",
  team = "Unknown team",
  format = "Damaged tag",
  version = "Unknown tag version",
}

local open_team -- the team turning in tags
local closes_at = 0
local closer
local counted = {} -- player -> game time when their tag last counted
local message, failed, fade

local function show()
  local data = { message = message, error = failed }
  if open_team then
    data.team = open_team
    data.left = math.max(0, math.ceil(closes_at - game.time()))
  end
  ui.screen("tags", data)
end

-- A message under the station's state, cleared after 4 s.
local function say(text, bad)
  message, failed = text, bad
  show()
  if fade then
    cancel(fade)
    fade = nil
  end
  if text then
    fade = after(4, function()
      fade = nil
      message, failed = nil, false
      show()
    end)
  end
end

local function close()
  open_team, closer = nil, nil
  say(nil, false)
end

local function open(team)
  open_team = team
  closes_at = game.time() + params.turn_in_s
  if closer then
    cancel(closer)
  end
  closer = after(params.turn_in_s, close)
end

on("game.start", show)

on("team_input.press", function(e)
  open(e.team)
  say("Scan your tags", false)
end)

on("nfc.tag", function(e)
  if not e.valid then
    log("kill confirmed: tag " .. tostring(e.uid) .. " refused: " .. tostring(e.reason))
    return say(refused[e.reason] or "Not a game tag", true)
  end
  if open_team == nil then
    return say("Press your team's button first", true)
  end
  if e.team == nil then
    return say("This tag has no team", true)
  end
  local last = counted[e.player]
  if last and game.time() - last < params.retag_after_s then
    return say("Tag already counted", true)
  end
  counted[e.player] = game.time()
  open(open_team)
  if e.team == open_team then
    emit("kill.denied", { team = open_team, player = e.player, owner = e.team })
    say("Kill denied: " .. e.player, false)
  else
    emit("kill.confirmed", { team = open_team, player = e.player, owner = e.team })
    score.add(open_team, params.confirm_points, "kill")
    score.add(e.team, -params.penalty_points, "killed")
    say("Kill confirmed: " .. e.player, false)
  end
end)

-- The time left to scan, once a second while the station is open.
every(1, function()
  if open_team then
    show()
  end
end)
