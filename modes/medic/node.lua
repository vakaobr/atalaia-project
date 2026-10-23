-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Medic Kit (Ligaduras): a hit player scans their signed NFC tag
-- (protocol/nfc-tag.md), then holds a button for params.heal_hold_s seconds
-- to be healed; letting go early cancels the heal. The kit holds
-- params.charges heals and shows how many are left. A player gets at most
-- params.max_heals_per_player heals in the game (0: no limit), and waits
-- params.cooldown_s between two of them. With params.team the kit serves
-- that team only. Every refusal says why on the screen.
--
-- A role package (modes/README.md): in a field game the kit's node runs this
-- script alone, next to any main mode. The controller's field.lua counts the
-- heals of every kit and tells the kits ("heals" mode command), so a limit
-- holds across kits; a kit out of its reach goes on with its own count and
-- what it was told. The GM refills a kit from the console ("refill").

local HOLD_STEP_MS = 250 -- shells send team_input.hold this often (modes/README.md)
local SCAN_WINDOW_S = 15 -- after a scan, the hold must start within this time
local SHOW_S = 4 -- a result stays on the screen this long

local tag_refusals = {
  mac = "mac", -- forged: signed with another key
  game = "game", -- a tag from another game
  no_game = "no_game", -- this kit is not in a controller's game
  team = "team", -- a team this game does not have
}

-- Why a tag or a hold was refused, in the kit's language (params.lang).
local reasons = {
  pt = {
    mac = "Etiqueta falsificada",
    game = "Etiqueta de outro jogo",
    no_game = "Este kit não está num jogo",
    team = "Equipa desconhecida",
    not_tag = "Não é uma etiqueta do jogo",
    wrong_team = "Este kit é de outra equipa",
    limit = "Chegaste ao limite de tratamentos",
    cooldown = "Espera %d s",
    cancelled = "Largaste antes do tempo: lê a etiqueta outra vez",
    scan_first = "Lê primeiro a tua etiqueta",
  },
  en = {
    mac = "Forged tag",
    game = "Tag from another game",
    no_game = "This kit is not in a game",
    team = "Unknown team",
    not_tag = "Not a game tag",
    wrong_team = "This kit is for another team",
    limit = "You have had all your heals",
    cooldown = "Wait %d s",
    cancelled = "Let go too early: scan again",
    scan_first = "Scan your tag first",
  },
  -- German and Traditional Chinese (Taiwan): drafted by an AI model, not yet reviewed
  -- (docs/translations/status.yaml).
  de = {
    mac = "Gefälschter Tag",
    game = "Tag aus einem anderen Spiel",
    no_game = "Dieses Kit ist in keinem Spiel",
    team = "Unbekanntes Team",
    not_tag = "Kein Tag dieses Spiels",
    wrong_team = "Dieses Kit gehört einem anderen Team",
    limit = "Du hast alle Behandlungen gehabt",
    cooldown = "Warte %d s",
    cancelled = "Zu früh losgelassen: nochmal scannen",
    scan_first = "Scanne zuerst deinen Tag",
  },
  ["zh-tw"] = {
    mac = "偽造的標籤",
    game = "其他遊戲的標籤",
    no_game = "這個醫護包不在遊戲中",
    team = "未知隊伍",
    not_tag = "不是這場遊戲的標籤",
    wrong_team = "這是別隊的醫護包",
    limit = "你的治療次數已用完",
    cooldown = "請等 %d 秒",
    cancelled = "太早放開了：請再感應一次",
    scan_first = "請先感應你的標籤",
  },
}
local texts = reasons[params.lang] or reasons.pt

local s = state.node { charges = params.charges }
local used = {} -- player -> heals in this game: this kit's, and those it was told about
local last = {} -- player -> game time (s) of their last heal
local pending -- after a valid scan: { player, team, base } until the heal or a refusal
local window -- the timer that ends the scan's wait for a hold
local back -- the timer that brings the idle screen back

local function idle()
  if back then
    cancel(back)
    back = nil
  end
  if s.charges <= 0 then
    ui.screen("medic_empty", { team = params.team })
  else
    ui.screen("medic_idle", { remaining = s.charges, team = params.team })
  end
