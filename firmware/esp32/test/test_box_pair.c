/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Pairing by code (main/cpace.c, main/box_pair.c, protocol/adoption.md section 7):
 * CPace on Monocypher against draft-irtf-cfrg-cpace-14's Appendix B.1 and B.1.10
 * (protocol/vectors/pairing.json, also checked by the Python side); the vectors'
 * whole run played against the box (its REPLY and DONE byte for byte), a wrong
 * code, and the box's limits: replays, repeats, timeouts, a minute's wait after
 * three failed runs, the lock after ten, a low-order point, the offers' pace.
 */
#include <stdio.h>
#include <string.h>

#include "adoption.h"
#include "atalaia/pair_frame.h"
#include "box_pair.h"
#include "check.h"
#include "cpace.h"
#include "pair_vectors.h"

/* ---- CPace against the draft ------------------------------------------------ */

static void test_cpace_draft(void)
{
    uint8_t gs[CPACE_GS_MAX];
    size_t n = cpace_generator_string(pv_b1_prs, pv_b1_prs_len, pv_b1_ci, pv_b1_ci_len, pv_b1_sid,
                                      pv_b1_sid_len, gs, sizeof(gs));
    CHECK(n == pv_b1_generator_string_len && memcmp(gs, pv_b1_generator_string, n) == 0);
    uint8_t g[32], ya[32], yb[32], k1[32], k2[32], isk[64];
    CHECK(cpace_generator(pv_b1_prs, pv_b1_prs_len, pv_b1_ci, pv_b1_ci_len, pv_b1_sid,
                          pv_b1_sid_len, g));
    CHECK(memcmp(g, pv_b1_g, 32) == 0);
    cpace_scalar_mult(pv_b1_ya, g, ya);
    cpace_scalar_mult(pv_b1_yb, g, yb);
    CHECK(memcmp(ya, pv_b1_Ya, 32) == 0 && memcmp(yb, pv_b1_Yb, 32) == 0);
    CHECK(cpace_scalar_mult_vfy(pv_b1_ya, yb, k1) && cpace_scalar_mult_vfy(pv_b1_yb, ya, k2));
    CHECK(memcmp(k1, pv_b1_K, 32) == 0 && memcmp(k2, pv_b1_K, 32) == 0);
    cpace_isk_ir(pv_b1_sid, pv_b1_sid_len, k1, ya, pv_b1_ada, pv_b1_ada_len, yb, pv_b1_adb,
                 pv_b1_adb_len, isk);
    CHECK(memcmp(isk, pv_b1_isk_ir, 64) == 0);
    (void)pv_b1_hash_generator_string;

    int aborts = 0;
    CHECK(PV_LOW_COUNT == 12);
    for (size_t i = 0; i < PV_LOW_COUNT; i++) {
        uint8_t q[32];
        cpace_scalar_mult(pv_low_s, pv_low_u[i], q);
        if (memcmp(q, pv_low_q[i], 32) != 0) {
            fprintf(stderr, "FAIL cpace low-order point %zu\n", i);
            check_failures++;
        }
        static const uint8_t zero[32] = {0};
        bool neutral = memcmp(pv_low_q[i], zero, 32) == 0;
        CHECK(cpace_scalar_mult_vfy(pv_low_s, pv_low_u[i], q) == !neutral);
        aborts += neutral;
    }
    CHECK(aborts == 7); /* u0-u5 and u7, as the draft says */
}

