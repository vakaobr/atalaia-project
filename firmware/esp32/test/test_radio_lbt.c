/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The radio task's transmit stage with listen before talk (radio/radio_lbt.c, RFC 0001
 * Amendment 14, decision SL-25), driven on a scripted fake HAL: busy N times then free, busy for
 * ever (gives up after 8), the receiver's flag instead of a CAD, the duty-cycle budget, order,
 * tags. The radio task (radio_task.c, ESP32 only) is this stage plus a queue and a loop; the
 * loop's own granularity is checked here as a 10 ms turn.
 */
#include <string.h>

#include "check.h"
#include "radio/radio_lbt.h"

/* ---- A scripted radio ---------------------------------------------------------------------- */

enum { FREE = 0, BUSY_CAD = 1, BUSY_FLAG = 2 };

typedef struct {
    int script[64]; /* the answers, in order; past the end: script_default */
    int script_len;
    int script_default;
    int busy_calls;
    int sends;
    uint8_t last[RADIO_MAX_PKT_LEN];
    size_t last_len;
    int send_rc;
    uint32_t duty_ms;
    uint32_t sent_at_ms; /* the clock when send() was called */
} fake_t;

static fake_t fk;
static uint32_t clock_ms;

static int fk_busy(hal_radio_busy_t *info)
{
    int a = fk.busy_calls < fk.script_len ? fk.script[fk.busy_calls] : fk.script_default;
    fk.busy_calls++;
    info->why = a == FREE ? HAL_BUSY_FREE : a == BUSY_CAD ? HAL_BUSY_CAD : HAL_BUSY_PREAMBLE;
    info->cad_us = a == BUSY_FLAG ? 0 : 8000; /* a receiver flag costs no CAD */
    info->rearm_us = 0;
    info->sample_us = 0;
    return a == FREE ? 0 : 1;
}

static int fk_send(const uint8_t *d, size_t n)
{
    fk.sends++;
    memcpy(fk.last, d, n);
    fk.last_len = n;
    fk.sent_at_ms = clock_ms;
    return fk.send_rc;
}

static uint32_t fk_duty(void)
{
    return fk.duty_ms;
}

static const hal_radio_ops_t fake_radio = {
    .send = fk_send, .duty_cycle_remaining_ms = fk_duty, .channel_busy = fk_busy};
static const hal_radio_ops_t fake_radio_no_busy = {.send = fk_send,
                                                   .duty_cycle_remaining_ms = fk_duty};

static uint32_t seed;
static uint32_t rnd(void *ctx)
{
    (void)ctx;
    seed ^= seed << 13;
    seed ^= seed >> 17;
    seed ^= seed << 5;
    return seed;
}

static void reset_fake(void)
{
    memset(&fk, 0, sizeof(fk));
    fk.duty_ms = 360000;
    clock_ms = 1000;
    seed = 0xC0FFEE;
}

static radio_tx_msg_t frame(uint8_t first, uint32_t tag)
{
    radio_tx_msg_t m;
    memset(&m, 0, sizeof(m));
    m.len = 48;
    memset(m.data, first, m.len);
    m.tag = tag;
    return m;
}

/* The radio task's loop: a turn every 10 ms until the frame is gone (or limit_ms). Returns the ms
 * it took. */
static uint32_t run_until_done(radio_txs_t *t, uint32_t limit_ms, uint32_t *tag,
                               radio_tx_status_t *status)
{
    uint32_t start = clock_ms;
    while (clock_ms - start <= limit_ms) {
        if (radio_txs_step(t, clock_ms, tag, status) == RADIO_TXS_DONE) return clock_ms - start;
        clock_ms += 10;
    }
    return UINT32_MAX;
}

/* ---- Tests --------------------------------------------------------------------------------- */

static void test_disabled_sends_at_once(void)
{
    reset_fake();
    radio_txs_t t;
    radio_txs_init(&t, &fake_radio, false, rnd, NULL);
    fk.script_default = BUSY_CAD; /* would be busy for ever */
    radio_tx_msg_t m = frame(0xA1, 5);
    CHECK(radio_txs_load(&t, &m, clock_ms));
    uint32_t tag = 0;
    radio_tx_status_t st = RADIO_TX_RESULT_ERROR;
    CHECK(radio_txs_step(&t, clock_ms, &tag, &st) == RADIO_TXS_DONE);
    CHECK(tag == 5 && st == RADIO_TX_RESULT_OK && fk.sends == 1);
    CHECK(fk.busy_calls == 0 && t.stats.cads == 0 && t.stats.deferrals == 0);
    /* No channel_busy in the HAL at all: the same, even enabled. */
    radio_txs_init(&t, &fake_radio_no_busy, true, rnd, NULL);
    CHECK(radio_txs_load(&t, &m, clock_ms));
    CHECK(radio_txs_step(&t, clock_ms, &tag, &st) == RADIO_TXS_DONE && fk.sends == 2);
}

