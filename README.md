<p align="center">
  <img src="site/img/logo-512.png" width="160" height="160" alt="The Atalaia badge: three watchtowers on sand dunes, with signal fires on their tops joined by an arc, above the word ATALAIA">
</p>

# Atalaia

[![CI](https://github.com/vakaobr/atalaia-project/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/vakaobr/atalaia-project/actions/workflows/ci.yml)
[![Project page](https://github.com/vakaobr/atalaia-project/actions/workflows/pages.yml/badge.svg?branch=main)](https://github.com/vakaobr/atalaia-project/actions/workflows/pages.yml)
[![Licence: GPL-3.0-or-later](https://img.shields.io/badge/licence-GPL--3.0--or--later-blue)](LICENSING.md)
[![REUSE compliant](https://img.shields.io/badge/REUSE-compliant-green)](https://reuse.software/)
[![Status: pre-alpha](https://img.shields.io/badge/status-pre--alpha-orange)](#roadmap)
[![Discussions](https://img.shields.io/github/discussions/vakaobr/atalaia-project?label=discussions)](https://github.com/vakaobr/atalaia-project/discussions)

**The open force-on-force platform.** Project page: [Português](https://vakaobr.github.io/atalaia-project/) · [English](https://vakaobr.github.io/atalaia-project/en/)

![Illustration: at dusk, a stone watchtower on a hilltop carries a radio box whose signals reach glowing orange GAME PROP boxes spread across a forested valley, while a group of players walks past them. Painted text reads "Open-source project ATALAIA".](site/img/watchtower-night-1600.jpg)

Atalaia is an open, local-first platform for airsoft, paintball and milsim game props. Build a domination box from a €20 microcontroller, turn an old Android phone into a hacking terminal, run a 20-box weekend milsim on a LoRa mesh, and write your own game modes as small scripts. No cloud required, no vendor lock-in.

*Atalaia* is Portuguese for "watchtower" ([why that name?](#name)).

> **Status: pre-alpha.** Nothing here is ready for the field yet. Phase 0 is complete: the shared core, its Lua sandbox, the Skirmesh-RF event codec and a browser-based simulator run Domination and Bomb. Phase 1 software is done: the Field Box firmware, its screens and an emulator setup that plays a game on a simulated box; the final gate — a 2-hour club game on real hardware — awaits prototype parts. Phase 2 (the field network) is in progress: the encrypted Skirmesh-RF radio protocol, the multi-box simulator, the firmware radio driver, the field controller (REST, WebSocket and MQTT APIs, game log, controller failover) and the USB radio modem firmware are built and tested in Docker, against the modem's real code and a real MQTT broker; the GM console comes next, and none of it has run on radio hardware yet. Ideas, reviews and early contributors are very welcome.

---

## Why Atalaia

Electronic game props add a lot to a game, but commercial systems keep the rules locked inside closed firmware. Every new game mode waits on the vendor, there is no public API, and you cannot add your own hardware.

Atalaia takes a different approach:

- **Local-first.** Every game runs fully offline, from a single house to a multi-kilometre forest. The internet is optional.
- **Any hardware.** ESP32 boards, Raspberry Pi, Arduino-class boards and new or repurposed Android phones all work in the same game.
- **Game modes are scripts.** Modes are short Lua scripts with a settings file. Change or share a mode without reflashing anything.
- **Open protocol and API.** Props talk over the documented **Skirmesh-RF** protocol, and the field controller exposes MQTT, REST and WebSocket APIs for scoreboards, overlays and your own tools.
- **Built for players and fields.** A player app with roles (player, squad leader, VIP, marshal, GM), squads, custom scenarios, and a chrono registry with spot checks to catch power changes after check-in.
- **Copyleft.** Anyone can use Atalaia, including fields that charge entry fees and makers who sell boxes. Anyone who distributes or hosts a modified version must share their changes.

## How it fits together

```
                 Site server (optional)
           accounts · history · player app · chrono
                         │ internet
 GM & player apps ── Field controller ── Scoreboards, ATAK, webhooks
     (Wi-Fi)        Raspberry Pi / Android      (MQTT, REST)
                         │
                 Skirmesh-RF (LoRa mesh)
       ┌──────────┬──────┴──────┬──────────────┐
   Field Box   Satellite   Android prop     Thin node
    (ESP32)     (ESP32)    (+ ESP32 pod)    (Arduino)
```

Every full node runs the same C11 core and the same Lua game modes; only the platform shell and hardware drivers differ. The complete design is in the [design specification](docs/design-spec.md).

## Repository layout

| Folder | What lives there | Licence |
| --- | --- | --- |
| [`core/`](core/) | Shared C11 core: event bus, state store, Lua sandbox, protocol codec | GPL-3.0-or-later |
| [`protocol/`](protocol/) | Skirmesh-RF message and event schemas | GPL-3.0-or-later |
| [`modes/`](modes/) | Built-in game modes (Lua + manifest) | GPL-3.0-or-later |
| [`firmware/`](firmware/) | ESP32 firmware (ESP-IDF) and Arduino thin-node firmware | GPL-3.0-or-later |
| [`app/`](app/) | Flutter app for Android and iOS: props, controller, player roles | GPL-3.0-or-later + app-store permission |
| [`controller/`](controller/) | Field controller and GM console | AGPL-3.0-or-later |
| [`server/`](server/) | Optional site server | AGPL-3.0-or-later |
| [`simulator/`](simulator/) | Desktop simulator with virtual nodes and a web view | GPL-3.0-or-later |
| [`hardware/`](hardware/) | Reference builds: wiring, bills of materials, enclosures | CERN-OHL-S-2.0 |
| [`docs/`](docs/) | Design spec, RFCs, guides | CC-BY-SA-4.0 |
| [`site/`](site/) | The project page in Portuguese and English, published to [GitHub Pages](https://vakaobr.github.io/atalaia-project/) | CC-BY-SA-4.0 |
| [`tools/`](tools/) | Developer scripts | GPL-3.0-or-later |

See [LICENSING.md](LICENSING.md) for the details.

## Roadmap

| Phase | Focus | Done when |
| --- | --- | --- |
| 0 · Foundations | Repository, licences, shared core skeleton, Lua sandbox, simulator | The simulator runs Domination and Bomb from Lua scripts |
| 1 · Single box | Field Box build, ESP32 firmware, on-device presets | One box runs a 2-hour club game with no restarts |
| 2 · Field network | Skirmesh-RF over LoRa, field controller, API, GM console | 5 boxes on a CQB site and an outdoor field, zero lost captures |
| 3 · Android and players | Android props, I/O pod, player app with roles, chrono check-in | One game mixes ESP32 and Android props without issues |
| 4 · Site server and advanced play | Site server, custom scenarios, advanced modes, ATAK | A weekend milsim runs on Atalaia end to end |
| 5 · Community | Visual mode editor, mode registry, carrier PCB, translations | Ongoing |

## Getting started

**Run the simulator** (no hardware needed). Build the core and run its tests and every mode's tests:

```sh
sh tools/check.sh
```

You need a C11 compiler, CMake 3.16 or newer, Python 3.10 or newer and PyYAML. No compiler? Use the [dev container](tools/README.md). To play a mode in your browser, holding team buttons and watching the props' screens and the event log, see the [simulator](simulator/README.md#play-a-mode-in-the-browser). To write a mode, start with [modes/README.md](modes/README.md).

**Build the Field Box firmware** (cross-compiles in Docker, no toolchain needed locally; works from `cmd`, PowerShell or bash):

```sh
python tools/docker_fw.py build    # the firmware, in firmware/esp32/build/
python tools/docker_fw.py test     # its host tests and screen reference images
python tools/docker_fw.py wokwi    # the variant for the Wokwi emulator
```

To play a game on an emulated Field Box in VS Code before any hardware exists, see [firmware/esp32/docs/WOKWI.md](firmware/esp32/docs/WOKWI.md). See [firmware/esp32/README.md](firmware/esp32/README.md) for the full build guide, Kconfig options, pin table, and bring-up checklist.

## Contributing

Atalaia is built by players, field owners and makers. You can help by:

- asking questions and sharing ideas in [Discussions](https://github.com/vakaobr/atalaia-project/discussions),
- reviewing the [design specification](docs/design-spec.md) and opening issues,
- proposing game modes with the **Game mode idea** issue template,
- writing code for any phase-0 task,
- sharing how your field plays, so the defaults fit real games.

Please read [CONTRIBUTING.md](CONTRIBUTING.md) first. Every commit needs a `Signed-off-by` line (`git commit -s`), and we follow a strict clean-room policy: no code, firmware, manuals, sounds or images from any commercial product.

## Safety

Atalaia props are game equipment. Make them look like game props: bright colours, clear "GAME PROP" labels, and nothing resembling a real explosive device. Transport them in labelled cases, never leave them unattended outside the field, and treat lithium batteries with care. The [design specification](docs/design-spec.md) covers field safety and radio regulations in more detail.

## Name

An *atalaia* (say "ah-tah-LYE-ah") is a watchtower: a lookout post on a hill or a stretch of coast whose crew watched for trouble and passed the warning along. The word came into Portuguese from the Arabic *aṭ-ṭalāʾiʿ*, "the scouts" or "the vanguard", and *estar de atalaia* still means "to be on the lookout". Atalaias are scattered across Portugal's coast and countryside, and several towns carry the name.

It turned out to be an accurate name for this project:

- **A field controller is a watchtower.** It sits somewhere high, sees every prop on the field, and tells the GM the moment something changes.
- **Watchtowers were local-first.** No tower ever waited for a cloud service. They worked with what was in sight.
- **They also ran the original low-bandwidth mesh.** Smoke by day, fire by night, relayed from tower to tower: tiny messages, long range, very little airtime, a limited number of hops, and nobody streaming video. Skirmesh-RF follows the same rules with LoRa and fewer burnt eyebrows.
- **The Arabic root means "the scouts".** That's a reasonable description of anyone who has ever played milsim.
- **It's a real word, not a product name.** Portuguese speakers can say it without trying, and everyone else gets to learn one new word.

Forks are welcome under the licence, but please give your fork its own name so players can tell it apart from the original project. Every watchtower needs its own hill.

## Licence

Atalaia is free software. The core, firmware, app and modes are licensed under the [GNU GPL v3 or later](LICENSES/GPL-3.0-or-later.txt); the field controller and site server under the [GNU AGPL v3 or later](LICENSES/AGPL-3.0-or-later.txt); hardware designs under [CERN-OHL-S-2.0](LICENSES/CERN-OHL-S-2.0.txt); documentation under [CC BY-SA 4.0](LICENSES/CC-BY-SA-4.0.txt). See [LICENSING.md](LICENSING.md).
