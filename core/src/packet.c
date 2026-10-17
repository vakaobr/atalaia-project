/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Skirmesh-RF packet header codec, nonce/AAD construction, and the
 * test-stub crypto backend. The header is 9 bytes, big-endian. The
 * test stub XORs with a deterministic key+nonce-derived stream and
 * uses FNV-1a for the tag, so all framing logic can be tested without
 * a real AES-CCM library.
 */
#include <string.h>

#include "atalaia/packet.h"

/* ---- big-endian helpers --------------------------------------------------- */

static void put_u16_be(uint8_t *p, uint16_t v)
{
    p[0] = (uint8_t)(v >> 8);
    p[1] = (uint8_t)(v);
}

static uint16_t get_u16_be(const uint8_t *p)
{
    return (uint16_t)((uint16_t)p[0] << 8 | p[1]);
}

/* ---- header encode / decode ----------------------------------------------- */

void atalaia_header_encode(const atalaia_header_t *hdr, uint8_t buf[ATALAIA_RF_HEADER_SIZE])
{
    buf[0] = hdr->version_flags;
    put_u16_be(buf + 1, hdr->game_id);
    put_u16_be(buf + 3, hdr->source);
    put_u16_be(buf + 5, hdr->seq);
    buf[7] = hdr->hop_limit;
    buf[8] = hdr->type;
}

bool atalaia_header_decode(const uint8_t buf[ATALAIA_RF_HEADER_SIZE], atalaia_header_t *hdr)
{
    if (buf == NULL || hdr == NULL) {
        return false;
    }
    hdr->version_flags = buf[0];
    hdr->game_id = get_u16_be(buf + 1);
    hdr->source = get_u16_be(buf + 3);
    hdr->seq = get_u16_be(buf + 5);
    hdr->hop_limit = buf[7];
    hdr->type = buf[8];

    /* Reject unknown versions. */
    if (ATALAIA_VF_VERSION(hdr->version_flags) != 1) {
        return false;
    }
    return true;
}

/* ---- nonce ---------------------------------------------------------------- */

/*
 * 13-byte nonce:
 *   bytes 0-1   game_id   (big-endian)
 *   bytes 2-3   source    (big-endian)
 *   bytes 4-7   (epoch << 16) | seq  (big-endian uint32)
 *   bytes 8-12  zeros
 */
void atalaia_nonce_build(const atalaia_header_t *hdr, uint16_t epoch,
                         uint8_t nonce[ATALAIA_RF_NONCE_SIZE])
{
    memset(nonce, 0, ATALAIA_RF_NONCE_SIZE);
    put_u16_be(nonce + 0, hdr->game_id);
    put_u16_be(nonce + 2, hdr->source);
    uint32_t combined = ((uint32_t)epoch << 16) | hdr->seq;
    nonce[4] = (uint8_t)(combined >> 24);
    nonce[5] = (uint8_t)(combined >> 16);
    nonce[6] = (uint8_t)(combined >> 8);
    nonce[7] = (uint8_t)(combined);
    /* bytes 8-12 already zero */
}

/* ---- AAD ------------------------------------------------------------------ */

/*
 * AAD = header bytes 0-6 + byte 8 (skip hop_limit at byte 7).
 * This binds the ciphertext to everything except the mutable hop_limit.
 */
void atalaia_aad_extract(const uint8_t header_buf[ATALAIA_RF_HEADER_SIZE],
                         uint8_t aad[ATALAIA_RF_AAD_SIZE])
{
    memcpy(aad, header_buf, 7); /* bytes 0-6 */
    aad[7] = header_buf[8];     /* byte 8 (type), skipping hop_limit */
}

/* ---- full packet encrypt / decrypt ---------------------------------------- */

size_t atalaia_packet_encrypt(const atalaia_header_t *hdr, uint16_t epoch, const uint8_t *key,
                              const uint8_t *payload, size_t payload_len, uint8_t *out,
                              size_t out_cap, const atalaia_crypto_ops_t *crypto)
{
    if (hdr == NULL || key == NULL || crypto == NULL || crypto->encrypt == NULL) {
        return 0;
    }
    if (payload_len > ATALAIA_RF_PAYLOAD_MAX) {
        return 0;
    }
    size_t total = ATALAIA_RF_HEADER_SIZE + payload_len + ATALAIA_RF_MIC_SIZE;
    if (total > out_cap) {
        return 0;
    }

    /* Write header. */
    atalaia_header_encode(hdr, out);

    /* Build nonce and AAD. */
    uint8_t nonce[ATALAIA_RF_NONCE_SIZE];
    atalaia_nonce_build(hdr, epoch, nonce);

    uint8_t aad[ATALAIA_RF_AAD_SIZE];
    atalaia_aad_extract(out, aad);

    /* Encrypt payload into out after the header; tag follows. */
    uint8_t *ct = out + ATALAIA_RF_HEADER_SIZE;
    uint8_t *tag = ct + payload_len;

    int rc =
        crypto->encrypt(crypto->ctx, key, nonce, ATALAIA_RF_NONCE_SIZE, aad, ATALAIA_RF_AAD_SIZE,
                        payload, payload_len, ct, tag, ATALAIA_RF_MIC_SIZE);
    if (rc != 0) {
        return 0;
    }
    return total;
}

