# Simulator

Runs the shared core on a desktop with any number of virtual nodes on a virtual clock. It is used to develop and test game modes before any hardware exists, and CI uses it to run every mode's `tests/`.

It is a small Python package that loads the core as a shared library, so modes behave exactly as they will on a prop.

## Run the mode tests

```sh
cmake -S core -B build -DATALAIA_SHARED=ON && cmake --build build
pip install -r simulator/requirements.txt
cd simulator
python -m atalaia_sim test                     # every mode in modes/
python -m atalaia_sim test ../modes/bomb       # one mode
```

The simulator looks for the library in `build/`. Point it elsewhere with `--lib PATH` or the `ATALAIA_CORE_LIB` environment variable. A failing test prints the merged event log and the scripts' log lines.

The test file format is described in [modes/README.md](../modes/README.md#tests). A mode with a `field.lua` (Hold-All Domination, Last Stand) runs it as the field controller does, in the same simulation: node events reach it, `field.owner()` follows each node's captures, `field.send()` reaches the nodes, and its events, points and `game.win()` count for the whole field (`Simulation.field`). A test also fails when a mode emits an event that breaks the [protocol schema](../protocol/README.md#in-the-simulator) or would not fit in a LoRa packet. A mode's screen templates (`assets/screens/*.yaml`) count as one more test per mode: each must pass the core's own template parser and carry its file's name. The simulated game has a game id and key (fixed per seed), so the `scan` step makes and checks player tags as a box does.

## Play a mode in the browser

```sh
cd simulator
python -m atalaia_sim serve ../modes/bomb
python -m atalaia_sim serve ../modes/domination --node alpha=zone --node bravo=zone --param tick_s=5
python -m atalaia_sim serve ../modes/holdall --node alpha=zone --node bravo=zone --node charlie=zone
python -m atalaia_sim serve ../modes/bomb --modifier ../modes/codes --param codes=4711:hint
```

Then open <http://localhost:8000/>. The page shows every node's screen, its other outputs (such as the team display) and its last sound, plus the score, the event log with each event's size on LoRa, and any protocol problems. A mode with a `field.lua` (Hold-All Domination, Last Stand) runs it as the field controller does, and the *Field controller* panel shows its state, its points, the commands it sent to boxes and its log. Press **Start game**, then hold a team's button for as long as that team holds the prop's input. The shell's `team_input.hold` events go out every 250 ms of game time, so a capture takes exactly as long as on a prop. The clock runs at 1× to 60× real time, or can be stopped and stepped. **Pause**, **End** and **Reset** act as the GM would.

| Option | Default |
| --- | --- |
| `--node NAME=ROLE` (repeat for more) | One node, named after the mode's first role |
| `--modifier FOLDER` (repeat for more): a modifier or a role package such as `../modes/medic` (give its nodes their role with `--node kit=medic`) | None: the mode on its own (see [modifiers and role packages](../modes/README.md#main-modes-modifiers-role-packages-and-scenarios)) |
| `--teams red,blue,green` | `red,blue` |
| `--param NAME=VALUE` (repeat for more) | The defaults in `mode.yaml` |
| `--seed N` | 1 |
| `--port N`, `--host ADDR` | 8000 on 127.0.0.1 |

The server is for your own machine: it only answers requests addressed to `localhost` (add names with `--allow-host`) and only takes actions, and the editor's reloads, sent as JSON. It needs nothing beyond PyYAML.

## Write a mode in blocks

The simulator also serves the **mode editor** (phase 5 plan phase 1): while `serve` runs, open <http://localhost:8000/editor/>. Build a mode from blocks, one workspace for the boxes' script (`node.lua`) and one for the field controller's (`field.lua`), and fill in the *Mode* tab; the editor writes `node.lua`, `field.lua` and `mode.yaml` beside the blocks as you go, lists problems (a setting used but not declared, an event's value outside a "when" block, ...) and points at their block. Save the blocks as a `.blocks.json` file and open it again later; download each generated file into a mode folder, add `tests/`, and run them with `python -m atalaia_sim test`. *Examples* loads Domination and Hold-All Domination as blocks: their generated files pass every test of the hand-written modes. **Test in the simulator** (phase 5 plan phase 2) sends the generated files to the server (`POST /api/reload`, at most 1 MB): they load in the core first, and if they load the game in the simulator becomes this mode, started, with the number of boxes you chose (*Boxes*); *Open the game* shows it in the simulator's tab. If they do not load, the game that was running goes on. Errors the scripts hit, on loading or while the game runs, appear in the editor's problems list and as warnings on the blocks they come from. The page speaks English and European Portuguese and needs no network: Blockly 13.3.0 is vendored in [`atalaia_sim/editor/vendor/blockly/`](atalaia_sim/editor/vendor/blockly/README.md). A mode made this way reaches Field Boxes only by joining `modes/` and a firmware release (boxes run built-in scripts only, decision K10); planned: the GM console sending a box the signed modes a game needs (phase 5 plan phase 13, the maintainer's P5R-8). The editor's design: `docs/phase-5-community/` (ADR-P5-1 and P5-2 as amended 2026-10-22).

### Without a C compiler

The simulator needs the core built as a native library, so without a C compiler (Windows without Visual Studio, for example) run it in the [dev container](../tools/dev/Dockerfile) with [`tools/docker_sim.py`](../tools/docker_sim.py). It takes the same arguments and works from `cmd`, PowerShell or bash, as long as Docker is running:

```sh
python ../tools/docker_sim.py serve ../modes/bomb       # from simulator/
python tools/docker_sim.py test                          # from the repository root
```

The first run builds the `atalaia-dev` image, and every run rebuilds the core incrementally, so it takes a few seconds before the URL appears. The page is published on `localhost` only. Ctrl+C stops it; if a window was closed instead, `docker rm -f atalaia-serve-8000` removes the leftover container.

## Dependencies

| Package | Required | Purpose |
| --- | --- | --- |
| PyYAML | Yes | Schema loading, test vector parsing |
| cryptography | Yes (in CI, optional locally) | AES-128-CCM for packet encryption in `packet.py` |

Install with `pip install -r simulator/requirements.txt`, or use the dev container (which installs `python3-cryptography` from apt).

When `ATALAIA_REQUIRE_ALL=1` is set (as in `tools/check.sh` and CI), tests that need `cryptography` fail instead of skipping.

## Run the simulator's own tests

```sh
cd simulator
python -m unittest discover -s tests
```

They cover the Python event codec ([`codec.py`](atalaia_sim/codec.py), checked against the same vectors as the C codec), the packet codec ([`packet.py`](atalaia_sim/packet.py), header/nonce/AAD/payloads and AES-CCM against shared vectors), the radio model ([`radio_model.py`](atalaia_sim/radio_model.py), multi-node delivery with loss/partition/dedupe, and the duty-cycle budget and power of the game channel's EU868 sub-band, which a node may not exceed), the EU868 channel rules ([`eu868.py`](atalaia_sim/eu868.py): sub-band limits, the whole 125 kHz channel inside one sub-band, checked against the C core over a frequency sweep, the candidate channels, LoRa time on air; `test_eu868.py`), the field controller ([`field_controller.py`](atalaia_sim/field_controller.py): game lifecycle, TIME beacons, ACKs per box and epoch, event decoding and replay dedupe, score merge; the real controller in `controller/` runs this same class), the CLAIM election ([`election.py`](atalaia_sim/election.py), alone and as failover over the radio model: a backup takes over within 40 s of the controller going silent, the old controller steps down when it returns), `field.*` through the ctypes bindings (`test_field_ops.py`), `geo.distance` and `geo.in_zone` from Lua through the ctypes bindings against `protocol/vectors/geo.json`, known answers and exact bits (`test_geo.py`), the Medic Kit and role packages (`test_medic.py`: a kit's node running the kit alone next to Domination with its own parameters, two kits sharing a player's limit through the medic `field.lua`, a kit out of the controller's reach using its own count and the totals adding up when it is back (`Simulation.set_reachable`), a rebooted kit told every count again, mode commands that must name themselves), scenario packages and the objectives role package (`test_scenario.py`: the composition rules against the shared vectors of `protocol/vectors/composition.yaml`, which the app's Dart runner passes too; the example scenario `modes/objectives/tests/fixtures/foxhound` setting its nodes up with the mode command `setup`, once and again after a reboot (`Simulation.reboot`, the `reboot` test step); no join carrying the scenario or its parameters; a `field.send` too large for a box's 128-byte CMD buffer reported in `Simulation.problems`; the objectives script in a Reduced box's Lua heap), the phase 2 mode pack (`test_mode_pack.py`: main modes composed with modifiers, Hold-All over five boxes, Last Stand ending the game on every box, `field.send` reaching a box, the firmware's built-in presets agreeing with the manifests, and every main mode with every modifier fitting a 16 KB preset and a Reduced-tier box's 64 KB Lua heap), every message the controller sends checked against the C decoders (`test_controller_messages.py`), the join payload codec ([`join.py`](atalaia_sim/join.py), against the same vectors as the C one, `protocol/vectors/join.json`; the field controller makes its join payloads with it), the field frames ([`field_frame.py`](atalaia_sim/field_frame.py): HKDF-SHA256 against RFC 5869, bodies, sealed frames, refusals and invite parts against `protocol/vectors/field_frame.json`, as the C codec; `test_field_frame.py`) and re-inviting boxes between games ([`lobby.py`](atalaia_sim/lobby.py), the box's and the controller's sides, which the controller runs too: in the radio model a box leaves one game, announces itself and is invited into the next, its HELLO reaching the next game's FieldController; a box in a game answers busy, a replayed invite and the same game again are refused, another field's frames are not heard, a two-part invite gets through a lossy radio, DISCOVER brings an answer within seconds, and an hour of announcements keeps within 2 % of the duty cycle; `test_reinvite_sim.py`), the player tag codec ([`tag.py`](atalaia_sim/tag.py), against `protocol/vectors/tag.json`, and agreeing with the core's `nfc.tag` data through ctypes), the capability proxy codec ([`capability_proxy.py`](atalaia_sim/capability_proxy.py): frames, payloads and a resynchronising decoder, against `protocol/vectors/capability_proxy.yaml`), the screen template checks ([`screens.py`](atalaia_sim/screens.py): every `modes/*/assets/screens/*.yaml` through the core's parser), the schema checks, the web view's game logic ([`live.py`](atalaia_sim/live.py): also a field script playing live, and reloading a mode from the editor's files with its errors' script and line, the running game kept on an error) and server ([`web.py`](atalaia_sim/web.py): also `POST /api/reload` under the same rules as actions, its size limit and its answers), and the mode editor's files as the server serves them (`test_editor_files.py`: routes and their Content-Security-Policy, the vendored Blockly against its checksums, both languages' keys, the example projects). [`protocol.py`](atalaia_sim/protocol.py) is generated by `tools/protogen.py`; do not edit it.

The mode editor's browser tests (`editor_tests/`: the Lua generator's unit tests, both examples' round trip through the hand-written modes' tests, the page in both languages, save, open and the draft; the *Test* button playing Hold-All in the simulator's page, errors back on their blocks, every generated line mapped to its block) run in headless Chromium: `python tools/docker_editor.py` from the repository root (CI's `editor` job).

## Status

| Feature | Status |
| --- | --- |
| Virtual nodes running `node.lua` | Done |
| Event-sequence tests | Done |
| Protocol checks on every emitted event | Done |
| Web view of screens, outputs, sounds and events | Done (`serve`) |
| Packet codec (header, payloads, AES-CCM) | Done (Phase 2A) |
| RadioModel (lossy delivery, partition, dedupe) | Done (Phase 2B) |
| FieldController (game lifecycle, TIME, scores) | Done (Phase 2B); ACKs, event log, transports (Phase 2D); node health events `node.online`, `node.offline`, `battery.low` (phase 4 follow-up, decisions FU1-1 to FU1-4; off unless the host sets `node_offline_ms` and `battery_low_pct`, as the field controller does) |
| CLAIM election and failover | Done (Phase 2D), shared with the field controller |
| `field.*` and `state.field` from Python (ctypes `field_ops`) | Done (Phase 2D) |
| `field.lua` in a simulated game | Done: in tests (phase 2) and in the web view, with its own panel (phase 5 plan phase 2) |
| Player tags in tests (`scan` step, `nfc.tag` checked by the core with the game's key) | Done (phase 3, plan phase A) |
| Mode editor (blocks to `node.lua`, `field.lua` and `mode.yaml`, at `/editor/`) | Done (phase 5, plan phase 1, 2026-10-22); its *Test in the simulator* with `POST /api/reload` and errors back on the blocks: done (plan phase 2, 2026-10-22) |
| Screen template checks (the core's parser through ctypes) | Done (phase 3, plan phase A); the web view still shows a screen's name and data, not the template drawn |
| Capability proxy reference codec | Done (phase 3, plan phase A) |
