<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Atalaia user manuals

These are the manuals for the people who **use** Atalaia on a field: players, organisers, marshals and the people who look after the boxes. They are not for developers. For the design, the protocol and the code, start at the [documentation index](../README.md).

> **Pre-alpha.** The software for every role is built, but no real phone, box or controller has been used on a field yet. The manuals describe the screens and steps as the software shows them today. A step that depends on hardware says **Not yet tested on a field**. When the software changes, the manuals change with it.

## The manuals

| For | English | Português (pt-PT) |
| --- | --- | --- |
| **Everyone**: one page for game day | [Quick start](en/quick-start.md) | [Início rápido](pt/quick-start.md) |
| **Players**: install the app, join a game, check in, play | [Player manual](en/player.md) | [Manual de quem joga](pt/player.md) |
| **Game masters and field organisers**: the controller, the GM console, a game from start to end, the site server | [Game master manual](en/game-master.md) | [Manual da organização](pt/game-master.md) |
| **Marshals**: chrono check-in, spot checks, replicas to chrono | [Marshal manual](en/marshal.md) | [Manual de marshal](pt/marshal.md) |
| **Field Box operators**: switching on, joining a game, screens, battery, radio basics, troubleshooting | [Field Box operator manual](en/field-box.md) | [Manual de operação da Field Box](pt/field-box.md) |

For people who **build** things (not for players or organisers on game day):

| For | English | Português (pt-PT) |
| --- | --- | --- |
| **Builders**: get, flash and set up the firmware of a box, a pod or the modem board | [Firmware guide](en/firmware.md) | [Guia do firmware](pt/firmware.md) |
| **Organisers**: set up the field controller on a Raspberry Pi, with its modem board | [Controller setup guide](en/controller-setup.md) | [Guia de montagem do controlador](pt/controller-setup.md) |
| **Builders**: the hardware, with a pin reference for each board | [Field Box](../../hardware/field-box/BUILD.md), [Satellite](../../hardware/satellite/BUILD.md), [I/O pod](../../hardware/io-pod/BUILD.md), [Target addon](../../hardware/target-addon/BUILD.md) | [Field Box](../../hardware/field-box/BUILD.pt.md); em inglês: [Satellite](../../hardware/satellite/BUILD.md), [I/O pod](../../hardware/io-pod/BUILD.md), [Target addon](../../hardware/target-addon/BUILD.md) |

The guides for the satellite, the I/O pod and the target addon are in English only for now. Portuguese follows.

Each manual has a **Troubleshooting** section at the end.

## Languages

The manuals are in **English** and **European Portuguese (pt-PT)**. The Portuguese manuals are a faithful translation of the English ones, in the words players use on the field (*marshal*, *squad*, *Último Elemento* for Last Stand).

**German and Traditional Chinese are out of scope for now.** The app, the GM console, the boxes' screens and the project page are available in German and Traditional Chinese, but the manuals are not. The project page, in all four languages, links to this index.

## Words and conventions

- Names of buttons, tabs and screens are written in **bold**, exactly as the software shows them in that language. The English app calls the GM role **Game master**. The Portuguese app calls the player role **Participante** and the GM role **Organização**.
- Terms the project page explains are linked to its glossary: [English](https://atalaia-project.link/en/glossary/) · [Português](https://atalaia-project.link/glossario/).
- Pictures come from the project page. They are not photos of a real field: the screens are the software's own test images and the box animations are drawn by the firmware's own screen code.

## Related guides

- The firmware guide ([English](en/firmware.md), [Português](pt/firmware.md)) and the Field Box build manual ([English](../../hardware/field-box/BUILD.md), [Português](../../hardware/field-box/BUILD.pt.md)) and the [build guide](https://atalaia-project.link/en/build-guides/) on the project page: for building a box.
- The [app guide](../../app/README.md) and the [iPhone guide](../../app/docs/ios-on-a-mac.md): for building and installing the app.
- The [controller guide](../../controller/README.md) and the [site server guide](../../server/README.md): for installing the controller and the server.
- The [community mode registry](https://vakaobr.github.io/atalaia-modes/): shared game modes.
- The [radio page](https://atalaia-project.link/en/radio/): how the radio works.

Found a step that does not match the software? Open an issue or tell us in [Discussions](https://github.com/vakaobr/atalaia-project/discussions). To help translate, see [`../translations/`](../translations/README.md).
