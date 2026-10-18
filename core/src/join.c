/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Join payload codec (protocol/join.md), with a small SHA-256 and
 * HMAC-SHA256 so the core needs no crypto library for it: a box checks
 * one join payload, not a stream, so speed does not matter.
 */
#include "atalaia/join.h"

#include <string.h>

#include "atalaia/codec.h"

#include "cbor_int.h"

/* ---- SHA-256 (FIPS 180-4) ------------------------------------------------- */

typedef struct {
    uint32_t h[8];
    uint8_t block[64];
    size_t used;   /* bytes in block */
    uint64_t bits; /* message length so far */
} sha256_t;

static const uint32_t K256[64] = {
    0x428a2f98u, 0x71374491u, 0xb5c0fbcfu, 0xe9b5dba5u, 0x3956c25bu, 0x59f111f1u, 0x923f82a4u,
    0xab1c5ed5u, 0xd807aa98u, 0x12835b01u, 0x243185beu, 0x550c7dc3u, 0x72be5d74u, 0x80deb1feu,
    0x9bdc06a7u, 0xc19bf174u, 0xe49b69c1u, 0xefbe4786u, 0x0fc19dc6u, 0x240ca1ccu, 0x2de92c6fu,
    0x4a7484aau, 0x5cb0a9dcu, 0x76f988dau, 0x983e5152u, 0xa831c66du, 0xb00327c8u, 0xbf597fc7u,
    0xc6e00bf3u, 0xd5a79147u, 0x06ca6351u, 0x14292967u, 0x27b70a85u, 0x2e1b2138u, 0x4d2c6dfcu,
    0x53380d13u, 0x650a7354u, 0x766a0abbu, 0x81c2c92eu, 0x92722c85u, 0xa2bfe8a1u, 0xa81a664bu,
    0xc24b8b70u, 0xc76c51a3u, 0xd192e819u, 0xd6990624u, 0xf40e3585u, 0x106aa070u, 0x19a4c116u,
    0x1e376c08u, 0x2748774cu, 0x34b0bcb5u, 0x391c0cb3u, 0x4ed8aa4au, 0x5b9cca4fu, 0x682e6ff3u,
    0x748f82eeu, 0x78a5636fu, 0x84c87814u, 0x8cc70208u, 0x90befffau, 0xa4506cebu, 0xbef9a3f7u,
    0xc67178f2u,
};

static uint32_t rotr(uint32_t x, unsigned n)
{
    return (x >> n) | (x << (32u - n));
}

static void sha256_compress(sha256_t *s, const uint8_t *p)
{
    uint32_t w[64];
    for (int i = 0; i < 16; i++) {
        w[i] = (uint32_t)p[4 * i] << 24 | (uint32_t)p[4 * i + 1] << 16 |
               (uint32_t)p[4 * i + 2] << 8 | (uint32_t)p[4 * i + 3];
    }
    for (int i = 16; i < 64; i++) {
        uint32_t s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >> 3);
        uint32_t s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >> 10);
        w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    uint32_t a = s->h[0], b = s->h[1], c = s->h[2], d = s->h[3];
    uint32_t e = s->h[4], f = s->h[5], g = s->h[6], h = s->h[7];
    for (int i = 0; i < 64; i++) {
        uint32_t t1 =
            h + (rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)) + ((e & f) ^ (~e & g)) + K256[i] + w[i];
        uint32_t t2 = (rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)) + ((a & b) ^ (a & c) ^ (b & c));
        h = g;
        g = f;
        f = e;
        e = d + t1;
        d = c;
        c = b;
        b = a;
        a = t1 + t2;
    }
    s->h[0] += a;
    s->h[1] += b;
    s->h[2] += c;
    s->h[3] += d;
    s->h[4] += e;
    s->h[5] += f;
    s->h[6] += g;
    s->h[7] += h;
}

static void sha256_init(sha256_t *s)
{
    static const uint32_t iv[8] = {0x6a09e667u, 0xbb67ae85u, 0x3c6ef372u, 0xa54ff53au,
                                   0x510e527fu, 0x9b05688cu, 0x1f83d9abu, 0x5be0cd19u};
    memcpy(s->h, iv, sizeof(iv));
    s->used = 0;
    s->bits = 0;
}

