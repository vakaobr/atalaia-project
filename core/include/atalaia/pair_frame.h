/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Pair frames (protocol/adoption.md section 7, RFC 0001 Amendment 8): adopting
 * a box over the radio with the 6-digit code it shows. Message type 10 (PAIR),
 * game id 0, hop_limit 0, never relayed, in the clear: the box has no key yet,
 * so the security comes from CPace (CPACE-X25519-SHA512, run with the code;
 * firmware/esp32/main/cpace.c, simulator/atalaia_sim/cpace.py).
 *
 *   header (9: version 1, not encrypted, game 0, source 0, seq 0, hop 0, type 10) | body (CBOR)
 *
 *   OFFER  box -> controllers  pair id, name, tier
 *   START  controller -> box   pair id, sid, Ya
 *   REPLY  box -> controller   pair id, sid, Yb, tag (the box's key confirmation)
 *   KEY    controller -> box   pair id, sid, tag (the controller's), nonce, sealed (join key, name)
 *   DONE   box -> controller   pair id, sid, result, fingerprint, tag
 *
 * This file has the bodies, the frames and what follows CPace's ISK: the keys
 * (HKDF-SHA256, salt = sid), the tags and the sealed join key (AES-128-CCM with
 * an 8-byte MIC under a nonce that never depends on a random number generator).
 * The C codec here and the Python one (simulator/atalaia_sim/pair_frame.py)
 * check the same vectors (protocol/vectors/pairing.json).
 */
#ifndef ATALAIA_PAIR_FRAME_H
#define ATALAIA_PAIR_FRAME_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "atalaia/join.h"
#include "atalaia/packet.h"

#define ATALAIA_PF_TYPE           10                     /* ATALAIA_MSG_PAIR */
#define ATALAIA_PF_BODY_MAX       ATALAIA_RF_PAYLOAD_MAX /* 200 */
#define ATALAIA_PF_MIN            (ATALAIA_RF_HEADER_SIZE + 1)
#define ATALAIA_PF_MAX            (ATALAIA_RF_HEADER_SIZE + ATALAIA_PF_BODY_MAX) /* 209 */
#define ATALAIA_PF_PAIR_ID_SIZE   8
#define ATALAIA_PF_SID_SIZE       16
#define ATALAIA_PF_POINT_SIZE     32
#define ATALAIA_PF_TAG_SIZE       16
#define ATALAIA_PF_NONCE_SIZE     13
#define ATALAIA_PF_MIC_SIZE       8
#define ATALAIA_PF_FP_SIZE        4
#define ATALAIA_PF_NAME_MAX       24 /* the box's name in OFFER */
#define ATALAIA_PF_FIELD_NAME_MAX 48 /* the field's name sealed in KEY */
#define ATALAIA_PF_SEALED_MIN     (ATALAIA_JOIN_KEY_SIZE + 1 + ATALAIA_PF_MIC_SIZE)
#define ATALAIA_PF_SEALED_MAX     (ATALAIA_PF_SEALED_MIN + ATALAIA_PF_FIELD_NAME_MAX)
#define ATALAIA_PF_ISK_SIZE       64
#define ATALAIA_PF_CODE_DIGITS    6
#define ATALAIA_PF_CI_LABEL       "atalaia pair v1"
#define ATALAIA_PF_AD_CONTROLLER  "atalaia controller"
#define ATALAIA_PF_AD_BOX         "atalaia box"
/* lv_cat(CI_LABEL, pair id): 1 + 15 + 1 + 8 bytes. */
#define ATALAIA_PF_CI_SIZE (2 + sizeof(ATALAIA_PF_CI_LABEL) - 1 + ATALAIA_PF_PAIR_ID_SIZE)

typedef enum {
    ATALAIA_PF_OFFER = 1,
    ATALAIA_PF_START = 2,
    ATALAIA_PF_REPLY = 3,
    ATALAIA_PF_KEY = 4,
    ATALAIA_PF_DONE = 5,
} atalaia_pf_kind_t;

enum {
    ATALAIA_PF_K_KIND = 1,
    ATALAIA_PF_K_PAIR = 2,
    ATALAIA_PF_K_NAME = 3,
    ATALAIA_PF_K_TIER = 4,
    ATALAIA_PF_K_SID = 5,
    ATALAIA_PF_K_POINT = 6,
    ATALAIA_PF_K_TAG = 7,
    ATALAIA_PF_K_NONCE = 8,
    ATALAIA_PF_K_SEALED = 9,
    ATALAIA_PF_K_RESULT = 10,
    ATALAIA_PF_K_FP = 11,
};

/* DONE's results: firmware/esp32/main/adoption.h's adopt_result_t, in its order (0-9). */
#define ATALAIA_PF_RESULT_MAX 9

typedef struct {
    uint8_t kind; /* atalaia_pf_kind_t */
    uint8_t pair_id[ATALAIA_PF_PAIR_ID_SIZE];
    /* OFFER */
    char name[ATALAIA_PF_NAME_MAX + 1];
    uint8_t tier; /* 0 full, 1 reduced, 2 proxy */
    /* the rest */
    uint8_t sid[ATALAIA_PF_SID_SIZE];
    uint8_t point[ATALAIA_PF_POINT_SIZE]; /* START: Ya, REPLY: Yb */
    uint8_t tag[ATALAIA_PF_TAG_SIZE];     /* REPLY, KEY, DONE */
    uint8_t nonce[ATALAIA_PF_NONCE_SIZE]; /* KEY */
    uint8_t sealed[ATALAIA_PF_SEALED_MAX];
    uint8_t sealed_len;
    uint8_t result; /* DONE */
    uint8_t fingerprint[ATALAIA_PF_FP_SIZE];
} atalaia_pf_msg_t;

/* True for a pair frame's header (version 1, not encrypted, game 0, type 10) and length. */
bool atalaia_pf_is_frame(const uint8_t *pkt, size_t len);

/* The whole frame (header and body); 0 if a field is out of range or it does not fit. */
size_t atalaia_pf_encode(const atalaia_pf_msg_t *m, uint8_t *out, size_t cap);

/* Reads a body: the kind first, every field of the kind once, no key of another kind,
 * no key from 32 up (unknown keys up to 31 are skipped), nothing after the map. */
bool atalaia_pf_body_decode(const uint8_t *buf, size_t len, atalaia_pf_msg_t *m);

/* atalaia_pf_is_frame, then the body. */
bool atalaia_pf_decode(const uint8_t *pkt, size_t len, atalaia_pf_msg_t *m);

/* CPace's channel identifier for a box's pair id: lv_cat(ATALAIA_PF_CI_LABEL, pair id). */
void atalaia_pf_channel_id(const uint8_t pair_id[ATALAIA_PF_PAIR_ID_SIZE],
                           uint8_t out[ATALAIA_PF_CI_SIZE]);

/* The run's keys from CPace's ISK: HKDF-SHA256 with the sid as salt. */
typedef struct {
    uint8_t confirm_a[32]; /* the controller's tag (KEY) */
    uint8_t confirm_b[32]; /* the box's tags (REPLY, DONE) */
    uint8_t seal[16];      /* AES-128-CCM of KEY's sealed join key */
    uint8_t nonce[32];     /* the key of KEY's nonce pseudonym */
} atalaia_pf_keys_t;

void atalaia_pf_keys(const uint8_t isk[ATALAIA_PF_ISK_SIZE], const uint8_t sid[ATALAIA_PF_SID_SIZE],
                     atalaia_pf_keys_t *out);

void atalaia_pf_tag_reply(const atalaia_pf_keys_t *k, uint8_t out[ATALAIA_PF_TAG_SIZE]);
void atalaia_pf_tag_key(const atalaia_pf_keys_t *k, uint8_t out[ATALAIA_PF_TAG_SIZE]);
void atalaia_pf_tag_done(const atalaia_pf_keys_t *k, uint8_t result,
                         const uint8_t fingerprint[ATALAIA_PF_FP_SIZE],
                         uint8_t out[ATALAIA_PF_TAG_SIZE]);

/* Equal tags, in constant time. */
bool atalaia_pf_tag_equal(const uint8_t a[ATALAIA_PF_TAG_SIZE],
                          const uint8_t b[ATALAIA_PF_TAG_SIZE]);

/*
 * KEY's sealed join key and field name: AES-128-CCM under k->seal, nonce as given, AAD
 * "atalaia pair key v1" | pair id | sid; plaintext key (32) | name length (1) | name.
 * seal returns the sealed length (or 0); open returns false unless it authenticates and
 * the name's length is right (name: NUL-terminated, at most 48 bytes, not otherwise checked).
 */
size_t atalaia_pf_seal_key(const atalaia_pf_keys_t *k, const uint8_t nonce[ATALAIA_PF_NONCE_SIZE],
                           const uint8_t pair_id[ATALAIA_PF_PAIR_ID_SIZE],
                           const uint8_t sid[ATALAIA_PF_SID_SIZE],
                           const uint8_t join_key[ATALAIA_JOIN_KEY_SIZE], const char *name,
                           uint8_t *out, size_t cap, const atalaia_crypto_ops_t *crypto);
bool atalaia_pf_open_key(const atalaia_pf_keys_t *k, const uint8_t nonce[ATALAIA_PF_NONCE_SIZE],
                         const uint8_t pair_id[ATALAIA_PF_PAIR_ID_SIZE],
                         const uint8_t sid[ATALAIA_PF_SID_SIZE], const uint8_t *sealed,
                         size_t sealed_len, uint8_t join_key[ATALAIA_JOIN_KEY_SIZE],
                         char name[ATALAIA_PF_FIELD_NAME_MAX + 1],
                         const atalaia_crypto_ops_t *crypto);

#endif /* ATALAIA_PAIR_FRAME_H */
