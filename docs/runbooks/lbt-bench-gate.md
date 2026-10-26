<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Runbook: the listen-before-talk bench gate

Decision **SL-25** ([decisions-to-review.md](../review/decisions-to-review.md); design in SL-26 to SL-29) recommends a CAD before every transmission, **but only if the radio's "busy" test also covers a frame the receiver is already receiving**: a CAD sees only a preamble (about 12.5 ms of a 92 ms frame at SF7/125 kHz). This runbook measures that on two real Heltec V4.3 boards. **The gate: more than 90 % of the probes made inside a frame find the channel busy, in the whole frame and in every tenth of it. If not, the answer to SL-25 becomes "don't".**

Status: the test is built and host-tested; **the run is pending** (nobody has run it on a board yet). Nothing here changes a normal image: the test exists only in the bench image (`sdkconfig.bench`, Kconfig `ATALAIA_LBT_BENCH`), and does nothing until a console command is typed.

## What it does

- **Board 2, the transmitter** (`@lbt tx`): sends frames of a STATE's length (48-56 bytes, random) on the field channel, one every 300-700 ms (random) after the previous one ended.
- **Board 1, the prober** (`@lbt probe`): calls the HAL's `channel_busy()` every 2-5 ms (jittered), and receives the frames. `channel_busy()` is: if the receiver has flagged a **preamble detected** or a **valid header**, busy (and no CAD, which would take the chip out of receive and lose the frame); if a frame has just ended (**RxDone** pending), not busy and nothing touched; otherwise one CAD and back to receive.
- From each frame's RxDone time (taken in the interrupt) and its airtime, the prober rebuilds the frame's window on the air and places every probe against it: a hit or a miss by tenth of the frame (and by preamble / header / payload), or, outside every frame, a *false busy*. Every probe is a `LBT,p` line on the console; `tools/bench_lbt_gate.py` rebuilds the table from them and prints PASS or FAIL.
- The CAD's real duration and the receiver's re-arm time are measured around each call (`esp_timer`) and compared with SL-25's assumed 4 ms.

The channel is the build's region default: **EU868, 869.525 MHz, SF7/125 kHz** (the image from `docker_fw.py bench`). AS923-TW (921.5 MHz, SF9/500 kHz) is a separate image, see the end; run it only with an antenna and a board for that band.

## Duty cycle

A burst at 300-700 ms spaces uses 15-20 % of the airtime *while it runs*; the regulation limits the **rolling hour** (10 % on 869.4-869.65 MHz). The transmitter therefore runs at most **1000 frames (about 90 s of air, 2.5 % of the hour)**, the default 300 frames are about 28 s (0.8 %), the HAL still refuses a frame that does not fit in the 10 % budget, and **the transmitter stops by itself (`reason=duty_guard`) when the budget left falls under 70 % of it**, counting earlier runs, so a few runs in a row stay under about 3 % of an hour. Its `LBT,tsum` line gives the run's own duty (`run_duty_pm`, per mille), the budget left (`left_ms`) and the hour's share used (`hour_used_pm`, per mille). Wait for `hour_used_pm` to fall before repeating a long series.

## What you need

- Two Heltec V4.3 boards with their **LoRa antennas fitted** (never transmit without one), 1-2 m apart and not touching. Board 1 = COM3 (Field Box `b6f7d43f589aabc6`), board 2 = COM4 (the USB radio modem), as in HANDOVER.md.
- The Windows flasher venv `%USERPROFILE%\atalaia-flash` (esptool 4.8.1, with pyserial) and the folder `%USERPROFILE%\atalaia-bench`.
- Nothing else holding the ports: **stop `com_bridge.py` (COM4 <-> 127.0.0.1:7600) and the `atalaia-controller-bench` container** first (the modem is going away for the test), and close any serial monitor.

## 1. The images

Built in Docker from the repository (an `ATALAIA_VOLUME_SUFFIX` of your own keeps the build cache apart from other checkouts):

```sh
python3 tools/docker_fw.py bench      # -> firmware/esp32/build-bench/  (EU868; both boards, for the test)
python3 tools/docker_fw.py modem      # -> firmware/esp32/build-modem/  (board 2, to put it back afterwards)
```

The checked-in `docker_fw.py` writes both into `firmware/esp32/` of the checkout; flashing uses a **copy** of each folder in the Windows bench folder, as for every flash here:

```sh
# in WSL, from the checkout (the Windows profile folder is /mnt/c/Users/<you>)
mkdir -p /mnt/c/Users/<you>/atalaia-bench/lbt-bench /mnt/c/Users/<you>/atalaia-bench/lbt-modem
cp -r firmware/esp32/build-bench/{flash_args,atalaia_esp32.bin,ota_data_initial.bin,bootloader,partition_table} /mnt/c/Users/<you>/atalaia-bench/lbt-bench/
cp -r firmware/esp32/build-modem/{flash_args,atalaia_esp32.bin,ota_data_initial.bin,bootloader,partition_table} /mnt/c/Users/<you>/atalaia-bench/lbt-modem/
```

