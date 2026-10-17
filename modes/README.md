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
| [Domination](domination/) | Draft script, waiting for the core runtime |
| [Bomb / Rush](bomb/) | Draft script, waiting for the core runtime |

The script API these drafts use is described in the "Game runtime and scripting" section of the design specification. It is not implemented yet, so expect small changes.
