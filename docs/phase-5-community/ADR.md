<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phase 5 -- Community: Architecture Decisions

Eight decisions settle the structure of the visual mode editor, the mode
registry with its signing and verification scheme, the carrier PCB scope,
the i18n architecture, and the community governance process before any
implementation begins. Each one answers a question the research phase
identified and creates a constraint that the planning phase must respect.

---

### ADR-P5-1: Blockly-to-Lua code generation strategy

**Status:** Accepted

**Context:** The visual editor must generate readable `node.lua` and
`field.lua` scripts using the Blockly library (design-spec.md section 9:
"Generated code stays readable, so a GM can graduate to editing it by
hand"). Blockly provides a `CodeGenerator` base class that can target
any language; built-in generators exist for JavaScript, Python, Dart,
Lua and PHP. The alternative is a template-based approach that
concatenates string fragments without using Blockly's generator
framework. The existing modes (`modes/domination/node.lua` at 29 lines,
`modes/bomb/node.lua` at 67 lines) establish the target output style:
minimal, idiomatic Lua with 2-space indentation, named local functions,
`state.node{}` at the top, `on()` handlers, `every()`/`after()` timers,
and `cap()`/`ui.*`/`audio.*` hardware calls.

Blockly is an active Google project with breaking changes between major
versions. The editor must pin a specific version to avoid silent
regressions in block definitions and generated code.

**Decision:**

**Use Blockly's `CodeGenerator` class with a custom Lua target.** The
generator subclasses `CodeGenerator` and registers a block-to-code
function for each custom block. This is the same approach used by
Blockly's built-in Python and Dart generators and produces code that
follows the block tree's structure rather than relying on brittle string
templates.

The custom Lua generator applies these formatting rules to keep the
output indistinguishable from hand-written mode scripts:

1. **2-space indentation**, matching the project's StyLua configuration.
2. **Named local functions** for event handlers and timer callbacks
   (e.g., `local function on_hold(e)` rather than anonymous inline
   functions), generated from the block's label or the event type.
3. **`state.node{}` at the top**, generated from the editor's state
   variable declarations, before any handler.
4. **No Blockly boilerplate comments.** The default `CodeGenerator`
   inserts `-- Describe this function...` placeholders; the custom
   generator suppresses these.
5. **Blank lines** between top-level blocks (state, handlers, timers)
   for readability.

Block categories map 1:1 to the script API surface from `script_api.c`
and design-spec.md section 9:

| Block category | Script API | Blocks |
|----------------|-----------|--------|
| Events | `on(type, fn)`, `emit(type, data, opts)` | "when [event] happens", "send event [type] with [data]" |
| Timers | `every(s, fn)`, `after(s, fn)`, `cancel(id)` | "every [N] seconds do", "after [N] seconds do", "cancel timer [id]" |
| State | `state.node{}`, `state.field{}` | "set state [key] to [value]", "get state [key]" |
| Game control | `game.start()`, `game.finish(reason)`, `game.win(team)` | "end game", "team [team] wins" |
| Scoring | `score.add(team, n, reason, squad)`, `score.get(team)` | "add [N] points to [team] for [reason]" |
| Hardware | `cap(id):method(...)`, `ui.screen(t, d)`, `audio.play(clip)` | "show screen [template]", "play sound [clip]", "show team color" |
| Field | `field.nodes(role)`, `field.owner(node)`, `field.send(node, cmd)` | "for each node with role [role]", "send [cmd] to [node]" |
| Utilities | `params`, `rand(a, b)`, `log(msg)` | "parameter [name]", "random between [a] and [b]" |

The editor also generates `mode.yaml` from the block workspace:
blocks using `cap("team_display")` imply `requires: [team_input]`;
blocks using `nfc` or `keypad` capabilities add those to `optional`.
Parameter declarations in the editor produce the `params` section with
type, default, min/max and label.

**Blockly version pinning:** Pin to a specific minor release of
Blockly v11.x (e.g., `blockly@11.2.1`). The pinned version is vendored
into `editor/vendor/blockly/` and committed to the repository, rather
than loaded from a CDN. This eliminates CDN availability as a runtime
dependency and ensures the editor works fully offline (consistent with
the project's local-first principle, design-spec.md section 3). Version
updates go through a PR that runs the full block-definition and
code-generation test suite.

**CI round-trip test:** A CI job generates Lua from every example block
workspace (one per built-in mode pattern), then runs the generated Lua
through `python -m atalaia_sim test` to verify correctness. This catches
both Blockly upgrade regressions and script API changes that break the
editor.

**Consequences:**
- The `CodeGenerator` class provides operator precedence, variable
  scoping, and indentation management out of the box. A template-based
  approach would have to reimplement all of these.
- Named local functions make the output greppable and debuggable. A GM
  who graduates from the editor can find handlers by function name.
- Vendoring Blockly adds ~2 MB to the repository. This is acceptable
  for an editor that must work offline on a field with no internet.
- Every script API change in `script_api.c` requires a corresponding
  update to the block definition and code generator. The CI round-trip
  test catches omissions.
- Field-script blocks (`state.field{}`, `field.*`) cannot be finalized
  until the field API ships in phase 2C. Node-script blocks can proceed
  immediately.

---

### ADR-P5-2: Editor-simulator integration architecture

**Status:** Accepted

**Context:** The simulator's web view (`simulator/atalaia_sim/web.py`)
serves static files and a JSON API (`GET /api/state`,
`POST /api/action`). The editor should integrate with the simulator so
a GM can write blocks, generate Lua, and test the mode live in the
browser. The simulator's `LiveGame` class (`simulator/atalaia_sim/live.py`)
wraps a `Simulation` with a real-time clock and thread-safe state. The
editor needs a mechanism to push generated Lua to the simulator and
trigger a hot-reload.

Two integration approaches exist: (a) a REST endpoint that accepts
the generated Lua and restarts the simulation, or (b) a WebSocket
connection that streams Lua and receives live state updates.

**Decision:**

**Add a `POST /api/reload` endpoint to the simulator's web server.**
The endpoint accepts a JSON body containing the generated `node.lua`
(and optionally `field.lua` and `mode.yaml`) and restarts the
simulation with the new scripts. This is simpler than a WebSocket and
sufficient for the use case: the GM edits blocks, clicks "Test", the
editor POSTs the Lua, and the simulator reloads.

Endpoint specification:

```
POST /api/reload
Content-Type: application/json

{
  "node_lua": "-- generated node.lua content",
  "field_lua": null,
  "mode_yaml": "id: org.atalaia.custom\n...",
  "params": { "fuse_s": 300 }
}
```

Response: `200 OK` with `{"status": "ok", "errors": []}` on success,
or `200 OK` with `{"status": "error", "errors": ["line 12: ..."]}` if
the Lua fails to load (syntax error or sandbox violation). The endpoint
never returns 4xx/5xx for Lua errors; it always reports them in the
response body so the editor can display them inline.

The reload sequence in `LiveGame`:

1. Stop the current simulation (halt all timers, clear state).
2. Create a new `Simulation` with the posted scripts and params.
3. Load the scripts into the sandbox.
4. If loading succeeds, start the game and return success.
5. If loading fails (syntax error, sandbox limit), return the error
   list and keep the previous simulation running.

**The editor is a separate page, not embedded in the simulator.**
The editor lives at `editor/index.html` and is served by the simulator
as a static page alongside the existing web view. Both pages share the
same origin (the simulator's HTTP server), so the editor can call
`/api/reload` and `/api/state` without CORS issues. A "Test" button
in the editor opens the simulator view in a new tab or an iframe.

The simulator's `WebServer` is extended to serve files from both
`atalaia_sim/web/` (existing simulator UI) and `editor/` (new editor
UI). The URL structure:

| Path | Serves |
|------|--------|
| `/` | Simulator web view (existing) |
| `/editor/` | Blockly editor page |
| `/api/state` | Existing game state API |
| `/api/action` | Existing action API |
| `/api/reload` | New: reload mode from posted Lua |

**Consequences:**
- A single HTTP server (the simulator's `WebServer`) serves both UIs.
  No additional process or port is needed.
- The REST approach is stateless: the editor does not need to maintain
  a persistent connection. Refreshing the editor page does not break
  anything.
- Hot-reload latency is dominated by the Lua load time (~10 ms for a
  typical mode). The GM sees the result immediately.
- The simulator's existing `/api/state` endpoint provides all the state
  the editor needs for a live preview. No new state-streaming mechanism
  is required.
- WebSocket live updates (showing events as they fire) can be added
  later without changing the reload mechanism.

---

### ADR-P5-3: Mode registry hosting and index format

**Status:** Accepted

**Context:** Design-spec.md section 13 describes a Git-based registry:
"an index repository listing each mode's id, versions, hashes, licence,
required capabilities and the author's signature." The registry must
work offline (the controller caches the index) and be maintainable with
standard Git and GitHub workflows.

**Decision:**

**GitHub Releases for packages, GitHub Pages for the index.**

The registry is a separate GitHub repository
(`atalaia-project/atalaia-modes`). It contains:

1. **The index file** (`index.json`): a JSON file listing every
   registered mode with its versions, hashes, signatures, and download
   URLs. Published to GitHub Pages so the controller can fetch it as a
   static file.
2. **Author public keys** (`keys/<author>.pub`): Ed25519 public keys,
   one per author, submitted via PR.
3. **A revocation list** (`keys/revoked.json`): revoked key
   fingerprints with revocation timestamps.
4. **CI configuration** (`.github/workflows/registry.yml`): validates
   submissions, runs mode tests, verifies signatures.

Mode packages themselves are tarballs (`.tar.gz` of the mode directory)
hosted as GitHub Release assets on the mode's own repository, or on the
registry repository for authors who do not maintain a separate repo.
The index entry points to the download URL.

**Index format** (`index.json`):

```json
{
  "schema_version": 1,
  "generated_at": "2026-10-18T00:00:00Z",
  "modes": [
    {
      "id": "org.atalaia.bomb",
      "name": "Bomb / Rush",
      "description": "Arm and defend, or defuse before the fuse runs out.",
      "author": "atalaia-project",
      "author_key_fingerprint": "SHA256:...",
      "homepage": "https://github.com/atalaia-project/atalaia-project",
      "versions": [
        {
          "version": "1.2.0",
          "min_core": "0.4.0",
          "min_tier": "reduced",
          "license": "GPL-3.0-or-later",
          "sha256": "a1b2c3...",
          "signature": "ed25519:...",
          "url": "https://github.com/.../releases/download/v1.2.0/bomb-1.2.0.tar.gz",
          "size_bytes": 4096,
          "verified": true,
          "verified_at": "2026-10-18T00:00:00Z"
        }
      ]
    }
  ]
}
```

Key fields:

- `schema_version`: integer, incremented on breaking changes to the
  index format. The controller rejects indices with an unknown schema
  version and keeps its cached copy.
- `author_key_fingerprint`: the SHA-256 fingerprint of the author's
  Ed25519 public key in `keys/`. Links the index entry to the key file.
- `sha256`: hex-encoded SHA-256 of the tarball. The controller verifies
  this after downloading.
- `signature`: the Ed25519 signature of the `sha256` value, hex-encoded.
  The controller verifies this against the author's public key.
- `verified`: true only if the mode passed CI tests and a maintainer
  review. Set by the registry CI, not by the author.
- `size_bytes`: total tarball size. The controller enforces a per-mode
  size limit (default 1 MB) and skips packages that exceed it.
- `min_core`: the minimum core API version. The controller compares
  this against its own core version and does not install modes that
  require a newer core.

**Package format:** A tarball of the mode directory, preserving the
standard layout (`mode.yaml`, `node.lua`, optional `field.lua`,
`assets/`, `i18n/`, `tests/`). The tarball root is the mode id
(e.g., `org.atalaia.bomb/mode.yaml`). No additional metadata files
inside the tarball; all registry metadata lives in the index.

**Controller sync workflow:**

1. Fetch `index.json` from the Pages URL (HTTPS, with ETag caching).
2. Compare against the cached index; identify new or updated modes.
3. For each new/updated mode, download the tarball from the `url`.
4. Verify the SHA-256 hash.
5. Verify the Ed25519 signature against the author's public key.
6. Check the revocation list for the author's key.
7. If all checks pass, install the mode in the local mode store.
8. On failure, log the error and skip the mode.

The controller caches both the index and all installed packages for
offline use. Modes are pushed to nodes over Wi-Fi or BLE during join
(design-spec.md section 10).

**Consequences:**
- GitHub Pages provides free, reliable HTTPS hosting for the index with
  global CDN. No custom server infrastructure is needed.
- GitHub Releases provides unlimited storage for release assets (mode
  tarballs) on public repositories.
- A separate repository for the registry keeps mode submissions out of
  the main project's PR queue and issue tracker.
- The JSON index is easy to parse on every platform (Python on the
  controller, C/JSON on ESP32 if needed, Dart on Android).
- Schema versioning prevents a controller from misinterpreting a
  newer index format. The controller is conservative: unknown schema
  version means keep the cached copy.
- The 1 MB per-mode size limit prevents the registry from becoming a
  file-hosting service. Sound assets are the largest component; modes
  with many audio clips may need to reference external downloads.
- Mode packages hosted on GitHub Releases get the same availability
  and CDN as the index. Authors with their own repositories can host
  releases there.

---

### ADR-P5-4: Mode signing scheme

**Status:** Accepted

**Context:** Design-spec.md section 14: "Packages are signed by their
author; the controller shows who signed a mode before installing it."
The firmware uses Ed25519 for image signing (design-spec.md section 13).
The registry needs a signing scheme that is consistent with the firmware,
simple enough for community authors to use, and supports key revocation.

**Decision:**

**Ed25519 signatures on the tarball SHA-256.**

Each mode author generates an Ed25519 keypair using a provided CLI tool
(`registry/tools/keygen.py`) or any standard tool (`ssh-keygen -t ed25519`,
`openssl genpkey`). The tool outputs:

- A private key file (`<author>.key`) that the author keeps locally.
  Never committed to any repository.
- A public key file (`<author>.pub`) that the author submits to the
  registry repository via PR, placed in `keys/<author>.pub`.

**Signing workflow** (author-side):

1. Build the mode package: `tar czf bomb-1.2.0.tar.gz org.atalaia.bomb/`
2. Compute the SHA-256: `sha256sum bomb-1.2.0.tar.gz`
3. Sign the SHA-256 hex string with the private key:
   `registry/tools/sign.py --key author.key --hash <sha256>`
4. Submit a PR to the registry repository with the updated `index.json`
   entry containing the new version, SHA-256, and signature.

**Verification workflow** (controller-side):

1. Look up the author's public key by `author_key_fingerprint` in
   the index.
2. Check that the key is not in the revocation list (`keys/revoked.json`).
3. Verify the Ed25519 signature of the `sha256` string against the
   public key.
4. Verify that the downloaded tarball's SHA-256 matches the `sha256`
   in the index.
5. If any check fails, reject the package and log the failure.

**Signature scope:** The signature covers the hex-encoded SHA-256 of
the tarball, not the tarball contents directly. This means:
- The signature is computed over a short, fixed-length string (64 hex
  characters), making the signing operation trivial.
- The SHA-256 is independently verifiable: the controller can check the
  hash without the author's key, and then check the signature of the
  hash.
- Re-signing does not require the original tarball, only the hash.

**Key revocation:**

`keys/revoked.json` is a JSON array of revocation entries:

```json
[
  {
    "fingerprint": "SHA256:...",
    "author": "compromised-author",
    "revoked_at": "2026-10-18T00:00:00Z",
    "reason": "Key compromise reported by author"
  }
]
```

The controller fetches this file alongside the index. A revoked key
means:
- No new packages signed by that key are accepted.
- Existing installed packages signed by that key are flagged with a
  warning in the GM console, but NOT automatically removed (to avoid
  disrupting a game in progress).
- The author must generate a new keypair and re-sign their packages.

Revocation is performed by a project maintainer via a PR to the registry
repository. The author can request revocation by opening an issue.

**Key fingerprint:** The SHA-256 hash of the public key bytes, encoded
as `SHA256:<base64>`. This is the same format used by SSH.

**Consequences:**
- Ed25519 is consistent with the firmware signing scheme (design-spec.md
  section 13) and is widely supported by standard tools.
- The signing workflow requires only Python and the `cryptography`
  library (already a project dependency), or standard CLI tools.
- Key revocation is explicit and auditable (PRs to the registry repo).
  There is no automatic key rotation.
- A compromised key affects only the compromised author's packages.
  Other authors' packages remain valid.
- The controller shows the author name and verified badge before
  installing a mode, giving the GM visibility into what they are
  loading.
- The scheme does not prevent a legitimate author from signing a
  malicious mode. The sandbox (core/README.md) is the primary defence
  against malicious scripts; signing provides attribution, not safety.

---

### ADR-P5-5: Approved licence list for community modes

**Status:** Accepted

**Context:** Design-spec.md section 17: "Community modes: Author's
choice from an approved list." The registry CI checks the `license`
field in `mode.yaml` against this list. The list must include only
licences that are compatible with the project's GPL-3.0-or-later
built-in modes and that keep the registry open.

**Decision:**

The approved SPDX licence identifiers for community modes are:

| SPDX identifier | Type | Notes |
|-----------------|------|-------|
| `GPL-3.0-or-later` | Copyleft | Same as built-in modes. Recommended default. |
| `LGPL-3.0-or-later` | Weak copyleft | For authors who want to allow proprietary modifications to non-mode code that imports mode assets. |
| `MIT` | Permissive | Widely used, simple terms. |
| `Apache-2.0` | Permissive | Includes patent grant; common in enterprise contributions. |
| `BSD-2-Clause` | Permissive | Minimal terms. |
| `BSD-3-Clause` | Permissive | Adds non-endorsement clause. |
| `CC0-1.0` | Public domain dedication | For trivial modes and examples. |

**Criteria for inclusion:**
- Must be OSI-approved or FSF-approved as a free software licence, or
  a widely-accepted public domain dedication.
- Must be compatible with redistribution alongside GPL-3.0-or-later
  code (the built-in modes and the core). All listed licences satisfy
  this.
- Must not include a noncommercial clause. Licences like
  CC BY-NC or PolyForm Noncommercial are explicitly excluded because
  they would prevent fields (which are businesses) from using those
  modes.

**Enforcement:** The registry CI (`registry-lint` job) validates the
`license` field in `mode.yaml` against this list. Submissions with
an unlisted licence are rejected with a clear error message listing
the approved options. The `mode.yaml` field uses a single SPDX
identifier, not an SPDX expression (no `AND`/`OR`).

**Adding a new licence:** Requires an RFC (per CONTRIBUTING.md) with
justification that the licence meets the criteria above.

**Consequences:**
- The approved list covers the most common open-source licences. An
  author who wants to share a mode has a clear, short list to choose
  from.
- Permissive licences (MIT, Apache-2.0, BSD) are included because
  some authors prefer them, and they do not conflict with the project's
  copyleft philosophy.
- CC0-1.0 is included for trivial examples and templates, even though
  it is not technically a "licence" but a public domain dedication.
- The explicit exclusion of noncommercial licences is consistent with
  the design-spec.md section 17 rationale: "Licences that forbid
  commercial use are not open source."
- The list can be expanded through the RFC process, but the bar is
  high: a new licence must meet all three criteria and have a clear
  use case not covered by the existing options.

---

### ADR-P5-6: Carrier PCB scope and timing

**Status:** Accepted

**Context:** The Field Box (hardware/field-box/README.md) is currently
built by hand-wiring modules to the Heltec WiFi LoRa 32 V4.3 on a
perfboard. Design-spec.md section 18 lists "Carrier PCB timing" as an
open question, deferred to be decided later. The carrier PCB would
replace the perfboard with a purpose-built board that routes all signals
to labelled connectors. The research identifies that the PCB depends on
validated pin assignments from phase 1 hardware bring-up.

**Decision:**

**The carrier PCB is deferred until at least 3 Field Box prototypes
have been built and tested on perfboard in phase 1.** The PCB design
begins only after the following gates are met:

1. **Pin assignments validated**: the GPIO assignments in
   `hardware/field-box/README.md` and `firmware/esp32/main/Kconfig.projbuild`
   have been confirmed on physical hardware.
2. **I2C bus stability**: all four I2C devices (OLED, PCF8574, PN532,
   MAX17048) coexist reliably on one bus at the assigned addresses.
3. **Physical fit**: the board and module layout fits inside the
   reference IP65 enclosure (~200 x 150 x 100 mm).

**PCB scope -- what it includes:**

| Feature | Detail |
|---------|--------|
| Heltec V4.3 header sockets | Pin headers or castellated pads for the main board |
| I2C bus routing | Labelled JST connectors for PCF8574, PN532, MAX17048, OLED |
| SPI bus routing | Labelled connector for the display (MOSI, CLK, CS, DC, RST, BL) |
| I2S routing | Labelled connector for the MAX98357A (BCLK, LRCLK, DOUT) |
| GPIO breakout | Labelled screw terminals or JST for team buttons (GPIO 4, 5, 33, 34) |
| WS2812B level shifter | 3.3V-to-5V level shifter for the LED data line (GPIO 48) |
| M12 addon bus | GND, 5V, SDA, SCL, INT (design-spec.md section 6) |
| Power management | USB-C PD input pads, BMS connector, power switch pads |
| Mounting holes | 4x M3, matching the reference enclosure standoffs |

**PCB scope -- what stays off-board (as separate modules):**

| Module | Reason |
|--------|--------|
| Heltec V4.3 itself | It is the main board, not a component on the carrier |
| PN532 NFC reader | Positioning depends on the enclosure; connected via I2C cable |
| MAX98357A + speaker | Acoustic placement varies; connected via I2S cable |
| Team buttons | Mounted in enclosure cutouts; connected via screw terminals |
| Keypad | Mounted externally; connected via I2C through the PCF8574 |
| Display | Mounting position varies; connected via SPI flat cable |
| LED ring | Mounted externally; single data wire via level shifter |
| Battery pack | External; connected via JST to BMS connector |

**Design tool and licence:**

- **KiCad** (open-source EDA, version 8.x).
- **CERN-OHL-S-2.0** licence, per `REUSE.toml` (`hardware/**`).
- Design files live in `hardware/field-box/pcb/`: schematic (`.kicad_sch`),
  PCB layout (`.kicad_pcb`), BOM (`.csv`), Gerbers (`gerber/`).

**CI:** When the PCB design exists, a CI job runs KiCad DRC (Design
Rule Check) and ERC (Electrical Rules Check) on every PR that touches
`hardware/field-box/pcb/`. The job uses the `kicad/kicad:8.0` Docker
image and `kicad-cli`.

**Consequences:**
- The PCB cannot block any phase 5 software deliverable. The editor,
  registry, i18n and community processes proceed independently.
- Deferring the PCB until phase 1 hardware is validated avoids layout
  rework. The pin assignments in `Kconfig.projbuild` are the single
  source of truth; the PCB routes to those pins.
- The level shifter for WS2812B is on-board because it is universal
  (every Field Box with an LED ring needs it) and small enough to not
  affect layout.
- The M12 addon bus connector is included because it is part of the
  reference design (design-spec.md section 6) and would be hard to add
  later as a daughter board.
- Modules that depend on enclosure geometry (NFC, speaker, buttons,
  display) stay off-board. This keeps the carrier PCB compatible with
  different enclosure sizes and layouts.
- Community contributors can order the PCB from any fabricator using
  the Gerbers; KiCad is free and cross-platform for modifications.

---

### ADR-P5-7: i18n architecture for the full platform

**Status:** Accepted

**Context:** The project site already uses a YAML-keyed i18n workflow
(`site/i18n/en.yaml`, `site/i18n/pt.yaml`, `tools/build_site.py`) with
CI completeness checks. Design-spec.md section 12: "English and
Portuguese ship first." Phase 5 expands i18n to the editor, mode
strings, and firmware screen strings. The ESP32-S3 has limited
resources (2 MB PSRAM) and cannot load large locale bundles.

**Decision:**

**Unified YAML-keyed approach across all components.** Every
translatable string in the platform is identified by a dot-separated
key and stored in per-language YAML files. The build tooling converts
YAML to the format each component needs.

**Four i18n domains and their file locations:**

| Domain | Source files | Build output | Runtime |
|--------|------------|-------------|---------|
| Site | `site/i18n/<lang>.yaml` | HTML pages via `build_site.py` | Static HTML per language |
| Editor | `editor/i18n/<lang>.yaml` | JSON via `build_editor_i18n.py` | Blockly `Msg` overrides loaded at init |
| Modes | `modes/<mode>/i18n/<lang>.yaml` | Included in mode tarball | Read by controller/GM console for display |
| Firmware | `firmware/esp32/i18n/<lang>.yaml` | C header via `build_firmware_i18n.py` | Compiled into firmware, selected at boot |

**Key naming convention:** `<domain>.<area>.<key>`, for example:
- `editor.blocks.when_team_claims`: "When a team claims this box"
- `editor.categories.events`: "Events"
- `mode.bomb.name`: "Bomb / Rush"
- `firmware.screen.idle_title`: "Ready"

**Editor i18n:**

The editor's YAML files contain block labels, tooltips, category names,
help text and error messages. A build script (`tools/build_editor_i18n.py`)
converts each YAML file to a JSON file that the editor loads at init
via Blockly's `Msg` override mechanism:

```javascript
// editor/i18n/en.json (generated from editor/i18n/en.yaml)
Blockly.Msg['ATALAIA_WHEN_TEAM_CLAIMS'] = 'When a team claims this box';
Blockly.Msg['ATALAIA_EVERY_N_SECONDS'] = 'every %1 seconds do';
```

The editor detects the browser's language and falls back to English.

**Mode i18n:**

Each mode's `i18n/<lang>.yaml` contains translated mode name,
description, parameter labels, and screen template text. The GM
console reads these when displaying mode information. The simulator
uses the English fallback.

**Firmware i18n:**

The firmware's 12 LVGL screen templates contain hard-coded English
text. A build script (`tools/build_firmware_i18n.py`) reads
`firmware/esp32/i18n/<lang>.yaml` and generates a C header with a
string table:

```c
// firmware/esp32/main/i18n/strings_pt.h (generated)
#define I18N_IDLE_TITLE    "Pronto"
#define I18N_GAME_RUNNING  "Jogo em curso"
#define I18N_BATTERY_LOW   "Bateria fraca"
```

The active locale is selected at boot from the node's stored
configuration (set during first-time Wi-Fi setup). Only one locale
is compiled into each firmware image to conserve flash. A node that
needs a different locale must be reflashed, or (future improvement)
the locale table can be stored in a filesystem partition and loaded
at boot.

**ESP32 resource constraints:** A full locale table for 12 screen
templates is approximately 2-4 KB of string data. This fits easily
in flash. PSRAM is not needed for i18n strings.

**CI completeness check:**

A CI job (`i18n-check`) validates all four domains:

1. For each domain, load all `<lang>.yaml` files.
2. Verify that every key in the English file exists in every other
   language file.
3. Verify that no extra keys exist in non-English files (prevents
   orphaned translations).
4. Verify that every key in the English file is referenced by the
   corresponding template/code (prevents unused keys).

This extends the existing `build_site.py --check` to cover all domains.

**Adding a new language:**

1. Copy `en.yaml` to `<lang>.yaml` in each domain that the contributor
   wants to translate.
2. Translate every key.
3. Run `tools/build_site.py` (for site), `tools/build_editor_i18n.py`
   (for editor), or `tools/build_firmware_i18n.py` (for firmware).
4. Open a PR. CI validates completeness.

Partial translations are accepted for modes and the editor (untranslated
keys fall back to English) but NOT for the site (every key must be
present in every language file, as enforced by the existing CI check).

**Consequences:**
- YAML as the single source format means translators only learn one
  format, regardless of which component they translate.
- The build scripts are thin converters (YAML to JSON, YAML to C
  header). They do not introduce new dependencies beyond PyYAML.
- Firmware i18n is compile-time, not runtime. This uses the least
  flash and RAM but requires a reflash to change the locale. This is
  acceptable for v1; a future improvement could load locale files from
  a SPIFFS/LittleFS partition.
- The English fallback for modes and the editor means a partially
  translated mode is still usable, just not fully localized.
- The CI completeness check prevents key drift across locales, which
  the research identified as a medium-likelihood risk.
- The Portuguese terminology table in `site/README.md` applies to all
  domains: translators should consult it for consistent Portuguese
  terms across the platform.

---

### ADR-P5-8: Community mode review and governance process

**Status:** Accepted

**Context:** CONTRIBUTING.md describes the existing governance: DCO
sign-off, clean-room policy, RFC process for protocol/API changes.
Phase 5 adds a mode registry where community authors submit modes for
inclusion. The registry needs a review process that balances quality
(sandbox compliance, tests, licence) with accessibility (a community
author should not need deep C or protocol knowledge to submit a mode).
Design-spec.md section 13 describes the "verified badge" as requiring
CI tests and a maintainer review.

**Decision:**

**PR-based curation with a structured review checklist.**

Mode submission follows a fork-and-PR workflow on the registry
repository (`atalaia-project/atalaia-modes`):

1. **Author prepares the mode**: writes `mode.yaml`, `node.lua`,
   optional `field.lua`, `assets/`, `i18n/`, and `tests/`.
2. **Author signs the package**: generates the tarball, computes
   SHA-256, signs with their Ed25519 key (see ADR-P5-4).
3. **Author opens a PR** to the registry repository, adding their
   mode entry to `index.json` and (if new) their public key to
   `keys/`.
4. **Registry CI runs automatically**:
   - `registry-lint`: validates `mode.yaml` schema, checks `license`
     against the approved list (ADR-P5-5), checks tarball size (max
     1 MB), verifies the Ed25519 signature.
   - `registry-test`: unpacks the tarball and runs
     `python -m atalaia_sim test <mode>` against the mode's `tests/`.
   - `sandbox-escape`: runs the mode against a battery of known Lua
     sandbox escape patterns (attempts to access `io`, `os`, `require`,
     `load`, `loadfile`, `dofile`, `debug` library).
5. **A project maintainer reviews the PR** using the review checklist
   (below).
6. **On approval**, the maintainer merges the PR. The CI rebuilds the
   index and publishes it to GitHub Pages. The mode is now available
   to controllers that sync the index.

**Review checklist** (used by maintainers on every mode submission PR):

| # | Check | Automated? |
|---|-------|-----------|
| 1 | `mode.yaml` schema is valid (id, version, license, roles, params) | Yes (CI) |
| 2 | `license` is in the approved list (ADR-P5-5) | Yes (CI) |
| 3 | All source files have SPDX headers matching the declared licence | Yes (CI, `reuse lint`) |
| 4 | `tests/` exist and pass in the simulator | Yes (CI) |
| 5 | No `io`, `os`, `require`, `load`, `debug` usage (sandbox compliance) | Yes (CI) |
| 6 | No hardcoded team names, node counts, or language strings outside `i18n/` | Manual |
| 7 | `params` have reasonable defaults, min/max bounds, and labels | Manual |
| 8 | Event types follow naming: standard events for standard types, `x.<author>.<name>` for custom | Manual |
| 9 | `assets/` total size is reasonable (under 512 KB for sounds, images) | Yes (CI) |
| 10 | No offensive, misleading, or trademarked content in mode name, description, or assets | Manual |
| 11 | If `i18n/` is present, English keys exist; other languages are optional | Yes (CI) |
| 12 | Ed25519 signature is valid and the key is not revoked | Yes (CI) |

**Verified badge criteria:**

A mode receives the `"verified": true` flag in the index when ALL of
the following are met:

1. All 12 checklist items pass.
2. The mode's `tests/` demonstrate meaningful coverage (not just a
   single trivial test).
3. A project maintainer has reviewed the Lua code and confirmed it
   follows the script API correctly.

Unverified modes are still listed in the index and installable, but
the controller displays a warning: "This mode has not been reviewed by
the project maintainers."

**RFC requirements for phase 5 changes:**

The following changes to registry infrastructure require an RFC (per
the existing process in CONTRIBUTING.md):

- Changes to the index `schema_version` (breaking format change).
- Changes to the signing algorithm (replacing Ed25519).
- Changes to the approved licence list (adding or removing a licence).
- Changes to the sandbox limits that affect mode compatibility.

Changes that do NOT require an RFC:

- Adding new review checklist items.
- Adding new CI checks.
- Updating the Blockly version (goes through a normal PR with tests).
- Adding new editor blocks for an existing API function.

**Mode updates:**

An author updates their mode by submitting a new PR with the updated
index entry (new version, new hash, new signature). The same review
process applies. The registry preserves all previous versions in the
index; the controller shows the latest version by default but can
install older versions.

**Consequences:**
- PR-based curation prevents typosquatting and spam. Every mode is
  reviewed before it appears in the index.
- Automated CI handles the mechanical checks (signature, licence,
  tests, sandbox). Maintainers focus on code quality and gameplay
  review.
- The verified badge is a quality signal, not a gate. Unverified modes
  are still available, giving new authors a path to publish while they
  work toward verification.
- The review process adds latency to mode publication (a maintainer
  must review each PR). This is acceptable for a curated registry;
  an open-publish model would not provide the same quality guarantees.
- The RFC requirement for signing and format changes ensures stability
  for controller implementations that parse the index.
- CONTRIBUTING.md must be updated to document the mode submission
  process, linking to the registry repository and the review checklist.
