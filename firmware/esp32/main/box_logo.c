/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The field's logo on the Field Box's TFT (box_logo.h).
 */
#include "box_logo.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static char s_base[128];
static uint16_t *s_pixels;

static bool path_of(char *buf, size_t cap, const char *name)
{
    return s_base[0] != '\0' && snprintf(buf, cap, "%s/%s", s_base, name) < (int)cap;
}

int box_logo_init(const char *base_path)
{
    if (base_path == NULL || strlen(base_path) >= sizeof(s_base)) return -1;
    snprintf(s_base, sizeof(s_base), "%s", base_path);
    char p[160];
    if (path_of(p, sizeof(p), "logo.new")) remove(p); /* a fetch a power loss cut short */
    return 0;
}

static bool is_hex(const char *s, size_t n)
{
    for (size_t i = 0; i < n; i++) {
        if (!((s[i] >= '0' && s[i] <= '9') || (s[i] >= 'a' && s[i] <= 'f'))) return false;
    }
    return true;
}

/* The kept file: the 64 hex digits of the id, then the box-ready bytes (header and pixels). */
static bool header_ok(const uint8_t *h)
{
    return memcmp(h, "ALG1", 4) == 0 && h[4] == BL_SIDE && h[5] == 0 && h[6] == BL_SIDE &&
           h[7] == 0;
}

bool box_logo_kept(char id[BL_ID_LEN + 1])
{
    char p[160];
    if (!path_of(p, sizeof(p), "logo.bin")) return false;
    FILE *f = fopen(p, "rb");
    if (f == NULL) return false;
    uint8_t head[BL_ID_LEN + BL_HEADER];
    bool ok = fread(head, 1, sizeof(head), f) == sizeof(head) && header_ok(head + BL_ID_LEN) &&
              is_hex((const char *)head, BL_ID_LEN);
    if (ok) {
        fseek(f, 0, SEEK_END);
        ok = ftell(f) == (long)(BL_ID_LEN + BL_BYTES);
    }
    fclose(f);
    if (ok && id != NULL) {
        memcpy(id, head, BL_ID_LEN);
        id[BL_ID_LEN] = '\0';
    }
    return ok;
}

const uint16_t *box_logo_load(void)
{
    if (s_pixels != NULL) return s_pixels;
    if (!box_logo_kept(NULL)) return NULL;
    char p[160];
    if (!path_of(p, sizeof(p), "logo.bin")) return NULL;
    FILE *f = fopen(p, "rb");
    if (f == NULL) return NULL;
    uint16_t *px = malloc(BL_PIXELS * 2);
    if (px != NULL && (fseek(f, BL_ID_LEN + BL_HEADER, SEEK_SET) != 0 ||
                       fread(px, 2, BL_PIXELS, f) != BL_PIXELS)) {
        free(px);
        px = NULL;
    }
    fclose(f);
    s_pixels = px;
    return s_pixels;
}

void box_logo_unload(void)
{
    free(s_pixels);
    s_pixels = NULL;
}

void box_logo_forget(void)
{
    char p[160];
    if (path_of(p, sizeof(p), "logo.bin")) remove(p);
}

/* ---- the release ------------------------------------------------------------------------- */

bool box_logo_parse_release(const char *text, size_t len, char id[BL_ID_LEN + 1], char sha_hex[65],
                            uint32_t *bytes)
{
    static const char magic[] = "atalaia-box-logo-v1\nid=";
    static const char sha_key[] = "\nsha256=";
    static const char bytes_key[] = "\nbytes=";
    if (len < sizeof(magic) - 1 + BL_ID_LEN || memcmp(text, magic, sizeof(magic) - 1) != 0) {
        return false;
    }
    const char *p = text + sizeof(magic) - 1;
    const char *end = text + len;
    if ((size_t)(end - p) < BL_ID_LEN + sizeof(sha_key) - 1 + 64 + sizeof(bytes_key) - 1 + 2 ||
        !is_hex(p, BL_ID_LEN) || memcmp(p + BL_ID_LEN, sha_key, sizeof(sha_key) - 1) != 0) {
        return false;
    }
    memcpy(id, p, BL_ID_LEN);
    id[BL_ID_LEN] = '\0';
    p += BL_ID_LEN + sizeof(sha_key) - 1;
    if (!is_hex(p, 64) || memcmp(p + 64, bytes_key, sizeof(bytes_key) - 1) != 0) return false;
    memcpy(sha_hex, p, 64);
    sha_hex[64] = '\0';
    p += 64 + sizeof(bytes_key) - 1;
    uint32_t n = 0;
    const char *d = p;
    while (d < end && *d >= '0' && *d <= '9' && n < 100000000u) n = n * 10 + (uint32_t)(*d++ - '0');
    if (d == p || d >= end || *d != '\n' || d + 1 != end) return false;
    *bytes = n;
    return true;
}

void box_logo_path(char *buf, size_t cap, const char *what)
{
    snprintf(buf, cap, "%s%s%s", BL_PATH, what ? "/" : "", what ? what : "");
}