static void sha256_update(sha256_t *s, const uint8_t *p, size_t n)
{
    s->bits += (uint64_t)n * 8u;
    while (n > 0) {
        size_t take = 64 - s->used;
        if (take > n) take = n;
        memcpy(s->block + s->used, p, take);
        s->used += take;
        p += take;
        n -= take;
        if (s->used == 64) {
            sha256_compress(s, s->block);
            s->used = 0;
        }
    }
}

static void sha256_final(sha256_t *s, uint8_t out[32])
{
    uint64_t bits = s->bits;
    uint8_t pad = 0x80;
    sha256_update(s, &pad, 1);
    pad = 0;
    while (s->used != 56) sha256_update(s, &pad, 1);
    uint8_t len[8];
    for (int i = 0; i < 8; i++) len[i] = (uint8_t)(bits >> (56 - 8 * i));
    sha256_update(s, len, 8);
    for (int i = 0; i < 8; i++) {
        out[4 * i] = (uint8_t)(s->h[i] >> 24);
        out[4 * i + 1] = (uint8_t)(s->h[i] >> 16);
        out[4 * i + 2] = (uint8_t)(s->h[i] >> 8);
        out[4 * i + 3] = (uint8_t)s->h[i];
    }
}

void atalaia_sha256(const uint8_t *msg, size_t len, uint8_t out[32])
{
    sha256_t s;
    sha256_init(&s);
    sha256_update(&s, msg, len);
    sha256_final(&s, out);
}

void atalaia_hmac_sha256(const uint8_t *key, size_t key_len, const uint8_t *msg, size_t msg_len,
                         uint8_t out[32])
{
    uint8_t k[64] = {0};
    if (key_len > 64) {
        atalaia_sha256(key, key_len, k);
    } else if (key_len > 0) {
        memcpy(k, key, key_len);
    }
    uint8_t pad[64];
    uint8_t inner[32];
    sha256_t s;

    for (int i = 0; i < 64; i++) pad[i] = (uint8_t)(k[i] ^ 0x36);
    sha256_init(&s);
    sha256_update(&s, pad, 64);
    sha256_update(&s, msg, msg_len);
    sha256_final(&s, inner);

    for (int i = 0; i < 64; i++) pad[i] = (uint8_t)(k[i] ^ 0x5c);
    sha256_init(&s);
    sha256_update(&s, pad, 64);
    sha256_update(&s, inner, 32);
    sha256_final(&s, out);
}

/* ---- Field checks --------------------------------------------------------- */

bool atalaia_join_channel_ok(uint32_t hz)
{
    return (hz >= 868000000u && hz <= 868600000u) || (hz >= 868700000u && hz <= 869200000u) ||
           (hz >= 869400000u && hz <= 869650000u) || (hz >= 869700000u && hz <= 870000000u);
}

/* Valid UTF-8 with no NUL, 1..max bytes. */
static bool text_ok(const char *s, size_t max)
{
    const uint8_t *p = (const uint8_t *)s;
    size_t n = strlen(s);
    if (n == 0 || n > max) return false;
    for (size_t i = 0; i < n;) {
        uint8_t c = p[i];
        size_t len;
        if (c < 0x80) {
            len = 1;
        } else if (c >= 0xC2 && c < 0xE0) {
            len = 2;
        } else if (c >= 0xE0 && c < 0xF0) {
            len = 3;
        } else if (c >= 0xF0 && c < 0xF5) {
            len = 4;
        } else {
            return false;
        }
        if (n - i < len) return false;
        for (size_t k = 1; k < len; k++) {
            if ((p[i + k] & 0xC0) != 0x80) return false;
        }
        if (len > 1) {
            if ((c == 0xE0 && p[i + 1] < 0xA0) || (c == 0xF0 && p[i + 1] < 0x90)) return false;
            if (c == 0xED && p[i + 1] > 0x9F) return false;
            if (c == 0xF4 && p[i + 1] > 0x8F) return false;
        }
        i += len;
    }
    return true;
}

bool atalaia_join_valid(const atalaia_join_t *j)
{
    if (j->game_id == 0 || j->game_id == 0xFFFF) return false;
    if (j->node_id == 0xFFFF || j->controller_id == 0xFFFF) return false;
    if (j->node_id == j->controller_id) return false;
    if (!atalaia_join_channel_ok(j->channel_hz)) return false;
    if (j->max_hops < 1 || j->max_hops > 3) return false;
    if (j->team_count < 1 || j->team_count > ATALAIA_JOIN_TEAMS_MAX) return false;
    for (uint8_t t = 0; t < j->team_count; t++) {
        if (!text_ok(j->teams[t], ATALAIA_JOIN_TEAM_MAX)) return false;
        for (uint8_t u = 0; u < t; u++) {
            if (strcmp(j->teams[t], j->teams[u]) == 0) return false;
        }
    }
    if (!text_ok(j->mode_id, ATALAIA_JOIN_MODE_MAX)) return false;
    if (!text_ok(j->role, ATALAIA_JOIN_ROLE_MAX)) return false;
    if (j->kind > ATALAIA_JOIN_KIND_CONTROLLER) return false;
    return true;
}

