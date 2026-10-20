-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Objectives (org.atalaia.objectives), the nodes of a custom scenario
-- (decision P4R7). A node does nothing of its own: it waits for the mode
-- command "setup" from the scenario's field.lua on the controller, which says
-- what the node is for, and reports what happens with the standard events. It
-- never scores: the scenario decides when an objective is completed or failed.
--
-- setup (every field optional but kind; at most 127 bytes of JSON):
--   kind      capture, code, tags, bomb; off (inactive, a hidden objective);
--             done (completed: team, the team that completed it, if one);
--             failed
--   team      capture, code, tags: the only team that may do it (code: the
--             team credited); bomb: the attackers, who arm (any other team
--             defuses). Empty: every team.
--   label     the objective's short name, in the scenario's language
--   lang      pt (the default) or en: the screen's texts
--   hold_ms   capture and arm: how long a team holds its input (3000)
--   defuse_ms bomb: how long a team holds to defuse (hold_ms)
--   code      code: the digits to type, then #
--   count     tags: how many tags a team scans (1): players' own tags, or with
--             any, any cards (intel), for team or the last team to press
--   any       tags: true for any card, not only players' tags
--   fuse_s    bomb: the fuse (60)
--   holder    capture: the team holding the node (after a reboot)
--   have      tags: the tags of team already counted (after a reboot)
--   armed     bomb: the team that armed it (after a reboot), with left, the
--             seconds left on the fuse; the bomb goes on without a new event
--
-- Reports: zone.captured / zone.neutralized (capture, and the GM's owner
-- override), code.used (code: no code in the event, only the team), tag.scanned
-- (tags: tag, the card's uid; owner, the player; team), bomb.armed / bomb.defused /
-- bomb.exploded (bomb). A script does not know its role (decision M5-5): the
-- setup's kind is what the node does, so one script serves both roles.

local cfg = {} -- the last setup
local holder -- capture: the team holding the node
local typed, note = "", nil -- code: the digits typed; the bottom line (wrong, ok, ...)
local got, seen = {}, {} -- tags: team -> tags counted; uid -> true
local phase, by, explode_at, fuse -- bomb: standby, armed, defused, exploded
local last_team -- the last team to press its input (code: the team credited)

local function int(v, lo, hi, default)
  v = math.tointeger(v)
  if v == nil or v < lo or v > hi then
    return default
  end
  return v
end

local function show()
  local k = cfg.kind
  local d = { lang = cfg.lang, label = cfg.label }
  if k == "capture" then
    d.team, d.only, d.hold_ms = holder, cfg.team, cfg.hold_ms
    ui.screen("obj_capture", d)
  elseif k == "code" then
    d.team, d.digits, d.note = cfg.team or last_team, #typed, note
    ui.screen("obj_code", d)
  elseif k == "tags" then
    local team = cfg.team or cfg.last
    d.team, d.have, d.count, d.note, d.any = team, team and got[team] or 0, cfg.count, note, cfg.any
    ui.screen("obj_tags", d)
  elseif k == "bomb" then
    d.phase, d.team, d.attackers, d.fuse_s = phase, by, cfg.team, cfg.fuse_s
    d.left = phase == "armed" and math.max(0, math.ceil(explode_at - game.time())) or 0
    ui.screen("obj_bomb", d)
  else
    d.state, d.team = k or "wait", k == "done" and cfg.team or nil -- wait, off, done, failed
    ui.screen("obj_status", d)
  end
end

local function may(team)
  return cfg.team == nil or team == cfg.team
end

-- Capture.

local function take(team, squad)
  emit("zone.captured", { team = team, squad = squad, previous_team = holder })
  holder = team
  cap("team_display"):show(team)
  audio.play("captured")
  show()
end

-- Bomb site.

local function arm(team, left, quiet)
  phase, by, explode_at = "armed", team, game.time() + left
  fuse = after(left, function()
    fuse, phase = nil, "exploded"
    audio.play("explosion")
    emit("bomb.exploded", { team = by })
    show()
  end)
  if not quiet then
    audio.play("armed")
    emit("bomb.armed", { team = team, fuse_s = left })
  end
  show()
end

local function defuse(team)
  cancel(fuse)
  fuse, phase, by = nil, "defused", team
  audio.play("defused")
  emit("bomb.defused", { team = team })
  show()
end

on("game.start", show)

on("cmd.mode", function(e)
  if e.name ~= "setup" then
    return
  end
  if fuse then
    cancel(fuse)
  end
  local hold = int(e.hold_ms, 0, 600000, 3000)
  cfg = {
    kind = e.kind,
    team = e.team ~= "" and e.team or nil,
    label = e.label,
    lang = e.lang,
    hold_ms = hold,
    defuse_ms = int(e.defuse_ms, 0, 600000, hold),
    code = type(e.code) == "string" and e.code or nil,
    count = int(e.count, 1, 100, 1),
    any = e.any == true,
    fuse_s = int(e.fuse_s, 10, 3600, 60),
  }
  holder, typed, note, got, seen = e.holder ~= "" and e.holder or nil, "", nil, {}, {}
  phase, by, fuse = "standby", nil, nil
  if cfg.kind == "tags" and cfg.team then
    got[cfg.team] = int(e.have, 0, 100, 0)
  end
  if holder then
    cap("team_display"):show(holder)
  end
  if cfg.kind == "bomb" and type(e.armed) == "string" then
    return arm(e.armed, int(e.left, 1, 3600, cfg.fuse_s), true)
  end
  show()
end)

on("team_input.press", function(e)
  last_team = e.team
end)

on("team_input.hold", function(e)
  local k = cfg.kind
  if k == "capture" then
    if e.team ~= holder and e.ms >= cfg.hold_ms and may(e.team) then
      take(e.team, e.squad)
    end
  elseif k == "bomb" then
    if phase == "standby" and e.ms >= cfg.hold_ms and may(e.team) then
      arm(e.team, cfg.fuse_s)
    elseif phase == "armed" and e.team ~= by and e.ms >= cfg.defuse_ms then
      defuse(e.team)
    end
  end
end)

-- The GM's owner override (the console's Boxes tab), for a capture only.
on("cmd.set_owner", function(e)
  if cfg.kind ~= "capture" then
    return
  end
  local team = e.team
  if team == "" or team == "none" then
    team = nil
  end
  if team == holder then
    return
  end
  if team then
    return take(team)
  end
  emit("zone.neutralized", { previous_team = holder })
  holder = nil
  cap("team_display"):show("none")
  show()
end)

