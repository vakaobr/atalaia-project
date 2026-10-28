/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Firmware updates over the air: the box's checks and the update job (fw_update.h).
 * The formats are protocol/firmware-update.md; the shared Python
 * (controller/atalaia_controller/firmware_release.py) and this file check the same
 * vectors (protocol/vectors/firmware.json). Ed25519 is Monocypher's RFC 8032 check
 * (components/monocypher, decision FU3-2).
 */
#include "fw_update.h"

#include <stdio.h>
#include <string.h>

#include "atalaia/node.h"
#include "monocypher-ed25519.h"
#include "screen_json.h"

static const char *const RESULT_NAMES[] = {
    "installed", "busy",        "bad_offer",   "no_key",        "no_link",
    "no_wifi",   "unreachable", "bad_release", "bad_signature", "wrong_platform",
    "not_newer", "too_big",     "bad_image",   "wrong_board",   "download",
    "bad_hash",  "flash",       "battery",     "cancelled",     "layout",
};

const char *fw_result_name(fw_result_t r)
{
    size_t i = (size_t)r;
    return i < sizeof(RESULT_NAMES) / sizeof(RESULT_NAMES[0]) ? RESULT_NAMES[i] : "?";
}

/* ---- versions ------------------------------------------------------------------------ */

static bool is_digit(char c)
{
    return c >= '0' && c <= '9';
}

