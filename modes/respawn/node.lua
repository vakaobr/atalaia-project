-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Respawn and Lives: a respawn point counts lives. A player scans their
-- signed NFC tag (protocol/nfc-tag.md), or presses their team's button, to
-- come back into the game. Each respawn takes one of the team's `lives`, or
-- one of the player's own with per_player. A player waits respawn_cooldown_s
-- between respawns; button presses carry no player, so they only have a 2 s
-- guard against double presses. When a team has no lives left, the next
-- respawn is refused and team.eliminated is sent (once). Lives are counted on
-- this box: give each team one respawn point, or share one.

local refused = {
  unsigned = "Not a game tag",
  no_game = "No game: join one first",
  game = "Tag from another game",
  mac = "Forged tag",
  team = "Unknown team",
  format = "Damaged tag",
  version = "Unknown tag version",
}
local BUTTON_GUARD_S = 2

local lives = {} -- team, or player with per_player -> lives left
local last = {} -- player id, or "team:<team>" for buttons -> game time of the last respawn
local out = {} -- team -> true once team.eliminated was sent
local message, failed, fade
local shown = { lives = params.lives }

local function show()
  ui.screen("respawn", {
    team = shown.team,
    player = shown.player,
    lives = shown.lives,
    message = message,
    error = failed,
  })
end

-- A message under the lives count, cleared after 4 s.
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

local function lives_of(key)
  if lives[key] == nil then
    lives[key] = params.lives
  end
  return lives[key]
end

local function respawn(team, player)
  if params.per_player and player == nil then
    return say("Scan your tag", true)
  end
  if team == nil and not params.per_player then
    return say("This tag has no team", true)
  end
  local who = player or ("team:" .. team)
  local wait_s = player and params.respawn_cooldown_s or BUTTON_GUARD_S
  local t = last[who]
  if t and game.time() - t < wait_s then
    return say("Wait " .. math.ceil(wait_s - (game.time() - t)) .. " s", true)
  end
  local key = params.per_player and player or team
  shown.team, shown.player = team, player
  shown.lives = lives_of(key)
  if lives_of(key) <= 0 then
    if not params.per_player and not out[team] then
      out[team] = true
      emit("team.eliminated", { team = team })
    end
    return say(params.per_player and "No lives left" or "No lives left: team out", true)
  end
  lives[key] = lives[key] - 1
  last[who] = game.time()
  shown.lives = lives[key]
  emit("player.respawn", { team = team, player = player, lives_left = lives[key] })
  say("Back in the game", false)
end

on("game.start", show)

on("nfc.tag", function(e)
  if not e.valid then
    log("respawn: tag " .. tostring(e.uid) .. " refused: " .. tostring(e.reason))
    return say(refused[e.reason] or "Not a game tag", true)
  end
  respawn(e.team, e.player)
end)

on("team_input.press", function(e)
  respawn(e.team, nil)
end)
