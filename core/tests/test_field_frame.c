/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Field frames (atalaia/field_frame.h) against the shared vectors
 * (protocol/vectors/field_frame.json, also checked by
 * simulator/tests/test_field_frame.py): HKDF-SHA256 against RFC 5869's
 * appendix A, the field key, every body and frame, every refusal, the
 * invite parts. The frames need the real AES-CCM backend (mbedtls); the
 * rest runs everywhere. Every vector is checked; none is skipped.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "atalaia/field_frame.h"
#include "check.h"
#include "field_frame_vectors.h"

static void fail(const char *what, const char *name)
{
    fprintf(stderr, "FAIL field frame %s: %s\n", what, name);
    check_failures++;
}

static void test_hkdf_rfc5869(void)
{
    CHECK(FF_HKDF_VECTOR_COUNT == 3);
    for (size_t i = 0; i < FF_HKDF_VECTOR_COUNT; i++) {
        const ff_hkdf_vector_t *v = &ff_hkdf_vectors[i];
        uint8_t okm[128];
        CHECK(v->okm_len <= sizeof(okm));
        if (!atalaia_hkdf_sha256(v->salt, v->salt_len, v->ikm, v->ikm_len, v->info, v->info_len,
                                 okm, v->okm_len) ||
            memcmp(okm, v->okm, v->okm_len) != 0) {
            fail("hkdf", v->name);
        }
        /* The PRK is HMAC(salt, IKM), no salt being 32 zero bytes (RFC 5869 section 2.2). */
        uint8_t zeros[32] = {0};
        uint8_t prk[32];
        atalaia_hmac_sha256(v->salt_len ? v->salt : zeros, v->salt_len ? v->salt_len : 32, v->ikm,
                            v->ikm_len, prk);
        if (memcmp(prk, v->prk, 32) != 0) fail("hkdf prk", v->name);
    }
    uint8_t big[8161];
    CHECK(!atalaia_hkdf_sha256(NULL, 0, ff_join_key, 32, NULL, 0, big, sizeof(big)));

    uint8_t key[ATALAIA_FF_KEY_SIZE];
    atalaia_ff_key(ff_join_key, key);
    CHECK(memcmp(key, ff_field_key, sizeof(key)) == 0);
}

static bool same_msg(const atalaia_ff_msg_t *a, const atalaia_ff_msg_t *b)
{
    if (a->kind != b->kind) return false;
    if (a->kind == ATALAIA_FF_DISCOVER) return true;
    if (memcmp(a->device_id, b->device_id, 8) != 0 || memcmp(a->token, b->token, 8) != 0) {
        return false;
    }
    if (a->kind == ATALAIA_FF_ANNOUNCE) {
        return strcmp(a->name, b->name) == 0 && a->tier == b->tier &&
               a->last_game == b->last_game && strcmp(a->last_role, b->last_role) == 0 &&
               a->battery_pct == b->battery_pct && a->answer == b->answer && a->result == b->result;
    }
    return a->invite_id == b->invite_id && a->part == b->part && a->parts == b->parts &&
           a->chunk_len == b->chunk_len && memcmp(a->chunk, b->chunk, a->chunk_len) == 0;
}

