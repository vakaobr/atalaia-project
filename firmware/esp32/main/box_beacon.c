/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The Field Box as an iBeacon: the bytes (box_beacon.h).
 */
#include "box_beacon.h"

#include <stdio.h>
#include <string.h>

#include "atalaia/join.h"

void box_beacon_uuid(const uint8_t join_key[BOX_BEACON_KEY_SIZE],
                     uint8_t uuid[BOX_BEACON_UUID_SIZE])
{
    uint8_t mac[32];
    atalaia_hmac_sha256(join_key, BOX_BEACON_KEY_SIZE, (const uint8_t *)BOX_BEACON_UUID_LABEL,
                        sizeof(BOX_BEACON_UUID_LABEL) - 1, mac);
    memcpy(uuid, mac, BOX_BEACON_UUID_SIZE);
    uuid[6] = (uint8_t)((uuid[6] & 0x0F) | 0x80); /* version 8: custom */
    uuid[8] = (uint8_t)((uuid[8] & 0x3F) | 0x80); /* variant of RFC 4122 */
}

bool box_beacon_id(const uint8_t join_key[BOX_BEACON_KEY_SIZE], uint16_t node_id,
                   box_beacon_id_t *out)
{
    if (node_id == 0 || node_id == 0xFFFF) return false;
    box_beacon_uuid(join_key, out->uuid);
    out->major = (uint16_t)BOX_BEACON_MAJOR;
    out->minor = node_id;
    return true;
}

size_t box_beacon_adv(const box_beacon_id_t *id, int8_t measured_power,
                      uint8_t out[BOX_BEACON_ADV_SIZE])
{
    static const uint8_t head[] = {
        0x02, 0x01, 0x06,       /* flags: general discoverable, no BR/EDR */
        0x1A, 0xFF, 0x4C, 0x00, /* 26 bytes of manufacturer data, Apple's company id */
        0x02, 0x15,             /* iBeacon, 21 bytes follow */
    };
    memcpy(out, head, sizeof(head));
    memcpy(out + sizeof(head), id->uuid, BOX_BEACON_UUID_SIZE);
    size_t p = sizeof(head) + BOX_BEACON_UUID_SIZE;
    out[p++] = (uint8_t)(id->major >> 8);
    out[p++] = (uint8_t)(id->major & 0xFF);
    out[p++] = (uint8_t)(id->minor >> 8);
    out[p++] = (uint8_t)(id->minor & 0xFF);
    out[p++] = (uint8_t)measured_power;
    return p; /* 30 */
}

void box_beacon_uuid_text(const uint8_t uuid[BOX_BEACON_UUID_SIZE], char out[37])
{
    snprintf(out, 37, "%02X%02X%02X%02X-%02X%02X-%02X%02X-%02X%02X-%02X%02X%02X%02X%02X%02X",
             uuid[0], uuid[1], uuid[2], uuid[3], uuid[4], uuid[5], uuid[6], uuid[7], uuid[8],
             uuid[9], uuid[10], uuid[11], uuid[12], uuid[13], uuid[14], uuid[15]);
}

uint16_t box_beacon_interval_units(uint32_t interval_ms)
{
    uint32_t units = (interval_ms * 1000u + 312u) / 625u;
    if (units < 0x0020u) units = 0x0020u; /* 20 ms */
    if (units > 0x4000u) units = 0x4000u; /* 10.24 s */
    return (uint16_t)units;
}

bool box_beacon_memory_ok(size_t internal_free, size_t internal_largest)
{
    return internal_free >= BOX_BEACON_MIN_INTERNAL_FREE &&
           internal_largest >= BOX_BEACON_MIN_INTERNAL_LARGEST;
}
