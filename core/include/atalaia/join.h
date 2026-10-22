/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Join payload (ADR-P2-12, protocol/join.md): what a box or a standby
 * controller needs to take part in a game, carried by an NFC card, a QR
 * code or a serial line, never over LoRa.
 *
 *   version (1 byte, 1) | body (CBOR map, integer keys) | HMAC-SHA256 (32)
 *
 * The tag is HMAC-SHA256 over the version byte and the body, keyed with
 * the field's 32-byte join key (set once on every controller and box of a
 * field). The C codec here and the Python one (simulator/atalaia_sim/join.py)
 * check the same vectors (protocol/vectors/join.json).
 */
#ifndef ATALAIA_JOIN_H
#define ATALAIA_JOIN_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define ATALAIA_JOIN_VERSION     1
#define ATALAIA_JOIN_MAX         448 /* whole payload, bytes: fits an NTAG215 card */
#define ATALAIA_JOIN_MAC_SIZE    32
#define ATALAIA_JOIN_KEY_SIZE    32 /* the field join key */
#define ATALAIA_JOIN_GAME_KEY    16
#define ATALAIA_JOIN_TEAMS_MAX   8
#define ATALAIA_JOIN_TEAM_MAX    23 /* bytes, without the NUL (ATALAIA_TEAM_NAME_MAX - 1) */
#define ATALAIA_JOIN_MODE_MAX    63
#define ATALAIA_JOIN_ROLE_MAX    31
#define ATALAIA_JOIN_PARAMS_MAX  200 /* bytes of the parameters' compact JSON form */
#define ATALAIA_JOIN_URLS_MAX    3   /* key 14: the controller's https addresses */
#define ATALAIA_JOIN_URL_MAX     64  /* bytes of one address, without the NUL */
#define ATALAIA_JOIN_CA_SIZE     32  /* key 13: SHA-256 of the field CA's DER certificate */
#define ATALAIA_JOIN_LANG_MAX    8   /* key 15: the box language, bytes without the NUL */
#define ATALAIA_JOIN_TEXT_PREFIX "atalaia:join:"
#define ATALAIA_JOIN_NDEF_TYPE   "application/vnd.atalaia.join"

/* CBOR keys of the body. */
enum {
    ATALAIA_JOIN_K_GAME_ID = 1,
    ATALAIA_JOIN_K_GAME_KEY = 2,
    ATALAIA_JOIN_K_NODE_ID = 3,
    ATALAIA_JOIN_K_CONTROLLER_ID = 4,
    ATALAIA_JOIN_K_CHANNEL_HZ = 5,
    ATALAIA_JOIN_K_MAX_HOPS = 6,
    ATALAIA_JOIN_K_TEAMS = 7,
    ATALAIA_JOIN_K_MODE_ID = 8,
    ATALAIA_JOIN_K_ROLE = 9,
    ATALAIA_JOIN_K_GAME_SEED = 10,
    ATALAIA_JOIN_K_PARAMS = 11,
    ATALAIA_JOIN_K_KIND = 12,
    ATALAIA_JOIN_K_CA_SHA256 = 13, /* optional (RFC 0001 Amendment 4) */
    ATALAIA_JOIN_K_URLS = 14,      /* optional (RFC 0001 Amendment 4) */
    ATALAIA_JOIN_K_LANG = 15,      /* optional (RFC 0001 Amendment 10) */
};

typedef enum {
    ATALAIA_JOIN_KIND_NODE = 0,       /* a box or other prop */
    ATALAIA_JOIN_KIND_CONTROLLER = 1, /* a standby controller */
} atalaia_join_kind_t;

typedef struct {
    uint16_t game_id; /* 1-65534 */
    uint8_t game_key[ATALAIA_JOIN_GAME_KEY];
    uint16_t node_id;       /* this device's short id in the game, 0-65534 */
    uint16_t controller_id; /* the controller that issued it, 0-65534 */
    uint32_t channel_hz;    /* the shared game channel, inside an EU868 sub-band */
    uint8_t max_hops;       /* relay clamp, 1-3 (ADR-P2-6) */
    char teams[ATALAIA_JOIN_TEAMS_MAX][ATALAIA_JOIN_TEAM_MAX + 1];
    uint8_t team_count; /* 1-8 */
    char mode_id[ATALAIA_JOIN_MODE_MAX + 1];
    char role[ATALAIA_JOIN_ROLE_MAX + 1];
    uint32_t game_seed;
    char params_json[ATALAIA_JOIN_PARAMS_MAX + 1]; /* "" when the payload has none */
    uint8_t kind;                                  /* atalaia_join_kind_t */
    /* The field CA and the controller's https addresses (keys 13 and 14), when the
     * controller serves HTTPS: a box uses them only for firmware updates over Wi-Fi
     * (protocol/firmware-update.md), pinning that CA. */
    bool has_ca;
    uint8_t ca_sha256[ATALAIA_JOIN_CA_SIZE];
    uint8_t url_count; /* 0-3 */
    char urls[ATALAIA_JOIN_URLS_MAX][ATALAIA_JOIN_URL_MAX + 1];
    /* The language of the box's screens (key 15): "pt", "en", "pt-br"...; "" when the payload
     * has none (English). A box that does not know the language uses English. */
    char lang[ATALAIA_JOIN_LANG_MAX + 1];
} atalaia_join_t;

