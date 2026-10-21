/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Pair frames: adopting a box over the radio by its code (atalaia/pair_frame.h,
 * protocol/adoption.md section 7).
 */
#include "atalaia/pair_frame.h"

#include <string.h>

#include "atalaia/field_frame.h"
#include "atalaia/protocol.h"

#include "cbor_int.h"

#define BIT(k) (1u << (k))

_Static_assert(ATALAIA_PF_TYPE == ATALAIA_MSG_PAIR, "the pair frames' message type");

static const atalaia_header_t PF_HEADER = {
    .version_flags = ATALAIA_VF_MAKE(1, 1, 0, 0), /* v1, normal, no ACK, not encrypted */
    .game_id = 0,
    .source = 0,
    .seq = 0,
    .hop_limit = 0,
    .type = ATALAIA_PF_TYPE,
};

/* The fields of each kind, in their order on air. */
#define OFFER_KEYS (BIT(ATALAIA_PF_K_PAIR) | BIT(ATALAIA_PF_K_NAME) | BIT(ATALAIA_PF_K_TIER))
#define START_KEYS (BIT(ATALAIA_PF_K_PAIR) | BIT(ATALAIA_PF_K_SID) | BIT(ATALAIA_PF_K_POINT))
#define REPLY_KEYS (START_KEYS | BIT(ATALAIA_PF_K_TAG))
#define KEY_KEYS                                                                                   \
    (BIT(ATALAIA_PF_K_PAIR) | BIT(ATALAIA_PF_K_SID) | BIT(ATALAIA_PF_K_TAG) |                      \
     BIT(ATALAIA_PF_K_NONCE) | BIT(ATALAIA_PF_K_SEALED))
#define DONE_KEYS                                                                                  \
    (BIT(ATALAIA_PF_K_PAIR) | BIT(ATALAIA_PF_K_SID) | BIT(ATALAIA_PF_K_RESULT) |                   \
     BIT(ATALAIA_PF_K_FP) | BIT(ATALAIA_PF_K_TAG))
#define KNOWN_KEYS 0xFFEu /* keys 1-11 */

static uint32_t keys_of(uint8_t kind)
{
    switch (kind) {
    case ATALAIA_PF_OFFER: return OFFER_KEYS;
    case ATALAIA_PF_START: return START_KEYS;
    case ATALAIA_PF_REPLY: return REPLY_KEYS;
    case ATALAIA_PF_KEY: return KEY_KEYS;
    case ATALAIA_PF_DONE: return DONE_KEYS;
    default: return 0;
    }
}

bool atalaia_pf_is_frame(const uint8_t *pkt, size_t len)
{
    atalaia_header_t h;
    if (pkt == NULL || len < ATALAIA_PF_MIN || len > ATALAIA_PF_MAX) return false;
    if (!atalaia_header_decode(pkt, &h)) return false;
    return h.game_id == 0 && h.type == ATALAIA_PF_TYPE && !ATALAIA_VF_ENC(h.version_flags) &&
           ATALAIA_VF_VERSION(h.version_flags) == 1;
}

