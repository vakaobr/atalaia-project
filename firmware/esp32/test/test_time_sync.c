/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Tests for the time synchronization module.
 */
#include <stdio.h>

#include "check.h"
#include "radio/time_sync.h"

static void test_slew_converges(void)
{
    atalaia_time_sync_t ts;
    atalaia_time_sync_init(&ts);

    /* Local is 100 ms behind the controller. Feed 4 beacons. */
    for (int i = 0; i < 4; i++) {
        uint32_t controller_time = 1000 + (uint32_t)(i * 1000) + 100;
        uint32_t local_time = 1000 + (uint32_t)(i * 1000);
        atalaia_time_sync_on_beacon(&ts, controller_time, 0, 0, local_time);
    }

    /* The offset should be approximately 100 ms. */
    CHECK(ts.offset_ms >= 80 && ts.offset_ms <= 120);
    CHECK(ts.slew_remaining_ms > 0);
    CHECK(!ts.stepped);

    /* Apply slew adjustments. With 10ms ticks, the slew should converge. */
    int32_t total_adj = 0;
    for (int i = 0; i < 5000; i++) {
        uint32_t adjusted = atalaia_time_sync_adjust(&ts, 10);
        total_adj += (int32_t)adjusted - 10;
        if (ts.slew_remaining_ms == 0) break;
    }
    CHECK(ts.slew_remaining_ms == 0);
    /* The total adjustment should approximately equal the offset. */
    CHECK(total_adj >= 80 && total_adj <= 120);
}

static void test_step_on_large_offset(void)
{
    atalaia_time_sync_t ts;
    atalaia_time_sync_init(&ts);

    /* Local is 600 ms behind -- should trigger a step. */
    atalaia_time_sync_on_beacon(&ts, 1600, 0, 0, 1000);
    CHECK(ts.stepped);
    CHECK(ts.slew_remaining_ms == 0);
    CHECK(ts.offset_ms >= 500);
}

static void test_ignore_small_offset(void)
{
    atalaia_time_sync_t ts;
    atalaia_time_sync_init(&ts);

    /* Local is only 3 ms behind -- should be ignored. */
    atalaia_time_sync_on_beacon(&ts, 1003, 0, 0, 1000);
    CHECK(!ts.stepped);
    CHECK(ts.slew_remaining_ms == 0);
}

static void test_ema(void)
{
    atalaia_time_sync_t ts;
    atalaia_time_sync_init(&ts);

    /* Feed beacons with varying offsets and verify the EMA smooths them. */
    atalaia_time_sync_on_beacon(&ts, 1200, 0, 0, 1000); /* +200 */
    CHECK(ts.offset_ms == 200);

    atalaia_time_sync_on_beacon(&ts, 2100, 0, 0, 2000); /* +100 */
    /* EMA: 200000 + (100000 - 200000)/4 = 175000 -> 175 */
    CHECK(ts.offset_ms >= 170 && ts.offset_ms <= 180);

    atalaia_time_sync_on_beacon(&ts, 3050, 0, 0, 3000); /* +50 */
    /* EMA should continue smoothing down. */
    CHECK(ts.offset_ms > 100 && ts.offset_ms < 180);
}

static void test_adjust_during_slew(void)
{
    atalaia_time_sync_t ts;
    atalaia_time_sync_init(&ts);

    /* Positive slew (local behind): delta should be stretched. */
    atalaia_time_sync_on_beacon(&ts, 1100, 0, 0, 1000);
    CHECK(ts.slew_remaining_ms > 0);
    uint32_t adj = atalaia_time_sync_adjust(&ts, 100);
    /* With 5% slew rate, 100ms tick -> max 5ms adjustment.
     * So adjusted delta should be between 100 and 105. */
    CHECK(adj >= 100 && adj <= 105);
    CHECK(ts.slew_remaining_ms >= 0); /* decreased */

    /* Negative slew (local ahead). */
    atalaia_time_sync_init(&ts);
    atalaia_time_sync_on_beacon(&ts, 900, 0, 0, 1000);
    CHECK(ts.slew_remaining_ms < 0);
    adj = atalaia_time_sync_adjust(&ts, 100);
    /* Delta should be compressed. */
    CHECK(adj >= 95 && adj <= 100);
}

void run_time_sync_tests(void)
{
    test_slew_converges();
    test_step_on_large_offset();
    test_ignore_small_offset();
    test_ema();
    test_adjust_during_slew();
}
