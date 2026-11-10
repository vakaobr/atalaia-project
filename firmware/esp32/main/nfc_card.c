/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * The USB console's NTAG writer (nfc_card.h). The page maps are NXP's NTAG213/215/216 datasheet's
 * (section 8.5, memory organisation):
 *
 *            pages  user pages  dynamic lock  CFG0, CFG1, PWD, PACK  CC byte 2  GET_VERSION byte 6
 *   NTAG213     45  4-39 (144)  40            41-44                  0x12       0x0F
 *   NTAG215    135  4-129 (504) 130           131-134                0x3E       0x11
 *   NTAG216    231  4-225 (888) 226           227-230                0x6D       0x13
 *
 * Pages 0-2 hold the UID, the internal byte and the static lock bytes, page 3 the capability
 * container (CC); none of these is ever written here, nor anything past the last user page.
 */
#include "nfc_card.h"

#include "hal/pn532.h"

#include <string.h>

typedef struct {
    const char *name;
    uint8_t cc_size;
    uint8_t version_size;
    uint8_t last_user_page;
    uint8_t dyn_lock_pages; /* pages one dynamic lock bit locks, from page 16 */
} ntag_t;

static const ntag_t NTAGS[] = {
    [NFC_T2_UNKNOWN] = {"unknown", 0, 0, 0, 0},
    [NFC_T2_NTAG213] = {"NTAG213", 0x12, 0x0F, 39, 2},
    [NFC_T2_NTAG215] = {"NTAG215", 0x3E, 0x11, 129, 16},
    [NFC_T2_NTAG216] = {"NTAG216", 0x6D, 0x13, 225, 16},
};
#define NTAG_KINDS (sizeof(NTAGS) / sizeof(NTAGS[0]))

const char *nfc_t2_kind_name(nfc_t2_kind_t kind)
{
    return (unsigned)kind < NTAG_KINDS ? NTAGS[kind].name : "unknown";
}

const char *nfc_card_result_name(nfc_card_result_t r)
{
    switch (r) {
    case NFC_CARD_OK: return "ok";
    case NFC_CARD_NO_READER: return "no NFC reader";
    case NFC_CARD_NO_TAG: return "no card (or it was taken away)";
    case NFC_CARD_UNKNOWN_TAG: return "not an NTAG213, NTAG215 or NTAG216";
    case NFC_CARD_EMPTY: return "nothing to write";
    case NFC_CARD_TOO_BIG: return "more than the card's user memory";
    case NFC_CARD_LOCKED: return "the card is locked (read-only)";
    case NFC_CARD_WRITE_FAILED: return "a page could not be written";
    case NFC_CARD_VERIFY_FAILED: return "what was read back differs";
    }
    return "?";
}

const char *nfc_card_result_code(nfc_card_result_t r)
{
    switch (r) {
    case NFC_CARD_OK: return "ok";
    case NFC_CARD_NO_READER: return "no_reader";
    case NFC_CARD_NO_TAG: return "no_card";
    case NFC_CARD_UNKNOWN_TAG: return "unknown_tag";
    case NFC_CARD_EMPTY: return "empty";
    case NFC_CARD_TOO_BIG: return "too_big";
    case NFC_CARD_LOCKED: return "locked";
    case NFC_CARD_WRITE_FAILED: return "write_failed";
    case NFC_CARD_VERIFY_FAILED: return "verify_failed";
    }
    return "?";
}

nfc_t2_kind_t nfc_card_kind_from_cc(const uint8_t cc[4])
{
    if (cc[0] != 0xE1) return NFC_T2_UNKNOWN; /* the NDEF magic number */
    for (unsigned k = 1; k < NTAG_KINDS; k++) {
        if (cc[2] == NTAGS[k].cc_size) return (nfc_t2_kind_t)k;
    }
    return NFC_T2_UNKNOWN;
}