const char *atalaia_join_result_name(atalaia_join_result_t result)
{
    switch (result) {
    case ATALAIA_JOIN_OK: return "ok";
    case ATALAIA_JOIN_ERR_LENGTH: return "bad length";
    case ATALAIA_JOIN_ERR_VERSION: return "unknown version";
    case ATALAIA_JOIN_ERR_MAC: return "bad tag (another field's join key, or tampered)";
    case ATALAIA_JOIN_ERR_BODY: return "bad content";
    }
    return "?";
}

/* ---- Encoding ------------------------------------------------------------- */

size_t atalaia_join_encode(const atalaia_join_t *j, const uint8_t join_key[ATALAIA_JOIN_KEY_SIZE],
                           uint8_t *buf, size_t cap)
{
    if (!atalaia_join_valid(j)) return 0;
    if (cap > ATALAIA_JOIN_MAX) cap = ATALAIA_JOIN_MAX;
    if (cap < 1 + ATALAIA_JOIN_MAC_SIZE + 1) return 0;

    buf[0] = ATALAIA_JOIN_VERSION;
    mc_writer_t w;
    mc_init_writer(&w, buf + 1, cap - 1 - ATALAIA_JOIN_MAC_SIZE);
    bool params = j->params_json[0] != '\0';

    mc_put_map(&w, params ? 12 : 11);
    mc_put_uint(&w, ATALAIA_JOIN_K_GAME_ID);
    mc_put_uint(&w, j->game_id);
    mc_put_uint(&w, ATALAIA_JOIN_K_GAME_KEY);
    mc_put_bytes(&w, j->game_key, ATALAIA_JOIN_GAME_KEY);
    mc_put_uint(&w, ATALAIA_JOIN_K_NODE_ID);
    mc_put_uint(&w, j->node_id);
    mc_put_uint(&w, ATALAIA_JOIN_K_CONTROLLER_ID);
    mc_put_uint(&w, j->controller_id);
    mc_put_uint(&w, ATALAIA_JOIN_K_CHANNEL_HZ);
    mc_put_uint(&w, j->channel_hz);
    mc_put_uint(&w, ATALAIA_JOIN_K_MAX_HOPS);
    mc_put_uint(&w, j->max_hops);
    mc_put_uint(&w, ATALAIA_JOIN_K_TEAMS);
    mc_put_array(&w, j->team_count);
    for (uint8_t t = 0; t < j->team_count; t++) mc_put_text(&w, j->teams[t]);
    mc_put_uint(&w, ATALAIA_JOIN_K_MODE_ID);
    mc_put_text(&w, j->mode_id);
    mc_put_uint(&w, ATALAIA_JOIN_K_ROLE);
    mc_put_text(&w, j->role);
    mc_put_uint(&w, ATALAIA_JOIN_K_GAME_SEED);
    mc_put_uint(&w, j->game_seed);
    if (params) {
        mc_put_uint(&w, ATALAIA_JOIN_K_PARAMS);
        if (w.ok) {
            size_t n = atalaia_json_map_encode(j->params_json, w.buf + w.pos, w.cap - w.pos, NULL);
            if (n == 0) {
                w.ok = false;
            } else {
                w.pos += n;
            }
        }
    }
    mc_put_uint(&w, ATALAIA_JOIN_K_KIND);
    mc_put_uint(&w, j->kind);
    if (!w.ok) return 0;

    size_t signed_len = 1 + w.pos;
    atalaia_hmac_sha256(join_key, ATALAIA_JOIN_KEY_SIZE, buf, signed_len, buf + signed_len);
    return signed_len + ATALAIA_JOIN_MAC_SIZE;
}

/* ---- Decoding ------------------------------------------------------------- */

static bool read_uint_max(mc_reader_t *r, uint64_t max, uint64_t *out)
{
    uint64_t v;
    if (!mc_read_uint(r, &v) || v > max) {
        r->ok = false;
        return false;
    }
    *out = v;
    return true;
}

