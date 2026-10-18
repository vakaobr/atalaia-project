/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Player tag codec against the shared vectors (protocol/vectors/tag.json,
 * also checked by simulator/tests/test_tag.py). Every vector is checked;
 * none is skipped.
 */
#include <stdio.h>
#include <string.h>

#include "atalaia/tag.h"
#include "check.h"
#include "packet_vectors.h"

static const uint8_t other_key[16] = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16};

static void test_valid_vectors(void)
{
    CHECK(TAG_VECTOR_COUNT >= 3);
    for (size_t i = 0; i < TAG_VECTOR_COUNT; i++) {
        const tag_vector_t *v = &tag_vectors[i];
        int before = check_failures;

        atalaia_tag_t got;
        memset(&got, 0, sizeof(got));
        CHECK(atalaia_tag_decode(v->payload, v->payload_len, TAG_VECTOR_GAME_ID, tag_game_key,
                                 TAG_VECTOR_TEAM_COUNT, &got) == ATALAIA_TAG_OK);
        CHECK(strcmp(got.player, v->fields.player) == 0);
        CHECK(got.team == v->fields.team && got.game_id == v->fields.game_id);

        uint8_t buf[ATALAIA_TAG_MAX];
        CHECK(atalaia_tag_encode(&v->fields, tag_game_key, buf, sizeof(buf)) == v->payload_len);
        CHECK(memcmp(buf, v->payload, v->payload_len) == 0);
        /* One byte short of room: nothing is written. */
        CHECK(atalaia_tag_encode(&v->fields, tag_game_key, buf, v->payload_len - 1) == 0);

        /* Another game's key: the signature does not match. */
        CHECK(atalaia_tag_decode(v->payload, v->payload_len, TAG_VECTOR_GAME_ID, other_key,
                                 TAG_VECTOR_TEAM_COUNT, &got) == ATALAIA_TAG_ERR_MAC);

        /* Type 2 tag memory both ways. */
        uint8_t mem[128];
        size_t n = atalaia_tag_to_ndef_tag(v->payload, v->payload_len, mem, sizeof(mem));
        CHECK(n == v->ndef_tag_len && memcmp(mem, v->ndef_tag, n) == 0);
        const uint8_t *found = NULL;
        CHECK(atalaia_tag_from_ndef_tag(v->ndef_tag, v->ndef_tag_len, &found) == v->payload_len);
        CHECK(found != NULL && memcmp(found, v->payload, v->payload_len) == 0);

        if (check_failures != before) fprintf(stderr, "  in tag vector %s\n", v->name);
    }
}

static void test_invalid_vectors(void)
{
    CHECK(TAG_BAD_VECTOR_COUNT >= 9);
    for (size_t i = 0; i < TAG_BAD_VECTOR_COUNT; i++) {
        const tag_bad_vector_t *v = &tag_bad_vectors[i];
        atalaia_tag_t got;
        memset(&got, 0xA5, sizeof(got));
        atalaia_tag_result_t r = atalaia_tag_decode(v->payload, v->payload_len, TAG_VECTOR_GAME_ID,
                                                    tag_game_key, TAG_VECTOR_TEAM_COUNT, &got);
        if (r != v->result) {
            fprintf(stderr, "FAIL tag bad vector %s (%s): got %s\n", v->name, v->why,
                    atalaia_tag_result_name(r));
            check_failures++;
        }
        CHECK(got.game_id == 0xA5A5); /* nothing is written on failure */
    }
}

static void test_event_vectors(void)
{
    CHECK(TAG_EVENT_VECTOR_COUNT >= 5);
    for (size_t i = 0; i < TAG_EVENT_VECTOR_COUNT; i++) {
        const tag_event_vector_t *v = &tag_event_vectors[i];
        char json[ATALAIA_TAG_JSON_MAX];
        size_t n =
            atalaia_tag_event_json(tag_uid, tag_uid_len, v->payload, v->payload_len,
                                   TAG_VECTOR_GAME_ID, v->game_key ? tag_game_key : NULL,
                                   tag_vector_teams, TAG_VECTOR_TEAM_COUNT, json, sizeof(json));
        if (n != strlen(v->json) || strcmp(json, v->json) != 0) {
            fprintf(stderr, "FAIL tag event vector %s: got %s\n", v->name, json);
            check_failures++;
        }
    }
}

static void test_edges(void)
{
    CHECK(atalaia_tag_player_ok("p-17"));
    CHECK(atalaia_tag_player_ok("a"));
    CHECK(!atalaia_tag_player_ok(""));
    CHECK(!atalaia_tag_player_ok(NULL));
    CHECK(!atalaia_tag_player_ok("p 17"));
    CHECK(!atalaia_tag_player_ok("p\"17"));
    CHECK(atalaia_tag_player_ok("abcdefghijklmnopqrstuvwxyz012345"));   /* 32 */
    CHECK(!atalaia_tag_player_ok("abcdefghijklmnopqrstuvwxyz0123456")); /* 33 */

    atalaia_tag_t t = {"p 17", 1, 1};
    uint8_t buf[ATALAIA_TAG_MAX];
    CHECK(atalaia_tag_encode(&t, tag_game_key, buf, sizeof(buf)) == 0);
    CHECK(atalaia_tag_decode(NULL, 0, 1, tag_game_key, 2, NULL) == ATALAIA_TAG_ERR_FORMAT);
    CHECK(strcmp(atalaia_tag_result_name(ATALAIA_TAG_ERR_TEAM), "team") == 0);

    /* A team name that needs escaping, and a JSON buffer that is too small. */
    const char *teams[] = {"r\"ed", "blue"};
    char json[ATALAIA_TAG_JSON_MAX];
    size_t n = atalaia_tag_event_json(tag_uid, tag_uid_len, tag_vectors[0].payload,
                                      tag_vectors[0].payload_len, TAG_VECTOR_GAME_ID, tag_game_key,
                                      teams, 2, json, sizeof(json));
    CHECK(n > 0 && strstr(json, "\"team\":\"r\\\"ed\"") != NULL);
    CHECK(atalaia_tag_event_json(tag_uid, tag_uid_len, tag_vectors[0].payload,
                                 tag_vectors[0].payload_len, TAG_VECTOR_GAME_ID, tag_game_key,
                                 teams, 2, json, 20) == 0);
    CHECK(json[0] == '\0');

    /* A tag beside other records: the Atalaia record is found by its type. */
    uint8_t mem[] = {0x03, 0x0D, 0x91, 0x01, 0x04, 'T',  0x02, 'e',
                     'n',  'h',  'i',  0x52, 0x01, 0x00, 'x',  0xFE};
    const uint8_t *found = NULL;
    CHECK(atalaia_tag_from_ndef_tag(mem, sizeof(mem), &found) == 0);
}

void run_tag_tests(void)
{
    test_valid_vectors();
    test_invalid_vectors();
    test_event_vectors();
    test_edges();
}
