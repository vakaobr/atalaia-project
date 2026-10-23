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

**The open force-on-force platform.** Project page: [Português](https://atalaia-project.link/) · [English](https://atalaia-project.link/en/)

![Illustration: at dusk, a stone watchtower on a hilltop carries a radio box whose signals reach glowing orange GAME PROP boxes spread across a forested valley, while a group of players walks past them. Painted text reads "Open-source project ATALAIA".](site/img/watchtower-night-1600.jpg)

Atalaia is an open, local-first platform for airsoft, paintball and milsim game props. Build a domination box from a €20 microcontroller, turn an old Android phone into a hacking terminal, run a 20-box weekend milsim on a LoRa mesh, and write your own game modes as small scripts. No cloud required, no vendor lock-in.

*Atalaia* is Portuguese for "watchtower" ([why that name?](#name)).

> **Status: pre-alpha.** Nothing here is ready for the field yet. Phase 0 is complete: the shared core, its Lua sandbox, the Skirmesh-RF event codec and a browser-based simulator run Domination and Bomb. Phase 1 software is done: the Field Box firmware, its screens and an emulator setup that plays a game on a simulated box; the first Heltec V4.3 board has run it on the bench (boot, the radio's front end, two buttons, a Bomb game on the board's own small screen), and the final gate — a 2-hour club game in a built box — is still open. Phase 2 (the field network) has its network software built: the encrypted Skirmesh-RF radio protocol, the multi-box simulator, the field controller (REST, WebSocket and MQTT APIs, game log, controller failover), the USB radio modem firmware, the GM console with its scoreboard, the NFC and QR join flow, and the Field Box firmware talking the protocol (events, scores, commands, time sync, relaying). It is all tested in Docker, end to end: the controller with the modem's real code, the box's real game and radio code, a real MQTT broker and the console in a headless browser. On the bench (2026-10-21) two Heltec V4.3 boards exchange packets, and a box joined a game, was started and captured a zone through the field controller and its USB modem; the field test with five boxes (plan phase F) is still open. The phase's mode pack is written too: Hold-All Domination, Last Stand, per-team arming codes on Bomb and the Codes modifier, tested in the simulator, through the controller and on the host box. Phase 3 (Android and players) is well under way, in software, with nothing run on a real phone yet: three new modes that read players' signed NFC tags (Kill Confirmed, Respawn and Lives, Player Check-in) and the Medic Kit ("Ligaduras": a hit player scans their tag and holds a button to be healed, with limited heals per kit and per player, next to any game), the I/O pod (its link protocol and its firmware: a Heltec board that lends its buttons, keypad, lights, siren, NFC reader, enclosure switch and LoRa radio to a phone over USB or Bluetooth LE), and mode screens described in YAML that the Field Box draws; and the Android and iOS app (iOS is not built yet: it needs a Mac). The phone as the field controller has started: its game engine runs a mode's field.lua on the shared core and answers the Pi controller's REST API, live stream and MQTT topics, passing the same shared contract cases (no radio, check-in or screen yet). Its engine runs the shared core from Dart, each game node in its own background isolate, with every game mode's tests passing through it; its screens, in European Portuguese and English, turn an Android phone into a game prop that runs any mode and draws the mode's own screens, with big team buttons, a keypad and NFC tags; let a player follow a game from the field controller; give marshals the chrono check-in (energy, limit templates, spot checks, readings signed by the marshal), a replica registry and signed player tags; and open the GM console. Players check in at the field by scanning a printed poster, with no account and no internet, declare the replicas they will use and see their chrono state; marshals work from that "replicas to chrono" list and their signed readings mark each replica passed or refused; players can share their position during a game (the controller decides who sees it); and an Android prop takes part in the controller's game over the field's Wi-Fi, or over the field's radio through an I/O pod when there is no Wi-Fi (the app's tests talk to the pod firmware's own code run on a PC; no pod board has run it yet). A field or club running its own controller can brand it: its logo, wallpaper and colour in the app, the GM console, the scoreboard and the check-in poster, and team names and crests next to the team colours. CI and a local Android 16 emulator run the app. Phase 4 (site server and advanced play) has all 22 of its software plan phases built, in software (its hardware phases wait for the boards), among them its new modes, Master and Satellites (satellites held together with the master raise its points, and the master changing hands frees them) the logic of Target Windows (a target lights up in a random team's colour and a hit while it is lit scores for that team; the target addon itself is not built yet) the Hacking Terminal (a code to crack, wires to cut in the right order or a sequence to repeat on a box's keypad or a phone's; solving it can reveal a code and capture the terminal) and VIP / Payload (a team escorts its VIP, tracked by the app's position reports, or a phone with GPS to an extraction zone, past checkpoint boxes; positions stay on the controller and the phone), and an ATAK feed that puts the boxes on ATAK maps, with the field's safe zones, respawns, HQs and other map features (the field can be loaded from OpenStreetMap, over the open orthophoto of Portugal, Spain, France (overseas too), the Netherlands, Belgium, Luxembourg, Switzerland, eleven German states, Poland or Czechia, with its outline as the boundary, and players' phones warn them when they leave it), on the field's Wi-Fi and, through the site server with a certificate per device, for staff away from the field, in software and not yet on radio hardware or a phone in the field. Ideas, reviews and early contributors are very welcome.

---

## What it looks like

The eight captures below show the real Field Box firmware (ESP32, LVGL 9.2, 320×240 TFT) running in the Wokwi emulator. The box UI is in English. Not yet tested on physical hardware.

<table>
<tr>
<td align="center"><img src="site/img/screens/bomb-1-pin.png" width="240" alt="PIN entry screen"><br><em>Admin PIN entry</em></td>
<td align="center"><img src="site/img/screens/bomb-2-choose-game.png" width="240" alt="Game selection: Bomb / Domination"><br><em>Pick a game mode</em></td>
<td align="center"><img src="site/img/screens/bomb-3-confirm.png" width="240" alt="Start confirmation: Bomb, 10 min"><br><em>Confirm and start</em></td>
</tr>
<tr>
<td align="center"><img src="site/img/screens/bomb-4-standby.png" width="240" alt="Standby: hold to arm, RED"><br><em>Waiting for red team to arm</em></td>
<td align="center"><img src="site/img/screens/bomb-5-armed.png" width="240" alt="Armed: 5:00 countdown"><br><em>Bomb armed, 5-minute fuse</em></td>
<td align="center"><img src="site/img/screens/bomb-6-defused.png" width="240" alt="Defused: BLUE team wins"><br><em>Blue defused in time</em></td>
</tr>
<tr>
<td align="center"><img src="site/img/screens/join-joined.png" width="240" alt="Joined game 4242, zone, node 7"><br><em>Joined a field game</em></td>
<td align="center"><img src="site/img/screens/codes-entry.png" width="240" alt="Code entry: two of four digits typed"><br><em>Typing a code (Codes modifier)</em></td>
<td align="center"><img src="hardware/field-box/wiring/field-box-wiring.png" width="240" alt="Field Box wiring diagram"><br><em><a href="hardware/field-box/BUILD.md">Build manual</a> wiring diagram</em></td>
</tr>
</table>

The Android app (phase 3, in Portuguese here) draws the same mode screens from the same YAML files. These are its test images, not photos of a phone: nothing has run on a real phone yet.

<table>
<tr>
<td align="center"><img src="site/img/screens/app-prop-game-pt.png" width="180" alt="An Android phone as the bomb: the mode's countdown screen (ARMED, 4:47 until detonation) above two big buttons, red and blue, to hold"><br><em>A phone as the bomb</em></td>
<td align="center"><img src="site/img/screens/app-player-pt.png" width="180" alt="The player's view: the game's name, 20:00 to go, the blue team's 20 points above the red team's 12, who holds each objective, and what happened"><br><em>Following the game</em></td>
<td align="center"><img src="site/img/screens/app-chrono-pt.png" width="180" alt="The marshal's chronograph: a replica checked in against the Portugal limits (marked unverified), the BB weight, a keypad for the velocity, and a green PASS"><br><em>Chrono check-in</em></td>
</tr>
</table>

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

## How the radio works

The props talk over LoRa, a long-range, low-power radio, in Atalaia's own protocol, Skirmesh-RF. None of it has been on a real field yet: range and timing will be measured in the phase 2 field test.

**What LoRa can do.** LoRa trades speed for reach: it gets short messages across a field on very little battery, and its signal gets through walls and trees better than Wi-Fi does, although concrete, metal and hills still block it. A box that cannot reach the controller is heard through the other boxes, and European rules limit how much of the time each device may transmit.

![How LoRa radio works, in five panels: chirps decoded below the noise; the spreading factor, where each step about doubles the time on air; range, longest over open ground and much shorter indoors or behind concrete, metal or a hill (design estimate 0.5–2 km outdoors, to be measured); boxes relaying for each other, at most twice by default; and the EU868 rules: one game channel at 869.525 MHz, up to 500 mW, at most 10% of the time.](site/img/diagrams/lora-wide-en.svg)

**Which channel, and why 869.525 MHz.** All of a game's traffic shares one channel. The default, 869.525 MHz, is the centre of 869.4–869.65 MHz, the only part of the European 868 MHz band where a device may transmit up to 10% of the time at up to 500 mW (ERP). Elsewhere in 868–870 MHz the rules allow 1% of the time (0.1% on 868.7–869.2 MHz) at 25 mW: about a tenth of the airtime, and much less range. 868.1, 868.3 and 868.5 MHz are LoRaWAN's default channels and often busy. The default is shared too: LoRaWAN gateways send some replies on 869.525 MHz, and Meshtastic's European default is the same frequency; nobody's packets are mistaken for anyone else's, but everyone nearby shares the airtime. So the GM chooses the field's channel in the GM console: keep 869.525 MHz, let the controller's USB modem listen to every legal channel for about a minute and suggest the quietest, draw one at random, or pick one by hand. The boxes and the modem then follow that channel's own power and duty-cycle limits, and a channel must fit inside one sub-band as a whole. Sources and details: [RFC 0001 Amendment 3](docs/rfcs/0001-skirmesh-rf-wire-format.md) (ERC Recommendation 70-03 Annex 1, ETSI EN 300 220-2, LoRaWAN Regional Parameters) and [controller/README.md](controller/README.md#the-fields-radio-channel).

**Radio regions: Europe and Taiwan.** A field is in one radio region, chosen once in the GM console (`[radio] region`). In Taiwan (AS923, 920–925 MHz) the NCC's rules (LP0002 5.8.1) give a single channel that does not hop full power only if it is at least 500 kHz wide, so there the boxes use LoRa SF9 at 500 kHz (about the range of SF7 at 125 kHz), at most 0.5 W at the antenna, and 921.5 MHz by default. Every box, USB radio modem and I/O pod is built for one region (`docker_fw.py build --region=as923-tw`) and refuses the other regions' channels and joins. The Taiwanese region is in software and host tests only: not tested on air, and not certified (a product sold in Taiwan needs NCC type approval and an antenna made for 920 MHz). Details: [RFC 0001 Amendment 12](docs/rfcs/0001-skirmesh-rf-wire-format.md), decisions RF-AS923-1 to -14.

**One protocol on every device.** Skirmesh-RF is built in layers, from the radio up to the controller's API. A Field Box runs everything up to the game modes; a Raspberry Pi controller leaves the radio work to a USB radio modem; in phase 3 an Android phone does the same with an I/O pod, whose firmware is the USB modem's radio code. Phones on the field's Wi-Fi need no LoRa radio at all. The wire format is [RFC 0001](docs/rfcs/0001-skirmesh-rf-wire-format.md).

![Skirmesh-RF on different devices: five layers from the bottom up (the LoRa radio on one shared channel; the encrypted Skirmesh-RF packet with anti-replay, hop limit, ACKs, TIME beacons and CLAIM failover; the eight message types in CBOR; the shared C core and Lua modes; the controller's APIs, GM console, scoreboard and join codes), and which layers each device runs. Built and tested in software: the Field Box (1 to 4), the USB radio modem (1 and 2), the field controller (2 to 5) and the GM console on phones over Wi-Fi (5). Built in software for phase 3 too: the I/O pod (1 and 2) and the Android device (2 to 4). Planned: the satellite box (1 to 4).](site/img/diagrams/skirmesh-wide-en.svg)

The diagrams are built in English and Portuguese, for wide and narrow screens, from [`site/src/diagrams/`](site/src/diagrams/) by `tools/build_site.py`; the project page's radio page shows them in your language ([Português](https://atalaia-project.link/radio/) · [English](https://atalaia-project.link/en/radio/)).

## Repository layout

| Folder | What lives there | Licence |
| --- | --- | --- |
| [`core/`](core/) | Shared C11 core: event bus, state store, Lua sandbox, protocol codec | GPL-3.0-or-later |
| [`protocol/`](protocol/) | Skirmesh-RF message and event schemas; [usb-modem.md](protocol/usb-modem.md) (modem framing); [join.md](protocol/join.md) (join payload) | GPL-3.0-or-later |
| [`modes/`](modes/) | Built-in game modes (Lua + manifest) | GPL-3.0-or-later |
| [`firmware/`](firmware/) | ESP32 firmware (ESP-IDF) and Arduino thin-node firmware | GPL-3.0-or-later |
| [`app/`](app/) | Flutter app: props and the phone controller (Android), player, marshal and GM roles (Android; iOS project in place, built by CI, not yet run on an iPhone: [guide](app/docs/ios-on-a-mac.md)) | GPL-3.0-or-later + app-store permission |
| [`controller/`](controller/) | Field controller (`atalaia_controller`) and GM console ([`controller/console/`](controller/console/), served at `/console/`) | AGPL-3.0-or-later |
| [`server/`](server/) | Optional site server | AGPL-3.0-or-later |
| [`simulator/`](simulator/) | Desktop simulator with virtual nodes and a web view; the mode editor (blocks to Lua) at `/editor/` | GPL-3.0-or-later |
| [`examples/scoreboard/`](examples/scoreboard/) | MQTT subscriber scoreboard example | GPL-3.0-or-later |
| [`hardware/`](hardware/) | Reference builds: wiring, bills of materials, enclosures; the Field Box build manual ([hardware/field-box/BUILD.md](hardware/field-box/BUILD.md)) and the build guides of the Satellite, the I/O pod and the target addon | CERN-OHL-S-2.0 |
| [`docs/`](docs/) | Design spec, RFCs, phase folders, guides | CC-BY-SA-4.0 |
| [`site/`](site/) | The project page in Portuguese, English, German and Traditional Chinese, published to [GitHub Pages](https://atalaia-project.link/) | CC-BY-SA-4.0 |
| [`tools/`](tools/) | Developer scripts: `check.sh`, `docker_fw.py`, `docker_console.py`, `docker_editor.py`, `docker_server.py`, `docker_sim.py`, `build_site.py`, `docker_hw.py` | GPL-3.0-or-later |

See [LICENSING.md](LICENSING.md) for the details.

## Roadmap

| Phase | Focus | Done when |
| --- | --- | --- |
| 0 · Foundations | Repository, licences, shared core skeleton, Lua sandbox, simulator | The simulator runs Domination and Bomb from Lua scripts |
| 1 · Single box | Field Box build, ESP32 firmware, on-device presets, a build manual with a wiring diagram | One box runs a 2-hour club game with no restarts |
| 2 · Field network | Skirmesh-RF over LoRa, field controller, API, GM console, and a mode pack (done in software): Hold-All Domination, Last Stand, per-team arming codes on Bomb and the Codes modifier | 5 boxes on a CQB site and an outdoor field, zero lost captures |
| 3 · Android and players | Android props, I/O pod, player app with roles; Respawn, Kill Confirmed, Player Check-in, Money Factory, the Medic Kit (a hit player scans their tag and holds to be healed, with limited heals) and chrono check-in. Done in software: the three tag modes, Money Factory (factory boxes make money while a team holds them, players collect it with their tag and bank it at a bank box; the controller's `field.lua` keeps what each player carries, decision A1's blocker), the Medic Kit (a role package next to any mode, its heals counted across kits by the controller, refilled from the GM console), signed player tags, the I/O pod protocol, YAML mode screens, and the app: its engine (the core through `dart:ffi` in a game loop isolate, built for Android with the NDK) and its screens (Android props, the player's view, the marshal's chrono check-in, replicas and tags, the GM console; Portuguese and English), tested on an emulator in CI; field check-in with a printed poster, player tokens and roles, the "replicas to chrono" list fed by signed readings, player positions, Android props on the field's Wi-Fi, HTTPS with the field's own CA, field and team branding (logo, wallpaper, colour, team crests), the I/O pod's firmware (USB and Bluetooth LE, the Field Box's buttons, keypad, ring, sound, NFC and an enclosure switch, the radio passthrough) and the phone's radio link through it, tested against the pod's own code on a PC. Done in software: the phone as the field controller (all seven slices: *Field controller* on the app's home screen runs a mode's field.lua and the Pi controller's REST API, live stream, MQTT topics, check-in with players' tokens, the replicas-to-chrono list and positions on its own isolate under a foreground service, keeps its games across a restart, uses an I/O pod as its radio, serves the GM console from the app and opens HTTPS with a field CA it makes itself, and MQTT, to the field's Wi-Fi, serves the field plan (a plan per level, its map position, map features with the field boundary, the field loaded from a map) and the radio channel with a quiet-channel scan through the I/O pod, and the boxes over the radio: with the Pi's USB radio modem plugged into the phone it invites free boxes into the next game with sealed radio invites, tells a game's boxes it is over, adopts new boxes by their pairing code or a field card the phone writes by NFC, and sends firmware updates between games (the I/O pod's firmware does not relay these radio messages yet); it also keeps presets, takes mode uploads and signed mode packages and sends them to the boxes that lack them, compiles scenarios, plays games with role packages and shows team names and crests, and does everything else a Pi's controller does: failover, so that a phone and a Pi can each be the other's standby, the site server sync (games, logs and scores sent when the internet is there; rosters, branding and the scenario library from it), the remote GM and the ATAK feed, all passing the same contract cases and playing games with the pod's, the modem's and the Field Box's own code on a PC; not yet run on a phone). Next: the field test with real phones and pods | One game mixes ESP32 and Android props without issues |
| 4 · Site server and advanced play | Site server, custom scenarios, advanced modes, ATAK. Done in software: Master and Satellites (satellites held with the master raise its points; the master changing hands frees them), tested in the simulator, through the controller and on the host box; the Hacking Terminal (a code to crack, wires to cut or a sequence to repeat on a keypad; solving it reveals a code and can capture the terminal), tested the same way; VIP / Payload (a team escorts its VIP, tracked by the app's position reports through the controller, or a phone with GPS to an extraction zone past checkpoint boxes; positions never leave the controller and the phone), tested the same way and through the app's prop; the runtime of custom scenarios (a scenario package is a field script on the controller over the built-in objectives package, whose boxes and props capture, take a code, count tags or cards, or hold a bomb site, and are set up again after a reboot; the scenario reveals, completes and scores the objectives), tested in the simulator, through the controller on host boxes and in the app's tests; the scenario compiler and validator (a YAML scenario of seven objective types with dependencies, reveals, time windows and points, every problem reported with where and why, compiled into such a package from the command line; the hand-written example, recompiled, passes the same tests); scenarios in the GM console and the app (a scenario editor in the console that lists every problem with its place as the GM types and installs the scenario, the boxes named with the scenario's names when they join, and in the app's player view the objectives meant for that player with their names and state: a team's or a squad's objectives reach only it, a hidden one nothing before it is revealed), tested with host boxes, in a headless browser and in the app's tests; the logic of Target Windows (a hit while the target shows a team's colour scores for that team), in the simulator and the app's tests, waiting for the target addon; the site server's skeleton (FastAPI on PostgreSQL 16, its migrations and health check, in its own image) its accounts (Argon2id passwords, TOTP required for admins, GMs and marshals, rotating sessions, per-field roles, an audit log) and personal data rights (access, export, correction, erasure, consent records, a daily retention purge); the controller sync (field controllers push their games, event logs and scores to the site server, offline first and safe to replay, a GM's negative adjustment included), tested end to end against the real controller and PostgreSQL in Docker, not yet over a real 4G link; the chrono registry (signed readings verified on the server and kept as signed, public keys only, sharing between fields with consent), not yet run with a real chronograph; scheduling with a public field page per field (Portuguese and English, no JavaScript) and open iCalendar and JSON feeds of its games, no personal data on them; registration for scheduled games with pre-declared replicas and check-in tickets, the controller pulling the roster and reporting who came, registering from the app, and importing a registration list (CSV or JSON) exported from another platform; club profiles (a club's name, colour, logo and crest, members its admins invite, a public page off by default with a report button and an administrator who can hide it) and branding sync (a field's branding and saved teams edited on the site server, every image checked with the controller's own rules, pulled by controllers set to `[sync] branding = "site"`, so a club's crest uploaded once reaches every field that saved its team), tested against the real controller and PostgreSQL in Docker; device health (each box's battery, link and firmware from what the controllers sync; the field controller now logs when a box goes silent or comes back and when its battery runs low, which a box with a battery gauge also reports itself, in software and not yet on real boards), a firmware catalogue that lists only releases signed with a trusted release key, and over-the-air firmware updates for the Field Box (the GM uploads a signed release to the field controller and updates the boxes between games; each box fetches it over the field Wi-Fi, checks the signature with keys built into its own firmware, installs it in its spare slot and goes back to the old firmware if the new one does not start), in software and host tests, not yet run on a real board, and the remote GM (a user with the gm role on the field, logged in with TOTP, sees a controller's live game and starts, pauses, resumes or ends it, sends a GM message or a mode command, over a connection the controller opens itself and only when the field turns it on; every command logged on both sides), tested against the real controller and PostgreSQL in Docker, not yet on a real deployment; staff web pages for the history, the scenario library and presets, device health and the remote GM (login with TOTP, Portuguese and English, phone-sized; the pages hold no data and call the API, so its role rules hold), tested in headless Chromium against the real API in Docker, not yet on a real deployment; game history (each game's score timeline from the per-node counters and its event log by type and time; organisers see everything, players and spectators a live game a minute behind, without secrets or player ids), a public scoreboard per field (off by default) and the field's scenario library (scenarios checked with the controller's own compiler and the core, kept as revisions, with game presets), which every controller of the field, a standby included, installs from the site server, tested against the real controller and PostgreSQL in Docker; the site server's deployment (Caddy in front with an automatic certificate, the database and the server unreachable from outside, a setup script that makes the secrets, encrypted daily backups and a restore into a fresh database), tested in Docker on a computer, not yet on a real server with a real domain; hosted multi-tenant mode (one site server for many fields, each in a database schema of its own reached at its own address, with row-level security underneath, and the hub operator's commands to make, migrate, suspend, export and delete one field; one field's staff, controllers, players and pages never see another's), tested against PostgreSQL in Docker; and its deployment (a setup script for a hub that makes the database roles, every field at its own address with a certificate only an active field's name can get, encrypted backups restored with the isolation checked again), tested in Docker on one computer, not yet on a real hosted server with a real domain, and not live before the legal review; geo utilities in the core (`geo.distance` and `geo.in_zone` for every script, the same result to the bit on the box, the controller and phones); the ATAK feed (the controller sends the boxes and zones as Cursor on Target markers in their owners' colours over the field Wi-Fi, placed by two corners of the field image the GM gives a map position; player positions never go to the multicast group, only to staff ATAK devices when the field turns it on), tested with receivers on a computer, not yet with a real ATAK phone; and the remote ATAK relay (staff away from the field, or a command post, see the boxes and zones on ATAK through the site server, over TLS with a client certificate per device that the field's admin or GM issues from the field's own authority as a TAK data package and can revoke at once; player positions only to a GM's or a marshal's certificate; the controller opens the connection; off by default), tested in Docker with TLS clients, the real controller and the deployments, not yet with a real ATAK phone or on a real server | A weekend milsim runs on Atalaia end to end |
| 5 · Community | Visual mode editor, mode registry, carrier PCB, translations, build guides for other node types. Done in software: the visual mode editor (a page of the simulator that turns blocks into a mode's Lua scripts and manifest, for the boxes and the field controller, with zones on the map, GM commands, several roles, modifiers and role packages and the mode's own screens, in Portuguese and English; its three examples pass the hand-written modes' tests), testing a mode from it live in the simulator, making the mode's package from it (the same archive the packing tool makes; signing stays offline), signed mode packages (one archive signed like a firmware release, a tool to pack, sign and verify them, the registry index's format), a sandbox-escape battery in CI that closed two ways for a script to outrun the watchdog, the field controller installing signed modes, uploaded or from a registry index, showing who signed them, and sending a box the signed modes a game needs (*Send missing modes* in the GM console's invite dialog: the box fetches them over the field Wi-Fi between games, checks them with keys built into its firmware, keeps them, and the game waits for it; tested on a computer, not yet on a real box), and scenario blocks in the console (the *Scenarios* tab's manifest as blocks, by mouse, touch or keyboard, which the controller checks and installs as before; every example compiles exactly as written by hand), the community mode registry ready as a template the maintainer creates its repository from (each submission's signatures, its source against the signed package, its licences and its tests checked by CI; the verified badge is the project's own signature, which is what boxes trust), the community processes (submitting a mode, the review checklist, keys and their revocation, moderation), German and Traditional Chinese as written in Taiwan in the project page, GM console, mode editor, app and Field Box screens (drafted by an AI model, to be reviewed by players who speak them; the Field Box's fonts carry just the Chinese letters its screens use, now compressed, so its firmware is no bigger), with a translation guide and a check of every language, and build guides for the Satellite (the Field Box's firmware with two buttons and an LED ring), the I/O pod (the Field Box's parts without the screen) and the target addon (what is decided and what is not: not buildable yet), in [`hardware/`](hardware/) and on the project page in four languages; no box built from them yet. Next: creating the registry repository (the maintainer), the review of the German | Ongoing |

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

**Run the field controller and its GM console** on a laptop, without a radio, in the dev container (see [controller/README.md](controller/README.md#running-it)): the console is at `http://localhost:8080/console/` and the scoreboard at `/scoreboard`. The console's browser tests run with `python tools/docker_console.py`.

**Run the site server's tests** (its skeleton, accounts, personal data rights, the controller sync, the chrono registry, scheduling with the public field pages and feeds, registration with the game-day roster, and the registration import with platform adapters exist so far, the sync tested end to end against the real controller) against a throwaway PostgreSQL 16 in Docker: `python3 tools/docker_server.py test`, `python3 tools/docker_server.py migrations`, `python3 tools/docker_server.py deploy` (the deployment behind Caddy) and `python3 tools/docker_server.py browser` (the staff pages in headless Chromium); `up` and `down` start and stop a local trial. See [server/README.md](server/README.md).

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
