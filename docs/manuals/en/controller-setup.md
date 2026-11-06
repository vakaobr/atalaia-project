<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Controller setup guide (Raspberry Pi)

For the organiser who sets up the **field controller** on a Raspberry Pi. You need to be able to type commands in a terminal. You do not need to write code. The developer details are in the [controller guide](../../../controller/README.md). Running the game is in the [Game master manual](game-master.md). To use an Android phone as the controller instead, see the [Phone controller guide](phone-controller.md).

> **Not field-ready yet.** Atalaia is pre-alpha. The controller has run on a computer in Docker, with a modem board on its USB, real boxes and the GM console, on a bench. As of 2026-11-06 it has **not been tested on a real Raspberry Pi**, and not on a field. The install steps below follow the controller guide and have not been run on a Pi.

Contents: 1. What the controller is · 2. Parts · 3. Prepare the modem board · 4. Install the controller · 5. First start: codes and keys · 6. Open the console · 7. The controller clock · 8. The network · 9. A standby controller · 10. Backups and how long data is kept · 11. Update the controller and the modem · 12. Troubleshooting

## 1. What the controller is

The controller is a small computer that keeps the official score. It hears the boxes over the radio through a **modem board**, and it serves the **GM console**, a web page you open on a phone or a laptop.

```
boxes ))) radio ((( modem board ==USB== Raspberry Pi ── Wi-Fi ── GM console, players' phones
```

## 2. Parts

