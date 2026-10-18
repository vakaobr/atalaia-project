/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Player tags (ADR-P3-9, protocol/nfc-tag.md): the NFC tag a player
 * carries in Kill Confirmed, Respawn and Player Check-in. It says who the
 * player is and which team they play for, signed with the game key so a
 * box can tell a real tag from a forged one:
 *
 *   version (1, = 1) | player (1-32 bytes) | team (1) | game_id (2, BE) | mac (16)
 *
 * mac is HMAC-SHA256 over everything before it, keyed with the game's
 * 16-byte key and truncated to 16 bytes. The game key is new for every
 * game, so tags are written for each game (the controller holds the key).
 * The tag's UID is reported but never trusted. On a Type 2 tag the payload
 * is one NDEF MIME record of type ATALAIA_TAG_NDEF_TYPE.
 *
 * The C codec here and the Python one (simulator/atalaia_sim/tag.py) check
 * the same vectors (protocol/vectors/tag.json).
 */
#ifndef ATALAIA_TAG_H
#define ATALAIA_TAG_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define ATALAIA_TAG_VERSION    1
#define ATALAIA_TAG_MAC_SIZE   16
#define ATALAIA_TAG_KEY_SIZE   16 /* the game key */
#define ATALAIA_TAG_PLAYER_MAX 32 /* bytes: letters, digits, '-', '_', '.' */
#define ATALAIA_TAG_MIN        (1 + 1 + 1 + 2 + ATALAIA_TAG_MAC_SIZE)
#define ATALAIA_TAG_MAX        (1 + ATALAIA_TAG_PLAYER_MAX + 1 + 2 + ATALAIA_TAG_MAC_SIZE)
#define ATALAIA_TAG_UID_MAX    10 /* bytes; ISO 14443-3 UIDs are 4, 7 or 10 */
#define ATALAIA_TAG_NDEF_TYPE  "application/vnd.atalaia.tag"
#define ATALAIA_TAG_JSON_MAX   256 /* nfc.tag data, NUL included */

typedef struct {
    char player[ATALAIA_TAG_PLAYER_MAX + 1];
    uint8_t team;     /* 1-based team id in the game; 0 = no team */
    uint16_t game_id; /* the game the tag was written for */
} atalaia_tag_t;

typedef enum {
    ATALAIA_TAG_OK = 0,
    ATALAIA_TAG_ERR_FORMAT,  /* too short or too long, or a malformed player id */
    ATALAIA_TAG_ERR_VERSION, /* a format version this codec does not know */
    ATALAIA_TAG_ERR_GAME,    /* written for another game */
    ATALAIA_TAG_ERR_MAC,     /* the signature does not match: forged or tampered */
    ATALAIA_TAG_ERR_TEAM,    /* authentic, but its team is not one of the game's */
} atalaia_tag_result_t;

/* A short name for a result, as nfc.tag reports it: "ok", "format", "version", "game", "mac",
 * "team". */
const char *atalaia_tag_result_name(atalaia_tag_result_t result);

/* True if the player id is 1-32 bytes of letters, digits, '-', '_' or '.'. */
bool atalaia_tag_player_ok(const char *player);

/*
 * Writes the signed payload for t with the game key. Returns its length,
 * or 0 if the player id is invalid or it does not fit in cap.
 */
size_t atalaia_tag_encode(const atalaia_tag_t *t, const uint8_t game_key[ATALAIA_TAG_KEY_SIZE],
                          uint8_t *buf, size_t cap);

/*
 * Checks a payload for the game (game_id, game_key) with team_count teams.
 * Fills *out only when the result is ATALAIA_TAG_OK. The game id is
 * checked before the signature (a tag from an earlier game reports "game");
 * the signature is compared in constant time.
 */
atalaia_tag_result_t atalaia_tag_decode(const uint8_t *buf, size_t len, uint16_t game_id,
                                        const uint8_t game_key[ATALAIA_TAG_KEY_SIZE],
                                        uint8_t team_count, atalaia_tag_t *out);

/* The payload in a Type 2 tag's user memory (from page 4), or 0 if none. */
size_t atalaia_tag_from_ndef_tag(const uint8_t *mem, size_t len, const uint8_t **payload);

/* A Type 2 tag's user memory holding the payload. Returns the length, or 0. */
size_t atalaia_tag_to_ndef_tag(const uint8_t *payload, size_t len, uint8_t *mem, size_t cap);

/*
 * The data of the nfc.tag input event a host gives the node when a tag is
 * read, as a JSON object:
 *
 *   {"uid":"04a1b2c3","valid":true,"player":"p-17","team":"blue"}
 *   {"uid":"04a1b2c3","valid":false,"reason":"mac"}
 *
 * payload is the tag's Atalaia record (NULL when it has none: reason
 * "unsigned"); game_key NULL means the node is not in a game with a key
 * (reason "no_game"). teams[0..team_count) are the game's team names (team
 * id i+1 is teams[i]); a valid tag with team 0 has no "team". Returns the
 * JSON length, or 0 if it does not fit in cap (ATALAIA_TAG_JSON_MAX always does).
 */
size_t atalaia_tag_event_json(const uint8_t *uid, size_t uid_len, const uint8_t *payload,
                              size_t len, uint16_t game_id, const uint8_t *game_key,
                              const char *const *teams, size_t team_count, char *json, size_t cap);

#endif /* ATALAIA_TAG_H */
