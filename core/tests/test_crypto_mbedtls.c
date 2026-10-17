/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Tests for the real AES-128-CCM crypto backend (mbedtls).
 * Only compiled when ATALAIA_HAVE_MBEDTLS is defined.
 *
 * Known-answer vector: key/nonce/aad/plaintext from RFC 3610 Packet
 * Vector 1 (13-byte nonce, 8-byte tag). Expected ciphertext and tag
 * cross-verified against Python cryptography AESCCM.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "atalaia/packet.h"
#include "check.h"
#include "packet_vectors.h"

#ifdef ATALAIA_HAVE_MBEDTLS

/* --- RFC 3610 test vector 1 ------------------------------------------------
 *
 * Packet Vector #1 of RFC 3610, "Counter with CBC-MAC (CCM)", section 8
 * (https://www.rfc-editor.org/rfc/rfc3610#section-8): AES-128, M = 8 (an
 * 8-byte tag), L = 2 (a 13-byte nonce), 8 bytes of AAD and 23 bytes of
 * plaintext, driven through the atalaia_crypto_ops_t interface. The expected
 * output is copied from the RFC, not computed, so a broken backend fails.
 */

static const uint8_t rfc3610_key[16] = {0xC0, 0xC1, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7,
                                        0xC8, 0xC9, 0xCA, 0xCB, 0xCC, 0xCD, 0xCE, 0xCF};

static const uint8_t rfc3610_nonce[13] = {0x00, 0x00, 0x00, 0x03, 0x02, 0x01, 0x00,
                                          0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5};

/* AAD (header, 8 bytes) */
static const uint8_t rfc3610_aad[8] = {0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07};

/* Plaintext (23 bytes) */
static const uint8_t rfc3610_pt[23] = {0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F,
                                       0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17,
                                       0x18, 0x19, 0x1A, 0x1B, 0x1C, 0x1D, 0x1E};

/* Expected ciphertext (23 bytes) and tag (8 bytes), from the RFC. */
static const uint8_t rfc3610_ct[23] = {0x58, 0x8C, 0x97, 0x9A, 0x61, 0xC6, 0x63, 0xD2,
                                       0xF0, 0x66, 0xD0, 0xC2, 0xC0, 0xF9, 0x89, 0x80,
                                       0x6D, 0x5F, 0x6B, 0x61, 0xDA, 0xC3, 0x84};

static const uint8_t rfc3610_tag[8] = {0x17, 0xE8, 0xD1, 0x2C, 0xFD, 0xF9, 0x26, 0xE0};

static void test_rfc3610_encrypt(void)
{
    uint8_t ct[23];
    uint8_t tag[8];

    int rc = atalaia_crypto_mbedtls.encrypt(atalaia_crypto_mbedtls.ctx, rfc3610_key, rfc3610_nonce,
                                            13, rfc3610_aad, 8, rfc3610_pt, 23, ct, tag, 8);
    CHECK(rc == 0);
    CHECK(memcmp(ct, rfc3610_ct, 23) == 0);
    CHECK(memcmp(tag, rfc3610_tag, 8) == 0);
}

static void test_rfc3610_decrypt(void)
{
    uint8_t pt[23];

    int rc = atalaia_crypto_mbedtls.decrypt(atalaia_crypto_mbedtls.ctx, rfc3610_key, rfc3610_nonce,
                                            13, rfc3610_aad, 8, rfc3610_ct, 23, pt, rfc3610_tag, 8);
    CHECK(rc == 0);
    CHECK(memcmp(pt, rfc3610_pt, 23) == 0);
}

static void test_rfc3610_tampered_fails(void)
{
    uint8_t pt[23];
    uint8_t bad_ct[23];
    memcpy(bad_ct, rfc3610_ct, 23);
    bad_ct[0] ^= 0x01; /* flip one bit */

    int rc = atalaia_crypto_mbedtls.decrypt(atalaia_crypto_mbedtls.ctx, rfc3610_key, rfc3610_nonce,
                                            13, rfc3610_aad, 8, bad_ct, 23, pt, rfc3610_tag, 8);
    CHECK(rc != 0);
}

