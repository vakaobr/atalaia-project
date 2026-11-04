<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Controller setup guide (Raspberry Pi)

For the organiser who sets up the **field controller** on a Raspberry Pi. You need to be able to type commands in a terminal. You do not need to write code. The developer details are in the [controller guide](../../../controller/README.md). Running the game is in the [Game master manual](game-master.md).

> **Not field-ready yet.** Atalaia is pre-alpha. The controller has run on a computer in Docker, with a modem board on its USB, a real box and the GM console, on a bench. **Not yet tested on a real Raspberry Pi**, and not on a field. The install steps below follow the controller guide and were not run on a Pi.

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
| A Wi-Fi network | A router, a phone's hotspot, or one made by the Pi. It does not need the internet. Setting up a hotspot on the Pi is a normal Raspberry Pi task and is not covered here |

Put the modem's antenna upright, in the open, away from metal and from the power bank. Do not hide it in a metal box. Its range is not measured yet.

## 3. Prepare the modem board

1. Flash the board with the modem image: download it or build it, then write it with esptool. The whole path, for Windows, Linux and macOS, is in [Set up the radio modem](modem.md) (sections 3 and 4). Use the same region as your boxes.
2. Plug it into the Pi and find its port (`ls /dev/ttyACM*`; [Set up the radio modem, section 6](modem.md#6-plug-it-into-the-controller-and-find-its-port)). Its small screen shows **MODEM MODE**. At first it says `LINK waiting`. That is right: the controller is not running yet. Once the controller runs, the screen switches to the language of your boxes (the **box language** setting), so in Portuguese you will see `LINK aguarda`, in German `LINK wartet`, in Chinese `等待` in the top bar; the rest of this guide uses the English words.

## 4. Install the controller

This is the supported way from the [controller guide](../../../controller/README.md#running-it): Raspberry Pi OS or Ubuntu, the system's packages, no Docker. The commands need a network connection on the Pi, and `sudo`.

1. Install the packages and the code:

   ```
   sudo apt update
   sudo apt install git python3-fastapi python3-uvicorn python3-websockets python3-paho-mqtt \
        python3-serial python3-yaml python3-cryptography libmbedtls-dev mosquitto cmake build-essential
   sudo git clone https://github.com/vakaobr/atalaia-project /opt/atalaia
   ```

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
   - `[api] tls_names`: the addresses phones use to reach the Pi, for example `["192.168.4.1", "campo.local"]`.
   - `[mqtt] enabled`: leave it, or set `false` if you do not use scoreboards. The default needs the Mosquitto program that you installed.
5. Install the service, so that it starts when the Pi starts:

   ```
   sudo cp /opt/atalaia/controller/deploy/atalaia-controller.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now atalaia-controller
   ```

## 5. First start

1. Check that it runs: `sudo systemctl status atalaia-controller`. It should say `active (running)`. For the log: `sudo journalctl -u atalaia-controller -n 50`.
2. Look at the modem board's small screen. **LINK OK** means the controller is talking to it. `waiting` means it is not: check the port setting and the cable. `DOWN` means it was talking and stopped: check the Pi. The console's header should say **Radio: up** too. All the checks, and a join through the modem, are in [Set up the radio modem, sections 8 and 9](modem.md#8-check-that-the-controller-and-the-modem-talk).
3. On the first start the controller makes the field's secrets: the two access codes, the **field join key**, and the field's own certificate. Show them. The command runs in the controller's folder, as its user:

   ```
   cd /opt/atalaia/controller
   sudo -u atalaia python3 -m atalaia_controller tokens --config /etc/atalaia/controller.toml
   sudo -u atalaia python3 -m atalaia_controller join-key --config /etc/atalaia/controller.toml
   ```

   The **GM code** runs the game: keep it to yourself. The **read-only code** only watches: give it to scoreboards. The **join key** is the field's master secret. Give it to nobody but trusted staff. Do not put it in a chat or an email.

## 6. Open the console

1. Join the field's Wi-Fi with a phone or a laptop.
2. Find the Pi's address: on the Pi, run `hostname -I`.
3. Open `https://` *the Pi's address* `:8443/console/`, for example `https://192.168.4.1:8443/console/`. The browser warns once that it does not know the certificate: it is the field's own, so accept it. Type the GM code. (On plain `http://…:8080` the page opens but the console will not send the code; it shows the https address.)

The controller serves HTTPS on port 8443, with a certificate from the field's own authority, and the GM code is accepted only there. Phones check it against the check-in poster's fingerprint. Plain MQTT (port 1883) is for the Pi itself; a scoreboard on another machine uses MQTT over TLS on port 8883 (`deploy/mosquitto-tls.conf`, see the controller README). If you change the Pi's address or name, add it to `tls_names` and restart the service.

From here, follow the [Game master manual](game-master.md): the radio channel, adopting the boxes, a game from start to end.

## The clock

A field has no internet, so the controller cannot ask the network for the time. **A Raspberry Pi 4 has no clock of its own.** After a power cut it starts with the time it last saved (the system's *fake-hwclock* keeps the time of the last orderly shutdown or hourly save), or with 1 January 1970 if it has none. A **Raspberry Pi 5 has a real-time clock, but it keeps time only with its optional battery** (the RTC battery connector); without it, it behaves like a Pi 4. Put the battery on a Pi 5 if you can. Phones and laptops have the right time, so a controller with a wrong clock is the one that is out of step.

What the controller does about it (the details are in the [controller README](../../../controller/README.md#the-wall-clock)):

- **Games, timers and the radio do not use the clock.** Game time, pauses, timeouts and rate limits run on a clock that only counts forward, so a wrong or a jumping time never changes a game's length.
- **It notices.** At start and every few seconds it compares its clock with the day this software was released and with the newest time it has already seen (it saves that every few minutes, so a Pi 4 that comes up days behind is caught too). If the clock is earlier, the log says `the clock is wrong` and the console shows a yellow banner **The controller's clock is wrong** on every screen.
- **It keeps its certificates valid.** The field's certificates are issued for a window that starts before this software's release date, so a phone with the right time accepts them even if the controller's clock was wrong when they were made. A field certificate made at 1970 by an older version (it would have expired in 1980) is replaced when the controller starts; players then scan the poster again and the app asks to trust the field once more.
- **It deletes nothing while the clock is wrong**, nor for an hour after the clock jumps forward by a day or more. The retention periods (see [How long the controller keeps data](#how-long-the-controller-keeps-data)) would otherwise count from a wrong date.
- **Check-ins made while the clock is wrong get codes that end at the wrong time.** After you set the clock, a code made at 1970 is already over: players check in again (the app asks).

**To set the clock**, open the console on a phone or laptop (their time is right), and in the yellow banner, or in **Settings › Controller clock**, tap **Set the controller's clock from this device**. Only the GM code can do it. The controller moves its clock **forward only**: it refuses a time earlier than the newest data it holds, earlier than its current time, or (when its clock looks right) more than 14 days ahead. A move backwards would let expired player codes and certificates work again. The setting lasts until the Pi restarts; a Pi 4 without a battery needs it after every power cut (the banner reminds you). To keep the time across restarts, set the system clock too, as `root` on the Pi: `sudo timedatectl set-time "2026-11-02 14:30:00"` (the controller's user cannot do this itself, on purpose), or give the Pi a way to learn the time: an RTC module, the Pi 5's battery, or a router that gives the time to the Pi over NTP while it is on the internet.

If the console refuses ("... is earlier than ..."), either the phone's time is wrong too, or the controller has already seen a later time because its clock was *ahead* for a while. The controller never goes back by itself: fix it as `root` with `sudo timedatectl set-time` and restart the service; the records made while it was ahead keep their dates.

## Using a travel router

A small **travel router** (a pocket router on a power bank) is the simplest field Wi-Fi: the Pi and the phones all join the router's Wi-Fi.

1. **Join the Pi to the router.** The Pi joins the router's Wi-Fi like a phone, or plugs into its LAN socket with a cable (better: no Wi-Fi to lose).
2. **Give the Pi a fixed address.** In the router's settings, make a *DHCP reservation* (also called a *static lease* or *address binding*) for the Pi's MAC address, for example `192.168.8.10`. Do not use a different address on each start: the check-in poster and the QR codes carry the controller's address. Find the MAC address on the Pi with `ip link show`. (You can set a static address on the Pi instead, outside the router's DHCP range; the reservation is easier to undo.)
3. **Tell the controller its address.** Put it in `[api] tls_names` in `/etc/atalaia/controller.toml`, for example `["192.168.8.10", "campo.local"]`, and restart the service, so the certificate covers it (section 6).
4. **The router must work with no internet.** Many travel routers insist on an uplink: they show a "no internet" page, or keep the Wi-Fi on but hand out no address until they are set up. Test it before the day: switch off the router's uplink (no cable, no hotspot), switch it on, and join with a phone. The phone may say "no internet"; that is fine. If it drops the Wi-Fi because there is no internet, turn off that phone's *Switch to mobile data automatically* (Android) or *Wi-Fi Assist* (iPhone), or use a router that does not need it.
5. **Do NOT let the router isolate its clients.** Switch off *AP isolation* / *client isolation* / *wireless isolation*, and do not put the phones on the **guest network**: guest networks usually isolate clients so that phones cannot reach other devices, including the Pi. With isolation on, the phones join the Wi-Fi but cannot open the controller, the check-in fails and the console does not load. Test it: from a phone on the Wi-Fi, open `https://192.168.8.10:8443/console/` (the address you reserved).
6. **The address the players use.** Players do not type it: the **check-in poster** carries the controller's https address and fingerprint in its QR code. The poster is made in the console (**Check-in** tab, **Print the poster**, see the [Game master manual](game-master.md#check-in-rules-and-the-poster)); its **The controller's https addresses** box shows the addresses the QR code holds, one per line, and you can fix them there (for example, to the reserved address). Print it again whenever the address changes. The console also shows the address to use, when you open the plain `http://` page by mistake.

If the router's address range changes (for example, it is a different router at the next field), the reserved address changes too: check the poster and `tls_names` before the day.

## 7. Backups

Everything the controller keeps is in two places: `/etc/atalaia/controller.toml` (your settings), and the folder `/var/lib/atalaia/` (the database with the access codes, the join key, games, presets and the check-in list; the `tls` folder with the field's certificate authority; the `firmware` folder with firmware images).

To make a backup, stop the controller, copy, start it again:

```
sudo systemctl stop atalaia-controller
sudo tar czf atalaia-backup.tar.gz /etc/atalaia /var/lib/atalaia
sudo systemctl start atalaia-controller
```

Copy the file to a USB stick or another computer. **Treat it like a password:** it holds the join key, which opens every box of the field. Do not put it on a shared drive.

To restore on a new Pi, install as in section 4, stop the service, unpack the backup with `sudo tar xzf atalaia-backup.tar.gz -C /`, then start it. The boxes keep working, because the join key is the same. Without a backup you must adopt every box again. Restoring has not been tried.

Back up before a game day and after you adopt new boxes. Do not copy the database while the controller runs.

### How long the controller keeps data

Once a day the controller deletes what is older than its retention periods. They are settings in the `[checkin]` section of `/etc/atalaia/controller.toml`, in days:

- `retention_days = 30`: the names and federation numbers of a game's check-ins, erased this many days after the game.
- `chrono_retention_days = 365` (30 to 3653): chronograph readings, other fields' copies of them and a marshal's earlier keys.
- `game_retention_days = 365` (30 to 3653): an ended game's events, scores and list of devices. With a site server set up, a game is never deleted before the site server has all of it, so a game that cannot be sent stays until it can.

The last two can also be set in the GM console (**Check-in › Check-in rules**, see the [Game master manual](game-master.md#check-in-rules-and-the-poster)). With `[sync] branding = "site"` they come from the site server's field settings and the console cannot change them. After you edit the file, restart the controller (`sudo systemctl restart atalaia-controller`). A backup holds what the controller had not yet deleted: delete old backups too, as you would the data.

**Walk-ins on the site server.** With a site server, after a game made from a scheduled game the controller sends only how many players came without a registration (walk-ins). Set `push_walkins = true` in `[sync]` to send each walk-in too, as a guest registration: the player id, the display name given at check-in and the chrono results of the declared replicas (type, class, passed or refused). It never sends a federation number, a team, a replica's make and model or a ticket, and marshals and GMs are not sent. The site server deletes these guest registrations 30 days after the game, and at once when the controller erases that player on request. It is off by default. Turn it on only if the field needs walk-ins in its records on the site, and say so in the field's privacy notice (the template has lines for it, marked for the field's choice and a lawyer's review). The default check-in notice the app shows says the name is never sent to the site server: with this on, give the controller your own check-in notice (`[checkin] notice_pt` and `notice_en`, files in Markdown) that says otherwise, and raise `notice_version`. A site server that does not know guests yet gets the count only. On the phone controller the same setting is **Send walk-ins to the site server as guests** in the site settings.

## 8. Troubleshooting

| Problem | What to do |
| --- | --- |
| The modem's screen says `LINK waiting` | The controller is not running, or `[modem] port` is wrong. Check `ls /dev/ttyACM*` and the service's log. More in the [modem troubleshooting table](modem.md#10-troubleshooting) |
| `Permission denied` on the port in the log | The user is not in the `dialout` group (section 4, step 3) |
| The console does not open | Check the Pi's address, port 8443 (https), and that the phone is on the field Wi-Fi |
| The console says to use the https address | You opened `http://…:8080`: the controller does not take the GM code over plain HTTP. Use the `https://…:8443/console/` address it shows |
| The modem's screen says `RADIO FAULT` | The radio chip did not start. Try another board; check the antenna and the cable |
| A box does not hear the controller | Same region and channel? Antennas fitted? See the Game master manual's troubleshooting |
| I forgot the codes | Run the `tokens` and `join-key` commands again (section 5) |

Found a step that does not match? Open an issue or tell us in [Discussions](https://github.com/vakaobr/atalaia-project/discussions).
