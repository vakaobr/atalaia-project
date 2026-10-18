/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * USB radio modem framing: encoder and a resynchronising decoder.
 */
#include "modem_framing.h"

#include <string.h>

uint16_t modem_crc16(const uint8_t *data, size_t len)
{
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < len; i++) {
        crc ^= (uint16_t)((uint16_t)data[i] << 8);
        for (int bit = 0; bit < 8; bit++) {
            if (crc & 0x8000) {
                crc = (uint16_t)((crc << 1) ^ 0x1021);
            } else {
                crc = (uint16_t)(crc << 1);
            }
        }
    }
    return crc;
}

size_t modem_frame_encode(uint8_t type, const uint8_t *payload, size_t len, uint8_t *out,
                          size_t cap)
{
    if (len > MODEM_FRAME_PAYLOAD_MAX || cap < len + MODEM_FRAME_OVERHEAD) {
        return 0;
    }
    if (len > 0 && payload == NULL) {
        return 0;
    }
    out[0] = MODEM_SYNC;
    out[1] = type;
    out[2] = (uint8_t)(len >> 8);
    out[3] = (uint8_t)(len & 0xFF);
    if (len > 0) {
        memcpy(out + MODEM_FRAME_HEAD, payload, len);
    }
    uint16_t crc = modem_crc16(out + 1, len + 3);
    out[MODEM_FRAME_HEAD + len] = (uint8_t)(crc >> 8);
    out[MODEM_FRAME_HEAD + len + 1] = (uint8_t)(crc & 0xFF);
    return len + MODEM_FRAME_OVERHEAD;
}

void modem_decoder_init(modem_decoder_t *d)
{
    memset(d, 0, sizeof(*d));
}

/* Removes the first n bytes of the raw buffer. */
static void drop(modem_decoder_t *d, size_t n)
{
    if (n >= d->raw_len) {
        d->raw_len = 0;
        return;
    }
    memmove(d->raw, d->raw + n, d->raw_len - n);
    d->raw_len -= n;
}

/*
 * Delivers every complete frame at the start of the buffer. On a bad
 * length or CRC, only the sync byte is dropped, so a real frame that
 * starts inside the rejected bytes is still found.
 */
static void parse(modem_decoder_t *d, modem_frame_cb cb, void *ctx)
{
    for (;;) {
        size_t skip = 0;
        while (skip < d->raw_len && d->raw[skip] != MODEM_SYNC) {
            skip++;
        }
        if (skip > 0) {
            d->dropped_bytes += (uint32_t)skip;
            drop(d, skip);
        }
        if (d->raw_len < MODEM_FRAME_HEAD) {
            return;
        }
        size_t len = ((size_t)d->raw[2] << 8) | d->raw[3];
        if (len > MODEM_FRAME_PAYLOAD_MAX) {
            d->length_errors++;
            d->dropped_bytes++;
            drop(d, 1);
            continue;
        }
        size_t total = len + MODEM_FRAME_OVERHEAD;
        if (d->raw_len < total) {
            return;
        }
        uint16_t want = (uint16_t)(((uint16_t)d->raw[MODEM_FRAME_HEAD + len] << 8) |
                                   d->raw[MODEM_FRAME_HEAD + len + 1]);
        if (modem_crc16(d->raw + 1, len + 3) != want) {
            d->crc_errors++;
            d->dropped_bytes++;
            drop(d, 1);
            continue;
        }
        d->frames++;
        if (cb != NULL) {
            cb(ctx, d->raw[1], d->raw + MODEM_FRAME_HEAD, len);
        }
        drop(d, total);
    }
}

void modem_decoder_feed(modem_decoder_t *d, const uint8_t *data, size_t len, modem_frame_cb cb,
                        void *ctx)
{
    for (size_t i = 0; i < len; i++) {
        /* The buffer holds at most one frame; parse() always leaves room
         * because it drops or delivers as soon as a frame is complete. */
        if (d->raw_len == sizeof(d->raw)) {
            d->dropped_bytes++;
            drop(d, 1);
        }
        d->raw[d->raw_len++] = data[i];
        parse(d, cb, ctx);
    }
}
