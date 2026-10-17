/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Tests for the packet header codec, nonce/AAD construction and
 * encrypt/decrypt round-trip with the test stub crypto backend.
 */
#include <stdio.h>
#include <string.h>

#include "atalaia/packet.h"
#include "atalaia/protocol.h"
#include "check.h"
#include "packet_vectors.h"

static void test_vf_macros(void)
{
    uint8_t vf = ATALAIA_VF_MAKE(1, 2, 1, 1);
    CHECK(ATALAIA_VF_VERSION(vf) == 1);
    CHECK(ATALAIA_VF_PRIO(vf) == 2);
    CHECK(ATALAIA_VF_ACK(vf) == 1);
    CHECK(ATALAIA_VF_ENC(vf) == 1);

    vf = ATALAIA_VF_MAKE(1, 0, 0, 0);
    CHECK(ATALAIA_VF_VERSION(vf) == 1);
    CHECK(ATALAIA_VF_PRIO(vf) == 0);
    CHECK(ATALAIA_VF_ACK(vf) == 0);
    CHECK(ATALAIA_VF_ENC(vf) == 0);

    vf = ATALAIA_VF_MAKE(1, 3, 1, 0);
    CHECK(ATALAIA_VF_PRIO(vf) == 3);
    CHECK(ATALAIA_VF_ACK(vf) == 1);
    CHECK(ATALAIA_VF_ENC(vf) == 0);
}

static void test_header_round_trip(void)
{
    atalaia_header_t hdr = {.version_flags = ATALAIA_VF_MAKE(1, 2, 1, 1),
                            .game_id = 0x1234,
                            .source = 0xABCD,
                            .seq = 0x5678,
                            .hop_limit = 3,
                            .type = 4};
    uint8_t buf[ATALAIA_RF_HEADER_SIZE];
    atalaia_header_encode(&hdr, buf);

    atalaia_header_t out;
    CHECK(atalaia_header_decode(buf, &out));
    CHECK(out.version_flags == hdr.version_flags);
    CHECK(out.game_id == hdr.game_id);
    CHECK(out.source == hdr.source);
    CHECK(out.seq == hdr.seq);
    CHECK(out.hop_limit == hdr.hop_limit);
    CHECK(out.type == hdr.type);
}

static void test_header_big_endian(void)
{
    atalaia_header_t hdr = {.version_flags = ATALAIA_VF_MAKE(1, 0, 0, 0),
                            .game_id = 0x0102,
                            .source = 0x0304,
                            .seq = 0x0506,
                            .hop_limit = 2,
                            .type = 1};
    uint8_t buf[ATALAIA_RF_HEADER_SIZE];
    atalaia_header_encode(&hdr, buf);

    /* game_id at bytes 1-2 in big-endian */
    CHECK(buf[1] == 0x01 && buf[2] == 0x02);
    /* source at bytes 3-4 */
    CHECK(buf[3] == 0x03 && buf[4] == 0x04);
    /* seq at bytes 5-6 */
    CHECK(buf[5] == 0x05 && buf[6] == 0x06);
}

static void test_header_reject_bad_version(void)
{
    uint8_t buf[ATALAIA_RF_HEADER_SIZE] = {0};
    buf[0] = ATALAIA_VF_MAKE(0, 0, 0, 0); /* version 0 */
    atalaia_header_t hdr;
    CHECK(!atalaia_header_decode(buf, &hdr));

    buf[0] = ATALAIA_VF_MAKE(2, 0, 0, 0); /* version 2 */
    CHECK(!atalaia_header_decode(buf, &hdr));
}

