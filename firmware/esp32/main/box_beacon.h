/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The Field Box as an iBeacon (protocol/box-beacon.md, decisions BBC-1 to BBC-12): what it
 * advertises, as bytes. Platform-free: the NimBLE side (box_beacon_esp.c) only hands these
 * bytes to the Bluetooth controller, and the host tests check them against the shared vectors
 * (protocol/vectors/box_beacon.json).
 *
 *   - The proximity UUID is the field's: HMAC-SHA256(join key, "atalaia box beacon uuid v1")
 *     cut to 16 bytes, with the version nibble set to 8 and the variant to RFC 4122's, so it is
 *     a well-formed UUID. Every box of the field has the same one (a phone filters by it) and the
 *     controller, which holds the join key, derives the same.
 *   - The major is the constant BOX_BEACON_MAJOR. The GM's own beacons (tags) may not use it (the
 *     controller refuses them), so a box's id "major:minor" never collides with a tag's.
 *   - The minor is the box's node id in the game (1-65534), which the controller knows from the
 *     join it made and keys the box's position by.
 *
 * The packet is the standard 30-byte iBeacon advertisement: flags, then Apple's manufacturer
 * data (company id 0x004C, type 0x02, length 0x15, UUID, major and minor big-endian, the
 * calibrated power at one metre).
 */
#ifndef ATALAIA_BOX_BEACON_H
#define ATALAIA_BOX_BEACON_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define BOX_BEACON_MAJOR      0xB0C5u /* 45253 */
#define BOX_BEACON_UUID_SIZE  16
#define BOX_BEACON_ADV_SIZE   30
#define BOX_BEACON_KEY_SIZE   32
#define BOX_BEACON_UUID_LABEL "atalaia box beacon uuid v1"

typedef struct {
    uint8_t uuid[BOX_BEACON_UUID_SIZE];
    uint16_t major;
    uint16_t minor;
} box_beacon_id_t;

/* The field's beacon UUID from its join key. */
void box_beacon_uuid(const uint8_t join_key[BOX_BEACON_KEY_SIZE],
                     uint8_t uuid[BOX_BEACON_UUID_SIZE]);

/* The box's identity for a join key and node id: the field's UUID, BOX_BEACON_MAJOR, the node id.
 * False for a node id that is no box's (0 or 0xFFFF). */
bool box_beacon_id(const uint8_t join_key[BOX_BEACON_KEY_SIZE], uint16_t node_id,
                   box_beacon_id_t *out);

/* The 30 advertisement bytes of an iBeacon with this identity and calibrated power (dBm at 1 m).
 * Returns BOX_BEACON_ADV_SIZE. */
size_t box_beacon_adv(const box_beacon_id_t *id, int8_t measured_power,
                      uint8_t out[BOX_BEACON_ADV_SIZE]);

/* "XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX" (upper case) and the NUL: 37 bytes. */
void box_beacon_uuid_text(const uint8_t uuid[BOX_BEACON_UUID_SIZE], char out[37]);

/* The 0.625 ms units of the controller's advertising interval for a time in milliseconds,
 * clamped to the range Bluetooth allows for a non-connectable advertiser (20 ms to 10.24 s). */
uint16_t box_beacon_interval_units(uint32_t interval_ms);

#endif /* ATALAIA_BOX_BEACON_H */
