<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Quick start

One page for game day. In Portuguese: [Início rápido](../pt/quick-start.md). Every role has a full manual: [player](player.md), [game master](game-master.md), [marshal](marshal.md), [Field Box operator](field-box.md).

> **Pre-alpha.** Nothing here has been used on a real field yet. Words in *italics* are in the [glossary](https://atalaia-project.link/en/glossary/).

## If you play

1. Install the Atalaia app (Android 8.0 or later, or iPhone). Tap the **gear**, then **Language** › **English**.
2. Join the field's Wi-Fi. If the phone says "no internet", stay connected.
3. **Player › Check in at the field › Scan the poster.** Read the notice, type your **Name or callsign**, tap **Check in**.
4. **Pick the replicas** you will use. Take them to a marshal for the *chrono*.
5. **Follow the game.** Capture boxes at the box: **hold your team's button** until the bar is full.
6. Optional: **Share my position**. Keep **Vibrate on game events** on.

## If you run the game

1. Start the field controller (a Raspberry Pi with its USB modem, or the app's **Field controller** on Android). Get the **GM code**: `python3 -m atalaia_controller tokens`.
2. Open `https://` *controller address* `:8443/console/` (accept the field's own certificate once). Type the GM code.
3. Once: **Settings** › choose the radio channel. **Adopt** the new boxes. **Check-in** › **Print the poster** and put it up.
4. **Game** › name, mode, teams, duration › **Create game**.
5. **Invite boxes**: tick them, give roles, **Invite**. Wait for **Ready to start**.
6. **Check-in**: confirm players, give teams, add marshals.
7. **Start** › **Yes**. Watch **Log** and **Boxes**. **End** when done.

## If you are a marshal

1. Check in as a player. Ask the organisers to add you under **Check-in › Marshals**.
2. **Marshal** shows **You are marshal M-01**. Stay on the field's Wi-Fi at least every 2 hours.
3. **Replicas to chrono** › tap a replica › **Check-in** › choose **BB weight**, type the velocity, **Record the shot** for each shot.
4. **Send to the controller**. During the game, use **Spot check**.

## If you look after the boxes

1. Antenna fitted. Battery charged. Switch **on**.
2. First time: join the `atalaia-…` Wi-Fi, open `192.168.4.1`, fill in the page, choose an **Admin PIN**.
3. The organisers **adopt** the box (cable, field card or the 6-digit code). It shows **READY · Next game**.
4. They **invite** it. It shows **WAITING**, then **GAME ON** at the start.
5. Lost box? The console says **not heard**. Move it closer, or put a box in between.

Building a box: the [build guide](https://atalaia-project.link/en/build-guides/).