const char *box_logo_result_name(bl_result_t r)
{
    static const char *const names[] = {"kept", "none",    "no_wifi",  "unreachable",
                                        "bad",  "storage", "cancelled"};
    return (unsigned)r < sizeof(names) / sizeof(names[0]) ? names[r] : "?";
}

/* ---- the fetch --------------------------------------------------------------------------- */

static void to_hex(const uint8_t *d, char out[65])
{
    for (int i = 0; i < 32; i++) snprintf(out + 2 * i, 3, "%02x", d[i]);
}

/* The bytes into logo.new (the id, then what came), hashed as they stream; renamed over
 * logo.bin only when whole and as promised. */
static bl_result_t download(const char *base, const fw_io_t *io, const char *id,
                            const char *sha_hex, uint8_t *buf, size_t cap)
{
    char path[48], tmp[160], dst[160];
    box_logo_path(path, sizeof(path), NULL);
    if (!path_of(tmp, sizeof(tmp), "logo.new") || !path_of(dst, sizeof(dst), "logo.bin")) {
        return BL_STORAGE;
    }
    int64_t length = -1;
    if (!io->open(io->ctx, base, path, &length))
        return length == -2 ? BL_BAD : BL_UNREACHABLE; /* a release it then does not serve */
    bl_result_t r = BL_KEPT;
    if (length >= 0 && length != (int64_t)BL_BYTES) r = BL_BAD;
    FILE *f = r == BL_KEPT ? fopen(tmp, "wb") : NULL;
    if (r == BL_KEPT && (f == NULL || fwrite(id, 1, BL_ID_LEN, f) != BL_ID_LEN)) r = BL_STORAGE;
    atalaia_sha256_t sha;
    atalaia_sha256_init(&sha);
    uint8_t head[BL_HEADER] = {0};
    size_t got = 0;
    while (r == BL_KEPT) {
        if (io->cancelled(io->ctx)) {
            r = BL_CANCELLED;
            break;
        }
        int n = io->read(io->ctx, buf, cap);
        if (n < 0) r = BL_UNREACHABLE;
        if (n <= 0) break;
        if (got + (size_t)n > BL_BYTES) {
            r = BL_BAD;
            break;
        }
        for (int i = 0; i < n && got + (size_t)i < BL_HEADER; i++) head[got + (size_t)i] = buf[i];
        got += (size_t)n;
        atalaia_sha256_update(&sha, buf, (size_t)n);
        if (fwrite(buf, 1, (size_t)n, f) != (size_t)n) r = BL_STORAGE;
    }
    io->close(io->ctx);
    if (f != NULL && fclose(f) != 0 && r == BL_KEPT) r = BL_STORAGE;
    if (r == BL_KEPT && got != BL_BYTES) r = BL_BAD;
    if (r == BL_KEPT) {
        uint8_t digest[32];
        char hex[65];
        atalaia_sha256_final(&sha, digest);
        to_hex(digest, hex);
        if (strcmp(hex, sha_hex) != 0 || !header_ok(head)) r = BL_BAD;
    }
    if (r == BL_KEPT && rename(tmp, dst) != 0) {
        remove(dst); /* a file system that does not rename over a file */
        if (rename(tmp, dst) != 0) r = BL_STORAGE;
    }
    if (r != BL_KEPT) remove(tmp);
    return r;
}

bl_result_t box_logo_run(const atalaia_join_t *join, const fw_io_t *io, uint8_t *buf,
                         size_t buf_cap)
{
    if (!join->has_ca || join->url_count == 0) return BL_UNREACHABLE;
    if (buf == NULL || buf_cap < 512) return BL_STORAGE;
    if (io->cancelled(io->ctx)) return BL_CANCELLED;
    if (!io->net_up(io->ctx)) {
        io->net_down(io->ctx);
        return BL_NO_WIFI;
    }
    char path[48], text[BL_TEXT_MAX + 1];
    box_logo_path(path, sizeof(path), "release");
    bl_result_t r = BL_UNREACHABLE;
    const char *base = NULL;
    int n = -1;
    for (uint8_t u = 0; u < join->url_count; u++) {
        if (io->cancelled(io->ctx)) {
            r = BL_CANCELLED;
            break;
        }
        n = io->get_text(io->ctx, join->urls[u], path, text, sizeof(text));
        if (n > 0 || n <= -2) { /* it answered: the address to use */
            base = join->urls[u];
            break;
        }
    }
    if (base != NULL) {
        char id[BL_ID_LEN + 1], sha_hex[65], kept[BL_ID_LEN + 1];
        uint32_t bytes = 0;
        if (n == -2) {
            box_logo_forget(); /* the controller has no logo a box can draw */
            r = BL_NONE;
        } else if (n <= 0 || !box_logo_parse_release(text, (size_t)n, id, sha_hex, &bytes) ||
                   bytes != BL_BYTES) {
            r = BL_BAD;
        } else if (box_logo_kept(kept) && strcmp(kept, id) == 0) {
            r = BL_KEPT;
        } else {
            r = download(base, io, id, sha_hex, buf, buf_cap);
        }
    }
    io->net_down(io->ctx);
    return r;
}