size_t atalaia_pf_encode(const atalaia_pf_msg_t *m, uint8_t *out, size_t cap)
{
    uint32_t keys = keys_of(m->kind);
    if (keys == 0 || cap < ATALAIA_RF_HEADER_SIZE + 1) return 0;
    if ((keys & BIT(ATALAIA_PF_K_NAME)) &&
        (!atalaia_join_text_ok(m->name, ATALAIA_PF_NAME_MAX) || m->tier > 2)) {
        return 0;
    }
    if ((keys & BIT(ATALAIA_PF_K_SEALED)) &&
        (m->sealed_len < ATALAIA_PF_SEALED_MIN || m->sealed_len > ATALAIA_PF_SEALED_MAX)) {
        return 0;
    }
    if ((keys & BIT(ATALAIA_PF_K_RESULT)) && m->result > ATALAIA_PF_RESULT_MAX) return 0;
    atalaia_header_encode(&PF_HEADER, out);
    size_t room = cap - ATALAIA_RF_HEADER_SIZE;
    mc_writer_t w;
    mc_init_writer(&w, out + ATALAIA_RF_HEADER_SIZE,
                   room < ATALAIA_PF_BODY_MAX ? room : ATALAIA_PF_BODY_MAX);
    unsigned count = 1;
    for (unsigned k = 2; k <= ATALAIA_PF_K_FP; k++) count += (keys & BIT(k)) != 0;
    mc_put_map(&w, count);
    mc_put_uint(&w, ATALAIA_PF_K_KIND);
    mc_put_uint(&w, m->kind);
    /* The order of the Python encoder (pair_frame._FIELDS). */
    static const uint8_t order[][5] = {
        [ATALAIA_PF_OFFER] = {ATALAIA_PF_K_PAIR, ATALAIA_PF_K_NAME, ATALAIA_PF_K_TIER, 0, 0},
        [ATALAIA_PF_START] = {ATALAIA_PF_K_PAIR, ATALAIA_PF_K_SID, ATALAIA_PF_K_POINT, 0, 0},
        [ATALAIA_PF_REPLY] = {ATALAIA_PF_K_PAIR, ATALAIA_PF_K_SID, ATALAIA_PF_K_POINT,
                              ATALAIA_PF_K_TAG, 0},
        [ATALAIA_PF_KEY] = {ATALAIA_PF_K_PAIR, ATALAIA_PF_K_SID, ATALAIA_PF_K_TAG,
                            ATALAIA_PF_K_NONCE, ATALAIA_PF_K_SEALED},
        [ATALAIA_PF_DONE] = {ATALAIA_PF_K_PAIR, ATALAIA_PF_K_SID, ATALAIA_PF_K_RESULT,
                             ATALAIA_PF_K_FP, ATALAIA_PF_K_TAG},
    };
    for (size_t i = 0; i < 5 && order[m->kind][i] != 0; i++) {
        uint8_t key = order[m->kind][i];
        mc_put_uint(&w, key);
        switch (key) {
        case ATALAIA_PF_K_PAIR: mc_put_bytes(&w, m->pair_id, ATALAIA_PF_PAIR_ID_SIZE); break;
        case ATALAIA_PF_K_NAME: mc_put_text(&w, m->name); break;
        case ATALAIA_PF_K_TIER: mc_put_uint(&w, m->tier); break;
        case ATALAIA_PF_K_SID: mc_put_bytes(&w, m->sid, ATALAIA_PF_SID_SIZE); break;
        case ATALAIA_PF_K_POINT: mc_put_bytes(&w, m->point, ATALAIA_PF_POINT_SIZE); break;
        case ATALAIA_PF_K_TAG: mc_put_bytes(&w, m->tag, ATALAIA_PF_TAG_SIZE); break;
        case ATALAIA_PF_K_NONCE: mc_put_bytes(&w, m->nonce, ATALAIA_PF_NONCE_SIZE); break;
        case ATALAIA_PF_K_SEALED: mc_put_bytes(&w, m->sealed, m->sealed_len); break;
        case ATALAIA_PF_K_RESULT: mc_put_uint(&w, m->result); break;
        case ATALAIA_PF_K_FP: mc_put_bytes(&w, m->fingerprint, ATALAIA_PF_FP_SIZE); break;
        default: return 0;
        }
    }
    return w.ok ? ATALAIA_RF_HEADER_SIZE + w.pos : 0;
}

static bool read_fixed(mc_reader_t *r, uint8_t *out, size_t size)
{
    size_t n = 0;
    return mc_read_bytes(r, out, size, &n) && n == size;
}

static bool read_uint_max(mc_reader_t *r, uint64_t max, uint64_t *out)
{
    if (!mc_read_uint(r, out) || *out > max) {
        r->ok = false;
        return false;
    }
    return true;
}