static void test_run_math(void)
{
    uint8_t ci[ATALAIA_PF_CI_SIZE], g[32], ya[32], yb[32], k[32], isk[64];
    atalaia_pf_channel_id(pv_run_pair_id, ci);
    CHECK(cpace_generator((const uint8_t *)PV_CODE, 6, ci, sizeof(ci), pv_run_sid, 16, g));
    CHECK(memcmp(g, pv_run_g, 32) == 0);
    cpace_scalar_mult(pv_run_ya, g, ya);
    cpace_scalar_mult(pv_run_yb, g, yb);
    CHECK(memcmp(ya, pv_run_Ya, 32) == 0 && memcmp(yb, pv_run_Yb, 32) == 0);
    CHECK(cpace_scalar_mult_vfy(pv_run_yb, ya, k) && memcmp(k, pv_run_K, 32) == 0);
    cpace_isk_ir(pv_run_sid, 16, k, ya, pv_run_ada, pv_run_ada_len, yb, pv_run_adb, pv_run_adb_len,
                 isk);
    CHECK(memcmp(isk, pv_run_isk, 64) == 0);
    CHECK(cpace_generator((const uint8_t *)PV_WRONG_CODE, 6, ci, sizeof(ci), pv_run_sid, 16, g));
    cpace_scalar_mult(pv_run_yb, g, yb);
    CHECK(memcmp(yb, pv_wrong_yb, 32) == 0);

    /* Generators whose hashed string is 2^254 or more: Monocypher gets p - r (cpace.c). */
    int high = 0;
    CHECK(PV_GENERATOR_COUNT >= 6);
    for (size_t i = 0; i < PV_GENERATOR_COUNT; i++) {
        const pv_generator_t *v = &pv_generators[i];
        atalaia_pf_channel_id(v->pair_id, ci);
        CHECK(cpace_generator((const uint8_t *)v->code, 6, ci, sizeof(ci), v->sid, 16, g));
        if (memcmp(g, v->g, 32) != 0) {
            fprintf(stderr, "FAIL cpace generator %zu (r_high %d)\n", i, v->r_high);
            check_failures++;
        }
        high += v->r_high;
    }
    CHECK(high >= 4);
}

/* ---- the box ----------------------------------------------------------------- */

static struct {
    uint8_t sent[8][ATALAIA_PF_MAX];
    size_t sent_len[8];
    int sends;
    uint8_t fill; /* what the random source gives */
    char tmpl[24];
    char data[160];
    char log[200];
    bool busy;
    int stores;
    uint8_t key[32];
    char name[64];
} t;

static bool f_send(void *u, const uint8_t *pkt, size_t len)
{
    (void)u;
    int i = t.sends++ % 8;
    memcpy(t.sent[i], pkt, len);
    t.sent_len[i] = len;
    return true;
}

static void f_random(void *u, uint8_t *buf, size_t len)
{
    (void)u;
    memset(buf, t.fill, len);
}

static void f_screen(void *u, const char *tmpl, const char *data)
{
    (void)u;
    snprintf(t.tmpl, sizeof(t.tmpl), "%s", tmpl);
    snprintf(t.data, sizeof(t.data), "%s", data);
}

static void f_log(void *u, const char *line)
{
    (void)u;
    snprintf(t.log, sizeof(t.log), "%s", line);
}

static bool a_busy(void *ctx)
{
    (void)ctx;
    return t.busy;
}

static bool a_store(void *ctx, const uint8_t key[32], const char *name)
{
    (void)ctx;
    t.stores++;
    memcpy(t.key, key, 32);
    snprintf(t.name, sizeof(t.name), "%s", name);
    return true;
}

static void a_screen(void *ctx, const char *tmpl, const char *data)
{
    f_screen(ctx, tmpl, data);
}

static void a_log(void *ctx, const char *line)
{
    f_log(ctx, line);
}

static adoption_t adopt;
static box_pair_t pair;

static const uint8_t *last_sent(size_t *len)
{
    int i = (t.sends - 1) % 8;
    *len = t.sent_len[i];
    return t.sent[i];
}

static void fresh(uint32_t now)
{
    memset(&t, 0, sizeof(t));
    t.fill = 0x6b; /* the vectors' yb; also the code's and pair id's bytes */
    adoption_ops_t aops = {a_busy, a_store, a_screen, a_log, NULL};
    adoption_init(&adopt, &aops, "4321");
    box_pair_ops_t ops = {f_send, f_random, f_screen, f_log, NULL};
    box_pair_init(&pair, &ops, &adopt, &atalaia_crypto_test_stub, "porta-norte", 0, 869525000u);
    CHECK(box_pair_start(&pair, now));
    /* The vectors' code and pair id in place of the ones drawn. */
    memcpy(pair.code, PV_CODE, 7);
    memcpy(pair.pair_id, pv_run_pair_id, 8);
}

/* The vectors' KEY with its join key sealed by the crypto the host tests have (the test
 * stub: the firmware's host tests run without mbedtls); the core's test checks the real
 * AES-CCM bytes of the vector. Everything else in the frame is the vector's. */