static void test_free_channel_sends_at_once_after_one_cad(void)
{
    reset_fake();
    radio_txs_t t;
    radio_txs_init(&t, &fake_radio, true, rnd, NULL);
    radio_tx_msg_t m = frame(0xB2, 0);
    uint32_t tag = 9;
    radio_tx_status_t st = RADIO_TX_RESULT_ERROR;
    CHECK(radio_txs_step(&t, clock_ms, &tag, &st) == RADIO_TXS_IDLE);
    CHECK(radio_txs_load(&t, &m, clock_ms));
    CHECK(!radio_txs_load(&t, &m, clock_ms)); /* one in hand */
    CHECK(radio_txs_step(&t, clock_ms, &tag, &st) == RADIO_TXS_DONE);
    CHECK(tag == 0 && st == RADIO_TX_RESULT_OK);
    CHECK(fk.sends == 1 && fk.last[0] == 0xB2 && fk.last_len == 48);
    CHECK(t.stats.cads == 1 && t.stats.deferrals == 0 && t.stats.gave_up == 0);
    CHECK(!radio_txs_busy(&t));
}

static void test_busy_n_times_then_free(void)
{
    reset_fake();
    radio_txs_t t;
    radio_txs_init(&t, &fake_radio, true, rnd, NULL);
    fk.script[0] = BUSY_CAD;
    fk.script[1] = BUSY_CAD;
    fk.script[2] = BUSY_CAD;
    fk.script_len = 3; /* then free */
    radio_tx_msg_t m = frame(0xC3, 77);
    CHECK(radio_txs_load(&t, &m, clock_ms));
    uint32_t t0 = clock_ms, tag = 0;
    radio_tx_status_t st = RADIO_TX_RESULT_ERROR;
    /* The first look: busy, held. Nothing is sent and the loop goes on. */
    CHECK(radio_txs_step(&t, clock_ms, &tag, &st) == RADIO_TXS_WAITING);
    CHECK(fk.sends == 0 && radio_txs_busy(&t));
    uint32_t w = radio_txs_wait_ms(&t, clock_ms);
    CHECK(w >= ATALAIA_LBT_WAIT_MIN_MS && w <= ATALAIA_LBT_WAIT_MAX_MS);
    /* Before the wait has passed no CAD is made. */
    clock_ms += w - 1;
    CHECK(radio_txs_step(&t, clock_ms, &tag, &st) == RADIO_TXS_WAITING);
    CHECK(fk.busy_calls == 1);
    clock_ms += 1;
    uint32_t took = run_until_done(&t, 2000, &tag, &st);
    CHECK(took != UINT32_MAX);
    CHECK(tag == 77 && st == RADIO_TX_RESULT_OK && fk.sends == 1);
    CHECK(fk.busy_calls == 4);
    CHECK(t.stats.cads == 4 && t.stats.deferrals == 3 && t.stats.gave_up == 0);
    /* Three waits of 20-200 ms, each honoured to the 10 ms turn. */
    uint32_t total = fk.sent_at_ms - t0;
    CHECK(total >= 3 * ATALAIA_LBT_WAIT_MIN_MS && total <= 3 * (ATALAIA_LBT_WAIT_MAX_MS + 10));
}

static void test_gives_up_after_eight_tries(void)
{
    reset_fake();
    radio_txs_t t;
    radio_txs_init(&t, &fake_radio, true, rnd, NULL);
    fk.script_default = BUSY_CAD; /* never free */
    radio_tx_msg_t m = frame(0xD4, 3);
    CHECK(radio_txs_load(&t, &m, clock_ms));
    uint32_t t0 = clock_ms, tag = 0;
    radio_tx_status_t st = RADIO_TX_RESULT_ERROR;
    CHECK(run_until_done(&t, 4000, &tag, &st) != UINT32_MAX);
    CHECK(tag == 3 && st == RADIO_TX_RESULT_OK && fk.sends == 1 && fk.last[0] == 0xD4);
    CHECK(t.stats.deferrals == 8 && t.stats.gave_up == 1);
    CHECK(t.stats.cads == 8 && fk.busy_calls == 8); /* the ninth turn makes no CAD */
    uint32_t total = fk.sent_at_ms - t0;
    CHECK(total >= 8 * ATALAIA_LBT_WAIT_MIN_MS && total <= 8 * (ATALAIA_LBT_WAIT_MAX_MS + 10));
    /* The next frame gets its own eight. */
    CHECK(radio_txs_load(&t, &m, clock_ms));
    fk.busy_calls = 0;
    fk.script_default = FREE;
    CHECK(radio_txs_step(&t, clock_ms, &tag, &st) == RADIO_TXS_DONE);
    CHECK(t.stats.gave_up == 1 && t.stats.deferrals == 8);
}

