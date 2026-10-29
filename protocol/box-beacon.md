# The Field Box as an iBeacon

A Field Box joined to a game advertises a standard **iBeacon** over Bluetooth LE, so that a phone which hears it is placed in the room, on the floor, where the GM put the box on the field view. It sits beside the iBeacon tags the GM registers ([ADR-P3-6](../docs/phase-3-android-players/ADR.md), decisions BLE-1 to BLE-9): both are beacons of the field's registry, a phone is located exactly the same way by either, and a field needs tags only where there is no box. Decisions BBC-1 to BBC-12; one switch in the join payload (key 19, RFC 0001 Amendment 19). Nothing else on the radio or the wire changes.

Shared vectors: [`vectors/box_beacon.json`](vectors/box_beacon.json) (written by `tools/box_beacon_vectors.py` from `hashlib` alone), checked by the box's C (`firmware/esp32/main/box_beacon.c`, test `test_box_beacon.c`), the Pi controller (`controller/atalaia_controller/box_beacons.py`) and the Android controller (`app/lib/controller/controller_box_beacons.dart`); the join's key 19 has its own section in [`vectors/join.json`](vectors/join.json) (`box_beacon`), checked by the three join codecs.

## 1. What a box advertises

One non-connectable, undirected advertisement, the standard 30-byte iBeacon packet:

| Bytes | Value |
| --- | --- |
| `02 01 06` | flags: general discoverable, no BR/EDR |
| `1A FF 4C 00 02 15` | 26 bytes of manufacturer data: Apple's company id `0x004C`, type `0x02`, 21 bytes follow |
| 16 bytes | **proximity UUID**: the field's (below) |
| 2 bytes, big endian | **major**: the constant **45253** (`0xB0C5`) |
| 2 bytes, big endian | **minor**: the box's **node id** in the game (1-65534) |
| 1 byte, signed | measured power at 1 m (dBm); **-59** by default |

- **The UUID is the field's, derived from its join key**, so a phone filters by one UUID for every box of the field and nothing about it has to travel: `HMAC-SHA256(join key, "atalaia box beacon uuid v1")`, the first 16 bytes, with the version nibble set to 8 (custom) and the variant bits to RFC 4122's (`10xx`). The box holds the join key from adoption ([adoption.md](adoption.md)); the controller holds the same key and derives the same UUID. The UUID is public (it is in the air), the key is not: HMAC does not leak it. A field whose join key is rotated has a new UUID, and every box is adopted again anyway.
- **The major is a constant a GM's tag cannot use.** A position report names a beacon by `major:minor` only, unique on the field; a tag the GM registers with major 45253 is refused (HTTP 400), so a box's id never collides with a tag's, whatever UUIDs the tags have.
- **The minor is the box's node id**, which the controller issued in the join and keys the box's position by (ML-4). So `45253:7` is node 7 of the live game.

## 2. When

A box advertises **while it is joined to a field game**: from the join (waiting for the start) until the game ends, paused included. Never between games (no radio time, no power, nothing for a phone to use: a phone shares its position only in a running game), never while it is fetching modes, and not after the end. The GM can turn the beacon off for the field; then the join of each new game carries key 19 (section 4) and the boxes of that game do not advertise. A box that reboots in a game comes back to the same state from its stored join.

