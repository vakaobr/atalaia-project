/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The Field Box's iBeacon bytes (main/box_beacon.c, decisions BBC-1 to BBC-12) against the shared
 * vectors (protocol/vectors/box_beacon.json, made by tools/box_beacon_vectors.py from hashlib
 * alone): the field's UUID from the join key, the 30 advertisement bytes for a node id and a
 * calibrated power, the node ids that are no box's, and the advertising interval's units. When the
 * box advertises at all (the phases of a game, key 19) is test_box_game.c's.
 */
#include <string.h>

#include "box_beacon.h"
#include "box_beacon_vectors.h"
#include "check.h"

static void test_uuid(void)
{
    CHECK(BOX_UUID_VECTOR_COUNT >= 3);
    for (size_t i = 0; i < BOX_UUID_VECTOR_COUNT; i++) {
        const box_uuid_vector_t *v = &box_uuid_vectors[i];
        uint8_t uuid[BOX_BEACON_UUID_SIZE];
        box_beacon_uuid(v->join_key, uuid);
        CHECK(memcmp(uuid, v->uuid, sizeof(uuid)) == 0);
        CHECK((uuid[6] >> 4) == 8 && (uuid[8] >> 6) == 2); /* a well-formed UUID */
        char text[37];
        box_beacon_uuid_text(uuid, text);
        CHECK(strcmp(text, v->text) == 0);
    }
    /* Another field has another UUID. */
    uint8_t a[16], b[16];
    box_beacon_uuid(box_uuid_vectors[0].join_key, a);
    box_beacon_uuid(box_uuid_vectors[1].join_key, b);
    CHECK(memcmp(a, b, sizeof(a)) != 0);
}

static void test_adv(void)
{
    CHECK(BOX_ADV_VECTOR_COUNT >= 6);
    for (size_t i = 0; i < BOX_ADV_VECTOR_COUNT; i++) {
        const box_adv_vector_t *v = &box_adv_vectors[i];
        box_beacon_id_t id;
        CHECK(box_beacon_id(v->join_key, (uint16_t)v->node_id, &id));
        CHECK(id.major == BOX_VECTOR_MAJOR && id.major == BOX_BEACON_MAJOR &&
              id.minor == v->node_id);
        uint8_t adv[BOX_BEACON_ADV_SIZE];
        CHECK(box_beacon_adv(&id, (int8_t)v->power, adv) == BOX_BEACON_ADV_SIZE);
        CHECK(memcmp(adv, v->adv, sizeof(adv)) == 0);
        /* What a phone's scan filter matches (Apple's id, type 0x02, length 0x15, the UUID). */
        CHECK(adv[5] == 0x4C && adv[6] == 0x00 && adv[7] == 0x02 && adv[8] == 0x15);
        CHECK(memcmp(adv + 9, id.uuid, 16) == 0);
        CHECK(adv[0] == 0x02 && adv[1] == 0x01 && adv[2] == 0x06 && adv[3] == 0x1A &&
              adv[4] == 0xFF);
    }
    box_beacon_id_t id;
    for (size_t i = 0; i < BOX_REFUSED_COUNT; i++) {
        CHECK(!box_beacon_id(box_uuid_vectors[0].join_key, (uint16_t)box_refused_node_ids[i], &id));
    }
}

static void test_interval(void)
{
    CHECK(BOX_INTERVAL_VECTOR_COUNT >= 7);
    for (size_t i = 0; i < BOX_INTERVAL_VECTOR_COUNT; i++) {
        CHECK(box_beacon_interval_units(box_interval_vectors[i].ms) ==
              box_interval_vectors[i].units);
    }
}

static void test_memory_gate(void)
{
    /* The controller starts with enough internal RAM in all and in one block, and only then. */
    CHECK(box_beacon_memory_ok(BOX_BEACON_MIN_INTERNAL_FREE, BOX_BEACON_MIN_INTERNAL_LARGEST));
    CHECK(box_beacon_memory_ok(120000, 60000));
    CHECK(!box_beacon_memory_ok(BOX_BEACON_MIN_INTERNAL_FREE - 1, BOX_BEACON_MIN_INTERNAL_LARGEST));
    CHECK(!box_beacon_memory_ok(BOX_BEACON_MIN_INTERNAL_FREE, BOX_BEACON_MIN_INTERNAL_LARGEST - 1));
    /* The bench's two failures (2026-10-29): 11 KB free with the beacon in, 19 KB without. */
    CHECK(!box_beacon_memory_ok(19079, 6400));
    CHECK(!box_beacon_memory_ok(43555 - 30000, 20480));
    CHECK(!box_beacon_memory_ok(0, 0));
}

void run_box_beacon_tests(void)
{
    test_memory_gate();
    test_uuid();
    test_adv();
    test_interval();
}
