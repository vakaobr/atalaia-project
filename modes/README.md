# Game modes

Each mode is a folder with a manifest and one or two Lua scripts:

```
<mode>/
  mode.yaml     id, version, licence, minimum device tier, roles, parameters
  node.lua      runs on each prop with the mode's role
  field.lua     optional: runs on the field controller for logic across props
  assets/       optional: sound clips, screen templates
  i18n/         optional: translated strings
  tests/        event sequences with expected results
```

The GM console builds its settings form from `params` in `mode.yaml`, so GMs never edit Lua.

| Mode | Status |
| --- | --- |
| [Domination](domination/) | Runs in the simulator; 5 tests |
| [Bomb / Rush](bomb/) | Runs in the simulator; 6 tests |

The script API is described in the "Game runtime and scripting" section of the [design specification](../docs/design-spec.md), and implemented in [`core/src/script_api.c`](../core/src/script_api.c).

## Inputs from the hardware

Modes react to semantic capabilities, so the same script works on a box with team buttons, a keypad or a touchscreen. The platform shell turns hardware into these events:

| Event | Data | When |
| --- | --- | --- |
| `team_input.press` | `team`, optional `squad` | A team presses its input |
| `team_input.hold` | `team`, `ms`, optional `squad` | Every 250 ms while a team holds its input; `ms` is the time held so far |
| `team_input.release` | `team`, `ms`, optional `squad` | The team lets go |

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

The game starts automatically at time 0 (`autostart: false` turns that off). Only `wait` and `hold` move time forward.

| Step | Example | What it does |
| --- | --- | --- |
| `wait` | `wait: 30` | Lets 30 seconds of game time pass |
| `hold` | `hold: { team: red, s: 5 }` | A team holds the input for 5 s and lets go; time passes |
| `press` | `press: { team: blue }` | A team presses the input |
| `input` | `input: { type: nfc.tag, data: { uid: "04a1" } }` | Any event to a node |
| `start`, `end`, `pause`, `resume` | `end: time` | Game events from the controller to every node |
| `expect` | `expect: { type: zone.captured, team: red, at: 3, data: { previous_team: blue } }` | The next matching event exists; later `expect`s search after it |
| `expect_no` | `expect_no: bomb.exploded` | No matching event since the last `expect` |
| `expect_score` | `expect_score: { team: red, points: 6 }` | Field total, or one node's with `node:` |
| `expect_screen` | `expect_screen: { template: countdown, data: { left: 1 } }` | The last screen a node showed |
| `expect_status` | `expect_status: ended` | `running`, `ended` or `halted` |

Steps that target a node take `node:`, which can be left out when the game has one node. In `expect`, a plain string matches the event type only; `data` matches a subset of the event's data.
