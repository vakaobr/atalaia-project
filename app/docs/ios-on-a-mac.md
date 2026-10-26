<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# The app on an iPhone, from a Mac

A step-by-step guide for the first tests (decisions iOS-1 to iOS-12 in
[docs/review/decisions-to-review.md](../../docs/review/decisions-to-review.md)).
Nothing here has been run on a Mac yet: the project in [`ios/`](../ios/) was
generated and edited on Linux with the pinned Flutter, and CI's `ios-build`
job compiles it on a Mac runner. If a step differs on your machine, the
troubleshooting list at the end is where to look first, and please write down
what you found.

## What you need

- A Mac (Apple silicon or Intel) with about 40 GB free, and an iPhone with a USB
  cable (Lightning or USB-C). iOS 13 or later; for NFC, an iPhone 7 or later.
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
| Everything this guide tests: network, QR (when written), player feed, positions, languages, the GM web view | yes | yes |
| **NFC tag reading** (the capability and its `com.apple.developer.nfc.readersession.formats` entitlement) | **no**: Xcode refuses the capability for a Personal Team and signing fails | yes |
| Push notifications, iCloud, Associated Domains, background modes needing a capability | no | yes |
| TestFlight, installing on other people's phones, the App Store | no | yes |

So: **a free account runs everything the app does on iOS today** (it has no
NFC code for iOS yet, so no entitlement is declared and signing works). The
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

## Troubleshooting

- **"Untrusted Developer" / the app closes at once**: trust the certificate
  (above). Also check Developer Mode is on.
- **"Failed to register bundle identifier"**, "No profiles for ... were found":
  the bundle id belongs to another team; add a suffix (step 7).
- **"Communication with Apple failed" / "no devices"**: Xcode > Settings >
  Accounts > Download Manual Profiles; reconnect the cable; unlock the phone.
- **"Failed to prepare device for development"** or the phone's iOS is newer
  than Xcode knows: update Xcode (App Store); Xcode > Window > Devices and
  Simulators shows what is missing.
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
   code. Scanning a QR code is **not available on iOS yet** (the camera
   scanner is written for Android only): the app should offer the typed way
   without a crash, and it should say so, not hang.
7. **Player feed**: time, points, objectives, eliminations, the GM's messages,
   over the controller's HTTP or HTTPS (the WebSocket stays up with the
   screen on; note what happens after 30 s with the screen locked, and after
   switching to another app and back).
8. **Positions** (the player sharing their position) are Android-only for now:
   the setting should be missing or disabled, not crash.
9. **Marshal**: the chrono check-in screens; limit templates in your language;
   the signed record stays on the phone.
10. **GM**: type the console's address (`http://192.168.4.1:8080/console/`): the
    console loads in the app's web view, works with the touch screen, the GM can
    send a message and end a game. Try a console served over HTTPS with the
    field's own certificate too: it is expected to **fail** in the web view
    (iOS does not trust the field CA there; see below), and to work in Safari
    after trusting the profile.
11. The haptic buzz (a short vibration on events that ask for one) and the screen
    staying awake while a game is shown.

Needs a paid account, or is not written yet, so expect it **not** to work:

12. NFC reading and writing of players' tags and join cards (no Swift side, no
    entitlement); the field card written by NFC.
13. The `atalaia://register?...` link from a site server's page (the iOS side of
    links is not written; open the app and type or scan instead).

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
- **QR scanning, NFC, position sharing, app links**: the app's own Kotlin plugins
  have no Swift twin yet; the Dart side answers "not available"
  (`MissingPluginException` is read as unavailable) and falls back to typing.
  Camera, NFC and location texts are already in the Info.plist, so adding
  the Swift side later does not change the permissions' wording.
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
  app is on the screen.
