# Tools

Developer scripts.

| Tool | What it does |
| --- | --- |
| [`check.sh`](check.sh) | Checks the generated protocol files, the project page and the formatting, builds the core and runs its tests, the simulator's tests, every game mode's tests and the field controller's tests (with the C host modem, the C host box and Mosquitto): the same checks as CI, apart from the firmware jobs, the console's browser tests and the app's Dart tests (`docker_app.py`) |
| [`format.sh`](format.sh) | Formats the core's C (clang-format 18) and the modes' Lua (StyLua); `--check` fails if anything needs formatting, as CI does |
| [`protogen.py`](protogen.py) | Generates the C and Python protocol tables, the C test vectors and the JSON Schema from `protocol/schema/`; `--check` fails if they are stale. See [protocol/README.md](../protocol/README.md#changing-the-schema) |
| [`build_site.py`](build_site.py) | Builds the project page in Portuguese (`site/index.html`) and English (`site/en/index.html`), and the radio diagrams (`site/img/diagrams/`), from `site/src/` and `site/i18n/`; `--check` fails if a page or diagram is stale, a translation is missing a key or does not fit its diagram, or a `#` link has no target. See [site/README.md](../site/README.md#translating-the-page) |
| [`docker_sim.py`](docker_sim.py) | Runs any simulator command (`serve`, `test`) in the dev container, from any shell: `python tools/docker_sim.py serve modes/bomb` |
| [`docker_fw.py`](docker_fw.py) | Builds the ESP32 firmware (`build`), its Wokwi emulator variant (`wokwi`), the USB radio modem variant (`modem`) and runs its host tests (`test`, `test --update-screens`) in Docker, from any shell. See [firmware/esp32/README.md](../firmware/esp32/README.md#build) |
| [`docker_console.py`](docker_console.py) | Runs the GM console's browser tests (headless Chromium against the real controller) in Docker, from any shell: `python tools/docker_console.py` (`-k NAME` for some). See [controller/console/README.md](../controller/console/README.md#tests) |
| [`docker_app.py`](docker_app.py) | Runs the app's Dart checks in the pinned Flutter image (`ghcr.io/cirruslabs/flutter:3.44.0`), as CI's "Player app logic (Dart)" job does: `python tools/docker_app.py` (`flutter analyze`, `dart format` check, `flutter test`), `test [paths]`, `format`, `lock`. Not part of `check.sh`: the dev container has no Dart. See [app/README.md](../app/README.md#tests) |
| [`check_wiring.py`](check_wiring.py) | Checks the Field Box wiring diagrams and pin table against the firmware's Kconfig pin defaults, and that the rendered diagrams are current |
| [`docker_hw.py`](docker_hw.py) | Renders the wiring diagrams (WireViz, pinned, in Docker) with `render`; `check` runs `check_wiring.py` |
| [`dev/Dockerfile`](dev/Dockerfile) | A Linux build environment matching CI, for machines without a C toolchain; it also has the field controller's Python packages and Mosquitto |
| [`dev/console/Dockerfile`](dev/console/Dockerfile) | The browser test image: Playwright 1.49 with Chromium, the controller's packages, Mosquitto and zbar-tools (built by `docker_console.py` and CI's console job) |

Using the dev container (from the repository root):

```sh
docker build -t atalaia-dev tools/dev
docker run --rm -v "$PWD:/src" atalaia-dev sh tools/check.sh
```

On Windows, use `${PWD}` in PowerShell or `$(pwd -W)` in Git Bash for the volume path.

`docker_sim.py`, `docker_fw.py`, `docker_console.py` and `docker_app.py` keep their build caches (for `docker_app.py`, the downloaded Dart packages) in named Docker volumes. To run them from two checkouts at once (for example a git worktree), give each its own volumes with `ATALAIA_VOLUME_SUFFIX`, e.g. `ATALAIA_VOLUME_SUFFIX=-p3 python tools/docker_fw.py test`.
