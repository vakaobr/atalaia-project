/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Tests for the protocol tables and the event codec. The shared vectors in
 * protocol/vectors/events.yaml are also run by the Python codec.
 */
#include <stdio.h>
#include <string.h>

#include "atalaia/codec.h"
#include "atalaia/protocol.h"
#include "check.h"
#include "protocol_vectors.h"

#define COUNT(a) (sizeof(a) / sizeof((a)[0]))
#define BUF 1024

static bool same_event(const atalaia_event_t *a, const atalaia_event_t *b)
{
    return a->node == b->node && a->seq == b->seq && a->t_ms == b->t_ms &&
           a->team == b->team && a->squad == b->squad && a->prio == b->prio &&
           strcmp(a->type, b->type) == 0;
}

static void test_tables(void)
{
    const atalaia_event_def_t *def = atalaia_event_def("bomb.exploded");
    CHECK(def != NULL && def->id == ATALAIA_EV_BOMB_EXPLODED);
    CHECK(def != NULL && def->prio == ATALAIA_PRIO_CRITICAL);
    CHECK(atalaia_event_def_by_id(ATALAIA_EV_ZONE_CAPTURED) != NULL);
    CHECK(strcmp(atalaia_event_def_by_id(ATALAIA_EV_ZONE_CAPTURED)->name, "zone.captured") == 0);
    CHECK(atalaia_event_def("x.club.thing") == NULL);
    CHECK(atalaia_event_def(NULL) == NULL);
    CHECK(atalaia_event_def_by_id(0) == NULL);

    const atalaia_data_field_def_t *f = atalaia_data_field("team", 4);
    CHECK(f != NULL && f->key == ATALAIA_DATA_TEAM && f->common);
    CHECK(atalaia_data_field("teams", 4) == f); /* only the first len bytes count */
    CHECK(atalaia_data_field("tea", 3) == NULL);
    CHECK(atalaia_data_field_by_key(ATALAIA_DATA_FUSE_S)->type == ATALAIA_FIELD_NUMBER);
    CHECK(atalaia_data_field_by_key(0) == NULL);

    /* Every data field an event lists exists. */
    for (size_t i = 0; i < atalaia_event_def_count; i++) {
        const atalaia_event_def_t *e = &atalaia_event_defs[i];
        for (uint8_t k = 0; k < e->data_count; k++) {
            CHECK(atalaia_data_field_by_key(e->data[k]) != NULL);
        }
    }

    CHECK(strcmp(atalaia_msg_type_name(ATALAIA_MSG_EVENT), "EVENT") == 0);
    CHECK(atalaia_msg_type_name(0) == NULL);
    CHECK(ATALAIA_RF_HEADER_BYTES == 9);
    CHECK(ATALAIA_RF_TYPE_OFFSET + ATALAIA_RF_TYPE_BYTES == ATALAIA_RF_HEADER_BYTES);
}

static void test_vectors(void)
{
    uint8_t buf[BUF];
    char json[BUF];
    const char *error;
    for (size_t i = 0; i < COUNT(protocol_vectors); i++) {
        const protocol_vector_t *v = &protocol_vectors[i];
        size_t n = atalaia_event_encode(&v->event, v->data_json, buf, sizeof(buf), &error);
        if (n != v->cbor_len || memcmp(buf, v->cbor, n) != 0) {
            fprintf(stderr, "vector '%s' encodes differently (%s)\n", v->name,
                    error != NULL ? error : "wrong bytes");
            CHECK(!"encode matches the vector");
        }

        atalaia_event_t ev;
        if (!atalaia_event_decode(v->cbor, v->cbor_len, &ev, json, sizeof(json), &error) ||
            !same_event(&ev, &v->event) || strcmp(json, v->data_json) != 0) {
            fprintf(stderr, "vector '%s' decodes differently (%s): %s\n", v->name,
                    error != NULL ? error : "wrong event", json);
            CHECK(!"decode matches the vector");
        }

        /* Too small a buffer fails cleanly at every size. */
        for (size_t cap = 0; cap < v->cbor_len; cap++) {
            CHECK(atalaia_event_encode(&v->event, v->data_json, buf, cap, NULL) == 0);
        }
        size_t json_len = strlen(v->data_json);
        for (size_t cap = 0; cap <= json_len; cap++) {
            CHECK(!atalaia_event_decode(v->cbor, v->cbor_len, &ev, json, cap, NULL));
        }
        CHECK(atalaia_event_decode(v->cbor, v->cbor_len, &ev, json, json_len + 1, NULL));
    }

    for (size_t i = 0; i < COUNT(protocol_bad_vectors); i++) {
        const protocol_bad_vector_t *v = &protocol_bad_vectors[i];
        atalaia_event_t ev;
        error = NULL;
        if (atalaia_event_decode(v->cbor, v->cbor_len, &ev, json, sizeof(json), &error)) {
            fprintf(stderr, "invalid vector '%s' decodes as %s %s\n", v->name, ev.type, json);
            CHECK(!"invalid vector is rejected");
        }
        CHECK(error != NULL && json[0] == '\0');
    }
    CHECK(!atalaia_event_decode(NULL, 0, NULL, json, sizeof(json), NULL));
    CHECK(!atalaia_event_decode((const uint8_t *)"", 0, NULL, json, sizeof(json), NULL));
}