On the ESP32-S3 (`firmware/esp32/main/box_beacon_esp.c`) the beacon is NimBLE as a **broadcaster only**: no connection, no scan, no pairing, no bond store. The Bluetooth controller is started on its own task when the box should advertise and **taken down again, with its memory, when it should not**. It also waits while the Wi-Fi is in use (the logo's fetch right after a join, a mode fetch, an update): the controller's memory and the Wi-Fi driver's share the internal RAM.

## 3. How often, how strong, and the radios

| Setting | Default | Why |
| --- | --- | --- |
| Interval | **500 ms** (Kconfig `ATALAIA_BOX_BEACON_INTERVAL_MS`, 100-10000) | An Android scan in low-power mode (what the app uses, BLE-9) listens about 0.5 s in every 5 s. A beacon that advertises less often than that is missed in a good share of the scans (about half at 1 s); at 500 ms nearly every window holds one advertisement. At 0 dBm that is two short events a second. |
| Transmit power | **0 dBm** (`ATALAIA_BOX_BEACON_TX_DBM`, -24 to 20) | About one room, which is what the position means. |
| Measured power | **-59 dBm** (`ATALAIA_BOX_BEACON_MEASURED_POWER`) | Only for other iBeacon apps; the Atalaia app never reads a distance. |

**Coexistence.** The SX1262 (LoRa, 868 MHz or 920-925 MHz) and Bluetooth (2.4 GHz) are different radios and different bands: a beacon does not touch the game's frames. What Bluetooth shares with the ESP32-S3 is its 2.4 GHz radio with **Wi-Fi**, and the box's Wi-Fi is on only for setup and for the between-game fetches above, which the beacon waits for. The Bluetooth controller does use internal RAM (about 25 KB more in the image, and its working memory while it runs, released when it stops): measured in [`docs/runbooks/box-beacon-bench.md`](../docs/runbooks/box-beacon-bench.md).

**Build switch.** Kconfig `ATALAIA_BOX_BEACON` (default **on** for the Field Box). The Wokwi variant has no Bluetooth radio and builds without it; the USB modem and the I/O pod do not advertise (the pod keeps its own Bluetooth link, `capability-proxy.md`).

## 4. The GM's switch: join key 19

Join payload key **19**, `box_beacon` ([join.md](join.md)): CBOR `false` when the GM turned the field's box beacons off, **left out** when they are on (the default; `true` is refused, so a join has one encoding). A payload without the key is byte for byte the payload of before, and a box from before key 19 skips it. The controller writes it from the field's setting (`PUT /api/v1/box-beacons`), read when the join is made: a game already joined keeps what its boxes were told, and the next game's join says what the setting is then. Turning the switch off also removes the boxes from the registry at once, so a phone's report of a box is refused from then on even in the live game, whatever the box still sends.

## 5. What the controller does with it

The controller **registers each box's beacon by itself, from the box's own position**, and shows it in the console's beacons panel as a **Field Box** (not editable as a tag, but it can be disabled). Nothing is typed:

- **`uuid`**: the field's, derived as above. **`major`**: 45253. **`minor`**: the node id.
- **`room`**: the box's name (the GM's name for it in a scenario, else the node's own name), or a room the GM gives it (`PUT /api/v1/box-beacons/{node_id}` with `room`; `null` gives the name back).
- **`level`, `x`, `y`**: the box's place on the field view (ML-4: its level and its place on that level's plan), so **moving the box, or changing its level, moves its beacon**. A level not in use shows level 0, as the box does.
- **A box the GM has not placed is not registered**: it has no level and no place. It still advertises, and a phone that hears it reports nothing.
- **Disabled** (`enabled: false`): left out of the registry for phones and shown disabled to staff; a report of it is refused.
- The boxes belong to the **live game** (a node id is the game's) and are never stored; only the GM's choices are (settings `box_beacons`, and per game `box_beacons_off:<id>` and `box_beacon_rooms:<id>`).

`GET /api/v1/beacons` lists the GM's tags and the boxes together: staff see every box with `kind: "box"`, `node_id`, `name`, `room`, `room_given`, `level`, `x`, `y` and `enabled`, and the field's setting as `box_beacons: {enabled, major, uuid}`; **every other token is given each tag's and each enabled box's `id` and `uuid` only**, which is what a phone needs to listen for them (the box UUID is one more entry in the UUID list its hardware scan filter is built from, BLE-9: **the app needs nothing else**). Staff are told by the `beacons` stream message when a box is placed or moved, disabled, or given a room; a phone reads the registry when it starts to share (BLE-5), so boxes are best placed before the game.

A phone that hears a box reports `source: ble`, `beacon_id: "45253:7"`; the controller turns it into the room, level and plan place as for a tag (BLE-3, BLE-4, BLE-8), and the strongest beacon the phone hears, tag or box, wins as it does today.

## 6. Threat model

- The advertisement carries nothing secret: the UUID is derived with an HMAC, the major is a constant, the minor is a node id. Anyone with a phone can see that a box is there and which node it is, as with any beacon; the position of a *player* is still decided by the controller, which accepts only a registered, enabled box (constraint 9: no client trust).
- A person with a Bluetooth radio can **replay or fake** a box's advertisement (any iBeacon can be copied) to make their own phone report that room. That is the same exposure as a tag, and no worse: the phone reports a room, never a point, and a modified app could report any room of the registry anyway.
- A box's Bluetooth address is the board's, public and fixed; a box is not a person.
