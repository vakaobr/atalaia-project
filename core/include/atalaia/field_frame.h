/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Field frames (protocol/field-frames.md, RFC 0001 Amendment 7): what travels
 * on a field's radio outside any game, between boxes that have no game and the
 * field controllers. Five kinds, in one message type (FIELD, 9):
 *
 *   ANNOUNCE  box -> controllers   "I am free": device id, a fresh token, name, last role
 *   DISCOVER  controller -> boxes  "who is free?": free boxes answer with an ANNOUNCE
 *   INVITE    controller -> a box  a join payload for the box's device id and token, in 1-3 parts
 *   GAME_OVER controller -> boxes  "game N (its key's tag T) is over": a box in that game leaves it
 *                                  (decision OT-13; for a controller that lost the game's key)
 *   MOVE      controller -> boxes  "the field is on channel C now (revision R)": a free box listens
 *                                  there (RFC 0001 Amendment 19)
 *
 * On air:
 *
 *   header (9: game_id 0, source 0, seq 0, hop_limit 0, type 9) | nonce (13) | body (AES-CCM) | MIC
 * (8)
 *
 * The key is HKDF-SHA256 (RFC 5869) of the field join key with the label
 * "atalaia field frame v1" (no salt), 16 bytes; the nonce, in the clear after
 * the header, never depends on a random number generator: the sender's
 * pseudonym (8 bytes, an HMAC of its 8-byte sender id), a boot counter kept in
 * NVS and raised before the first frame of every run (3 bytes) and a frame
 * counter (2 bytes), so no two frames of a field share one (decision RJ-15); the AAD is the
 * header without hop_limit, as for game packets. The body is a CBOR map with
 * integer keys. The C codec here and the Python one (simulator/atalaia_sim/
 * field_frame.py) check the same vectors (protocol/vectors/field_frame.json).
 */
#ifndef ATALAIA_FIELD_FRAME_H
#define ATALAIA_FIELD_FRAME_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "atalaia/join.h"
#include "atalaia/packet.h"

#define ATALAIA_FF_TYPE        9 /* ATALAIA_MSG_FIELD */
#define ATALAIA_FF_KEY_SIZE    16
#define ATALAIA_FF_NONCE_SIZE  13
#define ATALAIA_FF_BODY_MAX    (ATALAIA_RF_PAYLOAD_MAX - ATALAIA_FF_NONCE_SIZE) /* 187 */
#define ATALAIA_FF_MIN         (ATALAIA_RF_HEADER_SIZE + ATALAIA_FF_NONCE_SIZE + 1 + ATALAIA_RF_MIC_SIZE)
#define ATALAIA_FF_MAX         (ATALAIA_RF_HEADER_SIZE + ATALAIA_RF_PAYLOAD_MAX + ATALAIA_RF_MIC_SIZE)
#define ATALAIA_FF_DEVICE_SIZE 8
#define ATALAIA_FF_TOKEN_SIZE  8
#define ATALAIA_FF_NAME_MAX    24
#define ATALAIA_FF_PARTS_MAX   3
/* The largest chunk that keeps an INVITE body within ATALAIA_FF_BODY_MAX (its other
 * fields take 34 bytes at most); three of them hold a join payload of ATALAIA_JOIN_MAX. */
#define ATALAIA_FF_CHUNK_MAX   153
#define ATALAIA_FF_LABEL       "atalaia field frame v1"
#define ATALAIA_FF_NONCE_LABEL "atalaia field nonce v1"
#define ATALAIA_FF_SENDER_SIZE 8         /* a box's device id, a controller's sender id */
#define ATALAIA_FF_BOOT_MAX    0xFFFFFFu /* the boot counter's 3 bytes */
#define ATALAIA_FF_CTR_MAX     0xFFFFu   /* frames per boot count; then the boot count rises */
#define ATALAIA_FF_TAG_SIZE    8         /* a game key's tag (GAME_OVER, see below) */

typedef enum {
    ATALAIA_FF_ANNOUNCE = 1,
    ATALAIA_FF_DISCOVER = 2,
    ATALAIA_FF_INVITE = 3,
    ATALAIA_FF_GAME_OVER = 4, /* RFC 0001 Amendment 7, addendum of 2026-10-22 */
    ATALAIA_FF_MOVE = 5,      /* RFC 0001 Amendment 19: the field's channel changed */
} atalaia_ff_kind_t;

/* What a box answers to an invite (ANNOUNCE key 10). */
typedef enum {
    ATALAIA_FF_ACCEPTED = 0, /* joined: its HELLO follows in the game */
    ATALAIA_FF_BUSY = 1,     /* in a game, or playing a game picked on the box */
    ATALAIA_FF_REFUSED = 2,  /* the join payload's tag or content was refused */
    ATALAIA_FF_NO_MODE = 3,  /* the mode is not installed on the box */
    ATALAIA_FF_NOT_BOX = 4,  /* a standby controller's payload */
    ATALAIA_FF_STORAGE = 5,  /* the join could not be stored */
    ATALAIA_FF_RADIO = 6,    /* the radio may not transmit (epoch storage failed) */
    ATALAIA_FF_ENDED = 7,    /* a game this box has already played to its end */
} atalaia_ff_result_t;

/* Field keys of the bodies (every kind has key 1, the kind). */
enum {
    ATALAIA_FF_K_KIND = 1,
    ATALAIA_FF_K_DEVICE = 2,
    ATALAIA_FF_K_TOKEN = 3,
    /* ANNOUNCE */
    ATALAIA_FF_K_NAME = 4,
    ATALAIA_FF_K_TIER = 5,
    ATALAIA_FF_K_LAST_GAME = 6,
    ATALAIA_FF_K_LAST_ROLE = 7,
    ATALAIA_FF_K_BATTERY = 8,
    ATALAIA_FF_K_ANSWER = 9,
    ATALAIA_FF_K_RESULT = 10,
    /* INVITE */
    ATALAIA_FF_K_INVITE = 4,
    ATALAIA_FF_K_PART = 5,
    ATALAIA_FF_K_PARTS = 6,
    ATALAIA_FF_K_CHUNK = 7,
    /* GAME_OVER */
    ATALAIA_FF_K_GAME = 4,
    ATALAIA_FF_K_KEY_TAG = 5,
    /* MOVE */
    ATALAIA_FF_K_CHANNEL = 4, /* the field's channel, Hz */
    ATALAIA_FF_K_REV = 5,     /* rises with every change of channel */
};

typedef struct {
    uint8_t kind; /* atalaia_ff_kind_t */
    /* ANNOUNCE and INVITE */
    uint8_t device_id[ATALAIA_FF_DEVICE_SIZE];
    uint8_t token[ATALAIA_FF_TOKEN_SIZE];
    /* ANNOUNCE */
    char name[ATALAIA_FF_NAME_MAX + 1];
    uint8_t tier;                              /* 0 full, 1 reduced, 2 proxy */
    uint16_t last_game;                        /* 0 = none */
    char last_role[ATALAIA_JOIN_ROLE_MAX + 1]; /* "" = none */
    uint8_t battery_pct;                       /* 0xFF = unknown */
    uint16_t answer;                           /* the invite answered; 0 = none */
    uint8_t result;                            /* atalaia_ff_result_t, with answer */
    /* INVITE */
    uint16_t invite_id; /* 1-65535 */
    uint8_t part;       /* 0 .. parts - 1 */
    uint8_t parts;      /* 1-3 */
    uint8_t chunk_len;  /* 1-ATALAIA_FF_CHUNK_MAX */
    uint8_t chunk[ATALAIA_FF_CHUNK_MAX];
    /* GAME_OVER */
    uint16_t game_id;                     /* 1-65534 */
    uint8_t key_tag[ATALAIA_FF_TAG_SIZE]; /* the game key's tag (its epoch store's) */
    /* MOVE */
    uint32_t channel_hz; /* 1-0xFFFFFFFF; the box checks it against its region */
    uint32_t rev;        /* 1-0xFFFFFFFF; a box takes only one above the last it took */
} atalaia_ff_msg_t;

/* HKDF-SHA256 (RFC 5869): extract with salt (NULL or empty: 32 zero bytes), then
 * expand with info to out_len bytes (at most 255 * 32). */
bool atalaia_hkdf_sha256(const uint8_t *salt, size_t salt_len, const uint8_t *ikm, size_t ikm_len,
                         const uint8_t *info, size_t info_len, uint8_t *out, size_t out_len);

/* The field frames' AES-128 key from the field join key. */
void atalaia_ff_key(const uint8_t join_key[ATALAIA_JOIN_KEY_SIZE],
                    uint8_t out[ATALAIA_FF_KEY_SIZE]);

/* The key of the nonces' sender pseudonyms (32 bytes): HKDF-SHA256 of the join key with
 * ATALAIA_FF_NONCE_LABEL. */
void atalaia_ff_nonce_key(const uint8_t join_key[ATALAIA_JOIN_KEY_SIZE], uint8_t out[32]);

/* A frame's nonce: HMAC-SHA256(nonce_key, sender)[0..7] | boot (3 bytes, big-endian) |
 * ctr (2 bytes, big-endian). Unique as long as a sender never reuses a (boot, ctr): the boot
 * count is stored before its first use, and raised again when ctr would wrap. */
void atalaia_ff_nonce(const uint8_t nonce_key[32], const uint8_t sender[ATALAIA_FF_SENDER_SIZE],
                      uint32_t boot, uint16_t ctr, uint8_t out[ATALAIA_FF_NONCE_SIZE]);

/* The body of a frame. Returns its length, or 0 if a field is out of range or it does
 * not fit (in cap or in ATALAIA_FF_BODY_MAX). Only the kind's own fields are written. */
size_t atalaia_ff_body_encode(const atalaia_ff_msg_t *m, uint8_t *buf, size_t cap);

/* Reads a body: refuses an unknown kind, a missing or repeated field, a value of the wrong
 * type or out of range, trailing bytes and keys from 32 up; skips unknown keys up to 31. */
bool atalaia_ff_body_decode(const uint8_t *buf, size_t len, atalaia_ff_msg_t *m);

/* True if pkt has a field frame's header (version 1, encrypted, game 0, type 9) and a
 * length between ATALAIA_FF_MIN and ATALAIA_FF_MAX: cheap, before any crypto. */
bool atalaia_ff_is_frame(const uint8_t *pkt, size_t len);

/* Seals a body into a whole frame. Returns its length, or 0. */
size_t atalaia_ff_seal(const uint8_t key[ATALAIA_FF_KEY_SIZE],
                       const uint8_t nonce[ATALAIA_FF_NONCE_SIZE], const uint8_t *body,
                       size_t body_len, uint8_t *out, size_t cap,
                       const atalaia_crypto_ops_t *crypto);

/* Opens a frame into body (at least ATALAIA_FF_BODY_MAX bytes). Returns the body's length,
 * or 0 when it is not a field frame or does not authenticate (another field's key). */
size_t atalaia_ff_open(const uint8_t key[ATALAIA_FF_KEY_SIZE], const uint8_t *pkt, size_t len,
                       uint8_t *body, size_t cap, const atalaia_crypto_ops_t *crypto);

/* An invite's parts put back together. */
typedef struct {
    bool used;
    uint16_t invite_id;
    uint8_t token[ATALAIA_FF_TOKEN_SIZE];
    uint8_t parts;
    uint8_t have; /* bit per part */
    uint8_t len[ATALAIA_FF_PARTS_MAX];
    uint8_t data[ATALAIA_FF_PARTS_MAX][ATALAIA_FF_CHUNK_MAX];
} atalaia_ff_reasm_t;

void atalaia_ff_reasm_reset(atalaia_ff_reasm_t *r);

/*
 * Adds an INVITE part. A part of another invite (id, token or part count) starts over.
 * Returns the join payload's length once every part is there (written to out, and the
 * reassembly is reset), 0 while parts are missing, -1 if the payload does not fit in cap.
 */
int atalaia_ff_reasm_add(atalaia_ff_reasm_t *r, const atalaia_ff_msg_t *m, uint8_t *out,
                         size_t cap);

/* The number of parts a join payload of len bytes takes (0 if it is too long). */
size_t atalaia_ff_parts_for(size_t len);

#endif /* ATALAIA_FIELD_FRAME_H */