| Part | What to check |
| --- | --- |
| Raspberry Pi 4 or 5 | The design uses a Pi 4 or 5. A Pi Zero 2 W is named for small fields, not tried |
| Power for the Pi | The official power supply for your Pi. In the field, a power bank that can give the same current, 10 to 20 Ah (the design's size; the run time is not measured) |
| microSD card | A good-quality card. Its size is not critical |
| **Modem board** | A second **Heltec WiFi LoRa 32 V4**, the same revision (V4.3 or V4.2) as your boxes, 863-928 MHz |
| LoRa antenna for the modem | 868 MHz, 2 dBi or less (for Taiwan, a 915-925 MHz antenna). **Fit it before the board has power** |
| USB-C data cable | A short one, from the modem board to the Pi. A charge-only cable does not work |
| A Wi-Fi network | A router, a phone's hotspot, or one made by the Pi. It does not need the internet. Setting up a hotspot on the Pi is a normal Raspberry Pi task and is not covered here. A travel router is covered in [section 8](#8-the-network) |
| A battery for a Pi 5 (optional) | The Pi 5's real-time clock keeps time only with its battery. See [section 7](#the-controller-clock) |

Put the modem's antenna upright, in the open, away from metal and from the power bank. Do not hide it in a metal box. Its range is not measured yet.

## 3. Prepare the modem board

1. Flash the board with the modem image: download it or build it, then write it with esptool. The whole path, for Windows, Linux and macOS, is in [Set up the radio modem](modem.md) (sections 3 and 4). Use the same region as your boxes.
2. Plug it into the Pi and find its port (`ls /dev/ttyACM*`; [Set up the radio modem, section 6](modem.md#6-plug-it-into-the-controller-and-find-its-port)). Its small screen shows **MODEM MODE**. At first it says `LINK waiting`. That is right: the controller is not running yet. Once the controller runs, the screen switches to the language of your boxes (the **box language** setting), so in Portuguese you will see `LINK aguarda`, in German `LINK wartet`, in Chinese `等待` in the top bar; the rest of this guide uses the English words.

The modem has no over-the-air update: a new modem image is always written over USB ([section 11](#update-the-controller)).

## 4. Install the controller

This is the supported way from the [controller guide](../../../controller/README.md#running-it): Raspberry Pi OS or Ubuntu, the system's packages, no Docker. The commands need a network connection on the Pi, and `sudo`.

1. Install the packages and the code:

   ```
   sudo apt update
   sudo apt install git python3-fastapi python3-uvicorn python3-websockets python3-paho-mqtt \
        python3-serial python3-yaml python3-cryptography libmbedtls-dev mosquitto cmake build-essential
   sudo git clone https://github.com/vakaobr/atalaia-project /opt/atalaia
   ```

   This takes the newest code (the `main` branch). To install a published release instead, run `sudo git -C /opt/atalaia checkout v0.8.0` (the newest release on 2026-11-06; the [Releases page](https://github.com/vakaobr/atalaia-project/releases) lists them).
2. Build the small program library the controller needs for game scripts:

   ```
   sudo cmake -S /opt/atalaia/core -B /opt/atalaia/build -DATALAIA_SHARED=ON
   sudo cmake --build /opt/atalaia/build
   ```

3. Make the controller's user and folders. The service file in the project expects these names:

   ```
   sudo adduser --system --group --no-create-home atalaia
   sudo usermod -aG dialout atalaia
   sudo mkdir -p /etc/atalaia /var/lib/atalaia
   sudo chown atalaia /var/lib/atalaia
   sudo cp /opt/atalaia/controller/controller.example.toml /etc/atalaia/controller.toml
   ```

   `dialout` lets it open the modem's USB port.
4. Edit the settings file: `sudo nano /etc/atalaia/controller.toml`. The ones you need:
   - `[modem] port`: the modem's port. Usually `/dev/ttyACM0`. To check, run `ls /dev/ttyACM*` with the modem plugged in; with a Field Box plugged in too, use the stable name under `/dev/serial/by-id/` ([Set up the radio modem, section 6](modem.md#6-plug-it-into-the-controller-and-find-its-port)). An empty port means no radio.
   - `[radio] region`: `eu868` or `as923-tw`. It must match the modem and the boxes.
   - `[checkin] field_name`: your field's name. Players see it. `wifi_ssid`: the field Wi-Fi's name, printed on the check-in poster.
   - `[api] tls_names`: the addresses phones use to reach the Pi, for example `["192.168.4.1", "campo.local"]` ([section 8](#8-the-network)).
   - `[mqtt] enabled`: leave it, or set `false` if you do not use scoreboards. The default needs the Mosquitto program that you installed.
5. Install the service, so that it starts when the Pi starts:

   ```
   sudo cp /opt/atalaia/controller/deploy/atalaia-controller.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now atalaia-controller
   ```

## 5. First start: codes and keys

1. Check that it runs: `sudo systemctl status atalaia-controller`. It should say `active (running)`. For the log: `sudo journalctl -u atalaia-controller -n 50`.
2. Look at the modem board's small screen. **LINK OK** means the controller is talking to it. `waiting` means it is not: check the port setting and the cable. `DOWN` means it was talking and stopped: check the Pi. The console's header should say **Radio: up** too. All the checks, and a join through the modem, are in [Set up the radio modem, sections 8 and 9](modem.md#8-check-that-the-controller-and-the-modem-talk).
3. On the first start the controller makes the field's secrets: the two access codes, the **field join key**, and the field's own certificate. Show them. The commands run in the controller's folder, as its user, with its settings file:

   ```
   cd /opt/atalaia/controller
   sudo -u atalaia python3 -m atalaia_controller tokens --config /etc/atalaia/controller.toml
   sudo -u atalaia python3 -m atalaia_controller join-key --config /etc/atalaia/controller.toml
   ```

   Do not leave out `--config`: without it the command opens another, empty database (`atalaia.db` in the current folder) and prints new codes that the running controller does not know. Without `sudo -u atalaia` it cannot read the controller's own database.
4. Keep them apart:
   - The **GM code** runs the game: keep it to yourself.
   - The **read-only code** only watches: give it to scoreboards.
   - The **join key** is the field's master secret. Give it to nobody but trusted staff. Do not put it in a chat or an email. A standby controller needs the same key ([section 9](#standby-controller)).
5. For a referee or a visiting GM, do not hand out the GM code: make a short-lived **day code** in the console (**Settings**, **Access tokens**; see the [Game master manual](game-master.md)). The same can be done on the Pi with `tokens --create LABEL --scope read|gm|marshals --ttl 8h` (shown once), `tokens --list` and `tokens --revoke ID`, with the same `sudo -u atalaia ... --config /etc/atalaia/controller.toml` as above.

## 6. Open the console

1. Join the field's Wi-Fi with a phone or a laptop.
2. Find the Pi's address: on the Pi, run `hostname -I`.
3. Open `https://` *the Pi's address* `:8443/console/`, for example `https://192.168.4.1:8443/console/`. The browser warns once that it does not know the certificate: it is the field's own, so accept it.
4. Type the GM code. (On plain `http://…:8080` the page opens but the console will not send the code; it shows the https address.)

The controller serves HTTPS on port 8443, with a certificate from the field's own authority, and the GM code is accepted only there. Phones check it against the check-in poster's fingerprint. Plain MQTT (port 1883) is for the Pi itself; a scoreboard on another machine uses MQTT over TLS on port 8883 (`deploy/mosquitto-tls.conf`, see the controller README). If you change the Pi's address or name, add it to `tls_names` and restart the service.

From here, follow the [Game master manual](game-master.md): the radio channel, adopting the boxes, a game from start to end.

<a id="the-controller-clock"></a>

## 7. The controller clock

A field has no internet, so the controller cannot ask the network for the time. **A Raspberry Pi 4 has no clock of its own.** After a power cut it starts with the time it last saved (the system's *fake-hwclock* keeps the time of the last orderly shutdown or hourly save), or with 1 January 1970 if it has none. A **Raspberry Pi 5 has a real-time clock, but it keeps time only with its optional battery** (the RTC battery connector); without it, it behaves like a Pi 4. Put the battery on a Pi 5 if you can. Phones and laptops have the right time, so a controller with a wrong clock is the one that is out of step.

### What the controller does about it

The details are in the [controller README](../../../controller/README.md#the-wall-clock).

- **Games, timers and the radio do not use the clock.** Game time, pauses, timeouts and rate limits run on a clock that only counts forward, so a wrong or a jumping time never changes a game's length.
- **It notices (the clock guard).** At start and every few seconds it compares its clock with the day this software was released and with the newest time it has already seen (it saves that every few minutes, so a Pi 4 that comes up days behind is caught too). If the clock is earlier, the log says `the clock is wrong` and the console shows a yellow banner **The controller's clock is wrong.** on every screen.
- **It keeps its certificates valid.** The field's certificates are issued for a window that starts before this software's release date, so a phone with the right time accepts them even if the controller's clock was wrong when they were made. A field certificate made at 1970 by an older version (it would have expired in 1980) is replaced when the controller starts; players then scan the poster again and the app asks to trust the field once more.
- **It deletes nothing while the clock is wrong**, nor for an hour after the clock jumps forward by a day or more. The retention periods ([section 10](#how-long-the-controller-keeps-data)) would otherwise count from a wrong date.
- **Check-ins made while the clock is wrong get codes that end at the wrong time.** After you set the clock, a code made at 1970 is already over: players check in again (the app asks).

### Set the clock from the console (GM correction)

1. Open the console on a phone or laptop whose time is right.
2. In the yellow banner, or in **Settings › Controller clock**, tap **Set the controller's clock from this device**. Only the GM code can do it. A read-only code sees *Ask the game master to set it from the console.*
3. The console says *The controller's clock is now …* and the banner goes away.

The controller moves its clock **forward only**: it refuses a time earlier than the newest data it holds, earlier than its current time, or (when its clock looks right) more than 14 days ahead. A move backwards would let expired player codes and certificates work again. The setting lasts until the controller restarts; a Pi 4 without a battery needs it after every power cut (the banner reminds you).

To keep the time across restarts, set the system clock too, as `root` on the Pi: `sudo timedatectl set-time "2026-11-02 14:30:00"` (the controller's user cannot do this itself, on purpose). Or give the Pi a way to learn the time: an RTC module, the Pi 5's battery, or a router that gives the time to the Pi over NTP while it is on the internet.

If the console refuses ("... is earlier than ..."), either the phone's time is wrong too, or the controller has already seen a later time because its clock was *ahead* for a while. The controller never goes back by itself: fix it as `root` with `sudo timedatectl set-time` and restart the service; the records made while it was ahead keep their dates.

**From v0.9.0 (not released yet; build from `main` until then)**, the controller also uses the corrected time in the TIME beacons it sends the boxes and in **Release every box not in this game**, so a box compares its game's join time and a release on one clock. That button is refused while the clock is wrong: set the clock first.

A phone controller has the same clock guard from v0.9.0: see the [Phone controller guide](phone-controller.md#the-controller-clock).

## 8. The network

Players' phones, the console and Android props all use one Wi-Fi network at the field. It does not need the internet. The Pi must be on it, at an address that does not change, and that address must be in `[api] tls_names`.

### TLS names: the addresses in the certificate

The field's certificate names the addresses phones use to reach the controller. They come from `[api] tls_names` in `/etc/atalaia/controller.toml`, for example `["192.168.8.10", "campo.local"]`.

1. Put every address and name phones will use in `tls_names`.
2. Restart the service: `sudo systemctl restart atalaia-controller`. The certificate then covers them.
3. Print the check-in poster again if the address changed (step 6 below).

### Using a travel router

A small **travel router** (a pocket router on a power bank) is the simplest field Wi-Fi: the Pi and the phones all join the router's Wi-Fi.

1. **Join the Pi to the router.** The Pi joins the router's Wi-Fi like a phone, or plugs into its LAN socket with a cable (better: no Wi-Fi to lose).
2. **Give the Pi a fixed address.** In the router's settings, make a *DHCP reservation* (also called a *static lease* or *address binding*) for the Pi's MAC address, for example `192.168.8.10`. Do not use a different address on each start: the check-in poster and the QR codes carry the controller's address. Find the MAC address on the Pi with `ip link show`. (You can set a static address on the Pi instead, outside the router's DHCP range; the reservation is easier to undo.)
3. **Tell the controller its address.** Put it in `[api] tls_names`, as above, and restart the service.
4. **The router must work with no internet.** Many travel routers insist on an uplink: they show a "no internet" page, or keep the Wi-Fi on but hand out no address until they are set up. Test it before the day: switch off the router's uplink (no cable, no hotspot), switch it on, and join with a phone. The phone may say "no internet"; that is fine. If it drops the Wi-Fi because there is no internet, turn off that phone's *Switch to mobile data automatically* (Android) or *Wi-Fi Assist* (iPhone), or use a router that does not need it.
5. **Do NOT let the router isolate its clients.** Switch off *AP isolation* / *client isolation* / *wireless isolation*, and do not put the phones on the **guest network**: guest networks usually isolate clients so that phones cannot reach other devices, including the Pi. With isolation on, the phones join the Wi-Fi but cannot open the controller, the check-in fails and the console does not load. Test it: from a phone on the Wi-Fi, open `https://192.168.8.10:8443/console/` (the address you reserved).
6. **The address the players use.** Players do not type it: the **check-in poster** carries the controller's https address and fingerprint in its QR code. The poster is made in the console (**Check-in** tab, **Print the poster**, see the [Game master manual](game-master.md)); its **The controller's https addresses** box shows the addresses the QR code holds, one per line, and you can fix them there (for example, to the reserved address). Print it again whenever the address changes. The console also shows the address to use when you open the plain `http://` page by mistake.

If the router's address range changes (for example, it is a different router at the next field), the reserved address changes too: check the poster and `tls_names` before the day.

<a id="standby-controller"></a>

## 9. A standby controller

A second controller can follow a game and take it over if the main one fails: a second Pi with its own modem, or an Android phone with a radio ([Phone controller guide](phone-controller.md#standby-controller)). Not yet tried on a field.

### What a standby does, and what it refuses

While it stands by, it hears the game over its own radio, logs its events and follows its clock and scores, but it answers nothing. Its console says *This controller is on standby in this game: it follows the main controller and only takes charge if promoted.* Until it takes over, it refuses to:

- start, pause or resume the game (*This controller is not in charge of the game. To run it from here, promote it in the Controller tab.*), invite boxes, change scores or switch outputs;
- make join data (*A standby controller does not make join data; use the controller in charge.*);
- free boxes stuck in an ended game: it never resends GAME_OVER by itself, and refuses **Release** and **Release every box not in this game** (from v0.9.0, not released yet). The controller in charge does that.

Its **End** button reads **Leave the game**: it stops following, and the game goes on. It also leaves on its own when the game ends.

### Set up a standby Pi

1. Install the second Pi as in sections 2 to 6, with its own modem board, the same `[radio] region`, and the same modes installed as the main controller.
2. Give it the **same field join key**. On the main controller, show it with `join-key` ([section 5](#5-first-start-codes-and-keys)). On the standby, put it in `/etc/atalaia/controller.toml`:

   ```
   [join]
   key = "<the 64 hex digits>"
   ```

3. Choose how it takes over, in `[controller]` (below), and restart the standby: `sudo systemctl restart atalaia-controller`.
4. For each game: on the main controller, create the game. Then open the **Join** tab, under **For** choose **a standby controller**, and tap **Generate**.
5. On the standby's console, **Join** tab, **Join as a standby controller**: paste the text, tap **Join the game**. It says *This controller is now on standby in game …*. The standby must have no live game of its own.
6. On both, the **Controller** tab shows the **Role** (**controller in charge** or **standby**), the **Failover** mode and the **Priority**.
7. Generate the join again and paste it again after you move a box, change its room or disable one: the join text carries where the boxes are and the beacon choices, so a standby that takes over places players the same way.

<a id="failover-mode"></a>

### `failover_mode`: manual or automatic

In `[controller]` of `/etc/atalaia/controller.toml`:

- `failover_mode = "manual"` (the default): nothing happens by itself. When the main controller stops answering, open the standby's console, **Controller** tab, and tap **Promote to controller**. It asks *This controller will take charge of the game. Continue?*
- `failover_mode = "auto"`: the main controller sends its time beacon every 10 seconds instead of 30. A standby that misses three in a row (about **30 seconds** of silence) stands for the role and, a few seconds later, takes over. The project's example settings say to use `auto` only after field testing, which has not happened yet.

A standby set to `auto` counts the beacons it actually hears from the main controller, not the ones its own setting gives. It waits for **about 90 seconds** of silence (three missed 30-second beacons) until it has heard three beacons in a row 10 seconds apart, about 40 seconds after it joins or hears a new controller. It also waits 90 seconds after two beacons in a row go missing, and the whole time behind a main controller set to `manual`. So a different setting no longer makes a standby take over a main controller that still works. The beacons a start, a pause or a resume sends again in the next 10 seconds do not count. The standby's **Controller** tab shows **Takes over after** with the silence it waits for.

If the old controller comes back, it hears the newer one and steps down.

Give every controller of a game the same `failover_mode` anyway. When the two differ, the standby's console says so in the **Controller** tab, and its log has a warning:

- the standby is on `auto` and the main controller on `manual`: the standby takes over only after 90 seconds of silence;
- the standby is on `manual` and the main controller on `auto`: the standby never takes over by itself, so promote it by hand.

### `power_source`: who wins when two stand

When two standbys stand at once, the one with the better power wins. In `[controller]`:

| `power_source` | Meaning |
| --- | --- |
| `3` (default) | mains or USB power |
| `2` | a large battery (a power bank of 10 Ah or more) |
| `1` | a small battery |

Set `2` on a Pi that runs from a power bank. A phone controller always counts as `1`, so **a phone on battery yields to a Pi on mains** when both stand. Restart the controller after a change.

## 10. Backups and how long data is kept

### Make a backup

Everything the controller keeps is in two places: `/etc/atalaia/controller.toml` (your settings), and the folder `/var/lib/atalaia/` (the database with the access codes, the join key, games, presets and the check-in list; the `tls` folder with the field's certificate authority; the `firmware` folder with firmware images).

1. Stop the controller, copy, start it again:

   ```
   sudo systemctl stop atalaia-controller
   sudo tar czf atalaia-backup.tar.gz /etc/atalaia /var/lib/atalaia
   sudo systemctl start atalaia-controller
   ```

2. Copy the file to a USB stick or another computer. **Treat it like a password:** it holds the join key, which opens every box of the field. Do not put it on a shared drive.

Back up before a game day, after you adopt new boxes, and before you update ([section 11](#update-the-controller)). Do not copy the database while the controller runs.

### Restore a backup

1. Install a new Pi as in section 4.
2. Stop the service: `sudo systemctl stop atalaia-controller`.
3. Unpack the backup: `sudo tar xzf atalaia-backup.tar.gz -C /`.
4. Start it: `sudo systemctl start atalaia-controller`.

The boxes keep working, because the join key is the same. Without a backup you must adopt every box again. Restoring has not been tried.

If a game was running when the old controller was lost, its boxes may stay in it. The [Game master manual](game-master.md#recover-from-problems) says how to free them.

<a id="how-long-the-controller-keeps-data"></a>

### How long the controller keeps data

Once a day the controller deletes what is older than its retention periods. They are settings in the `[checkin]` section of `/etc/atalaia/controller.toml`, in days:

| Setting | Default | What it covers |
| --- | --- | --- |
| `retention_days` | 30 (1 to 3653) | The names and federation numbers of a game's check-ins, erased this many days after the game |
| `chrono_retention_days` | 365 (30 to 3653) | Chronograph readings, other fields' copies of them and a marshal's earlier keys |
| `game_retention_days` | **90** (30 to 3653) | An ended game's events, scores and list of devices. With a site server set up, a game is never deleted before the site server has all of it, so a game that cannot be sent stays until it can |

When a game is deleted, its team results stay for 365 days, without any player id.

The last two can also be set in the GM console (**Check-in › Check-in rules**). With `[sync] branding = "site"` they come from the site server's field settings and the console cannot change them. After you edit the file, restart the controller (`sudo systemctl restart atalaia-controller`). A backup holds what the controller had not yet deleted: delete old backups too, as you would the data.

With a site server, `[sync] push_walkins` (off by default) sends each walk-in to it as a guest registration. Turn it on only after reading what it sends and what the privacy notice must then say: see the [Site admin manual](site-admin.md).

<a id="update-the-controller"></a>

## 11. Update the controller and the modem

Update between games, never while a game is running. A new version can change the database the first time it starts, so make a backup first: it is the way back.

### Update the controller

1. Make a backup ([section 10](#make-a-backup)).
2. Get the new code:

   ```
   sudo git -C /opt/atalaia fetch --tags
   sudo git -C /opt/atalaia checkout v0.8.0
   ```

   Put the release you want in place of `v0.8.0`. To follow the newest code instead, `sudo git -C /opt/atalaia checkout main` and then `sudo git -C /opt/atalaia pull`.
3. Install any new packages: run the `sudo apt install ...` line of [section 4](#4-install-the-controller) again (it does nothing for packages you already have).
4. Rebuild the program library:

   ```
   sudo cmake -S /opt/atalaia/core -B /opt/atalaia/build -DATALAIA_SHARED=ON
   sudo cmake --build /opt/atalaia/build
   ```

5. Copy the service file again, in case it changed:

   ```
   sudo cp /opt/atalaia/controller/deploy/atalaia-controller.service /etc/systemd/system/
   sudo systemctl daemon-reload
   ```

6. Look for new settings: `diff /etc/atalaia/controller.toml /opt/atalaia/controller/controller.example.toml`. Your file keeps working without them (each setting has a default), but read what is new.
7. Check the firmware release keys (below).
8. Restart: `sudo systemctl restart atalaia-controller`, then `sudo systemctl status atalaia-controller` and the log, as in [section 5](#5-first-start-codes-and-keys).

To go back, check out the older version, rebuild (step 4), and restore the backup you made in step 1: an older version may not read a database a newer one has changed.

### The firmware release keys

The console's **Boxes** tab updates the boxes only with releases signed by a key in `[firmware] release_keys`. Since v0.8.0 the project signs with two keys: root `424d053af5cdbc35` and CI `a4f6002b0122b131`. The CI key `32b3c815ac30ad43` was retired on 2026-11-04.

1. Open `/etc/atalaia/controller.toml` and find `[firmware]`.
2. If `release_keys` is not there, you use the project's keys: nothing to do.
3. If it lists keys by hand (a copy of an older example file does), make sure it holds these two, and remove `rIO8ogMU3LRLLtnt6Rys+URdKYfmNv5mxvuRJQsX9Tw=` (the retired key) if it is there:

   ```
   release_keys = ["5tzPkN0AJSn+g34CP59linCRf/fcaWFc7GAAg7qzYNc=", "76eY5BoMQ4RHohhX/8iSUlIUA5o5Entfk7EFBUxpbSY="]
   ```

4. Restart the controller.

An empty list (`release_keys = []`) refuses every release. Updating the boxes themselves is in the [Field Box manual](field-box.md#update-the-boxes).

### Update the modem

The modem has no over-the-air update: write the new image over USB. When to do it, and how, is in [Set up the radio modem, Update the modem](modem.md#update-the-modem). In short: stop the controller, write the new modem image, start the controller again.

Update the modem too when the log says `the radio modem's firmware cannot report boxes still in an ended game`, or the console's **Boxes** tab says the radio modem cannot report them. That needs a modem image from v0.9.0 (not released yet; build it from `main` until then).

## 12. Troubleshooting

| Problem | What to do |
| --- | --- |
| The modem's screen says `LINK waiting` | The controller is not running, or `[modem] port` is wrong. Check `ls /dev/ttyACM*` and the service's log. More in the [modem troubleshooting table](modem.md#troubleshooting) |
| `Permission denied` on the port in the log | The user is not in the `dialout` group (section 4, step 3) |
| `Permission denied` or `unable to open database file` on `/var/lib/atalaia` | The folder is not the controller's: `sudo chown -R atalaia /var/lib/atalaia`, then restart. Run the `tokens` and `join-key` commands with `sudo -u atalaia` (section 5) |
| The console does not open | Check the Pi's address, port 8443 (https), and that the phone is on the field Wi-Fi. A router's client isolation or guest network blocks it (section 8) |
| The console says to use the https address | You opened `http://…:8080`: the controller does not take the GM code over plain HTTP. Use the `https://…:8443/console/` address it shows |
| The browser says the certificate does not match the address | The address is not in `[api] tls_names`: add it and restart (section 8) |
| A yellow banner says **The controller's clock is wrong.** | Set it from the console (section 7). On a Pi 4 without a battery, after every power cut |
| The modem's screen says `RADIO FAULT` | The radio chip did not start. Try another board; check the antenna and the cable |
| A box does not hear the controller | Same region and channel? Antennas fitted? See the [Game master manual](game-master.md#recover-from-problems) |
| A box is stuck in a game that is over, and the console says the radio modem cannot report it | The modem's image is older than v0.9.0: update it (section 11). Until then, take the box out at the box ([Field Box manual](field-box.md#take-a-box-out-of-its-game)) |
| **Promote to controller** is missing, or the standby never takes over | The standby has not joined this game (section 9, steps 4 and 5), or `failover_mode` is `manual`: promote it by hand |
| A standby on `auto` took about 90 s, not 30 s, to take over | It had not yet heard three beacons in a row 10 s apart (it had just joined or heard a new controller, or two beacons in a row were missed), or the main controller is on `manual`: section 9, [`failover_mode`](#failover-mode) |
| I forgot the codes | Run the `tokens` and `join-key` commands again (section 5) |

Found a step that does not match? Open an issue or tell us in [Discussions](https://github.com/vakaobr/atalaia-project/discussions).
