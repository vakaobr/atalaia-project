/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Join payload codec against the shared vectors (protocol/vectors/join.json,
 * also checked by simulator/tests/test_join.py), and HMAC-SHA256 against
 * RFC 4231. Every vector is checked; none is skipped.
 */
#include <stdio.h>
#include <string.h>

#include "atalaia/join.h"
#include "check.h"
#include "packet_vectors.h"

static bool same_join(const atalaia_join_t *a, const atalaia_join_t *b)
{
    if (a->game_id != b->game_id || memcmp(a->game_key, b->game_key, 16) != 0 ||
        a->node_id != b->node_id || a->controller_id != b->controller_id ||
        a->channel_hz != b->channel_hz || a->max_hops != b->max_hops ||
        a->team_count != b->team_count || strcmp(a->mode_id, b->mode_id) != 0 ||
        strcmp(a->role, b->role) != 0 || a->game_seed != b->game_seed ||
        strcmp(a->params_json, b->params_json) != 0 || a->kind != b->kind ||
        a->has_ca != b->has_ca || (a->has_ca && memcmp(a->ca_sha256, b->ca_sha256, 32) != 0) ||
        a->url_count != b->url_count) {
        return false;
    }
    for (uint8_t u = 0; u < a->url_count; u++) {
        if (strcmp(a->urls[u], b->urls[u]) != 0) return false;
    }
    for (uint8_t t = 0; t < a->team_count; t++) {
        if (strcmp(a->teams[t], b->teams[t]) != 0) return false;
    }
    return true;
}

static void test_hmac_rfc4231(void)
{
    CHECK(HMAC_VECTOR_COUNT == 3);
    for (size_t i = 0; i < HMAC_VECTOR_COUNT; i++) {
        const hmac_vector_t *v = &hmac_vectors[i];
        uint8_t mac[32];
        atalaia_hmac_sha256(v->key, v->key_len, v->data, v->data_len, mac);
        if (memcmp(mac, v->mac, 32) != 0) {
            fprintf(stderr, "FAIL hmac vector %s\n", v->name);
            check_failures++;
        }
    }
    /* FIPS 180-4 example: SHA-256("abc"). */
    static const uint8_t abc[32] = {0xba, 0x78, 0x16, 0xbf, 0x8f, 0x01, 0xcf, 0xea,
                                    0x41, 0x41, 0x40, 0xde, 0x5d, 0xae, 0x22, 0x23,
                                    0xb0, 0x03, 0x61, 0xa3, 0x96, 0x17, 0x7a, 0x9c,
                                    0xb4, 0x10, 0xff, 0x61, 0xf2, 0x00, 0x15, 0xad};
    uint8_t h[32];
    atalaia_sha256((const uint8_t *)"abc", 3, h);
    CHECK(memcmp(h, abc, 32) == 0);

    /* The streaming form gives the same digest however the input is cut (a firmware image
     * arrives in chunks): FIPS 180-4's two-block example, and "abc" one byte at a time. */
    static const char two[] = "abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq";
    static const uint8_t two_h[32] = {0x24, 0x8d, 0x6a, 0x61, 0xd2, 0x06, 0x38, 0xb8,
                                      0xe5, 0xc0, 0x26, 0x93, 0x0c, 0x3e, 0x60, 0x39,
                                      0xa3, 0x3c, 0xe4, 0x59, 0x64, 0xff, 0x21, 0x67,
                                      0xf6, 0xec, 0xed, 0xd4, 0x19, 0xdb, 0x06, 0xc1};
    for (size_t step = 1; step <= 64; step++) {
        atalaia_sha256_t s;
        atalaia_sha256_init(&s);
        for (size_t o = 0; o < sizeof(two) - 1; o += step) {
            size_t n = sizeof(two) - 1 - o < step ? sizeof(two) - 1 - o : step;
            atalaia_sha256_update(&s, (const uint8_t *)two + o, n);
        }
        atalaia_sha256_final(&s, h);
        CHECK(memcmp(h, two_h, 32) == 0);
    }
    atalaia_sha256_t s;
    atalaia_sha256_init(&s);
    for (int i = 0; i < 3; i++) atalaia_sha256_update(&s, (const uint8_t *)"abc" + i, 1);
    atalaia_sha256_update(&s, NULL, 0);
    atalaia_sha256_final(&s, h);
    CHECK(memcmp(h, abc, 32) == 0);
}

