<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# The app on an iPhone, from a Mac

A step-by-step guide for the first tests (decisions iOS-1 to iOS-16 in
[docs/review/decisions-to-review.md](../../docs/review/decisions-to-review.md)).
The project in [`ios/`](../ios/) was generated and edited on Linux with the
pinned Flutter; it was first built on a Mac on 2026-10-26 (Xcode 27.1, macOS
27.0, Apple silicon: `flutter build ios --release --no-codesign`) and the same
day installed and opened on an iPhone 15 Pro Max (iOS 27.2 beta, Xcode 27.2,
free Personal Team), where checks 1 to 4 below passed; CI's `ios-build` job
compiles it on a Mac runner. If a step differs on your machine, the
troubleshooting list at the end is where to look first, and please write down
what you found.

## What you need

- A Mac (Apple silicon or Intel) with about 40 GB free, and an iPhone with a USB
  cable (Lightning or USB-C). iOS 15 or later (an iPhone 6s or later); for NFC, an iPhone 7 or later.
- An Apple ID. A **free** one is enough for these first tests (see
  [Free account or paid](#free-account-or-paid)).
- Xcode, CocoaPods and Flutter 3.44.0, installed below.

## 1. Xcode and the command line tools

1. Install **Xcode** from the Mac App Store (it is large: several GB to download,
   about 15 GB installed). Open it once, accept the licence, let it install its
   extra components.
2. In Terminal:

   ```sh
   sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer
   sudo xcodebuild -runFirstLaunch
   xcodebuild -downloadPlatform iOS      # only if Xcode says the iOS platform is missing
   ```

3. Apple silicon only, if a tool complains about an Intel binary:
   `sudo softwareupdate --install-rosetta --agree-to-license`.

## 2. CocoaPods

```sh
brew install cocoapods        # or: sudo gem install cocoapods
```

Flutter 3.44 builds iOS plugins with Swift Package Manager when every plugin
supports it, and this app's only plugin, `webview_flutter`, does: the
repository has no `Podfile` and `pod install` is normally not needed. Flutter
and `flutter doctor` still want CocoaPods installed, and if a later plugin
brings a Podfile you will need it (step 6).

## 3. Flutter 3.44.0 (the version the project pins)

With [fvm](https://fvm.app) (several Flutter versions side by side):

```sh
brew tap leoafarias/fvm && brew install fvm
fvm install 3.44.0
```

or the exact tag, by hand:

```sh
git clone --depth 1 --branch 3.44.0 https://github.com/flutter/flutter.git ~/flutter-3.44.0
export PATH="$HOME/flutter-3.44.0/bin:$PATH"      # also in ~/.zshrc
```

Then `flutter --version` must say 3.44.0 (Dart 3.12). With fvm, write
`fvm flutter` for `flutter` below, or run `fvm use 3.44.0` inside `app/`.
Run `flutter doctor -v`: the Xcode, CocoaPods and "Connected device" lines
must be green once the iPhone is plugged in (Android and Chrome lines may stay
red; this app needs neither here).

## 4. Get the code

```sh
git clone https://github.com/vakaobr/atalaia-project.git
cd atalaia-project/app
dart tool/sync_console.dart                 # the GM console and the check-in notices into assets/ (not committed)
flutter pub get --enforce-lockfile          # the exact packages of pubspec.lock
```

`sync_console.dart` is not optional: `pubspec.yaml` lists `assets/console/`,
which exists only after it runs, and Flutter refuses to build without it.

## 5. Make the Xcode project ready, then open it

```sh
flutter build ios --config-only --release
open ios/Runner.xcworkspace            # the workspace, not Runner.xcodeproj
```

`--config-only` writes `ios/Flutter/Generated.xcconfig` and the plugin package
(`ios/Flutter/ephemeral/`, both git-ignored) without building.

## 6. If CocoaPods is needed

Only if `flutter build` or Xcode says "CocoaPods not installed" or a `Podfile`
appeared:

```sh
cd ios && pod install --repo-update && cd ..
```

(`pod repo update` alone fixes "unable to find a specification for ...".)
Always open the `.xcworkspace` after that.

## 7. Signing, with a free Apple ID

1. Xcode, **Settings (Cmd-,) > Accounts > +**, add your Apple ID. A
   "Personal Team" appears.
2. In the project navigator pick **Runner** (the blue icon), target **Runner**,
   tab **Signing & Capabilities**:
   - tick **Automatically manage signing**;
   - **Team**: your name (Personal Team);
   - **Bundle Identifier**: `org.atalaia.app` (the same as Android's). Apple
     lets a bundle id belong to one team only, so if Xcode says "Failed to
     register bundle identifier" or "is not available", add a suffix only for
     your own builds, for example `org.atalaia.app.anderson`. The app does not
     look at its own bundle id; do not commit that change.
   - Leave the capability list as it is: **do not add "Near Field
     Communication Tag Reading"** with a free account (next section).
3. Target **RunnerTests** can stay unsigned; it is not built for a phone.

## Free account or paid

| | Free Apple ID ("Personal Team") | Apple Developer Program (about 99 USD a year) |
| --- | --- | --- |
| Install on your own iPhone from Xcode or `flutter run` | yes | yes |
| How long the install lasts | **7 days**, then it will not open until reinstalled | one year (development profile); TestFlight builds 90 days |
| Apps and App IDs | few: about 3 apps per phone and 10 new App IDs a week | no practical limit |
| Everything this guide tests: network, QR scanning, `atalaia://` links, player feed, positions (on the screen), languages, the GM web view | yes | yes |
| **NFC tag reading** (the capability and its `com.apple.developer.nfc.readersession.formats` entitlement) | **no**: Xcode refuses the capability for a Personal Team and signing fails | yes |
| Push notifications, iCloud, Associated Domains, background modes needing a capability | no | yes |
| TestFlight, installing on other people's phones, the App Store | no | yes |

So: **a free account runs everything the app does on iOS today** (it has no
NFC code for iOS yet, so no entitlement is declared and signing works; the QR
scanner, the `atalaia://` links and the position need no entitlement either). The
day the NFC side is written, NFC testing needs the paid program; the same goes
for giving the app to players through TestFlight. This is a decision for the
maintainer (iOS-10).

## 8. The iPhone

1. Plug it in, unlock it, tap **Trust This Computer**.
2. **Developer Mode** (iOS 16 and later): Settings > Privacy & Security >
   Developer Mode > on, then restart when asked. The switch only appears after
   Xcode has tried to install something on the phone once; if it is missing,
   run step 9 once, let it fail, then come back.
3. Check Flutter sees it: `flutter devices` (note the id of the iPhone).

## 9. Run it

```sh
cd app
flutter run --release -d <iphone id>
```

Use `--release`: since iOS 14 a debug build opens only while attached to Xcode.
The first build takes several minutes. If a keychain dialog asks for your Mac
password, "Always allow".

The first start on the phone says **Untrusted Developer**: Settings > General >
**VPN & Device Management** > your Apple ID under Developer App > **Trust**,
then open the app again.

## The 7-day expiry

A free profile lasts 7 days. After that the icon stays, but the app will not
start. Reinstall with the same command (`flutter run --release -d <id>`, or Run
in Xcode) while the phone is connected: it replaces the app and **keeps its
settings**, because the bundle id is the same. Do not delete the app first, and
do not change the bundle id between installs (that is a different app, with
none of the saved field join key, marshal key or settings). Put a reminder on
day 6 before a field test.

## Tests on the Mac (the Dart tests, not the iPhone)

The app's Dart tests load the C core through `dart:ffi`, so the core has to be
built for the Mac first (`brew install cmake`; from the repository root):

```sh
cmake -S core -B build -DATALAIA_SHARED=ON
cmake --build build
cd app && flutter test test/ffi test/ui
```

The libraries are `build/libatalaia_core.dylib` and
`build/libatalaia_core_stub.dylib`, which the tests find by themselves. The
whole of it, what is left off on a Mac and why, is in the app's README
("Tests on a Mac"). This was written without a Mac: if the build or a test
stops, copy the first error into the session.

## Troubleshooting

- **"Untrusted Developer" / the app closes at once**: trust the certificate
  (above). Also check Developer Mode is on. On the first `flutter run` this is
  expected: the app is installed but iOS refuses to open it ("invalid code
  signature, inadequate entitlements or its profile has not been explicitly
  trusted by the user"), and `flutter run` only says "Could not run
  build/ios/iphoneos/Runner.app ... Error running application". Trust the
  certificate (Settings > General > VPN & Device Management) and open the app,
  or run again.
- **A run that worked fails with "Could not run build/ios/iphoneos/Runner.app"**:
  with a free Personal Team, Xcode may refresh the provisioning profile between
  installs (a debug and a release build, an integration test, a new profile),
  and iOS then asks to trust the developer certificate again, even if you
  trusted it earlier the same day. Look in Settings > General > VPN & Device
  Management for a new trust prompt, trust it, and run again (seen on the
  iPhone on 2026-10-26: `site_registration_test.dart` then passed with no
  other change).
- **No Developer Mode switch on the iPhone**: it appears only after Xcode has
  tried to run something on the phone once: pick the iPhone as the run
  destination in Xcode's toolbar and press Run (Xcode 27 has no Window >
  Devices and Simulators any more).
- **"Failed to register bundle identifier"**, "No profiles for ... were found":
  the bundle id belongs to another team; add a suffix (step 7).
- **"Communication with Apple failed" / "no devices"**: Xcode > Settings >
  Accounts > Download Manual Profiles; reconnect the cable; unlock the phone.
- **"Failed to prepare device for development"**, "connected (no DDI)", or
  the phone's iOS is newer than Xcode knows: update Xcode (App Store; a beta iOS
  may need the matching Xcode beta: iOS 27.2 needed Xcode 27.2), then select the
  iPhone as the run destination and press Run once.
- **`flutter build ios --simulator` fails with "Binary ... Flutter.framework/Flutter
  does not contain architectures "arm64 x86_64""** (Xcode 27.2, Flutter
  3.44.0): Flutter's tooling runs `lipo <binary> -verify_arch arm64 x86_64`,
  which Xcode 27.2's `lipo` refuses ("-verify_arch requires exactly one input
  file") although the framework has both. Not the app's fault; builds for an
  iPhone are not affected. Use `flutter run -d <simulator id>`, which builds
  only the Mac's own architecture.
- **`git status` shows `ios/Runner.xcodeproj/project.pbxproj` and
  `Runner.xcscheme` changed** after the first build: Xcode 27 upgrades the
  project's format ("Updating project for Xcode compatibility") and writes your
  team (`DEVELOPMENT_TEAM`). Do not commit your team; `git checkout -- ios/`
  before pulling.
- **`errSecInternalComponent` or "CodeSign failed"** from the terminal: unlock
  the login keychain (`security unlock-keychain ~/Library/Keychains/login.keychain-db`)
  or build once from Xcode and Allow.
- **"CocoaPods not installed" or "unable to find a specification"**: step 2 and
  step 6 (`pod repo update`).
- **Architecture errors or `ffi` complaints on Apple silicon**: Rosetta (step 1),
  and `sudo arch -x86_64 gem install ffi` only if you installed CocoaPods with gem.
- **"Unable to find directory 'assets/console/'"**: `dart tool/sync_console.dart` (step 4).
- **A strange build state** after changing Flutter versions: `flutter clean`,
  delete `ios/Flutter/ephemeral/` and `ios/Pods/`, then step 5 again.
- **TLS to the field controller fails on iOS but works on Android**: check the
  server certificate's validity. Apple's SecTrust (iOS and macOS, what `dart:io`
  uses there) refuses any TLS server certificate valid for more than 825 days,
  private CAs included; Android does not. The field's own are 365 days
  (`SERVER_DAYS`, `serverDays`; the CA's 3653 days are fine) and guard tests
  keep them under 825.
- **Local network**: the first time the app talks to the controller, iOS asks
  "Atalaia would like to find and connect to devices on your local network".
  Answer **Allow**. If you said no: Settings > Atalaia > Local Network.

## What to try on the iPhone

Write each result down (works, does not, what the screen said), with the iOS
version.

Before the field:

1. Install, open, and say which language the app starts in. Settings: switch
   Portuguese, English, German and Traditional Chinese; every screen changes,
   no square boxes in the Chinese text, nothing cut off on the small iPhone.
2. The role selector shows **player, marshal and GM** and no prop. The phone
   controller (field controller on the phone) is not offered either.
3. Close the app and open it again: the settings and the field join key are still
   there (this proves the app's private folder, the one native piece written for
   iOS).
4. The app icon (dark green with a gold tower), the launch screen (dark green,
   no white flash) and the name "Atalaia" on the home screen; the permission
   texts in the phone's language when asked.

At a field controller (a Pi's or an Android phone's, on its Wi-Fi):

5. Join the field's Wi-Fi; iOS will say "no internet": stay connected. The
   **Local Network** prompt appears: Allow.
6. Join a game by typing the **join text** or the controller's address and read
   code, **or by scanning a QR code** (join card, field poster): see "QR
   scanning" below. On the simulator, which has no camera, the app says so and
   offers the typed way.
7. **Player feed**: time, points, objectives, eliminations, the GM's messages,
   over the controller's HTTP or HTTPS (the WebSocket stays up with the
   screen on; note what happens after 30 s with the screen locked, and after
   switching to another app and back).
8. **Positions**: the player's *Share my position* switch, while the app is
   on the screen: see "Position sharing" below. It stops when the app leaves
   the screen, and the screen says so (the note under the switch).
9. **Marshal**: the chrono check-in screens; limit templates in your language;
   the signed record stays on the phone.
10. **GM**: type the console's address (`http://192.168.4.1:8080/console/`): the
    console loads in the app's web view, works with the touch screen, the GM can
    send a message and end a game. Try a console served over HTTPS with the
    field's own certificate too: it is expected to **fail** in the web view
    (iOS does not trust the field CA there; see below), and to work in Safari
    after trusting the profile.
11. The haptic buzz and the screen staying awake while a game is shown. The
    player view buzzes on a message from the GM (one longer tap), a box of the
    player's team captured (one short tap) or lost (two), the game starting
    (three quick taps) and ending (two medium taps), and on a squad's new
    orders (two medium taps); Settings has a "Vibrate on game events" switch
    (on by default; the squad-orders buzz and the out-of-bounds warning do not
    follow it). Check, with a second phone or the console sending the messages,
    that the five patterns can be told apart on the iPhone (VB-6: iOS cannot
    set a buzz's length, so each pulse is a tap of the haptic engine, or the
    system vibration for a long one), that nothing buzzes with the switch off,
    and that the Vibrate on Ring/Silent settings and System Haptics are
    respected. An iPhone without the haptic engine (6s) buzzes only for the
    long pulses.

Needs a paid account, or is not written yet, so expect it **not** to work:

12. NFC reading and writing of players' tags and join cards (no Swift side, no
    entitlement); the field card written by NFC.

### QR scanning (decision iOS-13)

The scanner is the app's own full-screen camera view (AVFoundation), the same
contract as Android's: the camera picture, the hint under it, a cancel button;
the first QR code read ends it and fills the join text.

- **Simulator** (no camera): the player's join screen and the marshal's replica
  registry (its QR tag) answer "There is no camera to read the code." (`join.no_camera`);
  the typed text still works. Nothing crashes, nothing hangs.
- **Phone**, first use: iOS asks "Atalaia would like to access the camera"
  (the text from `Info.plist`, in the phone's language). **Allow**: the camera
  opens full screen. **Don't Allow**: the scanner closes at once with nothing
  scanned (as Android's); to change it, Settings > Atalaia > Camera.
- Point it at a join card or a field's QR code (the check-in poster): the scanner closes and the app joins as
  if the text had been typed. A QR code that is not an Atalaia one is read and
  refused by the app ("This is not a valid join code"), not by the scanner.
- Cancel button: the scanner closes, nothing is scanned. Turn the phone to
  landscape while scanning: the picture stays upright and the bar stays at
  the bottom. Switch to another app and back while scanning: the picture
  resumes.
- Where it is used: the player's join and the marshal's replica registry QR
  tag (the Android prop's join screen has the same button; props are Android only).

### `atalaia://` links (decision iOS-14)

A site server's register page has an *Open in the app* button with an
`atalaia://register?site=...&field=...&game=...` link. The app's registration
screen opens with the site and the field to confirm.

On the **simulator** (booted; the app installed):

```sh
# the app is closed (cold start): the link starts it
xcrun simctl terminate booted org.atalaia.app
xcrun simctl openurl booted 'atalaia://register?site=https%3A%2F%2Fcampo.example.pt&field=campo-de-teste'

# the app is open (while running): the registration screen opens over the current one
xcrun simctl openurl booted 'atalaia://register?site=https%3A%2F%2Fcampo.example.pt&field=campo-de-teste&game=00000000-0000-4000-8000-000000000001'

# not ours, or not a valid site: nothing opens, nothing crashes
xcrun simctl openurl booted 'atalaia://register?site=http%3A%2F%2Fevil.example&field=x'
xcrun simctl openurl booted 'atalaia://elsewhere'
```

(`site` is the site server's origin, percent-encoded: an `https://` one, or
`http://` for localhost; the app checks it, `lib/site/site_link.dart`.) The
first time, Simulator or iOS may ask "Open in Atalaia?": **Open**.

On the **phone**: open the same link from Notes or Messages (a tapped
`atalaia://register?...` link), or from Safari with the site server's register
page. Cold start (app swiped away) and while running must both open the
registration screen. If nothing happens, check `Info.plist` has
`CFBundleURLTypes` with `atalaia` and the app was reinstalled after that.

### Position sharing (decision iOS-15), when in use only

On the player's screen, the *Share my position* switch (a field that took the
phone's check-in): under it, a note says that on iPhone the position is shared
only while Atalaia is on the screen.

- **First use**: turn the switch on: iOS asks "Allow Atalaia to use your
  location?" with **Allow While Using App** and **Allow Once**; there is no
  "Always" on offer (no background mode). If the phone gave only the
  *approximate* location (the *Precise Location* switch off in the prompt or
  in Settings), iOS then asks once for a temporary precise location with the
  app's text: **Allow** for a field test.
- **Refused**: the switch stays off and the screen says how to allow it
  (Settings > Atalaia > Location > While Using the App, and Location Services
  on). *Allow Once* asks again the next time the app is opened.
- **Sending**: with the controller up, *sent* counts up about every 10 s
  (the controller's interval); the GM console sees the player. The positions
  carry the phone's accuracy (metres), altitude, heading and speed when the
  phone knows them.
- **Leaving the screen**: switch to another app or lock the phone: the
  reports stop (iOS suspends the app); come back: they go on by themselves.
  The status bar's blue location indicator is shown while it runs on the
  screen. Nothing is sent from the background; that is by design (iOS-5).

On the **simulator**: Features > Location > *Custom Location...* (a latitude
and a longitude), *City Run*, *Freeway Drive*, or from a terminal:

```sh
xcrun simctl location booted set 38.7223,-9.1393          # one place
xcrun simctl location booted start --speed=2 --interval=1 38.7223,-9.1393 38.7230,-9.1385   # a walk (stop it with `set` or `clear`)
xcrun simctl location booted clear
xcrun simctl privacy booted reset location org.atalaia.app    # ask for the permission again
xcrun simctl privacy booted grant location org.atalaia.app    # skip the prompt (`revoke` to test a refusal)
```

The simulator's location prompt and the temporary-precision prompt appear as
on a phone. Check the fix goes on while you change the simulated place, and
the controller's console follows.

## Integration tests on the iPhone

The other on-device tests run the same way (`flutter test integration_test/<file>
-d <iPhone or simulator id>`). State on 2026-10-26:
`integration_test/site_registration_test.dart` passes on the iPhone (1/1) and in
the simulator; `integration_test/check_in_test.dart` failed on the iPhone on its
fixed 10-year server certificate (see Troubleshooting), now makes a 365-day one at
run time and passes in the simulator (2/2). `controller_test.dart`,
`game_flow_test.dart`, `medic_kit_test.dart` and `role_switching_test.dart` are
Android only (the phone as field controller, props on the game core).

`integration_test/ios_checklist_test.dart` does by itself what can be checked
without a human in items 1 to 3 and 5 to 11 of the checklist above. It runs on
the iPhone, in the iOS simulator and (the parts that need no iOS) on an Android
emulator, where CI runs it with the other files of `integration_test/`. It uses
no golden images: layout overflows are caught as the framework reports them
(`FlutterError.onError`) and the texts are looked for in the app's own language
tables, with Settings' titles also written out literally.

From `app/`, with the iPhone plugged in and signed as in steps 7 to 9 (the test
is built and installed like `flutter run`, with the same bundle id), or with a
simulator's id from `flutter devices`:

```sh
flutter test integration_test/ios_checklist_test.dart -d <udid> --reporter expanded
```

To follow a real field controller as well, give its address and its tokens (the
controller's *read* token and, for the marshal list, the GM token; the real
values never go in a file that is committed or in a shared note):

```sh
flutter test integration_test/ios_checklist_test.dart -d <udid> --reporter expanded \
  --dart-define=ATALAIA_TEST_CONTROLLER=http://192.168.1.183:8080 \
  --dart-define=ATALAIA_TEST_READ_TOKEN=<read token> \
  --dart-define=ATALAIA_TEST_GM_TOKEN=<GM token>
```

`--dart-define=ATALAIA_TEST_GAME=<game id>` picks the game the test player
checks in to when the controller lists several (the first one is used
otherwise). The first time the app talks to the controller, iOS shows the Local
Network prompt on the phone: answer **Allow** (the player test waits 30 s for
the feed, so there is time; after a "Don't Allow" it fails with the feed never
opening, and Settings > Atalaia > Local Network is where to turn it on). Keep
the phone unlocked, as for `flutter run`; tests run as a debug build, which is
fine while Flutter is attached.

| Checklist | Test | What it checks |
| --- | --- | --- |
| 1 | the app starts in Portuguese | a fresh start shows Portuguese (the app's default, not the phone's language): the "O que vais fazer neste telemóvel?" title and the role cards |
| 1 | each language ... no overflow | Settings switches pt, en, de, zh-tw and back; each is shown by Settings' title and the texts of Home, Player, Marshal and GM, on a 320 x 568 pt screen (the small iPhone; if the device ignores the size the check still runs at its own): no `RenderFlex overflowed` error, no other framework error. The look of the Chinese glyphs (no square boxes) stays a human check |
| 2 | the roles | player, marshal and GM, no prop and no field controller, and the "só o Android ..." note; on Android both are offered and the note is absent |
| 3 | the settings are written ... and survive a restart | the device channel gives a private folder; in a folder of the run's own inside it (`itest-settings-<time>/`, removed afterwards: the installed app's own `settings.json` is never touched) the language, the vibration switch and the join key are changed through the screens and the file is read back; the widget tree is dropped, the settings are loaded from the same folder as `main()` does and the app shows English, the switch off and the key's end |
| 3 | About shows the version | `Atalaia <appVersion>` from `lib/version.dart` in Settings > About (`test/version_test.dart` ties that to `pubspec.yaml`); on iOS also "no game core" |
| 5, 7 | a player joins the controller ... | needs `ATALAIA_TEST_CONTROLLER` and `ATALAIA_TEST_READ_TOKEN`. Through the screens: the address and code typed, *Connect*; the game's name and a row for each team within 30 s; then, for a running game, one more message of the feed (a box's score, node or event) within 20 s, with the clock on screen (the boxes report every 15 s, SL-*). A game that is not running only has the first part (the test says so in its output) |
| 6 | scanning a QR code with no camera | in the simulator (no camera): the scanner is not available (`ChannelQrScanner`), *Scan* answers "there is no camera to read the code" and the address and *Connect* stay; no exception. Skipped on a phone with a camera (scanning a real code is a person's check, iOS-13) and on Android |
| 8 | sharing the position | a check-in's player view of a running game (a stand-in feed) shows the switch and the iOS note (only while the app is in front, iOS-16); when the app already has location permission (`xcrun simctl privacy booted grant location org.atalaia.app` in the simulator) turning it on starts sharing, otherwise the test stops there (the permission prompt is a person's check); no exception. Skipped on Android |
| 9 | a player who is not on the GM's marshal list is refused | needs `ATALAIA_TEST_CONTROLLER`. Checks a new test player in at the controller (through the app's own client, display name `itest-ios`, and out again with `DELETE /checkin/me`) and opens the Marshal role: the "not on the marshal list" notice, no tools, nothing kept |
| 9 | a player the GM lists is accepted ... | needs `ATALAIA_TEST_CONTROLLER` and `ATALAIA_TEST_GM_TOKEN`. The same kind of test player is added to the marshal list with the GM API (`POST /api/v1/marshals`) and the Marshal role opens its tools (the app asks for a new token, takes the id the list gave and registers its key); the player is taken off the list (`DELETE /api/v1/marshals/<id>`) and the next opening says the marshal was removed. Off the list again, and out of the game, however the test ends |
| 10 | the GM screen opens an address in the web view | the GM role opens `127.0.0.1:<port>` of a small server the test starts on the phone, and the real web view loads its page (the title is read from the web view, and the server saw `GET /console/`); with `ATALAIA_TEST_CONTROLLER` also the controller's own console, which needs no login to load. Skipped on Android and where there is no device web view |
| 11 | the phone buzzes ... | the player view follows a stand-in stream on the loopback address (the real dart:io WebSocket) and a fake device service records the vibrations: none for the snapshot's events, then game start, a GM message, a box of the player's team captured and one taken, and game end each play their own pattern from `field_buzz.dart`; a box taken from nobody plays nothing, and with "Vibrate on game events" off nothing buzzes. How the taps feel, and the Ring/Silent and System Haptics settings, stay a human check |

A test that needs a define it was not given is shown as skipped, with the
define's name in its output. The tests that need no controller use only the
phone's own loopback address, and nothing writes in the installed app's own
settings. The same file also runs as a plain widget test on a computer (the app
then plays an iPhone and the web view checks are skipped), which is how it is
kept compiling and passing without a phone.

Left to a person: item 4 (icon, launch screen, names), item 5's Wi-Fi without
internet, item 7's lock screen and app switching, the feel of the buzz patterns
and the Chinese glyphs in item 1, a console over HTTPS (item 10), and
everything under "Needs a paid account".

## What does not work on iOS, and why

- **A prop** (the phone as a game box: the core, the game loop, kiosk, the
  foreground service, NFC in the background, the I/O pod over USB or Bluetooth)
  is Android only (ADR-P3-10, decision PD10). The role is hidden; the node
  runner reports "no core" on iOS: the C core is not built for iOS.
- **The phone as field controller** (`app/lib/controller`, `controllerRoleAvailable`
  is Android only) cannot run on iOS, for four reasons recorded in decision
  iOS-8: it needs the core (not built for iOS); iOS suspends an app a few
  seconds after it leaves the screen and gives a game server no equivalent of
  Android's foreground service, wake lock and Wi-Fi lock, so its HTTP, MQTT and
  WebSocket servers would stop mid-game; it needs the USB radio modem and the
  I/O pod's USB link, which an iPhone cannot open (no USB serial host access
  without Apple's MFi programme); and it starts the field's Wi-Fi (a local-only
  hotspot) from code, which iOS does not allow. An iPhone is a player, a marshal
  or a GM, joining a field controller that runs on a Pi, a PC or an Android phone.
- **NFC**: the app's Kotlin plugin has no Swift twin yet, and CoreNFC needs a
  paid account's entitlement (iOS-10); the Dart side answers "not available"
  (`MissingPluginException` is read as unavailable) and falls back to typing.
  (The QR scanner, the `atalaia://` links and the position now have their
  Swift sides: iOS-13 to iOS-15. The tones, the screen brightness and the
  permission requests other than the location stay unanswered.)
- **The GM console over HTTPS with the field's own CA**: the app pins that CA in
  its own HTTP client (`dart:io`, which iOS's App Transport Security does not
  govern), but the web view (WKWebView) knows nothing of the pin. The app's
  App Transport Security setting allows plain `http` to local-network
  addresses (`NSAllowsLocalNetworking`: IP addresses, `.local` names and
  single-label hosts, nothing else), so a console on `http://192.168.x.x` works;
  an `https://` console with the field CA's certificate, or `http://` to a
  public host name, is refused by iOS.
- **Bluetooth**: nothing on iOS uses it (the I/O pod's BLE link is Android's),
  so the app asks for no Bluetooth permission. **mDNS**: the app does not use it
  (the controller's address comes from the join), so no Bonjour entry.
- **Background**: no background modes. A position or a feed is live only while the
  app is on the screen: the position stops when the app leaves it and goes on
  when it comes back, and the player screen says so (iOS-15).
