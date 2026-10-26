/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The bench test of listen-before-talk's gate (decision SL-25): the receiver-state half of the
 * radio's channel_busy() (radio/channel_busy.c), the stub HAL's channel_busy(), and the bench's
 * arithmetic (radio/lbt_stats.c): classifying probes against a frame's reconstructed window.
 */
#include <string.h>

#include "check.h"
#include "hal/hal.h"
#include "hal/stub/hal_stub.h"
#include "radio/channel_busy.h"
#include "radio/lbt_stats.h"

#define AIR_US 92416u /* a 47-byte frame, SF7/125 kHz (test_radio_limits.c) */
#define SYM_US 1024u
#define MAX_US (AIR_US * 5 / 4)

/* ---- the receiver's state ----------------------------------------------------------------- */

static void test_rx_state(void)
{
    cb_track_t t;
    memset(&t, 0, sizeof(t));
    bool clear = true;

    /* No flag: free. */
    CHECK(cb_rx_state(&t, 0, 1, 1000, MAX_US, &clear) == HAL_BUSY_FREE);
    CHECK(!clear);
    /* A preamble, then a valid header: busy for the rest of the frame. */
    CHECK(cb_rx_state(&t, CB_IRQ_PREAMBLE, 1, 2000, MAX_US, &clear) == HAL_BUSY_PREAMBLE);
    CHECK(cb_rx_state(&t, CB_IRQ_PREAMBLE | CB_IRQ_HEADER_VALID, 1, 20000, MAX_US, &clear) ==
          HAL_BUSY_HEADER);
    CHECK(cb_rx_state(&t, CB_IRQ_PREAMBLE | CB_IRQ_HEADER_VALID, 1, 90000, MAX_US, &clear) ==
          HAL_BUSY_HEADER);
    CHECK(!clear);
    /* RxDone: the frame ended; not busy, and the flags are left for the reader to clear. */
    CHECK(cb_rx_state(&t, CB_IRQ_PREAMBLE | CB_IRQ_HEADER_VALID | CB_IRQ_RX_DONE, 1, 95000, MAX_US,
                      &clear) == HAL_BUSY_RX_DONE);
    CHECK(!clear);
    CHECK(!t.tracking);
}

static void test_rx_state_stale_flag(void)
{
    cb_track_t t;
    memset(&t, 0, sizeof(t));
    bool clear = false;
    /* A preamble of another network's frame: no RxDone ever comes. Believed for one longest
     * frame, then cleared and reported free. */
    CHECK(cb_rx_state(&t, CB_IRQ_PREAMBLE, 1, 1000, MAX_US, &clear) == HAL_BUSY_PREAMBLE);
    CHECK(cb_rx_state(&t, CB_IRQ_PREAMBLE, 1, 1000 + MAX_US, MAX_US, &clear) == HAL_BUSY_PREAMBLE);
    CHECK(!clear);
    CHECK(cb_rx_state(&t, CB_IRQ_PREAMBLE, 1, 1000 + MAX_US + 1, MAX_US, &clear) == HAL_BUSY_FREE);
    CHECK(clear);
    /* After the clear the flag is gone; a new one (new epoch) is a new frame. */
    CHECK(cb_rx_state(&t, 0, 2, 600000, MAX_US, &clear) == HAL_BUSY_FREE);
    CHECK(cb_rx_state(&t, CB_IRQ_PREAMBLE, 2, 700000, MAX_US, &clear) == HAL_BUSY_PREAMBLE);
}

static void test_rx_state_epoch(void)
{
    cb_track_t t;
    memset(&t, 0, sizeof(t));
    bool clear = false;
    CHECK(cb_rx_state(&t, CB_IRQ_PREAMBLE, 1, 0, MAX_US, &clear) == HAL_BUSY_PREAMBLE);
    /* The IRQ status was cleared (the epoch moved on) and a new frame's flag is up, with no probe
     * in between: it is timed from now, not from the old frame. */
    CHECK(cb_rx_state(&t, CB_IRQ_PREAMBLE, 2, 5 * MAX_US, MAX_US, &clear) == HAL_BUSY_PREAMBLE);
    CHECK(!clear);
    CHECK(t.first_seen == (int64_t)5 * MAX_US);
}