static void test_bodies(void)
{
    CHECK(FF_VALID_VECTOR_COUNT >= 7);
    for (size_t i = 0; i < FF_VALID_VECTOR_COUNT; i++) {
        const ff_valid_vector_t *v = &ff_valid_vectors[i];
        atalaia_ff_msg_t m;
        if (!atalaia_ff_body_decode(v->body, v->body_len, &m) || !same_msg(&m, &v->fields)) {
            fail("body decode", v->name);
            continue;
        }
        uint8_t buf[ATALAIA_FF_BODY_MAX];
        size_t n = atalaia_ff_body_encode(&v->fields, buf, sizeof(buf));
        if (n != v->body_len || memcmp(buf, v->body, n) != 0) fail("body encode", v->name);
        /* A buffer one byte short is refused, never overrun. */
        CHECK(atalaia_ff_body_encode(&v->fields, buf, v->body_len - 1) == 0);
    }
    for (size_t i = 0; i < FF_BAD_BODY_COUNT; i++) {
        atalaia_ff_msg_t m;
        if (atalaia_ff_body_decode(ff_bad_bodies[i].data, ff_bad_bodies[i].len, &m)) {
            fail("bad body accepted", ff_bad_bodies[i].name);
        }
    }
    /* Keys 11-31 are skipped: the optional-key case reads as the plain announce. */
    atalaia_ff_msg_t m;
    CHECK(atalaia_ff_body_decode(ff_optional_key_skipped, ff_optional_key_skipped_len, &m));
    CHECK(m.kind == ATALAIA_FF_ANNOUNCE && strcmp(m.name, "box") == 0 && m.battery_pct == 0xFF);

    /* The encoder refuses what the decoder would refuse. */
    atalaia_ff_msg_t bad = ff_valid_vectors[1].fields;
    bad.tier = 3;
    uint8_t buf[ATALAIA_FF_BODY_MAX];
    CHECK(atalaia_ff_body_encode(&bad, buf, sizeof(buf)) == 0);
    bad = ff_valid_vectors[1].fields;
    bad.name[0] = '\0';
    CHECK(atalaia_ff_body_encode(&bad, buf, sizeof(buf)) == 0);
    bad = ff_valid_vectors[5].fields;
    bad.part = 1; /* of one */
    CHECK(atalaia_ff_body_encode(&bad, buf, sizeof(buf)) == 0);
    bad.part = 0;
    bad.invite_id = 0;
    CHECK(atalaia_ff_body_encode(&bad, buf, sizeof(buf)) == 0);
    bad.kind = 9;
    CHECK(atalaia_ff_body_encode(&bad, buf, sizeof(buf)) == 0);
}

static void test_frame_shape(void)
{
    for (size_t i = 0; i < FF_VALID_VECTOR_COUNT; i++) {
        CHECK(atalaia_ff_is_frame(ff_valid_vectors[i].frame, ff_valid_vectors[i].frame_len));
    }
    for (size_t i = 0; i < FF_BAD_FRAME_COUNT; i++) {
        const ff_bad_vector_t *v = &ff_bad_frames[i];
        bool shape = atalaia_ff_is_frame(v->data, v->len);
        if (shape != (strcmp(v->reason, "mac") == 0)) fail("frame shape", v->name);
    }
    CHECK(!atalaia_ff_is_frame(NULL, 0));
    CHECK(ATALAIA_FF_MAX == 217 && ATALAIA_FF_BODY_MAX == 187);
}

#ifdef ATALAIA_HAVE_MBEDTLS
static void test_frames(void)
{
    const atalaia_crypto_ops_t *c = &atalaia_crypto_mbedtls;
    for (size_t i = 0; i < FF_VALID_VECTOR_COUNT; i++) {
        const ff_valid_vector_t *v = &ff_valid_vectors[i];
        uint8_t frame[ATALAIA_FF_MAX];
        size_t n =
            atalaia_ff_seal(ff_field_key, v->nonce, v->body, v->body_len, frame, sizeof(frame), c);
        if (n != v->frame_len || memcmp(frame, v->frame, n) != 0) fail("seal", v->name);
        uint8_t body[ATALAIA_FF_BODY_MAX];
        size_t b = atalaia_ff_open(ff_field_key, v->frame, v->frame_len, body, sizeof(body), c);
        if (b != v->body_len || memcmp(body, v->body, b) != 0) fail("open", v->name);
        /* Too small a body buffer: refused. */
        CHECK(atalaia_ff_open(ff_field_key, v->frame, v->frame_len, body, v->body_len - 1, c) == 0);
    }
    /* hop_limit is outside the AAD, as for game packets. */
    uint8_t body[ATALAIA_FF_BODY_MAX];
    size_t b = atalaia_ff_open(ff_field_key, ff_hop_limit_ignored, ff_hop_limit_ignored_len, body,
                               sizeof(body), c);
    CHECK(b == ff_valid_vectors[1].body_len && memcmp(body, ff_valid_vectors[1].body, b) == 0);
    for (size_t i = 0; i < FF_BAD_FRAME_COUNT; i++) {
        const ff_bad_vector_t *v = &ff_bad_frames[i];
        if (atalaia_ff_open(ff_field_key, v->data, v->len, body, sizeof(body), c) != 0) {
            fail("bad frame opened", v->name);
        }
    }
    /* Seal refuses an empty or oversized body, or a frame buffer too small. */
    uint8_t frame[ATALAIA_FF_MAX + 1];
    static const uint8_t nonce[13] = {0};
    uint8_t big[ATALAIA_FF_BODY_MAX + 1] = {0};
    CHECK(atalaia_ff_seal(ff_field_key, nonce, big, 0, frame, sizeof(frame), c) == 0);
    CHECK(atalaia_ff_seal(ff_field_key, nonce, big, sizeof(big), frame, sizeof(frame), c) == 0);
    CHECK(atalaia_ff_seal(ff_field_key, nonce, big, 10, frame, 39, c) == 0);
    CHECK(atalaia_ff_seal(ff_field_key, nonce, big, 10, frame, 40, c) == 40);
}
#endif