static size_t stub_key_frame(uint8_t *out)
{
    atalaia_pf_msg_t m;
    CHECK(atalaia_pf_decode(pv_frame_key, pv_frame_key_len, &m));
    atalaia_pf_keys_t k;
    atalaia_pf_keys(pv_run_isk, pv_run_sid, &k);
    m.sealed_len = (uint8_t)atalaia_pf_seal_key(&k, pv_run_nonce, pv_run_pair_id, pv_run_sid,
                                                pv_run_join_key, PV_FIELD_NAME, m.sealed,
                                                sizeof(m.sealed), &atalaia_crypto_test_stub);
    CHECK(m.sealed_len == pv_run_sealed_len);
    return atalaia_pf_encode(&m, out, ATALAIA_PF_MAX);
}

static void test_vector_run(void)
{
    uint8_t key_frame[ATALAIA_PF_MAX];
    size_t key_len = stub_key_frame(key_frame);
    fresh(1000);
    CHECK(box_pair_showing(&pair));
    CHECK(strcmp(t.tmpl, "status") == 0 && strstr(t.data, "\"title\":\"Pair this box\"") != NULL);
    /* An offer 1-3 s later; its frame is the vectors' (name porta-norte, tier 0). */
    CHECK(!box_pair_tick(&pair, 1500) && t.sends == 0);
    box_pair_tick(&pair, 4000);
    size_t n;
    const uint8_t *f = last_sent(&n);
    CHECK(t.sends == 1 && n == pv_frame_offer_len && memcmp(f, pv_frame_offer, n) == 0);

    /* START -> the box's REPLY, byte for byte (yb = 6b..6b). */
    CHECK(box_pair_on_packet(&pair, pv_frame_start, pv_frame_start_len, 5000));
    f = last_sent(&n);
    CHECK(t.sends == 2 && n == pv_frame_reply_len && memcmp(f, pv_frame_reply, n) == 0);
    /* START again (the REPLY was lost): the same REPLY once more, then nothing. */
    box_pair_on_packet(&pair, pv_frame_start, pv_frame_start_len, 6000);
    CHECK(t.sends == 3);
    box_pair_on_packet(&pair, pv_frame_start, pv_frame_start_len, 6100);
    CHECK(t.sends == 3);
    /* No offers during a run. */
    box_pair_tick(&pair, 40000 - 26000);
    CHECK(t.sends == 3);

    /* A KEY with the run's sid but a tag that does not match (anyone who heard the sid can send
     * one): ignored and counted, the run goes on (decision AD-25). */
    {
        atalaia_pf_msg_t forged;
        CHECK(atalaia_pf_decode(key_frame, key_len, &forged));
        forged.tag[0] ^= 1;
        uint8_t ff[ATALAIA_PF_MAX];
        size_t fn = atalaia_pf_encode(&forged, ff, sizeof(ff));
        CHECK(box_pair_on_packet(&pair, ff, fn, 6500));
        CHECK(pair.in_run && pair.bad_keys == 1 && pair.runs_failed == 0 && t.sends == 3);
        CHECK(t.stores == 0 && box_pair_showing(&pair));
        /* The controller's tag with sealed bytes changed: ignored too. */
        CHECK(atalaia_pf_decode(key_frame, key_len, &forged));
        forged.sealed[2] ^= 1;
        fn = atalaia_pf_encode(&forged, ff, sizeof(ff));
        box_pair_on_packet(&pair, ff, fn, 6600);
        CHECK(pair.in_run && pair.bad_keys == 2 && t.stores == 0);
    }
    /* KEY -> adopted with the vectors' key and name, DONE byte for byte. */
    CHECK(box_pair_on_packet(&pair, key_frame, key_len, 7000));
    CHECK(t.stores == 1 && memcmp(t.key, pv_run_join_key, 32) == 0 &&
          strcmp(t.name, PV_FIELD_NAME) == 0);
    CHECK(adopt.adopted && strcmp(adopt.fingerprint, "604A-0A95") == 0);
    f = last_sent(&n);
    CHECK(t.sends == 4 && n == pv_frame_done_len && memcmp(f, pv_frame_done, n) == 0);
    CHECK(!box_pair_showing(&pair));
    CHECK(strstr(t.data, "\"title\":\"Adopted\"") != NULL);
    CHECK(strstr(t.log, "pairing: done") != NULL);
    /* KEY again (the DONE was lost): DONE again, twice at most; then silence. */
    box_pair_on_packet(&pair, key_frame, key_len, 7500);
    box_pair_on_packet(&pair, key_frame, key_len, 7600);
    box_pair_on_packet(&pair, key_frame, key_len, 7700);
    CHECK(t.sends == 6 && t.stores == 1);
    /* Once adopted, a new pairing does not start; offers stop. */
    CHECK(!box_pair_start(&pair, 8000));
    box_pair_tick(&pair, 60000);
    CHECK(t.sends == 6);
}

