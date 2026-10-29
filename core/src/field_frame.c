/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Field frames: announcements, discoveries and invitations outside any game
 * (atalaia/field_frame.h, protocol/field-frames.md).
 */
#include "atalaia/field_frame.h"

#include <string.h>

#include "atalaia/protocol.h"

#include "cbor_int.h"

#define BIT(k) (1u << (k))

_Static_assert(ATALAIA_FF_TYPE == ATALAIA_MSG_FIELD, "the field frames' message type");

/* ---- HKDF-SHA256 (RFC 5869) ------------------------------------------------ */

#define HKDF_INFO_MAX 255

bool atalaia_hkdf_sha256(const uint8_t *salt, size_t salt_len, const uint8_t *ikm, size_t ikm_len,
                         const uint8_t *info, size_t info_len, uint8_t *out, size_t out_len)
{
    if (out_len > 255u * 32u || info_len > HKDF_INFO_MAX || (info_len > 0 && info == NULL)) {
        return false;
    }
    /* Extract: PRK = HMAC(salt, IKM); no salt is HashLen zero bytes. */
    static const uint8_t zeros[32] = {0};
    uint8_t prk[32];
    if (salt == NULL || salt_len == 0) {
        atalaia_hmac_sha256(zeros, sizeof(zeros), ikm, ikm_len, prk);
    } else {
        atalaia_hmac_sha256(salt, salt_len, ikm, ikm_len, prk);
    }
    /* Expand: T(i) = HMAC(PRK, T(i-1) | info | i). */
    uint8_t block[32 + HKDF_INFO_MAX + 1];
    uint8_t t[32] = {0};
    size_t t_len = 0;
    size_t done = 0;
    for (uint8_t i = 1; done < out_len; i++) {
        size_t n = 0;
        memcpy(block, t, t_len);
        n += t_len;
        if (info_len > 0) memcpy(block + n, info, info_len);
        n += info_len;
        block[n++] = i;
        atalaia_hmac_sha256(prk, sizeof(prk), block, n, t);
        t_len = sizeof(t);
        size_t take = out_len - done < sizeof(t) ? out_len - done : sizeof(t);
        memcpy(out + done, t, take);
        done += take;
    }
    memset(prk, 0, sizeof(prk));
    memset(t, 0, sizeof(t));
    memset(block, 0, sizeof(block));
    return true;
}

void atalaia_ff_key(const uint8_t join_key[ATALAIA_JOIN_KEY_SIZE], uint8_t out[ATALAIA_FF_KEY_SIZE])
{
    atalaia_hkdf_sha256(NULL, 0, join_key, ATALAIA_JOIN_KEY_SIZE, (const uint8_t *)ATALAIA_FF_LABEL,
                        sizeof(ATALAIA_FF_LABEL) - 1, out, ATALAIA_FF_KEY_SIZE);
}

void atalaia_ff_nonce_key(const uint8_t join_key[ATALAIA_JOIN_KEY_SIZE], uint8_t out[32])
{
    atalaia_hkdf_sha256(NULL, 0, join_key, ATALAIA_JOIN_KEY_SIZE,
                        (const uint8_t *)ATALAIA_FF_NONCE_LABEL, sizeof(ATALAIA_FF_NONCE_LABEL) - 1,
                        out, 32);
}

void atalaia_ff_nonce(const uint8_t nonce_key[32], const uint8_t sender[ATALAIA_FF_SENDER_SIZE],
                      uint32_t boot, uint16_t ctr, uint8_t out[ATALAIA_FF_NONCE_SIZE])
{
    uint8_t mac[32];
    atalaia_hmac_sha256(nonce_key, 32, sender, ATALAIA_FF_SENDER_SIZE, mac);
    memcpy(out, mac, 8);
    out[8] = (uint8_t)(boot >> 16);
    out[9] = (uint8_t)(boot >> 8);
    out[10] = (uint8_t)boot;
    out[11] = (uint8_t)(ctr >> 8);
    out[12] = (uint8_t)ctr;
}

