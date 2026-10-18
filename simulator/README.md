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

The test file format is described in [modes/README.md](../modes/README.md#tests). A mode with a `field.lua` (Hold-All Domination, Last Stand) runs it as the field controller does, in the same simulation: node events reach it, `field.owner()` follows each node's captures, `field.send()` reaches the nodes, and its events, points and `game.win()` count for the whole field (`Simulation.field`). A test also fails when a mode emits an event that breaks the [protocol schema](../protocol/README.md#in-the-simulator) or would not fit in a LoRa packet.

## Play a mode in the browser

```sh
cd simulator
python -m atalaia_sim serve ../modes/bomb
python -m atalaia_sim serve ../modes/domination --node alpha=zone --node bravo=zone --param tick_s=5
python -m atalaia_sim serve ../modes/holdall --node alpha=zone --node bravo=zone --node charlie=zone
python -m atalaia_sim serve ../modes/bomb --modifier ../modes/codes --param codes=4711:hint
```

Then open <http://localhost:8000/>. The page shows every node's screen, its other outputs (such as the team display) and its last sound, plus the score, the event log with each event's size on LoRa, and any protocol problems. Press **Start game**, then hold a team's button for as long as that team holds the prop's input. The shell's `team_input.hold` events go out every 250 ms of game time, so a capture takes exactly as long as on a prop. The clock runs at 1× to 60× real time, or can be stopped and stepped. **Pause**, **End** and **Reset** act as the GM would.

| Option | Default |
| --- | --- |
| `--node NAME=ROLE` (repeat for more) | One node, named after the mode's first role |
| `--modifier FOLDER` (repeat for more) | None: the mode on its own (see [modifiers](../modes/README.md#main-modes-and-modifiers)) |
| `--teams red,blue,green` | `red,blue` |
| `--param NAME=VALUE` (repeat for more) | The defaults in `mode.yaml` |
| `--seed N` | 1 |
| `--port N`, `--host ADDR` | 8000 on 127.0.0.1 |

The server is for your own machine: it only answers requests addressed to `localhost` (add names with `--allow-host`) and only takes actions sent as JSON. It needs nothing beyond PyYAML.

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

They cover the Python event codec ([`codec.py`](atalaia_sim/codec.py), checked against the same vectors as the C codec), the packet codec ([`packet.py`](atalaia_sim/packet.py), header/nonce/AAD/payloads and AES-CCM against shared vectors), the radio model ([`radio_model.py`](atalaia_sim/radio_model.py), multi-node delivery with loss/partition/dedupe, and the duty-cycle budget and power of the game channel's EU868 sub-band, which a node may not exceed), the EU868 channel rules ([`eu868.py`](atalaia_sim/eu868.py): sub-band limits, the whole 125 kHz channel inside one sub-band, checked against the C core over a frequency sweep, the candidate channels, LoRa time on air; `test_eu868.py`), the field controller ([`field_controller.py`](atalaia_sim/field_controller.py): game lifecycle, TIME beacons, ACKs per box and epoch, event decoding and replay dedupe, score merge; the real controller in `controller/` runs this same class), the CLAIM election ([`election.py`](atalaia_sim/election.py), alone and as failover over the radio model: a backup takes over within 40 s of the controller going silent, the old controller steps down when it returns), `field.*` through the ctypes bindings (`test_field_ops.py`), the phase 2 mode pack (`test_mode_pack.py`: main modes composed with modifiers, Hold-All over five boxes, Last Stand ending the game on every box, `field.send` reaching a box, the firmware's built-in presets agreeing with the manifests, and every main mode with every modifier fitting a 16 KB preset and a Reduced-tier box's 64 KB Lua heap), every message the controller sends checked against the C decoders (`test_controller_messages.py`), the join payload codec ([`join.py`](atalaia_sim/join.py), against the same vectors as the C one, `protocol/vectors/join.json`; the field controller makes its join payloads with it), the schema checks, and the web view's game logic ([`live.py`](atalaia_sim/live.py)) and server ([`web.py`](atalaia_sim/web.py)). [`protocol.py`](atalaia_sim/protocol.py) is generated by `tools/protogen.py`; do not edit it.

## Status

| Feature | Status |
| --- | --- |
| Virtual nodes running `node.lua` | Done |
| Event-sequence tests | Done |
| Protocol checks on every emitted event | Done |
| Web view of screens, outputs, sounds and events | Done (`serve`) |
| Packet codec (header, payloads, AES-CCM) | Done (Phase 2A) |
| RadioModel (lossy delivery, partition, dedupe) | Done (Phase 2B) |
| FieldController (game lifecycle, TIME, scores) | Done (Phase 2B); ACKs, event log, transports (Phase 2D) |
| CLAIM election and failover | Done (Phase 2D), shared with the field controller |
| `field.*` and `state.field` from Python (ctypes `field_ops`) | Done (Phase 2D) |
| `field.lua` in a simulated game | Not yet: the field controller runs `field.lua`; the simulator's web view does not |