static void test_wrong_code(void)
{
    fresh(1000);
    memcpy(pair.code, PV_WRONG_CODE, 7);
    box_pair_on_packet(&pair, pv_frame_start, pv_frame_start_len, 2000);
    size_t n;
    const uint8_t *f = last_sent(&n);
    atalaia_pf_msg_t m;
    CHECK(atalaia_pf_decode(f, n, &m) && m.kind == ATALAIA_PF_REPLY);
    CHECK(memcmp(m.point, pv_wrong_yb, 32) == 0 && memcmp(m.tag, pv_wrong_tag_reply, 16) == 0);
    /* The controller's KEY under the right code's keys: refused, nothing adopted, a new code. */
    uint8_t key_frame[ATALAIA_PF_MAX];
    size_t key_len = stub_key_frame(key_frame);
    box_pair_on_packet(&pair, key_frame, key_len, 3000);
    CHECK(t.stores == 0 && !adopt.adopted && box_pair_showing(&pair));
    /* Its tag does not match: ignored; the run fails only when its time runs out. */
    CHECK(pair.in_run && pair.bad_keys == 1 && pair.runs_failed == 0);
    box_pair_tick(&pair, 2000 + BOX_PAIR_RUN_MS);
    CHECK(pair.runs_failed == 1 && strstr(t.data, "Try again") != NULL);
    CHECK(strstr(t.data, "\"id\":\"b0c5\"") != NULL); /* the pair id's start, for the console */
    /* That START's sid never runs again, however often it is played back. */
    int sends = t.sends;
    box_pair_on_packet(&pair, pv_frame_start, pv_frame_start_len, 4000);
    CHECK(t.sends == sends && pair.runs_started == 1);
}

/* A KEY whose adoption fails (a game joined meanwhile): DONE says "busy", the code goes, and a
 * repeated KEY gets the same DONE again (twice at most). */
static void test_done_after_a_failed_adoption(void)
{
    uint8_t key_frame[ATALAIA_PF_MAX];
    size_t key_len = stub_key_frame(key_frame);
    fresh(1000);
    box_pair_on_packet(&pair, pv_frame_start, pv_frame_start_len, 2000);
    CHECK(pair.in_run);
    t.busy = true;
    box_pair_on_packet(&pair, key_frame, key_len, 3000);
    CHECK(t.stores == 0 && !pair.in_run && pair.runs_failed == 1 && pair.done_valid);
    size_t n;
    const uint8_t *f = last_sent(&n);
    atalaia_pf_msg_t m;
    CHECK(atalaia_pf_decode(f, n, &m) && m.kind == ATALAIA_PF_DONE && m.result == ADOPT_BUSY);
    int sends = t.sends;
    box_pair_on_packet(&pair, key_frame, key_len, 3500);
    box_pair_on_packet(&pair, key_frame, key_len, 3600);
    box_pair_on_packet(&pair, key_frame, key_len, 3700);
    CHECK(t.sends == sends + 2);
    f = last_sent(&n);
    CHECK(atalaia_pf_decode(f, n, &m) && m.kind == ATALAIA_PF_DONE && m.result == ADOPT_BUSY);
    CHECK(box_pair_showing(&pair) && strstr(t.data, "Try again") != NULL);
}

static void start_frame(uint8_t sid_byte, uint8_t *out, size_t *len)
{
    atalaia_pf_msg_t m;
    CHECK(atalaia_pf_decode(pv_frame_start, pv_frame_start_len, &m));
    m.sid[0] = sid_byte;
    memcpy(m.pair_id, pv_run_pair_id, 8);
    *len = atalaia_pf_encode(&m, out, ATALAIA_PF_MAX);
}