static void test_valid_vectors(void)
{
    CHECK(JOIN_VECTOR_COUNT >= 4);
    for (size_t i = 0; i < JOIN_VECTOR_COUNT; i++) {
        const join_vector_t *v = &join_vectors[i];
        int before = check_failures;

        atalaia_join_t got;
        CHECK(atalaia_join_decode(v->payload, v->payload_len, join_key, &got) == ATALAIA_JOIN_OK);
        CHECK(same_join(&got, &v->fields));

        /* Re-encodes byte for byte, from the decoded and from the expected fields. */
        uint8_t buf[ATALAIA_JOIN_MAX];
        size_t n = atalaia_join_encode(&got, join_key, buf, sizeof(buf));
        CHECK(n == v->payload_len && memcmp(buf, v->payload, n) == 0);
        n = atalaia_join_encode(&v->fields, join_key, buf, sizeof(buf));
        CHECK(n == v->payload_len && memcmp(buf, v->payload, n) == 0);

        /* Another field's key: the tag does not match. */
        CHECK(atalaia_join_decode(v->payload, v->payload_len, join_wrong_key, &got) ==
              ATALAIA_JOIN_ERR_MAC);

        /* Text form both ways. */
        char text[ATALAIA_JOIN_MAX * 2];
        CHECK(atalaia_join_to_text(v->payload, v->payload_len, text, sizeof(text)) ==
              strlen(v->text));
        CHECK(strcmp(text, v->text) == 0);
        uint8_t back[ATALAIA_JOIN_MAX];
        CHECK(atalaia_join_from_text(v->text, back, sizeof(back)) == v->payload_len);
        CHECK(memcmp(back, v->payload, v->payload_len) == 0);

        /* NFC tag memory both ways. */
        uint8_t tag[ATALAIA_JOIN_MAX + 64];
        n = atalaia_join_to_ndef_tag(v->payload, v->payload_len, tag, sizeof(tag));
        CHECK(n == v->ndef_tag_len && memcmp(tag, v->ndef_tag, n) == 0);
        const uint8_t *found = NULL;
        CHECK(atalaia_join_from_ndef_tag(v->ndef_tag, v->ndef_tag_len, &found) == v->payload_len);
        CHECK(found != NULL && memcmp(found, v->payload, v->payload_len) == 0);

        if (check_failures != before) fprintf(stderr, "  in join vector %s\n", v->name);
    }
}

static void test_invalid_vectors(void)
{
    CHECK(JOIN_BAD_VECTOR_COUNT >= 30);
    for (size_t i = 0; i < JOIN_BAD_VECTOR_COUNT; i++) {
        const join_bad_vector_t *v = &join_bad_vectors[i];
        atalaia_join_t got;
        memset(&got, 0xA5, sizeof(got));
        atalaia_join_result_t r = atalaia_join_decode(v->payload, v->payload_len, join_key, &got);
        if (r != v->result) {
            fprintf(stderr, "FAIL join bad vector %s (%s): got %s\n", v->name, v->why,
                    atalaia_join_result_name(r));
            check_failures++;
        }
        /* Nothing is written on failure. */
        CHECK(got.game_id == 0xA5A5);
    }
}

static void test_optional_key_skipped(void)
{
    atalaia_join_t got;
    CHECK(atalaia_join_decode(join_optional_key_skipped, join_optional_key_skipped_len, join_key,
                              &got) == ATALAIA_JOIN_OK);
    CHECK(same_join(&got, &join_vectors[0].fields));
}

/* Keys 13 (the field CA's SHA-256) and 14 (the controller's addresses): read, kept and
 * written back byte for byte; every malformed one refuses the payload (RFC 0001 Amendment 4). */
static void test_link_vectors(void)
{
    CHECK(JOIN_LINK_VECTOR_COUNT >= 3);
    for (size_t i = 0; i < JOIN_LINK_VECTOR_COUNT; i++) {
        const join_link_vector_t *v = &join_link_vectors[i];
        int before = check_failures;
        atalaia_join_t got;
        CHECK(atalaia_join_decode(v->payload, v->payload_len, join_key, &got) == ATALAIA_JOIN_OK);
        CHECK(same_join(&got, &v->fields));
        uint8_t buf[ATALAIA_JOIN_MAX];
        size_t n = atalaia_join_encode(&v->fields, join_key, buf, sizeof(buf));
        CHECK(n == v->payload_len && memcmp(buf, v->payload, n) == 0);
        uint8_t back[ATALAIA_JOIN_MAX];
        CHECK(atalaia_join_from_text(v->text, back, sizeof(back)) == v->payload_len);
        if (check_failures != before) fprintf(stderr, "  in join link vector %s\n", v->name);
    }
    CHECK(JOIN_LINK_BAD_VECTOR_COUNT >= 8);
    for (size_t i = 0; i < JOIN_LINK_BAD_VECTOR_COUNT; i++) {
        const join_bad_vector_t *v = &join_link_bad_vectors[i];
        atalaia_join_t got;
        if (atalaia_join_decode(v->payload, v->payload_len, join_key, &got) != v->result) {
            fprintf(stderr, "FAIL join link bad vector %s (%s)\n", v->name, v->why);
            check_failures++;
        }
    }
}

