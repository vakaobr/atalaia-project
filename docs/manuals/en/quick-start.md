<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Quick start

One page for game day. In Portuguese: [Início rápido](../pt/quick-start.md). Every role has a full manual: [player](player.md), [game master](game-master.md), [marshal](marshal.md), [Field Box operator](field-box.md), [phone prop](phone-prop.md). All manuals: [the index](../README.md).

> **Pre-alpha.** Nothing here has been used on a real field yet. Words in *italics* are in the [glossary](https://atalaia-project.link/en/glossary/).

## If you play

1. Install the Atalaia app (Android 8.0 or later, or iPhone). Tap the **gear**, then **Language** › **English**.
2. Join the field's Wi-Fi. If the phone says "no internet", stay connected.
3. **Player › Check in at the field › Scan the poster.** Read the notice, type your **Name or callsign**, tap **Check in**. Registered online? Pick your registration under **Online registration**, or show your printed ticket to a marshal or at the check-in desk.
4. **Pick the replicas** you will use. Take them to a marshal for the *chrono*.
5. **Follow the game.** Capture boxes at the box: **hold your team's button** until the bar is full.
6. Optional: **Share my position**. Keep **Vibrate on game events** on.

## If you run the game

1. Start the field controller. On a Raspberry Pi, show the codes with `cd /opt/atalaia/controller && sudo -u atalaia python3 -m atalaia_controller tokens --config /etc/atalaia/controller.toml`. On an Android phone, open **Field controller** in the app, then **Access codes › Show the codes**.
2. Open `https://` *controller address* `:8443/console/` (accept the field's own certificate once). Type the **GM code**.
3. Once: **Settings** › choose the radio channel. **Adopt** the new boxes. **Check-in** › **Print the poster** and put it up.
4. **Game** › name, mode, teams, duration › **Create game**.
5. **Invite boxes**: tick them, give roles, **Invite**. Wait for **Ready to start**.
6. **Check-in**: confirm players, give teams, add marshals. Registered players show as **expected**: tap **Arrived**, or scan their ticket under **Printed ticket**.
7. **Start** › **Yes**. Watch **Log** and **Boxes**. **End** when done.

New firmware for the boxes: [Update the boxes](field-box.md#update-the-boxes).

## If you are a marshal

1. Check in as a player. Ask the GM to add you under **Check-in › Marshals**.
2. **Marshal** shows **You are marshal M-01**. Stay on the field's Wi-Fi at least every 2 hours.
3. At the check-in desk: compare membership cards and tap **Card seen, matches**; check in a player without the app with **Check in by hand**. Take a registered player's printed ticket with **Marshal › Check in a ticket** ([the check-in desk](marshal.md#2-the-check-in-desk)).
4. **Replicas to chrono** › tap a replica › **Check-in** › choose **BB weight**, type the velocity, **Record the shot** for each shot.
5. **Send to the controller**. During the game, use **Spot check**.

## If you look after the boxes

1. Antenna fitted. Battery charged. Switch **on**.
2. First time: join the `atalaia-…` Wi-Fi, open `192.168.4.1`, fill in the page, choose an **Admin PIN**. The field's Wi-Fi password must be empty, 8 to 63 characters, or 64 hex digits.
3. The GM **adopts** the box (cable, field card or the 6-digit code). It shows **READY · Next game**.
4. The GM **invites** it. It shows **WAITING**, then **GAME ON** at the start.

## If something goes wrong

- **A box is refused "in another game", or the console lists it under Stuck in an ended game:** tap **Release**; or take it out at the box ([take a box out of its game](field-box.md#take-a-box-out-of-its-game), from v0.9.0, not released yet). More: [recover from problems](game-master.md#recover-from-problems).
- **The console says Radio down:** check the USB modem's cable, then see [recover from problems](game-master.md#recover-from-problems) and [update the modem](modem.md#update-the-modem).
- **A yellow banner says The controller's clock is wrong:** tap **Set the controller's clock from this device** if your phone's time is right ([the controller clock](controller-setup.md#the-controller-clock)).
- **A box shows as not heard:** move it closer, or put a box in between; after a channel change, use **Look for boxes** ([change the channel](game-master.md#change-the-channel)).
- **The console will not open:** use `https://` and port `8443`, stay on the field's Wi-Fi, and check the code; a day code may have ended ([recover from problems](game-master.md#recover-from-problems)).

Building a box: the [build guide](https://atalaia-project.link/en/build-guides/).
