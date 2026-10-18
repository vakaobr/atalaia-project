# Game modes

Each mode is a folder with a manifest and one or two Lua scripts:

```
<mode>/
  mode.yaml     id, version, licence, kind, minimum device tier, roles, parameters, translations
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

The script API is described in the "Game runtime and scripting" section of the [design specification](../docs/design-spec.md), and implemented in [`core/src/script_api.c`](../core/src/script_api.c).

Standard events, their data fields and their default priorities are listed in [`protocol/schema/events.yaml`](../protocol/schema/events.yaml); `emit()` uses that priority unless you pass `{ prio = ... }`. `team` and `squad` may go in any event's data. A mode's own events are named `x.<club>.<name>` and can carry any data. Tests fail if a mode emits anything else, or an event too large for a LoRa packet (200 bytes, see [protocol/README.md](../protocol/README.md#events-on-lora)).

## The mode pack (phase 2)

Ideas from public community requests (design specification sections 2 and 15); the rules and texts are our own.

- **Hold-All Domination** (`org.atalaia.holdall`): boxes are captured as in Domination, but they do not score. The controller's `field.lua` scores a team only while it holds every zone box (`points_per_tick` every `tick_s` seconds, the first tick one full `tick_s` after the last box fell), and only with at least `min_zones` boxes in play. Events: `holdall.scoring_start` and `holdall.scoring_stop` (from the controller).
- **Last Stand** (`org.atalaia.laststand`): the `defenders` hold every zone when the game starts. Once their defence is set up, a countdown of `countdown_s` runs while they hold `last_zones` zones or fewer (default: 1 of N); retaking a zone stops it, and it starts over (`reset`, the default) or carries on where it stopped. When it runs out, `laststand.defeated` is logged and, with `end_game`, the game ends with the `attackers` as winners. Events: `laststand.countdown_start` and `laststand.countdown_cancel` (with `duration_s`), `laststand.defeated`.
- **Bomb team codes**: with `team_codes` (`red=1234,blue=5678`) the keypad arms and defuses instead of the team buttons. In standby a team's code arms the bomb for that team; once armed, another team's code defuses it. `bomb.armed` and `bomb.defused` then carry the team and `reason: code`. Without `team_codes` the bomb behaves exactly as before.
- **Codes** (`org.atalaia.codes`, a modifier): `codes` lists keypad codes as `digits:kind[:points][:team]`, comma-separated, where kind is `points`, `hint` or `unlock` (`4711:points:50,0815:hint,2222:unlock:red`). Type the digits, then `#`; `*` clears. Each code works once per game on each box. `code.used` tells the GM which code (its place in the list), what it gave, the team it counted for (the code's team, else the team holding the box) and the team holding the box (`holder`). A points code with no team and no holder is refused.