static void test_nonce_construction(void)
{
    atalaia_header_t hdr = {.version_flags = ATALAIA_VF_MAKE(1, 0, 0, 1),
                            .game_id = 0x0A0B,
                            .source = 0x0C0D,
                            .seq = 0x1234,
                            .hop_limit = 2,
                            .type = 2};
    uint16_t epoch = 0x0005;
    uint8_t nonce[ATALAIA_RF_NONCE_SIZE];
    atalaia_nonce_build(&hdr, epoch, nonce);

    /* bytes 0-1: game_id BE */
    CHECK(nonce[0] == 0x0A && nonce[1] == 0x0B);
    /* bytes 2-3: source BE */
    CHECK(nonce[2] == 0x0C && nonce[3] == 0x0D);
    /* bytes 4-7: (epoch << 16) | seq = 0x00051234 BE */
    CHECK(nonce[4] == 0x00 && nonce[5] == 0x05);
    CHECK(nonce[6] == 0x12 && nonce[7] == 0x34);
    /* bytes 8-12: zeros */
    for (int i = 8; i < ATALAIA_RF_NONCE_SIZE; i++) {
        CHECK(nonce[i] == 0);
    }
}

static void test_aad_extraction(void)
{
    atalaia_header_t hdr = {.version_flags = ATALAIA_VF_MAKE(1, 1, 0, 1),
                            .game_id = 0xAAAA,
                            .source = 0xBBBB,
                            .seq = 0xCCCC,
                            .hop_limit = 5, /* skipped in AAD */
                            .type = 3};
    uint8_t hdr_buf[ATALAIA_RF_HEADER_SIZE];
    atalaia_header_encode(&hdr, hdr_buf);

    uint8_t aad[ATALAIA_RF_AAD_SIZE];
    atalaia_aad_extract(hdr_buf, aad);

    /* AAD = bytes 0-6 + byte 8 (skip byte 7 = hop_limit) */
    for (int i = 0; i < 7; i++) {
        CHECK(aad[i] == hdr_buf[i]);
    }
    CHECK(aad[7] == hdr_buf[8]); /* type */
}

static void test_encrypt_decrypt_round_trip(void)
{
    atalaia_header_t hdr = {.version_flags = ATALAIA_VF_MAKE(1, 1, 1, 1),
                            .game_id = 42,
                            .source = 7,
                            .seq = 100,
                            .hop_limit = 2,
                            .type = 2};
    uint8_t key[ATALAIA_RF_KEY_SIZE] = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16};
    uint16_t epoch = 1;
    uint8_t payload[] = "Hello, Skirmesh!";
    size_t payload_len = sizeof(payload) - 1;

    uint8_t pkt[256];
    size_t pkt_len = atalaia_packet_encrypt(&hdr, epoch, key, payload, payload_len, pkt,
                                            sizeof(pkt), &atalaia_crypto_test_stub);
    CHECK(pkt_len == ATALAIA_RF_HEADER_SIZE + payload_len + ATALAIA_RF_MIC_SIZE);

    /* Decrypt. */
    atalaia_header_t out_hdr;
    uint8_t out_payload[256];
    size_t out_len = 0;
    CHECK(atalaia_packet_decrypt(pkt, pkt_len, epoch, key, &out_hdr, out_payload, &out_len,
                                 &atalaia_crypto_test_stub));
    CHECK(out_len == payload_len);
    CHECK(memcmp(out_payload, payload, payload_len) == 0);
    CHECK(out_hdr.game_id == hdr.game_id);
    CHECK(out_hdr.source == hdr.source);
    CHECK(out_hdr.seq == hdr.seq);
}

static void test_tampered_packet_fails(void)
{
    atalaia_header_t hdr = {.version_flags = ATALAIA_VF_MAKE(1, 0, 0, 1),
                            .game_id = 1,
                            .source = 1,
                            .seq = 1,
                            .hop_limit = 2,
                            .type = 1};
    uint8_t key[ATALAIA_RF_KEY_SIZE] = {0};
    uint8_t payload[] = {0xAA, 0xBB, 0xCC};

    uint8_t pkt[256];
    size_t pkt_len = atalaia_packet_encrypt(&hdr, 0, key, payload, 3, pkt, sizeof(pkt),
                                            &atalaia_crypto_test_stub);
    CHECK(pkt_len > 0);

    /* Flip a ciphertext bit. */
    pkt[ATALAIA_RF_HEADER_SIZE] ^= 0x01;

    atalaia_header_t out_hdr;
    uint8_t out_payload[256];
    size_t out_len = 0;
    CHECK(!atalaia_packet_decrypt(pkt, pkt_len, 0, key, &out_hdr, out_payload, &out_len,
                                  &atalaia_crypto_test_stub));
}

