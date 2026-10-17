# Atalaia

**The open force-on-force platform.**

Atalaia is an open, local-first platform for airsoft, paintball and milsim game props. Build a domination box from a €20 microcontroller, turn an old Android phone into a hacking terminal, run a 20-box weekend milsim on a LoRa mesh, and write your own game modes as small scripts. No cloud required, no vendor lock-in.

> **Status: pre-alpha, design phase.** Nothing here is ready for the field yet. We are in phase 0: setting up the repository, the shared core and the simulator. Ideas, reviews and early contributors are very welcome.

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
| [`simulator/`](simulator/) | Desktop simulator with virtual nodes | GPL-3.0-or-later |
| [`hardware/`](hardware/) | Reference builds: wiring, bills of materials, enclosures | CERN-OHL-S-2.0 |
| [`docs/`](docs/) | Design spec, RFCs, guides | CC-BY-SA-4.0 |
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

There is nothing to flash yet. If you want to build the core skeleton and run its tests:

```sh
cmake -S core -B build
cmake --build build
ctest --test-dir build --output-on-failure
```

You need a C11 compiler and CMake 3.16 or newer.

## Contributing

Atalaia is built by players, field owners and makers. You can help by:

- reviewing the [design specification](docs/design-spec.md) and opening issues,
- proposing game modes with the **Game mode idea** issue template,
- writing code for any phase-0 task,
- sharing how your field plays, so the defaults fit real games.

Please read [CONTRIBUTING.md](CONTRIBUTING.md) first. Every commit needs a `Signed-off-by` line (`git commit -s`), and we follow a strict clean-room policy: no code, firmware, manuals, sounds or images from any commercial product.

## Safety

Atalaia props are game equipment. Make them look like game props: bright colours, clear "GAME PROP" labels, and nothing resembling a real explosive device. Transport them in labelled cases, never leave them unattended outside the field, and treat lithium batteries with care. The [design specification](docs/design-spec.md) covers field safety and radio regulations in more detail.

## Name

"Atalaia" is Portuguese for *watchtower*. Forks are welcome under the licence, but please give your fork its own name so players can tell it apart from the original project.

## Licence

Atalaia is free software. The core, firmware, app and modes are licensed under the [GNU GPL v3 or later](LICENSES/GPL-3.0-or-later.txt); the field controller and site server under the [GNU AGPL v3 or later](LICENSES/AGPL-3.0-or-later.txt); hardware designs under [CERN-OHL-S-2.0](LICENSES/CERN-OHL-S-2.0.txt); documentation under [CC BY-SA 4.0](LICENSES/CC-BY-SA-4.0.txt). See [LICENSING.md](LICENSING.md).
