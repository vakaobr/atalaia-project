# Tools

Developer scripts.

| Tool | What it does |
| --- | --- |
| [`check.sh`](check.sh) | Checks the generated protocol files and project page, builds the core and runs its tests, the simulator's tests and every game mode's tests: the same checks as CI |
| [`format.sh`](format.sh) | Formats the core's C (clang-format 18) and the modes' Lua (StyLua); `--check` fails if anything needs formatting, as CI does |
| [`protogen.py`](protogen.py) | Generates the C and Python protocol tables, the C test vectors and the JSON Schema from `protocol/schema/`; `--check` fails if they are stale. See [protocol/README.md](../protocol/README.md#changing-the-schema) |
| [`build_site.py`](build_site.py) | Builds the project page in Portuguese (`site/index.html`) and English (`site/en/index.html`) from `site/src/` and `site/i18n/`; `--check` fails if a page is stale, a translation is missing a key, or a `#` link has no target. See [site/README.md](../site/README.md#translating-the-page) |
| [`docker_sim.py`](docker_sim.py) | Runs any simulator command (`serve`, `test`) in the dev container, from any shell: `python tools/docker_sim.py serve modes/bomb` |
| [`docker_fw.py`](docker_fw.py) | Builds the ESP32 firmware (`build`), its Wokwi emulator variant (`wokwi`) and runs its host tests (`test`, `test --update-screens`) in Docker, from any shell. See [firmware/esp32/README.md](../firmware/esp32/README.md#build) |
| [`dev/Dockerfile`](dev/Dockerfile) | A Linux build environment matching CI, for machines without a C toolchain |

Using the dev container (from the repository root):

```sh
docker build -t atalaia-dev tools/dev
docker run --rm -v "$PWD:/src" atalaia-dev sh tools/check.sh
```

On Windows, use `${PWD}` in PowerShell or `$(pwd -W)` in Git Bash for the volume path.