/* ---- Bodies ------------------------------------------------------------------ */

static bool announce_ok(const atalaia_ff_msg_t *m)
{
    if (!atalaia_join_text_ok(m->name, ATALAIA_FF_NAME_MAX) || m->tier > 2) return false;
    if (m->last_game == 0xFFFF) return false;
    if (m->last_role[0] != '\0' && !atalaia_join_text_ok(m->last_role, ATALAIA_JOIN_ROLE_MAX)) {
        return false;
    }
    if (m->battery_pct != 0xFF && m->battery_pct > 100) return false;
    return m->answer == 0 || m->result <= ATALAIA_FF_ENDED;
}

static bool invite_ok(const atalaia_ff_msg_t *m)
{
    return m->invite_id != 0 && m->parts >= 1 && m->parts <= ATALAIA_FF_PARTS_MAX &&
           m->part < m->parts && m->chunk_len >= 1 && m->chunk_len <= ATALAIA_FF_CHUNK_MAX;
}

size_t atalaia_ff_body_encode(const atalaia_ff_msg_t *m, uint8_t *buf, size_t cap)
{
    mc_writer_t w;
    mc_init_writer(&w, buf, cap < ATALAIA_FF_BODY_MAX ? cap : ATALAIA_FF_BODY_MAX);
    switch (m->kind) {
    case ATALAIA_FF_ANNOUNCE:
        if (!announce_ok(m)) return 0;
        mc_put_map(&w, (uint64_t)5 + (m->last_game != 0) + (m->last_role[0] != '\0') +
                           (m->battery_pct != 0xFF) + (m->answer != 0 ? 2u : 0u));
        mc_put_uint(&w, ATALAIA_FF_K_KIND);
        mc_put_uint(&w, m->kind);
        mc_put_uint(&w, ATALAIA_FF_K_DEVICE);
        mc_put_bytes(&w, m->device_id, ATALAIA_FF_DEVICE_SIZE);
        mc_put_uint(&w, ATALAIA_FF_K_TOKEN);
        mc_put_bytes(&w, m->token, ATALAIA_FF_TOKEN_SIZE);
        mc_put_uint(&w, ATALAIA_FF_K_NAME);
        mc_put_text(&w, m->name);
        mc_put_uint(&w, ATALAIA_FF_K_TIER);
        mc_put_uint(&w, m->tier);
        if (m->last_game != 0) {
            mc_put_uint(&w, ATALAIA_FF_K_LAST_GAME);
            mc_put_uint(&w, m->last_game);
        }
        if (m->last_role[0] != '\0') {
            mc_put_uint(&w, ATALAIA_FF_K_LAST_ROLE);
            mc_put_text(&w, m->last_role);
        }
        if (m->battery_pct != 0xFF) {
            mc_put_uint(&w, ATALAIA_FF_K_BATTERY);
            mc_put_uint(&w, m->battery_pct);
        }
        if (m->answer != 0) {
            mc_put_uint(&w, ATALAIA_FF_K_ANSWER);
            mc_put_uint(&w, m->answer);
            mc_put_uint(&w, ATALAIA_FF_K_RESULT);
            mc_put_uint(&w, m->result);
        }
        break;
    case ATALAIA_FF_DISCOVER:
        mc_put_map(&w, 1);
        mc_put_uint(&w, ATALAIA_FF_K_KIND);
        mc_put_uint(&w, m->kind);
        break;
    case ATALAIA_FF_INVITE:
        if (!invite_ok(m)) return 0;
        mc_put_map(&w, 7);
        mc_put_uint(&w, ATALAIA_FF_K_KIND);
        mc_put_uint(&w, m->kind);
        mc_put_uint(&w, ATALAIA_FF_K_DEVICE);
        mc_put_bytes(&w, m->device_id, ATALAIA_FF_DEVICE_SIZE);
        mc_put_uint(&w, ATALAIA_FF_K_TOKEN);
        mc_put_bytes(&w, m->token, ATALAIA_FF_TOKEN_SIZE);
        mc_put_uint(&w, ATALAIA_FF_K_INVITE);
        mc_put_uint(&w, m->invite_id);
        mc_put_uint(&w, ATALAIA_FF_K_PART);
        mc_put_uint(&w, m->part);
        mc_put_uint(&w, ATALAIA_FF_K_PARTS);
        mc_put_uint(&w, m->parts);
        mc_put_uint(&w, ATALAIA_FF_K_CHUNK);
        mc_put_bytes(&w, m->chunk, m->chunk_len);
        break;
    case ATALAIA_FF_GAME_OVER:
        if (m->game_id == 0 || m->game_id == 0xFFFF) return 0;
        mc_put_map(&w, 3);
        mc_put_uint(&w, ATALAIA_FF_K_KIND);
        mc_put_uint(&w, m->kind);
        mc_put_uint(&w, ATALAIA_FF_K_GAME);
        mc_put_uint(&w, m->game_id);
        mc_put_uint(&w, ATALAIA_FF_K_KEY_TAG);
        mc_put_bytes(&w, m->key_tag, ATALAIA_FF_TAG_SIZE);
        break;
    case ATALAIA_FF_MOVE:
        if (m->channel_hz == 0 || m->rev == 0) return 0;
        mc_put_map(&w, 3);
        mc_put_uint(&w, ATALAIA_FF_K_KIND);
        mc_put_uint(&w, m->kind);
        mc_put_uint(&w, ATALAIA_FF_K_CHANNEL);
        mc_put_uint(&w, m->channel_hz);
        mc_put_uint(&w, ATALAIA_FF_K_REV);
        mc_put_uint(&w, m->rev);
        break;
    default: return 0;
    }
    return w.ok ? w.pos : 0;
}