static bool equal_ct(const uint8_t *a, const uint8_t *b, size_t n)
{
    uint8_t diff = 0;
    for (size_t i = 0; i < n; i++) diff |= (uint8_t)(a[i] ^ b[i]);
    return diff == 0;
}

#define JBIT(k) (1u << (k))
#define JOIN_REQUIRED                                                                              \
    (JBIT(ATALAIA_JOIN_K_GAME_ID) | JBIT(ATALAIA_JOIN_K_GAME_KEY) | JBIT(ATALAIA_JOIN_K_NODE_ID) | \
     JBIT(ATALAIA_JOIN_K_CONTROLLER_ID) | JBIT(ATALAIA_JOIN_K_CHANNEL_HZ) |                        \
     JBIT(ATALAIA_JOIN_K_MAX_HOPS) | JBIT(ATALAIA_JOIN_K_TEAMS) | JBIT(ATALAIA_JOIN_K_MODE_ID) |   \
     JBIT(ATALAIA_JOIN_K_ROLE) | JBIT(ATALAIA_JOIN_K_GAME_SEED) | JBIT(ATALAIA_JOIN_K_KIND))

/* A text field into out (cap includes the NUL); NUL bytes inside are refused. */
static bool read_text(mc_reader_t *r, char *out, size_t cap)
{
    size_t n = 0;
    if (!mc_read_text(r, out, cap, &n)) return false;
    if (strlen(out) != n) {
        r->ok = false;
        return false;
    }
    return true;
}

static bool decode_body(const uint8_t *body, size_t len, atalaia_join_t *j)
{
    mc_reader_t r;
    mc_init_reader(&r, body, len);
    memset(j, 0, sizeof(*j));
    uint32_t seen = 0;

    uint64_t count;
    if (!mc_read_map(&r, &count)) return false;
    for (uint64_t i = 0; i < count && r.ok; i++) {
        uint64_t key, v;
        /* Keys 13-31 are reserved for optional fields (skipped); 32 and up are invalid. */
        if (!mc_read_uint(&r, &key) || key >= 32) return false;
        if (seen & JBIT(key)) return false; /* duplicate key */
        seen |= JBIT(key);
        switch (key) {
        case ATALAIA_JOIN_K_GAME_ID:
            if (!read_uint_max(&r, UINT16_MAX, &v)) return false;
            j->game_id = (uint16_t)v;
            break;
        case ATALAIA_JOIN_K_GAME_KEY: {
            size_t n = 0;
            if (!mc_read_bytes(&r, j->game_key, sizeof(j->game_key), &n) ||
                n != ATALAIA_JOIN_GAME_KEY) {
                return false;
            }
            break;
        }
        case ATALAIA_JOIN_K_NODE_ID:
            if (!read_uint_max(&r, UINT16_MAX, &v)) return false;
            j->node_id = (uint16_t)v;
            break;
        case ATALAIA_JOIN_K_CONTROLLER_ID:
            if (!read_uint_max(&r, UINT16_MAX, &v)) return false;
            j->controller_id = (uint16_t)v;
            break;
        case ATALAIA_JOIN_K_CHANNEL_HZ:
            if (!read_uint_max(&r, UINT32_MAX, &v)) return false;
            j->channel_hz = (uint32_t)v;
            break;
        case ATALAIA_JOIN_K_MAX_HOPS:
            if (!read_uint_max(&r, UINT8_MAX, &v)) return false;
            j->max_hops = (uint8_t)v;
            break;
        case ATALAIA_JOIN_K_TEAMS: {
            uint64_t n;
            if (!mc_read_array(&r, &n) || n > ATALAIA_JOIN_TEAMS_MAX) return false;
            for (uint64_t t = 0; t < n; t++) {
                if (!read_text(&r, j->teams[t], sizeof(j->teams[t]))) return false;
            }
            j->team_count = (uint8_t)n;
            break;
        }
        case ATALAIA_JOIN_K_MODE_ID:
            if (!read_text(&r, j->mode_id, sizeof(j->mode_id))) return false;
            break;
        case ATALAIA_JOIN_K_ROLE:
            if (!read_text(&r, j->role, sizeof(j->role))) return false;
            break;
        case ATALAIA_JOIN_K_GAME_SEED:
            if (!read_uint_max(&r, UINT32_MAX, &v)) return false;
            j->game_seed = (uint32_t)v;
            break;
        case ATALAIA_JOIN_K_PARAMS: {
            size_t used = 0;
            if (!atalaia_json_map_decode(r.p, mc_remaining(&r), &used, j->params_json,
                                         sizeof(j->params_json), NULL)) {
                return false;
            }
            r.p += used;
            break;
        }
        case ATALAIA_JOIN_K_KIND:
            if (!read_uint_max(&r, UINT8_MAX, &v)) return false;
            j->kind = (uint8_t)v;
            break;
        default:
            if (!mc_skip_value(&r)) return false;
            break;
        }
    }
    if (!r.ok || r.p != r.end || (seen & JOIN_REQUIRED) != JOIN_REQUIRED) return false;
    return atalaia_join_valid(j);
}

