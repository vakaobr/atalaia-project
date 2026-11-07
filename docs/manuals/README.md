<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Atalaia user manuals

These are the manuals for the people who **use** Atalaia on a field: players, organisers, marshals and the people who look after the boxes. They are not for developers. For the design, the protocol and the code, start at the [documentation index](../README.md).

> **Pre-alpha.** The software for every role is built, but no real phone, box or controller has been used on a field yet. The manuals describe the screens and steps as the software shows them today. A step that depends on hardware says **Not yet tested on a field**. A feature names the release it comes in, for example **from v0.10.0** (the newest release, 2026-11-07); one that is not in a release yet says **not released yet**. When the software changes, the manuals change with it.

## The manuals

On game day:

| For | English | Português (pt-PT) |
| --- | --- | --- |
| **Everyone**: one page per role, and what to do when something goes wrong | [Quick start](en/quick-start.md) | [Início rápido](pt/quick-start.md) |
| **Players**: install the app, check in, play, your account on the field's site | [Player manual](en/player.md) | [Manual de quem joga](pt/player.md) |
| **Game masters**: the GM console, a game from start to end, recovering from problems, updating the boxes | [Game master manual](en/game-master.md) | [Manual da organização](pt/game-master.md) |
| **Marshals**: the check-in desk, the chrono, spot checks, players' tags | [Marshal manual](en/marshal.md) | [Manual de marshal](pt/marshal.md) |
| **Field Box operators**: switching on, joining a game, screens, outputs, taking a box out of its game, battery, updates | [Field Box operator manual](en/field-box.md) | [Manual de operação da Field Box](pt/field-box.md) |
| **Game prop operators**: a phone as a game prop, with its I/O pod | [Phone prop and I/O pod](en/phone-prop.md) | [Telemóvel como dispositivo de jogo e módulo de E/S](pt/phone-prop.md) |

Setting up a field (once, and for each update):

| For | English | Português (pt-PT) |
| --- | --- | --- |
| **Organisers**: the field controller on a Raspberry Pi with its modem board, a standby controller, updates | [Controller setup guide](en/controller-setup.md) | [Guia de montagem do controlador](pt/controller-setup.md) |
| **Organisers**: the field controller on an Android phone | [Phone controller guide (Android)](en/phone-controller.md) | [Guia do telemóvel controlador (Android)](pt/phone-controller.md) |
| **Organisers and builders**: flash the controller's radio modem, plug it in, check it, update it | [Set up the radio modem](en/modem.md) | [Montar o modem de rádio](pt/modem.md) |
| **Field admins**: the site server's staff pages, accounts, schedules, registrations, data and privacy | [Site server administration manual](en/site-admin.md) | [Manual da administração do servidor do site](pt/site-admin.md) |

For people who **build** things (not for players or organisers on game day):

| For | English | Português (pt-PT) |
| --- | --- | --- |
| **Builders**: get, flash and set up the firmware of a box, a pod, the modem board or an expansion-port module | [Firmware guide](en/firmware.md) | [Guia do firmware](pt/firmware.md) |
| **Builders**: the hardware, with a pin reference for each board | [Field Box](../../hardware/field-box/BUILD.md), [Satellite](../../hardware/satellite/BUILD.md), [I/O pod](../../hardware/io-pod/BUILD.md), [Target addon](../../hardware/target-addon/BUILD.md), [Expansion port](../../hardware/expansion-port/BUILD.md), [I2C output module](../../hardware/output-module/BUILD.md) | [Field Box](../../hardware/field-box/BUILD.pt.md), [caixa Satélite](../../hardware/satellite/BUILD.pt.md), [módulo de E/S](../../hardware/io-pod/BUILD.pt.md), [módulo de alvo](../../hardware/target-addon/BUILD.pt.md), [porta de expansão](../../hardware/expansion-port/BUILD.pt.md), [módulo de saídas I2C](../../hardware/output-module/BUILD.pt.md) |

Each manual has a **Troubleshooting** section at the end.

## Languages

The manuals are in **English** and **European Portuguese (pt-PT)**. The Portuguese manuals are a faithful translation of the English ones, in the words players use on the field (*marshal*, *squad*, *Último Elemento* for Last Stand).

**German, Traditional Chinese and Polish are out of scope for now.** The app, the GM console and the boxes' screens are available in German and Traditional Chinese, and the project page also in Polish, but the manuals are not. The project page, in all its languages, links to this index.

## Words and conventions

- Names of buttons, tabs and screens are written in **bold**, exactly as the software shows them in that language. The English app calls the GM role **Game master**. The Portuguese app calls the player role **Participante** and the GM role **Organização**.
- The **GM** (game master) is the person at the GM console during a game. The **organisers** are the field's staff as a whole: they set up the field, the controller and the boxes. One person is often both.
- Two different actions are both called **Leave the game**: the player's, in the app on **My check-in** (it erases your name from the game), and the box's, in the box's admin menu (it takes the box out of its game). The manuals always say which one: *in the app* or *at the box*.
- In Portuguese, the I/O pod is the **módulo de E/S**; the boards on the expansion port are the **módulo de saídas** and the **módulo de alvo**.
- A version is always named (*from v0.9.0*), never "this release".
- Terms the project page explains are linked to its glossary: [English](https://atalaia-project.link/en/glossary/) · [Português](https://atalaia-project.link/glossario/).
- Pictures come from the project page. They are not photos of a real field: the screens are the software's own test images and the box animations are drawn by the firmware's own screen code.

## Related guides

- The firmware guide ([English](en/firmware.md), [Português](pt/firmware.md)) and the Field Box build manual ([English](../../hardware/field-box/BUILD.md), [Português](../../hardware/field-box/BUILD.pt.md)) and the [build guide](https://atalaia-project.link/en/build-guides/) on the project page: for building a box.
- The [app guide](../../app/README.md) and the [iPhone guide](../../app/docs/ios-on-a-mac.md): for building and installing the app.
- The [controller guide](../../controller/README.md) and the [site server guide](../../server/README.md): for installing the controller and the server.
- The [community mode registry](https://vakaobr.github.io/atalaia-modes/): shared game modes.
- The [radio page](https://atalaia-project.link/en/radio/): how the radio works.
- The [architecture diagrams](../architecture.md) ([em português](../architecture.pt.md)): how the radio links, the app, the controller and the site server talk to each other.

Found a step that does not match the software? Open an issue or tell us in [Discussions](https://github.com/vakaobr/atalaia-project/discussions). To help translate, see [`../translations/`](../translations/README.md).