static bool read_uint_max(mc_reader_t *r, uint64_t max, uint64_t *out)
{
    if (!mc_read_uint(r, out) || *out > max) {
        r->ok = false;
        return false;
    }
    return true;
}

static bool read_fixed(mc_reader_t *r, uint8_t *out, size_t size)
{
    size_t n = 0;
    return mc_read_bytes(r, out, size, &n) && n == size;
}

static bool read_text_field(mc_reader_t *r, char *out, size_t cap)
{
    size_t n = 0;
    return mc_read_text(r, out, cap, &n) && atalaia_join_text_ok(out, cap - 1) && strlen(out) == n;
}

/* The fields each kind may carry, and must. */
#define ANNOUNCE_KEYS                                                                              \
    (BIT(ATALAIA_FF_K_KIND) | BIT(ATALAIA_FF_K_DEVICE) | BIT(ATALAIA_FF_K_TOKEN) |                 \
     BIT(ATALAIA_FF_K_NAME) | BIT(ATALAIA_FF_K_TIER) | BIT(ATALAIA_FF_K_LAST_GAME) |               \
     BIT(ATALAIA_FF_K_LAST_ROLE) | BIT(ATALAIA_FF_K_BATTERY) | BIT(ATALAIA_FF_K_ANSWER) |          \
     BIT(ATALAIA_FF_K_RESULT))
#define ANNOUNCE_REQUIRED                                                                          \
    (BIT(ATALAIA_FF_K_KIND) | BIT(ATALAIA_FF_K_DEVICE) | BIT(ATALAIA_FF_K_TOKEN) |                 \
     BIT(ATALAIA_FF_K_NAME) | BIT(ATALAIA_FF_K_TIER))
#define INVITE_KEYS                                                                                \
    (BIT(ATALAIA_FF_K_KIND) | BIT(ATALAIA_FF_K_DEVICE) | BIT(ATALAIA_FF_K_TOKEN) |                 \
     BIT(ATALAIA_FF_K_INVITE) | BIT(ATALAIA_FF_K_PART) | BIT(ATALAIA_FF_K_PARTS) |                 \
     BIT(ATALAIA_FF_K_CHUNK))
