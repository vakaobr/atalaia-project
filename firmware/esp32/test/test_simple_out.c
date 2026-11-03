/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Tests for simple_out.c (draft RFC "The expansion port", EXP-32, EXP-34): the burst scheduler
 * against a fake RMT that records every burst (bursts of 25 frames topped up every 200 ms, never
 * more than 0.5 s queued, so pulses stop within 0.5 s of the game task's last turn; widths 1.0
 * and 2.0 ms; a change of width flushes; the signal's end is 0.5 s of 1.0 ms and then nothing),
 * and the pins the build refuses (45 with the buzzer, 46 on a V4.2, 5 on a V4.3, another part's).
 */
#include <stdio.h>
#include <string.h>

#include "check.h"
#include "simple_out.h"

typedef struct {
    uint16_t width;
    uint16_t frames;
    bool flush;
    uint32_t t;
} burst_t;

static burst_t bursts[256];
static int burst_count;
static bool rmt_refuses;
static uint32_t clock_ms;

static bool fake_send(void *ctx, uint16_t width_us, uint16_t frames, bool flush)
{
    (void)ctx;
    if (rmt_refuses) return false;
    if (burst_count < 256) bursts[burst_count++] = (burst_t){width_us, frames, flush, clock_ms};
    return true;
}

static simple_out_t so;

static void fresh(void)
{
    burst_count = 0;
    rmt_refuses = false;
    clock_ms = 1000;
    simple_out_rmt_t rmt = {.ctx = NULL, .send = fake_send};
    simple_out_init(&so, 46, &rmt);
}

/* Turns of the game task every 10 ms until `until`, the channel on/off and live or not. */
static void run_until(uint32_t until, bool on, bool live)
{
    while ((int32_t)(clock_ms - until) < 0) {
        simple_out_drive(&so, on, live, clock_ms);
        clock_ms += 10;
    }
}

/* The queue never holds more than 0.5 s, and while live it never runs dry. */
static void check_horizon(bool live)
{
    CHECK(so.horizon_ms - clock_ms <= SO_BURST_MS);
    if (live) CHECK(simple_out_pulsing(&so, clock_ms));
}

static void test_boot_signal_ends(void)
{
    fresh();
    /* Boot: not live, off: 0.5 s of 1.0 ms pulses, then nothing (the pin low). */
    simple_out_drive(&so, false, false, clock_ms);
    CHECK(burst_count == 1);
    CHECK(bursts[0].width == SO_OFF_US && bursts[0].frames == SO_BURST_FRAMES && !bursts[0].flush);
    CHECK(simple_out_pulsing(&so, clock_ms + SO_BURST_MS - 1));
    run_until(clock_ms + 5000, false, false);
    CHECK(burst_count == 1);
    CHECK(!simple_out_pulsing(&so, clock_ms));
}

static void test_live_off_renewed(void)
{
    fresh();
    simple_out_drive(&so, false, false, clock_ms); /* boot */
    clock_ms += 2000;
    burst_count = 0;
    /* A game runs: a live "off", 1.0 ms pulses that never stop while the task turns. */
    uint32_t start = clock_ms;
    simple_out_drive(&so, false, true, clock_ms);
    CHECK(burst_count == 1 && bursts[0].width == SO_OFF_US && bursts[0].frames == 25);
    CHECK(!bursts[0].flush); /* nothing was queued any more */
    for (uint32_t t = 0; t < 3000; t += 10) {
        clock_ms += 10;
        simple_out_drive(&so, false, true, clock_ms);
        check_horizon(true);
    }
    /* Renewed every 200 ms with what brings the queue back to 0.5 s: 10 frames each. */
    CHECK(burst_count == 1 + 3000 / SO_RENEW_MS);
    for (int i = 1; i < burst_count; i++) {
        CHECK(bursts[i].width == SO_OFF_US && !bursts[i].flush);
        CHECK(bursts[i].frames == SO_RENEW_MS / SO_FRAME_MS);
        CHECK(bursts[i].t - bursts[i - 1].t == SO_RENEW_MS);
    }
    CHECK(bursts[1].t == start + SO_RENEW_MS);
}

static void test_on_flushes_and_hang_stops(void)
{
    fresh();
    run_until(clock_ms + 1000, false, true);
    int before = burst_count;
    /* On: the queued off pulses go, 2.0 ms pulses start at once. */
    simple_out_drive(&so, true, true, clock_ms);
    CHECK(burst_count == before + 1);
    CHECK(bursts[before].width == SO_ON_US && bursts[before].frames == 25 && bursts[before].flush);
    run_until(clock_ms + 1000, true, true);
    check_horizon(true);
    /* The game task hangs right after a renewal: the pulses stop within 0.5 s, by themselves. */
    uint32_t last_turn = clock_ms - 10;
    CHECK(so.horizon_ms - last_turn <= SO_BURST_MS);
    CHECK(simple_out_pulsing(&so, last_turn));
    CHECK(!simple_out_pulsing(&so, last_turn + SO_BURST_MS));
}

static void test_end_after_on(void)
{
    fresh();
    run_until(clock_ms + 500, true, true);
    int before = burst_count;
    /* The game pauses with the channel on: 1.0 ms at once for 0.5 s, then the pin low. */
    simple_out_drive(&so, false, false, clock_ms);
    CHECK(burst_count == before + 1);
    CHECK(bursts[before].width == SO_OFF_US && bursts[before].frames == 25 && bursts[before].flush);
    uint32_t ends = clock_ms + SO_BURST_MS;
    run_until(clock_ms + 3000, false, false);
    CHECK(burst_count == before + 1);
    CHECK(!simple_out_pulsing(&so, ends));
}

static void test_end_after_live_off(void)
{
    fresh();
    run_until(clock_ms + 1050, false, true);
    int before = burst_count;
    /* Off pulses already: topped up to a full 0.5 s once more, not flushed, then nothing. */
    simple_out_drive(&so, false, false, clock_ms);
    CHECK(burst_count <= before + 1);
    if (burst_count == before + 1)
        CHECK(!bursts[before].flush && bursts[before].width == SO_OFF_US);
    CHECK(so.horizon_ms - clock_ms <= SO_BURST_MS && so.horizon_ms - clock_ms >= SO_BURST_MS - 20);
    run_until(clock_ms + 3000, false, false);
    CHECK(burst_count <= before + 1);
    CHECK(!simple_out_pulsing(&so, clock_ms));
}

static void test_late_turns_leave_no_gap(void)
{
    fresh();
    simple_out_drive(&so, true, true, clock_ms);
    /* The task is late now and then (30 ms instead of 10): the queue never runs dry and never
     * holds more than 0.5 s. */
    for (int i = 0; i < 400; i++) {
        clock_ms += (i % 7 == 3) ? 30 : 10;
        simple_out_drive(&so, true, true, clock_ms);
        check_horizon(true);
    }
}

static void test_refused_send_retried(void)
{
    fresh();
    rmt_refuses = true;
    simple_out_drive(&so, true, true, clock_ms);
    CHECK(burst_count == 0 && !simple_out_pulsing(&so, clock_ms));
    rmt_refuses = false;
    clock_ms += 10;
    simple_out_drive(&so, true, true, clock_ms);
    CHECK(burst_count == 1 && bursts[0].width == SO_ON_US && bursts[0].frames == 25);
}

static void test_pins(void)
{
    const so_pin_use_t field_box[] = {
        {"button 1", 4},      {"button 2", 48},      {"button 3", 44},     {"the LED ring", 35},
        {"the display", 33},  {"the display", 47},   {"the display", 1},   {"the display", 3},
        {"the amplifier", 6}, {"the amplifier", 15}, {"the amplifier", 16}};
    size_t n = sizeof(field_box) / sizeof(field_box[0]);
    /* The plan's pins (EXP-34). */
    CHECK(simple_out_pin_problem(46, SO_BOARD_V4_3, -1, field_box, n) == NULL);
    CHECK(simple_out_pin_problem(5, SO_BOARD_V4_2, -1, field_box, n) == NULL);
    CHECK(simple_out_pin_problem(45, SO_BOARD_V4_3, -1, field_box, n) == NULL); /* no buzzer */
    CHECK(simple_out_pin_problem(33, SO_BOARD_V4_3, -1, NULL, 0) == NULL);      /* the pod */
    CHECK(simple_out_pin_problem(15, SO_BOARD_V4_3, -1, NULL, 0) == NULL);      /* board 5 */
    /* Refused: the buzzer's 45, the other revision's front-end line. */
    CHECK(simple_out_pin_problem(45, SO_BOARD_V4_3, 45, field_box, n) != NULL);
    CHECK(strstr(simple_out_pin_problem(45, SO_BOARD_V4_3, 45, NULL, 0), "buzzer") != NULL);
    CHECK(simple_out_pin_problem(46, SO_BOARD_V4_2, -1, NULL, 0) != NULL);
    CHECK(simple_out_pin_problem(5, SO_BOARD_V4_3, -1, NULL, 0) != NULL);
    /* Another part's pin: board 5's 15 is the amplifier's on a Field Box. */
    const char *why = simple_out_pin_problem(15, SO_BOARD_V4_3, -1, field_box, n);
    CHECK(why != NULL && strstr(why, "amplifier") != NULL);
    CHECK(simple_out_pin_problem(35, SO_BOARD_V4_3, -1, field_box, n) != NULL);
    CHECK(simple_out_pin_problem(-1, SO_BOARD_V4_3, -1, NULL, 0) != NULL);
    for (int g = 0; g <= 49; g++) {
        bool internal = g == 0 || g == 2 || g == 7 || (g >= 8 && g <= 14) || g == 17 || g == 18 ||
                        g == 19 || g == 20 || g == 21 || (g >= 22 && g <= 32) || g == 34 ||
                        g == 36 || g == 37 || (g >= 38 && g <= 44) || g == 49;
        if (internal) CHECK(simple_out_pin_problem(g, SO_BOARD_V4_3, -1, NULL, 0) != NULL);
    }
}

void run_simple_out_tests(void)
{
    test_boot_signal_ends();
    test_live_off_renewed();
    test_on_flushes_and_hang_stops();
    test_end_after_on();
    test_end_after_live_off();
    test_late_turns_leave_no_gap();
    test_refused_send_retried();
    test_pins();
}
