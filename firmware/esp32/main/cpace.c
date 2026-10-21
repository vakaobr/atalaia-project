/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * CPace on X25519 with SHA-512 (cpace.h), on Monocypher.
 */
#include "cpace.h"

#include <string.h>

#include "monocypher-ed25519.h"
#include "monocypher.h"

#define S_IN_BYTES 128 /* SHA-512's input block */

static const char DSI[] = "CPace255";
static const char DSI_ISK[] = "CPace255_ISK";

/* prepend_len for lengths below 128 (one LEB128 byte): every input here is shorter. */
static size_t put_lv(uint8_t *out, size_t at, size_t cap, const uint8_t *data, size_t len)
{
    if (len >= 128 || at + 1 + len > cap) return 0;
    out[at] = (uint8_t)len;
    if (len) memcpy(out + at + 1, data, len);
    return at + 1 + len;
}

size_t cpace_generator_string(const uint8_t *prs, size_t prs_len, const uint8_t *ci, size_t ci_len,
                              const uint8_t *sid, size_t sid_len, uint8_t *out, size_t cap)
{
    if (prs_len >= 128 || ci_len >= 128 || sid_len >= 128) return 0;
    const size_t dsi_len = sizeof(DSI) - 1;
    /* ZPAD so that the first block holds DSI, PRS and the padding's own length byte. */
    size_t used = (1 + prs_len) + (1 + dsi_len) + 1;
    size_t zpad = used < S_IN_BYTES ? S_IN_BYTES - used : 0;
    static const uint8_t zeros[S_IN_BYTES] = {0};
    size_t at = 0;
    if ((at = put_lv(out, at, cap, (const uint8_t *)DSI, dsi_len)) == 0) return 0;
    if ((at = put_lv(out, at, cap, prs, prs_len)) == 0) return 0;
    if ((at = put_lv(out, at, cap, zeros, zpad)) == 0) return 0;
    if ((at = put_lv(out, at, cap, ci, ci_len)) == 0) return 0;
    if ((at = put_lv(out, at, cap, sid, sid_len)) == 0) return 0;
    return at;
}

/* p = 2^255 - 19, little-endian. */
static const uint8_t P[32] = {0xed, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
                              0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
                              0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0x7f};

/* a >= b, little-endian 32-byte numbers. */
static bool ge(const uint8_t a[32], const uint8_t b[32])
{
    for (int i = 31; i >= 0; i--) {
        if (a[i] != b[i]) return a[i] > b[i];
    }
    return true;
}

/* out = a - b (a >= b). */
static void sub(uint8_t out[32], const uint8_t a[32], const uint8_t b[32])
{
    int borrow = 0;
    for (int i = 0; i < 32; i++) {
        int d = (int)a[i] - (int)b[i] - borrow;
        borrow = d < 0;
        out[i] = (uint8_t)(d + (borrow ? 256 : 0));
    }
}

bool cpace_generator(const uint8_t *prs, size_t prs_len, const uint8_t *ci, size_t ci_len,
                     const uint8_t *sid, size_t sid_len, uint8_t g[CPACE_POINT_SIZE])
{
    uint8_t gs[CPACE_GS_MAX];
    size_t n = cpace_generator_string(prs, prs_len, ci, ci_len, sid, sid_len, gs, sizeof(gs));
    if (n == 0) return false;
    uint8_t h[64];
    crypto_sha512(h, gs, n);
    /* decodeUCoordinate: 255 bits, reduced modulo p. */
    uint8_t r[32];
    memcpy(r, h, 32);
    r[31] &= 0x7f;
    if (ge(r, P)) sub(r, r, P);
    /* Monocypher's map reads 254 bits; it depends only on r^2, so give it min(r, p - r),
     * which is always below 2^254 (decision AD-10). */
    if (r[31] & 0x40) sub(r, P, r);
    crypto_elligator_map(g, r);
    crypto_wipe(h, sizeof(h));
    crypto_wipe(r, sizeof(r));
    crypto_wipe(gs, sizeof(gs));
    return true;
}

void cpace_scalar_mult(const uint8_t scalar[32], const uint8_t u[CPACE_POINT_SIZE],
                       uint8_t out[CPACE_POINT_SIZE])
{
    crypto_x25519(out, scalar, u);
}

bool cpace_scalar_mult_vfy(const uint8_t scalar[32], const uint8_t u[CPACE_POINT_SIZE],
                           uint8_t out[CPACE_POINT_SIZE])
{
    crypto_x25519(out, scalar, u);
    uint8_t d = 0;
    for (size_t i = 0; i < CPACE_POINT_SIZE; i++) d |= out[i];
    return d != 0;
}

static void lv(crypto_sha512_ctx *ctx, const uint8_t *data, size_t len)
{
    uint8_t n = (uint8_t)len; /* every input here is shorter than 128 bytes */
    crypto_sha512_update(ctx, &n, 1);
    if (len) crypto_sha512_update(ctx, data, len);
}

void cpace_isk_ir(const uint8_t *sid, size_t sid_len, const uint8_t k[CPACE_POINT_SIZE],
                  const uint8_t ya[CPACE_POINT_SIZE], const uint8_t *ada, size_t ada_len,
                  const uint8_t yb[CPACE_POINT_SIZE], const uint8_t *adb, size_t adb_len,
                  uint8_t isk[CPACE_ISK_SIZE])
{
    crypto_sha512_ctx ctx;
    crypto_sha512_init(&ctx);
    lv(&ctx, (const uint8_t *)DSI_ISK, sizeof(DSI_ISK) - 1);
    lv(&ctx, sid, sid_len);
    lv(&ctx, k, CPACE_POINT_SIZE);
    lv(&ctx, ya, CPACE_POINT_SIZE);
    lv(&ctx, ada, ada_len);
    lv(&ctx, yb, CPACE_POINT_SIZE);
    lv(&ctx, adb, adb_len);
    crypto_sha512_final(&ctx, isk);
}