atalaia_join_result_t atalaia_join_decode(const uint8_t *buf, size_t len,
                                          const uint8_t join_key[ATALAIA_JOIN_KEY_SIZE],
                                          atalaia_join_t *out)
{
    if (len < 1 + 1 + ATALAIA_JOIN_MAC_SIZE || len > ATALAIA_JOIN_MAX) {
        return ATALAIA_JOIN_ERR_LENGTH;
    }
    if (buf[0] != ATALAIA_JOIN_VERSION) return ATALAIA_JOIN_ERR_VERSION;

    size_t signed_len = len - ATALAIA_JOIN_MAC_SIZE;
    uint8_t mac[ATALAIA_JOIN_MAC_SIZE];
    atalaia_hmac_sha256(join_key, ATALAIA_JOIN_KEY_SIZE, buf, signed_len, mac);
    if (!equal_ct(mac, buf + signed_len, ATALAIA_JOIN_MAC_SIZE)) return ATALAIA_JOIN_ERR_MAC;

    atalaia_join_t j;
    if (!decode_body(buf + 1, signed_len - 1, &j)) {
        memset(&j, 0, sizeof(j));
        return ATALAIA_JOIN_ERR_BODY;
    }
    *out = j;
    memset(&j, 0, sizeof(j)); /* the game key */
    return ATALAIA_JOIN_OK;
}

/* ---- Text form (base64url, no padding) ------------------------------------ */

