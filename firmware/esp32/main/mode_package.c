/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Signed mode packages on the Field Box (mode_package.h): the release text, its
 * signature and the archive's canonical form, as the shared Python
 * (controller/atalaia_controller/mode_package.py) checks them; both are tested
 * against protocol/vectors/mode_package.json.
 */
#include "mode_package.h"

#include <stdio.h>
#include <string.h>

#include "atalaia/join.h"
#include "monocypher-ed25519.h"

static const char *const KIND_NAMES[] = {"mode", "modifier", "role", "scenario"};
static const char *const TIER_NAMES[] = {"reduced", "full"};

const char *mp_kind_name(mp_kind_t kind)
{
    return (unsigned)kind < 4 ? KIND_NAMES[kind] : "?";
}

const char *mp_tier_name(mp_tier_t tier)
{
    return (unsigned)tier < 2 ? TIER_NAMES[tier] : "?";
}

static bool id_char(char c, bool first)
{
    if ((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9')) return true;
    return !first && (c == '_' || c == '-');
}

bool mp_id_valid(const char *s, size_t n)
{
    if (s == NULL || n == 0 || n > MP_ID_MAX) return false;
    int parts = 0;
    size_t i = 0;
    while (i < n) {
        if (!id_char(s[i], true)) return false;
        i++;
        while (i < n && s[i] != '.') {
            if (!id_char(s[i], false)) return false;
            i++;
        }
        parts++;
        if (i < n) {
            i++; /* '.' */
            if (i == n) return false;
        }
    }
    return parts >= 2;
}

/* ---- release texts --------------------------------------------------------------------- */

/* "name=value\n" at *p: the value and its length; *p past the line feed. */
static bool take_line(const char **p, const char *end, const char *name, const char **value,
                      size_t *len)
{
    size_t nl = strlen(name);
    if ((size_t)(end - *p) < nl + 2 || memcmp(*p, name, nl) != 0 || (*p)[nl] != '=') return false;
    const char *v = *p + nl + 1;
    const char *e = memchr(v, '\n', (size_t)(end - v));
    if (e == NULL) return false;
    *value = v;
    *len = (size_t)(e - v);
    *p = e + 1;
    return true;
}

static int name_index(const char *const *names, size_t count, const char *v, size_t n)
{
    for (size_t i = 0; i < count; i++) {
        if (strlen(names[i]) == n && memcmp(names[i], v, n) == 0) return (int)i;
    }
    return -1;
}

static int hex_value(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    return -1;
}

bool mp_release_parse(const char *text, size_t len, mp_release_t *out)
{
    memset(out, 0, sizeof(*out));
    if (text == NULL || len == 0 || len > MP_RELEASE_TEXT_MAX) return false;
    for (size_t i = 0; i < len; i++) {
        unsigned char c = (unsigned char)text[i];
        if (c == 0 || c > 0x7F) return false; /* ASCII, as the Python decodes it */
    }
    const char *p = text, *end = text + len;
    size_t hl = strlen(MP_MANIFEST_HEADER);
    if (len < hl + 1 || memcmp(p, MP_MANIFEST_HEADER, hl) != 0 || p[hl] != '\n') return false;
    p += hl + 1;
    const char *v;
    size_t n;

    if (!take_line(&p, end, "id", &v, &n) || !mp_id_valid(v, n)) return false;
    memcpy(out->id, v, n);

    if (!take_line(&p, end, "version", &v, &n) || n > FW_VERSION_MAX) return false;
    memcpy(out->version, v, n);
    out->version[n] = '\0';
    if (!fw_version_valid_plain(out->version)) return false;

    int k;
    if (!take_line(&p, end, "kind", &v, &n) || (k = name_index(KIND_NAMES, 4, v, n)) < 0) {
        return false;
    }
    out->kind = (mp_kind_t)k;
    if (!take_line(&p, end, "min_tier", &v, &n) || (k = name_index(TIER_NAMES, 2, v, n)) < 0) {
        return false;
    }
    out->tier = (mp_tier_t)k;

    /* [1-9][0-9]{0,6}, at most the controller's limit. */
    if (!take_line(&p, end, "size", &v, &n) || n < 1 || n > 7 || v[0] == '0') return false;
    uint32_t size = 0;
    for (size_t i = 0; i < n; i++) {
        if (v[i] < '0' || v[i] > '9') return false;
        size = size * 10u + (uint32_t)(v[i] - '0');
    }
    if (size > MP_PACKAGE_MAX) return false;
    out->size = size;

    if (!take_line(&p, end, "sha256", &v, &n) || n != 64) return false;
    for (size_t i = 0; i < 32; i++) {
        int hi = hex_value(v[2 * i]), lo = hex_value(v[2 * i + 1]);
        if (hi < 0 || lo < 0) return false;
        out->sha256[i] = (uint8_t)(hi << 4 | lo);
    }
    memcpy(out->sha256_hex, v, 64);
    out->manifest_len = (size_t)(p - text);

    if (!take_line(&p, end, "signature", &v, &n) || !fw_signature_decode(v, n, out->signature)) {
        return false;
    }
    return p == end;
}

int mp_release_signer(const mp_release_t *rel, const char *text, const uint8_t (*keys)[32],
                      size_t key_count)
{
    for (size_t k = 0; k < key_count; k++) {
        if (crypto_ed25519_check(rel->signature, keys[k], (const uint8_t *)text,
                                 rel->manifest_len) == 0) {
            return (int)k;
        }
    }
    return -1;
}

void mp_key_id(const uint8_t key[32], char out[17])
{
    uint8_t h[32];
    atalaia_sha256(key, 32, h);
    for (int i = 0; i < 8; i++) snprintf(out + 2 * i, 3, "%02x", h[i]);
}

/* ---- the archive ----------------------------------------------------------------------- */

enum { ST_HEADER = 0, ST_DATA, ST_PAD, ST_END, ST_DONE };

/* A ustar number: width - 1 octal digits, then NUL. */
static void put_octal(uint8_t *f, size_t width, uint32_t value)
{
    for (size_t i = width - 1; i-- > 0;) {
        f[i] = (uint8_t)('0' + (value & 7u));
        value >>= 3;
    }
    f[width - 1] = 0;
}

/* The canonical header of "<root>/<name>" (path, plen bytes) holding size bytes: exactly what
 * the Python's _header writes. */
static void canonical_header(uint8_t h[MP_BLOCK], const char *path, size_t plen, uint32_t size)
{
    memset(h, 0, MP_BLOCK);
    memcpy(h, path, plen);
    put_octal(h + 100, 8, 0644);
    put_octal(h + 108, 8, 0);
    put_octal(h + 116, 8, 0);
    put_octal(h + 124, 12, size);
    put_octal(h + 136, 12, 0);
    memset(h + 148, ' ', 8);
    h[156] = '0';
    memcpy(h + 257,
           "ustar\0"
           "00",
           8);
    put_octal(h + 329, 8, 0);
    put_octal(h + 337, 8, 0);
    uint32_t sum = 0;
    for (size_t i = 0; i < MP_BLOCK; i++) sum += h[i];
    put_octal(h + 148, 7, sum); /* six digits and NUL; the space after stays */
}

static bool all_zero(const uint8_t *p, size_t n)
{
    for (size_t i = 0; i < n; i++) {
        if (p[i] != 0) return false;
    }
    return true;
}

static bool name_char(char c)
{
    return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_' ||
           c == '.' || c == '-';
}

/* The files the controller takes (FILE_NAME in the Python): mode.yaml, node.lua, field.lua and
 * assets/<segments>, no segment empty or starting with a dot. */
static bool file_name_ok(const char *name)
{
    if (strcmp(name, "mode.yaml") == 0 || strcmp(name, "node.lua") == 0 ||
        strcmp(name, "field.lua") == 0) {
        return true;
    }
    if (strncmp(name, "assets/", 7) != 0) return false;
    const char *seg = name + 7;
    for (;;) {
        size_t n = strcspn(seg, "/");
        if (n == 0 || seg[0] == '.') return false;
        for (size_t i = 0; i < n; i++) {
            if (!name_char(seg[i])) return false;
        }
        if (seg[n] == '\0') return true;
        seg += n + 1;
    }
}

static mp_tar_result_t fail(mp_tar_t *t, mp_tar_result_t r)
{
    if (t->result == MP_TAR_OK) t->result = r;
    t->state = ST_DONE;
    return t->result;
}

static mp_tar_result_t header(mp_tar_t *t)
{
    const uint8_t *h = t->block;
    if (all_zero(h, MP_BLOCK)) {
        if (t->files == 0) return fail(t, MP_TAR_BAD_ARCHIVE); /* an empty archive */
        t->state = ST_END;
        return MP_TAR_OK;
    }
    /* The name and the size, read as loosely as is safe; the comparison below decides. */
    size_t plen = 0;
    while (plen < MP_NAME_MAX && h[plen] != 0) plen++;
    char path[MP_NAME_MAX + 1];
    memcpy(path, h, plen);
    path[plen] = '\0';
    uint32_t size = 0;
    for (size_t i = 124; i < 135; i++) {
        if (h[i] < '0' || h[i] > '7') return fail(t, MP_TAR_BAD_ARCHIVE);
        size = size << 3 | (uint32_t)(h[i] - '0');
    }
    if (size > t->limit) return fail(t, MP_TAR_BAD_ARCHIVE);
    for (size_t i = 0; i < plen; i++) {
        if (h[i] < 0x20 || h[i] > 0x7E) return fail(t, MP_TAR_BAD_ARCHIVE); /* ASCII */
    }
    uint8_t want[MP_BLOCK];
    canonical_header(want, path, plen, size);
    if (memcmp(want, h, MP_BLOCK) != 0) return fail(t, MP_TAR_BAD_ARCHIVE);

    /* "<root>/<name>": one root, a mode id; the name a file the controller takes. */
    const char *slash = strchr(path, '/');
    if (slash == NULL) return fail(t, MP_TAR_BAD_ARCHIVE);
    size_t rlen = (size_t)(slash - path);
    const char *name = slash + 1;
    if (t->files == 0) {
        if (!mp_id_valid(path, rlen)) return fail(t, MP_TAR_BAD_ARCHIVE);
        memcpy(t->root, path, rlen);
        t->root[rlen] = '\0';
    } else if (strlen(t->root) != rlen || memcmp(t->root, path, rlen) != 0) {
        return fail(t, MP_TAR_BAD_ARCHIVE);
    }
    if (!file_name_ok(name)) return fail(t, MP_TAR_BAD_ARCHIVE);
    /* Sorted by name, each once. */
    if (t->files > 0 && strcmp(t->prev, name) >= 0) return fail(t, MP_TAR_BAD_ARCHIVE);
    if (t->files >= MP_FILES_MAX) return fail(t, MP_TAR_BAD_ARCHIVE);
    if (t->files == 0 && t->expect[0] != '\0' && strcmp(t->root, t->expect) != 0) {
        return fail(t, MP_TAR_MISMATCH);
    }
    snprintf(t->prev, sizeof(t->prev), "%s", name);
    t->files++;
    t->remaining = size;
    t->pad = (MP_BLOCK - size % MP_BLOCK) % MP_BLOCK;
    t->utf8_need = 0;
    if (t->ops != NULL && t->ops->file_begin != NULL &&
        !t->ops->file_begin(t->ops->ctx, name, size)) {
        return fail(t, MP_TAR_STOPPED);
    }
    t->state = ST_DATA;
    return MP_TAR_OK;
}

/* UTF-8 as Python's strict decoder takes it (no overlong forms, surrogates or values above
 * U+10FFFF), and no NUL. */
static bool utf8_ok(mp_tar_t *t, const uint8_t *p, size_t n)
{
    for (size_t i = 0; i < n; i++) {
        uint8_t c = p[i];
        if (t->utf8_need > 0) {
            if (c < t->utf8_lo || c > t->utf8_hi) return false;
            t->utf8_lo = 0x80;
            t->utf8_hi = 0xBF;
            t->utf8_need--;
            continue;
        }
        if (c == 0) return false;
        if (c < 0x80) continue;
        t->utf8_lo = 0x80;
        t->utf8_hi = 0xBF;
        if (c >= 0xC2 && c <= 0xDF) {
            t->utf8_need = 1;
        } else if (c >= 0xE0 && c <= 0xEF) {
            t->utf8_need = 2;
            if (c == 0xE0) t->utf8_lo = 0xA0;
            if (c == 0xED) t->utf8_hi = 0x9F;
        } else if (c >= 0xF0 && c <= 0xF4) {
            t->utf8_need = 3;
            if (c == 0xF0) t->utf8_lo = 0x90;
            if (c == 0xF4) t->utf8_hi = 0x8F;
        } else {
            return false;
        }
    }
    return true;
}

static mp_tar_result_t end_of_file(mp_tar_t *t)
{
    if (t->utf8_need != 0) return fail(t, MP_TAR_BAD_ARCHIVE);
    if (t->ops != NULL && t->ops->file_end != NULL && !t->ops->file_end(t->ops->ctx)) {
        return fail(t, MP_TAR_STOPPED);
    }
    t->state = t->pad > 0 ? ST_PAD : ST_HEADER;
    t->have = 0;
    return MP_TAR_OK;
}

void mp_tar_init(mp_tar_t *t, const char *expect, uint32_t limit, const mp_tar_ops_t *ops)
{
    memset(t, 0, sizeof(*t));
    t->ops = ops;
    t->limit = limit;
    if (expect != NULL) snprintf(t->expect, sizeof(t->expect), "%s", expect);
    t->state = ST_HEADER;
}

mp_tar_result_t mp_tar_feed(mp_tar_t *t, const uint8_t *data, size_t len)
{
    if (t->result != MP_TAR_OK) return t->result;
    if ((uint64_t)t->total + len > t->limit) return fail(t, MP_TAR_TOO_BIG);
    t->total += (uint32_t)len;
    while (len > 0) {
        switch (t->state) {
        case ST_HEADER:
        case ST_END: {
            size_t take = MP_BLOCK - t->have < len ? MP_BLOCK - t->have : len;
            memcpy(t->block + t->have, data, take);
            t->have += take;
            data += take;
            len -= take;
            if (t->have < MP_BLOCK) break;
            t->have = 0;
            if (t->state == ST_END) {
                /* The second zero block; nothing may follow it. */
                if (!all_zero(t->block, MP_BLOCK)) return fail(t, MP_TAR_BAD_ARCHIVE);
                t->state = ST_DONE;
                break;
            }
            if (header(t) != MP_TAR_OK) return t->result;
            if (t->state == ST_DATA && t->remaining == 0 && end_of_file(t) != MP_TAR_OK) {
                return t->result;
            }
            break;
        }
        case ST_DATA: {
            size_t take = t->remaining < len ? t->remaining : len;
            if (!utf8_ok(t, data, take)) return fail(t, MP_TAR_BAD_ARCHIVE);
            if (t->ops != NULL && t->ops->file_data != NULL &&
                !t->ops->file_data(t->ops->ctx, data, take)) {
                return fail(t, MP_TAR_STOPPED);
            }
            t->remaining -= (uint32_t)take;
            data += take;
            len -= take;
            if (t->remaining == 0 && end_of_file(t) != MP_TAR_OK) return t->result;
            break;
        }
        case ST_PAD: {
            size_t take = t->pad < len ? t->pad : len;
            if (!all_zero(data, take)) return fail(t, MP_TAR_BAD_ARCHIVE);
            t->pad -= (uint32_t)take;
            data += take;
            len -= take;
            if (t->pad == 0) t->state = ST_HEADER;
            break;
        }
        default: return fail(t, MP_TAR_BAD_ARCHIVE); /* data after the end */
        }
    }
    return MP_TAR_OK;
}

mp_tar_result_t mp_tar_finish(mp_tar_t *t)
{
    if (t->result != MP_TAR_OK) return t->result;
    if (t->state != ST_DONE) return fail(t, MP_TAR_BAD_ARCHIVE); /* cut short: no end */
    return MP_TAR_OK;
}

mp_tar_result_t mp_tar_check(const uint8_t *archive, size_t len, const char *expect, uint32_t limit,
                             const mp_tar_ops_t *ops)
{
    mp_tar_t t;
    mp_tar_init(&t, expect, limit, ops);
    if (len > limit) return MP_TAR_TOO_BIG;
    mp_tar_result_t r = mp_tar_feed(&t, archive, len);
    return r != MP_TAR_OK ? r : mp_tar_finish(&t);
}