static void test_rfc3610_wrong_key_fails(void)
{
    uint8_t pt[23];
    uint8_t wrong_key[16] = {0};

    int rc = atalaia_crypto_mbedtls.decrypt(atalaia_crypto_mbedtls.ctx, wrong_key, rfc3610_nonce,
                                            13, rfc3610_aad, 8, rfc3610_ct, 23, pt, rfc3610_tag, 8);
    CHECK(rc != 0);
}

/* --- round-trip through the full packet layer ----------------------------- */

static void test_mbedtls_packet_round_trip(void)
{
    atalaia_header_t hdr = {.version_flags = ATALAIA_VF_MAKE(1, 1, 1, 1),
                            .game_id = 42,
                            .source = 7,
                            .seq = 100,
                            .hop_limit = 2,
                            .type = 2};
    uint8_t key[ATALAIA_RF_KEY_SIZE] = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16};
    uint16_t epoch = 1;
    uint8_t payload[] = "Hello, Atalaia!";
    size_t payload_len = sizeof(payload) - 1;

    uint8_t pkt[256];
    size_t pkt_len = atalaia_packet_encrypt(&hdr, epoch, key, payload, payload_len, pkt,
                                            sizeof(pkt), &atalaia_crypto_mbedtls);
    CHECK(pkt_len == ATALAIA_RF_HEADER_SIZE + payload_len + ATALAIA_RF_MIC_SIZE);

    atalaia_header_t out_hdr;
    uint8_t out_payload[256];
    size_t out_len = 0;
    CHECK(atalaia_packet_decrypt(pkt, pkt_len, epoch, key, &out_hdr, out_payload, &out_len,
                                 &atalaia_crypto_mbedtls));
    CHECK(out_len == payload_len);
    CHECK(memcmp(out_payload, payload, payload_len) == 0);
    CHECK(out_hdr.game_id == hdr.game_id);
    CHECK(out_hdr.source == hdr.source);
    CHECK(out_hdr.seq == hdr.seq);
}

static void test_mbedtls_tampered_packet_fails(void)
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
    size_t pkt_len =
        atalaia_packet_encrypt(&hdr, 0, key, payload, 3, pkt, sizeof(pkt), &atalaia_crypto_mbedtls);
    CHECK(pkt_len > 0);

    pkt[ATALAIA_RF_HEADER_SIZE] ^= 0x01; /* flip ciphertext bit */

    atalaia_header_t out_hdr;
    uint8_t out_payload[256];
    size_t out_len = 0;
    CHECK(!atalaia_packet_decrypt(pkt, pkt_len, 0, key, &out_hdr, out_payload, &out_len,
                                  &atalaia_crypto_mbedtls));
}

static void test_mbedtls_empty_payload(void)
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
        atalaia_packet_encrypt(&hdr, 0, key, NULL, 0, pkt, sizeof(pkt), &atalaia_crypto_mbedtls);
    CHECK(pkt_len == ATALAIA_RF_HEADER_SIZE + ATALAIA_RF_MIC_SIZE);

    atalaia_header_t out_hdr;
    uint8_t out_payload[256];
    size_t out_len = 99;
    CHECK(atalaia_packet_decrypt(pkt, pkt_len, 0, key, &out_hdr, out_payload, &out_len,
                                 &atalaia_crypto_mbedtls));
    CHECK(out_len == 0);
}

/* ---- shared AES-CCM vector tests ----------------------------------------- */