bool atalaia_pf_body_decode(const uint8_t *buf, size_t len, atalaia_pf_msg_t *m)
{
    memset(m, 0, sizeof(*m));
    if (buf == NULL || len == 0 || len > ATALAIA_PF_BODY_MAX) return false;
    mc_reader_t r;
    mc_init_reader(&r, buf, len);
    uint64_t count, key, v;
    if (!mc_read_map(&r, &count) || count == 0 || count > 31) return false;
    if (!mc_read_uint(&r, &key) || key != ATALAIA_PF_K_KIND || !read_uint_max(&r, 255, &v)) {
        return false;
    }
    m->kind = (uint8_t)v;
    uint32_t want = keys_of(m->kind);
    if (want == 0) return false;
    uint32_t seen = 0;
    for (uint64_t i = 1; i < count && r.ok; i++) {
        if (!mc_read_uint(&r, &key) || key >= 32 || key == ATALAIA_PF_K_KIND || (seen & BIT(key))) {
            return false;
        }
        seen |= BIT(key);
        if (!(want & BIT(key))) {
            if (KNOWN_KEYS & BIT(key)) return false; /* another kind's */
            if (!mc_skip_value(&r)) return false;    /* a later optional field */
            continue;
        }
        bool ok;
        switch (key) {
        case ATALAIA_PF_K_PAIR: ok = read_fixed(&r, m->pair_id, ATALAIA_PF_PAIR_ID_SIZE); break;
        case ATALAIA_PF_K_NAME: {
            size_t n = 0;
            ok = mc_read_text(&r, m->name, sizeof(m->name), &n) && n >= 1 && strlen(m->name) == n &&
                 atalaia_join_text_ok(m->name, ATALAIA_PF_NAME_MAX);
            break;
        }
        case ATALAIA_PF_K_TIER:
            ok = read_uint_max(&r, 2, &v);
            m->tier = (uint8_t)v;
            break;
        case ATALAIA_PF_K_SID: ok = read_fixed(&r, m->sid, ATALAIA_PF_SID_SIZE); break;
        case ATALAIA_PF_K_POINT: ok = read_fixed(&r, m->point, ATALAIA_PF_POINT_SIZE); break;
        case ATALAIA_PF_K_TAG: ok = read_fixed(&r, m->tag, ATALAIA_PF_TAG_SIZE); break;
        case ATALAIA_PF_K_NONCE: ok = read_fixed(&r, m->nonce, ATALAIA_PF_NONCE_SIZE); break;
        case ATALAIA_PF_K_SEALED: {
            size_t n = 0;
            ok = mc_read_bytes(&r, m->sealed, sizeof(m->sealed), &n) &&
                 n >= ATALAIA_PF_SEALED_MIN && n <= ATALAIA_PF_SEALED_MAX;
            m->sealed_len = (uint8_t)n;
            break;
        }
        case ATALAIA_PF_K_RESULT:
            ok = read_uint_max(&r, ATALAIA_PF_RESULT_MAX, &v);
            m->result = (uint8_t)v;
            break;
        case ATALAIA_PF_K_FP: ok = read_fixed(&r, m->fingerprint, ATALAIA_PF_FP_SIZE); break;
        default: ok = false; break;
        }
        if (!ok) return false;
    }
    return r.ok && r.p == r.end && (seen & want) == want;
}

bool atalaia_pf_decode(const uint8_t *pkt, size_t len, atalaia_pf_msg_t *m)
{
    if (!atalaia_pf_is_frame(pkt, len)) return false;
    return atalaia_pf_body_decode(pkt + ATALAIA_RF_HEADER_SIZE, len - ATALAIA_RF_HEADER_SIZE, m);
}

void atalaia_pf_channel_id(const uint8_t pair_id[ATALAIA_PF_PAIR_ID_SIZE],
                           uint8_t out[ATALAIA_PF_CI_SIZE])
{
    const size_t label = sizeof(ATALAIA_PF_CI_LABEL) - 1;
    out[0] = (uint8_t)label;
    memcpy(out + 1, ATALAIA_PF_CI_LABEL, label);
    out[1 + label] = ATALAIA_PF_PAIR_ID_SIZE;
    memcpy(out + 2 + label, pair_id, ATALAIA_PF_PAIR_ID_SIZE);
}