#define GAME_OVER_KEYS (BIT(ATALAIA_FF_K_KIND) | BIT(ATALAIA_FF_K_GAME) | BIT(ATALAIA_FF_K_KEY_TAG))
#define MOVE_KEYS      (BIT(ATALAIA_FF_K_KIND) | BIT(ATALAIA_FF_K_CHANNEL) | BIT(ATALAIA_FF_K_REV))
#define KNOWN_KEYS     0x7FEu /* keys 1-10: a key another kind uses is not "unknown" */

bool atalaia_ff_body_decode(const uint8_t *buf, size_t len, atalaia_ff_msg_t *m)
{
    memset(m, 0, sizeof(*m));
    m->battery_pct = 0xFF;
    if (len == 0 || len > ATALAIA_FF_BODY_MAX) return false;
    /* The kind comes first in every body: read it, then the rest knowing what is allowed. */
    mc_reader_t r;
    mc_init_reader(&r, buf, len);
    uint64_t count, key, v;
    if (!mc_read_map(&r, &count) || count == 0 || count > 31) return false;
    if (!mc_read_uint(&r, &key) || key != ATALAIA_FF_K_KIND || !read_uint_max(&r, 255, &v)) {
        return false;
    }
    m->kind = (uint8_t)v;
    uint32_t allowed, required;
    switch (m->kind) {
    case ATALAIA_FF_ANNOUNCE:
        allowed = ANNOUNCE_KEYS;
        required = ANNOUNCE_REQUIRED;
        break;
    case ATALAIA_FF_DISCOVER:
        allowed = BIT(ATALAIA_FF_K_KIND);
        required = BIT(ATALAIA_FF_K_KIND);
        break;
    case ATALAIA_FF_INVITE:
        allowed = INVITE_KEYS;
        required = INVITE_KEYS;
        break;
    case ATALAIA_FF_GAME_OVER:
        allowed = GAME_OVER_KEYS;
        required = GAME_OVER_KEYS;
        break;
    case ATALAIA_FF_MOVE:
        allowed = MOVE_KEYS;
        required = MOVE_KEYS;
        break;
    default: return false;
    }
    uint32_t seen = BIT(ATALAIA_FF_K_KIND);
    for (uint64_t i = 1; i < count && r.ok; i++) {
        if (!mc_read_uint(&r, &key) || key >= 32 || (seen & BIT(key))) return false;
        seen |= BIT(key);
        if (!(allowed & BIT(key))) {
            /* Unknown keys up to 31 are skipped (later optional fields); another kind's
             * keys are not this kind's. */
            if (KNOWN_KEYS & BIT(key)) return false;
            if (!mc_skip_value(&r)) return false;
            continue;
        }
        bool ok = true;
        if (m->kind == ATALAIA_FF_GAME_OVER) {
            if (key == ATALAIA_FF_K_GAME) {
                ok = read_uint_max(&r, 0xFFFE, &v) && v != 0;
                m->game_id = (uint16_t)v;
            } else {
                ok = read_fixed(&r, m->key_tag, ATALAIA_FF_TAG_SIZE);
            }
        } else if (m->kind == ATALAIA_FF_MOVE) {
            ok = read_uint_max(&r, 0xFFFFFFFFu, &v) && v != 0;
            if (key == ATALAIA_FF_K_CHANNEL) {
                m->channel_hz = (uint32_t)v;
            } else {
                m->rev = (uint32_t)v;
            }
        } else if (key == ATALAIA_FF_K_DEVICE) {
            ok = read_fixed(&r, m->device_id, ATALAIA_FF_DEVICE_SIZE);
        } else if (key == ATALAIA_FF_K_TOKEN) {
            ok = read_fixed(&r, m->token, ATALAIA_FF_TOKEN_SIZE);
        } else if (m->kind == ATALAIA_FF_ANNOUNCE) {
            switch (key) {
            case ATALAIA_FF_K_NAME: ok = read_text_field(&r, m->name, sizeof(m->name)); break;
            case ATALAIA_FF_K_TIER:
                ok = read_uint_max(&r, 2, &v);
                m->tier = (uint8_t)v;
                break;
            case ATALAIA_FF_K_LAST_GAME:
                ok = read_uint_max(&r, 0xFFFE, &v) && v != 0;
                m->last_game = (uint16_t)v;
                break;
            case ATALAIA_FF_K_LAST_ROLE:
                ok = read_text_field(&r, m->last_role, sizeof(m->last_role));
                break;
            case ATALAIA_FF_K_BATTERY:
                ok = read_uint_max(&r, 100, &v);
                m->battery_pct = (uint8_t)v;
                break;
            case ATALAIA_FF_K_ANSWER:
                ok = read_uint_max(&r, 0xFFFF, &v) && v != 0;
                m->answer = (uint16_t)v;
                break;
            case ATALAIA_FF_K_RESULT:
                ok = read_uint_max(&r, ATALAIA_FF_ENDED, &v);
                m->result = (uint8_t)v;
                break;
            default: ok = false; break;
            }
        } else { /* INVITE */
            switch (key) {
            case ATALAIA_FF_K_INVITE:
                ok = read_uint_max(&r, 0xFFFF, &v) && v != 0;
                m->invite_id = (uint16_t)v;
                break;
            case ATALAIA_FF_K_PART:
                ok = read_uint_max(&r, ATALAIA_FF_PARTS_MAX - 1, &v);
                m->part = (uint8_t)v;
                break;
            case ATALAIA_FF_K_PARTS:
                ok = read_uint_max(&r, ATALAIA_FF_PARTS_MAX, &v) && v != 0;
                m->parts = (uint8_t)v;
                break;
            case ATALAIA_FF_K_CHUNK: {
                size_t n = 0;
                ok = mc_read_bytes(&r, m->chunk, sizeof(m->chunk), &n) && n != 0;
                m->chunk_len = (uint8_t)n;
                break;
            }
            default: ok = false; break;
            }
        }
        if (!ok) return false;
    }
    if (!r.ok || r.p != r.end || (seen & required) != required) return false;
    /* An answer always says how the invite went. */
    if (m->kind == ATALAIA_FF_ANNOUNCE &&
        ((seen & BIT(ATALAIA_FF_K_ANSWER)) != 0) != ((seen & BIT(ATALAIA_FF_K_RESULT)) != 0)) {
        return false;
    }
    if (m->kind == ATALAIA_FF_INVITE && m->part >= m->parts) return false;
    return true;
}