static void test_parts(void)
{
    for (size_t i = 0; i < FF_SPLIT_VECTOR_COUNT; i++) {
        const ff_split_vector_t *v = &ff_split_vectors[i];
        CHECK(atalaia_ff_parts_for(v->payload_len) == v->parts);
        atalaia_ff_reasm_t r;
        atalaia_ff_reasm_reset(&r);
        uint8_t out[ATALAIA_JOIN_MAX];
        int got = 0;
        /* Last part first: the order of arrival does not matter. */
        for (size_t k = v->parts; k-- > 0;) {
            atalaia_ff_msg_t m = {.kind = ATALAIA_FF_INVITE,
                                  .invite_id = 77,
                                  .part = (uint8_t)k,
                                  .parts = (uint8_t)v->parts,
                                  .chunk_len = (uint8_t)v->part_len[k]};
            memcpy(m.chunk, v->part[k], v->part_len[k]);
            got = atalaia_ff_reasm_add(&r, &m, out, sizeof(out));
            if (k > 0) CHECK(got == 0);
        }
        if (got != (int)v->payload_len || memcmp(out, v->payload, v->payload_len) != 0) {
            fail("reassembly", v->name);
        }
    }
    CHECK(atalaia_ff_parts_for(0) == 0 && atalaia_ff_parts_for(449) == 0);
    CHECK(atalaia_ff_parts_for(153) == 1 && atalaia_ff_parts_for(154) == 2);
    CHECK(atalaia_ff_parts_for(448) == 3);

    /* A part of another invite (or token) starts over; a part sent twice counts once. */
    atalaia_ff_reasm_t r;
    atalaia_ff_reasm_reset(&r);
    uint8_t out[ATALAIA_JOIN_MAX];
    atalaia_ff_msg_t a = {.kind = ATALAIA_FF_INVITE,
                          .invite_id = 1,
                          .part = 0,
                          .parts = 2,
                          .chunk_len = 2,
                          .chunk = {1, 2}};
    atalaia_ff_msg_t b = a;
    b.part = 1;
    b.chunk[0] = 3;
    CHECK(atalaia_ff_reasm_add(&r, &a, out, sizeof(out)) == 0);
    CHECK(atalaia_ff_reasm_add(&r, &a, out, sizeof(out)) == 0);
    atalaia_ff_msg_t other = b;
    other.invite_id = 2;
    CHECK(atalaia_ff_reasm_add(&r, &other, out, sizeof(out)) == 0); /* invite 2 starts over */
    CHECK(atalaia_ff_reasm_add(&r, &a, out, sizeof(out)) == 0);     /* invite 1 again */
    other = b;
    other.token[0] = 0xAA;
    CHECK(atalaia_ff_reasm_add(&r, &other, out, sizeof(out)) == 0); /* another token */
    CHECK(atalaia_ff_reasm_add(&r, &a, out, sizeof(out)) == 0);
    CHECK(atalaia_ff_reasm_add(&r, &b, out, sizeof(out)) == 4);
    CHECK(out[0] == 1 && out[1] == 2 && out[2] == 3 && out[3] == 2);
    /* Too small an output: -1, and the parts are dropped. */
    CHECK(atalaia_ff_reasm_add(&r, &a, out, sizeof(out)) == 0);
    CHECK(atalaia_ff_reasm_add(&r, &b, out, 3) == -1);
    CHECK(!r.used);
    atalaia_ff_msg_t announce = {.kind = ATALAIA_FF_ANNOUNCE};
    CHECK(atalaia_ff_reasm_add(&r, &announce, out, sizeof(out)) == 0);
}

