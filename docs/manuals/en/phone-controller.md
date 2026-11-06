<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phone controller guide (Android)

For the organiser who uses an **Android phone as the field controller** of a small game, with no Raspberry Pi. The phone runs the game, serves the GM console, the check-in and the scoreboard on the field's Wi-Fi, and talks to the boxes through a radio plugged into it. Running the game is in the [Game master manual](game-master.md). The Raspberry Pi controller is in the [Controller setup guide](controller-setup.md); the two do the same job, and this guide says where they differ.

> **Not field-ready yet.** Atalaia is pre-alpha. As of 2026-11-06 the phone controller has run on a computer and on an Android emulator, against the boxes', the pod's and the modem's own code; **not yet on a real phone**, with a real radio, or on a field. Android only: the iPhone app has no controller.

Contents: 1. What you need · 2. Start the controller · 3. Codes and the join key · 4. The controller clock · 5. The network · 6. The radio: USB radio modem or I/O pod · 7. A standby controller · 8. What needs a computer · 9. Backups and how long data is kept · 10. Updates · 11. Troubleshooting

## 1. What you need

| You need | Notes |
| --- | --- |
| An Android phone with the Atalaia app | Android 8.0 or later. The app is not in Google Play yet: see the [Player manual](player.md) for installing it. Keep the phone charged, or on a power bank: it runs the whole game |
| A radio for the boxes | A **USB radio modem** (the Pi's modem board, plugged into the phone's USB) or an **I/O pod** (over USB or Bluetooth). Without one, only Android props on Wi-Fi can play. Which to choose: [section 6](#6-the-radio-usb-radio-modem-or-io-pod) |
| A field Wi-Fi network | The phone's own hotspot, a router, or a network the app makes for the game ([section 5](#5-the-network)). It does not need the internet |
| A computer on the field's Wi-Fi | For printing the check-in poster and labels, and for exports ([section 8](#8-what-needs-a-computer)) |

## 2. Start the controller

1. In the app, tap **Field controller**.
2. If it asks, allow notifications. Under **Battery optimisation may stop the controller mid-game.**, tap **Ask for the exemption**.
3. Under **Field's network**, choose how phones reach it ([section 5](#5-the-network)).
4. Turn on **Open on the field's Wi-Fi**. Without it, only this phone reaches the controller.
5. Under **Radio**, tap **Find pods** and pick your USB radio modem or I/O pod from the list ([section 6](#6-the-radio-usb-radio-modem-or-io-pod)). Choose the radio before you start: to change it later, stop the controller.
6. Check the **Field join key** in **Settings** (the gear) ([section 3](#3-codes-and-the-join-key)).
7. Tap **Start the controller**. The phone goes on running with the screen off.
8. Under **Access codes**, tap **Show the codes**.
9. Tap **Open the console**, or open one of the addresses under **The console, on computers on the field's network:** on a computer.

If you stop and start the controller, a live game goes on.

## 3. Codes and the join key

**Access codes.** Under **Access codes**, **Show the codes** shows two codes:

- the **Game master's code** runs the game. Do not show it to players;
- the **Read-only code (scoreboard)** only watches.

For a referee or a visiting GM, make a short-lived day code in the console (**Settings**, **Access tokens**; see the [Game master manual](game-master.md)) instead of giving the GM code away.

**The field join key** is the field's master secret: boxes get it when they are adopted, and a standby controller needs the same one. The phone keeps it in **Settings**, under **Field join key**.

- If none is set when you first start the controller, the app makes one and keeps it there.
- To use the key of an existing field (for example, the Pi's), type its 64 hex digits there before you start. On a Pi, `join-key` shows it ([Controller setup guide, section 5](controller-setup.md#5-first-start-codes-and-keys)).
- The app shows only the key's last digits afterwards, never the whole key. If you want a copy (for a standby controller, or in case the phone is lost), make the key yourself, type it in, and keep the copy somewhere safe.

**Field card.** Under **Field card**, **Write the field card** writes the join key on an NTAG215 or NTAG216 card with the phone's NFC; new boxes join the field when you tap the card on them. The app warns you first: whoever has that card can make join cards for your boxes. Keep it locked away.

<a id="the-controller-clock"></a>

## 4. The controller clock

**From v0.9.0 (not released yet; build from `main` until then)** the phone controller has the Raspberry Pi's clock guard. A phone's clock is usually right, set by the mobile network, but one that was reset, set by hand, or has had no network for long can be wrong.

1. The controller compares its clock with the day this software was released, with the newest time it has seen and with the newest data it holds.
2. If the clock is earlier, the console shows the yellow banner **The controller's clock is wrong.** on every screen, and nothing is deleted until it is right.
3. To set it, open the console on a device whose time is right and, in the banner or in **Settings › Controller clock**, tap **Set the controller's clock from this device** (GM code only). It moves **forward only**.
4. The setting lasts until the controller is stopped. The controller uses the corrected time when it tells the boxes the time and when it sends **Release every box not in this game**.

Games and timers never depend on the clock. Why the clock matters and what the guard does is in the [Controller setup guide](controller-setup.md#the-controller-clock).

## 5. The network

Under **Field's network**, choose one:

1. **The phone's own hotspot.** Tap **Hotspot settings** and turn it on. Keep its name and password: they go on the check-in poster.
2. **A router the phone joins.** Tap **Wi-Fi settings** and join it. The router must work with no internet and must not isolate its clients: the same rules as for a Pi, in the [Controller setup guide, section 8](controller-setup.md#using-a-travel-router).
3. **Make a network for the game.** Android picks a new name and password each time. Players join it from the QR code on the screen. Do not put them on the poster.

Then turn on **Open on the field's Wi-Fi**. Phones, computers and props connect over HTTPS (port 8443, with the field's own certificate authority) and MQTT over TLS (port 8883).

**TLS names.** There is no `tls_names` to set: the phone puts its own addresses, and the addresses saved on the check-in poster, in the field's certificate. The screen shows **The field CA's fingerprint**, which the poster carries. If the phone's address changes (another router, another hotspot), print the poster again.

**The field's Wi-Fi name on the poster.** In the console, **Check-in** tab, **Check-in poster** form, **The field's Wi-Fi network name**.

## 6. The radio: USB radio modem or I/O pod

Both carry the game's radio. They differ in what else they do:

| | USB radio modem | I/O pod |
| --- | --- | --- |
| What it is | The Pi's modem board ([Set up the radio modem](modem.md)) | A pod board with buttons, lights, a siren and an NFC reader as well |
| Link to the phone | USB only (an OTG data cable) | USB (preferred) or Bluetooth |
| Games with boxes | Yes | Yes |
| Invites, game over, pairing by code | Yes | Only with pod firmware that relays these frames; with an older pod the console says the radio carries none |
| Firmware updates for the boxes | Yes | Yes |
| Channel scan | Yes | Yes |
| Boxes still in an ended game reported and freed by themselves | Yes, with a modem image from v0.9.0 (not released yet) | **No**: an I/O pod cannot report them |
| Buttons, lights, siren for the phone | No | Yes |

To use a USB radio modem, follow [Set up the radio modem, With a phone controller](modem.md#with-a-phone-controller). Linking an I/O pod (its passkey over Bluetooth, linking again) is in the [Phone prop guide](phone-prop.md).

When the radio cannot report boxes still in an ended game, the screen says so under **Radio**: *This USB radio modem's firmware cannot report boxes still in an ended game: update it...* or *An I/O pod cannot report boxes still in an ended game...*. Until then, take such a box out at the box ([Field Box manual](field-box.md#take-a-box-out-of-its-game)).

The phone cannot adopt boxes over a USB cable. Adopt them with the **field card** or by **pairing code** (the console's **Adopt** tab).

<a id="standby-controller"></a>

## 7. A standby controller

A phone can stand by for a Pi, and a Pi for a phone. How a standby joins a game, what it refuses and how it takes over is in the [Controller setup guide, A standby controller](controller-setup.md#standby-controller). On the phone:

1. Give it the **same field join key** as the main controller ([section 3](#3-codes-and-the-join-key)).
2. In **Settings**, open **Site server, failover and ATAK (field controller)**. Under **Failover**, choose **Manual** or **Automatic**. *Manual: the GM promotes a standby controller. Automatic: a standby takes over after three missed beacons (30 s).* A standby counts the beacons it hears from the main controller, so behind a main controller on manual it waits about 90 s and does not take over a controller that still works ([Controller setup guide](controller-setup.md#failover-mode)). Give every controller of a game the same choice anyway: the console's **Controller** tab warns when they differ.
3. The setting applies when the controller next starts: stop it and start it again.
4. Join each game as a standby from the console's **Join** tab, **Join as a standby controller**, with the text the main controller made.
5. To take over by hand, tap **Promote to controller** in the console's **Controller** tab.

**Power.** A phone controller always counts as running on a small battery. When a phone and a Pi on mains both stand for the role, **the phone yields to the Pi**. There is no setting for this on the phone.

## 8. What needs a computer

The console built into the app cannot print or save files. Open the console in a computer's browser, at one of the addresses under **The console, on computers on the field's network:**, for:

- **the check-in poster** (**Check-in** tab, **Print the poster**). The poster needs the controller open on the field's Wi-Fi;
- **replica labels** (**Print labels**);
- **Export CSV** of the check-in list.

Everything else works in the app's own console.

## 9. Backups and how long data is kept

The phone controller keeps its games, codes, the field's certificate authority and its settings in the app's private storage. **There is no backup command.** If the app is removed or the phone is lost, they are gone:

- keep a copy of the field join key ([section 3](#3-codes-and-the-join-key)): with it, a new phone or a Pi takes over the field's boxes without adopting them again;
- players scan the new poster and trust the field again, since the certificate is new;
- boxes that were in a game when the phone was lost may stay in it: the [Game master manual](game-master.md#recover-from-problems) says how to free them.

**Retention.** The same periods as on a Pi: an ended game's events and scores 90 days, chrono readings 365 days, names and federation numbers 30 days after the game. Set the first two in the console, **Check-in › Check-in rules**. Nothing is deleted while the clock is wrong (from v0.9.0). The table is in the [Controller setup guide](controller-setup.md#how-long-the-controller-keeps-data).

**Site server.** In **Settings**, **Site server, failover and ATAK (field controller)**, the phone takes the field's site server address and API key, as a Pi's `[sync]` does. **Send walk-ins to the site server as guests** is the Pi's `push_walkins`: read the [Site admin manual](site-admin.md) before you turn it on.

## 10. Updates

**The app.** Install the new `atalaia-debug.apk` over the old one, between games. Android keeps the app's data (and so the controller's games, codes and key) only when the new file is signed with the same key as the old one: ask whoever builds it for you to use the same build machine. If Android refuses to install it over the old one, do not uninstall the app before you have a copy of the join key: uninstalling deletes everything in section 9.

**The radio.** A USB radio modem is updated over USB from a computer: [Set up the radio modem, Update the modem](modem.md#update-the-modem). An I/O pod: [Phone prop guide](phone-prop.md).

**The boxes.** Under **Firmware updates**, **Firmware release keys** lists the keys whose releases the phone accepts (one per line, 44 characters each), as the Pi's `[firmware] release_keys`. A phone that kept the project's earlier default switches to the new keys by itself; a list you typed by hand stays as it is. Since v0.8.0 the project's keys are:

```
5tzPkN0AJSn+g34CP59linCRf/fcaWFc7GAAg7qzYNc=
76eY5BoMQ4RHohhX/8iSUlIUA5o5Entfk7EFBUxpbSY=
```

Remove `rIO8ogMU3LRLLtnt6Rys+URdKYfmNv5mxvuRJQsX9Tw=` (retired on 2026-11-04) if you typed it. A running controller restarts to take the keys. The boxes fetch the release over the phone's HTTPS, so **Open on the field's Wi-Fi** must be on. The update itself is in the [Field Box manual](field-box.md#update-the-boxes).

## 11. Troubleshooting

| Problem | What to do |
| --- | --- |
| The controller stops when the screen is off | Allow notifications, and tap **Ask for the exemption** under the battery warning. If Android says *Android did not let the controller show its notification*, keep the app open |
| **No pod found.** under **Radio** | USB: a data cable (not charge-only) and an OTG adapter if the phone needs one. Bluetooth: the pod on and near. A USB radio modem shows in the same list |
| **To change the radio, stop the controller.** | The radio is chosen before **Start the controller**: stop it, pick the radio, start again |
| Phones cannot open the console or check in | **Open on the field's Wi-Fi** is off, or the phones are on another network, or the router isolates its clients ([section 5](#5-the-network)) |
| *This phone is on no Wi-Fi network* | Turn the hotspot on, join the field's router, or make a network for the game |
| *The check-in poster needs the controller open on the field's Wi-Fi.* | Turn on **Open on the field's Wi-Fi**, then print the poster from a computer |
| A yellow banner says **The controller's clock is wrong.** | Set it from a device with the right time (section 4) |
| The screen says the radio cannot report boxes still in an ended game | With an I/O pod: use a USB radio modem for that. With a modem: update it (section 10). Until then, take the box out at the box ([Field Box manual](field-box.md#take-a-box-out-of-its-game)) |
| *None: this controller takes no firmware release for the boxes.* | Put the project's release keys under **Firmware release keys** (section 10) |
| Settings in **Site server, failover and ATAK** do nothing | They apply when the controller next starts: stop it and start it again |

Found a step that does not match? Open an issue or tell us in [Discussions](https://github.com/vakaobr/atalaia-project/discussions).