/* Encodes a zone.captured event with this data; returns the length or 0. */
static size_t encode_data(const char *data, uint8_t *buf, const char **error)
{
    atalaia_event_t ev;
    atalaia_event_init(&ev, 1, 1, 0, "x.test.data", 0, 0, ATALAIA_PRIO_NORMAL);
    return atalaia_event_encode(&ev, data, buf, BUF, error);
}

/* Encodes then decodes data, and checks the result equals expected. */
static void check_round_trip(const char *data, const char *expected)
{
    uint8_t buf[BUF];
    char json[BUF];
    const char *error = NULL;
    size_t n = encode_data(data, buf, &error);
    CHECK(n > 0);
    if (n > 0) {
        CHECK(atalaia_event_decode(buf, n, NULL, json, sizeof(json), &error));
        if (strcmp(json, expected) != 0) {
            fprintf(stderr, "round trip of %s gave %s, expected %s\n", data, json, expected);
            CHECK(!"round trip");
        }
    } else {
        fprintf(stderr, "could not encode %s: %s\n", data, error);
    }
}

/* Writes {"k":[[...0...]]} with this many arrays. */
static void nested(char *out, int arrays)
{
    strcpy(out, "{\"k\":");
    for (int i = 0; i < arrays; i++) strcat(out, "[");
    strcat(out, "0");
    for (int i = 0; i < arrays; i++) strcat(out, "]");
    strcat(out, "}");
}

static void test_json_input(void)
{
    uint8_t buf[BUF];
    const char *error;

    check_round_trip(" { \"a\" : [ 1 , 2 ] , \"b\" : { } } ", "{\"a\":[1,2],\"b\":{}}");
    check_round_trip("{\"s\":\"\\u00e7\\ud83d\\ude00\\/\\u0000\"}",
                     "{\"s\":\"\xc3\xa7\xf0\x9f\x98\x80/\\u0000\"}");
    check_round_trip("{\"n\":-0,\"e\":1E2,\"f\":-1.25e-1,\"g\":1e300,\"h\":1e-7}",
                     "{\"n\":0,\"e\":100.0,\"f\":-0.125,\"g\":1e+300,\"h\":1e-07}");
    check_round_trip("{\"p\":0.0001,\"q\":123456789012345678}",
                     "{\"p\":0.0001,\"q\":123456789012345678}");
    /* An empty object is left out, so it decodes as no data. */
    CHECK(encode_data("{}", buf, NULL) == encode_data(NULL, buf, NULL));

    static const char *const bad[] = {
        "", "[]", "\"x\"", "1", "{", "{\"a\"}", "{\"a\":}", "{\"a\":1,}", "{\"a\":1 \"b\":2}",
        "{a:1}", "{\"a\":1}x", "{\"a\":[1,]}", "{\"a\":tru}", "{\"a\":nul}",
        "{\"a\":01}", "{\"a\":1.}", "{\"a\":-}", "{\"a\":.5}", "{\"a\":1e}", "{\"a\":+1}",
        "{\"a\":1e999}", "{\"a\":9223372036854775808}", "{\"a\":-9223372036854775809}",
        "{\"a\":\"\x01\"}", "{\"a\":\"unterminated}", "{\"a\":\"\\x\"}", "{\"a\":\"\\u12\"}",
        "{\"a\":\"\\ud800\"}", "{\"a\":\"\\udc00\"}", "{\"a\":\"\\ud800\\u0041\"}",
        "{\"a\":\"\xc3\x28\"}", "{\"a\":\"\xed\xa0\x80\"}", "{\"a\":\"\xc3\"}",
        "{\"a\":1,\"a\":2}", "{\"team\":\"a\",\"team\":\"b\"}",
        "{\"a\":{\"b\":1,\"b\":2}}",
    };
    for (size_t i = 0; i < COUNT(bad); i++) {
        error = NULL;
        if (encode_data(bad[i], buf, &error) != 0 || error == NULL) {
            fprintf(stderr, "bad JSON data accepted: %s\n", bad[i]);
            CHECK(!"bad JSON is rejected");
        }
    }

    /* Nesting: 16 levels of data (the object and 15 arrays) are fine, 17 are not. */
    char deep[64];
    nested(deep, ATALAIA_CODEC_MAX_DEPTH - 1);
    CHECK(encode_data(deep, buf, NULL) > 0);
    nested(deep, ATALAIA_CODEC_MAX_DEPTH);
    CHECK(encode_data(deep, buf, &error) == 0);

    /* A data object with too many keys open at once. */
    char many[2048] = "{";
    for (int i = 0; i <= ATALAIA_CODEC_MAX_KEYS; i++) {
        char item[16];
        snprintf(item, sizeof(item), "%s\"%d\":0", i ? "," : "", i);
        strcat(many, item);
    }
    strcat(many, "}");
    CHECK(encode_data(many, buf, &error) == 0);

    /* Bad envelopes. */
    atalaia_event_t ev;
    atalaia_event_init(&ev, 1, 1, 0, "zone.captured", 1, 0, ATALAIA_PRIO_NORMAL);
    ev.type[3] = ' ';
    CHECK(atalaia_event_encode(&ev, NULL, buf, BUF, NULL) == 0);
    atalaia_event_init(&ev, 1, 1, 0, "zone.captured", 1, 0, ATALAIA_PRIO_NORMAL);
    ev.team = 251;
    CHECK(atalaia_event_encode(&ev, NULL, buf, BUF, NULL) == 0);
    ev.team = 1;
    ev.prio = (atalaia_prio_t)3;
    CHECK(atalaia_event_encode(&ev, NULL, buf, BUF, NULL) == 0);
    memset(ev.type, 'a', sizeof(ev.type)); /* no NUL */
    ev.prio = ATALAIA_PRIO_NORMAL;
    CHECK(atalaia_event_encode(&ev, NULL, buf, BUF, NULL) == 0);
    CHECK(atalaia_event_encode(NULL, NULL, buf, BUF, NULL) == 0);
}