end

-- A result screen, then the idle screen again after SHOW_S.
local function show(name, data)
  if back then
    cancel(back)
  end
  ui.screen(name, data)
  back = after(SHOW_S, function()
    back = nil
    idle()
  end)
end

local function forget()
  pending = nil
  if window then
    cancel(window)
    window = nil
  end
end

local function refuse(reason, data)
  forget()
  data = data or {}
  data.reason = reason
  data.message = string.format(texts[reason], data.wait_s or 0)
  data.remaining = s.charges
  log("medic: refused (" .. reason .. ")" .. (data.player and (" for " .. data.player) or ""))
  show("medic_refused", data)
end

local function heals_of(player)
  return used[player] or 0
end

local function heal()
  local p = pending
  forget()
  s.charges = s.charges - 1
  used[p.player] = heals_of(p.player) + 1
  last[p.player] = game.time()
  audio.play("healed")
  emit("medic.heal", {
    team = p.team,
    player = p.player,
    remaining = s.charges,
    player_heals_used = used[p.player],
  })
  show("medic_healed", {
    player = p.player,
    team = p.team,
    remaining = s.charges,
    used = used[p.player],
    max = params.max_heals_per_player,
  })
  if s.charges <= 0 then
    emit("medic.empty", { team = params.team })
  end
end

local function hold_screen(progress)
  if back then
    cancel(back)
    back = nil
  end
  ui.screen("medic_hold", {
    player = pending.player,
    team = pending.team,
    progress = progress,
    left = math.max(0, math.ceil(params.heal_hold_s * (1 - progress))),
    remaining = s.charges,
  })
end

on("game.start", idle)

on("nfc.tag", function(e)
  if not e.valid then
    log("medic: tag " .. tostring(e.uid) .. " refused: " .. tostring(e.reason))
    -- unsigned, format and version: not a player tag of this system
    return refuse(tag_refusals[e.reason] or "not_tag")
  end
  local who = { player = e.player, team = e.team }
  if params.team and e.team ~= params.team then
    return refuse("wrong_team", who)
  end
  if s.charges <= 0 then
    forget()
    return idle()
  end
  local max = params.max_heals_per_player
  if max > 0 and heals_of(e.player) >= max then
    who.used, who.max = heals_of(e.player), max
    return refuse("limit", who)
  end
  local t = last[e.player]
  if params.cooldown_s > 0 and t and game.time() - t < params.cooldown_s then
    who.wait_s = math.ceil(params.cooldown_s - (game.time() - t))
    return refuse("cooldown", who)
  end
  forget()
  pending = { player = e.player, team = e.team }
  window = after(SCAN_WINDOW_S, function()
    window = nil
    pending = nil
    idle()
  end)
  hold_screen(0)
end)

-- A press after the scan starts the hold from zero; a button already held
-- when the tag was read counts from its first hold step after the scan.
on("team_input.press", function()
  if pending then
    pending.base = 0
  end
end)

on("team_input.hold", function(e)
  if not pending then
    if s.charges > 0 and back == nil then
      refuse("scan_first")
    end
    return
  end
  if window then
    cancel(window)
    window = nil
  end
  if pending.base == nil then
    pending.base = math.max(0, e.ms - HOLD_STEP_MS)
  end
  local progress = (e.ms - pending.base) / (params.heal_hold_s * 1000)
  if progress >= 1 then
    heal()
  else
    hold_screen(progress)
  end
end)

on("team_input.release", function()
  if pending and pending.base ~= nil then
    refuse("cancelled", { player = pending.player, team = pending.team })
  end
end)

-- Mode commands (CMD opcode 8): the controller's count of a player's heals
-- at every kit, and the GM's refill.
on("cmd.mode", function(e)
  if e.name == "heals" and type(e.player) == "string" then
    local n = math.tointeger(e.used) or 0
    if n > heals_of(e.player) then
      used[e.player] = n
    end
    if type(e.at) == "number" and (last[e.player] == nil or e.at > last[e.player]) then
      last[e.player] = e.at
    end
  elseif e.name == "refill" then
    s.charges = params.charges
    log("medic: refilled to " .. s.charges)
    forget()
    idle()
  end
end)
