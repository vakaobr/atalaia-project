<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Runbook: indoor beacons on an iPhone (decisions IOSB-1 to IOSB-8)

`app/ios/Runner/BeaconScanPlugin.swift` ranges the field's iBeacons (GM tags and the Field Box's box beacons) through CoreLocation, on the same channels as Android's plugin. **It was written without a Mac: it has not been compiled by anyone but CI's `ios-build` job, and it has never run.** This is the checklist for the first time the maintainer's Mac and iPhone are free. The simulator cannot do it: it has no Bluetooth.

What should happen, in one line: with the player's app **on the screen**, in a running game that shares its position, the phone reports the strongest registered beacon (above -95 dBm) as a `ble` position; the controller turns it into room and floor; with the phone **locked** the position goes back to GPS and keeps the last floor.

## 0. What you need

- The Mac, Xcode and the iPhone as in [app/docs/ios-on-a-mac.md](../../app/docs/ios-on-a-mac.md) (iOS 15 or later; a free Apple ID works, the install lasts 7 days).
- A field controller (Pi, PC or Android phone) with a **field plan**, at least two levels if you can, and the phone checked in.
- **A GM tag**: any iBeacon transmitter (a beacon, or another phone with an iBeacon app) registered in the console's beacons panel (UUID, major, minor, room, level, place). Note its UUID.
- **A Field Box** on the bench board running a game: joined, **placed on the field view** (a box that is not placed is not registered), box beacons **on** (the console's beacons panel; Kconfig `ATALAIA_BOX_BEACON`, [protocol/box-beacon.md](../../protocol/box-beacon.md)). Its beacon is major 45253, minor its node id, the field's UUID. Put the box in a different room, or on a different level, from the tag.
- The console open on a laptop (the beacons panel, the log, the player's position).

## 1. Build and install

1. `git pull`, then follow ios-on-a-mac.md sections 4 to 9 (signing with your Apple ID, a suffix on the bundle id if `org.atalaia.app` is refused). Note the commit.
2. If Xcode shows a compile error in `BeaconScanPlugin.swift`, **stop and send the full message** (the file was never compiled): the likely places are the `@MainActor` and `@preconcurrency` extensions (copied from `LocationPlugin.swift`) and the `CLBeaconIdentityConstraint` calls. Also check it appears in Runner's *Build Phases > Compile Sources* (the project file was edited by hand).
3. Run on the iPhone. Join the field (QR or typed) and check in.

Pass: the app starts, joins, and nothing about beacons is asked yet.

## 2. The permission prompts

1. A running game; open the player screen; turn **Share my position** on.
2. iOS asks for the **location**: choose **Allow While Using App**. (Only this prompt: **no Bluetooth prompt and no *Always* are expected**. If a Bluetooth prompt appears, note it: it is a defect.)
3. The app then shows **Indoor positions**, saying the iPhone asks only for the location and that beacons work only while the app is open. **Not now**: the app says *Indoor positions are off* and goes on with GPS. Turn sharing off and on again; this time **Continue**: nothing new is asked (the location is already allowed), and the note under the switch reads *Listening for the field's beacons, only while Atalaia is open on the screen...*.
4. Refusal path: Settings > Atalaia > Location > Never, share again: the switch stays off with the iPhone message (existing behaviour). Set it back to While Using the App. Then try **Allow Once** and re-open: asked again next time.
5. Bluetooth off (Control Center) with sharing on: expected, **no error is shown** (iOS cannot tell without a Bluetooth permission, IOSB-4); the beacons are simply not heard and the position stays GPS. Note what you see.

## 3. A tag and a Field Box

Walk, phone in hand, app on the screen, sharing on, a game running, the console's player view open. For each of the two (the tag, then the box), and then both:

1. Stand about 1 m from it. Within about two beacon intervals (the game's interval, 5 s by default) the console shows the phone's position as **that beacon's room and level** (the box's name or room; the tag's room), and the player screen shows *Your position: <room>*.
2. Walk to the other (the box in the other room or level): the position **switches to its room and floor**. Walking back switches again. Note the delay.
3. Between them, with both audible, the **stronger** one wins.
4. Walk away until neither is heard (or beyond about 10 m / two walls): after about two intervals the position goes back to **GPS** (an outdoor fix) and the console says so.
5. If the field has levels: the floor picker is replaced by the beacon's floor while a beacon is heard (*the floor from a beacon*), and comes back when it is not.

Expected differences from Android, not defects: the first reading takes about a second longer than a window; a quieter or noisier signal (iOS averages one second at a time).

Pass: both kinds of beacon give a room and floor; the strongest wins; the fall back to GPS works.

## 4. Foreground, locked, other app

With a beacon in range and the position showing its room:

1. **Lock** the phone (side button) for a minute, then unlock and open Atalaia. Expected: while locked, no beacon reports (the console's position goes back to GPS/last known, **and the last floor is kept**); a few seconds after the app is on the screen again, the beacon is back without any action.
2. Switch to **another app** for a minute and return: the same.
3. Check that nothing was sent from the background (the console's report times show a gap while away).

Pass: foreground works; locked and background fall back to GPS and the last floor, and recover alone.

## 5. Battery

Ranging beacons is a CoreLocation task that wakes the radio about once a second; the windowing only reduces what the app sends. Note: 30 minutes with the screen on, sharing on, with and without beacons (iPhone Settings > Battery shows the app's share; note the percentage lost with the same brightness). Expect it to be near the cost of GPS sharing; more than about 10 % per hour above GPS only is worth reporting. The status bar's blue location indicator should be on while sharing on the screen, and off when sharing stops.

## 6. What to send back

- The commit, the iPhone model and iOS version, Xcode version.
- Every Xcode build error or warning from `BeaconScanPlugin.swift` (text, not a photo).
- The app's log for a session: Xcode's console (Window > Devices and Simulators > the phone > *Open Console*), filtered by `Atalaia`; or a screen recording.
- Screenshots: the **Indoor positions** dialog, the player screen with the note and *Your position*, the console's player view at each step of section 3 (with the beacons panel showing the tag and the Field Box), and the iPhone's Settings > Atalaia page.
- For each step above: pass or fail, and the seconds it took to switch rooms.
- The beacon list as the controller serves it (`GET /api/v1/beacons` with a player token, or the console's beacons panel), so the UUIDs and ids can be matched to what the phone heard.
- Anything surprising: a Bluetooth prompt, a Local Network prompt appearing at a new time, a crash, the app killed in the background, a beacon heard from the wrong room.

If everything passes, the decisions IOSB-1 to IOSB-8 are confirmed by test and the "not run on an iPhone yet" notes in app/README.md, ios-on-a-mac.md and the player manual can go.