static bool is_alnum(char c)
{
    return is_digit(c) || (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z');
}

/* 1-4 digits, then `end` (or NUL when end is 0); *p moves past the digits. */
static bool core_number(const char **p, char end, unsigned *out)
{
    unsigned v = 0;
    int n = 0;
    while (is_digit(**p)) {
        if (++n > 4) return false;
        v = v * 10u + (unsigned)(**p - '0');
        (*p)++;
    }
    if (n == 0 || **p != end) return false;
    *out = v;
    return true;
}

typedef struct {
    unsigned major, minor, patch;
    const char *pre; /* NULL: a release */
    size_t pre_len;
    bool build; /* "+build" metadata: kept in the text, ignored in the order (FV-2) */
} version_t;

/* A pre-release or build metadata: 1-20 of [0-9A-Za-z.], no empty identifier. */
static bool identifiers(const char *p, size_t n)
{
    if (n < 1 || n > 20 || p[n - 1] == '.') return false;
    char prev = '.'; /* so that a leading '.' is an empty identifier */
    for (size_t i = 0; i < n; i++) {
        if (!is_alnum(p[i]) && p[i] != '.') return false;
        if (p[i] == '.' && prev == '.') return false;
        prev = p[i];
    }
    return true;
}

static bool version_split(const char *v, version_t *out)
{
    if (v == NULL || strlen(v) > FW_VERSION_MAX) return false;
    const char *p = v;
    if (!core_number(&p, '.', &out->major)) return false;
    p++;
    if (!core_number(&p, '.', &out->minor)) return false;
    p++;
    const char *q = p;
    while (is_digit(*q)) q++;
    if (!core_number(&p, *q == '-' || *q == '+' ? *q : '\0', &out->patch)) return false;
    out->pre = NULL;
    out->pre_len = 0;
    out->build = false;
    if (*p == '-') {
        p++;
        size_t n = strcspn(p, "+");
        if (!identifiers(p, n)) return false;
        out->pre = p;
        out->pre_len = n;
        p += n;
    }
    if (*p == '+') {
        p++;
        size_t n = strlen(p);
        if (!identifiers(p, n)) return false;
        out->build = true;
        p += n;
    }
    return *p == '\0';
}

bool fw_version_valid(const char *v)
{
    version_t parts;
    return version_split(v, &parts);
}

bool fw_version_valid_plain(const char *v)
{
    version_t parts;
    return version_split(v, &parts) && !parts.build;
}

/* Two numeric identifiers by value, however many digits (leading zeros ignored). */
static int compare_numeric(const char *a, size_t na, const char *b, size_t nb)
{
    while (na > 1 && *a == '0') {
        a++;
        na--;
    }
    while (nb > 1 && *b == '0') {
        b++;
        nb--;
    }
    if (na != nb) return na < nb ? -1 : 1;
    int c = memcmp(a, b, na);
    return c < 0 ? -1 : c > 0;
}

static bool all_digits(const char *s, size_t n)
{
    for (size_t i = 0; i < n; i++) {
        if (!is_digit(s[i])) return false;
    }
    return true;
}

int fw_version_compare(const char *a, const char *b)
{
    version_t x, y;
    if (!version_split(a, &x) || !version_split(b, &y)) return 0;
    if (x.major != y.major) return x.major < y.major ? -1 : 1;
    if (x.minor != y.minor) return x.minor < y.minor ? -1 : 1;
    if (x.patch != y.patch) return x.patch < y.patch ? -1 : 1;
    if (x.pre == NULL || y.pre == NULL) {
        if (x.pre == y.pre) return 0;
        return x.pre == NULL ? 1 : -1; /* a pre-release sorts before its release */
    }
    /* Identifier by identifier, within the pre-release only: the build metadata after it
     * never counts (Semantic Versioning 2.0.0 section 10). */
    const char *p = x.pre, *q = y.pre;
    const char *pe = x.pre + x.pre_len, *qe = y.pre + y.pre_len;
    for (;;) {
        size_t np = 0, nq = 0;
        while (p + np < pe && p[np] != '.') np++;
        while (q + nq < qe && q[nq] != '.') nq++;
        bool dp = all_digits(p, np), dq = all_digits(q, nq);
        int c;
        if (dp && dq) {
            c = compare_numeric(p, np, q, nq);
        } else if (dp != dq) {
            c = dp ? -1 : 1; /* numbers before words */
        } else {
            size_t n = np < nq ? np : nq;
            c = memcmp(p, q, n);
            c = c < 0 ? -1 : c > 0 ? 1 : (np < nq ? -1 : np > nq ? 1 : 0);
        }
        if (c != 0) return c;
        p += np;
        q += nq;
        if (p == pe || q == qe) {
            if (p == pe && q == qe) return 0;
            return p == pe ? -1 : 1; /* fewer identifiers sort first */
        }
        p++;
        q++;
    }
}

/* ---- release texts ---------------------------------------------------------------------- */

static int b64_value(char c)
{
    if (c >= 'A' && c <= 'Z') return c - 'A';
    if (c >= 'a' && c <= 'z') return c - 'a' + 26;
    if (c >= '0' && c <= '9') return c - '0' + 52;
    if (c == '+') return 62;
    if (c == '/') return 63;
    return -1;
}

bool fw_signature_decode(const char *s, size_t n, uint8_t out[64])
{
    if (n != 88 || s[86] != '=' || s[87] != '=') return false;
    uint32_t acc = 0;
    int bits = 0;
    size_t o = 0;
    for (size_t i = 0; i < 86; i++) {
        int v = b64_value(s[i]);
        if (v < 0) return false;
        acc = (acc << 6) | (uint32_t)v;
        bits += 6;
        if (bits >= 8) {
            bits -= 8;
            if (o < 64) out[o++] = (uint8_t)(acc >> bits);
            acc &= (1u << bits) - 1u;
        }
    }
    return o == 64;
}

static int hex_value(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    return -1;
}

/* A line "name=value\n" at *p (within end): value and its length, *p past the line feed. */
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

static bool known_platform(const char *v, size_t n)
{
    static const char *const names[] = {"esp32", "esp32s3", "linux", "android"};
    for (size_t i = 0; i < sizeof(names) / sizeof(names[0]); i++) {
        if (strlen(names[i]) == n && memcmp(names[i], v, n) == 0) return true;
    }
    return false;
}

bool fw_release_parse(const char *text, size_t len, fw_release_t *out)
{
    memset(out, 0, sizeof(*out));
    if (text == NULL || len == 0 || len > FW_RELEASE_TEXT_MAX || memchr(text, '\0', len)) {
        return false;
    }
    const char *p = text, *end = text + len;
    size_t hl = strlen(FW_MANIFEST_HEADER);
    if (len < hl + 1 || memcmp(p, FW_MANIFEST_HEADER, hl) != 0 || p[hl] != '\n') return false;
    p += hl + 1;
    const char *v;
    size_t n;

    if (!take_line(&p, end, "platform", &v, &n) || !known_platform(v, n)) return false;
    memcpy(out->platform, v, n);

    if (!take_line(&p, end, "version", &v, &n) || n > FW_VERSION_MAX) return false;
    memcpy(out->version, v, n);
    out->version[n] = '\0';
    if (!fw_version_valid(out->version)) return false;

    if (!take_line(&p, end, "size", &v, &n) || n < 1 || n > 10 || v[0] == '0') return false;
    uint64_t size = 0;
    for (size_t i = 0; i < n; i++) {
        if (!is_digit(v[i])) return false;
        size = size * 10u + (uint64_t)(v[i] - '0');
    }
    if (size > UINT32_MAX) return false;
    out->size = (uint32_t)size;

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

bool fw_release_signed(const fw_release_t *rel, const char *text, const uint8_t (*keys)[32],
                       size_t key_count)
{
    for (size_t k = 0; k < key_count; k++) {
        if (crypto_ed25519_check(rel->signature, keys[k], (const uint8_t *)text,
                                 rel->manifest_len) == 0) {
            return true;
        }
    }
    return false;
}

int fw_keys_parse(const char *text, uint8_t (*keys)[32], size_t cap)
{
    if (text == NULL) return 0;
    size_t count = 0;
    const char *p = text;
    for (;;) {
        while (*p == ' ' || *p == ',') p++;
        if (*p == '\0') break;
        if (count >= cap) return -1;
        for (size_t i = 0; i < 32; i++) {
            int hi = hex_value(p[0] >= 'A' && p[0] <= 'F' ? (char)(p[0] + 32) : p[0]);
            int lo = hi < 0 ? -1 : hex_value(p[1] >= 'A' && p[1] <= 'F' ? (char)(p[1] + 32) : p[1]);
            if (hi < 0 || lo < 0) return -1;
            keys[count][i] = (uint8_t)(hi << 4 | lo);
            p += 2;
        }
        if (*p != '\0' && *p != ' ' && *p != ',') return -1;
        count++;
    }
    return (int)count;
}

bool fw_offer_parse(const char *params_json, char id[FW_RELEASE_ID_LEN + 1],
                    char version[FW_VERSION_MAX + 1])
{
    char a[FW_RELEASE_ID_LEN + 2], b[FW_VERSION_MAX + 2];
    if (params_json == NULL || !screen_json_str(params_json, "id", a, sizeof(a)) ||
        !screen_json_str(params_json, "version", b, sizeof(b))) {
        return false;
    }
    if (strlen(a) != FW_RELEASE_ID_LEN || !fw_version_valid(b)) return false;
    for (size_t i = 0; i < FW_RELEASE_ID_LEN; i++) {
        if (hex_value(a[i]) < 0) return false;
    }
    memcpy(id, a, FW_RELEASE_ID_LEN + 1);
    memcpy(version, b, strlen(b) + 1); /* fw_version_valid: at most FW_VERSION_MAX */
    return true;
}

/* ---- the image ------------------------------------------------------------------------ */

/* A NUL-terminated ASCII field of n bytes, zeros after the NUL. */
static bool c_field(const uint8_t *f, size_t n, char *out)
{
    const uint8_t *nul = memchr(f, 0, n);
    if (nul == NULL) return false;
    size_t len = (size_t)(nul - f);
    for (size_t i = 0; i < len; i++) {
        if (f[i] < 0x20 || f[i] > 0x7E) return false;
    }
    for (size_t i = len; i < n; i++) {
        if (f[i] != 0) return false;
    }
    memcpy(out, f, len + 1);
    return true;
}

bool fw_image_info(const uint8_t *head, size_t len, fw_image_info_t *out)
{
    memset(out, 0, sizeof(*out));
    if (head == NULL || len < FW_IMAGE_HEAD || head[0] != 0xE9) return false;
    const uint8_t *d = head + FW_APP_DESC_OFFSET;
    uint32_t magic =
        (uint32_t)d[0] | (uint32_t)d[1] << 8 | (uint32_t)d[2] << 16 | (uint32_t)d[3] << 24;
    if (magic != 0xABCD5432u) return false;
    const uint8_t *a = head + FW_DESC_OFFSET;
    if (memcmp(a, "ATFW", 4) != 0 || a[4] != 1) return false;
    out->layout = a[5];
    return c_field(d + 16, 32, out->version) && c_field(d + 48, 32, out->project) &&
           c_field(a + 8, 12, out->variant) && c_field(a + 20, 16, out->board);
}

/* ---- the job -------------------------------------------------------------------------- */

fw_result_t fw_update_precheck(const fw_job_t *job)
{
    if (job->playing) return FW_BUSY;
    if (job->id[0] == '\0' || !fw_version_valid(job->version)) return FW_BAD_OFFER;
    if (job->key_count == 0) return FW_NO_KEY;
    if (job->join == NULL || !job->join->has_ca || job->join->url_count == 0) return FW_NO_LINK;
    if (fw_version_compare(job->version, job->running_version) <= 0) return FW_NOT_NEWER;
    if (job->battery_pct >= 0 && job->battery_pct < job->min_battery_pct) return FW_BATTERY;
    return FW_INSTALLED;
}

/* The release text from the first address that answers; job->base is that address. */
static fw_result_t fetch_release(fw_job_t *job, const fw_io_t *io, char *text, size_t cap, int *len)
{
    char path[64];
    snprintf(path, sizeof(path), "/api/v1/firmware/%s/release", job->id);
    for (uint8_t u = 0; u < job->join->url_count; u++) {
        if (io->cancelled(io->ctx)) return FW_CANCELLED;
        int n = io->get_text(io->ctx, job->join->urls[u], path, text, cap);
        if (n > 0) {
            snprintf(job->base, sizeof(job->base), "%s", job->join->urls[u]);
            *len = n;
            return FW_INSTALLED;
        }
    }
    return FW_UNREACHABLE;
}

static fw_result_t check_release(fw_job_t *job, const char *text, size_t len)
{
    fw_release_t *rel = &job->release;
    if (!fw_release_parse(text, len, rel)) return FW_BAD_RELEASE;
    /* The offer names this exact release: its id is the start of the image's SHA-256. */
    if (memcmp(rel->sha256_hex, job->id, FW_RELEASE_ID_LEN) != 0 ||
        strcmp(rel->version, job->version) != 0) {
        return FW_BAD_RELEASE;
    }
    if (!fw_release_signed(rel, text, job->keys, job->key_count)) return FW_BAD_SIGNATURE;
    if (strcmp(rel->platform, job->platform) != 0) return FW_WRONG_PLATFORM;
    if (fw_version_compare(rel->version, job->running_version) <= 0) return FW_NOT_NEWER;
    if (rel->size > job->slot_size) return FW_TOO_BIG;
    if (rel->size < FW_IMAGE_HEAD) return FW_BAD_IMAGE;
    return FW_INSTALLED;
}

static fw_result_t check_head(const fw_job_t *job, const uint8_t *head)
{
    fw_image_info_t info;
    if (!fw_image_info(head, FW_IMAGE_HEAD, &info)) return FW_BAD_IMAGE;
    if (strcmp(info.version, job->release.version) != 0 ||
        strcmp(info.project, FW_PROJECT_NAME) != 0) {
        return FW_BAD_IMAGE;
    }
    if (strncmp(info.variant, job->desc->variant, sizeof(job->desc->variant)) != 0 ||
        strncmp(info.board, job->desc->board, sizeof(job->desc->board)) != 0) {
        return FW_WRONG_BOARD;
    }
    /* An update cannot change the partition table: an image that needs a newer one than this
     * box runs on is refused before the slot is touched (USB flash required once). */
    if (info.layout > job->layout) return FW_LAYOUT;
    return FW_INSTALLED;
}

/* Streams the image into the inactive slot. Nothing is written until its first bytes passed. */
static fw_result_t download(fw_job_t *job, const fw_io_t *io)
{
    char path[64];
    snprintf(path, sizeof(path), "/api/v1/firmware/%s/image", job->id);
    int64_t length = -1;
    if (!io->open(io->ctx, job->base, path, &length)) return FW_DOWNLOAD;
    fw_result_t r = FW_INSTALLED;
    if (length >= 0 && length != (int64_t)job->release.size) r = FW_DOWNLOAD;

    atalaia_sha256_t sha;
    atalaia_sha256_init(&sha);
    static uint8_t buf[4096]; /* one job at a time (the shell's update task) */
    uint8_t head[FW_IMAGE_HEAD];
    size_t have_head = 0;
    bool begun = false;
    job->written = 0;
    uint32_t got = 0;
    while (r == FW_INSTALLED) {
        if (io->cancelled(io->ctx)) {
            r = FW_CANCELLED;
            break;
        }
        int n = io->read(io->ctx, buf, sizeof(buf));
        if (n < 0) {
            r = FW_DOWNLOAD;
            break;
        }
        if (n == 0) break;
        if ((uint64_t)got + (uint64_t)n > job->release.size) {
            r = FW_DOWNLOAD; /* more than the signed size */
            break;
        }
        got += (uint32_t)n;
        atalaia_sha256_update(&sha, buf, (size_t)n);
        const uint8_t *p = buf;
        size_t left = (size_t)n;
        if (!begun) {
            size_t take = FW_IMAGE_HEAD - have_head < left ? FW_IMAGE_HEAD - have_head : left;
            memcpy(head + have_head, p, take);
            have_head += take;
            p += take;
            left -= take;
            if (have_head < FW_IMAGE_HEAD) continue;
            r = check_head(job, head);
            if (r != FW_INSTALLED) break;
            if (io->flash.begin(io->ctx, job->release.size) != 0) {
                r = FW_FLASH;
                break;
            }
            begun = true;
            if (io->flash.write(io->ctx, head, FW_IMAGE_HEAD) != 0) {
                r = FW_FLASH;
                break;
            }
        }
        if (left > 0 && io->flash.write(io->ctx, p, left) != 0) {
            r = FW_FLASH;
            break;
        }
        job->written = got;
        if (io->progress != NULL) io->progress(io->ctx, got, job->release.size);
    }
    io->close(io->ctx);
    if (r == FW_INSTALLED && got != job->release.size) r = FW_DOWNLOAD;
    if (r == FW_INSTALLED) {
        uint8_t digest[32];
        atalaia_sha256_final(&sha, digest);
        if (memcmp(digest, job->release.sha256, 32) != 0) r = FW_BAD_HASH;
    }
    if (r == FW_INSTALLED) {
        begun = false; /* esp_ota_end frees the slot's handle, valid or not */
        if (io->flash.end(io->ctx) != 0) r = FW_FLASH;
    }
    /* Only now, with the size, the hash and the image checked, does the next boot change. */
    if (r == FW_INSTALLED && io->flash.activate(io->ctx) != 0) r = FW_FLASH;
    if (r != FW_INSTALLED && begun) io->flash.abort(io->ctx);
    return r;
}

size_t fw_report(const atalaia_join_t *join, const char *id, fw_result_t result,
                 const char *version, char *body, size_t cap, char mac_hex[65])
{
    int n = snprintf(body, cap,
                     "atalaia-firmware-report-v1\ngame=%u\nnode=%u\nrelease=%s\nresult=%s\n"
                     "version=%s\n",
                     (unsigned)join->game_id, (unsigned)join->node_id, id, fw_result_name(result),
                     version);
    if (n <= 0 || (size_t)n >= cap) return 0;
    uint8_t mac[32];
    atalaia_hmac_sha256(join->game_key, ATALAIA_JOIN_GAME_KEY, (const uint8_t *)body, (size_t)n,
                        mac);
    for (int i = 0; i < 32; i++) snprintf(mac_hex + 2 * i, 3, "%02x", mac[i]);
    return (size_t)n;
}

fw_result_t fw_update_run(fw_job_t *job, const fw_io_t *io)
{
    memset(&job->release, 0, sizeof(job->release));
    job->base[0] = '\0';
    job->written = 0;
    job->reported = false;
    fw_result_t r = fw_update_precheck(job);
    if (r != FW_INSTALLED) return r;
    if (!io->net_up(io->ctx)) {
        io->net_down(io->ctx);
        return FW_NO_WIFI;
    }
    static char text[FW_RELEASE_TEXT_MAX + 1];
    int len = 0;
    r = fetch_release(job, io, text, sizeof(text), &len);
    if (r == FW_INSTALLED) r = check_release(job, text, (size_t)len);
    if (r == FW_INSTALLED) r = download(job, io);
    if (job->base[0] != '\0') {
        /* The controller hears how it went (the running version on a failure, the new one
         * once it is set to boot). */
        char body[FW_REPORT_MAX], mac[65];
        const char *version = r == FW_INSTALLED ? job->release.version : job->running_version;
        if (fw_report(job->join, job->id, r, version, body, sizeof(body), mac) > 0) {
            job->reported = io->post(io->ctx, job->base, "/api/v1/firmware/report", body, mac);
        }
    }
    io->net_down(io->ctx);
    return r;
}

/* ---- the self-test ---------------------------------------------------------------------- */

/* RFC 8032 section 7.1, TEST 1: the empty message. */
static const uint8_t RFC8032_T1_PUBLIC[32] = {
    0xd7, 0x5a, 0x98, 0x01, 0x82, 0xb1, 0x0a, 0xb7, 0xd5, 0x4b, 0xfe, 0xd3, 0xc9, 0x64, 0x07, 0x3a,
    0x0e, 0xe1, 0x72, 0xf3, 0xda, 0xa6, 0x23, 0x25, 0xaf, 0x02, 0x1a, 0x68, 0xf7, 0x07, 0x51, 0x1a};
static const uint8_t RFC8032_T1_SIGNATURE[64] = {
    0xe5, 0x56, 0x43, 0x00, 0xc3, 0x60, 0xac, 0x72, 0x90, 0x86, 0xe2, 0xcc, 0x80, 0x6e, 0x82, 0x8a,
    0x84, 0x87, 0x7f, 0x1e, 0xb8, 0xe5, 0xd9, 0x74, 0xd8, 0x73, 0xe0, 0x65, 0x22, 0x49, 0x01, 0x55,
    0x5f, 0xb8, 0x82, 0x15, 0x90, 0xa3, 0x3b, 0xac, 0xc6, 0x1e, 0x39, 0x70, 0x1c, 0xf9, 0xb4, 0x6b,
    0xd2, 0x5b, 0xf5, 0xf0, 0x59, 0x5b, 0xbe, 0x24, 0x65, 0x51, 0x41, 0x43, 0x8e, 0x7a, 0x10, 0x0b};

bool fw_update_self_test(const uint8_t (*keys)[32], size_t key_count)
{
    /* Without a release key this image could never be updated over the air again. */
    if (keys == NULL || key_count == 0) return false;

    /* Ed25519: the known answer verifies, a flipped bit does not. */
    uint8_t sig[64];
    memcpy(sig, RFC8032_T1_SIGNATURE, sizeof(sig));
    if (crypto_ed25519_check(sig, RFC8032_T1_PUBLIC, NULL, 0) != 0) return false;
    sig[63] ^= 1;
    if (crypto_ed25519_check(sig, RFC8032_T1_PUBLIC, NULL, 0) == 0) return false;

    /* SHA-256 (FIPS 180-4): "abc". */
    static const uint8_t abc[32] = {0xba, 0x78, 0x16, 0xbf, 0x8f, 0x01, 0xcf, 0xea,
                                    0x41, 0x41, 0x40, 0xde, 0x5d, 0xae, 0x22, 0x23,
                                    0xb0, 0x03, 0x61, 0xa3, 0x96, 0x17, 0x7a, 0x9c,
                                    0xb4, 0x10, 0xff, 0x61, 0xf2, 0x00, 0x15, 0xad};
    uint8_t h[32];
    atalaia_sha256_t s;
    atalaia_sha256_init(&s);
    atalaia_sha256_update(&s, (const uint8_t *)"abc", 3);
    atalaia_sha256_final(&s, h);
    if (memcmp(h, abc, 32) != 0) return false;

    /* The core: a join round trip, then a Lua node runs a script. */
    atalaia_join_t j;
    memset(&j, 0, sizeof(j));
    j.game_id = 1;
    j.node_id = 2;
    j.controller_id = 0;
    j.channel_hz = 869525000u;
    j.max_hops = 2;
    snprintf(j.teams[0], sizeof(j.teams[0]), "red");
    j.team_count = 1;
    snprintf(j.mode_id, sizeof(j.mode_id), "org.atalaia.selftest");
    snprintf(j.role, sizeof(j.role), "box");
    uint8_t key[ATALAIA_JOIN_KEY_SIZE] = {0};
    uint8_t buf[ATALAIA_JOIN_MAX];
    size_t n = atalaia_join_encode(&j, key, buf, sizeof(buf));
    atalaia_join_t back;
    if (n == 0 || atalaia_join_decode(buf, n, key, &back) != ATALAIA_JOIN_OK || back.node_id != 2) {
        return false;
    }
    atalaia_node_config_t cfg;
    memset(&cfg, 0, sizeof(cfg));
    cfg.node_id = 2;
    cfg.mem_limit = 64u * 1024u;
    atalaia_node_t *node = atalaia_node_create(&cfg);
    if (node == NULL) return false;
    static const char script[] = "local t = {}\nfor i = 1, 10 do t[i] = i * i end\n"
                                 "assert(t[10] == 100)\n";
    const char *const teams[] = {"red", "blue"};
    bool ok = atalaia_node_set_teams(node, teams, 2) &&
              atalaia_node_load(node, script, sizeof(script) - 1, "selftest") &&
              atalaia_node_status(node) == ATALAIA_NODE_RUNNING;
    atalaia_node_destroy(node);
    return ok;
}
