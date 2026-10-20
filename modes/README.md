# Game modes

Each mode is a folder with a manifest and one or two Lua scripts:

```
<mode>/
  mode.yaml     id, version, licence, kind, minimum device tier, roles, parameters, GM commands, translations
  node.lua      runs on each prop with the mode's role
  field.lua     optional: runs on the field controller for logic across props
  assets/       optional: sound clips, screen templates (assets/screens/<name>.yaml)
  tests/        event sequences with expected results
```

The GM console builds its settings form from `params` in `mode.yaml`, so GMs never edit Lua.

| Mode | Kind | Runs on | Status |
| --- | --- | --- | --- |
| [Domination](domination/) | main mode | boxes | Runs in the simulator and on the Field Box; its screens are YAML templates since phase 3; 6 tests |
| [Bomb / Rush](bomb/) | main mode | boxes | Runs in the simulator and on the Field Box; per-team keypad codes since the mode pack; its screens are YAML templates since phase 3; 10 tests |
| [Hold-All Domination](holdall/) | main mode | boxes + controller (`field.lua`) | Mode pack (phase 2); 5 tests, plus simulator, controller and host-box tests |
| [Last Stand](laststand/) | main mode | boxes + controller (`field.lua`) | Mode pack (phase 2); 5 tests, plus simulator and controller tests |
| [Codes](codes/) | modifier | boxes, alongside any main mode | Mode pack (phase 2); 3 tests (alone, with Domination, with Bomb's team codes), plus simulator and host-box tests |
| [Kill Confirmed](kill_confirmed/) | main mode | boxes and Android props with NFC | Phase 3; 2 tests, plus host-box tests with signed tags |
| [Respawn and Lives](respawn/) | main mode | boxes and Android props with NFC (or team buttons) | Phase 3; 3 tests |
| [Player Check-in](player_checkin/) | main mode | boxes and Android props with NFC | Phase 3; 2 tests |
| [Medic Kit](medic/) (Ligaduras) | role package | its own boxes and Android props with NFC, next to any main mode; controller (`field.lua`) | After phase 3 plan phase E; 7 tests, plus simulator, controller, host-box, browser and on-device tests |
| [Master and Satellites](master_satellites/) (Mestre e Satélites) | main mode | boxes + controller (`field.lua`) | Phase 4 plan phase 1, in software (not yet on radio hardware); 8 tests, plus controller, host-box and Field Box preset tests |
| [Target Windows](target_windows/) (Janelas de Alvo) | main mode | boxes with the target addon (`hit`, `led`) | Phase 4 plan phase 2: the logic, in software; the addon does not exist yet (HW2), so it is not a Field Box preset and no Android prop offers it; 7 tests |
| [Hacking Terminal](hacking_terminal/) (Terminal de Hacking) | main mode | boxes and Android props with a keypad | Phase 4 plan phase 4, in software (not yet on a phone in the field: HW3); 13 tests, plus controller, host-box, Field Box preset, browser and Dart tests |

The script API is described in the "Game runtime and scripting" section of the [design specification](../docs/design-spec.md), and implemented in [`core/src/script_api.c`](../core/src/script_api.c).

Standard events, their data fields and their default priorities are listed in [`protocol/schema/events.yaml`](../protocol/schema/events.yaml); `emit()` uses that priority unless you pass `{ prio = ... }`. `team` and `squad` may go in any event's data. A mode's own events are named `x.<club>.<name>` and can carry any data. Tests fail if a mode emits anything else, or an event too large for a LoRa packet (200 bytes, see [protocol/README.md](../protocol/README.md#events-on-lora)).

## The mode pack (phase 2)

Ideas from public community requests (design specification sections 2 and 15); the rules and texts are our own.

- **Hold-All Domination** (`org.atalaia.holdall`): boxes are captured as in Domination, but they do not score. The controller's `field.lua` scores a team only while it holds every zone box (`points_per_tick` every `tick_s` seconds, the first tick one full `tick_s` after the last box fell), and only with at least `min_zones` boxes in play. Events: `holdall.scoring_start` and `holdall.scoring_stop` (from the controller).
- **Last Stand** (`org.atalaia.laststand`): the `defenders` hold every zone when the game starts. Once their defence is set up, a countdown of `countdown_s` runs while they hold `last_zones` zones or fewer (default: 1 of N); retaking a zone stops it, and it starts over (`reset`, the default) or carries on where it stopped. When it runs out, `laststand.defeated` is logged and, with `end_game`, the game ends with the `attackers` as winners. Events: `laststand.countdown_start` and `laststand.countdown_cancel` (with `duration_s`), `laststand.defeated`.
- **Bomb team codes**: with `team_codes` (`red=1234,blue=5678`) the keypad arms and defuses instead of the team buttons. In standby a team's code arms the bomb for that team; once armed, another team's code defuses it. `bomb.armed` and `bomb.defused` then carry the team and `reason: code`. Without `team_codes` the bomb behaves exactly as before.
- **Codes** (`org.atalaia.codes`, a modifier): `codes` lists keypad codes as `digits:kind[:points][:team]`, comma-separated, where kind is `points`, `hint` or `unlock` (`4711:points:50,0815:hint,2222:unlock:red`). Type the digits, then `#`; `*` clears. Each code works once per game on each box. `code.used` tells the GM which code (its place in the list), what it gave, the team it counted for (the code's team, else the team holding the box) and the team holding the box (`holder`). A points code with no team and no holder is refused.

On a box without a controller (picked from the box's own preset list), Hold-All and Last Stand boxes only capture: their scoring and countdown live in `field.lua`.

## Master and Satellites (phase 4)

Design specification section 15; decisions P4R2, P4R3 and M1-1 to M1-5 in `docs/review/decisions-to-review.md`.

- **The boxes:** one box joined with the role `master`, any number with the role `satellite`. Both run the same `node.lua`: a team captures a box by holding its input for `capture_hold_ms`, as in Domination, and boxes do not score. Satellites report their captures with the standard `zone.captured` and `zone.neutralized` (no events of their own).
- **Scoring:** the controller's `field.lua` scores the master's holder every `tick_s` seconds (the first points one full tick after the capture): `points_per_tick` (default 2), plus `satellite_bonus_pct` % of it (default 50) for every satellite the same team holds, rounded down, because points are whole numbers (`score.add` takes integers). With the defaults that is 2, 3, 4 and 5 points a tick with 0 to 3 satellites. While the holder has fewer than `min_satellites` satellites (default 0) the master scores nothing. Nobody scores while nobody holds the master; a satellite alone never scores.
- **The master changes hands:** when the master leaves a team's hands (another team captures it, or the GM sets it to another team or to none), `field.lua` frees every satellite (`field.send(id, "set_owner", { team = "none" })`), each of them logs `zone.neutralized`, and the new holder starts without a bonus. The first capture of a free master frees nothing. A satellite that rebooted is freed at the next change of the master, as on the field. With more than one master box, only the first (the lowest node id) counts.
- **Screens:** `standby` (nobody holds the box), `captured` (a satellite: the team and since when) and `master_status` (the master: the team, its satellites of all of them, and its points per tick, red at 0), which the master shows when `field.lua` tells it (the mode command `status`, sent only when something on it changes). `final_score` is the Field Box's built-in screen, as for Hold-All.
- **The GM** sees the master's holder and the satellites held in the console's field state (`master`, `held`), and every capture and freed satellite in the log.

On a box without a controller (picked from the box's own preset list), Master and Satellites boxes only capture. It is the tenth built-in preset, on the second page of the box's keypad picker (`0` turns the page, decision M2-1).

## Target Windows (phase 4)

Design specification section 15; decisions P4R4, P4R26 and M2-2 to M2-5 in `docs/review/decisions-to-review.md`.

- **The target:** a box with the target addon (a plate with a hit sensor and an LED ring), the role `target`, which requires the capabilities `hit` and `led`. It is armed (`cap("hit"):arm()`) when the game starts and disarmed when it ends; a hit reaches the script as `hit.hit` with `strength` 0-255.
- **Windows:** the target stays dark for `interval_s` seconds (default 20), then lights up (`cap("ring"):fill(team)`) in a random team's colour for `window_s` seconds (default 5). The team is one of `game.teams()`, picked with the game's seeded `rand()`, so a replay picks the same teams. The next window opens `interval_s` after the last one closed.
- **Hits:** a hit of at least `min_strength` (default 40) while the window is open scores `hit_points` (default 5) for the window's team, on the target, and logs `target.hit` with that team and `window_open: true`; the first such hit closes the window unless `multi_hit`, which lets every hit in the window score. A hit while the target is dark scores nothing and logs `target.hit` with `window_open: false`, so the GM sees it. Weaker hits are ignored. The GM's owner override (`cmd.set_owner`) means nothing to a target and is ignored.
- **Screens:** `standby` while the target is dark (the team of the last scoring hit, and how many there were), `window` while it is open (the team's colour and the seconds left); `final_score` is the Field Box's built-in screen.

The addon and its driver are hardware work (phase 4 HW2): until they exist this mode runs in the simulator (the tests' `input` step gives `hit.hit`) and through the core in the app's tests, and is not a Field Box built-in preset (decision P4R23).

## Hacking Terminal (phase 4)

Design specification section 15; decisions P4R1, P4R5, P4R23 and M4-1 to M4-9 in `docs/review/decisions-to-review.md`.

- **The terminal:** a box or an Android prop with a keypad (the role `terminal` requires `keypad`; the team buttons, a team display, a screen and sound are optional). On an Android prop the on-screen keypad is shown from the start. It sets one puzzle, `puzzle`, of length `digits` (3-6, default 4):
  - `code` (the default): a code of `digits` different digits. Type a guess and `#` (`*` clears); the terminal shows how many digits are in the right place and how many are in the code but elsewhere, for the last three guesses.
  - `wires`: `digits` numbered wires to cut in the right order: press a wire's number.
  - `sequence`: any key shows a sequence of `digits` keys (1-9), one a second; then type it back (`*` shows it again).
  An unknown `puzzle` plays the code.
- **Wrong answers** (a wrong guess, a wrong wire, a wrong key) lock the terminal for `lockout_s` seconds (default 10; 0: no lock), with the seconds left on the screen; the wires are joined again and the sequence must be watched again, but the puzzle stays the same. Wrong answers are not events: the screen shows them.
- **Seeded:** every puzzle comes from the scripts' `rand()`, seeded with the game's seed and the node's id, so a replay of the game sets the same puzzles and every terminal has its own. The controller gives every game a seed; a Field Box gives every game picked on the box a new one.
- **The solving team** is the team that pressed its button last (`team_input.press`) since the last solve, or else the terminal's `team` parameter; with neither, nobody known solves it.
- **Solving** emits `hacking.solved` (47, critical) with `puzzle` (36), the code it reveals (`reveal_code`, as `code`, 10) and the team, scores `points` (default 10) for the team, and shows `ACESSO CONCEDIDO` / `ACCESS GRANTED` with the team and the code. Without `capture` the terminal then stays solved; with `capture` the terminal becomes the team's zone (`zone.captured`, the team display), and after 10 s of the solved screen it sets a new puzzle for the other teams, which its holder cannot solve (the screen says so). The GM's owner override applies with `capture` only, and the box's command "New puzzle" (`reset`) sets a new puzzle at once, unlocked and unsolved.
- **Screens** (`lang`: `pt`, the default, or `en`; the texts are in the templates): `hack_code`, `hack_wires`, `hack_sequence`, `hack_solved`; `final_score` at the end. The GM console's feed says who solved which puzzle and the code it revealed; the players' feed says only who hacked a terminal.

It is the eleventh built-in Field Box preset, the second entry of the picker's second page. On a box picked from its own preset list it needs no controller.

## Phase 3 modes (player tags)

These modes identify players by their **player tag**: an NFC tag signed with the game key ([protocol/nfc-tag.md](../protocol/nfc-tag.md)). The box checks the tag before the script sees it and gives the script `nfc.tag` with `valid`, and `player` and `team` (or the `reason` it was refused). In a game a box picked from its own preset list there is no game key, so tags are refused there (`no_game`); these modes are for games run by a field controller. Each box counts on its own: no state is shared between boxes.

- **Kill Confirmed** (`org.atalaia.kill_confirmed`): players drop their tag when hit. A team presses its button at the station and scans the tags it collected within `turn_in_s` seconds (each tag that counts keeps the station open). An enemy's tag confirms the kill: `kill.confirmed`, `confirm_points` for the team and `penalty_points` off the tag's team (`score.delta`). A teammate's tag denies it: `kill.denied`, no points. The same player's tag counts again only after `retag_after_s` seconds. The penalty is local to the box: a box reports only the points a team gained to the controller (decision E6), so the controller's totals do not subtract it, although the console lists the `score.delta` event.
- **Respawn and Lives** (`org.atalaia.respawn`): a respawn point counts lives, per team (default) or per player (`per_player`). A player scans their tag to come back in (`player.respawn` with `lives_left`) and waits `respawn_cooldown_s` before the next respawn. Without tags, a team's button press is a respawn for that team (with a 2 s guard against double presses). A team with no lives left is refused and reported once: `team.eliminated`.
- **Player Check-in** (`org.atalaia.player_checkin`): players check in at a checkpoint with their tag (`player.checkin`); the screen shows the count per team, and the team gets `points` per check-in. A player counts once per game, or again after `repeat_after_s` seconds; a scan before that is a duplicate and is refused.

Money Factory (also phase 3, ADR-P3-8) comes in a later plan phase: its events (`money.collected`, `money.deposited`) are in the schema already.

## The Medic Kit (Ligaduras)

Requested by the maintainer (decisions MK1-MK8 and MK9 on in `docs/review/decisions-to-review.md`). A **role package** (`org.atalaia.medic`, below): its `medic` boxes or phones stand next to any main mode, and a node given that role runs only the kit.

- **A heal:** a hit player scans their player tag (required: decision MK1), then holds a button for `heal_hold_s` seconds (default 10), as when arming the Bomb. Any team button counts: the tag says who the player is. Letting go early cancels: the player scans again. The screen fills up while the button is held, then shows the player back in the game and the heals left.
- **Limits:** the kit holds `charges` heals (default 5) and shows how many are left; at 0 it is empty (`medic.empty`) and refuses everyone until the GM refills it from the console (the *Boxes* tab's command, `refill`). A player gets at most `max_heals_per_player` heals in the game (default 2; 0 for no limit), at every kit, and waits `cooldown_s` between two (default 0). With `team` the kit serves that team only; empty, every team.
- **Refusals say why on the screen:** a forged tag, a tag from another game, a card that is not a player tag, a team the game lacks, a player of a team the kit does not serve, a player at the limit, still in the cooldown (with the seconds left), a hold without a scan, letting go early. Nothing is sent to the controller for a refusal.
- **Across kits:** each heal is `medic.heal` (`team`, `player`, `remaining`, `player_heals_used`). The kit's `field.lua` on the controller counts every player's heals for the whole game and tells the other kits (the mode command `heals`, below), so a limit of 2 holds across kits. A kit out of the controller's reach goes on with what it knows (its own heals, and what it was told): a player may get one heal too many there, and when the kit's events arrive the controller's count is the larger of the two. A kit that rebooted is told every count again. The kit's own charges do not survive a reboot (no mode's script state does yet).
- **Language:** `lang` (`pt`, the default, or `en`) picks the kit's screens; the texts are in the templates and the refusals in the script. The Field Box's fonts have no accented letters, so it draws "Le a tua etiqueta" for "Lê a tua etiqueta" (the app draws every character).
- **Screens:** `medic_idle` ("Lê a tua etiqueta", "Restam N ligaduras"), `medic_hold` ("Mantém premido para tratar", a filling bar, the seconds left), `medic_healed`, `medic_refused` (the reason), `medic_empty`.

## Main modes, modifiers and role packages

`kind: modifier` marks a package that runs alongside a main mode on the same node. `kind: role` marks a **role package**: it brings roles of its own to any game, and a node given one of them runs that package alone (a medic kit next to Domination's zone boxes runs no capture rules). A game and a preset name a main mode and its other parts with one id joined by `+`, main mode first:

```
org.atalaia.domination+org.atalaia.codes+org.atalaia.medic
```

The scripts are composed into one Lua chunk, the main mode's first, each in its own block, so their locals stay apart and their handlers for the same event run in that order:

```
do
<main node.lua>
end
do
<modifier node.lua>
end
```

The simulator (`atalaia_sim.mode.compose`), the field controller and the Field Box (`firmware/esp32/main/box_game.c`, from its stored presets) build the same chunk; `field.lua` scripts compose the same way. The parameters of the parts are merged into one schema, so their names must differ; the whole id is at most 63 bytes. A modifier on its own is a valid game too: Codes alone makes the box a code terminal.

Role packages are composed by role, not into the chunk:

- The game's roles are the main mode's and the role packages' (names must differ; a modifier adds none). The game form of the GM console lists role packages apart from the modifiers.
- A node with a main mode's role runs the main mode and the modifiers, as above. A node with a role package's role runs that package's `node.lua` alone, with that package's parameters only.
- The controller makes each box's join with **what that box runs**: a kit's join payload names `org.atalaia.medic` and carries the kit's parameters, a zone box's names `org.atalaia.domination+org.atalaia.codes` and the zone's parameters ([protocol/join.md](../protocol/join.md)). So the Field Box and the Android prop compose exactly as before and need not know the kinds; a standby controller's join names the whole game.
- `field.lua` scripts of every part run together on the controller, in the id's order, and see every node's events.
- A role package on its own is a valid game (a field of medic kits only); it cannot lead other parts.

Scripts on one box that read keypad codes share them through the global table `keypad_codes`: each adds a function that says whether a code is its own, so a code meant for one script is not reported as wrong by the other (Bomb's team codes and Codes do this).

While its prompt is up, Codes keeps the screen: it wraps `ui.screen`, holds the main mode's screens and shows the newest one when the prompt closes.

### Mode commands

A manifest may declare commands that the GM console offers for nodes of some roles:

```yaml
commands:
  refill: { roles: [medic], label: "Refill the kit" }
i18n:
  pt:
    commands:
      refill: Repor as ligaduras
```

The console shows a button per command on each box of those roles (the *Boxes* tab); the controller sends it as a **mode command**, CMD opcode 8 with the command's name in its params (`{"name": "refill"}`, RFC 0001 Amendment 5), and refuses names the game does not declare, or a box of another role. A `field.lua` sends mode commands of its own with `field.send(node, "mode", { name = "heals", ... })` (names: 1-24 of `a-z`, `0-9` and `_`, starting with a letter; they need no declaration). Either way the node's script gets `cmd.mode` with the params, the name included, and checks `e.name`.

## Translations

`mode.yaml` may carry translated display strings. English is the manifest's own text; other languages go under `i18n` (European Portuguese for every built-in mode), and the GM console shows them in its language:

```yaml
i18n:
  pt:
    name: Domínio Total
    description: ...
    params:
      tick_s: Segundos por ponto enquanto uma equipa tem todas as caixas
```

String parameters may set `max` (bytes). A game's parameters travel to the boxes in the join payload, whose parameter JSON is at most 200 bytes.

## Inputs from the hardware

Modes react to semantic capabilities, so the same script works on a box with team buttons, a keypad or a touchscreen. The platform shell turns hardware into these events:

| Event | Data | When |
| --- | --- | --- |
| `team_input.press` | `team`, optional `squad` | A team presses its input (on the Field Box, when a team button goes down) |
| `team_input.hold` | `team`, `ms`, optional `squad` | Every 250 ms while a team holds its input; `ms` is the time held so far |
| `team_input.release` | `team`, `ms`, optional `squad` | The team lets go |
| `keypad.key` | `key` (`0`-`9`, `*`, `#`) | A keypad key is pressed |
| `hit.hit` | `strength` (0-255) | A hit sensor (the target addon's plate) is hit while armed (`cap("hit"):arm()`; draft RFC 0000 Amendment 1) |
| `nfc.tag` | `uid`, `valid`, then `player` and `team` (valid) or `reason` | A tag is read, checked against the game's key first ([nfc-tag.md](../protocol/nfc-tag.md)): `reason` is `unsigned`, `no_game`, `format`, `version`, `game`, `mac` or `team` |
| `cmd.set_owner` | `team` (or `none`) | The GM's owner override from the console (decision E7); Hold-All and Last Stand handle it |
| `cmd.mode` | `name`, then the command's own params | A mode command from the GM (a manifest's `commands`) or the field script (CMD opcode 8); the Medic Kit's `refill` and `heals` |
| `gm.message` | `text` | A message from the GM |

## Positions and zones

`geo.distance(lat1, lon1, lat2, lon2)` gives the distance in metres between two points (haversine on a sphere of 6,371 km: within 0.5 % of the ellipsoid, far closer than a phone's GPS at game distances), and `geo.in_zone(lat, lon, zone)` says whether a point is in a zone, for node and field scripts alike (ADR-P4-9):

```lua
local extraction = { type = "circle", lat = 38.7223, lon = -9.1393, radius_m = 15 }
local compound = { type = "polygon", points = { {38.7220, -9.1400}, {38.7220, -9.1390},
                                                {38.7226, -9.1390}, {38.7226, -9.1400} } }
if geo.in_zone(lat, lon, extraction) then ... end
```

- Coordinates are WGS 84 degrees, latitude from -90 to 90 and longitude from -180 to 180; anything else (a string, NaN, a missing value) is a script error (`script.error`), as is a zone without a known `type`, a negative `radius_m` or a polygon with fewer than 3 or more than 32 points.
- A point on a circle's edge, on a polygon's edge or on a vertex is inside (decision M3-2). Polygons are tested in plain latitude and longitude, so keep them simple (not self-intersecting) and off the 180th meridian; circles work anywhere.
- The results are the same to the last bit on the Field Box, the controller and a phone, so a game replays the same everywhere (decision M3-1). Lua's own `math.sin` and friends come from each platform's C library and may differ in the last bit: use `geo` for positions.
- Where positions come from: a VIP's phone through the controller (`position.fix`, for `field.lua` only) and a payload prop's own GPS (`gps.fix`), both in plan phase 5; positions are never events (P4R6).

## Tests

Every mode ships tests in `tests/*.yaml`, and CI runs them in the [simulator](../simulator/) on every change. A test sets up a game and runs its steps in order:

```yaml
name: Attackers arm the bomb and it explodes when the fuse runs out
params: { fuse_s: 60 }        # optional: overrides of the mode.yaml defaults
teams: [red, blue]            # optional: this is the default
nodes: { bomb: bomb }         # optional: node name -> role; default is one node per the first role
seed: 1                       # optional: seeds rand()
steps:
  - hold: { team: red, s: 5 }
  - expect: { type: bomb.armed, team: red, at: 5 }
  - wait: 59
  - expect_no: bomb.exploded
  - wait: 1
  - expect: { type: bomb.exploded, at: 65 }
```

The game starts automatically at time 0 (`autostart: false` turns that off). Only `wait` and `hold` move time forward. A modifier's test may name a main mode to run with (`main: domination`, a sibling folder), and a main mode's test its modifiers (`modifiers: [codes]`).

When the mode has a `field.lua`, it runs as the controller runs it: it receives every node's events (with `node` and `team` in the data), `field.owner()` is the team of each node's last `zone.captured` (as box STATE reports it), `field.send(node, "set_owner", "message" or "mode", params)` reaches the node as `cmd.set_owner`, `gm.message` or `cmd.mode`, its own events are logged from node `controller`, its points count in the field total, and a `game.win()` or `game.finish()` ends the game on every node. Time then moves in steps of 100 ms.

| Step | Example | What it does |
| --- | --- | --- |
| `wait` | `wait: 30` | Lets 30 seconds of game time pass |
| `hold` | `hold: { team: red, s: 5 }` | A team holds the input for 5 s and lets go; time passes |
| `press` | `press: { team: blue }` | A team presses the input |
| `keys` | `keys: "4711#"` or `keys: { node: a, keys: "12#" }` | Keypad presses, one `keypad.key` per character |
| `scan` | `scan: { player: b1, team: blue }` | A player tag read: signed with the test game's key and checked by the core as on a box. `forged: true` signs it with another key, `game: 7` writes it for another game, `scan: { uid: "04deadbeef" }` is a card without a player tag |
| `input` | `input: { type: nfc.tag, data: { uid: "04a1" } }` | Any event to a node |
| `start`, `end`, `pause`, `resume` | `end: time` | Game events from the controller to every node |
| `expect` | `expect: { type: zone.captured, team: red, at: 3, data: { previous_team: blue } }` | The next matching event exists; later `expect`s search after it |
| `expect_no` | `expect_no: bomb.exploded` | No matching event since the last `expect` |
| `expect_score` | `expect_score: { team: red, points: 6 }` | Field total, or one node's with `node:` (`node: controller` for the field script's) |
| `expect_screen` | `expect_screen: { template: countdown, data: { left: 1 } }` | The last screen a node showed |
| `expect_status` | `expect_status: ended` | `running`, `ended` or `halted` |

Steps that target a node take `node:`, which can be left out when the game has one node. In `expect`, a plain string matches the event type only; `data` matches a subset of the event's data; `node: controller` matches the controller's events (game lifecycle and the field script's). Events at the same game time keep the order in which they happened.

## Screens

`ui.screen(name, data)` shows one of the mode's screens. A mode ships its screens as YAML templates in `assets/screens/<name>.yaml` (ADR-P3-4); the Field Box draws them with LVGL and the Android app draws the same files with Flutter (`app/lib/ui/template/`, the same parser and expressions ported to Dart and checked against the core's). A name without a template falls back to the Field Box's built-in screens (`code_entry`, used by Codes and Bomb's team codes, and the older C versions of the screens below), so Hold-All, Last Stand and Codes keep their C screens for now; the app has `code_entry` and `final_score` as templates of its own (`app/lib/prop/shell_screens.dart`).

```yaml
template: countdown              # the file's name
style: { background: panel }     # optional: the screen's background
layout:
  - type: row
    style: { width: fill, height: 44, background: danger }
    children:
      - type: label
        text: ARMED
        style: { font_size: 20, width: fill, align: center }
  - type: label
    text: "{left|clock}"
    style: { font_size: 48, color: "{left <= 10 && 'danger' || 'white'}" }
  - type: progress_bar
    value: "{left / params.fuse_s}"
    style: { width: 240, height: 10, color: team }
```

| Widget | Property | |
| --- | --- | --- |
| `label` | `text` | text with `{expressions}` |
| `progress_bar` | `value` | 0-1, a number or `{expression}` |
| `icon` | `icon` | `ok`, `close`, `warning`, `pause`, `play`, `stop`, `bell`, `home`, `refresh`, `gps`, `wifi`, `battery`, `power`, `bluetooth`, `settings`, `eye`, `plus`, `minus`, `left`, `right`, `up`, `down`, `audio`, `mute`, `bars`, `loop`, `charge` |
| `qr_code` | `data` | text with `{expressions}` (drawn as text on the Field Box until a template needs it: the QR library is left out of the image) |
| `spacer` | `height` | pixels or `fill` |
| `row`, `column` | `children` | widgets, side by side or stacked, centred |

Every widget takes `id` and `style`: `font_size` (the Field Box has 14, 20, 28 and 48 and picks the nearest), `align` (`left`, `center`, `right`), `color` and `background`, `padding` (a number or `{ top, right, bottom, left }`), `width` and `height` (pixels or `fill`, the room left in the parent), and `visible` (`false` or `{expression}`). The screen's widgets stack in a centred column, 320x240 on the Field Box.

A colour is a team name, `red`, `blue`, `green`, `yellow`, `orange`, `purple`, `white`, `black`, `grey`, `muted`, `accent`, `danger`, `panel`, `background`, `#RRGGBB`, `team` (the colour of the data's `team`), `contrast` (black or white, whichever reads on the background behind it) or `{expression}` giving one of these.

Expressions read the screen's data (`left`, `team`; dots reach into objects) and the game's parameters (`params.fuse_s`), with numbers, `'text'`, `+ - * /`, comparisons, `!`, `&&`, `||` and parentheses; `&&` and `||` give the deciding value, as in Lua, so `{a && 'x' || 'y'}` chooses. A missing name is empty (0 in arithmetic), and division by zero gives 0. In text, `{expression|clock}` shows seconds as `M:SS` (`H:MM:SS` from an hour), `|upper` in capitals and `|int` without decimals; `{{` and `}}` are braces. No functions, loops or conditionals beyond these.

The simulator's mode tests check every template with the core's own parser (the one the Field Box uses), and that its name matches its file; the parser and the expressions are in [`core/src/screen_template.c`](../core/src/screen_template.c). Text on the box is English for most modes, as the scripts write it. A mode can offer its screens in more languages through a parameter, as the Medic Kit does with `lang` (`visible: "{params.lang == 'en'}"` on each language's labels). The Field Box's fonts are ASCII only: it draws accented letters without the accent and other characters as `?` (`firmware/esp32/main/screen_template.c`); the app draws every character.

## On the Field Box

Every mode in this folder is built into the Field Box firmware (`firmware/esp32/main/CMakeLists.txt`) as a preset (the Medic Kit too, so a box can be joined as a kit), and a box adds the presets of built-in modes it does not have yet at boot; the scripts are data, so a mode needs no firmware code of its own. Its screen templates are built in the same way. A preset holds up to 16 KB of script (a main mode with its modifiers, composed). The largest combination, Bomb with Codes, takes about 50 KB of a Reduced-tier box's 64 KB Lua heap when loaded; Full-tier boxes have 256 KB.