static void test_receiver_flag_defers_without_a_cad(void)
{
    reset_fake();
    radio_txs_t t;
    radio_txs_init(&t, &fake_radio, true, rnd, NULL);
    fk.script[0] = BUSY_FLAG;
    fk.script[1] = BUSY_FLAG;
    fk.script_len = 2;
    radio_tx_msg_t m = frame(0xE5, 0);
    CHECK(radio_txs_load(&t, &m, clock_ms));
    uint32_t tag = 0;
    radio_tx_status_t st = RADIO_TX_RESULT_ERROR;
    CHECK(run_until_done(&t, 2000, &tag, &st) != UINT32_MAX);
    CHECK(t.stats.deferrals == 2);
    CHECK(t.stats.cads == 1); /* only the last look ran a CAD (free) */
}

static void test_duty_cycle_is_the_real_sends_business(void)
{
    reset_fake();
    radio_txs_t t;
    radio_txs_init(&t, &fake_radio, true, rnd, NULL);
    uint32_t tag = 0;
    radio_tx_status_t st = RADIO_TX_RESULT_OK;
    radio_tx_msg_t m = frame(0xF6, 8);

    /* Budget exhausted: refused at once, no CAD and no waiting. */
    fk.duty_ms = 0;
    fk.script_default = BUSY_CAD;
    CHECK(radio_txs_load(&t, &m, clock_ms));
    CHECK(radio_txs_step(&t, clock_ms, &tag, &st) == RADIO_TXS_DONE);
    CHECK(tag == 8 && st == RADIO_TX_RESULT_DUTY_CYCLE && fk.sends == 0 && fk.busy_calls == 0);

    /* A budget too small for this frame: the HAL says so at the send, after the wait. */
    fk.duty_ms = 50;
    fk.send_rc = -3;
    fk.script[0] = BUSY_CAD;
    fk.script_len = 1;
    fk.script_default = FREE;
    CHECK(radio_txs_load(&t, &m, clock_ms));
    CHECK(radio_txs_step(&t, clock_ms, &tag, &st) == RADIO_TXS_WAITING);
    CHECK(run_until_done(&t, 2000, &tag, &st) != UINT32_MAX);
    CHECK(st == RADIO_TX_RESULT_DUTY_CYCLE && fk.sends == 1);

    /* A radio error. */
    fk.send_rc = -1;
    fk.busy_calls = 0;
    fk.script_len = 0;
    CHECK(radio_txs_load(&t, &m, clock_ms));
    CHECK(radio_txs_step(&t, clock_ms, &tag, &st) == RADIO_TXS_DONE);
    CHECK(st == RADIO_TX_RESULT_ERROR);
}

static void test_frames_go_in_order_one_at_a_time(void)
{
    reset_fake();
    radio_txs_t t;
    radio_txs_init(&t, &fake_radio, true, rnd, NULL);
    fk.script[0] = BUSY_CAD;
    fk.script_len = 1;
    radio_tx_msg_t a = frame(0x11, 1), b = frame(0x22, 2);
    CHECK(radio_txs_load(&t, &a, clock_ms));
    uint32_t tag = 0;
    radio_tx_status_t st = RADIO_TX_RESULT_ERROR;
    CHECK(radio_txs_step(&t, clock_ms, &tag, &st) == RADIO_TXS_WAITING);
    CHECK(!radio_txs_load(&t, &b, clock_ms)); /* held: the queue behind it waits */
    CHECK(run_until_done(&t, 2000, &tag, &st) != UINT32_MAX && tag == 1 && fk.last[0] == 0x11);
    CHECK(radio_txs_load(&t, &b, clock_ms));
    CHECK(radio_txs_step(&t, clock_ms, &tag, &st) == RADIO_TXS_DONE && tag == 2);
    CHECK(fk.last[0] == 0x22 && fk.sends == 2);
}

static void test_waits_follow_the_given_source(void)
{
    /* The same seed waits the same. */
    uint32_t waits[2][8];
    for (int run = 0; run < 2; run++) {
        reset_fake();
        radio_txs_t t;
        radio_txs_init(&t, &fake_radio, true, rnd, NULL);
        fk.script_default = BUSY_CAD;
        radio_tx_msg_t m = frame(0x33, 0);
        radio_txs_load(&t, &m, clock_ms);
        uint32_t tag;
        radio_tx_status_t st;
        for (int i = 0; i < 8; i++) {
            CHECK(radio_txs_step(&t, clock_ms, &tag, &st) == RADIO_TXS_WAITING);
            waits[run][i] = radio_txs_wait_ms(&t, clock_ms);
            clock_ms += waits[run][i];
        }
    }
    CHECK(memcmp(waits[0], waits[1], sizeof(waits[0])) == 0);
}

void run_radio_lbt_tests(void)
{
    test_disabled_sends_at_once();
    test_free_channel_sends_at_once_after_one_cad();
    test_busy_n_times_then_free();
    test_gives_up_after_eight_tries();
    test_receiver_flag_defers_without_a_cad();
    test_duty_cycle_is_the_real_sends_business();
    test_frames_go_in_order_one_at_a_time();
    test_waits_follow_the_given_source();
}