-- Code: digits, then #; * clears. A wrong code is only on the screen.
on("keypad.key", function(e)
  if cfg.kind ~= "code" or note == "ok" then
    return
  end
  local k = e.key
  if k == "#" then
    if cfg.code and typed == cfg.code then
      note = "ok"
      emit("code.used", { team = cfg.team or last_team })
      audio.play("captured")
    else
      note = "wrong"
    end
    typed = ""
  elseif k == "*" then
    typed, note = "", nil
  elseif string.match(k or "", "^%d$") and #typed < 8 then
    typed, note = typed .. k, nil
  end
  show()
end)

-- Tags: each player of a team scans their own tag once; with any, any card
-- (intel cards) counts once, for the team at the box.
on("nfc.tag", function(e)
  if cfg.kind ~= "tags" then
    return
  end
  local team = e.team
  if cfg.any then
    team = cfg.team or last_team
  end
  if not cfg.any and not e.valid then
    note = "not_tag"
  elseif team == nil then
    note = "team_first"
  elseif not may(team) then
    note = "wrong_team"
  else
    cfg.last = team
    local n = got[team] or 0
    if seen[e.uid] or n >= cfg.count then
      note = "again"
    else
      seen[e.uid], got[team], note = true, n + 1, nil
      emit("tag.scanned", { team = team, tag = e.uid, owner = e.valid and e.player or nil })
    end
  end
  show()
end)

every(1, function()
  if cfg.kind == "bomb" and phase == "armed" then
    show()
  end
end)

on("game.end", function()
  ui.screen("final_score", { owner = holder })
end)