static void derive(const uint8_t *isk, const uint8_t *sid, const char *label, uint8_t *out,
                   size_t len)
{
    atalaia_hkdf_sha256(sid, ATALAIA_PF_SID_SIZE, isk, ATALAIA_PF_ISK_SIZE, (const uint8_t *)label,
                        strlen(label), out, len);
}

void atalaia_pf_keys(const uint8_t isk[ATALAIA_PF_ISK_SIZE], const uint8_t sid[ATALAIA_PF_SID_SIZE],
                     atalaia_pf_keys_t *out)
{
    derive(isk, sid, "atalaia pair confirm a v1", out->confirm_a, sizeof(out->confirm_a));
    derive(isk, sid, "atalaia pair confirm b v1", out->confirm_b, sizeof(out->confirm_b));
    derive(isk, sid, "atalaia pair seal v1", out->seal, sizeof(out->seal));
    derive(isk, sid, "atalaia pair nonce v1", out->nonce, sizeof(out->nonce));
}

static void tag(const uint8_t key[32], const uint8_t *msg, size_t len,
                uint8_t out[ATALAIA_PF_TAG_SIZE])
{
    uint8_t mac[32];
    atalaia_hmac_sha256(key, 32, msg, len, mac);
    memcpy(out, mac, ATALAIA_PF_TAG_SIZE);
}

void atalaia_pf_tag_reply(const atalaia_pf_keys_t *k, uint8_t out[ATALAIA_PF_TAG_SIZE])
{
    static const char msg[] = "atalaia pair reply";
    tag(k->confirm_b, (const uint8_t *)msg, sizeof(msg) - 1, out);
}

void atalaia_pf_tag_key(const atalaia_pf_keys_t *k, uint8_t out[ATALAIA_PF_TAG_SIZE])
{
    static const char msg[] = "atalaia pair key";
    tag(k->confirm_a, (const uint8_t *)msg, sizeof(msg) - 1, out);
}

void atalaia_pf_tag_done(const atalaia_pf_keys_t *k, uint8_t result,
                         const uint8_t fingerprint[ATALAIA_PF_FP_SIZE],
                         uint8_t out[ATALAIA_PF_TAG_SIZE])
{
    static const char label[] = "atalaia pair done";
    uint8_t msg[sizeof(label) - 1 + 1 + ATALAIA_PF_FP_SIZE];
    memcpy(msg, label, sizeof(label) - 1);
    msg[sizeof(label) - 1] = result;
    memcpy(msg + sizeof(label), fingerprint, ATALAIA_PF_FP_SIZE);
    tag(k->confirm_b, msg, sizeof(msg), out);
}

bool atalaia_pf_tag_equal(const uint8_t a[ATALAIA_PF_TAG_SIZE],
                          const uint8_t b[ATALAIA_PF_TAG_SIZE])
{
    uint8_t d = 0;
    for (size_t i = 0; i < ATALAIA_PF_TAG_SIZE; i++) d |= (uint8_t)(a[i] ^ b[i]);
    return d == 0;
}

#define AAD_LABEL "atalaia pair key v1"
#define AAD_SIZE  (sizeof(AAD_LABEL) - 1 + ATALAIA_PF_PAIR_ID_SIZE + ATALAIA_PF_SID_SIZE)

static void key_aad(const uint8_t *pair_id, const uint8_t *sid, uint8_t aad[AAD_SIZE])
{
    memcpy(aad, AAD_LABEL, sizeof(AAD_LABEL) - 1);
    memcpy(aad + sizeof(AAD_LABEL) - 1, pair_id, ATALAIA_PF_PAIR_ID_SIZE);
    memcpy(aad + sizeof(AAD_LABEL) - 1 + ATALAIA_PF_PAIR_ID_SIZE, sid, ATALAIA_PF_SID_SIZE);
}

