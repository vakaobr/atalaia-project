<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Phase 2 -- Field Network: Implementation Notes

## Wokwi Radio Init Bisection (Phase C)

**Root cause:** The original `sx_wait_busy()` helper looped
indefinitely while the BUSY pin was high.  On the Wokwi DevKitC-1
emulator, GPIO 13 (BUSY) floats and can read as permanently high,
hanging the radio init and starving LittleFS of CPU time.  The
hang caused the symptoms originally attributed to "SPI3 corrupting
flash": the LittleFS mount timeout was reached, the format did not
complete, and the preset store read returned garbage.

**Bisection evidence (2026-10-18):**

| Step | What it adds | Scenario result |
|------|-------------|-----------------|
| 1 | `spi_bus_initialize(SPI3_HOST)` only | Pass |
| 2 | + `spi_bus_add_device` | Pass |
| 3 | + GPIO config for RST, BUSY, DIO1 (no ISR) | Pass |
| 4 | + DIO1 ISR install | Pass |
| 5 | + Reset pulse + BUSY wait (with timeout) | Pass |
| 6 | + First SPI transaction (SyncWord probe) | Pass |
| 0 | Full init (all steps, no debug stop) | Pass |

All six steps pass individually and the full init (step 0) passes
after the fix.  The `CONFIG_ATALAIA_RADIO_DEBUG_STEP` Kconfig
option remains available for future bisection.

**Fix (applied):**

1. `sx_wait_busy()` now has a 200-iteration timeout instead of an
   infinite loop.
2. The step-5 BUSY wait also has a 100-iteration timeout.
3. `CONFIG_ATALAIA_RADIO_DISABLE` is no longer set in
   `sdkconfig.wokwi`.  The radio init runs, correctly logs
   "SX1262 not detected (sync_hi=0x00)", cleans up, and the game
   continues.

**Test coverage for the radio layer:**

- 10 radio protocol tests (`test_radio_protocol.c`): boot epoch,
  first boot, NVS write failure, seq wrap epoch increment, seq wrap
  NVS failure, epoch exhaustion, receiver epoch trial (known source,
  reboot, lower epoch rejection, unknown source).
- 6 TX power tests (`test_radio_power.c`): g-band default, g2-band
  default, no FEM, high-gain antenna, clamp low, clamp high.
- 4 radio HAL stub tests (`test_radio_stub.c`): send, recv,
  duty-cycle, channel set.
- All tests run on Linux with the stub HAL and test-stub crypto
  backend (XOR + FNV-1a, from `packet.c`).

## Single Shared Game Channel (Amendment 1, 2026-10-18)

The original design (ADR-P2-13, RFC 0001 section 8) specified
three-channel round-robin hopping on the g-band.  This was
incompatible with single-radio half-duplex operation: after TX on
channel N, the SX1262 listens on channel N, so nodes that last
transmitted on different channels miss each other.

Amendment 1 of RFC 0001 replaces the hopping with a single shared
game channel, by default 869.525 MHz (g2 sub-band, 10% duty cycle,
500 mW ERP).  All traffic uses the same channel.  The channel is
configurable per game via the CONFIG message and validated against
the EU868 sub-band table.

See `docs/rfcs/0001-skirmesh-rf-wire-format.md` Amendment 1 for
the full rationale.

## Phase D: field controller and USB modem (2026-10-18)

### One radio side, two hosts

The simulator's `FieldController` (`simulator/atalaia_sim/field_controller.py`)
now sends through a transport instead of calling the radio model
directly, and gained what a real controller needs: ACKs per box and per
epoch (`AckTracker`), event decoding with replay dedupe, TIME beacons
with every required field, ADR-P2-3 CMD opcodes, events the controller
itself originates (GM adjustments, field scripts, lifecycle), and the
CLAIM election (`election.py`). The real controller
(`controller/atalaia_controller/engine.py`) runs this same class with a
`ModemTransport`; the simulator runs it with a `RadioTransport`. Failover
is therefore tested where it can be tested without boards, over the
radio model with two and three controllers (`test_failover_sim.py`).

### The modem is plain C with injected I/O

`main/modem/modem.c` and `modem_framing.c` have no ESP-IDF dependency:
`modem_task.c` (ESP only) supplies the serial link and the radio task.
The same two files run in three places: on the ESP32-S3, in the host
unit tests with the stub crypto (`test/test_modem.c`,
`test/test_modem_framing.c`), and in `test/modem_host/`, a Linux program
with mbedtls AES-CCM whose serial link is a TCP socket and whose air is
UDP. The controller's tests open it with pyserial's `socket://` URL,
exactly as the Pi opens `/dev/ttyACM0`, so Python framing, C framing,
C encryption and Python decryption (and back) are checked against each
other, and the watchdog is tested against a modem process that is
killed and restarted.

The radio task gained tagged TX results (for TX_ACK), a channel request
queue and a cached duty-cycle figure, because only the radio task may
touch the SPI bus.

### Findings fixed along the way

