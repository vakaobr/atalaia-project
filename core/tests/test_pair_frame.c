/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Pair frames (atalaia/pair_frame.h) against the shared vectors
 * (protocol/vectors/pairing.json, also checked by simulator/tests/
 * test_pair_frame.py): the five frames of a run, the keys from its ISK, the
 * tags, KEY's nonce and sealed join key (with the real AES-CCM backend), and
 * every body and frame that must be refused. CPace itself (X25519, Elligator 2,
 * SHA-512) is the firmware's (firmware/esp32/test/test_box_pair.c checks it
 * against the draft's vectors). Every vector is checked; none is skipped.
 */
#include <stdio.h>
#include <string.h>

#include "atalaia/field_frame.h"
#include "atalaia/pair_frame.h"
#include "check.h"
#include "pair_vectors.h"

static void test_frames(void)
{
    const struct {
        const char *name;
        const uint8_t *frame;
        size_t len;
        uint8_t kind;
    } frames[] = {
        {"offer", pv_frame_offer, pv_frame_offer_len, ATALAIA_PF_OFFER},
        {"start", pv_frame_start, pv_frame_start_len, ATALAIA_PF_START},
        {"reply", pv_frame_reply, pv_frame_reply_len, ATALAIA_PF_REPLY},
        {"key", pv_frame_key, pv_frame_key_len, ATALAIA_PF_KEY},
        {"done", pv_frame_done, pv_frame_done_len, ATALAIA_PF_DONE},
    };
    for (size_t i = 0; i < sizeof(frames) / sizeof(frames[0]); i++) {
        atalaia_pf_msg_t m;
        CHECK(atalaia_pf_is_frame(frames[i].frame, frames[i].len));
        bool ok = atalaia_pf_decode(frames[i].frame, frames[i].len, &m);
        if (!ok) fprintf(stderr, "FAIL pair frame %s does not decode\n", frames[i].name);
        CHECK(ok && m.kind == frames[i].kind);
        CHECK(memcmp(m.pair_id, pv_run_pair_id, ATALAIA_PF_PAIR_ID_SIZE) == 0);
        uint8_t out[ATALAIA_PF_MAX];
        size_t n = atalaia_pf_encode(&m, out, sizeof(out));
        CHECK(n == frames[i].len && memcmp(out, frames[i].frame, n) == 0);
        CHECK(atalaia_pf_encode(&m, out, n - 1) == 0);
        /* A field frame's shape is not a pair frame's, and the other way round. */
        CHECK(!atalaia_ff_is_frame(frames[i].frame, frames[i].len));
    }
    atalaia_pf_msg_t m;
    CHECK(atalaia_pf_decode(pv_frame_offer, pv_frame_offer_len, &m));
    CHECK(strcmp(m.name, "porta-norte") == 0 && m.tier == 0);
    CHECK(atalaia_pf_decode(pv_frame_start, pv_frame_start_len, &m));
    CHECK(memcmp(m.sid, pv_run_sid, 16) == 0 && memcmp(m.point, pv_run_Ya, 32) == 0);
    CHECK(atalaia_pf_decode(pv_frame_reply, pv_frame_reply_len, &m));
    CHECK(memcmp(m.point, pv_run_Yb, 32) == 0 && memcmp(m.tag, pv_run_tag_reply, 16) == 0);
    CHECK(atalaia_pf_decode(pv_frame_key, pv_frame_key_len, &m));
    CHECK(m.sealed_len == pv_run_sealed_len && memcmp(m.sealed, pv_run_sealed, m.sealed_len) == 0);
    CHECK(memcmp(m.nonce, pv_run_nonce, 13) == 0 && memcmp(m.tag, pv_run_tag_key, 16) == 0);
    CHECK(atalaia_pf_decode(pv_frame_done, pv_frame_done_len, &m));
    CHECK(m.result == 0 && memcmp(m.fingerprint, pv_run_fingerprint, 4) == 0);
    CHECK(memcmp(m.tag, pv_run_tag_done, 16) == 0);

    CHECK(PV_BAD_BODY_COUNT >= 19 && PV_BAD_FRAME_COUNT >= 6);
    for (size_t i = 0; i < PV_BAD_BODY_COUNT; i++) {
        if (atalaia_pf_body_decode(pv_bad_bodies[i].data, pv_bad_bodies[i].len, &m)) {
            fprintf(stderr, "FAIL pair body %s accepted\n", pv_bad_bodies[i].name);
            check_failures++;
        }
    }
    for (size_t i = 0; i < PV_BAD_FRAME_COUNT; i++) {
        if (atalaia_pf_is_frame(pv_bad_frames[i].data, pv_bad_frames[i].len) ||
            atalaia_pf_decode(pv_bad_frames[i].data, pv_bad_frames[i].len, &m)) {
            fprintf(stderr, "FAIL pair frame %s accepted\n", pv_bad_frames[i].name);
            check_failures++;
        }
    }
}