static void test_rx_state_header_error(void)
{
    cb_track_t t;
    memset(&t, 0, sizeof(t));
    bool clear = false;
    CHECK(cb_rx_state(&t, CB_IRQ_PREAMBLE | CB_IRQ_HEADER_ERR, 1, 10, MAX_US, &clear) ==
          HAL_BUSY_FREE);
    CHECK(clear);
}

/* ---- the stub HAL's channel_busy ------------------------------------------------------------ */

static void test_stub_channel_busy(void)
{
    hal_t hal;
    hal_stub_init(&hal);
    hal.radio->init();
    hal.radio->set_mode(HAL_RADIO_MODE_RX);
    hal_radio_busy_t info;

    /* Nothing flagged, nothing on the channel: one CAD, receive again. */
    hal_stub_radio_now_us = 1000;
    CHECK(!hal_radio_channel_busy(hal.radio, &info));
    CHECK(info.why == HAL_BUSY_FREE && info.cad_us > 0 && info.rearm_us > 0);
    CHECK(hal_stub_radio_cad_calls == 1 && hal_stub_radio_rx_rearms == 1);
    CHECK(hal_stub_radio_mode == HAL_RADIO_MODE_RX);

    /* A CAD that sees a preamble. */
    hal_stub_radio_cad_detects = true;
    CHECK(hal_radio_channel_busy(hal.radio, &info));
    CHECK(info.why == HAL_BUSY_CAD);
    hal_stub_radio_cad_detects = false;

    /* The receiver is on a frame: busy without a CAD (a CAD would abort the reception). */
    int cads = hal_stub_radio_cad_calls;
    hal_stub_radio_irq = CB_IRQ_PREAMBLE;
    CHECK(hal_radio_channel_busy(hal.radio, &info));
    CHECK(info.why == HAL_BUSY_PREAMBLE && info.cad_us == 0 && info.rearm_us == 0);
    hal_stub_radio_irq = CB_IRQ_PREAMBLE | CB_IRQ_HEADER_VALID;
    CHECK(hal_radio_channel_busy(hal.radio, &info));
    CHECK(info.why == HAL_BUSY_HEADER);
    CHECK(hal_stub_radio_cad_calls == cads);

    /* The frame ended: not busy, and no CAD or re-arm that would lose it. */
    hal_stub_radio_irq = CB_IRQ_RX_DONE | CB_IRQ_PREAMBLE | CB_IRQ_HEADER_VALID;
    CHECK(!hal_radio_channel_busy(hal.radio, &info));
    CHECK(info.why == HAL_BUSY_RX_DONE);
    CHECK(hal_stub_radio_cad_calls == cads);
    CHECK(hal_stub_radio_irq & CB_IRQ_RX_DONE); /* left for recv() */

    /* A radio error is "free" through the wrapper, and says so. */
    hal.radio->set_mode(HAL_RADIO_MODE_RX);
    hal_stub_radio_cad_fails = true;
    CHECK(!hal_radio_channel_busy(hal.radio, &info));
    CHECK(info.why == HAL_BUSY_ERROR);
    hal_stub_radio_cad_fails = false;

    /* Not in receive (after a TX timeout, a retune): a CAD, then receive. */
    hal.radio->set_mode(HAL_RADIO_MODE_STANDBY);
    hal_stub_radio_irq = CB_IRQ_PREAMBLE; /* stale: not looked at */
    CHECK(!hal_radio_channel_busy(hal.radio, &info));
    CHECK(info.why == HAL_BUSY_FREE && hal_stub_radio_mode == HAL_RADIO_MODE_RX);

    /* A HAL without the test: free. */
    hal_radio_ops_t none = *hal.radio;
    none.channel_busy = NULL;
    CHECK(!hal_radio_channel_busy(&none, &info));
    CHECK(!hal_radio_channel_busy(NULL, NULL));
    hal.radio->deinit();
}