size_t atalaia_pf_seal_key(const atalaia_pf_keys_t *k, const uint8_t nonce[ATALAIA_PF_NONCE_SIZE],
                           const uint8_t pair_id[ATALAIA_PF_PAIR_ID_SIZE],
                           const uint8_t sid[ATALAIA_PF_SID_SIZE],
                           const uint8_t join_key[ATALAIA_JOIN_KEY_SIZE], const char *name,
                           uint8_t *out, size_t cap, const atalaia_crypto_ops_t *crypto)
{
    size_t n = name ? strlen(name) : 0;
    size_t pt_len = ATALAIA_JOIN_KEY_SIZE + 1 + n;
    if (n > ATALAIA_PF_FIELD_NAME_MAX || cap < pt_len + ATALAIA_PF_MIC_SIZE || crypto == NULL ||
        crypto->encrypt == NULL) {
        return 0;
    }
    uint8_t pt[ATALAIA_JOIN_KEY_SIZE + 1 + ATALAIA_PF_FIELD_NAME_MAX];
    memcpy(pt, join_key, ATALAIA_JOIN_KEY_SIZE);
    pt[ATALAIA_JOIN_KEY_SIZE] = (uint8_t)n;
    if (n) memcpy(pt + ATALAIA_JOIN_KEY_SIZE + 1, name, n);
    uint8_t aad[AAD_SIZE];
    key_aad(pair_id, sid, aad);
    int rc = crypto->encrypt(crypto->ctx, k->seal, nonce, ATALAIA_PF_NONCE_SIZE, aad, sizeof(aad),
                             pt, pt_len, out, out + pt_len, ATALAIA_PF_MIC_SIZE);
    memset(pt, 0, sizeof(pt));
    return rc == 0 ? pt_len + ATALAIA_PF_MIC_SIZE : 0;
}

bool atalaia_pf_open_key(const atalaia_pf_keys_t *k, const uint8_t nonce[ATALAIA_PF_NONCE_SIZE],
                         const uint8_t pair_id[ATALAIA_PF_PAIR_ID_SIZE],
                         const uint8_t sid[ATALAIA_PF_SID_SIZE], const uint8_t *sealed,
                         size_t sealed_len, uint8_t join_key[ATALAIA_JOIN_KEY_SIZE],
                         char name[ATALAIA_PF_FIELD_NAME_MAX + 1],
                         const atalaia_crypto_ops_t *crypto)
{
    if (sealed_len < ATALAIA_PF_SEALED_MIN || sealed_len > ATALAIA_PF_SEALED_MAX ||
        crypto == NULL || crypto->decrypt == NULL) {
        return false;
    }
    size_t pt_len = sealed_len - ATALAIA_PF_MIC_SIZE;
    uint8_t pt[ATALAIA_JOIN_KEY_SIZE + 1 + ATALAIA_PF_FIELD_NAME_MAX];
    uint8_t aad[AAD_SIZE];
    key_aad(pair_id, sid, aad);
    bool ok = crypto->decrypt(crypto->ctx, k->seal, nonce, ATALAIA_PF_NONCE_SIZE, aad, sizeof(aad),
                              sealed, pt_len, pt, sealed + pt_len, ATALAIA_PF_MIC_SIZE) == 0 &&
              pt[ATALAIA_JOIN_KEY_SIZE] == pt_len - ATALAIA_JOIN_KEY_SIZE - 1;
    if (ok) {
        memcpy(join_key, pt, ATALAIA_JOIN_KEY_SIZE);
        size_t n = pt[ATALAIA_JOIN_KEY_SIZE];
        memcpy(name, pt + ATALAIA_JOIN_KEY_SIZE + 1, n);
        name[n] = '\0';
    }
    memset(pt, 0, sizeof(pt));
    return ok;
}