static const char B64URL[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";

static int b64_value(char c)
{
    if (c >= 'A' && c <= 'Z') return c - 'A';
    if (c >= 'a' && c <= 'z') return c - 'a' + 26;
    if (c >= '0' && c <= '9') return c - '0' + 52;
    if (c == '-') return 62;
    if (c == '_') return 63;
    return -1;
}

static bool is_space(char c)
{
    return c == ' ' || c == '\t' || c == '\r' || c == '\n';
}

size_t atalaia_join_from_text(const char *text, uint8_t *buf, size_t cap)
{
    while (is_space(*text)) text++;
    size_t plen = strlen(ATALAIA_JOIN_TEXT_PREFIX);
    if (strncmp(text, ATALAIA_JOIN_TEXT_PREFIX, plen) != 0) return 0;
    text += plen;
    size_t n = strlen(text);
    while (n > 0 && is_space(text[n - 1])) n--;
    if (n % 4 == 1) return 0; /* not a whole number of bytes */

    size_t out = 0;
    uint32_t acc = 0;
    int bits = 0;
    for (size_t i = 0; i < n; i++) {
        int v = b64_value(text[i]);
        if (v < 0) return 0;
        acc = (acc << 6) | (uint32_t)v;
        bits += 6;
        if (bits >= 8) {
            bits -= 8;
            if (out >= cap) return 0;
            buf[out++] = (uint8_t)(acc >> bits);
        }
    }
    /* Unused low bits of the last character must be zero (canonical form). */
    if (bits > 0 && (acc & ((1u << bits) - 1u)) != 0) return 0;
    return out;
}

size_t atalaia_join_to_text(const uint8_t *payload, size_t len, char *text, size_t cap)
{
    size_t plen = strlen(ATALAIA_JOIN_TEXT_PREFIX);
    size_t need = plen + (len * 4 + 2) / 3 + 1;
    if (need > cap) return 0;
    memcpy(text, ATALAIA_JOIN_TEXT_PREFIX, plen);
    size_t o = plen;
    uint32_t acc = 0;
    int bits = 0;
    for (size_t i = 0; i < len; i++) {
        acc = (acc << 8) | payload[i];
        bits += 8;
        while (bits >= 6) {
            bits -= 6;
            text[o++] = B64URL[(acc >> bits) & 0x3F];
        }
    }
    if (bits > 0) text[o++] = B64URL[(acc << (6 - bits)) & 0x3F];
    text[o] = '\0';
    return o;
}

/* ---- NFC Forum Type 2 tag (NTAG215/216) ----------------------------------- */

#define TLV_NULL       0x00
#define TLV_NDEF       0x03
#define TLV_TERMINATOR 0xFE
#define NDEF_MB        0x80
#define NDEF_ME        0x40
#define NDEF_CF        0x20
#define NDEF_SR        0x10
#define NDEF_IL        0x08
#define NDEF_TNF_MIME  0x02

/* Finds the join record in an NDEF message. */
static size_t find_record(const uint8_t *m, size_t len, const uint8_t **payload)
{
    size_t type_len = strlen(ATALAIA_JOIN_NDEF_TYPE);
    size_t i = 0;
    while (i < len) {
        uint8_t hdr = m[i++];
        if (hdr & NDEF_CF) return 0; /* chunked records are not used */
        if (i >= len) return 0;
        size_t tlen = m[i++];
        size_t plen;
        if (hdr & NDEF_SR) {
            if (i >= len) return 0;
            plen = m[i++];
        } else {
            if (len - i < 4) return 0;
            plen = (size_t)m[i] << 24 | (size_t)m[i + 1] << 16 | (size_t)m[i + 2] << 8 | m[i + 3];
            i += 4;
        }
        size_t idlen = 0;
        if (hdr & NDEF_IL) {
            if (i >= len) return 0;
            idlen = m[i++];
        }
        if (tlen > len - i) return 0;
        const uint8_t *type = m + i;
        i += tlen;
        if (idlen > len - i) return 0;
        i += idlen;
        if (plen > len - i) return 0;
        if ((hdr & 0x07) == NDEF_TNF_MIME && tlen == type_len &&
            memcmp(type, ATALAIA_JOIN_NDEF_TYPE, type_len) == 0) {
            *payload = m + i;
            return plen;
        }
        i += plen;
        if (hdr & NDEF_ME) return 0;
    }
    return 0;
}

size_t atalaia_join_from_ndef_tag(const uint8_t *mem, size_t len, const uint8_t **payload)
{
    size_t i = 0;
    while (i < len) {
        uint8_t t = mem[i++];
        if (t == TLV_NULL) continue;
        if (t == TLV_TERMINATOR) return 0;
        if (i >= len) return 0;
        size_t l = mem[i++];
        if (l == 0xFF) {
            if (len - i < 2) return 0;
            l = (size_t)mem[i] << 8 | mem[i + 1];
            i += 2;
        }
        if (l > len - i) return 0;
        if (t == TLV_NDEF) return find_record(mem + i, l, payload);
        i += l; /* lock or memory control TLV, or one we do not know */
    }
    return 0;
}

size_t atalaia_join_to_ndef_tag(const uint8_t *payload, size_t len, uint8_t *mem, size_t cap)
{
    size_t type_len = strlen(ATALAIA_JOIN_NDEF_TYPE);
    bool sr = len < 256;
    size_t rec_len = 2 + (sr ? 1 : 4) + type_len + len;
    size_t tlv_head = rec_len < 0xFF ? 2 : 4;
    size_t total = tlv_head + rec_len + 1;
    if (total > cap) return 0;

    size_t o = 0;
    mem[o++] = TLV_NDEF;
    if (rec_len < 0xFF) {
        mem[o++] = (uint8_t)rec_len;
    } else {
        mem[o++] = 0xFF;
        mem[o++] = (uint8_t)(rec_len >> 8);
        mem[o++] = (uint8_t)rec_len;
    }
    mem[o++] = (uint8_t)(NDEF_MB | NDEF_ME | (sr ? NDEF_SR : 0) | NDEF_TNF_MIME);
    mem[o++] = (uint8_t)type_len;
    if (sr) {
        mem[o++] = (uint8_t)len;
    } else {
        mem[o++] = (uint8_t)(len >> 24);
        mem[o++] = (uint8_t)(len >> 16);
        mem[o++] = (uint8_t)(len >> 8);
        mem[o++] = (uint8_t)len;
    }
    memcpy(mem + o, ATALAIA_JOIN_NDEF_TYPE, type_len);
    o += type_len;
    memcpy(mem + o, payload, len);
    o += len;
    mem[o++] = TLV_TERMINATOR;
    return o;
}