nfc_t2_kind_t nfc_card_kind_from_version(const uint8_t v[8])
{
    /* Fixed header 00, vendor 04 (NXP), product type 04 (NTAG), ..., storage size, protocol 03. */
    if (v[0] != 0x00 || v[1] != 0x04 || v[2] != 0x04 || v[7] != 0x03) return NFC_T2_UNKNOWN;
    for (unsigned k = 1; k < NTAG_KINDS; k++) {
        if (v[6] == NTAGS[k].version_size) return (nfc_t2_kind_t)k;
    }
    return NFC_T2_UNKNOWN;
}

uint8_t nfc_card_last_user_page(nfc_t2_kind_t kind)
{
    return (unsigned)kind < NTAG_KINDS ? NTAGS[kind].last_user_page : 0;
}

nfc_card_result_t nfc_card_detect(const hal_nfc_ops_t *nfc, nfc_card_info_t *info)
{
    memset(info, 0, sizeof(*info));
    if (nfc == NULL || nfc->poll == NULL || nfc->t2_read == NULL || nfc->t2_write == NULL ||
        nfc->t2_get_version == NULL) {
        return NFC_CARD_NO_READER;
    }
    uint8_t b[16];
    if (nfc->t2_read(0, b) != 0) return NFC_CARD_NO_TAG; /* pages 0 to 3 */
    memcpy(info->static_lock, b + 10, 2);
    memcpy(info->cc, b + 12, 4);
    nfc_t2_kind_t by_cc = nfc_card_kind_from_cc(info->cc);
    nfc_t2_kind_t by_version = NFC_T2_UNKNOWN;
    uint8_t v[8];
    if (nfc->t2_get_version(v) == 0) {
        by_version = nfc_card_kind_from_version(v);
    } else {
        /* A tag without GET_VERSION answers NAK and goes idle: select it again. */
        hal_nfc_tag_t tag;
        if (!nfc->poll(&tag)) return NFC_CARD_NO_TAG;
    }
    info->cc_known = by_cc != NFC_T2_UNKNOWN;
    info->version_known = by_version != NFC_T2_UNKNOWN;
    nfc_t2_kind_t kind = by_cc != NFC_T2_UNKNOWN ? by_cc : by_version;
    if (info->cc_known && info->version_known && by_version != by_cc) {
        /* They disagree: the smaller, which never reaches the larger one's lock pages. */
        kind = NTAGS[by_cc].last_user_page < NTAGS[by_version].last_user_page ? by_cc : by_version;
    }
    if (kind == NFC_T2_UNKNOWN) return NFC_CARD_UNKNOWN_TAG;
    info->kind = kind;
    info->last_user_page = NTAGS[kind].last_user_page;
    /* The dynamic lock bytes, right after the user memory (read, never written). */
    if (nfc->t2_read((uint8_t)(info->last_user_page + 1), b) != 0) return NFC_CARD_NO_TAG;
    memcpy(info->dynamic_lock, b, 3);
    return NFC_CARD_OK;
}

/* Whether a lock bit covers user page p (NTAG21x datasheet 8.5.2 and 8.5.3). */
static bool page_locked(const nfc_card_info_t *info, unsigned p)
{
    if (p < 8) return (info->static_lock[0] >> p) & 1u;        /* L4-L7: lock byte 0 bits 4-7 */
    if (p < 16) return (info->static_lock[1] >> (p - 8)) & 1u; /* L8-L15: lock byte 1 */
    unsigned bit = (p - 16) / NTAGS[info->kind].dyn_lock_pages;
    if (bit >= 16) return false;
    return (info->dynamic_lock[bit / 8] >> (bit % 8)) & 1u;
}