static void test_wrong_key_fails(void)
{
    atalaia_header_t hdr = {.version_flags = ATALAIA_VF_MAKE(1, 0, 0, 1),
                            .game_id = 1,
                            .source = 1,
                            .seq = 1,
                            .hop_limit = 2,
                            .type = 1};
    uint8_t key1[ATALAIA_RF_KEY_SIZE] = {1};
    uint8_t key2[ATALAIA_RF_KEY_SIZE] = {2};
    uint8_t payload[] = {0xDE, 0xAD};

    uint8_t pkt[256];
    size_t pkt_len = atalaia_packet_encrypt(&hdr, 0, key1, payload, 2, pkt, sizeof(pkt),
                                            &atalaia_crypto_test_stub);
    CHECK(pkt_len > 0);

    atalaia_header_t out_hdr;
    uint8_t out_payload[256];
    size_t out_len = 0;
    CHECK(!atalaia_packet_decrypt(pkt, pkt_len, 0, key2, &out_hdr, out_payload, &out_len,
                                  &atalaia_crypto_test_stub));
}

static void test_empty_payload(void)
{
    atalaia_header_t hdr = {.version_flags = ATALAIA_VF_MAKE(1, 0, 0, 1),
                            .game_id = 99,
                            .source = 1,
                            .seq = 0,
                            .hop_limit = 1,
                            .type = 6};
    uint8_t key[ATALAIA_RF_KEY_SIZE] = {0};

    uint8_t pkt[256];
    size_t pkt_len =
        atalaia_packet_encrypt(&hdr, 0, key, NULL, 0, pkt, sizeof(pkt), &atalaia_crypto_test_stub);
    CHECK(pkt_len == ATALAIA_RF_HEADER_SIZE + ATALAIA_RF_MIC_SIZE);

    atalaia_header_t out_hdr;
    uint8_t out_payload[256];
    size_t out_len = 99;
    CHECK(atalaia_packet_decrypt(pkt, pkt_len, 0, key, &out_hdr, out_payload, &out_len,
                                 &atalaia_crypto_test_stub));
    CHECK(out_len == 0);
}

/* Small deterministic generator. */
static uint32_t pkt_next_rand(uint32_t *state)
{
    *state = *state * 1664525u + 1013904223u;
    return *state >> 8;
}

/*
 * Mutated headers and packets never crash the decoder (CI runs this
 * under ASan/UBSan). Accepted packets re-encode identically.
 */
static void test_header_mutations(void)
{
    atalaia_header_t valid = {
        .version_flags = ATALAIA_VF_MAKE(1, 1, 1, 1),
        .game_id = 0x1234,
        .source = 42,
        .seq = 100,
        .hop_limit = 2,
        .type = ATALAIA_MSG_EVENT,
    };
    uint8_t base[ATALAIA_RF_HEADER_SIZE];
    atalaia_header_encode(&valid, base);

    uint32_t state = 99999;
    size_t accepted = 0;

    for (size_t round = 0; round < 2000; round++) {
        uint8_t m[ATALAIA_RF_HEADER_SIZE];
        memcpy(m, base, ATALAIA_RF_HEADER_SIZE);
        int edits = 1 + (int)(pkt_next_rand(&state) % 3);
        for (int e = 0; e < edits; e++) {
            size_t at = pkt_next_rand(&state) % ATALAIA_RF_HEADER_SIZE;
            m[at] = (uint8_t)pkt_next_rand(&state);
        }
        atalaia_header_t out;
        if (atalaia_header_decode(m, &out)) {
            accepted++;
            /* Re-encode and verify identical. */
            uint8_t re[ATALAIA_RF_HEADER_SIZE];
            atalaia_header_encode(&out, re);
            CHECK(memcmp(m, re, ATALAIA_RF_HEADER_SIZE) == 0);
        }
    }
    CHECK(accepted > 0);
}

/*
 * Mutated encrypted packets never crash the decrypt path.
 */