typedef enum {
    ATALAIA_JOIN_OK = 0,
    ATALAIA_JOIN_ERR_LENGTH,  /* shorter than version + empty map + tag, or over the maximum */
    ATALAIA_JOIN_ERR_VERSION, /* a format version this codec does not know */
    ATALAIA_JOIN_ERR_MAC,     /* the tag does not match: another field's key, or tampered */
    ATALAIA_JOIN_ERR_BODY,    /* authentic, but a field is missing, malformed or out of range */
} atalaia_join_result_t;

/* A short English name for a result, for logs. */
const char *atalaia_join_result_name(atalaia_join_result_t result);

/*
 * Writes the payload for j, tagged with join_key. Returns its length, or 0
 * if a field is out of range or it does not fit in cap (or in
 * ATALAIA_JOIN_MAX).
 */
size_t atalaia_join_encode(const atalaia_join_t *j, const uint8_t join_key[ATALAIA_JOIN_KEY_SIZE],
                           uint8_t *buf, size_t cap);

/*
 * Checks the tag (in constant time) and then the body. Fills *out only
 * when the result is ATALAIA_JOIN_OK. Keys 13 (ca_sha256) and 14 (urls) are
 * read; unknown body keys 15-31 are skipped, so a newer controller may add
 * optional fields; keys from 32 up are refused.
 */
atalaia_join_result_t atalaia_join_decode(const uint8_t *buf, size_t len,
                                          const uint8_t join_key[ATALAIA_JOIN_KEY_SIZE],
                                          atalaia_join_t *out);

/* True if s is a join's language (key 15): 2-8 bytes of a-z, 0-9 and '-', the first two a-z. */
bool atalaia_join_lang_ok(const char *s);

/* True if s is valid UTF-8 without NUL, 1..max bytes: the payload's rule for text fields
 * (also the field frames', atalaia/field_frame.h). */
bool atalaia_join_text_ok(const char *s, size_t max);

/* Checks the fields of j as the decoder does (ranges, sizes, teams, addresses). */
bool atalaia_join_valid(const atalaia_join_t *j);

/* True if url is "https://host[:port]" (host: DNS labels or a [bracketed IPv6]
 * address; port 1-65535), ASCII, at most ATALAIA_JOIN_URL_MAX bytes: the
 * check-in poster's rule (protocol/checkin.md). */
bool atalaia_join_url_ok(const char *url);

/*
 * The text form, as in a QR code or on the serial console:
 * "atalaia:join:" + base64url without padding. Leading and trailing
 * spaces are ignored. Returns the payload length, or 0 if the text is not
 * a join text or does not fit in cap.
 */
size_t atalaia_join_from_text(const char *text, uint8_t *buf, size_t cap);

/* Writes the text form (NUL-terminated). Returns its length, or 0 if it does not fit. */
size_t atalaia_join_to_text(const uint8_t *payload, size_t len, char *text, size_t cap);

/*
 * Finds the join payload in the user memory of an NFC Forum Type 2 tag
 * (NTAG215/216, from page 4): the NDEF message TLV, then the first MIME
 * record of type ATALAIA_JOIN_NDEF_TYPE. Sets *payload to point inside mem
 * and returns its length, or 0 if there is none or the TLVs are malformed.
 */
size_t atalaia_join_from_ndef_tag(const uint8_t *mem, size_t len, const uint8_t **payload);

/*
 * Writes the bytes for a Type 2 tag's user memory (page 4 onwards): an
 * NDEF message TLV with one MIME record holding the payload, then the
 * terminator TLV. Returns the length, or 0 if it does not fit in cap.
 */
size_t atalaia_join_to_ndef_tag(const uint8_t *payload, size_t len, uint8_t *mem, size_t cap);

/*
 * The same two operations for any MIME record type (the join card's, or a
 * player tag's ATALAIA_TAG_NDEF_TYPE in atalaia/tag.h).
 */
size_t atalaia_ndef_find_mime(const uint8_t *mem, size_t len, const char *mime,
                              const uint8_t **payload);
size_t atalaia_ndef_write_mime(const char *mime, const uint8_t *payload, size_t len, uint8_t *mem,
                               size_t cap);

/* HMAC-SHA256 (RFC 2104 / FIPS 180-4), used by the join tag and player tags. */
void atalaia_hmac_sha256(const uint8_t *key, size_t key_len, const uint8_t *msg, size_t msg_len,
                         uint8_t out[32]);

/* SHA-256 of msg. */
void atalaia_sha256(const uint8_t *msg, size_t len, uint8_t out[32]);

/* SHA-256 of a stream (a firmware image as it downloads): init, update, final. */
typedef struct {
    uint32_t h[8];
    uint8_t block[64];
    size_t used;   /* bytes in block */
    uint64_t bits; /* message length so far */
} atalaia_sha256_t;
void atalaia_sha256_init(atalaia_sha256_t *s);
void atalaia_sha256_update(atalaia_sha256_t *s, const uint8_t *data, size_t len);
void atalaia_sha256_final(atalaia_sha256_t *s, uint8_t out[32]);

/* True if the channel lies inside an EU868 sub-band (g, g1, g2, g3). */
bool atalaia_join_channel_ok(uint32_t channel_hz);

#endif /* ATALAIA_JOIN_H */
