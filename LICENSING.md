# Licensing

Atalaia uses copyleft licences: anyone may use, study, modify and even sell Atalaia, including fields that charge entry fees and makers who sell pre-built props. In return, anyone who **distributes** a modified version, or **runs a modified controller or site server for others over a network**, must publish their changes under the same licence. Improvements flow back to the community.

| Part | Folders | Licence (SPDX) |
| --- | --- | --- |
| Core, protocol, firmware, modes, simulator, tools | `core/`, `protocol/`, `firmware/`, `modes/`, `simulator/`, `tools/` | `GPL-3.0-or-later` |
| App (Android and iOS) | `app/` | `GPL-3.0-or-later`, plus the [app-store permission](app/APP-STORE-PERMISSION.md) |
| Field controller and GM console | `controller/` | `AGPL-3.0-or-later` |
| Site server | `server/` | `AGPL-3.0-or-later` |
| Hardware designs | `hardware/` | `CERN-OHL-S-2.0` |
| Documentation and the project page | `docs/`, `site/` | `CC-BY-SA-4.0` |

Full licence texts are in [`LICENSES/`](LICENSES/). The root [`LICENSE`](LICENSE) file holds the GPL text because it covers most of the repository. Per-folder licences are declared in [`REUSE.toml`](REUSE.toml), following the [REUSE](https://reuse.software) conventions, and source files carry `SPDX-License-Identifier` headers.

## Third-party code

Third-party components keep their own licences and must be compatible with GPL-3.0. The project page bundles the Barlow and Barlow Condensed fonts (OFL-1.1) in `site/fonts/`. The ESP32 firmware uses LVGL (MIT), downloaded at build time; its configuration file `firmware/esp32/lvgl_conf/lv_conf.h` is LVGL's MIT template. The firmware's screen tests vendor the stb image headers (MIT or Unlicense) in `firmware/esp32/test/third_party/stb/`. Planned dependencies include Lua 5.4 (MIT), ESP-IDF (Apache-2.0), RadioLib (MIT), LVGL (MIT) and Flutter (BSD-3-Clause). Vendored code goes in a `third_party/` folder with its original licence file.

## Community game modes

Game modes shared through the registry may use any licence from an approved list, shown on each package. Built-in modes in `modes/` are GPL-3.0-or-later.

## The name

Forks are welcome, but please give yours a different name so players can tell it apart from the original Atalaia project.

## Legal review

These licence choices and the app-store permission are pending a legal review before the first public release. Nothing in this repository is legal advice.