/* The nonce rule (decision RJ-15): no random number in it. */
static void test_nonces(void)
{
    uint8_t nk[32];
    atalaia_ff_nonce_key(ff_join_key, nk);
    CHECK(memcmp(nk, ff_nonce_key, 32) == 0);
    CHECK(FF_NONCE_VECTOR_COUNT == 4);
    for (size_t i = 0; i < FF_NONCE_VECTOR_COUNT; i++) {
        const ff_nonce_vector_t *v = &ff_nonce_vectors[i];
        uint8_t n[ATALAIA_FF_NONCE_SIZE];
        atalaia_ff_nonce(nk, v->sender, v->boot, v->ctr, n);
        if (memcmp(n, v->nonce, sizeof(n)) != 0) fail("nonce", v->name);
    }
    /* A run after a stored count of 41: boot 42 from ctr 0, then boot 43 after ctr 65535. */
    static const struct {
        uint32_t boot;
        uint16_t ctr;
    } seq[4] = {{FF_NONCE_SOURCE_STORED + 1, 0},
                {FF_NONCE_SOURCE_STORED + 1, 1},
                {FF_NONCE_SOURCE_STORED + 1, 0xFFFF},
                {FF_NONCE_SOURCE_AFTER, 0}};
    for (int i = 0; i < 4; i++) {
        uint8_t n[ATALAIA_FF_NONCE_SIZE];
        atalaia_ff_nonce(nk, ff_nonce_source_sender, seq[i].boot, seq[i].ctr, n);
        CHECK(memcmp(n, ff_nonce_source[i], sizeof(n)) == 0);
    }
}

/* A body never makes the decoder read out of bounds (random bytes; ASan run). */
static void test_fuzz(void)
{
    uint32_t state = 0x5eed1234u;
    for (int round = 0; round < 20000; round++) {
        uint8_t b[ATALAIA_FF_BODY_MAX];
        size_t len = 1 + (size_t)(round % 60);
        for (size_t k = 0; k < len; k++) {
            state = state * 1103515245u + 12345u;
            b[k] = (uint8_t)(state >> 16);
        }
        if (round % 3 == 0) {
            /* Start like a valid body so the decoder goes deeper. */
            size_t n = ff_valid_vectors[round % FF_VALID_VECTOR_COUNT].body_len;
            memcpy(b, ff_valid_vectors[round % FF_VALID_VECTOR_COUNT].body, n < len ? n : len);
        }
        atalaia_ff_msg_t m;
        (void)atalaia_ff_body_decode(b, len, &m);
    }
}

void run_field_frame_tests(void)
{
    test_hkdf_rfc5869();
    test_bodies();
    test_frame_shape();
#ifdef ATALAIA_HAVE_MBEDTLS
    test_frames();
#else
    if (getenv("ATALAIA_REQUIRE_ALL") != NULL) {
        fprintf(stderr, "FAIL: ATALAIA_REQUIRE_ALL is set but the field frames need mbedtls\n");
        check_failures++;
    }
#endif
    test_parts();
    test_nonces();
    test_fuzz();
}
