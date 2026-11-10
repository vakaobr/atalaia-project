/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

#ifndef HAL_NFC_H
#define HAL_NFC_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef struct {
    uint8_t uid[10];
    uint8_t uid_len;
    uint8_t data[48];
    uint8_t data_len;
} hal_nfc_tag_t;

typedef struct {
    int (*init)(void);
    bool (*poll)(hal_nfc_tag_t *tag);
    /*
     * Reads the user memory (from page 4) of the NFC Forum Type 2 tag that
     * the last successful poll found (NTAG215/216), up to cap bytes, stopping
     * early once the NDEF message is complete. Returns the number of bytes
     * read, or -1 if no tag answers. Used for join cards (protocol/join.md).
     */
    int (*read_user_memory)(uint8_t *buf, size_t cap);
    /*
     * The NFC Forum Type 2 tag commands on the tag the last successful poll found, for the USB
     * console's card writer (nfc_card.h): READ (16 bytes: 4 pages from page), WRITE (one 4-byte
     * page) and GET_VERSION (8 bytes). 0 on success, -1 or less otherwise. NULL without a reader
     * that can (the host stub).
     */
    int (*t2_read)(uint8_t page, uint8_t out[16]);
    int (*t2_write)(uint8_t page, const uint8_t data[4]);
    int (*t2_get_version)(uint8_t out[8]);
    void (*deinit)(void);
} hal_nfc_ops_t;

#endif /* HAL_NFC_H */
