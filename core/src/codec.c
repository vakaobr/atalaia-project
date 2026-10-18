/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The event codec: JSON event data to CBOR and back, driven by the tables
 * generated from protocol/schema (protocol.c). Encoders write integers,
 * lengths and floats in their shortest form and keep map entries in input
 * order. The decoder accepts only that subset of CBOR; see codec.h.
 */
#include <errno.h>
#include <float.h>
#include <inttypes.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "atalaia/codec.h"
#include "atalaia/protocol.h"

/* Containers nested at once: the envelope plus the data. */
#define MAX_NESTING (ATALAIA_CODEC_MAX_DEPTH + 1)
#define NUMBER_MAX  64

enum {
    MAJOR_UINT = 0,
    MAJOR_NINT = 1,
    MAJOR_BYTES = 2,
    MAJOR_TEXT = 3,
    MAJOR_ARRAY = 4,
    MAJOR_MAP = 5,
    MAJOR_TAG = 6,
    MAJOR_SIMPLE = 7
};

/* ---- shared helpers ------------------------------------------------------ */

/* An output buffer. Fails once and keeps the first error. */
typedef struct {
    uint8_t *buf;
    size_t cap;
    size_t pos;
    const char *error;
} writer_t;

/* Keys of the open maps, as byte ranges of the output, to catch duplicates. */
typedef struct {
    uint16_t off[ATALAIA_CODEC_MAX_KEYS];
    uint16_t len[ATALAIA_CODEC_MAX_KEYS];
    size_t count;
} keyset_t;

static bool fail(writer_t *w, const char *message)
{
    if (w->error == NULL) {
        w->error = message;
    }
    return false;
}

static bool put(writer_t *w, const void *src, size_t n)
{
    if (n > w->cap - w->pos) {
        return fail(w, "does not fit");
    }
    memcpy(w->buf + w->pos, src, n);
    w->pos += n;
    return true;
}

static bool put_str(writer_t *w, const char *s)
{
    return put(w, s, strlen(s));
}

/*
 * Records the key at buf[off, off + len) for the innermost open map, whose
 * keys start at index first. Fails if that map already has the same key.
 */
static bool add_key(writer_t *w, keyset_t *ks, size_t first, size_t off, size_t len)
{
    for (size_t i = first; i < ks->count; i++) {
        if (ks->len[i] == len && memcmp(w->buf + ks->off[i], w->buf + off, len) == 0) {
            return fail(w, "duplicate key");
        }
    }
    if (ks->count == ATALAIA_CODEC_MAX_KEYS) {
        return fail(w, "too many keys in nested data");
    }
    ks->off[ks->count] = (uint16_t)off;
    ks->len[ks->count] = (uint16_t)len;
    ks->count++;
    return true;
}

/* Length of the valid UTF-8 sequence at s (n bytes available), or 0. */
static size_t utf8_len(const uint8_t *s, size_t n)
{
    uint8_t c = s[0];
    size_t len;
    if (c < 0x80) {
        return 1;
    } else if (c < 0xC2) {
        return 0; /* continuation byte or overlong two-byte form */
    } else if (c < 0xE0) {
        len = 2;
    } else if (c < 0xF0) {
        len = 3;
    } else if (c < 0xF5) {
        len = 4;
    } else {
        return 0;
    }
    if (n < len) {
        return 0;
    }
    for (size_t i = 1; i < len; i++) {
        if ((s[i] & 0xC0) != 0x80) {
            return 0;
        }
    }
    if ((c == 0xE0 && s[1] < 0xA0) || (c == 0xF0 && s[1] < 0x90)) {
        return 0; /* overlong */
    }
    if (c == 0xED && s[1] > 0x9F) {
        return 0; /* UTF-16 surrogate */
    }
    if (c == 0xF4 && s[1] > 0x8F) {
        return 0; /* above U+10FFFF */
    }
    return len;
}

static bool printable_ascii(const char *s, size_t len)
{
    for (size_t i = 0; i < len; i++) {
        if (s[i] < 0x21 || s[i] > 0x7E) {
            return false;
        }
    }
    return true;
}

/* ---- CBOR output --------------------------------------------------------- */

static size_t head_len(uint64_t v)
{
    return v < 24 ? 1 : v <= 0xFF ? 2 : v <= 0xFFFF ? 3 : v <= 0xFFFFFFFFu ? 5 : 9;
}

static void write_head(uint8_t *p, unsigned major, uint64_t v)
{
    size_t n = head_len(v);
    static const uint8_t ai[] = {0, 0, 24, 25, 0, 26, 0, 0, 0, 27};
    p[0] = (uint8_t)(major << 5 | (n == 1 ? (unsigned)v : ai[n]));
    for (size_t i = 1; i < n; i++) {
        p[i] = (uint8_t)(v >> (8 * (n - 1 - i)));
    }
}

