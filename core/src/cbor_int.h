/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Internal CBOR encode/decode helpers shared by the message codecs.
 * This header is internal to core/src/ and is not part of the public API.
 */
#ifndef ATALAIA_CBOR_INT_H
#define ATALAIA_CBOR_INT_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

/* ---- CBOR major types ----------------------------------------------------- */

enum {
    CBOR_MAJOR_UINT = 0,
    CBOR_MAJOR_NINT = 1,
    CBOR_MAJOR_BYTES = 2,
    CBOR_MAJOR_TEXT = 3,
    CBOR_MAJOR_ARRAY = 4,
    CBOR_MAJOR_MAP = 5,
    CBOR_MAJOR_TAG = 6,
    CBOR_MAJOR_SIMPLE = 7
};

/* ---- CBOR output helpers -------------------------------------------------- */

typedef struct {
    uint8_t *buf;
    size_t cap;
    size_t pos;
    bool ok;
} mc_writer_t;

static inline void mc_init_writer(mc_writer_t *w, uint8_t *buf, size_t cap)
{
    w->buf = buf;
    w->cap = cap;
    w->pos = 0;
    w->ok = true;
}

static inline size_t mc_head_len(uint64_t v)
{
    if (v < 24) return 1;
    if (v <= 0xFF) return 2;
    if (v <= 0xFFFF) return 3;
    if (v <= 0xFFFFFFFFu) return 5;
    return 9;
}

static inline void mc_write_head(uint8_t *p, unsigned major, uint64_t v)
{
    size_t n = mc_head_len(v);
    static const uint8_t ai[] = {0, 0, 24, 25, 0, 26, 0, 0, 0, 27};
    p[0] = (uint8_t)(major << 5 | (n == 1 ? (unsigned)v : ai[n]));
    for (size_t i = 1; i < n; i++) {
        p[i] = (uint8_t)(v >> (8 * (n - 1 - i)));
    }
}

static inline void mc_put_head(mc_writer_t *w, unsigned major, uint64_t v)
{
    size_t n = mc_head_len(v);
    if (n > w->cap - w->pos) {
        w->ok = false;
        return;
    }
    mc_write_head(w->buf + w->pos, major, v);
    w->pos += n;
}

static inline void mc_put_int(mc_writer_t *w, int64_t v)
{
    if (v >= 0) {
        mc_put_head(w, CBOR_MAJOR_UINT, (uint64_t)v);
    } else {
        mc_put_head(w, CBOR_MAJOR_NINT, (uint64_t)(-(v + 1)));
    }
}

static inline void mc_put_uint(mc_writer_t *w, uint64_t v)
{
    mc_put_head(w, CBOR_MAJOR_UINT, v);
}

static inline void mc_put_text(mc_writer_t *w, const char *s)
{
    size_t len = strlen(s);
    mc_put_head(w, CBOR_MAJOR_TEXT, len);
    if (len > w->cap - w->pos) {
        w->ok = false;
        return;
    }
    memcpy(w->buf + w->pos, s, len);
    w->pos += len;
}

static inline void mc_put_bytes(mc_writer_t *w, const uint8_t *data, size_t len)
{
    mc_put_head(w, CBOR_MAJOR_BYTES, len);
    if (len > w->cap - w->pos) {
        w->ok = false;
        return;
    }
    memcpy(w->buf + w->pos, data, len);
    w->pos += len;
}

static inline void mc_put_map(mc_writer_t *w, uint64_t count)
{
    mc_put_head(w, CBOR_MAJOR_MAP, count);
}

static inline void mc_put_array(mc_writer_t *w, uint64_t count)
{
    mc_put_head(w, CBOR_MAJOR_ARRAY, count);
}

/* ---- CBOR input helpers --------------------------------------------------- */

typedef struct {
    const uint8_t *p;
    const uint8_t *end;
    bool ok;
} mc_reader_t;

static inline void mc_init_reader(mc_reader_t *r, const uint8_t *buf, size_t len)
{
    r->p = buf;
    r->end = buf + len;
    r->ok = true;
}

static inline size_t mc_remaining(const mc_reader_t *r)
{
    return (size_t)(r->end - r->p);
}

static inline bool mc_read_head(mc_reader_t *r, unsigned *major, uint64_t *value)
{
    if (mc_remaining(r) < 1) {
        r->ok = false;
        return false;
    }
    uint8_t initial = *r->p++;
    *major = initial >> 5;
    unsigned ai = initial & 0x1F;
    if (ai < 24) {
        *value = ai;
        return true;
    }
    if (ai > 27) {
        r->ok = false;
        return false;
    }
    size_t n = (size_t)1 << (ai - 24);
    if (mc_remaining(r) < n) {
        r->ok = false;
        return false;
    }
    uint64_t v = 0;
    for (size_t i = 0; i < n; i++) {
        v = v << 8 | *r->p++;
    }
    *value = v;
    return true;
}