/* Small deterministic generator for the mutation test. */
static uint32_t next_rand(uint32_t *state)
{
    *state = *state * 1664525u + 1013904223u;
    return *state >> 8;
}

/*
 * Mutated and random payloads never crash the decoder (CI runs this under
 * AddressSanitizer), and whatever it accepts encodes and decodes again.
 */
static void test_mutations(void)
{
    uint8_t buf[BUF];
    uint8_t again[BUF];
    char json[BUF];
    char json2[BUF];
    uint32_t state = 12345;
    size_t accepted = 0;
    for (size_t i = 0; i < COUNT(protocol_vectors); i++) {
        const protocol_vector_t *v = &protocol_vectors[i];
        for (size_t round = 0; round < 400; round++) {
            size_t len = v->cbor_len;
            memcpy(buf, v->cbor, len);
            int edits = 1 + (int)(next_rand(&state) % 3);
            for (int e = 0; e < edits; e++) {
                size_t at = next_rand(&state) % len;
                switch (next_rand(&state) % 4) {
                case 0: buf[at] = (uint8_t)next_rand(&state); break;
                case 1: buf[at] ^= (uint8_t)(1u << (next_rand(&state) % 8)); break;
                case 2: len = at + 1; break; /* truncate */
                default: buf[at] = (uint8_t[]){0x00, 0x17, 0x18, 0x1b, 0x7f, 0x9f, 0xbf, 0xff}
                             [next_rand(&state) % 8]; break;
                }
            }
            atalaia_event_t ev, ev2;
            if (!atalaia_event_decode(buf, len, &ev, json, sizeof(json), NULL)) {
                continue;
            }
            accepted++;
            size_t n = atalaia_event_encode(&ev, json, again, sizeof(again), NULL);
            CHECK(n > 0);
            CHECK(atalaia_event_decode(again, n, &ev2, json2, sizeof(json2), NULL));
            CHECK(same_event(&ev, &ev2) && strcmp(json, json2) == 0);
        }
    }
    for (size_t round = 0; round < 20000; round++) {
        size_t len = 1 + next_rand(&state) % 64;
        for (size_t k = 0; k < len; k++) {
            buf[k] = (uint8_t)next_rand(&state);
        }
        buf[0] = (uint8_t)(0xA0 | (buf[0] & 0x07)); /* mostly small maps */
        atalaia_event_t ev;
        atalaia_event_decode(buf, len, &ev, json, sizeof(json), NULL);
    }
    CHECK(accepted > 0); /* some mutations still decode, so the check above ran */
}

void run_codec_tests(void)
{
    test_tables();
    test_vectors();
    test_json_input();
    test_mutations();
}