static bool put_head(writer_t *w, unsigned major, uint64_t v)
{
    size_t n = head_len(v);
    if (n > w->cap - w->pos) {
        return fail(w, "does not fit");
    }
    write_head(w->buf + w->pos, major, v);
    w->pos += n;
    return true;
}

/*
 * Containers and text are written after a one-byte placeholder at start,
 * since their length is only known at the end. This writes the real head
 * there, moving the content up if the head needs more than one byte.
 */
static bool fix_head(writer_t *w, size_t start, unsigned major, uint64_t count)
{
    size_t n = head_len(count);
    if (n > 1) {
        if (n - 1 > w->cap - w->pos) {
            return fail(w, "does not fit");
        }
        memmove(w->buf + start + n, w->buf + start + 1, w->pos - start - 1);
        w->pos += n - 1;
    }
    write_head(w->buf + start, major, count);
    return true;
}

static bool put_int(writer_t *w, int64_t v)
{
    if (v >= 0) {
        return put_head(w, MAJOR_UINT, (uint64_t)v);
    }
    return put_head(w, MAJOR_NINT, (uint64_t)(-(v + 1)));
}

static bool put_text(writer_t *w, const char *s, size_t len)
{
    return put_head(w, MAJOR_TEXT, len) && put(w, s, len);
}

/* The half-precision bits for d, if d is exactly representable as one. */
static bool to_half(double d, uint16_t *out)
{
    if (fabs(d) > 65504.0) {
        return false;
    }
    float f = (float)d;
    if ((double)f != d) {
        return false;
    }
    uint32_t bits;
    memcpy(&bits, &f, sizeof(bits));
    uint16_t sign = (uint16_t)((bits >> 16) & 0x8000);
    int exp = (int)((bits >> 23) & 0xFF) - 127;
    uint32_t mant = bits & 0x7FFFFF;
    if ((bits & 0x7FFFFFFF) == 0) {
        *out = sign; /* zero, keeping its sign */
        return true;
    }
    if (exp >= -14) { /* normal half */
        if (mant & 0x1FFF) {
            return false;
        }
        *out = (uint16_t)(sign | (uint32_t)(exp + 15) << 10 | mant >> 13);
        return true;
    }
    if (exp < -24) {
        return false;
    }
    /* Subnormal half: the value is m * 2^-24 with m < 1024. */
    uint32_t full = mant | 0x800000;
    unsigned shift = (unsigned)(-(exp + 1)); /* 14 to 23 */
    if (full & ((1u << shift) - 1)) {
        return false;
    }
    *out = (uint16_t)(sign | full >> shift);
    return true;
}

/* A float in the shortest of half, single and double precision that is exact. */
static bool put_double(writer_t *w, double d)
{
    uint8_t b[9];
    uint16_t half;
    if (to_half(d, &half)) {
        b[0] = 0xF9;
        b[1] = (uint8_t)(half >> 8);
        b[2] = (uint8_t)half;
        return put(w, b, 3);
    }
    if (fabs(d) <= FLT_MAX && (double)(float)d == d) {
        float f = (float)d;
        uint32_t bits;
        memcpy(&bits, &f, sizeof(bits));
        b[0] = 0xFA;
        for (int i = 0; i < 4; i++) {
            b[1 + i] = (uint8_t)(bits >> (24 - 8 * i));
        }
        return put(w, b, 5);
    }
    uint64_t bits;
    memcpy(&bits, &d, sizeof(bits));
    b[0] = 0xFB;
    for (int i = 0; i < 8; i++) {
        b[1 + i] = (uint8_t)(bits >> (56 - 8 * i));
    }
    return put(w, b, 9);
}

/* ---- JSON data to CBOR ---------------------------------------------------- */

typedef struct {
    const char *p;
    writer_t *w;
    keyset_t keys;
    int depth;  /* containers open, counting the envelope */
    bool plain; /* keep every key as text (no standard data keys) */
} json_in_t;

static void skip_ws(json_in_t *j)
{
    while (*j->p == ' ' || *j->p == '\t' || *j->p == '\n' || *j->p == '\r') {
        j->p++;
    }
}

