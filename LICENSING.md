# Licensing

Atalaia uses copyleft licences: anyone may use, study, modify and even sell Atalaia, including fields that charge entry fees and makers who sell pre-built props. In return, anyone who **distributes** a modified version, or **runs a modified controller or site server for others over a network**, must publish their changes under the same licence. Improvements flow back to the community.

| Part | Folders | Licence (SPDX) |
| --- | --- | --- |
| Core, protocol, firmware, modes, simulator, tools | `core/`, `protocol/`, `firmware/`, `modes/`, `simulator/`, `tools/` | `GPL-3.0-or-later` |
| App (Android and iOS) | `app/` | `GPL-3.0-or-later`, plus the [app-store permission](app/APP-STORE-PERMISSION.md) |
| Field controller | `controller/` (except the console) | `AGPL-3.0-or-later` |
| GM console | `controller/console/` | `GPL-3.0-or-later`, plus the [app-store permission](app/APP-STORE-PERMISSION.md) |
| Site server | `server/` | `AGPL-3.0-or-later` |
| Hardware designs | `hardware/` | `CERN-OHL-S-2.0` |
| Documentation and the project page | `docs/`, `site/` | `CC-BY-SA-4.0` |

The GM console was AGPL-3.0-or-later until 2026-10-22. It is browser code that every user's browser receives as readable source, so the AGPL's network clause added nothing to it, and the app could not ship it with the app-store permission under the AGPL. Its copyright holder moved it to GPL-3.0-or-later with that permission, so the phone controller can serve the same console (decision PE24-8); the controller's server code stays AGPL-3.0-or-later.

Full licence texts are in [`LICENSES/`](LICENSES/). The root [`LICENSE`](LICENSE) file holds the GPL text because it covers most of the repository. Per-folder licences are declared in [`REUSE.toml`](REUSE.toml), following the [REUSE](https://reuse.software) conventions, and source files carry `SPDX-License-Identifier` headers.

## Third-party code

Third-party components keep their own licences and must be compatible with GPL-3.0. The project page bundles the Barlow and Barlow Condensed fonts (OFL-1.1) in `site/fonts/`. The ESP32 firmware uses LVGL (MIT), downloaded at build time; its configuration file `firmware/esp32/lvgl_conf/lv_conf.h` is LVGL's MIT template. The firmware's screen tests vendor the stb image headers (MIT or Unlicense) in `firmware/esp32/test/third_party/stb/`. Planned dependencies include Lua 5.4 (MIT), ESP-IDF (Apache-2.0), RadioLib (MIT), LVGL (MIT) and Flutter (BSD-3-Clause). Vendored code goes in a `third_party/` folder with its original licence file.

## Map data in a field's image

A field image drawn by the console's *Load the field from a map* (decisions MF-19 to MF-30) is the field's own data, made in the GM's browser and kept on the field controller; it is not part of this repository. It is drawn from OpenStreetMap data (© OpenStreetMap contributors, ODbL) and, in mainland Portugal, the DGT's orthophoto (Ortofotomapas © DGT, CC BY 4.0), and carries both attributions in its corner. The browser tests use made-up fixtures, not OpenStreetMap or DGT data. No map library is vendored: the console's map viewer is the project's own code.

## Community game modes

Game modes shared through the registry may use any licence from an approved list, shown on each package. Built-in modes in `modes/` are GPL-3.0-or-later.

## The name

Forks are welcome, but please give yours a different name so players can tell it apart from the original Atalaia project.

## Legal review

These licence choices and the app-store permission are pending a legal review before the first public release. Nothing in this repository is legal advice.