(`flash_args` lists the images by relative path: bootloader at 0x0, partition table at 0x8000, `ota_data_initial.bin` at 0xf000, the app at 0x20000, so the five items above are all it needs.)

## 2. Flash both boards with the bench image

In `cmd` or PowerShell, in `%USERPROFILE%\atalaia-bench\lbt-bench`:

```bat
"%USERPROFILE%\atalaia-flash\Scripts\python.exe" -m esptool --chip esp32s3 -p COM3 -b 921600 write_flash @flash_args
"%USERPROFILE%\atalaia-flash\Scripts\python.exe" -m esptool --chip esp32s3 -p COM3 --after hard_reset chip_id
"%USERPROFILE%\atalaia-flash\Scripts\python.exe" -m esptool --chip esp32s3 -p COM4 -b 921600 write_flash @flash_args
"%USERPROFILE%\atalaia-flash\Scripts\python.exe" -m esptool --chip esp32s3 -p COM4 --after hard_reset chip_id
```

The second and fourth lines reset the boards (the serial recorder's RTS reset is unreliable). Both boards then boot the bench Field Box image; each prints `serial keys on` and `SX1262 initialised: eu868, SF7, BW125k` on the console. The boards keep their old settings (no erase is needed): the test uses neither a joined game nor the picker (if the picker asks for a PIN, the bench admin PIN is 1234). A board that was in a game sends nothing during the test: the test takes the radio from the game.

## 3. Run it

The tool types the command and saves what the board prints. It needs only pyserial; run it with the flasher's Python so that it is there. From `%USERPROFILE%\atalaia-bench` (`wslpath -w tools/bench_lbt_gate.py` gives the path of the script in WSL):

**Prober first** (it waits up to 60 s for the first frame):

```bat
"%USERPROFILE%\atalaia-flash\Scripts\python.exe" \\wsl.localhost\Ubuntu-22.04\home\andersonleite\code\atalaia-project\tools\bench_lbt_gate.py --capture COM3 --send "@lbt probe 300" --out prober.log
```

**Then, within a minute, the transmitter** (a second window):

```bat
"%USERPROFILE%\atalaia-flash\Scripts\python.exe" \\wsl.localhost\Ubuntu-22.04\home\andersonleite\code\atalaia-project\tools\bench_lbt_gate.py --capture COM4 --send "@lbt tx 300" --out tx.log
```

(adjust the path to the checkout the images came from). 300 frames take about 3 minutes. The prober ends when it has received 300 frames (`reason=frames`), after 60 s without one (`reason=idle`) or on `@lbt stop`; the tool then prints the report. To stop early: type `@lbt stop` on either console (or run the tool again with `--send "@lbt stop"`). To read an existing log: `python3 tools/bench_lbt_gate.py prober.log`.

Without the tool, any serial terminal on the port works (type `@lbt probe 300` and Enter; save the output; `python3 tools/bench_lbt_gate.py saved.log`). Commands: `@lbt tx [frames]` (default 300, at most 1000), `@lbt probe [frames [gap_min_us gap_max_us]]` (default 300, 2000 5000), `@lbt stop`, `@lbt status`.

### The lines to expect

Prober (`LBT,` lines among the usual log; the `p` lines are every probe, about 250 a second):

```text
LBT,cfg,role=probe,region=eu868,freq=869525000,sf=7,bw=125000,sym_us=1024
LBT,start,role=probe,frames=300,gap_us=2000-5000
LBT,p,3456789012,0,3590,410        probe: time (low 32 bits of esp_timer, us), why, CAD us, re-arm us
LBT,p,3456793301,2,0,0             why: 0 free, 1 CAD saw a preamble, 2 receiver's preamble flag,
LBT,p,3456795318,3,0,0                  3 receiver's header-valid flag, 4 frame ended (not busy), 5 radio error
LBT,r,1,3456850123,52,0,95744,-38,0   a frame: n, RxDone time, length, sequence number, airtime us, RSSI, frames missed before it
...  every 25 frames:
LBT,sum,frames=25,lost=0,in=1150,hit=1139,hit_pm=990,out=...,out_busy=...,amb=...,err=0
LBT,dec,n/hit=115/115:114/114:...        probes / hits in each tenth of the frame
LBT,seg,pre=...,hdr=...,pay=...,by_cad=...,by_pre=...,by_hdr=...
LBT,tim,cad_n=...,cad_avg_us=...,cad_min_us=...,cad_max_us=...,rearm_avg_us=...,rearm_max_us=...,probes_dropped=0,lines_dropped=0
LBT,end,role=probe,reason=frames,frames=300
```

Transmitter:

```text
LBT,cfg,role=tx,region=eu868,freq=869525000,sf=7,bw=125000,sym_us=1024
LBT,start,role=tx,frames=300,budget_left_ms=360000,min_left_ms=252000
LBT,t,0,3456850120,52,95744          seq, time after the send, length, airtime us
LBT,tsum,sent=25,failed=0,air_ms=2400,elapsed_ms=14800,run_duty_pm=162,left_ms=357600,hour_used_pm=6
LBT,end,role=tx,reason=frames,sent=300
```

The report (`bench_lbt_gate.py`) prints the frames received against sent, the table by tenth of the frame (hit rate, with the millisecond range of each tenth), by part (preamble, header, payload), by what saw the frame (CAD, preamble flag, header flag), the false-busy rate, the CAD time against 4 ms and the receiver's re-arm time, then one of:

- **PASS** (exit 0): above 90 % overall and in every tenth.
- **FAIL** (exit 1): the table shows where. A cliff after the first tenth with `found busy by: CAD` only and no flags means the receiver's flags never showed (the chip does not latch them in continuous receive, or the mask is wrong): SL-25 is "don't" unless that is fixed. A dip around the second tenth is the header (the flag comes after the preamble).
- **INCONCLUSIVE** (exit 2): fewer than 20 frames or 20 probes in a tenth. Run again with more frames, or move the boards closer if the frames do not arrive.
- It warns when under 80 % of the frames were received (a CAD and the re-arm take the prober's own receiver off the air for a few milliseconds, so it can lose a frame it probed into; its probes are then *unplaced*, not counted as false busy; widen the probe gap to see the effect: `@lbt probe 300 4000 8000`), when log lines were dropped by a slow console, and when its count disagrees with the firmware's own summary.

### Also measure (SL-25 asks)

- **The false-detect rate on a quiet channel**: `@lbt probe 1` with the transmitter off ends after 60 s with no frame; the report then gives the share of probes (all on a quiet channel) that found it busy. On the desk this is near 0; run it again where the field is.
- **The real CAD time**: in the report (`CAD: ... average`) against SL-25's 4 ms; the energy figures of SL-25 scale with it. The CAD's *current* (SL-25 assumed 6 mA, from memory of the datasheet, front-end module excluded) needs a meter on the board's supply: measure it with the prober running a CAD-only probe (`@lbt probe 1 2000 2000` on a quiet channel keeps the radio in CAD most of the time).
- Run the prober **and** the transmitter in the same room for 3 runs (different frame lengths happen by themselves), and attach the three `prober.log` files to SL-25.

## 4. Put board 2 back to the modem image

In `%USERPROFILE%\atalaia-bench\lbt-modem`:

```bat
"%USERPROFILE%\atalaia-flash\Scripts\python.exe" -m esptool --chip esp32s3 -p COM4 -b 921600 write_flash @flash_args
"%USERPROFILE%\atalaia-flash\Scripts\python.exe" -m esptool --chip esp32s3 -p COM4 --after hard_reset chip_id
```

Then start `com_bridge.py` (COM4 <-> 127.0.0.1:7600) and the `atalaia-controller-bench` container again as before the test, and check that the controller sees the modem. Board 1 stays on the bench image (it is what it ran before); to put it back on an older bench build, flash that build's folder (the previous images are under `prev-*` in the bench folder).

## AS923-TW

Only with a board and an antenna for 920-925 MHz (the Heltec V4 covers 863-928 MHz, but the antenna that came with it is for 868 MHz: check its band, and check that 921.5 MHz is allowed where you are). The AS923-TW bench image is built separately (`python3 tools/docker_fw.py bench --region=as923-tw`, which writes `build-bench/` again; the copy kept for this runbook is `firmware/esp32/build-bench-as923/`, with `flash_args` and the same four items). Copy it to `%USERPROFILE%\atalaia-bench\lbt-bench-as923`, flash **both** boards from there exactly as in step 2, and run the same commands: the channel is 921.5 MHz at SF9/500 kHz (a 1.024 ms symbol too, so the same CAD shape; **the CAD's detection peak of 23 for SF9 comes from a table for 125 kHz and is unproven: this is where it is tested**). The `LBT,cfg` line and the report say `as923-tw`. Put board 2 back to the modem image afterwards (step 4); if the modem image was built for EU868 and the board is going back to Europe, that is the same `lbt-modem` folder. If the antenna or the board cannot do the band, EU868 alone answers SL-25 for Europe and the AS923-TW question stays open.

## After the run

Write the numbers into SL-25 (the table by tenth, the CAD time, the false-detect rate) and into `docs/review/relay-study-results.md` section 11's bench paragraph, and say PASS or "don't". On a PASS the next step is SL-25's build step 2 onwards (the CAD parameters per region in the core's table, the radio task's pending slot, the config key); the HAL operation built here is step 1 and stays.
