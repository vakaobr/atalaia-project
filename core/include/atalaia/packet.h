/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Skirmesh-RF packet header codec and crypto interface.
 *
 * The 9-byte header (big-endian) carries version_flags, game_id, source,
 * seq, hop_limit and message type. The crypto operations interface lets
 * the packet codec work against any AES-128-CCM backend, including the
 * test stub shipped here for CI without libmbedtls.
 */
#ifndef ATALAIA_PACKET_H
#define ATALAIA_PACKET_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define ATALAIA_RF_HEADER_SIZE 9
#define ATALAIA_RF_MIC_SIZE    8
#define ATALAIA_RF_PAYLOAD_MAX 200
#define ATALAIA_RF_NONCE_SIZE  13
#define ATALAIA_RF_KEY_SIZE    16
#define ATALAIA_RF_AAD_SIZE    8

/* ---- version_flags helpers ------------------------------------------------ */

/*
 * Bit layout of version_flags (byte 0):
 *   7-5  version (3 bits, must be 1)
 *   4-3  priority (2 bits)
 *   2    ack_req  (1 bit)
 *   1    encrypted (1 bit)
 *   0    reserved  (1 bit, must be 0)
 */
#define ATALAIA_VF_MAKE(version, prio, ack, enc)                                                   \
    ((uint8_t)(((version) & 0x07) << 5 | ((prio) & 0x03) << 3 | ((ack) & 0x01) << 2 |              \
               ((enc) & 0x01) << 1))

#define ATALAIA_VF_VERSION(vf) (((vf) >> 5) & 0x07)
#define ATALAIA_VF_PRIO(vf)    (((vf) >> 3) & 0x03)
#define ATALAIA_VF_ACK(vf)     (((vf) >> 2) & 0x01)
#define ATALAIA_VF_ENC(vf)     (((vf) >> 1) & 0x01)

typedef struct {
    uint8_t version_flags;
    uint16_t game_id;
    uint16_t source;
    uint16_t seq;
    uint8_t hop_limit;
    uint8_t type;
} atalaia_header_t;

/* ---- Crypto operations interface ------------------------------------------ */

typedef struct {
    int (*encrypt)(void *ctx, const uint8_t *key, const uint8_t *nonce, size_t nonce_len,
                   const uint8_t *aad, size_t aad_len, const uint8_t *plaintext, size_t pt_len,
                   uint8_t *ciphertext, uint8_t *tag, size_t tag_len);
    int (*decrypt)(void *ctx, const uint8_t *key, const uint8_t *nonce, size_t nonce_len,
                   const uint8_t *aad, size_t aad_len, const uint8_t *ciphertext, size_t ct_len,
                   uint8_t *plaintext, const uint8_t *tag, size_t tag_len);
    void *ctx;
} atalaia_crypto_ops_t;

/* ---- Header encode / decode ----------------------------------------------- */

void atalaia_header_encode(const atalaia_header_t *hdr, uint8_t buf[ATALAIA_RF_HEADER_SIZE]);

bool atalaia_header_decode(const uint8_t buf[ATALAIA_RF_HEADER_SIZE], atalaia_header_t *hdr);

/* ---- Nonce and AAD -------------------------------------------------------- */

void atalaia_nonce_build(const atalaia_header_t *hdr, uint16_t epoch,
                         uint8_t nonce[ATALAIA_RF_NONCE_SIZE]);

void atalaia_aad_extract(const uint8_t header_buf[ATALAIA_RF_HEADER_SIZE],
                         uint8_t aad[ATALAIA_RF_AAD_SIZE]);

/* ---- Full packet encrypt / decrypt ---------------------------------------- */

/*
 * Encrypts header + payload into out (header || ciphertext || MIC).
 * Returns the total packet length, or 0 on error.
 */
size_t atalaia_packet_encrypt(const atalaia_header_t *hdr, uint16_t epoch, const uint8_t *key,
                              const uint8_t *payload, size_t payload_len, uint8_t *out,
                              size_t out_cap, const atalaia_crypto_ops_t *crypto);

/*
 * Decrypts a packet: extracts the header, decrypts the payload and verifies
 * the MIC. Returns true on success; *payload_len is set to the plaintext
 * length.
 */
bool atalaia_packet_decrypt(const uint8_t *pkt, size_t pkt_len, uint16_t epoch, const uint8_t *key,
                            atalaia_header_t *hdr, uint8_t *payload, size_t *payload_len,
                            const atalaia_crypto_ops_t *crypto);

/* ---- Test stub crypto backend (test-only, NOT cryptographically secure) --- */

extern const atalaia_crypto_ops_t atalaia_crypto_test_stub;

/* ---- Real AES-128-CCM backend (mbedtls) ---------------------------------- */

#ifdef ATALAIA_HAVE_MBEDTLS
extern const atalaia_crypto_ops_t atalaia_crypto_mbedtls;
#endif

#endif /* ATALAIA_PACKET_H */