static int hex_digit(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static bool read_hex4(json_in_t *j, uint32_t *out)
{
    uint32_t v = 0;
    for (int i = 0; i < 4; i++) {
        int d = hex_digit(j->p[i]);
        if (d < 0) {
            return fail(j->w, "bad \\u escape in JSON");
        }
        v = v << 4 | (uint32_t)d;
    }
    j->p += 4;
    *out = v;
    return true;
}

static bool put_utf8(writer_t *w, uint32_t cp)
{
    uint8_t b[4];
    size_t n;
    if (cp < 0x80) {
        b[0] = (uint8_t)cp;
        n = 1;
    } else if (cp < 0x800) {
        b[0] = (uint8_t)(0xC0 | cp >> 6);
        b[1] = (uint8_t)(0x80 | (cp & 0x3F));
        n = 2;
    } else if (cp < 0x10000) {
        b[0] = (uint8_t)(0xE0 | cp >> 12);
        b[1] = (uint8_t)(0x80 | (cp >> 6 & 0x3F));
        b[2] = (uint8_t)(0x80 | (cp & 0x3F));
        n = 3;
    } else {
        b[0] = (uint8_t)(0xF0 | cp >> 18);
        b[1] = (uint8_t)(0x80 | (cp >> 12 & 0x3F));
        b[2] = (uint8_t)(0x80 | (cp >> 6 & 0x3F));
        b[3] = (uint8_t)(0x80 | (cp & 0x3F));
        n = 4;
    }
    return put(w, b, n);
}

/* A JSON string (at the opening quote) as a CBOR text string. */
static bool json_string(json_in_t *j)
{
    writer_t *w = j->w;
    size_t start = w->pos;
    if (!put(w, "", 1)) { /* placeholder for the head */
        return false;
    }
    j->p++;
    for (;;) {
        unsigned char c = (unsigned char)*j->p;
        if (c == '"') {
            j->p++;
            break;
        }
        if (c < 0x20) {
            return fail(w, c == 0 ? "unterminated string in JSON"
                                  : "control character in a JSON string");
        }
        if (c == '\\') {
            char e = j->p[1];
            j->p += 2;
            const char *simple = strchr("\"\\/bfnrt", e);
            if (e != '\0' && simple != NULL) {
                static const char decoded[] = "\"\\/\b\f\n\r\t";
                if (!put(w, &decoded[simple - "\"\\/bfnrt"], 1)) {
                    return false;
                }
                continue;
            }
            if (e != 'u') {
                return fail(w, "bad escape in a JSON string");
            }
            uint32_t cp;
            if (!read_hex4(j, &cp)) {
                return false;
            }
            if (cp >= 0xD800 && cp <= 0xDBFF) {
                uint32_t low;
                if (j->p[0] != '\\' || j->p[1] != 'u') {
                    return fail(w, "unpaired surrogate in a JSON string");
                }
                j->p += 2;
                if (!read_hex4(j, &low)) {
                    return false;
                }
                if (low < 0xDC00 || low > 0xDFFF) {
                    return fail(w, "unpaired surrogate in a JSON string");
                }
                cp = 0x10000 + ((cp - 0xD800) << 10) + (low - 0xDC00);
            } else if (cp >= 0xDC00 && cp <= 0xDFFF) {
                return fail(w, "unpaired surrogate in a JSON string");
            }
            if (!put_utf8(w, cp)) {
                return false;
            }
            continue;
        }
        size_t avail = 1;
        while (avail < 4 && j->p[avail] != '\0') {
            avail++;
        }
        size_t n = utf8_len((const uint8_t *)j->p, avail);
        if (n == 0) {
            return fail(w, "JSON string is not valid UTF-8");
        }
        if (!put(w, j->p, n)) {
            return false;
        }
        j->p += n;
    }
    return fix_head(w, start, MAJOR_TEXT, w->pos - start - 1);
}

static bool is_digit(char c)
{
    return c >= '0' && c <= '9';
}

static bool json_number(json_in_t *j)
{
    const char *s = j->p;
    bool is_float = false;
    if (*j->p == '-') j->p++;
    if (*j->p == '0') {
        j->p++;
    } else if (is_digit(*j->p)) {
        while (is_digit(*j->p)) j->p++;
    } else {
        return fail(j->w, "bad number in JSON");
    }
    if (*j->p == '.') {
        is_float = true;
        j->p++;
        if (!is_digit(*j->p)) return fail(j->w, "bad number in JSON");
        while (is_digit(*j->p)) j->p++;
    }
    if (*j->p == 'e' || *j->p == 'E') {
        is_float = true;
        j->p++;
        if (*j->p == '+' || *j->p == '-') j->p++;
        if (!is_digit(*j->p)) return fail(j->w, "bad number in JSON");
        while (is_digit(*j->p)) j->p++;
    }
    size_t len = (size_t)(j->p - s);
    char buf[NUMBER_MAX];
    if (len >= sizeof(buf)) {
        return fail(j->w, "number too long in JSON");
    }
    memcpy(buf, s, len);
    buf[len] = '\0';
    errno = 0;
    if (!is_float) {
        long long v = strtoll(buf, NULL, 10); /* long long has at least 64 bits */
        if (errno == ERANGE) {
            return fail(j->w, "integers in data must fit in 64 bits");
        }
        return put_int(j->w, (int64_t)v);
    }
    double d = strtod(buf, NULL);
    if (!isfinite(d)) {
        return fail(j->w, "number out of range in JSON");
    }
    return put_double(j->w, d);
}

static bool json_value(json_in_t *j, bool top);

/*
 * A JSON object (at the brace) as a CBOR map. In the top-level data object,
 * standard field names become their integer keys.
 */
static bool json_object(json_in_t *j, bool top)
{
    writer_t *w = j->w;
    size_t start = w->pos;
    size_t first_key = j->keys.count;
    uint64_t count = 0;
    if (!put(w, "", 1)) {
        return false;
    }
    j->p++;
    skip_ws(j);
    if (*j->p == '}') {
        j->p++;
    } else {
        for (;;) {
            skip_ws(j);
            if (*j->p != '"') {
                return fail(w, "expected a string key in JSON");
            }
            size_t key = w->pos;
            if (!json_string(j)) {
                return false;
            }
            if (top && !j->plain) {
                /* The text is the key's bytes after its (now final) head. */
                unsigned ai = w->buf[key] & 0x1F;
                size_t head = ai < 24 ? 1 : 1 + ((size_t)1 << (ai - 24));
                size_t text_len = w->pos - key - head;
                const atalaia_data_field_def_t *f =
                    atalaia_data_field((const char *)w->buf + key + head, text_len);
                if (f != NULL) {
                    w->pos = key;
                    if (!put_head(w, MAJOR_UINT, f->key)) {
                        return false;
                    }
                }
            }
            if (!add_key(w, &j->keys, first_key, key, w->pos - key)) {
                return false;
            }
            skip_ws(j);
            if (*j->p != ':') {
                return fail(w, "expected ':' in JSON");
            }
            j->p++;
            if (!json_value(j, false)) {
                return false;
            }
            count++;
            skip_ws(j);
            if (*j->p == ',') {
                j->p++;
                continue;
            }
            if (*j->p != '}') {
                return fail(w, "expected ',' or '}' in JSON");
            }
            j->p++;
            break;
        }
    }
    j->keys.count = first_key;
    return fix_head(w, start, MAJOR_MAP, count);
}

static bool json_array(json_in_t *j)
{
    writer_t *w = j->w;
    size_t start = w->pos;
    uint64_t count = 0;
    if (!put(w, "", 1)) {
        return false;
    }
    j->p++;
    skip_ws(j);
    if (*j->p == ']') {
        j->p++;
        return fix_head(w, start, MAJOR_ARRAY, 0);
    }
    for (;;) {
        if (!json_value(j, false)) {
            return false;
        }
        count++;
        skip_ws(j);
        if (*j->p == ',') {
            j->p++;
            continue;
        }
        if (*j->p != ']') {
            return fail(w, "expected ',' or ']' in JSON");
        }
        j->p++;
        return fix_head(w, start, MAJOR_ARRAY, count);
    }
}

static bool json_literal(json_in_t *j, const char *word, uint8_t simple)
{
    size_t len = strlen(word);
    if (strncmp(j->p, word, len) != 0) {
        return fail(j->w, "unexpected character in JSON");
    }
    j->p += len;
    return put(j->w, &simple, 1);
}

static bool json_value(json_in_t *j, bool top)
{
    skip_ws(j);
    char c = *j->p;
    if (top && c != '{') {
        return fail(j->w, "data must be a JSON object");
    }
    if (c == '{' || c == '[') {
        if (j->depth >= MAX_NESTING) {
            return fail(j->w, "data nested too deep");
        }
        j->depth++;
        bool ok = c == '{' ? json_object(j, top) : json_array(j);
        j->depth--;
        return ok;
    }
    switch (c) {
    case '"': return json_string(j);
    case 't': return json_literal(j, "true", 0xF5);
    case 'f': return json_literal(j, "false", 0xF4);
    case 'n': return json_literal(j, "null", 0xF6);
    default:
        if (c == '-' || is_digit(c)) {
            return json_number(j);
        }
        return fail(j->w, c == '\0' ? "unexpected end of JSON" : "unexpected character in JSON");
    }
}

/* ---- encoding ------------------------------------------------------------- */

size_t atalaia_event_encode(const atalaia_event_t *ev, const char *data_json, uint8_t *buf,
                            size_t cap, const char **error)
{
    writer_t w = {buf, cap > ATALAIA_CODEC_MAX_BYTES ? ATALAIA_CODEC_MAX_BYTES : cap, 0, NULL};
    if (buf == NULL) {
        w.cap = 0;
    }
    const char *type = ev != NULL ? ev->type : NULL;
    const char *end = type != NULL ? memchr(type, '\0', ATALAIA_EVENT_TYPE_MAX) : NULL;
    size_t type_len = end != NULL ? (size_t)(end - type) : 0;

    if (end == NULL || type_len == 0 || !printable_ascii(type, type_len)) {
        fail(&w, "event type must be 1 to 47 printable ASCII characters");
    } else if (ev->team > ATALAIA_TEAM_MAX) {
        fail(&w, "team id out of range");
    } else if ((unsigned)ev->prio > ATALAIA_PRIO_CRITICAL) {
        fail(&w, "unknown priority");
    } else {
        const atalaia_event_def_t *def = atalaia_event_def(type);
        atalaia_prio_t prio = def != NULL ? def->prio : ATALAIA_PRIO_NORMAL;
        size_t start = w.pos;
        uint64_t entries = 4;
        if (put(&w, "", 1) && put_head(&w, MAJOR_UINT, ATALAIA_KEY_NODE) &&
            put_head(&w, MAJOR_UINT, ev->node) && put_head(&w, MAJOR_UINT, ATALAIA_KEY_SEQ) &&
            put_head(&w, MAJOR_UINT, ev->seq) && put_head(&w, MAJOR_UINT, ATALAIA_KEY_T) &&
            put_head(&w, MAJOR_UINT, ev->t_ms) && put_head(&w, MAJOR_UINT, ATALAIA_KEY_TYPE) &&
            (def != NULL ? put_head(&w, MAJOR_UINT, def->id) : put_text(&w, type, type_len))) {
            if (ev->team != ATALAIA_TEAM_NONE) {
                put_head(&w, MAJOR_UINT, ATALAIA_KEY_TEAM);
                put_head(&w, MAJOR_UINT, ev->team);
                entries++;
            }
            if (ev->squad != ATALAIA_SQUAD_NONE) {
                put_head(&w, MAJOR_UINT, ATALAIA_KEY_SQUAD);
                put_head(&w, MAJOR_UINT, ev->squad);
                entries++;
            }
            if (ev->prio != prio) {
                put_head(&w, MAJOR_UINT, ATALAIA_KEY_PRIO);
                put_head(&w, MAJOR_UINT, (uint64_t)ev->prio);
                entries++;
            }
            if (data_json != NULL && w.error == NULL) {
                size_t data_start = w.pos;
                json_in_t j = {data_json, &w, {{0}, {0}, 0}, 1, false};
                if (put_head(&w, MAJOR_UINT, ATALAIA_KEY_DATA) && json_value(&j, true)) {
                    skip_ws(&j);
                    if (*j.p != '\0') {
                        fail(&w, "trailing characters after the JSON data");
                    } else if (w.buf[data_start + 1] == 0xA0) {
                        w.pos = data_start; /* empty data is left out */
                    } else {
                        entries++;
                    }
                }
            }
            if (w.error == NULL) {
                fix_head(&w, start, MAJOR_MAP, entries);
            }
        }
    }
    if (error != NULL) {
        *error = w.error;
    }
    return w.error == NULL ? w.pos : 0;
}

/* ---- CBOR input ----------------------------------------------------------- */

typedef struct {
    const uint8_t *p;
    const uint8_t *end;
    writer_t *w; /* the JSON output */
    keyset_t keys;
    int depth;  /* containers open, counting the envelope */
    bool plain; /* every key is text (no standard data keys) */
} cbor_in_t;

static size_t remaining(const cbor_in_t *r)
{
    return (size_t)(r->end - r->p);
}

/* Reads an initial byte and its argument. */
static bool read_head(cbor_in_t *r, unsigned *major, unsigned *ai, uint64_t *value)
{
    if (remaining(r) < 1) {
        return fail(r->w, "truncated");
    }
    uint8_t initial = *r->p++;
    *major = initial >> 5;
    *ai = initial & 0x1F;
    if (*ai < 24) {
        *value = *ai;
        return true;
    }
    if (*ai > 27) {
        return fail(r->w, "indefinite lengths and reserved values are not allowed");
    }
    size_t n = (size_t)1 << (*ai - 24);
    if (remaining(r) < n) {
        return fail(r->w, "truncated");
    }
    uint64_t v = 0;
    for (size_t i = 0; i < n; i++) {
        v = v << 8 | *r->p++;
    }
    *value = v;
    return true;
}

static bool read_uint(cbor_in_t *r, uint64_t max, const char *message, uint64_t *out)
{
    unsigned major, ai;
    uint64_t v;
    if (!read_head(r, &major, &ai, &v)) {
        return false;
    }
    if (major != MAJOR_UINT || v > max) {
        return fail(r->w, message);
    }
    *out = v;
    return true;
}

/* ---- CBOR to JSON data ----------------------------------------------------- */

static double from_half(uint16_t h)
{
    int exp = (h >> 10) & 0x1F;
    unsigned mant = h & 0x3FF;
    double v;
    if (exp == 0) {
        v = ldexp((double)mant, -24);
    } else if (exp == 31) {
        v = mant != 0 ? NAN : INFINITY;
    } else {
        v = ldexp((double)(mant + 1024), exp - 25);
    }
    return (h & 0x8000) ? -v : v;
}

/*
 * Writes d as the shortest JSON number that reads back as the same double,
 * formatted like Python's repr(): fixed notation for exponents from -4 to 15,
 * and always with a '.' or exponent so it stays a float in Lua.
 */
static bool put_json_double(writer_t *w, double d)
{
    char digits[32];
    char out[64];
    int prec = 0;
    for (; prec < 17; prec++) {
        snprintf(digits, sizeof(digits), "%.*e", prec, d);
        if (strtod(digits, NULL) == d) {
            break;
        }
    }
    int exp10 = atoi(strchr(digits, 'e') + 1);
    if (exp10 < -4 || exp10 >= 16) {
        return put_str(w, digits);
    }
    int decimals = prec - exp10 > 0 ? prec - exp10 : 0;
    snprintf(out, sizeof(out), "%.*f", decimals, d);
    if (strchr(out, '.') == NULL) {
        strcat(out, ".0");
    }
    return put_str(w, out);
}

/* Writes len bytes of valid UTF-8 as a quoted JSON string. */
static bool put_json_string(writer_t *w, const uint8_t *s, size_t len)
{
    if (!put(w, "\"", 1)) {
        return false;
    }
    for (size_t i = 0; i < len; i++) {
        uint8_t c = s[i];
        const char *esc = NULL;
        char u[8];
        switch (c) {
        case '"': esc = "\\\""; break;
        case '\\': esc = "\\\\"; break;
        case '\b': esc = "\\b"; break;
        case '\f': esc = "\\f"; break;
        case '\n': esc = "\\n"; break;
        case '\r': esc = "\\r"; break;
        case '\t': esc = "\\t"; break;
        default:
            if (c < 0x20) {
                snprintf(u, sizeof(u), "\\u%04x", c);
                esc = u;
            }
        }
        if (esc != NULL ? !put_str(w, esc) : !put(w, &c, 1)) {
            return false;
        }
    }
    return put(w, "\"", 1);
}

/* Reads a text string's bytes (after its head) and checks they are UTF-8. */
static bool read_text(cbor_in_t *r, uint64_t len, const uint8_t **text)
{
    if (len > remaining(r)) {
        return fail(r->w, "truncated");
    }
    *text = r->p;
    for (size_t i = 0; i < len;) {
        size_t n = utf8_len(r->p + i, (size_t)len - i);
        if (n == 0) {
            return fail(r->w, "text is not valid UTF-8");
        }
        i += n;
    }
    r->p += len;
    return true;
}

static bool cbor_value(cbor_in_t *r, bool top);

static bool cbor_container(cbor_in_t *r, unsigned major, uint64_t count, bool top)
{
    writer_t *w = r->w;
    if (r->depth >= MAX_NESTING) {
        return fail(w, "data nested too deep");
    }
    if (count > remaining(r)) {
        return fail(w, "truncated"); /* every item takes at least a byte */
    }
    r->depth++;
    size_t first_key = r->keys.count;
    if (!put(w, major == MAJOR_MAP ? "{" : "[", 1)) {
        return false;
    }
    for (uint64_t i = 0; i < count; i++) {
        if (i > 0 && !put(w, ",", 1)) {
            return false;
        }
        if (major == MAJOR_MAP) {
            unsigned kmajor, ai;
            uint64_t k;
            if (!read_head(r, &kmajor, &ai, &k)) {
                return false;
            }
            size_t key = w->pos;
            if (top && kmajor == MAJOR_UINT && !r->plain) {
                const atalaia_data_field_def_t *f =
                    k <= 0xFF ? atalaia_data_field_by_key((unsigned)k) : NULL;
                if (f == NULL) {
                    return fail(w, "unknown data key");
                }
                if (!put_json_string(w, (const uint8_t *)f->name, strlen(f->name))) {
                    return false;
                }
            } else if (kmajor == MAJOR_TEXT) {
                const uint8_t *text;
                if (!read_text(r, k, &text) || !put_json_string(w, text, (size_t)k)) {
                    return false;
                }
            } else {
                return fail(w, "data keys must be text");
            }
            if (!add_key(w, &r->keys, first_key, key, w->pos - key) || !put(w, ":", 1)) {
                return false;
            }
        }
        if (!cbor_value(r, false)) {
            return false;
        }
    }
    r->keys.count = first_key;
    r->depth--;
    return put(w, major == MAJOR_MAP ? "}" : "]", 1);
}

static bool cbor_value(cbor_in_t *r, bool top)
{
    writer_t *w = r->w;
    unsigned major, ai;
    uint64_t v;
    char num[32];
    if (!read_head(r, &major, &ai, &v)) {
        return false;
    }
    if (top && major != MAJOR_MAP) {
        return fail(w, "data must be a map");
    }
    switch (major) {
    case MAJOR_UINT:
        if (v > INT64_MAX) {
            return fail(w, "integers in data must fit in 64 bits");
        }
        snprintf(num, sizeof(num), "%" PRIu64, v);
        return put_str(w, num);
    case MAJOR_NINT:
        if (v > INT64_MAX) {
            return fail(w, "integers in data must fit in 64 bits");
        }
        snprintf(num, sizeof(num), "%" PRId64, -1 - (int64_t)v);
        return put_str(w, num);
    case MAJOR_TEXT: {
        const uint8_t *text;
        return read_text(r, v, &text) && put_json_string(w, text, (size_t)v);
    }
    case MAJOR_ARRAY:
    case MAJOR_MAP: return cbor_container(r, major, v, top);
    case MAJOR_SIMPLE: {
        double d;
        if (ai == 20) return put_str(w, "false");
        if (ai == 21) return put_str(w, "true");
        if (ai == 22) return put_str(w, "null");
        if (ai == 25) {
            d = from_half((uint16_t)v);
        } else if (ai == 26) {
            uint32_t bits = (uint32_t)v;
            float f;
            memcpy(&f, &bits, sizeof(f));
            d = f;
        } else if (ai == 27) {
            memcpy(&d, &v, sizeof(d));
        } else {
            return fail(w, "undefined and simple values are not allowed");
        }
        if (!isfinite(d)) {
            return fail(w, "NaN and infinity are not allowed");
        }
        return put_json_double(w, d);
    }
    default: return fail(w, "byte strings and tags are not allowed");
    }
}

/* ---- decoding ------------------------------------------------------------- */

static bool decode_envelope(cbor_in_t *r, atalaia_event_t *ev)
{
    writer_t *w = r->w;
    unsigned major, ai;
    uint64_t count;
    uint64_t node = 0, seq = 0, t = 0, team = 0, squad = 0, prio = 0;
    unsigned seen = 0;
    bool has_data = false;
    const atalaia_event_def_t *def = NULL;

    memset(ev, 0, sizeof(*ev));
    if (!read_head(r, &major, &ai, &count)) {
        return false;
    }
    if (major != MAJOR_MAP) {
        return fail(w, "an event is a map");
    }
    if (count > remaining(r)) {
        return fail(w, "truncated");
    }
    for (uint64_t i = 0; i < count; i++) {
        uint64_t key;
        if (!read_uint(r, 31, "unknown envelope key", &key)) {
            return false;
        }
        if (seen & (1u << key)) {
            return fail(w, "duplicate envelope key");
        }
        seen |= 1u << key;
        bool ok;
        switch (key) {
        case ATALAIA_KEY_NODE: ok = read_uint(r, 0xFFFF, "node out of range", &node); break;
        case ATALAIA_KEY_SEQ: ok = read_uint(r, 0xFFFF, "seq out of range", &seq); break;
        case ATALAIA_KEY_T: ok = read_uint(r, 0xFFFFFFFFu, "t out of range", &t); break;
        case ATALAIA_KEY_TEAM:
            ok = read_uint(r, ATALAIA_TEAM_MAX, "team out of range", &team);
            break;
        case ATALAIA_KEY_SQUAD: ok = read_uint(r, 0xFF, "squad out of range", &squad); break;
        case ATALAIA_KEY_PRIO:
            ok = read_uint(r, ATALAIA_PRIO_CRITICAL, "unknown priority", &prio);
            break;
        case ATALAIA_KEY_TYPE: {
            uint64_t v;
            ok = read_head(r, &major, &ai, &v);
            if (!ok) {
                break;
            }
            if (major == MAJOR_UINT) {
                def = v <= 0xFF ? atalaia_event_def_by_id((unsigned)v) : NULL;
                if (def == NULL) {
                    return fail(w, "unknown event id");
                }
                strcpy(ev->type, def->name);
            } else if (major == MAJOR_TEXT) {
                if (v == 0 || v >= ATALAIA_EVENT_TYPE_MAX || v > remaining(r) ||
                    !printable_ascii((const char *)r->p, (size_t)v)) {
                    return fail(w, "event type must be 1 to 47 printable ASCII characters");
                }
                memcpy(ev->type, r->p, (size_t)v);
                ev->type[v] = '\0';
                r->p += v;
                def = atalaia_event_def(ev->type);
            } else {
                return fail(w, "event type must be an id or text");
            }
            break;
        }
        case ATALAIA_KEY_DATA:
            has_data = true;
            ok = cbor_value(r, true);
            break;
        default: return fail(w, "unknown envelope key");
        }
        if (!ok) {
            return false;
        }
    }
    if (remaining(r) != 0) {
        return fail(w, "trailing bytes");
    }
    const unsigned required = 1u << ATALAIA_KEY_NODE | 1u << ATALAIA_KEY_SEQ | 1u << ATALAIA_KEY_T |
                              1u << ATALAIA_KEY_TYPE;
    if ((seen & required) != required) {
        return fail(w, "the event needs node, seq, t and type");
    }
    if (!has_data && !put_str(w, "{}")) {
        return false;
    }
    ev->node = (uint16_t)node;
    ev->seq = (uint16_t)seq;
    ev->t_ms = (uint32_t)t;
    ev->team = (uint8_t)team;
    ev->squad = (uint8_t)squad;
    if (seen & (1u << ATALAIA_KEY_PRIO)) {
        ev->prio = (atalaia_prio_t)prio;
    } else {
        ev->prio = def != NULL ? def->prio : ATALAIA_PRIO_NORMAL;
    }
    return true;
}

bool atalaia_event_decode(const uint8_t *buf, size_t len, atalaia_event_t *ev, char *data_json,
                          size_t data_cap, const char **error)
{
    atalaia_event_t scratch;
    writer_t w = {(uint8_t *)data_json, 0, 0, NULL};
    if (data_json == NULL || data_cap == 0) {
        fail(&w, "no room for the data");
    } else {
        /* Room for the NUL; offsets must fit the key set's 16 bits. */
        w.cap = data_cap - 1 > ATALAIA_CODEC_MAX_BYTES ? ATALAIA_CODEC_MAX_BYTES : data_cap - 1;
        if (buf == NULL || len > ATALAIA_CODEC_MAX_BYTES) {
            fail(&w, buf == NULL ? "no payload" : "payload too long");
        } else {
            cbor_in_t r = {buf, buf + len, &w, {{0}, {0}, 0}, 1, false};
            decode_envelope(&r, ev != NULL ? ev : &scratch);
        }
        data_json[w.error == NULL ? w.pos : 0] = '\0';
    }
    if (error != NULL) {
        *error = w.error;
    }
    return w.error == NULL;
}

/* ---- JSON objects as plain CBOR maps (CMD parameters) --------------------- */

size_t atalaia_json_map_encode(const char *json, uint8_t *buf, size_t cap, const char **error)
{
    writer_t w = {buf, cap > ATALAIA_CODEC_MAX_BYTES ? ATALAIA_CODEC_MAX_BYTES : cap, 0, NULL};
    if (buf == NULL) {
        w.cap = 0;
    }
    if (json == NULL) {
        fail(&w, "no JSON");
    } else {
        json_in_t j = {json, &w, {{0}, {0}, 0}, 0, true};
        if (json_value(&j, true)) {
            skip_ws(&j);
            if (*j.p != '\0') {
                fail(&w, "trailing characters after the JSON object");
            }
        }
    }
    if (error != NULL) {
        *error = w.error;
    }
    return w.error == NULL ? w.pos : 0;
}

bool atalaia_json_map_decode(const uint8_t *buf, size_t len, size_t *used, char *json,
                             size_t json_cap, const char **error)
{
    writer_t w = {(uint8_t *)json, 0, 0, NULL};
    if (json == NULL || json_cap == 0) {
        fail(&w, "no room for the JSON");
    } else {
        w.cap = json_cap - 1 > ATALAIA_CODEC_MAX_BYTES ? ATALAIA_CODEC_MAX_BYTES : json_cap - 1;
        if (buf == NULL || len > ATALAIA_CODEC_MAX_BYTES) {
            fail(&w, buf == NULL ? "no CBOR" : "CBOR too long");
        } else {
            cbor_in_t r = {buf, buf + len, &w, {{0}, {0}, 0}, 0, true};
            if (cbor_value(&r, true) && used != NULL) {
                *used = (size_t)(r.p - buf);
            }
        }
        json[w.error == NULL ? w.pos : 0] = '\0';
    }
    if (error != NULL) {
        *error = w.error;
    }
    return w.error == NULL;
}
