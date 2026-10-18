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
    void (*deinit)(void);
} hal_nfc_ops_t;

#endif /* HAL_NFC_H */