static void test_packet_mutations(void)
{
    uint8_t key[ATALAIA_RF_KEY_SIZE] = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16};
    atalaia_header_t hdr = {
        .version_flags = ATALAIA_VF_MAKE(1, 1, 0, 1),
        .game_id = 7,
        .source = 3,
        .seq = 50,
        .hop_limit = 2,
        .type = ATALAIA_MSG_EVENT,
    };
    uint8_t payload[] = {0xA1, 0x01, 0x03}; /* small CBOR map */
    uint8_t pkt[256];
    size_t pkt_len = atalaia_packet_encrypt(&hdr, 0, key, payload, sizeof(payload), pkt,
                                            sizeof(pkt), &atalaia_crypto_test_stub);
    CHECK(pkt_len > 0);

    uint32_t state = 77777;

    for (size_t round = 0; round < 2000; round++) {
        uint8_t m[256];
        size_t len = pkt_len;
        memcpy(m, pkt, len);
        int edits = 1 + (int)(pkt_next_rand(&state) % 3);
        for (int e = 0; e < edits; e++) {
            size_t at = pkt_next_rand(&state) % len;
            switch (pkt_next_rand(&state) % 3) {
            case 0: m[at] = (uint8_t)pkt_next_rand(&state); break;
            case 1: m[at] ^= (uint8_t)(1u << (pkt_next_rand(&state) % 8)); break;
            default:
                len = at > (ATALAIA_RF_HEADER_SIZE + ATALAIA_RF_MIC_SIZE)
                          ? at
                          : ATALAIA_RF_HEADER_SIZE + ATALAIA_RF_MIC_SIZE;
                break;
            }
        }
        atalaia_header_t out_hdr;
        uint8_t out_payload[256];
        size_t out_len = sizeof(out_payload);
        /* Must not crash; the result doesn't matter. */
        atalaia_packet_decrypt(m, len, 0, key, &out_hdr, out_payload, &out_len,
                               &atalaia_crypto_test_stub);
    }
}

/* ---- shared vector tests -------------------------------------------------- */

static void test_header_vectors(void)
{
    size_t count = sizeof(header_vectors) / sizeof(header_vectors[0]);
    for (size_t i = 0; i < count; i++) {
        const header_vector_t *v = &header_vectors[i];

        /* Decode the vector bytes and compare fields. */
        atalaia_header_t hdr;
        CHECK(atalaia_header_decode(v->bytes, &hdr));
        CHECK(hdr.version_flags == v->version_flags);
        CHECK(hdr.game_id == v->game_id);
        CHECK(hdr.source == v->source);
        CHECK(hdr.seq == v->seq);
        CHECK(hdr.hop_limit == v->hop_limit);
        CHECK(hdr.type == v->type);

        /* Re-encode and compare to the vector bytes. */
        uint8_t buf[ATALAIA_RF_HEADER_SIZE];
        atalaia_header_encode(&hdr, buf);
        CHECK(memcmp(buf, v->bytes, ATALAIA_RF_HEADER_SIZE) == 0);
    }
}

static void test_header_bad_vectors(void)
{
    /* Invalid vectors must not crash.  Vectors that the decoder can
     * actually detect (e.g. wrong version) are rejected; others may
     * still decode -- the point is exercising the path safely. */
    size_t count = sizeof(header_bad_vectors) / sizeof(header_bad_vectors[0]);
    for (size_t i = 0; i < count; i++) {
        const header_bad_vector_t *v = &header_bad_vectors[i];
        atalaia_header_t hdr;
        (void)atalaia_header_decode(v->bytes, &hdr);
    }
}

void run_packet_tests(void)
{
    test_vf_macros();
    test_header_round_trip();
    test_header_big_endian();
    test_header_reject_bad_version();
    test_nonce_construction();
    test_aad_extraction();
    test_encrypt_decrypt_round_trip();
    test_tampered_packet_fails();
    test_wrong_key_fails();
    test_empty_payload();
    test_header_mutations();
    test_packet_mutations();
    test_header_vectors();
    test_header_bad_vectors();
}