static void test_limits(void)
{
    fresh(1000);
    uint8_t f[ATALAIA_PF_MAX];
    size_t n;
    uint32_t now = 2000;
    /* Runs that time out: three, then a minute's wait in which a START is ignored. */
    for (uint8_t i = 1; i <= 3; i++) {
        start_frame(i, f, &n);
        memcpy(pair.pair_id, pv_run_pair_id, 8);
        box_pair_on_packet(&pair, f, n, now);
        CHECK(pair.in_run);
        now += BOX_PAIR_RUN_MS;
        box_pair_tick(&pair, now);
        CHECK(!pair.in_run);
    }
    CHECK(pair.waiting && strstr(t.data, "\"title\":\"Pair paused\"") != NULL);
    CHECK(strstr(t.data, "\"code\"") == NULL); /* no code to type while paused */
    start_frame(9, f, &n);
    box_pair_on_packet(&pair, f, n, now + 1000);
    CHECK(!pair.in_run);
    int sends = t.sends;
    box_pair_tick(&pair, now + 30000); /* no offers while waiting */
    CHECK(t.sends == sends);
    now += BOX_PAIR_WAIT_MS;
    box_pair_tick(&pair, now);
    CHECK(!pair.waiting);
    /* Seven more failed runs: locked until a restart. */
    for (uint8_t i = 10; pair.active && i < 40; i++) {
        start_frame(i, f, &n);
        box_pair_on_packet(&pair, f, n, now);
        now += BOX_PAIR_RUN_MS;
        box_pair_tick(&pair, now);
        if (pair.waiting) {
            now += BOX_PAIR_WAIT_MS;
            box_pair_tick(&pair, now);
        }
    }
    CHECK(pair.locked && !pair.active && pair.runs_failed == BOX_PAIR_RUNS_MAX);
    /* Said on the screen until a key, not only logged (decision AD-25). */
    CHECK(strstr(t.data, "Pair locked") != NULL && strstr(t.data, "restart the box") != NULL);
    CHECK(box_pair_showing(&pair) && !box_pair_tick(&pair, now + 1));
    CHECK(box_pair_key(&pair, '1', now + 2) && !box_pair_showing(&pair));
    CHECK(box_pair_tick(&pair, now + 3)); /* the shell redraws its own screen */
    CHECK(!box_pair_start(&pair, now));

    /* A low-order point burns the run. */
    fresh(1000);
    atalaia_pf_msg_t m;
    CHECK(atalaia_pf_decode(pv_frame_start, pv_frame_start_len, &m));
    memset(m.point, 0, 32);
    n = atalaia_pf_encode(&m, f, sizeof(f));
    box_pair_on_packet(&pair, f, n, 2000);
    CHECK(pair.runs_failed == 1 && !pair.in_run && t.sends == 0);

    /* Busy (a game): START ignored. Another box's pair id: ignored. */
    fresh(1000);
    t.busy = true;
    box_pair_on_packet(&pair, pv_frame_start, pv_frame_start_len, 2000);
    CHECK(!pair.in_run && t.sends == 0);
    t.busy = false;
    pair.pair_id[0] ^= 1;
    box_pair_on_packet(&pair, pv_frame_start, pv_frame_start_len, 2000);
    CHECK(!pair.in_run && pair.frames_ignored == 1);
    /* A field frame is not a pair frame. */
    CHECK(!box_pair_on_packet(&pair, pv_bad_frames[1].data, pv_bad_frames[1].len, 2000));

    /* Offers: at most one in 15 s, and the code leaves after 5 minutes. */
    fresh(0);
    int offers = 0;
    for (uint32_t ms = 0; ms <= BOX_PAIR_SHOW_MS + 1000; ms += 100) {
        sends = t.sends;
        bool gone = box_pair_tick(&pair, ms);
        offers += t.sends - sends;
        if (gone) CHECK(ms >= BOX_PAIR_SHOW_MS);
    }
    CHECK(offers >= 15 && offers <= 21 && !box_pair_showing(&pair));
    CHECK(strstr(t.log, "no field paired it") != NULL);

    /* Keys: '#' a new code, '*' stops; adopted by a card in the meantime: pairing stops. */
    fresh(1000);
    t.fill = 0x11;
    CHECK(box_pair_key(&pair, '#', 1100) && strcmp(pair.code, PV_CODE) != 0);
    CHECK(box_pair_key(&pair, '5', 1200) && box_pair_showing(&pair));
    CHECK(box_pair_key(&pair, '*', 1300) && !box_pair_showing(&pair));
    CHECK(box_pair_tick(&pair, 1400));
    CHECK(!box_pair_key(&pair, '*', 1500));
    fresh(1000);
    adoption_restore(&adopt, pv_run_join_key, "Campo");
    CHECK(!box_pair_tick(&pair, 1100) && !box_pair_showing(&pair));
}