- **The C payload codec did not match the schema.** HELLO capabilities
  were a byte string, STATE counters and CLAIM acks arrays of maps, CMD
  params text; required fields were left out when zero; decoders checked
  nothing. The shared-vector tests in C and in Python skipped any vector
  they could not decode, so phase A's "C and Python verify the same
  vectors" was true only for the vectors that happened to agree. The C
  codec now follows the schema and RFC 0001 exactly, both test suites
  are strict, and the invalid vectors are checked too (decision D8).
- **The simulator's ctypes structs were short.** `atalaia_node_callbacks_t`
  gained `field_state` and `atalaia_node_config_t` `field_ops` in phase C,
  but `core.py` was not updated, so the core read past the end of the
  Python config. Fixed, with `field_ops` callbacks from Python.
- **The Python CBOR codec could not encode byte strings**, so the ACK
  bitmap never worked. Payloads may now carry them; event data still may
  not (it is JSON).
- **Event identity after a reboot.** A box restarts its event seq at 1,
  so the events table is UNIQUE on (game, node, seq, game time, type)
  (decision D6), and packet dedupe and ACKs are keyed by epoch.
- **`sx_wait_busy()` ignored its timeout.** It now returns -1, `sx_cmd()`
  propagates it and SPI errors, and the probe reports "SX1262 not
  detected (BUSY stuck high after reset)" in Wokwi and releases the bus.

### Known limits

- ACK `ack_seq` is "highest contiguous seq", but STATE and telemetry share
  the seq space and are never resent, so one lost STATE leaves a gap that
  only the bitmap covers (decision D7, an RFC question).
- The Field Box shell did not yet use the radio protocol (decision D18):
  done in phase E, below.
- The modem reports SNR as 0: the radio HAL does not read it yet.

## Phase E: join flow, boxes on the radio, GM console (2026-10-18)

### The join payload

ADR-P2-12 listed the join's fields but not their encoding, and its HMAC
key was "the controller's long-term key", which a box cannot check. The
payload is now a version byte, a CBOR map with integer keys and an
HMAC-SHA256 tag keyed with a **field join key** that every controller and
box of a field holds (protocol/join.md, RFC 0001 Amendment 2, decisions E1
and E2). It also carries what a box or a standby controller needs before
its first TIME beacon: the controller's id, the channel, the relay clamp,
the seed, the parameters and its kind. The C codec (`core/src/join.c`)
has its own SHA-256 so the core still needs no crypto library for it; it
is checked against RFC 4231 and, with the Python codec, against the same
vectors, invalid ones included (each with a correct tag, so they test the
body checks).

### One box program, three places

`main/box_game.c` (join, game lifecycle from CMD and TIME, rejoin after a
reboot) and `main/radio/field_link.c` (the radio side) are plain C with
injected storage, screens, clock and TX sink. They run on the ESP32-S3
(`shell.c`), in the host unit tests with the stub HAL and test crypto,
and in `test/box_host/`, a Linux program with mbedtls whose radio is UDP
and whose NVS and flash are files. The controller's end-to-end tests start
the host modem and host boxes on a Python UDP hub (`AirHub`, which can
also put two programs out of each other's range) and play whole games:
the controller's join text typed into the box's console, HELLO, CMD
start, a capture logged once and acknowledged, STATE counters adding up,
pause and resume, a battery pull (kill and restart with the same files:
new epoch, `node.rebooted`, no lost capture, a new capture with the event
seq restarted), the end (the box forgets the key), and a box out of the
modem's range heard through another box's relay.

### Findings fixed along the way

- **Retries must be new packets.** The modem and the controller drop a
  packet they have seen (same source, epoch and seq) as a flood copy, so
  resending the identical packet after a lost ACK would never be
  acknowledged. Each retry is a new packet with a new seq (decision E8).
- **The relay rule.** `flood.c` treats hop_limit as the relays left (1 is
  relayed once more, with 0); the box follows it (E9).
- **Stack.** The Wokwi join scenario overflowed the 8 KB game task during a
  join: the preset list (3.7 KB) moved off the stack and the task got
  12 KB (E15).
- **The test harness.** A host box that rejoins prints log lines before
  READY; the helper first read the wrong line and then blocked reading the
  stderr of a live process. Found by a hang, fixed in `support.py`.
- **The store under load.** The browser tests hit an intermittent HTTP 500:
  the API's threads and the engine share one SQLite connection, and rows
  were fetched after the lock was released. `_exec` now reads the rows
  while it holds the lock.

### Known limits

- Nothing of this has run on the boards: the SX1262 link, the PN532 with
  real NTAG cards, NVS encryption on a provisioned box (phase F).
- Boxes cannot join over Wi-Fi (E3); `set_owner` has no effect on the
  built-in modes (E7); penalties are not in the box counters (E6).
- An ACK names a seq but not the epoch: after the box's seq wraps
  (65,536 packets) an ACK for the old epoch could clear a new packet with
  the same seq. Not reachable in a game; worth an RFC with D7.