static void test_url_rule(void)
{
    CHECK(atalaia_join_url_ok("https://10.42.0.1:8443"));
    CHECK(atalaia_join_url_ok("https://atalaia.local"));
    CHECK(atalaia_join_url_ok("https://[fd00::1]:443"));
    CHECK(atalaia_join_url_ok("https://a:65535"));
    CHECK(!atalaia_join_url_ok("https://a:65536"));
    CHECK(!atalaia_join_url_ok("https://a:0443"));
    CHECK(!atalaia_join_url_ok("https://a:"));
    CHECK(!atalaia_join_url_ok("http://a"));
    CHECK(!atalaia_join_url_ok("https://a/"));
    CHECK(!atalaia_join_url_ok("https://a..b"));
    CHECK(!atalaia_join_url_ok("https://"));
    CHECK(!atalaia_join_url_ok("https://[1]"));
    CHECK(!atalaia_join_url_ok("https://a.example.org:8443:1"));
    char longest[80];
    snprintf(longest, sizeof(longest), "https://%056d", 0);
    CHECK(strlen(longest) == 64 && atalaia_join_url_ok(longest));
    snprintf(longest, sizeof(longest), "https://%057d", 0);
    CHECK(!atalaia_join_url_ok(longest));
}

static void test_text_and_tag_edges(void)
{
    uint8_t buf[ATALAIA_JOIN_MAX];
    CHECK(atalaia_join_from_text("atalaia:join:AQID", buf, sizeof(buf)) == 3);
    CHECK(buf[0] == 1 && buf[1] == 2 && buf[2] == 3);
    CHECK(atalaia_join_from_text("  atalaia:join:AQID\r\n", buf, sizeof(buf)) == 3);
    CHECK(atalaia_join_from_text("atalaia:join:AQI", buf, sizeof(buf)) == 2);
    CHECK(atalaia_join_from_text("atalaia:join:AQJ", buf, sizeof(buf)) == 0); /* bits left over */
    CHECK(atalaia_join_from_text("atalaia:join:A", buf, sizeof(buf)) == 0);
    CHECK(atalaia_join_from_text("atalaia:join:AQ+D", buf, sizeof(buf)) == 0); /* not base64url */
    CHECK(atalaia_join_from_text("atalaia:jo1n:AQID", buf, sizeof(buf)) == 0);
    CHECK(atalaia_join_from_text("atalaia:join:AQID", buf, 2) == 0); /* does not fit */
    char text[8];
    CHECK(atalaia_join_to_text(buf, 3, text, sizeof(text)) == 0); /* does not fit */

    /* A lock control TLV and NULL TLVs before the NDEF message are skipped. */
    const join_vector_t *v = &join_vectors[0];
    uint8_t mem[ATALAIA_JOIN_MAX + 64];
    size_t o = 0;
    mem[o++] = 0x01;
    mem[o++] = 0x03;
    mem[o++] = 0xA0;
    mem[o++] = 0x10;
    mem[o++] = 0x44;
    mem[o++] = 0x00;
    memcpy(mem + o, v->ndef_tag, v->ndef_tag_len);
    const uint8_t *found = NULL;
    CHECK(atalaia_join_from_ndef_tag(mem, o + v->ndef_tag_len, &found) == v->payload_len);
    /* Truncated memory, an empty tag and a text record are not a join. */
    CHECK(atalaia_join_from_ndef_tag(v->ndef_tag, v->ndef_tag_len / 2, &found) == 0);
    static const uint8_t empty[] = {0x03, 0x00, 0xFE};
    CHECK(atalaia_join_from_ndef_tag(empty, sizeof(empty), &found) == 0);
    static const uint8_t text_rec[] = {0x03, 0x08, 0xD1, 0x01, 0x04, 'T',
                                       0x02, 'e',  'n',  'x',  0xFE};
    CHECK(atalaia_join_from_ndef_tag(text_rec, sizeof(text_rec), &found) == 0);
}

static void test_encode_refuses_bad_fields(void)
{
    atalaia_join_t j = join_vectors[0].fields;
    uint8_t buf[ATALAIA_JOIN_MAX];
    j.max_hops = 4;
    CHECK(atalaia_join_encode(&j, join_key, buf, sizeof(buf)) == 0);
    j = join_vectors[0].fields;
    j.channel_hz = 915000000u;
    CHECK(atalaia_join_encode(&j, join_key, buf, sizeof(buf)) == 0);
    j = join_vectors[0].fields;
    CHECK(atalaia_join_encode(&j, join_key, buf, 40) == 0); /* does not fit */
    snprintf(j.params_json, sizeof(j.params_json), "not json");
    CHECK(atalaia_join_encode(&j, join_key, buf, sizeof(buf)) == 0);
}

void run_join_tests(void)
{
    test_hmac_rfc4231();
    test_valid_vectors();
    test_invalid_vectors();
    test_optional_key_skipped();
    test_link_vectors();
    test_url_rule();
    test_text_and_tag_edges();
    test_encode_refuses_bad_fields();
}