/* An adopted box shows a pairing code only while the admin menu has armed a move (decision PKB-4);
 * the vectors' whole run then moves it to the vectors' field, and the old one is kept until then.
 */
static void test_move_to_another_field(void)
{
    uint8_t key_frame[ATALAIA_PF_MAX];
    size_t key_len = stub_key_frame(key_frame);
    uint8_t old_key[32];
    memset(old_key, 0x42, sizeof(old_key));

    /* Adopted and not armed: no code (as before). */
    fresh(1000);
    box_pair_stop(&pair, "test");
    adoption_restore(&adopt, old_key, "Campo velho");
    CHECK(!box_pair_start(&pair, 2000) && !box_pair_showing(&pair));
    /* Armed: the code shows and offers go out. */
    CHECK(adoption_allow_move(&adopt, true));
    CHECK(box_pair_start(&pair, 2000) && box_pair_showing(&pair));
    memcpy(pair.code, PV_CODE, 7);
    memcpy(pair.pair_id, pv_run_pair_id, 8);
    box_pair_tick(&pair, 2100);
    CHECK(box_pair_showing(&pair)); /* adopted, but armed: the code stays */
    box_pair_tick(&pair, 5000);
    CHECK(t.sends >= 1);
    /* The run: the vectors' START, then the KEY moves the box; the old key was there until it. */
    CHECK(box_pair_on_packet(&pair, pv_frame_start, pv_frame_start_len, 6000));
    CHECK(t.stores == 0 && memcmp(adopt.key, old_key, 32) == 0);
    CHECK(box_pair_on_packet(&pair, key_frame, key_len, 7000));
    CHECK(t.stores == 1 && memcmp(t.key, pv_run_join_key, 32) == 0 &&
          strcmp(t.name, PV_FIELD_NAME) == 0);
    CHECK(adopt.adopted && memcmp(adopt.key, pv_run_join_key, 32) == 0 && !adopt.move_armed);
    CHECK(strcmp(adopt.fingerprint, "604A-0A95") == 0 && !box_pair_showing(&pair));
    /* Done: it is an ordinary adopted box again, so no code without a new arming. */
    CHECK(!box_pair_start(&pair, 8000));

    /* Armed and cancelled with '*': the old field stays and the arming is gone. */
    fresh(1000);
    box_pair_stop(&pair, "test");
    adoption_restore(&adopt, old_key, "Campo velho");
    CHECK(adoption_allow_move(&adopt, true) && box_pair_start(&pair, 2000));
    CHECK(box_pair_key(&pair, '*', 2500) && !adopt.move_armed);
    CHECK(memcmp(adopt.key, old_key, 32) == 0 && !box_pair_start(&pair, 3000));
    /* The code timing out disarms it too. */
    CHECK(adoption_allow_move(&adopt, true) && box_pair_start(&pair, 4000));
    box_pair_tick(&pair, 4000 + BOX_PAIR_SHOW_MS + 1);
    CHECK(!box_pair_showing(&pair) && !adopt.move_armed && memcmp(adopt.key, old_key, 32) == 0);
    /* Another field's card taken while armed (with its PIN) ends the code. */
    CHECK(adoption_allow_move(&adopt, true) && box_pair_start(&pair, 400000));
    CHECK(adoption_offer(&adopt, pv_run_join_key, "Campo", "4321") == ADOPT_READOPTED);
    box_pair_tick(&pair, 400100);
    CHECK(!box_pair_showing(&pair) && !adopt.move_armed);
}

void run_box_pair_tests(void)
{
    test_move_to_another_field();
    test_cpace_draft();
    test_run_math();
    test_vector_run();
    test_wrong_code();
    test_done_after_a_failed_adoption();
    test_limits();
}
