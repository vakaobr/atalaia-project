-- SPDX-FileCopyrightText: 2026 The Atalaia contributors
-- SPDX-License-Identifier: GPL-3.0-or-later
--
-- Bomb / Rush (draft): attackers arm, defenders defuse before the fuse runs out.

local s = state.node { phase = "standby", fuse = 0 }

local function arm(team)
  s.phase, s.fuse = "armed", params.fuse_s
  audio.play("armed")
  emit("bomb.armed", { team = team, fuse_s = s.fuse }, { prio = "critical" })
end

on("team_input.hold", function(e)
  if s.phase == "standby" and e.team == params.attackers and e.ms >= params.arm_hold_ms then
    arm(e.team)
  elseif s.phase == "armed" and e.team == params.defenders and e.ms >= params.defuse_hold_ms then
    s.phase = params.reset_after_defuse and "standby" or "defused"
    audio.play("defused")
    emit("bomb.defused", { team = e.team }, { prio = "critical" })
  end
end)

if params.auto_arm_after_s then
  after(params.auto_arm_after_s, function()
    if s.phase == "standby" then arm(params.attackers) end
  end)
end

every(1, function()
  if s.phase ~= "armed" then return end
  s.fuse = s.fuse - 1
  ui.screen("countdown", { left = s.fuse })
  if s.fuse <= 0 then
    s.phase = "exploded"
    audio.play("explosion")
    emit("bomb.exploded", { team = params.attackers }, { prio = "critical" })
  end
end)