static inline bool mc_read_uint(mc_reader_t *r, uint64_t *out)
{
    unsigned major;
    uint64_t v;
    if (!mc_read_head(r, &major, &v) || major != CBOR_MAJOR_UINT) {
        r->ok = false;
        return false;
    }
    *out = v;
    return true;
}

static inline bool mc_read_int(mc_reader_t *r, int64_t *out)
{
    unsigned major;
    uint64_t v;
    if (!mc_read_head(r, &major, &v)) {
        return false;
    }
    if (major == CBOR_MAJOR_UINT) {
        if (v > INT64_MAX) {
            r->ok = false;
            return false;
        }
        *out = (int64_t)v;
        return true;
    }
    if (major == CBOR_MAJOR_NINT) {
        if (v > (uint64_t)INT64_MAX) {
            r->ok = false;
            return false;
        }
        *out = -1 - (int64_t)v;
        return true;
    }
    r->ok = false;
    return false;
}

static inline bool mc_read_text(mc_reader_t *r, char *out, size_t out_cap, size_t *out_len)
{
    unsigned major;
    uint64_t len;
    if (!mc_read_head(r, &major, &len) || major != CBOR_MAJOR_TEXT) {
        r->ok = false;
        return false;
    }
    if (len >= out_cap || len > mc_remaining(r)) {
        r->ok = false;
        return false;
    }
    memcpy(out, r->p, (size_t)len);
    out[(size_t)len] = '\0';
    r->p += (size_t)len;
    if (out_len != NULL) {
        *out_len = (size_t)len;
    }
    return true;
}

static inline bool mc_read_bytes(mc_reader_t *r, uint8_t *out, size_t out_cap, size_t *out_len)
{
    unsigned major;
    uint64_t len;
    if (!mc_read_head(r, &major, &len) || major != CBOR_MAJOR_BYTES) {
        r->ok = false;
        return false;
    }
    if (len > out_cap || len > mc_remaining(r)) {
        r->ok = false;
        return false;
    }
    memcpy(out, r->p, (size_t)len);
    r->p += (size_t)len;
    if (out_len != NULL) {
        *out_len = (size_t)len;
    }
    return true;
}

static inline bool mc_read_map(mc_reader_t *r, uint64_t *count)
{
    unsigned major;
    if (!mc_read_head(r, &major, count) || major != CBOR_MAJOR_MAP) {
        r->ok = false;
        return false;
    }
    return true;
}

static inline bool mc_read_array(mc_reader_t *r, uint64_t *count)
{
    unsigned major;
    if (!mc_read_head(r, &major, count) || major != CBOR_MAJOR_ARRAY) {
        r->ok = false;
        return false;
    }
    return true;
}

/*
 * How deep a skipped value may nest (arrays and maps inside arrays and maps). The message codecs
 * read values two or three levels deep; a peer's unknown field gets this many and no more, so a
 * packet of nothing but 0x81 bytes cannot recurse the C stack away (review finding FLD-8).
 */
#define MC_SKIP_MAX_DEPTH 16

static inline bool mc_skip_value_at(mc_reader_t *r, unsigned depth)
{
    unsigned major;
    uint64_t v;
    if (!mc_read_head(r, &major, &v)) {
        return false;
    }
    switch (major) {
    case CBOR_MAJOR_UINT:
    case CBOR_MAJOR_NINT:
    case CBOR_MAJOR_SIMPLE: return true;
    case CBOR_MAJOR_BYTES:
    case CBOR_MAJOR_TEXT:
        if (v > mc_remaining(r)) {
            r->ok = false;
            return false;
        }
        r->p += (size_t)v;
        return true;
    case CBOR_MAJOR_ARRAY:
    case CBOR_MAJOR_MAP: {
        if (depth >= MC_SKIP_MAX_DEPTH) {
            r->ok = false;
            return false;
        }
        /* Every item takes at least one byte: a count beyond what is left cannot be met. */
        if (v > mc_remaining(r)) {
            r->ok = false;
            return false;
        }
        uint64_t items = major == CBOR_MAJOR_MAP ? v * 2 : v;
        for (uint64_t i = 0; i < items; i++) {
            if (!mc_skip_value_at(r, depth + 1)) return false;
        }
        return true;
    }
    default: r->ok = false; return false;
    }
}

/* Skip one CBOR value (used for unknown keys). */
static inline bool mc_skip_value(mc_reader_t *r)
{
    return mc_skip_value_at(r, 0);
}

#endif /* ATALAIA_CBOR_INT_H */