/* ---- Frames ------------------------------------------------------------------- */

static const atalaia_header_t FF_HEADER = {
    .version_flags = ATALAIA_VF_MAKE(1, 1, 0, 1), /* v1, normal, no ACK, encrypted */
    .game_id = 0,
    .source = 0,
    .seq = 0,
    .hop_limit = 0,
    .type = ATALAIA_FF_TYPE,
};

bool atalaia_ff_is_frame(const uint8_t *pkt, size_t len)
{
    atalaia_header_t h;
    if (pkt == NULL || len < ATALAIA_FF_MIN || len > ATALAIA_FF_MAX) return false;
    if (!atalaia_header_decode(pkt, &h)) return false;
    return h.game_id == 0 && h.type == ATALAIA_FF_TYPE && ATALAIA_VF_ENC(h.version_flags);
}

size_t atalaia_ff_seal(const uint8_t key[ATALAIA_FF_KEY_SIZE],
                       const uint8_t nonce[ATALAIA_FF_NONCE_SIZE], const uint8_t *body,
                       size_t body_len, uint8_t *out, size_t cap,
                       const atalaia_crypto_ops_t *crypto)
{
    size_t total = ATALAIA_RF_HEADER_SIZE + ATALAIA_FF_NONCE_SIZE + body_len + ATALAIA_RF_MIC_SIZE;
    if (key == NULL || nonce == NULL || body == NULL || out == NULL || crypto == NULL ||
        crypto->encrypt == NULL || body_len == 0 || body_len > ATALAIA_FF_BODY_MAX || total > cap) {
        return 0;
    }
    atalaia_header_encode(&FF_HEADER, out);
    memcpy(out + ATALAIA_RF_HEADER_SIZE, nonce, ATALAIA_FF_NONCE_SIZE);
    uint8_t aad[ATALAIA_RF_AAD_SIZE];
    atalaia_aad_extract(out, aad);
    uint8_t *ct = out + ATALAIA_RF_HEADER_SIZE + ATALAIA_FF_NONCE_SIZE;
    if (crypto->encrypt(crypto->ctx, key, nonce, ATALAIA_FF_NONCE_SIZE, aad, sizeof(aad), body,
                        body_len, ct, ct + body_len, ATALAIA_RF_MIC_SIZE) != 0) {
        return 0;
    }
    return total;
}

