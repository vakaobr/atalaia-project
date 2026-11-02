<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Bench test: a flaky I2C bus must not reboot the box

Decisions I2C-1 to I2C-6. Context: on 2026-10-31 a keypad with bad solder joints rebooted board 5
six times in three minutes (`Interrupt wdt timeout on CPU0` in `i2c_isr_handler_default`), and the
controller logged each restart as `node.rebooted` with reason `power`. The firmware now uses the
`i2c_master` driver and skips a failing device with a growing back-off
(`firmware/esp32/README.md`, "The I2C bus must never take the box down"). The host tests cover
the back-off logic and the reason words; **this runbook is the part only real hardware can show.**

Needs: a Field Box image from this change (`python tools/docker_fw.py build`), a board with the
keypad (and the OLED), a Pi or phone controller with a game running on the box, a serial console
(open the port without asserting DTR/RTS: `bootlog.py`'s way, or the box resets).

1. **Healthy baseline.** Flash, join a game, start it. The log has `hal_i2c: I2C bus on SDA 17,
   SCL 18`, `hal_kp: PCF8574 keypad at 0x20` and no `suspended` line. Keys work.
2. **Pull the keypad's SDA while the game runs** (a jumper wire to the header, unplug it by
   hand). Expect within a second: `hal_i2c: device 0x20 suspended after 3 failures`, then
   `still failing` lines about 0.5, 1, 2, 4... s apart (up to 30 s). **No reboot**, the game and
   the console's feed carry on, the team buttons still work, no `Interrupt wdt` or `Guru
   Meditation`. Leave it 5 minutes.
3. **Plug it back.** Within 30 s: `device 0x20 answers again`; keys work again.
4. **Make it noisy.** Touch SDA and SCL with a finger or a long wire for a minute while keys are
   pressed; try the keypad's bad-joint board (board 5) as it was. Expect `suspended`/`answers
   again` cycles and possibly `bus reset after a run of failed transactions`, never a restart.
   Record the number of `hal_i2c` lines per minute (it must stay low: the back-off bounds it).
5. **Hold SCL low** (to GND through a 1 kohm) for 10 s, release. The OLED, keypad, NFC and gauge
   all report failures, then recover after the release. No restart.
6. **A restart that is a crash reports as one.** Optional, to see the controller side: with a
   game running, crash the box on purpose (there is no command for it: a scratch build that
   calls `abort()`; pulling the USB power is not a crash and must read `power`). After a panic the console's feed reads
   "A box crashed and restarted (program crash)" and the API log's `node.rebooted` has
   `data.reason` `panic`; after a watchdog reset `watchdog`.

Pass: steps 2, 4 and 5 show no restart, and step 3 shows the recovery. Write the result and the
`hal_i2c` log lines in the wave report.
