-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Bomb / Rush: attackers arm, defenders defuse before the fuse runs out.

local s = state.node { phase = "standby", explode_at = 0 }
local fuse_timer

-- The prop's screen follows the phase: standby, countdown, defused, exploded.
local function show_countdown()
  ui.screen("countdown", { left = math.ceil(s.explode_at - game.time()) })
end

local function show_standby()
  ui.screen("standby", { arm = params.attackers })
end

local function explode()
  s.phase = "exploded"
  audio.play("explosion")
  ui.screen("exploded", { team = params.attackers })
  emit("bomb.exploded", { team = params.attackers }, { prio = "critical" })
end

local function arm(team)
  s.phase = "armed"
  s.explode_at = game.time() + params.fuse_s
  -- The explosion is its own timer, so it lands exactly on time no matter
  -- when the bomb was armed relative to the display tick below.
  fuse_timer = after(params.fuse_s, explode)
  audio.play("armed")
  show_countdown()
  emit("bomb.armed", { team = team, fuse_s = params.fuse_s }, { prio = "critical" })
end

on("game.start", show_standby)

on("team_input.hold", function(e)
  if s.phase == "standby" and e.team == params.attackers and e.ms >= params.arm_hold_ms then
    arm(e.team)
  elseif s.phase == "armed" and e.team == params.defenders and e.ms >= params.defuse_hold_ms then
    cancel(fuse_timer)
    audio.play("defused")
    if params.reset_after_defuse then
      s.phase = "standby"
      show_standby()
    else
      s.phase = "defused"
      ui.screen("defused", { team = e.team })
    end
    emit("bomb.defused", { team = e.team }, { prio = "critical" })
  end
end)

if params.auto_arm_after_s then
  after(params.auto_arm_after_s, function()
    if s.phase == "standby" then
      arm(params.attackers)
    end
  end)
end

every(1, function()
  if s.phase == "armed" then
    show_countdown()
  end
end)
