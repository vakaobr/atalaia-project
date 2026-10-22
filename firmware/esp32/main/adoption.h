/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Adoption (protocol/adoption.md): how a box gets its field's join key.
 *
 * A box is unadopted (no stored join key; a development key does not count)
 * or adopted to one field, known by the key's fingerprint and the field's
 * name. Two ways are built (decision AD-1):
 *
 *   - an NFC field card (MIME type application/vnd.atalaia.field: version,
 *     the field's name, the join key, an 8-byte check) tapped on the reader;
 *   - "@adopt <64 hex> [<admin PIN>|-] [<field name>]" on the serial console,
 *     which the field controller types over the USB cable after "@adopt-info".
 *
 * An unadopted box takes the first field that offers itself. An adopted box
 * takes the same field again (the name may change) and another field's key
 * only with its admin PIN: typed on the keypad after the card, or given in
 * "@adopt"; the PIN is checked by admin_pin.h, whose failure count survives
 * a restart (after five wrong PINs in a row each try waits 1, 2, 4 ... 60
 * minutes, decision AD-28), and a Field Box with no admin PIN set moves to
 * no other field. Nothing is adopted while a field game is joined.
 * "@joinkey <64 hex>" follows the same rules without a PIN.
 *
 * Replies on the console are one line, "ATALAIA-ADOPT {json}", which the
 * controller reads. Platform-free: the shell gives the storage, the screen
 * and the log; the host tests and the host box run it as the box does.
 */
#ifndef ATALAIA_ADOPTION_H
#define ATALAIA_ADOPTION_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "admin_pin.h"

#define ADOPTION_KEY_SIZE     32
#define ADOPTION_NAME_MAX     48 /* bytes of UTF-8 */
#define ADOPTION_CHECK_SIZE   8
#define ADOPTION_CARD_MIN     (2 + ADOPTION_KEY_SIZE + ADOPTION_CHECK_SIZE)
#define ADOPTION_CARD_MAX     (ADOPTION_CARD_MIN + ADOPTION_NAME_MAX)
#define ADOPTION_NDEF_TYPE    "application/vnd.atalaia.field"
#define ADOPTION_FP_SIZE      10 /* "XXXX-XXXX" and the NUL */
#define ADOPTION_PIN_MAX      ADMIN_PIN_MAX
#define ADOPTION_PIN_TRIES    ADMIN_PIN_FREE_TRIES /* wrong PINs in a row before the waits */
#define ADOPTION_PIN_WAIT_MS  60000                /* a card waits this long for its PIN */
#define ADOPTION_SCREEN_MS    4000                 /* a result stays on the screen this long */
#define ADOPTION_REPLY_PREFIX "ATALAIA-ADOPT "
#define ADOPTION_REPLY_MAX    512

/* ---- the field card ------------------------------------------------------ */

typedef struct {
    uint8_t key[ADOPTION_KEY_SIZE];
    char name[ADOPTION_NAME_MAX + 1];
} adoption_card_t;

typedef enum {
    ADOPTION_CARD_OK = 0,
    ADOPTION_CARD_LENGTH,  /* not 42-90 bytes, or the name's length does not match */
    ADOPTION_CARD_VERSION, /* not version 1 */
    ADOPTION_CARD_NAME,    /* the name is not clean UTF-8 */
    ADOPTION_CARD_CHECK,   /* the check does not match: written wrong or damaged */
} adoption_card_result_t;

/* "ok", "length", "version", "name", "check" (the vectors' reasons). */
const char *adoption_card_result_name(adoption_card_result_t r);

adoption_card_result_t adoption_card_decode(const uint8_t *data, size_t len, adoption_card_t *out);
/* The card's payload; 0 if the name is not allowed or it does not fit in cap. */
size_t adoption_card_encode(const adoption_card_t *card, uint8_t *buf, size_t cap);
/* The field card's payload in a Type 2 tag's memory (page 4 on), or 0. */
size_t adoption_card_from_ndef_tag(const uint8_t *mem, size_t len, const uint8_t **payload);

/* 0-48 bytes of UTF-8 (shortest forms, no surrogates), no control character, '"' or '\'. */
bool adoption_name_ok(const char *name, size_t len);

/* The field's fingerprint: HMAC-SHA256(key, "atalaia-field-fingerprint")[:4] as "XXXX-XXXX". */
void adoption_fingerprint(const uint8_t key[ADOPTION_KEY_SIZE], char out[ADOPTION_FP_SIZE]);

/* ---- the box's adoption state ------------------------------------------- */

typedef enum {
    ADOPT_ADOPTED = 0, /* was unadopted, now adopted */
    ADOPT_SAME,        /* already this field's (the name updated) */
    ADOPT_READOPTED,   /* moved from another field, with the admin PIN */
    ADOPT_NEED_PIN,    /* adopted to another field: the admin PIN is needed */
    ADOPT_BAD_PIN,
    ADOPT_LOCKED,   /* too many wrong PINs: a wait runs (admin_pin.h) */
    ADOPT_BUSY,     /* a field game is joined */
    ADOPT_BAD_KEY,  /* not 64 hex digits, or a name that is not allowed */
    ADOPT_BAD_CARD, /* a field card that does not decode */
    ADOPT_STORE_FAILED,
    ADOPT_NO_PIN, /* adopted to another field, and no admin PIN is set on this box */
} adopt_result_t;

/* "adopted", "same", "readopted", "need_pin", "bad_pin", "locked", "busy",
 * "bad_key", "bad_card", "store_failed", "no_pin". */
const char *adopt_result_name(adopt_result_t r);
static inline bool adopt_result_ok(adopt_result_t r)
{
    return r == ADOPT_ADOPTED || r == ADOPT_SAME || r == ADOPT_READOPTED;
}

typedef struct {
    /* True while a field game is joined: nothing is adopted then. */
    bool (*busy)(void *ctx);
    /* Store the join key and the field's name (NVS); true if both are stored. */
    bool (*store)(void *ctx, const uint8_t key[ADOPTION_KEY_SIZE], const char *name);
    void (*screen)(void *ctx, const char *tmpl, const char *data_json);
    void (*log)(void *ctx, const char *line);
    void *ctx;
} adoption_ops_t;

/* Who the box is, for "@adopt-info". */
typedef struct {
    const char *name; /* the box's node name */
    const char *mac;  /* "AA:BB:CC:DD:EE:FF" (the USB serial number on a Heltec V4) */
    const char *fw;   /* the firmware's version */
} adoption_identity_t;

typedef struct {
    adoption_ops_t ops;
    admin_pin_t *pin;    /* the admin PIN's check: the shell's (shared with the picker) */
    admin_pin_t own_pin; /* adoption_init's, in RAM, until adoption_set_pin */
    bool adopted;
    uint8_t key[ADOPTION_KEY_SIZE];
    char name[ADOPTION_NAME_MAX + 1];
    char fingerprint[ADOPTION_FP_SIZE];
    /* Another field's card, waiting for the admin PIN on the keypad. */
    bool pending;
    adoption_card_t pending_card;
    uint32_t pending_since_ms;
    char typed[ADOPTION_PIN_MAX + 1];
    uint8_t typed_len;
    /* A result on the screen until overlay_until_ms. */
    bool overlay;
    uint32_t overlay_until_ms;
} adoption_t;

/* admin_pin: checked in RAM only (host tests); a box gives its shared check with
 * adoption_set_pin, whose count is in NVS. */
void adoption_init(adoption_t *a, const adoption_ops_t *ops, const char *admin_pin);
void adoption_set_pin(adoption_t *a, admin_pin_t *pin);
/* At boot, the key and name stored in NVS (a development key is not given here). */
void adoption_restore(adoption_t *a, const uint8_t key[ADOPTION_KEY_SIZE], const char *name);

/*
 * Offers a field: key, its name ("" keeps the name a box adopted to the same
 * field already has) and the admin PIN (NULL: none given). Stores it when the
 * rules allow and returns what happened.
 */
adopt_result_t adoption_offer(adoption_t *a, const uint8_t key[ADOPTION_KEY_SIZE], const char *name,
                              const char *pin);

/*
 * A tag read by the NFC reader (its memory from page 4). Returns false if it
 * holds no field card (the shell handles it as before). Otherwise it is
 * offered (no PIN), its result shown and logged, *result set; another
 * field's card then waits for the admin PIN on the keypad.
 */
bool adoption_tap(adoption_t *a, const uint8_t *mem, size_t len, uint32_t now_ms,
                  adopt_result_t *result);

/* Logs and shows the result of an offer made another way (the pairing code: via "radio"). */
void adoption_report(adoption_t *a, const char *via, adopt_result_t r, uint32_t now_ms);

/* True while a card waits for its PIN or a result is on the screen: keys go to adoption_key. */
bool adoption_active(const adoption_t *a);
/* A keypad key: digits, '*' deletes (cancels when empty), '#' enters the PIN; any key
 * closes a result screen. Returns true if the key was used. */
bool adoption_key(adoption_t *a, char key, uint32_t now_ms);
/* Timeouts. Returns true once when adoption leaves the screen (the shell redraws its own). */
bool adoption_tick(adoption_t *a, uint32_t now_ms);

/*
 * A console command line (without the '@'): "adopt-info", "adopt ...", "joinkey ...".
 * Returns false if it is none of them. Otherwise *reply holds the line to print
 * (NUL-terminated, at most ADOPTION_REPLY_MAX bytes with the prefix).
 */
bool adoption_command(adoption_t *a, const char *cmd, const adoption_identity_t *id,
                      uint32_t now_ms, char *reply, size_t cap);

#endif /* ATALAIA_ADOPTION_H */
