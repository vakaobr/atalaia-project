/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

#ifndef HAL_NFC_H
#define HAL_NFC_H

#include <stdbool.h>
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
    void (*deinit)(void);
} hal_nfc_ops_t;

#endif /* HAL_NFC_H */