static void test_aes_ccm_vectors_encrypt(void)
{
    for (size_t i = 0; i < AES_CCM_VECTOR_COUNT; i++) {
        const aes_ccm_vector_t *v = &aes_ccm_vectors[i];

        /* Verify nonce construction. */
        atalaia_header_t hdr = {.version_flags = v->version_flags,
                                .game_id = v->game_id,
                                .source = v->source,
                                .seq = v->seq,
                                .hop_limit = v->hop_limit,
                                .type = v->type};
        uint8_t nonce[ATALAIA_RF_NONCE_SIZE];
        atalaia_nonce_build(&hdr, v->epoch, nonce);
        CHECK(memcmp(nonce, v->nonce, ATALAIA_RF_NONCE_SIZE) == 0);

        /* Verify AAD construction. */
        uint8_t hdr_buf[ATALAIA_RF_HEADER_SIZE];
        atalaia_header_encode(&hdr, hdr_buf);
        uint8_t aad[ATALAIA_RF_AAD_SIZE];
        atalaia_aad_extract(hdr_buf, aad);
        CHECK(memcmp(aad, v->aad, v->aad_len) == 0);

        /* Encrypt and compare ciphertext + tag. */
        uint8_t ct[256];
        uint8_t tag[ATALAIA_RF_MIC_SIZE];
        int rc = atalaia_crypto_mbedtls.encrypt(
            atalaia_crypto_mbedtls.ctx, v->key, nonce, ATALAIA_RF_NONCE_SIZE, aad, v->aad_len,
            v->plaintext, v->plaintext_len, ct, tag, ATALAIA_RF_MIC_SIZE);
        CHECK(rc == 0);
        if (v->ciphertext_len > 0) {
            CHECK(memcmp(ct, v->ciphertext, v->ciphertext_len) == 0);
        }
        CHECK(memcmp(tag, v->tag, ATALAIA_RF_MIC_SIZE) == 0);
    }
}

static void test_aes_ccm_vectors_decrypt(void)
{
    for (size_t i = 0; i < AES_CCM_VECTOR_COUNT; i++) {
        const aes_ccm_vector_t *v = &aes_ccm_vectors[i];
        uint8_t nonce[ATALAIA_RF_NONCE_SIZE];
        atalaia_header_t hdr = {.version_flags = v->version_flags,
                                .game_id = v->game_id,
                                .source = v->source,
                                .seq = v->seq,
                                .hop_limit = v->hop_limit,
                                .type = v->type};
        atalaia_nonce_build(&hdr, v->epoch, nonce);
        uint8_t hdr_buf[ATALAIA_RF_HEADER_SIZE];
        atalaia_header_encode(&hdr, hdr_buf);
        uint8_t aad[ATALAIA_RF_AAD_SIZE];
        atalaia_aad_extract(hdr_buf, aad);

        uint8_t pt[256];
        int rc = atalaia_crypto_mbedtls.decrypt(
            atalaia_crypto_mbedtls.ctx, v->key, nonce, ATALAIA_RF_NONCE_SIZE, aad, v->aad_len,
            v->ciphertext, v->ciphertext_len, pt, v->tag, ATALAIA_RF_MIC_SIZE);
        CHECK(rc == 0);
        if (v->plaintext_len > 0) {
            CHECK(memcmp(pt, v->plaintext, v->plaintext_len) == 0);
        }
    }
}

void run_crypto_mbedtls_tests(void)
{
    test_rfc3610_encrypt();
    test_rfc3610_decrypt();
    test_rfc3610_tampered_fails();
    test_rfc3610_wrong_key_fails();
    test_mbedtls_packet_round_trip();
    test_mbedtls_tampered_packet_fails();
    test_mbedtls_empty_payload();
    test_aes_ccm_vectors_encrypt();
    test_aes_ccm_vectors_decrypt();
}

#else /* !ATALAIA_HAVE_MBEDTLS */

void run_crypto_mbedtls_tests(void)
{
    if (getenv("ATALAIA_REQUIRE_ALL") != NULL) {
        fprintf(stderr,
                "FAIL: ATALAIA_REQUIRE_ALL is set but ATALAIA_HAVE_MBEDTLS is not defined\n");
        check_failures++;
        return;
    }
    printf("  skipped: AES-CCM tests (mbedtls not available)\n");
}

#endif /* ATALAIA_HAVE_MBEDTLS */
