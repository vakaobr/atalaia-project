/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * Writing and reading an NTAG213/215/216 card with the box's own PN532, from the USB console
 * ("@nfcwrite", "@nfcread"; tools/nfc_write.py sends them): the bench's and the workshop's way
 * to make a join card (protocol/join.md) or the field card (protocol/adoption.md) from the bytes
 * the GM console shows. An Android phone (the app's tag writer) stays the normal way.
 *
 * Only user memory is written: from page 4 to the last user page of the tag's size (NXP's NTAG
 * datasheet: NTAG213 pages 4-39, NTAG215 4-129, NTAG216 4-225), never the UID, static lock, CC,
 * dynamic lock or configuration pages. The size is read from the capability container (page 3,
 * byte 2) and from GET_VERSION (byte 6); when both answer and disagree the smaller is taken, and
 * a card neither names is refused. Every page written is read back.
 *
 * Platform-free (the hal_nfc_ops_t Type 2 primitives below it) so the host tests check it
 * against a fake PN532 holding a fake NTAG (test/test_pn532.c).
 */
#ifndef ATALAIA_NFC_CARD_H
#define ATALAIA_NFC_CARD_H

#include "hal/hal_nfc.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define NFC_CARD_FIRST_PAGE 4
#define NFC_CARD_MAX        888    /* NTAG216's user memory, the largest */
#define NFC_CARD_WAIT_MS    10000u /* how long "@nfcwrite" / "@nfcread" wait for a card */

typedef enum {
    NFC_T2_UNKNOWN = 0,
    NFC_T2_NTAG213,
    NFC_T2_NTAG215,
    NFC_T2_NTAG216,
} nfc_t2_kind_t;

typedef enum {
    NFC_CARD_OK = 0,
    NFC_CARD_NO_READER,    /* no PN532, or one without the Type 2 commands */
    NFC_CARD_NO_TAG,       /* no card answered, or it went away */
    NFC_CARD_UNKNOWN_TAG,  /* not an NTAG213/215/216 by its CC or GET_VERSION */
    NFC_CARD_EMPTY,        /* nothing to write */
    NFC_CARD_TOO_BIG,      /* more than the card's user memory */
    NFC_CARD_LOCKED,       /* the CC or a static lock bit says read-only */
    NFC_CARD_WRITE_FAILED, /* a page's WRITE failed (the card was taken away, or locked) */
    NFC_CARD_VERIFY_FAILED /* what was read back differs */
} nfc_card_result_t;

typedef struct {
    nfc_t2_kind_t kind;
    uint8_t last_user_page;  /* 39, 129 or 225 */
    uint8_t cc[4];           /* page 3 */
    uint8_t static_lock[2];  /* page 2 bytes 2 and 3 */
    uint8_t dynamic_lock[3]; /* the dynamic lock page's bytes 0 to 2 */
    bool cc_known;           /* the CC named a size */
    bool version_known;      /* GET_VERSION named a size */
    unsigned pages_written;  /* nfc_card_write: pages written (and checked when OK) */
    uint8_t failed_page;     /* NFC_CARD_WRITE_FAILED / VERIFY_FAILED: the page */
} nfc_card_info_t;

const char *nfc_t2_kind_name(nfc_t2_kind_t kind);
const char *nfc_card_result_name(nfc_card_result_t r);
/* One word for the "ATALAIA-NFC {json}" line tools/nfc_write.py reads: "ok", "no_card", ... */
const char *nfc_card_result_code(nfc_card_result_t r);

/* The kind a capability container's byte 2 (data area / 8) names, or NFC_T2_UNKNOWN. */
nfc_t2_kind_t nfc_card_kind_from_cc(const uint8_t cc[4]);
/* The kind a GET_VERSION answer names (NXP, NTAG, storage size byte 6), or NFC_T2_UNKNOWN. */
nfc_t2_kind_t nfc_card_kind_from_version(const uint8_t v[8]);
/* The last user page of a kind (0 for NFC_T2_UNKNOWN). */
uint8_t nfc_card_last_user_page(nfc_t2_kind_t kind);

/*
 * The card the last successful poll found: its size (CC, then GET_VERSION; a failed GET_VERSION
 * leaves the tag idle, so it is polled again), its CC and static lock bytes.
 */
nfc_card_result_t nfc_card_detect(const hal_nfc_ops_t *nfc, nfc_card_info_t *info);

/*
 * Writes data (the bytes from page 4: TLVs, the NDEF message, the terminator) to the polled
 * card, padded with zeros to whole pages, and reads every page back. info->pages_written says
 * how far it got.
 */
nfc_card_result_t nfc_card_write(const hal_nfc_ops_t *nfc, const uint8_t *data, size_t len,
                                 nfc_card_info_t *info);

/*
 * Reads the polled card's user memory from page 4 into buf: up to the end of the NDEF message
 * (all false) or the whole user memory (all true), at most cap bytes. *got is the length.
 */
nfc_card_result_t nfc_card_read(const hal_nfc_ops_t *nfc, uint8_t *buf, size_t cap, bool all,
                                size_t *got, nfc_card_info_t *info);

/*
 * Hex digits (upper or lower case, one word: tools/nfc_write.py takes out the spaces the GM console
 * shows) appended to out[*len..cap). Returns false, leaving *len as it was, for an odd digit
 * count, another character, or more than fits.
 */
bool nfc_card_hex_append(const char *hex, uint8_t *out, size_t *len, size_t cap);

#endif /* ATALAIA_NFC_CARD_H */