size_t atalaia_ff_open(const uint8_t key[ATALAIA_FF_KEY_SIZE], const uint8_t *pkt, size_t len,
                       uint8_t *body, size_t cap, const atalaia_crypto_ops_t *crypto)
{
    if (key == NULL || body == NULL || crypto == NULL || crypto->decrypt == NULL ||
        !atalaia_ff_is_frame(pkt, len)) {
        return 0;
    }
    size_t body_len = len - ATALAIA_RF_HEADER_SIZE - ATALAIA_FF_NONCE_SIZE - ATALAIA_RF_MIC_SIZE;
    if (body_len > cap) return 0;
    uint8_t aad[ATALAIA_RF_AAD_SIZE];
    atalaia_aad_extract(pkt, aad);
    const uint8_t *nonce = pkt + ATALAIA_RF_HEADER_SIZE;
    const uint8_t *ct = nonce + ATALAIA_FF_NONCE_SIZE;
    if (crypto->decrypt(crypto->ctx, key, nonce, ATALAIA_FF_NONCE_SIZE, aad, sizeof(aad), ct,
                        body_len, body, ct + body_len, ATALAIA_RF_MIC_SIZE) != 0) {
        memset(body, 0, body_len);
        return 0;
    }
    return body_len;
}

/* ---- Invite parts ---------------------------------------------------------------- */

void atalaia_ff_reasm_reset(atalaia_ff_reasm_t *r)
{
    memset(r, 0, sizeof(*r));
}

int atalaia_ff_reasm_add(atalaia_ff_reasm_t *r, const atalaia_ff_msg_t *m, uint8_t *out, size_t cap)
{
    if (m->kind != ATALAIA_FF_INVITE || m->parts == 0 || m->part >= m->parts ||
        m->parts > ATALAIA_FF_PARTS_MAX || m->chunk_len == 0) {
        return 0;
    }
    if (!r->used || r->invite_id != m->invite_id || r->parts != m->parts ||
        memcmp(r->token, m->token, ATALAIA_FF_TOKEN_SIZE) != 0) {
        atalaia_ff_reasm_reset(r);
        r->used = true;
        r->invite_id = m->invite_id;
        r->parts = m->parts;
        memcpy(r->token, m->token, ATALAIA_FF_TOKEN_SIZE);
    }
    r->len[m->part] = m->chunk_len;
    memcpy(r->data[m->part], m->chunk, m->chunk_len);
    r->have |= (uint8_t)(1u << m->part);
    if (r->have != (uint8_t)((1u << r->parts) - 1u)) return 0;
    size_t total = 0;
    for (uint8_t p = 0; p < r->parts; p++) total += r->len[p];
    if (total > cap || total > ATALAIA_JOIN_MAX) {
        atalaia_ff_reasm_reset(r);
        return -1;
    }
    size_t at = 0;
    for (uint8_t p = 0; p < r->parts; p++) {
        memcpy(out + at, r->data[p], r->len[p]);
        at += r->len[p];
    }
    atalaia_ff_reasm_reset(r);
    return (int)total;
}

size_t atalaia_ff_parts_for(size_t len)
{
    if (len == 0 || len > ATALAIA_JOIN_MAX) return 0;
    return (len + ATALAIA_FF_CHUNK_MAX - 1) / ATALAIA_FF_CHUNK_MAX;
}