bool atalaia_packet_decrypt(const uint8_t *pkt, size_t pkt_len, uint16_t epoch, const uint8_t *key,
                            atalaia_header_t *hdr, uint8_t *payload, size_t *payload_len,
                            const atalaia_crypto_ops_t *crypto)
{
    if (pkt == NULL || key == NULL || hdr == NULL || payload == NULL || payload_len == NULL ||
        crypto == NULL || crypto->decrypt == NULL) {
        return false;
    }
    if (pkt_len < ATALAIA_RF_HEADER_SIZE + ATALAIA_RF_MIC_SIZE) {
        return false;
    }

    if (!atalaia_header_decode(pkt, hdr)) {
        return false;
    }

    size_t ct_len = pkt_len - ATALAIA_RF_HEADER_SIZE - ATALAIA_RF_MIC_SIZE;
    if (ct_len > ATALAIA_RF_PAYLOAD_MAX) {
        return false;
    }

    uint8_t nonce[ATALAIA_RF_NONCE_SIZE];
    atalaia_nonce_build(hdr, epoch, nonce);

    uint8_t aad[ATALAIA_RF_AAD_SIZE];
    atalaia_aad_extract(pkt, aad);

    const uint8_t *ct = pkt + ATALAIA_RF_HEADER_SIZE;
    const uint8_t *tag = ct + ct_len;

    int rc = crypto->decrypt(crypto->ctx, key, nonce, ATALAIA_RF_NONCE_SIZE, aad,
                             ATALAIA_RF_AAD_SIZE, ct, ct_len, payload, tag, ATALAIA_RF_MIC_SIZE);
    if (rc != 0) {
        return false;
    }
    *payload_len = ct_len;
    return true;
}

/* ---- test stub crypto backend --------------------------------------------- */

/*
 * The test stub uses a simple XOR stream derived from key + nonce for
 * "encryption" and FNV-1a over (key + nonce + aad + plaintext) for the
 * "tag". This is NOT cryptographically secure -- it exists only to test
 * the packet framing, nonce construction and AAD extraction.
 */

/* Generate a pseudo-random byte stream by hashing key+nonce+counter. */
static uint8_t stub_stream_byte(const uint8_t *key, const uint8_t *nonce, size_t nonce_len,
                                size_t index)
{
    /* Simple hash: FNV-1a seeded with the index, mixed with key and nonce. */
    uint32_t h = 2166136261u ^ (uint32_t)index;
    for (size_t i = 0; i < ATALAIA_RF_KEY_SIZE; i++) {
        h ^= key[i];
        h *= 16777619u;
    }
    for (size_t i = 0; i < nonce_len; i++) {
        h ^= nonce[i];
        h *= 16777619u;
    }
    return (uint8_t)(h & 0xFF);
}

static void stub_compute_tag(const uint8_t *key, const uint8_t *nonce, size_t nonce_len,
                             const uint8_t *aad, size_t aad_len, const uint8_t *plaintext,
                             size_t pt_len, uint8_t *tag, size_t tag_len)
{
    /* FNV-1a over key + nonce + aad + plaintext, then spread to tag_len. */
    uint32_t h = 2166136261u;
    size_t i;
    for (i = 0; i < ATALAIA_RF_KEY_SIZE; i++) {
        h ^= key[i];
        h *= 16777619u;
    }
    for (i = 0; i < nonce_len; i++) {
        h ^= nonce[i];
        h *= 16777619u;
    }
    for (i = 0; i < aad_len; i++) {
        h ^= aad[i];
        h *= 16777619u;
    }
    for (i = 0; i < pt_len; i++) {
        h ^= plaintext[i];
        h *= 16777619u;
    }
    /* Fill the tag by cycling through the hash bytes and re-hashing. */
    for (i = 0; i < tag_len; i++) {
        tag[i] = (uint8_t)(h >> (8 * (i % 4)));
        if ((i % 4) == 3) {
            h ^= (uint32_t)(i + 1);
            h *= 16777619u;
        }
    }
}

static int stub_encrypt(void *ctx, const uint8_t *key, const uint8_t *nonce, size_t nonce_len,
                        const uint8_t *aad, size_t aad_len, const uint8_t *plaintext, size_t pt_len,
                        uint8_t *ciphertext, uint8_t *tag, size_t tag_len)
{
    (void)ctx;
    for (size_t i = 0; i < pt_len; i++) {
        ciphertext[i] = plaintext[i] ^ stub_stream_byte(key, nonce, nonce_len, i);
    }
    stub_compute_tag(key, nonce, nonce_len, aad, aad_len, plaintext, pt_len, tag, tag_len);
    return 0;
}

static int stub_decrypt(void *ctx, const uint8_t *key, const uint8_t *nonce, size_t nonce_len,
                        const uint8_t *aad, size_t aad_len, const uint8_t *ciphertext,
                        size_t ct_len, uint8_t *plaintext, const uint8_t *tag, size_t tag_len)
{
    (void)ctx;
    /* Decrypt by XOR. */
    for (size_t i = 0; i < ct_len; i++) {
        plaintext[i] = ciphertext[i] ^ stub_stream_byte(key, nonce, nonce_len, i);
    }
    /* Verify tag. */
    uint8_t expected[ATALAIA_RF_MIC_SIZE];
    if (tag_len > sizeof(expected)) {
        return -1;
    }
    stub_compute_tag(key, nonce, nonce_len, aad, aad_len, plaintext, ct_len, expected, tag_len);
    for (size_t i = 0; i < tag_len; i++) {
        if (tag[i] != expected[i]) {
            return -1;
        }
    }
    return 0;
}

const atalaia_crypto_ops_t atalaia_crypto_test_stub = {
    .encrypt = stub_encrypt, .decrypt = stub_decrypt, .ctx = NULL};
