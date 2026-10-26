/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Tests for listen before talk (atalaia/lbt.h, RFC 0001 Amendment 14).
 */
#include <stdio.h>

#include "atalaia/lbt.h"
#include "check.h"

/* A seeded stub: xorshift32, or a scripted value. */
typedef struct {
    uint32_t state;
    int scripted_n;
    const uint32_t *scripted;
    int calls;
} stub_rand_t;

static uint32_t stub_rand(void *ctx)
{
    stub_rand_t *r = (stub_rand_t *)ctx;
    r->calls++;
    if (r->scripted != NULL && r->scripted_n > 0) {
        return r->scripted[(r->calls - 1) % r->scripted_n];
    }
    uint32_t x = r->state;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    r->state = x;
    return x;
}

static void test_free_channel_sends_at_once(void)
{
    stub_rand_t r = {.state = 12345};
    atalaia_lbt_t l;
    atalaia_lbt_init(&l, stub_rand, &r);
    uint32_t w = 0;
    CHECK(atalaia_lbt_should_listen(&l));
    CHECK(atalaia_lbt_decide(&l, false, &w) == ATALAIA_LBT_SEND);
    CHECK(r.calls == 0); /* no wait drawn when free */
}

static void test_busy_waits_20_to_200(void)
{
    stub_rand_t r = {.state = 99};
    uint32_t lo = 1000, hi = 0;
    for (int k = 0; k < 2000; k++) {
        atalaia_lbt_t l;
        atalaia_lbt_init(&l, stub_rand, &r);
        uint32_t w = 0;
        CHECK(atalaia_lbt_decide(&l, true, &w) == ATALAIA_LBT_WAIT);
        if (w < lo) lo = w;
        if (w > hi) hi = w;
    }
    CHECK(lo >= ATALAIA_LBT_WAIT_MIN_MS && hi <= ATALAIA_LBT_WAIT_MAX_MS);
    /* The whole range is reached. */
    CHECK(lo <= ATALAIA_LBT_WAIT_MIN_MS + 3 && hi >= ATALAIA_LBT_WAIT_MAX_MS - 3);
}

static void test_wait_edges_follow_the_draw(void)
{
    /* span 181: draw 0 -> 20, 180 -> 200, 181 -> 20 again. */
    const uint32_t script[] = {0, 180, 181, 0xFFFFFFFFu};
    stub_rand_t r = {.scripted = script, .scripted_n = 4};
    uint32_t expect[] = {20, 200, 20, 20 + 0xFFFFFFFFu % 181u};
    for (int i = 0; i < 4; i++) {
        atalaia_lbt_t l;
        atalaia_lbt_init(&l, stub_rand, &r);
        uint32_t w = 0;
        CHECK(atalaia_lbt_decide(&l, true, &w) == ATALAIA_LBT_WAIT);
        CHECK(w == expect[i]);
    }
}

static void test_gives_up_after_eight_tries(void)
{
    stub_rand_t r = {.state = 7};
    atalaia_lbt_t l;
    atalaia_lbt_init(&l, stub_rand, &r);
    uint32_t w;
    for (int i = 0; i < ATALAIA_LBT_MAX_TRIES; i++) {
        CHECK(atalaia_lbt_should_listen(&l));
        CHECK(atalaia_lbt_decide(&l, true, &w) == ATALAIA_LBT_WAIT);
    }
    CHECK(r.calls == ATALAIA_LBT_MAX_TRIES);
    /* The 9th turn: no look at the channel, and the frame goes. */
    CHECK(!atalaia_lbt_should_listen(&l));
    CHECK(atalaia_lbt_decide(&l, true, &w) == ATALAIA_LBT_SEND_ANYWAY);
    CHECK(r.calls == ATALAIA_LBT_MAX_TRIES); /* no ninth wait drawn */
    /* The next frame starts again. */
    CHECK(atalaia_lbt_should_listen(&l));
    CHECK(atalaia_lbt_decide(&l, true, &w) == ATALAIA_LBT_WAIT);
}

static void test_free_after_some_waits_resets_the_count(void)
{
    stub_rand_t r = {.state = 3};
    atalaia_lbt_t l;
    atalaia_lbt_init(&l, stub_rand, &r);
    uint32_t w;
    for (int i = 0; i < 5; i++) CHECK(atalaia_lbt_decide(&l, true, &w) == ATALAIA_LBT_WAIT);
    CHECK(atalaia_lbt_decide(&l, false, &w) == ATALAIA_LBT_SEND);
    /* A fresh frame gets its eight waits. */
    for (int i = 0; i < ATALAIA_LBT_MAX_TRIES; i++) {
        CHECK(atalaia_lbt_decide(&l, true, &w) == ATALAIA_LBT_WAIT);
    }
    CHECK(atalaia_lbt_decide(&l, true, &w) == ATALAIA_LBT_SEND_ANYWAY);
}

static void test_reset_and_null_wait(void)
{
    stub_rand_t r = {.state = 5};
    atalaia_lbt_t l;
    atalaia_lbt_init(&l, stub_rand, &r);
    uint32_t w;
    for (int i = 0; i < 4; i++) CHECK(atalaia_lbt_decide(&l, true, &w) == ATALAIA_LBT_WAIT);
    atalaia_lbt_reset(&l);
    CHECK(l.tries == 0);
    CHECK(atalaia_lbt_decide(&l, true, NULL) == ATALAIA_LBT_WAIT); /* wait_ms may be NULL */
}

static void test_same_seed_same_waits(void)
{
    uint32_t a[8], b[8];
    for (int run = 0; run < 2; run++) {
        stub_rand_t r = {.state = 2026};
        atalaia_lbt_t l;
        atalaia_lbt_init(&l, stub_rand, &r);
        for (int i = 0; i < 8; i++) {
            uint32_t w = 0;
            CHECK(atalaia_lbt_decide(&l, true, &w) == ATALAIA_LBT_WAIT);
            (run == 0 ? a : b)[i] = w;
        }
    }
    for (int i = 0; i < 8; i++) CHECK(a[i] == b[i]);
}

void run_lbt_tests(void)
{
    test_free_channel_sends_at_once();
    test_busy_waits_20_to_200();
    test_wait_edges_follow_the_draw();
    test_gives_up_after_eight_tries();
    test_free_after_some_waits_resets_the_count();
    test_reset_and_null_wait();
    test_same_seed_same_waits();
}