/* ---- the bench's arithmetic ----------------------------------------------------------------- */

/* Probes every 2 ms over [from, to); busy_fn says what each one found. */
static void probe_span(lbt_stats_t *s, uint32_t from, uint32_t to, hal_busy_why_t why)
{
    for (uint32_t t = from; (int32_t)(t - to) < 0; t += 2000) {
        lbt_stats_probe(s, t, why, why == HAL_BUSY_CAD || why == HAL_BUSY_FREE ? 3500 : 0,
                        why == HAL_BUSY_CAD || why == HAL_BUSY_FREE ? 400 : 0);
    }
}

static void test_stats_full_coverage(void)
{
    lbt_stats_t s;
    lbt_stats_init(&s);
    uint32_t end = 1000000, start = end - AIR_US;
    /* 200 ms of quiet, then the frame: the CAD sees the preamble, the receiver's flags the rest. */
    probe_span(&s, start - 200000, start, HAL_BUSY_FREE);
    probe_span(&s, start, start + 12 * SYM_US, HAL_BUSY_CAD);
    probe_span(&s, start + 12 * SYM_US, start + 20 * SYM_US, HAL_BUSY_PREAMBLE);
    probe_span(&s, start + 20 * SYM_US, end, HAL_BUSY_HEADER);
    lbt_stats_frame(&s, end, AIR_US, SYM_US, 0);

    CHECK(s.frames == 1 && s.frames_lost == 0);
    CHECK(lbt_stats_in_total(&s) > 40);
    CHECK(lbt_stats_hit_total(&s) == lbt_stats_in_total(&s));
    for (int d = 0; d < LBT_DECILES; d++) {
        CHECK(s.in_n[d] >= 4);
        CHECK(s.in_hit[d] == s.in_n[d]);
    }
    CHECK(s.seg_n[LBT_SEG_PREAMBLE] > 0 && s.seg_n[LBT_SEG_HEADER] > 0 &&
          s.seg_n[LBT_SEG_PAYLOAD] > 0);
    /* The quiet 200 ms at 2 ms came before the first frame heard: a frame may have been lost
     * there, so it is unplaced, not "outside". */
    CHECK(s.out_n == 0 && s.amb_n == 100);
    CHECK(s.hit_cad > 0 && s.hit_preamble > 0 && s.hit_header > 0);
    CHECK(s.pending_n == 0);
    CHECK(s.cad_n == 100 + s.hit_cad && s.cad_min_us == 3500 && s.cad_max_us == 3500);
    CHECK(s.rearm_max_us == 400);
    CHECK(lbt_permille(lbt_stats_hit_total(&s), lbt_stats_in_total(&s)) == 1000);
}

static void test_stats_cad_alone_is_blind(void)
{
    /* A plain CAD (no receiver state) sees only the preamble: probes after it find nothing. */
    lbt_stats_t s;
    lbt_stats_init(&s);
    uint32_t end = 5000000, start = end - AIR_US;
    probe_span(&s, start, start + 49 * SYM_US / 4, HAL_BUSY_CAD); /* 12.25 symbols */
    probe_span(&s, start + 14000, end, HAL_BUSY_FREE);
    lbt_stats_frame(&s, end, AIR_US, SYM_US, 0);
    uint32_t pm = lbt_permille(lbt_stats_hit_total(&s), lbt_stats_in_total(&s));
    CHECK(pm > 100 && pm < 200); /* about 12.5 of 92 ms */
    CHECK(s.in_hit[0] == s.in_n[0] && s.in_hit[9] == 0);
    CHECK(s.seg_hit[LBT_SEG_PAYLOAD] == 0 &&
          s.seg_hit[LBT_SEG_PREAMBLE] == s.seg_n[LBT_SEG_PREAMBLE]);
}

