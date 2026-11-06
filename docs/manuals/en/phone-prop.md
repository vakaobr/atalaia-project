<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phone prop and I/O pod

For the person who sets up an Android phone as a game prop, with or without an I/O pod. In Portuguese: [Telemóvel como dispositivo de jogo e módulo de E/S](../pt/phone-prop.md).

A phone that runs the whole game for the field (the **Field controller** role) is a different job: see the [Game master manual](game-master.md). The Field Box itself is in the [Field Box operator manual](field-box.md).

> **Not field-ready yet.** Atalaia is pre-alpha. The phone prop is tested on a computer and on CI's Android emulator. The I/O pod's firmware is tested on a computer, against the app and the controller. **Neither has run on a real phone or a real pod on a field.** Steps that need real hardware say **Not yet tried on hardware**.

## Contents

1. [What it is](#1-what-it-is)
2. [Set up the phone](#2-set-up-the-phone)
3. [Link an I/O pod](#3-link-an-io-pod)
4. [Get the phone into a game](#4-get-the-phone-into-a-game)
5. [During the game](#5-during-the-game)
6. [When the pod's link is lost](#6-when-the-pods-link-is-lost)
7. [Outputs and modules on the pod](#7-outputs-and-modules-on-the-pod)
8. [Modes the app does not carry](#8-modes-the-app-does-not-carry)
9. [Limits](#9-limits)
10. [Troubleshooting](#10-troubleshooting)

## 1. What it is

A **phone prop** is an Android phone that acts as a box: it runs the game mode, shows the mode's screens, has team buttons on the screen, and reads player tags with the phone's NFC. In the app it is the **Game prop** role. Only Android can do it: it needs kiosk mode, NFC in the background and USB.

An **I/O pod** is a small board (a Heltec V4, like a box) that lends the phone what it lacks: big team buttons, a keypad, a light ring, sound, an NFC reader, a LoRa radio, and optionally outputs (a siren, a strobe...) and an expansion port for a target or an output module. It links to the phone over a **USB-C cable** (preferred) or **Bluetooth**. How to build one: [I/O pod build guide](../../../hardware/io-pod/BUILD.md). How to flash it: [firmware guide, section 10](firmware.md#10-the-io-pod-variants).

| | Phone alone | Phone with an I/O pod |
| --- | --- | --- |
| Team buttons | On the screen | Big buttons on the pod |
| Player tags | The phone's NFC | The pod's reader |
| Link to the controller | The field's Wi-Fi | The field's Wi-Fi first, the pod's LoRa radio while the Wi-Fi is down |
| Outputs, target, output module | None | If the pod was built with them ([section 7](#7-outputs-and-modules-on-the-pod)) |

## 2. Set up the phone

Do this once, before the game day.

1. Install the Atalaia app and open it. On **What will this phone do?**, choose **Game prop**.
2. Open **Settings** and set:
   - **Field join key**: the 64 hex digits the organisers give you. Without it the phone cannot join the field's games.
   - **Admin PIN**: 4 to 8 digits. The app asks for it to start, pause, end and leave a game, and for the **Game master** menu. Without a PIN, anyone can pause or end a game on this prop.
   - **Kiosk mode**: on. During a game the phone is pinned to the app; if someone gets out, the app warns and the GM is told.
   - **Mode keys for fetched modes**, only if the organisers use modes the app does not carry ([section 8](#8-modes-the-app-does-not-carry)).
3. Open **Battery and background** (in **Settings**, or from the warning on the prop's screen) and take Atalaia out of battery optimisation. The screen gives the steps for Samsung, Xiaomi, Huawei, OnePlus and other makers. Without it, Android may stop the app during a game.
4. Charge the phone. A game of a few hours on the screen uses a lot of battery: bring a power bank.

## 3. Link an I/O pod

Fit the pod's antennas before you power it. Never power a pod without its LoRa antenna.

**Over USB (preferred):**

1. Connect the phone to the pod with a USB-C OTG cable (a data cable, not a charge-only one).
2. In the app, on the prop's screen, under **I/O pod**, tap **Link a pod**, then **Find pods**.
3. Open the pod and allow USB access. The app says **Pod linked over USB**.

**Over Bluetooth:**

1. With no cable, tap **Link a pod**, then **Find pods**. The pod is listed as `atalaia-pod-XXXX`. Open it.
2. The pod's small screen shows **PAIR**, the seconds left and a 6-digit code. Android asks for it: type the 6 digits within 30 seconds.
3. The pod shows **PAIRED** and the app says **Pod linked over BLE**. The phone and the pod keep the pairing: you do this once.

If it goes wrong:

- **A wrong code**, or *Cancel*: the pod shows **FAILED**. Open the pod again for a new code.
- **Too slow**: the pod shows **TOO SLOW**. Open it again and type the code within 30 seconds.
- **"This pod needs pairing again"**: the pod forgot its phones, or was paired before it had a code. The app forgets the old pairing and opens the pod again by itself, once: type the new code. If Android does not let the app forget it, forget `atalaia-pod-XXXX` in Android's Bluetooth settings, then link it again.
- **Make the pod forget every phone**: open the pod's lid and hold the board's **PRG** button for 5 seconds. The pod shows **FORGET ALL**, then **CLEARED**. Do it between games: opening the lid reports a tamper if the pod has an enclosure switch.

A pod links to one phone at a time. The pod's screen speaks English only. Not yet tried on hardware.

## 4. Get the phone into a game

**A game of the field controller (the normal way):**

1. Tap **Join a game**.
2. Scan the **join QR code** on the GM's console, hold the **join card** to the back of the phone, or paste the `atalaia:join:...` text.
3. The phone shows **Controller's game**, the game number, its node number and the channel. A code from another field is refused (**the join key does not match**).
4. Wait for the GM's **Start**.

The join QR code and the join card carry the game key: show them only to the people setting up the field.

**A game on this phone alone:** tap **New game**, choose the mode, its role, the teams, its parameters and the length, then **Prepare the game** and **Start**. A mode that scores across several boxes needs the controller: alone, the prop only does its own part, and the app says so. If the mode needs something the phone lacks (an NFC reader, for example), the app names it: link an I/O pod that has it.

## 5. During the game

- The phone shows the mode's screen, with **Hold** buttons for each team, or uses the pod's buttons. Player tags go to the back of the phone, or to the pod's reader.
- **Game master** (on the game screen) asks for the admin PIN and opens a menu: **Pause** / **Resume** and **End the game** (when they apply), **Link the pod again** and **Unlink the I/O pod** (with a pod), **Game log**, and **Leave**.
- **Leave** takes this prop out of a game that is still running: **Leave the game?** The game goes on for everyone else, and this prop stops counting. This is not the player app's **Leave the game** (which erases a player's name from the game) nor the Field Box's admin menu entry of the same name ([Field Box manual](field-box.md#take-a-box-out-of-its-game)).
- A red banner says **Someone left kiosk mode during the game** or **Someone opened the I/O pod during the game**. The GM is told too. Tell the game master.
- Keep the app in the foreground. If Android sends it to the background, the pod's outputs go off ([section 7](#7-outputs-and-modules-on-the-pod)).

## 6. When the pod's link is lost

1. The app opens the link again by itself, and the game screen says so: **The I/O pod link was lost. Reconnecting (try N)…**. A pod that needs pairing again is paired once more, and the screen asks for the new code.
2. If that does not work (a wrong or slow pairing code, a pod that refuses the phone), a red banner says **The app could not link the pod again by itself** and why. If a different pod answered, the banner names the pod the game expects.
3. Bring that pod. Tap **Game master**, type the admin PIN and tap **Link the pod again**. The app tries the pod at once; Android asks for the code on the pod's screen if it has to pair.
4. Once the pod is back, the banner goes and the game goes on with the pod (its buttons, outputs and radio), not from the start. If it fails again, the banner comes back with the new reason.

The game goes on without the pod in the meantime. After the game, you can also link a pod from the prop's screen (**I/O pod**). Not yet tried on hardware.

## 7. Outputs and modules on the pod

**Simple outputs.** A pod built with a **simple output** (a siren, a strobe, a light or a smoke machine's remote on an RC relay switch; [I/O pod build guide, section 8.1](../../../hardware/io-pod/BUILD.md#81-simple-outputs-optional)) lends it to the phone. The game on the phone switches it as a box switches its own, and so does the GM from the console.

- There is nothing to enable on the phone or the pod: a pod has no admin PIN, so the builder set the output's use (**siren**, **smoke**...) and its longest time on when building the pod. Ask the builder which use it has: the game asks for an output by its use.
- The same rules as on a box ([Field Box manual, section 8.1](field-box.md#81-what-the-game-does-with-an-output)): only during the game (and an end-of-game horn for up to 10 seconds), off when the game starts, is paused or ends, never longer than its longest time, at most one change every half second.
- **If the phone goes, the output goes off.** The pod turns it off when the USB cable is pulled, the Bluetooth link drops, or the app stops talking to it for 1.5 seconds.

**A target or an output module.** A pod with an expansion port takes the same modules as a box ([I/O pod build guide, section 8.2](../../../hardware/io-pod/BUILD.md#82-expansion-port-optional)):

- **A target**: plug it in and the game on the phone counts its hits while the game runs, as on a box.
- **An output module**: its relays work as the pod's simple outputs, only if the pod was built to lend them. Their longest time is the pod's build setting, never more than the module's own. The pod turns them off when the phone goes.
- Plug modules in before the game. The GM sees them under the phone in the console.

**Safety** is the box's: low-voltage devices on their own battery or supply only (at most 24 V), never mains, a smoke machine only through its low-voltage remote input, never pyrotechnics, hearing protection near sirens, eye and face protection near a target ([Field Box manual, section 8.5](field-box.md#85-safety)).

Not yet tried on hardware.

## 8. Modes the app does not carry

If the game uses a mode the app does not carry, and the organisers allow it, the phone gets the mode from the field controller over the field's Wi-Fi before the game starts. It takes only a package **signed** by a mode key you trust:

1. Ask the organisers for the mode key: the project's, or your club's.
2. In **Settings › Mode keys for fetched modes**, paste it (44 base64 characters; one per line, at most 4). Never add a key you were not given by the project or your club.
3. Join the field's Wi-Fi, then join the game. The app says **Getting the game's mode from the controller and checking its signature…**.

A package that is unsigned, signed by another key or damaged is refused with a message and never runs. With no mode key at all, the phone runs only the modes built into the app. Not yet tested on a field.

## 9. Limits

- **Android only.** An iPhone cannot be a prop.
- **One phone per pod**, and one pod per phone, at a time.
- **No admin PIN on the pod.** Its outputs are on as the builder built them; the phone's admin PIN guards the game.
- **The phone must stay awake and in front.** Battery optimisation off, the app in the foreground; otherwise the game stops counting or the pod's outputs go off.
- **An I/O pod is not a radio modem for the controller's stuck-box reports.** A phone controller that uses a pod as its radio cannot free boxes stuck in an ended game by itself: see the [Field Box manual](field-box.md#take-a-box-out-of-its-game).
- The pod and the modules are reflashed over USB, never updated over the air.
- Nothing here has been used on a real field.

## 10. Troubleshooting

| Problem | What to do |
| --- | --- |
| **First set the field join key in the settings.** | Set the **Field join key** in **Settings** ([section 2](#2-set-up-the-phone)). |
| The join code is refused: from another field | The phone's join key is not this field's. Ask the organisers for the right key. |
| **This code is for a standby controller, not a prop.** | The GM showed the wrong code. Ask for the prop's join code. |
| The phone does not find the pod over USB | A charge-only cable, or a phone without USB host (OTG). Try another cable. |
| `atalaia-pod-XXXX` is not listed | The pod's 2.4 GHz antenna is missing, another phone is linked (one at a time), or the pod was built without Bluetooth. |
| Android asks for a code but the pod's screen stays dark | The pod's small screen was not found at boot. Ask the builder (the code is in the pod's log). |
| **This pod needs pairing again** every time | Android did not forget its pairing: forget `atalaia-pod-XXXX` in the Bluetooth settings, then link it again. |
| **This phone lacks: …** | The mode needs a part the phone does not have. Link an I/O pod that has it. |
| The pod's siren never comes on | The pod was built without the output, or with another use than the game asks for (ask the builder); the pod is not linked; no game running; the switch's own battery is flat. |
| The pod's output goes off by itself | The phone stopped talking to the pod (the app was sent to the background or closed) or the link dropped. Link again; keep the app in the foreground. |
| The target's hits never reach the game | The game is not running, or the app is older than the pod. Update the app. |
| **This phone trusts no mode key, so it takes no mode from the controller.** | Add the mode key in **Settings › Mode keys for fetched modes** ([section 8](#8-modes-the-app-does-not-carry)). |
| **Could not reach the controller with the field's certificate.** | Join the field's Wi-Fi and try again. |
| The game stopped counting when the screen went off | Take Atalaia out of battery optimisation (**Battery and background**). |

For the pod's build and bench faults, see the [I/O pod build guide, section 11](../../../hardware/io-pod/BUILD.md#11-troubleshooting).