On a box without a controller (picked from the box's own preset list), Hold-All and Last Stand boxes only capture: their scoring and countdown live in `field.lua`.

## Phase 3 modes (player tags)

These modes identify players by their **player tag**: an NFC tag signed with the game key ([protocol/nfc-tag.md](../protocol/nfc-tag.md)). The box checks the tag before the script sees it and gives the script `nfc.tag` with `valid`, and `player` and `team` (or the `reason` it was refused). In a game a box picked from its own preset list there is no game key, so tags are refused there (`no_game`); these modes are for games run by a field controller. Each box counts on its own: no state is shared between boxes.

- **Kill Confirmed** (`org.atalaia.kill_confirmed`): players drop their tag when hit. A team presses its button at the station and scans the tags it collected within `turn_in_s` seconds (each tag that counts keeps the station open). An enemy's tag confirms the kill: `kill.confirmed`, `confirm_points` for the team and `penalty_points` off the tag's team (`score.delta`). A teammate's tag denies it: `kill.denied`, no points. The same player's tag counts again only after `retag_after_s` seconds. The penalty is local to the box: a box reports only the points a team gained to the controller (decision E6), so the controller's totals do not subtract it, although the console lists the `score.delta` event.
- **Respawn and Lives** (`org.atalaia.respawn`): a respawn point counts lives, per team (default) or per player (`per_player`). A player scans their tag to come back in (`player.respawn` with `lives_left`) and waits `respawn_cooldown_s` before the next respawn. Without tags, a team's button press is a respawn for that team (with a 2 s guard against double presses). A team with no lives left is refused and reported once: `team.eliminated`.
- **Player Check-in** (`org.atalaia.player_checkin`): players check in at a checkpoint with their tag (`player.checkin`); the screen shows the count per team, and the team gets `points` per check-in. A player counts once per game, or again after `repeat_after_s` seconds; a scan before that is a duplicate and is refused.

Money Factory (also phase 3, ADR-P3-8) comes in a later plan phase: its events (`money.collected`, `money.deposited`) are in the schema already.

## Main modes and modifiers

`kind: modifier` marks a package that runs alongside a main mode on the same node. A game, a preset and a join payload name a main mode and its modifiers with one id joined by `+`, main mode first:

```
org.atalaia.domination+org.atalaia.codes
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

The simulator (`atalaia_sim.mode.compose`), the field controller and the Field Box (`firmware/esp32/main/box_game.c`, from its stored presets) build the same chunk; `field.lua` scripts compose the same way. The parameters of the parts are merged into one schema, so their names must differ; the whole id is at most 63 bytes (it travels in the join payload). A modifier on its own is a valid game too: Codes alone makes the box a code terminal.

Scripts on one box that read keypad codes share them through the global table `keypad_codes`: each adds a function that says whether a code is its own, so a code meant for one script is not reported as wrong by the other (Bomb's team codes and Codes do this).

While its prompt is up, Codes keeps the screen: it wraps `ui.screen`, holds the main mode's screens and shows the newest one when the prompt closes.

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
| `nfc.tag` | `uid`, `valid`, then `player` and `team` (valid) or `reason` | A tag is read, checked against the game's key first ([nfc-tag.md](../protocol/nfc-tag.md)): `reason` is `unsigned`, `no_game`, `format`, `version`, `game`, `mac` or `team` |
| `cmd.set_owner` | `team` (or `none`) | The GM's owner override from the console (decision E7); Hold-All and Last Stand handle it |
| `gm.message` | `text` | A message from the GM |

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

When the mode has a `field.lua`, it runs as the controller runs it: it receives every node's events (with `node` and `team` in the data), `field.owner()` is the team of each node's last `zone.captured` (as box STATE reports it), `field.send(node, "set_owner" or "message", params)` reaches the node as `cmd.set_owner` or `gm.message`, its own events are logged from node `controller`, its points count in the field total, and a `game.win()` or `game.finish()` ends the game on every node. Time then moves in steps of 100 ms.

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

`ui.screen(name, data)` shows one of the mode's screens. A mode ships its screens as YAML templates in `assets/screens/<name>.yaml` (ADR-P3-4); the Field Box draws them with LVGL and the Android app will draw the same files with Flutter. A name without a template falls back to the Field Box's built-in screens (`code_entry`, used by Codes and Bomb's team codes, and the older C versions of the screens below), so Hold-All, Last Stand and Codes keep their C screens for now.

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

The simulator's mode tests check every template with the core's own parser (the one the Field Box uses), and that its name matches its file; the parser and the expressions are in [`core/src/screen_template.c`](../core/src/screen_template.c). Text on the box is English for now, as the scripts write it.

## On the Field Box

Every mode in this folder is built into the Field Box firmware (`firmware/esp32/main/CMakeLists.txt`) as a preset, and a box adds the presets of built-in modes it does not have yet at boot; the scripts are data, so a mode needs no firmware code of its own. Its screen templates are built in the same way. A preset holds up to 16 KB of script (a main mode with its modifiers, composed). The largest combination, Bomb with Codes, takes about 50 KB of a Reduced-tier box's 64 KB Lua heap when loaded; Full-tier boxes have 256 KB.