static void test_stats_false_busy_and_next_frame(void)
{
    lbt_stats_t s;
    lbt_stats_init(&s);
    uint32_t end1 = 1000000, end2 = 2000000;
    probe_span(&s, end1 - AIR_US, end1, HAL_BUSY_HEADER);
    lbt_stats_frame(&s, end1, AIR_US, SYM_US, 0); /* the first: its quiet before is unplaced */
    /* Between the frames: ten busy probes outside any frame, the rest quiet, and probes that
     * belong to frame 2 (after frame 1, waiting). */
    for (int i = 0; i < 10; i++)
        lbt_stats_probe(&s, end1 + 10000 + (uint32_t)i * 2000, HAL_BUSY_CAD, 3500, 400);
    probe_span(&s, end1 + 50000, end2 - AIR_US, HAL_BUSY_FREE);
    probe_span(&s, end2 - AIR_US, end2, HAL_BUSY_HEADER);
    lbt_stats_frame(&s, end2, AIR_US, SYM_US, 0);
    CHECK(s.frames == 2);
    CHECK(s.out_busy == 10);
    CHECK(s.out_n > 400);
    CHECK(s.out_busy * 1000 / s.out_n < 25);
    CHECK(lbt_stats_hit_total(&s) == lbt_stats_in_total(&s));
}

static void test_stats_lost_frame_is_not_false_busy(void)
{
    lbt_stats_t s;
    lbt_stats_init(&s);
    uint32_t end1 = 1000000;
    probe_span(&s, end1 - AIR_US, end1, HAL_BUSY_HEADER);
    lbt_stats_frame(&s, end1, AIR_US, SYM_US, 0);
    /* A frame in between was not received (its probes found it busy), then frame 3 arrives with
     * a gap of one in the sequence numbers: those probes judge nothing. */
    uint32_t end3 = 1800000;
    probe_span(&s, end1 + 200000, end1 + 300000, HAL_BUSY_HEADER);
    probe_span(&s, end1 + 300000, end3 - AIR_US, HAL_BUSY_FREE);
    probe_span(&s, end3 - AIR_US, end3, HAL_BUSY_HEADER);
    lbt_stats_frame(&s, end3, AIR_US, SYM_US, 1);
    CHECK(s.frames == 2 && s.frames_lost == 1);
    CHECK(s.out_n == 0 && s.out_busy == 0);
    CHECK(s.amb_n > 200 && s.dropped == 0);
}

static void test_stats_first_frame_and_errors_and_wrap(void)
{
    lbt_stats_t s;
    lbt_stats_init(&s);
    /* The clock wraps at 2^32 us: the frame ends just after it. */
    uint32_t end = 40000;
    uint32_t start = end - AIR_US; /* wraps to near 2^32 */
    CHECK(start > 0x80000000u);
    probe_span(&s, start - 20000, start, HAL_BUSY_FREE);
    probe_span(&s, start, end, HAL_BUSY_HEADER);
    lbt_stats_probe(&s, start + 50000, HAL_BUSY_ERROR, 0, 0);
    lbt_stats_frame(&s, end, AIR_US, SYM_US, 0);
    CHECK(lbt_stats_in_total(&s) > 40 && lbt_stats_hit_total(&s) == lbt_stats_in_total(&s));
    CHECK(s.err_n == 1);
    CHECK(s.out_n == 0 && s.amb_n == 10); /* before the first frame heard: unplaced */
}

static void test_stats_pending_overflow(void)
{
    lbt_stats_t s;
    lbt_stats_init(&s);
    for (uint32_t i = 0; i < LBT_PENDING_MAX + 5; i++)
        lbt_stats_probe(&s, i * 1000, HAL_BUSY_FREE, 0, 0);
    CHECK(s.pending_n == LBT_PENDING_MAX && s.dropped == 5);
}

/* ---- the frame, the numbers, the command --------------------------------------------------- */

