/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Tests for the dedupe table, jitter and relay logic.
 */
#include <stdio.h>

#include "atalaia/flood.h"
#include "check.h"

static void test_dedupe_basic(void)
{
    atalaia_dedupe_t d;
    atalaia_dedupe_init(&d);

    /* First time: not seen. */
    CHECK(!atalaia_dedupe_seen(&d, 1, 100, 0));
    /* Second time: seen. */
    CHECK(atalaia_dedupe_seen(&d, 1, 100, 10));
    /* Different source: not seen. */
    CHECK(!atalaia_dedupe_seen(&d, 2, 100, 20));
    /* Different seq: not seen. */
    CHECK(!atalaia_dedupe_seen(&d, 1, 101, 30));
}

static void test_dedupe_expire(void)
{
    atalaia_dedupe_t d;
    atalaia_dedupe_init(&d);

    CHECK(!atalaia_dedupe_seen(&d, 1, 1, 0));
    CHECK(atalaia_dedupe_seen(&d, 1, 1, 10000));

    /* The last seen_at_ms was refreshed to 10000, so it stays valid
     * until 10000 + 30000 = 40000 (exclusive). */
    CHECK(atalaia_dedupe_seen(&d, 1, 1, 29999));

    /* After 30 s from the last refresh (29999), the entry expires. */
    CHECK(!atalaia_dedupe_seen(&d, 1, 1, 60000));
}

static void test_dedupe_evict_lru(void)
{
    atalaia_dedupe_t d;
    atalaia_dedupe_init(&d);

    /* Fill the table. */
    for (uint16_t i = 0; i < ATALAIA_DEDUPE_SIZE; i++) {
        CHECK(!atalaia_dedupe_seen(&d, 0, i, i));
    }
    CHECK(d.count == ATALAIA_DEDUPE_SIZE);

    /* All entries are within the expiry window, so the next insert evicts
     * the oldest (seq=0, seen_at_ms=0). */
    CHECK(!atalaia_dedupe_seen(&d, 0, 9999, ATALAIA_DEDUPE_SIZE));
    CHECK(d.count == ATALAIA_DEDUPE_SIZE);

    /* seq=0 was evicted; it should no longer be seen. */
    CHECK(!atalaia_dedupe_seen(&d, 0, 0, ATALAIA_DEDUPE_SIZE + 1));
}

static void test_jitter_range(void)
{
    /* All jitter values must be in [JITTER_MIN, JITTER_MAX]. */
    for (uint16_t src = 0; src < 100; src++) {
        for (uint16_t seq = 0; seq < 100; seq++) {
            uint32_t j = atalaia_flood_jitter_ms(src, seq);
            CHECK(j >= ATALAIA_JITTER_MIN_MS && j <= ATALAIA_JITTER_MAX_MS);
        }
    }
}

static void test_jitter_varies(void)
{
    /* Different (source, seq) pairs should produce different jitter for
     * at least some cases (not all the same). */
    int same = 0;
    uint32_t first = atalaia_flood_jitter_ms(0, 0);
    for (uint16_t i = 1; i < 100; i++) {
        if (atalaia_flood_jitter_ms(i, i) == first) same++;
    }
    CHECK(same < 90); /* most should differ */
}

static void test_relay_decision(void)
{
    uint8_t new_hl;

    /* hop_limit = 0: do not relay. */
    CHECK(!atalaia_flood_should_relay(0, 5, &new_hl));
    CHECK(new_hl == 0);

    /* hop_limit = 1: relay once with new_hop_limit = 0. */
    CHECK(atalaia_flood_should_relay(1, 5, &new_hl));
    CHECK(new_hl == 0);

    /* hop_limit = 2, max_hops = 5: relay with new = 1. */
    CHECK(atalaia_flood_should_relay(2, 5, &new_hl));
    CHECK(new_hl == 1);

    /* hop_limit = 10, max_hops = 3: clamped to 3, relay with new = 2. */
    CHECK(atalaia_flood_should_relay(10, 3, &new_hl));
    CHECK(new_hl == 2);

    /* hop_limit = 1, max_hops = 1: clamped to 1, relay with new = 0. */
    CHECK(atalaia_flood_should_relay(1, 1, &new_hl));
    CHECK(new_hl == 0);
}

void run_flood_tests(void)
{
    test_dedupe_basic();
    test_dedupe_expire();
    test_dedupe_evict_lru();
    test_jitter_range();
    test_jitter_varies();
    test_relay_decision();
}
