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

The channel is the build's region default: **EU868, 869.525 MHz, SF7/125 kHz** (the image from `docker_fw.py bench`). AS923-TW's modulation (SF9/500 kHz, detPeak 23) is tested on a **legal EU channel, 868.3 MHz**, with the same image and one more word on the command (`proxy=as923`): see "The AS923-TW modulation on 868.3 MHz" at the end. A bench in Europe never transmits on 921.5 MHz.

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

Without the tool, any serial terminal on the port works (type `@lbt probe 300` and Enter; save the output; `python3 tools/bench_lbt_gate.py saved.log`). Commands: `@lbt tx [frames]` (default 300, at most 1000), `@lbt probe [frames [gap_min_us gap_max_us]]` (default 300, 2000 5000), `@lbt stop`, `@lbt status`. Add `proxy=as923 [peak=N] [min=N] [power=dBm]` to `tx` or `probe` for the AS923-TW modulation on 868.3 MHz (default 100 frames, at most 123 for `tx`).

### The lines to expect

Prober (`LBT,` lines among the usual log; the `p` lines are every probe, about 250 a second):

```text
LBT,cfg,role=probe,profile=build,region=eu868,mod=eu868,freq=869525000,sf=7,bw=125000,sym_us=1024,cad_sym=2,det_peak=22,det_min=10,peak_proven=1,duty_ppm=100000,limit_dbm=27,tx_dbm=hal
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
LBT,cfg,role=tx,profile=build,region=eu868,mod=eu868,freq=869525000,sf=7,bw=125000,sym_us=1024,cad_sym=2,det_peak=22,det_min=10,peak_proven=1,duty_ppm=100000,limit_dbm=27,tx_dbm=hal
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

## The AS923-TW modulation on 868.3 MHz

SL-25's AS923-TW question is the CAD's detection peak at SF9/500 kHz (the core's `atalaia_region_info(AS923_TW)->cad`). Semtech's 23, from a table for 125 kHz, failed here on 2026-10-26 (17.8 % false busy on a quiet channel); the table now has **29** (0.5 %, frames still detected; decision SL-38), still **unproven** on an AS923-TW image. CAD behaves by SF and bandwidth, not by carrier, so the test needs the modulation, not 921.5 MHz, which is not allowed here (and the boards' antennas are for 868 MHz). The bench image runs **AS923-TW's modulation on 868.3 MHz** when the command says `proxy=as923`:

| | the proxy run |
|---|---|
| modulation | SF9, 500 kHz, CR 4/5, the AS923-TW table's CAD settings: 2 symbols, **detPeak 29**, detMin 10 (`peak=N` / `min=N` change them for a sweep) |
| channel | **868.3 MHz, 500 kHz wide: 868.05-868.55 MHz**, inside EU868 sub-band g (868.0-868.6 MHz) |
| limits | sub-band g's: **1 % duty (36 s of airtime per rolling hour), 14 dBm = 25 mW ERP**: with the Kconfig defaults (FEM 14 dB, antenna 2 dBi) 0 dBm conducted is the legal maximum |
| TX power | **-9 dBm conducted** by default (the SX1262's lowest, 9 dB under the 0 dBm limit; the boards are metres apart). `power=N` raises it, up to 0: the radio refuses more |
| frames | 100 by default, at most 123 (see the duty below) |

The EU868 bench image itself is unchanged: the profile is applied when the run starts and the build's own settings (SF7/125 kHz, 869.525 MHz) are put back when it ends (`@lbt stop` included). Safety: the firmware and the report tool refuse a proxy channel that is not wholly inside 868.0-868.6 MHz, or that touches 920-925 MHz (host-tested, `lbt_profile_channel_ok`); there is no command to choose the frequency; the profile exists only in an EU868 image; the sub-band's duty budget is the HAL's own (`radio_limits`, with the SF9/500 kHz airtime), so what g has spent stays spent.

### Duty of one run

Sub-band g allows 1 % of the rolling hour: **36 000 ms** of airtime. A STATE-length frame (48-56 bytes) at SF9/500 kHz takes **77.1-87.3 ms** (82.2 ms at 52 bytes; `atalaia_airtime_us`; EU868's SF7/125 kHz takes 97.5-107.8 ms).

| run | air | share of g's hour |
|---|---|---|
| one frame | 77-87 ms | |
| **default, 100 frames** (avg. 82 ms) | **about 8.2 s** (at most 8.7 s) | **0.23 % of the hour, 23 % of the 1 % budget** |
| the self-stop's cap, 123 frames (all 56 bytes: 10.7 s) | at most 10.8 s | 0.30 % of the hour, 30 % of the budget |
| 300 frames (EU868's default) | about 24.6 s | 68 % of the budget: **not allowed** (`tx 300 proxy=as923` is refused) |

The transmitter stops by itself (`reason=duty_guard`) when the budget left falls under **70 %** of 36 000 ms (25 200 ms), counting every earlier run in the rolling hour: so a second 100-frame run less than an hour after the first stops after about 30 frames. The command refuses more than **123 frames** (what 30 % of the budget allows at the longest frames). While the run lasts the spacing (300-700 ms, 82 ms frames) is about 14 % duty; only the rolling hour is limited and stays at 0.3 %. The `LBT,tsum` lines give `run_duty_pm`, `left_ms` (of 36 000) and `hour_used_pm` (of the hour, per mille).

### Steps

1. **Build** (the image is the EU868 bench image, the same as for the EU run; this checkout's `docker_fw.py bench` gives it, and the folder to flash is already copied to `firmware/esp32/build-bench-as923proxy/`, which holds `flash_args`, the app, `ota_data_initial.bin` and the two small folders):

   ```sh
   python3 tools/docker_fw.py bench      # -> firmware/esp32/build-bench/ ; then in WSL, from the checkout:
   mkdir -p /mnt/c/Users/<you>/atalaia-bench/lbt-bench-as923proxy
   cp -r firmware/esp32/build-bench-as923proxy/* /mnt/c/Users/<you>/atalaia-bench/lbt-bench-as923proxy/
   ```

   (If you rebuilt, copy `flash_args`, `atalaia_esp32.bin`, `ota_data_initial.bin`, `bootloader/bootloader.bin` and `partition_table/partition-table.bin` from `build-bench/` the same way.) Boards flashed with an earlier bench image do not know `proxy=` (`@lbt` says "usage"): flash them again.
2. **Flash both boards** from `%USERPROFILE%\atalaia-bench\lbt-bench-as923proxy`, exactly as step 2 above (board 1 COM3, board 2 COM4; stop `com_bridge.py` and `atalaia-controller-bench` first).
3. **Run**, from `%USERPROFILE%\atalaia-bench`, **prober first** (board 1, COM3):

   ```bat
   "%USERPROFILE%\atalaia-flash\Scripts\python.exe" \\wsl.localhost\Ubuntu-22.04\home\andersonleite\code\atalaia-project\tools\bench_lbt_gate.py --capture COM3 --send "@lbt probe 100 proxy=as923" --out prober-as923.log
   ```

   **then, within a minute, the transmitter** (board 2, COM4, a second window):

   ```bat
   "%USERPROFILE%\atalaia-flash\Scripts\python.exe" \\wsl.localhost\Ubuntu-22.04\home\andersonleite\code\atalaia-project\tools\bench_lbt_gate.py --capture COM4 --send "@lbt tx 100 proxy=as923" --out tx-as923.log
   ```

   100 frames take about a minute. Both consoles print the profile: `LBT,cfg,...,profile=as923-eu868,region=eu868,mod=as923-tw,freq=868300000,sf=9,bw=500000,sym_us=1024,cad_sym=2,det_peak=23,det_min=10,peak_proven=0,duty_ppm=10000,limit_dbm=14,tx_dbm=-9`. If either prints `LBT,end,...,reason=profile` the radio refused the profile and transmitted nothing. The report (the tool prints it when the prober ends) starts with the profile, the channel, the CAD under test and the duty limit.
4. **The quiet channel** (false detect), transmitter off: `--send "@lbt probe 1 proxy=as923"` on board 1; it ends after 60 s with no frame and reports the share of probes that found the channel busy.
5. Three runs for the record, an hour apart (the budget), attach the logs to SL-25; **put board 2 back to the modem image (step 4 above)**.

### What PASS means for the detection peak

`PASS` (exit 0), in the same report as the EU run: **more than 90 % of the probes made inside a frame find the channel busy, overall and in every tenth of the frame**, at SF9/500 kHz with the table's detPeak (the report says, for example, `with detPeak 29 at SF9 / 500 kHz`), **and** the quiet-channel run (step 4) finds the channel busy in well under 1 % of its probes. Then that peak holds at SF9/500 kHz: set `det_peak_bench_proven` to `true` in the AS923-TW row of `core/src/duty_cycle.c` (and update `core/include/atalaia/duty_cycle.h`'s comment, SL-34, the radio field-test runbook's AS923-TW note and `relay-study-results.md` section 13), and a Taiwanese field may keep `--lbt=on`. Read the preamble row and `found busy by: CAD` too: the receiver's flags cover most of a frame, so the CAD's own share shows in the first 12.25 symbols of each frame (12.5 ms); a preamble row far under the rest means the CAD alone misses preambles at this peak. Carrier and antenna differ from the 921.5 MHz case (868 MHz, the 868 MHz antennas): that does not change a CAD's detection, but the real AS923-TW channel is still unmeasured on air; say so in SL-25.

### If it fails

`FAIL` (exit 1) or a high false-busy rate: try other peaks, **on the prober** (the transmitter's CAD is not used), one value per run, with `peak=N` (allowed 10-40) and `min=N` (1-30), each run needing the transmitter again; use `tx 40` (about 3.3 s of air, 0.09 % of the hour: at least 20 frames are needed for a verdict) so that several values fit in the budget:

```bat
... --capture COM3 --send "@lbt probe 40 proxy=as923 peak=21" --out prober-p21.log
... --capture COM4 --send "@lbt tx 40 proxy=as923" --out tx-p21.log
```

Try 21, 22, 24, 25 (a lower peak is more sensitive and falsely busier; a higher one the reverse), then keep the highest peak that still passes with a quiet-channel false-busy rate under 1 %. A run with `peak=` prints `peak_proven=0`: only the unchanged table value, once proven, is written back as proven. A FAIL with `found busy by: CAD` only, and no flags (the cliff after the first tenth) is the EU868 finding again: the receiver's flags never showed; the peak does not matter then. If the boards cannot hear each other at -9 dBm (frames missing, `reason=idle`), run both with `power=-3` or `power=0`: the legal limit in g is 0 dBm conducted.

### An AS923-TW image on an AS923-TW antenna

The other way to test it, in Taiwan or with a board and an antenna made for 920-925 MHz and the right to transmit there: `python3 tools/docker_fw.py bench --region=as923-tw` writes `build-bench/` again (the copy for that is `firmware/esp32/build-bench-as923/`, with `flash_args` and the same four items); flash **both** boards from it as in step 2 and run the plain commands (`@lbt probe 300`, `@lbt tx 300`; 921.5 MHz, SF9/500 kHz, its 10 % budget): the `LBT,cfg` line and the report say `as923-tw`. Never transmit on 921.5 MHz where it is not allowed.

## After the run

Write the numbers into SL-25 (the table by tenth, the CAD time, the false-detect rate) and into `docs/review/relay-study-results.md` section 11's bench paragraph, and say PASS or "don't". On a PASS the next step is SL-25's build step 2 onwards (the CAD parameters per region in the core's table, the radio task's pending slot, the config key); the HAL operation built here is step 1 and stays.