static void test_frame(void)
{
    uint32_t rng = 12345;
    uint8_t buf[255];
    uint32_t seq = 0;
    CHECK(lbt_frame_build(buf, 52, 0xA1B2C3D4u, &rng));
    CHECK(lbt_frame_parse(buf, 52, &seq) && seq == 0xA1B2C3D4u);
    CHECK(!lbt_frame_build(buf, 4, 1, &rng));
    CHECK(!lbt_frame_build(buf, 256, 1, &rng));
    buf[0] = 'X';
    CHECK(!lbt_frame_parse(buf, 52, &seq));
    CHECK(!lbt_frame_parse(buf, 5, &seq));

    /* The random numbers: in range, deterministic from the seed, and not all alike. */
    uint32_t a = 77, b = 77, lo = 99, hi = 0;
    for (int i = 0; i < 2000; i++) {
        uint32_t x = lbt_rand_range(&a, LBT_STATE_LEN_MIN, LBT_STATE_LEN_MAX);
        CHECK(x == lbt_rand_range(&b, LBT_STATE_LEN_MIN, LBT_STATE_LEN_MAX));
        CHECK(x >= LBT_STATE_LEN_MIN && x <= LBT_STATE_LEN_MAX);
        if (x < lo) lo = x;
        if (x > hi) hi = x;
    }
    CHECK(lo == LBT_STATE_LEN_MIN && hi == LBT_STATE_LEN_MAX);
    uint32_t zero = 0;
    CHECK(lbt_rand(&zero) != 0); /* a zero seed does not stick */
}

static void test_parse_cmd(void)
{
    lbt_cmd_t c;
    CHECK(lbt_parse_cmd("tx", &c) && c.kind == LBT_CMD_TX && c.frames == LBT_FRAMES_DEFAULT);
    CHECK(lbt_parse_cmd("tx 50", &c) && c.kind == LBT_CMD_TX && c.frames == 50);
    CHECK(lbt_parse_cmd(" tx 1000 ", &c) && c.frames == 1000);
    CHECK(!lbt_parse_cmd("tx 1001", &c) && c.kind == LBT_CMD_BAD); /* the duty guard's cap */
    CHECK(!lbt_parse_cmd("tx 0", &c));
    CHECK(!lbt_parse_cmd("tx 5 6", &c));
    CHECK(!lbt_parse_cmd("txx", &c));
    CHECK(lbt_parse_cmd("probe", &c) && c.kind == LBT_CMD_PROBE && c.frames == LBT_FRAMES_DEFAULT &&
          c.gap_min_us == 2000 && c.gap_max_us == 5000);
    CHECK(lbt_parse_cmd("probe 100", &c) && c.frames == 100 && c.gap_max_us == 5000);
    CHECK(lbt_parse_cmd("probe 100 1000 3000", &c) && c.gap_min_us == 1000 && c.gap_max_us == 3000);
    CHECK(!lbt_parse_cmd("probe 100 3000 1000", &c));
    CHECK(!lbt_parse_cmd("probe 100 3000", &c));
    CHECK(!lbt_parse_cmd("probe x", &c));
    CHECK(!lbt_parse_cmd("probe 100 1000 3000 9", &c));
    CHECK(lbt_parse_cmd("stop", &c) && c.kind == LBT_CMD_STOP);
    CHECK(lbt_parse_cmd("status", &c) && c.kind == LBT_CMD_STATUS);
    CHECK(!lbt_parse_cmd("", &c) && !lbt_parse_cmd("go", &c) && !lbt_parse_cmd(NULL, &c));
}

void run_lbt_tests(void)
{
    test_rx_state();
    test_rx_state_stale_flag();
    test_rx_state_epoch();
    test_rx_state_header_error();
    test_stub_channel_busy();
    test_stats_full_coverage();
    test_stats_cad_alone_is_blind();
    test_stats_false_busy_and_next_frame();
    test_stats_lost_frame_is_not_false_busy();
    test_stats_first_frame_and_errors_and_wrap();
    test_stats_pending_overflow();
    test_frame();
    test_parse_cmd();
}