nfc_card_result_t nfc_card_write(const hal_nfc_ops_t *nfc, const uint8_t *data, size_t len,
                                 nfc_card_info_t *info)
{
    memset(info, 0, sizeof(*info));
    if (len == 0) return NFC_CARD_EMPTY;
    if (len > NFC_CARD_MAX) return NFC_CARD_TOO_BIG;
    nfc_card_result_t r = nfc_card_detect(nfc, info);
    if (r != NFC_CARD_OK) return r;
    unsigned pages = (unsigned)((len + 3) / 4);
    unsigned last = NFC_CARD_FIRST_PAGE + pages - 1;
    if (last > info->last_user_page) return NFC_CARD_TOO_BIG;
    /* CC byte 3: write access 0x0 granted, 0xF none (an NDEF-formatted card only). */
    if (info->cc[0] == 0xE1 && (info->cc[3] & 0x0F) != 0) return NFC_CARD_LOCKED;
    for (unsigned p = NFC_CARD_FIRST_PAGE; p <= last; p++) {
        if (page_locked(info, p)) {
            info->failed_page = (uint8_t)p;
            return NFC_CARD_LOCKED;
        }
    }
    for (unsigned i = 0; i < pages; i++) {
        uint8_t page[4] = {0};
        size_t off = (size_t)i * 4;
        memcpy(page, data + off, len - off < 4 ? len - off : 4);
        uint8_t p = (uint8_t)(NFC_CARD_FIRST_PAGE + i);
        if (p < NFC_CARD_FIRST_PAGE || p > info->last_user_page) return NFC_CARD_TOO_BIG;
        if (nfc->t2_write(p, page) != 0) {
            info->failed_page = p;
            return NFC_CARD_WRITE_FAILED;
        }
        info->pages_written++;
    }
    for (unsigned p = NFC_CARD_FIRST_PAGE; p <= last; p += 4) {
        uint8_t b[16];
        if (nfc->t2_read((uint8_t)p, b) != 0) {
            info->failed_page = (uint8_t)p;
            return NFC_CARD_VERIFY_FAILED;
        }
        for (unsigned q = 0; q < 4 && p + q <= last; q++) {
            uint8_t want[4] = {0};
            size_t off = (size_t)(p + q - NFC_CARD_FIRST_PAGE) * 4;
            memcpy(want, data + off, len - off < 4 ? len - off : 4);
            if (memcmp(b + q * 4, want, 4) != 0) {
                info->failed_page = (uint8_t)(p + q);
                return NFC_CARD_VERIFY_FAILED;
            }
        }
    }
    return NFC_CARD_OK;
}

nfc_card_result_t nfc_card_read(const hal_nfc_ops_t *nfc, uint8_t *buf, size_t cap, bool all,
                                size_t *got, nfc_card_info_t *info)
{
    *got = 0;
    nfc_card_result_t r = nfc_card_detect(nfc, info);
    if (r != NFC_CARD_OK) return r;
    for (unsigned p = NFC_CARD_FIRST_PAGE; p <= info->last_user_page && *got < cap; p += 4) {
        uint8_t b[16];
        if (nfc->t2_read((uint8_t)p, b) != 0) return *got > 0 ? NFC_CARD_OK : NFC_CARD_NO_TAG;
        size_t take = (size_t)(info->last_user_page - p + 1) * 4;
        if (take > 16) take = 16;
        if (take > cap - *got) take = cap - *got;
        memcpy(buf + *got, b, take);
        *got += take;
        if (!all && t2_ndef_complete(buf, *got)) break;
    }
    return NFC_CARD_OK;
}

static int hex_digit(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

bool nfc_card_hex_append(const char *hex, uint8_t *out, size_t *len, size_t cap)
{
    size_t n = strlen(hex);
    if (n % 2 != 0 || *len + n / 2 > cap) return false;
    for (size_t i = 0; i < n; i++) {
        if (hex_digit(hex[i]) < 0) return false;
    }
    for (size_t i = 0; i < n; i += 2) {
        out[(*len)++] = (uint8_t)(hex_digit(hex[i]) << 4 | hex_digit(hex[i + 1]));
    }
    return true;
}