static void test_keys_and_tags(void)
{
    uint8_t ci[ATALAIA_PF_CI_SIZE];
    atalaia_pf_channel_id(pv_run_pair_id, ci);
    CHECK(sizeof(ci) == pv_run_ci_len && memcmp(ci, pv_run_ci, sizeof(ci)) == 0);
    CHECK(strlen(ATALAIA_PF_AD_CONTROLLER) == pv_run_ada_len &&
          memcmp(ATALAIA_PF_AD_CONTROLLER, pv_run_ada, pv_run_ada_len) == 0);
    CHECK(strlen(ATALAIA_PF_AD_BOX) == pv_run_adb_len &&
          memcmp(ATALAIA_PF_AD_BOX, pv_run_adb, pv_run_adb_len) == 0);
    atalaia_pf_keys_t k;
    atalaia_pf_keys(pv_run_isk, pv_run_sid, &k);
    CHECK(memcmp(k.confirm_a, pv_run_confirm_a, 32) == 0);
    CHECK(memcmp(k.confirm_b, pv_run_confirm_b, 32) == 0);
    CHECK(memcmp(k.seal, pv_run_seal, 16) == 0);
    CHECK(memcmp(k.nonce, pv_run_nonce_key, 32) == 0);
    uint8_t t[16];
    atalaia_pf_tag_reply(&k, t);
    CHECK(memcmp(t, pv_run_tag_reply, 16) == 0 && atalaia_pf_tag_equal(t, pv_run_tag_reply));
    atalaia_pf_tag_key(&k, t);
    CHECK(memcmp(t, pv_run_tag_key, 16) == 0);
    CHECK(!atalaia_pf_tag_equal(t, pv_run_tag_reply));
    atalaia_pf_tag_done(&k, 0, pv_run_fingerprint, t);
    CHECK(memcmp(t, pv_run_tag_done, 16) == 0);
    /* KEY's nonce: the field frames' rule, with the run's own nonce key and sender id. */
    uint8_t nonce[13];
    atalaia_ff_nonce(k.nonce, pv_run_sender, 1, 0, nonce);
    CHECK(memcmp(nonce, pv_run_nonce, 13) == 0);
}

static void test_sealed_key(void)
{
#ifdef ATALAIA_HAVE_MBEDTLS
    const atalaia_crypto_ops_t *c = &atalaia_crypto_mbedtls;
    atalaia_pf_keys_t k;
    atalaia_pf_keys(pv_run_isk, pv_run_sid, &k);
    uint8_t sealed[ATALAIA_PF_SEALED_MAX];
    size_t n = atalaia_pf_seal_key(&k, pv_run_nonce, pv_run_pair_id, pv_run_sid, pv_run_join_key,
                                   PV_FIELD_NAME, sealed, sizeof(sealed), c);
    CHECK(n == pv_run_sealed_len && memcmp(sealed, pv_run_sealed, n) == 0);
    uint8_t key[32];
    char name[ATALAIA_PF_FIELD_NAME_MAX + 1];
    CHECK(atalaia_pf_open_key(&k, pv_run_nonce, pv_run_pair_id, pv_run_sid, pv_run_sealed,
                              pv_run_sealed_len, key, name, c));
    CHECK(memcmp(key, pv_run_join_key, 32) == 0 && strcmp(name, PV_FIELD_NAME) == 0);
    /* Another run's sid or pair id, or one bit changed: nothing opens. */
    uint8_t other[16] = {0};
    CHECK(!atalaia_pf_open_key(&k, pv_run_nonce, pv_run_pair_id, other, pv_run_sealed,
                               pv_run_sealed_len, key, name, c));
    CHECK(!atalaia_pf_open_key(&k, pv_run_nonce, other, pv_run_sid, pv_run_sealed,
                               pv_run_sealed_len, key, name, c));
    sealed[3] ^= 1;
    CHECK(!atalaia_pf_open_key(&k, pv_run_nonce, pv_run_pair_id, pv_run_sid, sealed, n, key, name,
                               c));
    CHECK(!atalaia_pf_open_key(&k, pv_run_nonce, pv_run_pair_id, pv_run_sid, sealed, 40, key, name,
                               c));
    char long_name[50];
    memset(long_name, 'A', 49);
    long_name[49] = '\0';
    CHECK(atalaia_pf_seal_key(&k, pv_run_nonce, pv_run_pair_id, pv_run_sid, pv_run_join_key,
                              long_name, sealed, sizeof(sealed), c) == 0);
#endif
}

void run_pair_frame_tests(void)
{
    test_frames();
    test_keys_and_tags();
    test_sealed_key();
}
