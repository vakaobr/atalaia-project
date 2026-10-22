/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * An in-memory epoch store for the host tests (radio_protocol.h's
 * read_legacy_epoch / read_epochs / write_epochs). A write replaces the blob
 * whole or, with write_fail (a power cut before the commit, a full flash),
 * leaves it as it was: the two outcomes NVS's set_blob allows.
 */
#ifndef ATALAIA_EPOCH_STORE_FAKE_H
#define ATALAIA_EPOCH_STORE_FAKE_H

#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "radio/radio_protocol.h"

typedef struct {
    uint8_t blob[ATALAIA_EPOCH_STORE_MAX + 16]; /* room for a too-long blob */
    int len;                                    /* 0: no blob yet */
    uint16_t legacy;                            /* the old firmware's single "epoch" */
    bool have_legacy;
    bool read_fails; /* read_epochs returns -2 */
    bool write_fail; /* write_epochs fails and changes nothing */
    int writes;      /* write_epochs calls */
} epoch_fake_t;

static inline int epoch_fake_read_legacy(void *ctx, uint16_t *e)
{
    epoch_fake_t *f = (epoch_fake_t *)ctx;
    if (!f->have_legacy) return -1;
    *e = f->legacy;
    return 0;
}

static inline int epoch_fake_read(void *ctx, uint8_t *buf, size_t cap)
{
    epoch_fake_t *f = (epoch_fake_t *)ctx;
    if (f->read_fails) return -2;
    if (f->len == 0) return -1;
    /* A blob longer than the buffer is an error, as NVS's ESP_ERR_NVS_INVALID_LENGTH. */
    if ((size_t)f->len > cap) return -2;
    memcpy(buf, f->blob, (size_t)f->len);
    return f->len;
}

static inline int epoch_fake_write(void *ctx, const uint8_t *buf, size_t len)
{
    epoch_fake_t *f = (epoch_fake_t *)ctx;
    f->writes++;
    if (f->write_fail || len > sizeof(f->blob)) return -1;
    memcpy(f->blob, buf, len);
    f->len = (int)len;
    return 0;
}

/* The epoch stored for a game key, or -1 if the store has no record for it. */
static inline int epoch_fake_of(const epoch_fake_t *f, const uint8_t key[16])
{
    uint8_t tag[ATALAIA_EPOCH_TAG_SIZE];
    atalaia_radio_epoch_tag(key, tag);
    if (f->len < 4) return -1;
    for (int i = 0; i < f->blob[1]; i++) {
        const uint8_t *r = f->blob + 4 + i * ATALAIA_EPOCH_REC_SIZE;
        if (memcmp(r, tag, sizeof(tag)) == 0) return r[8] << 8 | r[9];
    }
    return -1;
}

/* Ops for f (read_key/write_key/erase_key as given). */
#define EPOCH_FAKE_OPS(f, rk, wk, ek)                                                              \
    ((atalaia_radio_nvs_ops_t){.read_legacy_epoch = epoch_fake_read_legacy,                        \
                               .read_epochs = epoch_fake_read,                                     \
                               .write_epochs = epoch_fake_write,                                   \
                               .read_key = (rk),                                                   \
                               .write_key = (wk),                                                  \
                               .erase_key = (ek),                                                  \
                               .ctx = (f)})

#endif /* ATALAIA_EPOCH_STORE_FAKE_H */
