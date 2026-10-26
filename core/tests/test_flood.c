/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Tests for the dedupe table, jitter, relay decision and the relay rules of RFC 0001 Amendment 13.
 */
#include <stdio.h>

#include "atalaia/ack.h"
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

/* ---- Relay rules (RFC 0001 Amendment 13, decision SL-16) ---------------------------------- */

/* A seeded stand-in for the box's entropy: xorshift32, or a script of values. */
typedef struct {
    uint32_t state;
    const uint32_t *script;
    size_t script_len, used;
    size_t draws;
} stub_t;

static uint32_t stub_rand(void *ctx)
{
    stub_t *s = (stub_t *)ctx;
    s->draws++;
    if (s->script != NULL) {
        uint32_t v = s->script[s->used < s->script_len ? s->used : s->script_len - 1];
        s->used++;
        return v;
    }
    uint32_t x = s->state;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    s->state = x;
    return x;
}

static void hear_boxes(atalaia_relay_t *r, uint16_t first, int count, uint32_t now)
{
    for (int i = 0; i < count; i++) atalaia_relay_heard(r, (uint16_t)(first + i), now);
}

static void test_relay_slot_count(void)
{
    CHECK(ATALAIA_RELAY_SLOTS == 8);
    stub_t st = {1, NULL, 0, 0, 0};
    atalaia_relay_t r;
    atalaia_relay_init(&r, stub_rand, &st);
    atalaia_relay_heard(&r, 9, 1000); /* one neighbour: every frame relays */
    for (uint16_t i = 0; i < ATALAIA_RELAY_SLOTS; i++) {
        CHECK(atalaia_relay_plan(&r, ATALAIA_RELAY_OTHER, 9, i, 0, 1000) == (int)i);
    }
    CHECK(atalaia_relay_pending(&r) == ATALAIA_RELAY_SLOTS);
    /* The ninth is dropped, not queued. */
    CHECK(atalaia_relay_plan(&r, ATALAIA_RELAY_OTHER, 9, 99, 0, 1000) == ATALAIA_RELAY_NO_SLOT);
    CHECK(atalaia_relay_pending(&r) == ATALAIA_RELAY_SLOTS);
    /* A slot frees when its delay has passed, and the next frame takes it. */
    CHECK(atalaia_relay_take_due(&r, 1000) == -1);
    int freed = atalaia_relay_take_due(&r, 1000 + ATALAIA_RELAY_DELAY_MAX_MS);
    CHECK(freed >= 0 && atalaia_relay_pending(&r) == ATALAIA_RELAY_SLOTS - 1);
    CHECK(atalaia_relay_plan(&r, ATALAIA_RELAY_OTHER, 9, 100, 0, 2000) == freed);
}

static void test_relay_delay_ranges(void)
{
    /* The delay is 20 + d % 581 for every frame but those that ask for an ACK (350 + d % 351). */
    const uint32_t draws[] = {0, 580, 581, 100000, 4294967295u};
    for (size_t k = 0; k < sizeof(draws) / sizeof(draws[0]); k++) {
        stub_t st = {0, &draws[k], 1, 0, 0};
        atalaia_relay_t r;
        atalaia_relay_init(&r, stub_rand, &st);
        int slot = atalaia_relay_plan(&r, ATALAIA_RELAY_OTHER, 9, 1, 0, 5000);
        CHECK(slot == 0);
        uint32_t d = r.slots[0].due_ms - 5000;
        CHECK(d == 20 + draws[k] % 581);
        CHECK(d >= ATALAIA_RELAY_DELAY_MIN_MS && d <= ATALAIA_RELAY_DELAY_MAX_MS);
        CHECK(st.draws == 1); /* one neighbour (floor of 1): the probability took no draw */

        stub_t sa = {0, &draws[k], 1, 0, 0};
        atalaia_relay_t ra;
        atalaia_relay_init(&ra, stub_rand, &sa);
        slot = atalaia_relay_plan(&ra, ATALAIA_RELAY_ASKS_ACK, 9, 1, 0, 5000);
        CHECK(slot == 0 && ra.slots[0].wait_ack);
        d = ra.slots[0].due_ms - 5000;
        CHECK(d == 350 + draws[k] % 351);
        CHECK(d >= ATALAIA_RELAY_ACK_WAIT_MIN_MS && d <= ATALAIA_RELAY_ACK_WAIT_MAX_MS);
        CHECK(sa.draws == 1); /* a frame that asks for an ACK always waits: no probability */
    }
}

static void test_relay_cancelled_when_the_ack_is_overheard(void)
{
    stub_t st = {7, NULL, 0, 0, 0};
    atalaia_relay_t r;
    atalaia_relay_init(&r, stub_rand, &st);
    int a = atalaia_relay_plan(&r, ATALAIA_RELAY_ASKS_ACK, 9, 10, 0, 0);
    int b = atalaia_relay_plan(&r, ATALAIA_RELAY_ASKS_ACK, 9, 12, 0, 0);
    int c = atalaia_relay_plan(&r, ATALAIA_RELAY_ASKS_ACK, 8, 10, 0, 0); /* another box, same seq */
    int o = atalaia_relay_plan(&r, ATALAIA_RELAY_OTHER, 9, 11, 0, 0);    /* a STATE of box 9 */
    CHECK(a >= 0 && b >= 0 && c >= 0 && o >= 0);

    /* ACK for box 9: seq 10 is the contiguous one (<= 10 covered), 12 needs the bitmap bit 1. */
    uint8_t bits[1] = {0x02}; /* ack_seq 10: bit n = seq 11 + n, so bit 1 = seq 12 */
    CHECK(atalaia_relay_ack_heard(&r, 9, 10, bits, 1) == 2);
    CHECK(!r.slots[a].used && !r.slots[b].used);
    CHECK(r.slots[c].used); /* box 8's frame is not covered by box 9's ACK */
    CHECK(r.slots[o].used); /* a STATE never waited for an ACK */
    CHECK(atalaia_relay_ack_heard(&r, 9, 10, bits, 1) == 0);

    /* Not covered: a seq above the bitmap, and ack_seq 0xFFFF (none) with no bit. */
    int d = atalaia_relay_plan(&r, ATALAIA_RELAY_ASKS_ACK, 5, 300, 0, 0);
    CHECK(atalaia_relay_ack_heard(&r, 5, 10, bits, 1) == 0);
    CHECK(atalaia_relay_ack_heard(&r, 5, 0xFFFF, NULL, 0) == 0);
    CHECK(r.slots[d].used);
    CHECK(atalaia_relay_ack_heard(&r, 5, 300, NULL, 0) == 1);

    /* atalaia_ack_covers itself. */
    uint8_t b2[2] = {0x01, 0x80};
    CHECK(atalaia_ack_covers(5, NULL, 0, 5) && atalaia_ack_covers(5, NULL, 0, 0));
    CHECK(!atalaia_ack_covers(5, NULL, 0, 6));
    CHECK(atalaia_ack_covers(5, b2, 2, 6) && !atalaia_ack_covers(5, b2, 2, 7));
    CHECK(atalaia_ack_covers(5, b2, 2, 6 + 15) && !atalaia_ack_covers(5, b2, 2, 6 + 16));
    CHECK(atalaia_ack_covers(0xFFFF, b2, 2, 0) && !atalaia_ack_covers(0xFFFF, b2, 2, 1));
    CHECK(!atalaia_ack_covers(0xFFFF, NULL, 0, 0));
}

static void test_relay_ack_only_on_the_path(void)
{
    stub_t st = {3, NULL, 0, 0, 0};
    atalaia_relay_t r;
    atalaia_relay_init(&r, stub_rand, &st);
    /* No frame of box 9 relayed: the ACK for it is not. */
    CHECK(atalaia_relay_plan(&r, ATALAIA_RELAY_ACK, 0, 1, 9, 1000) == ATALAIA_RELAY_SKIP);
    CHECK(st.draws == 0);

    /* A frame that asked for an ACK is relayed (due): box 9 is on the path from that moment. */
    int s = atalaia_relay_plan(&r, ATALAIA_RELAY_ASKS_ACK, 9, 4, 0, 1000);
    CHECK(s >= 0);
    CHECK(atalaia_relay_take_due(&r, 1000) == -1);
    CHECK(atalaia_relay_take_due(&r, 1000 + ATALAIA_RELAY_ACK_WAIT_MAX_MS) == s);
    uint32_t at = 1000 + ATALAIA_RELAY_ACK_WAIT_MAX_MS;
    CHECK(atalaia_relay_plan(&r, ATALAIA_RELAY_ACK, 0, 2, 9, at) >= 0);
    CHECK(atalaia_relay_plan(&r, ATALAIA_RELAY_ACK, 0, 3, 8, at) == ATALAIA_RELAY_SKIP);
    /* 30 s later, still; after 30 s, not. */
    CHECK(atalaia_relay_plan(&r, ATALAIA_RELAY_ACK, 0, 4, 9, at + ATALAIA_RELAY_PATH_MS) >= 0);
    CHECK(atalaia_relay_plan(&r, ATALAIA_RELAY_ACK, 0, 5, 9, at + ATALAIA_RELAY_PATH_MS + 1) ==
          ATALAIA_RELAY_SKIP);

    /* A relay cancelled by the ACK never reaches the path. */
    atalaia_relay_t q;
    atalaia_relay_init(&q, stub_rand, &st);
    int w = atalaia_relay_plan(&q, ATALAIA_RELAY_ASKS_ACK, 7, 20, 0, 0);
    CHECK(atalaia_relay_ack_heard(&q, 7, 20, NULL, 0) == 1);
    CHECK(atalaia_relay_take_due(&q, 100000) == -1 && w >= 0);
    CHECK(atalaia_relay_plan(&q, ATALAIA_RELAY_ACK, 0, 1, 7, 100000) == ATALAIA_RELAY_SKIP);
}

/* The probability, with a seeded entropy stub: min(1, 3 / n) over the neighbours heard in 10 min.
 */
static void test_relay_probability(void)
{
    /* No draw at all up to three neighbours. */
    for (int n = 0; n <= 3; n++) {
        stub_t st = {99, NULL, 0, 0, 0};
        atalaia_relay_t r;
        atalaia_relay_init(&r, stub_rand, &st);
        hear_boxes(&r, 20, n, 1000);
        CHECK(atalaia_relay_neighbours(&r, 1000) == (uint32_t)(n > 0 ? n : 1));
        for (int i = 0; i < 20; i++) {
            int slot = atalaia_relay_plan(&r, ATALAIA_RELAY_OTHER, 9, (uint16_t)i, 0, 1000);
            CHECK(slot >= 0);
            atalaia_relay_take_due(&r, 1000 + 1000);
        }
        CHECK(st.draws == 20); /* the delay only */
    }

    /* A scripted draw: 12 neighbours relay when the draw is below 3 (mod 12), and then a second
     * draw sets the delay. */
    for (uint32_t d = 0; d < 12; d++) {
        uint32_t script[2] = {d, 40};
        stub_t st = {0, script, 2, 0, 0};
        atalaia_relay_t r;
        atalaia_relay_init(&r, stub_rand, &st);
        hear_boxes(&r, 20, 12, 1000);
        int slot = atalaia_relay_plan(&r, ATALAIA_RELAY_OTHER, 9, 1, 0, 1000);
        if (d < 3) {
            CHECK(slot == 0 && st.draws == 2 && r.slots[0].due_ms == 1000 + 20 + 40);
        } else {
            CHECK(slot == ATALAIA_RELAY_SKIP && st.draws == 1);
        }
    }

    /* The rate over many frames, for 6, 12 and 30 neighbours, from a seeded stub: within 3 % of
     * 3 / n, and the same seed gives the same sequence of decisions. */
    const int ns[3] = {6, 12, 30};
    for (int k = 0; k < 3; k++) {
        int relayed = 0, total = 20000;
        uint32_t fingerprint = 2166136261u;
        stub_t st = {0xC0FFEEu + (uint32_t)k, NULL, 0, 0, 0};
        atalaia_relay_t r;
        atalaia_relay_init(&r, stub_rand, &st);
        hear_boxes(&r, 20, ns[k], 1000);
        for (int i = 0; i < total; i++) {
            int slot = atalaia_relay_plan(&r, ATALAIA_RELAY_OTHER, 9, (uint16_t)i, 0, 1000);
            if (slot >= 0) {
                relayed++;
                atalaia_relay_take_due(&r, 1000 + 1000);
            }
            fingerprint = (fingerprint ^ (uint32_t)(slot >= 0)) * 16777619u;
        }
        double want = 3.0 / ns[k];
        double got = (double)relayed / total;
        CHECK(got > want - 0.03 && got < want + 0.03);

        stub_t st2 = {0xC0FFEEu + (uint32_t)k, NULL, 0, 0, 0};
        atalaia_relay_t r2;
        atalaia_relay_init(&r2, stub_rand, &st2);
        hear_boxes(&r2, 20, ns[k], 1000);
        uint32_t fp2 = 2166136261u;
        for (int i = 0; i < total; i++) {
            int slot = atalaia_relay_plan(&r2, ATALAIA_RELAY_OTHER, 9, (uint16_t)i, 0, 1000);
            if (slot >= 0) atalaia_relay_take_due(&r2, 1000 + 1000);
            fp2 = (fp2 ^ (uint32_t)(slot >= 0)) * 16777619u;
        }
        CHECK(fp2 == fingerprint);
    }

    /* The controller's ACK on the path draws too (it is "everything else", once on the path). */
    uint32_t script[3] = {0, 0, 0};
    stub_t st = {0, script, 3, 0, 0};
    atalaia_relay_t r;
    atalaia_relay_init(&r, stub_rand, &st);
    atalaia_relay_plan(&r, ATALAIA_RELAY_ASKS_ACK, 9, 1, 0, 1000);
    atalaia_relay_take_due(&r, 5000); /* box 9 on the path */
    hear_boxes(&r, 20, 12, 5000);
    uint32_t skip_draw[2] = {7, 0};
    stub_t st2 = {0, skip_draw, 2, 0, 0};
    r.rand_ctx = &st2;
    CHECK(atalaia_relay_plan(&r, ATALAIA_RELAY_ACK, 0, 1, 9, 5000) == ATALAIA_RELAY_SKIP);
}

static void test_relay_neighbours_expire_and_evict(void)
{
    stub_t st = {5, NULL, 0, 0, 0};
    atalaia_relay_t r;
    atalaia_relay_init(&r, stub_rand, &st);
    hear_boxes(&r, 100, 10, 1000);
    atalaia_relay_heard(&r, 100, 2000); /* the same box again: still 10 */
    CHECK(atalaia_relay_neighbours(&r, 2000) == 10);
    CHECK(atalaia_relay_neighbours(&r, 1000 + ATALAIA_RELAY_NEIGHBOUR_MS) == 10);
    /* Box 100 was heard again at 2000, the other nine at 1000. */
    CHECK(atalaia_relay_neighbours(&r, 1000 + ATALAIA_RELAY_NEIGHBOUR_MS + 1) == 1);
    CHECK(atalaia_relay_neighbours(&r, 2000 + ATALAIA_RELAY_NEIGHBOUR_MS + 1) == 1); /* floor 1 */

    /* More boxes than the table holds: the oldest goes, never more than the table. */
    atalaia_relay_t big;
    atalaia_relay_init(&big, stub_rand, &st);
    for (int i = 0; i < ATALAIA_RELAY_NEIGHBOURS + 10; i++) {
        atalaia_relay_heard(&big, (uint16_t)(500 + i), 1000 + (uint32_t)i);
    }
    CHECK(atalaia_relay_neighbours(&big, 2000) == ATALAIA_RELAY_NEIGHBOURS);
    /* Time 0 is a valid time. */
    atalaia_relay_t z;
    atalaia_relay_init(&z, stub_rand, &st);
    atalaia_relay_heard(&z, 1, 0);
    atalaia_relay_heard(&z, 2, 0);
    CHECK(atalaia_relay_neighbours(&z, 0) == 2);
}

/* The backoff schedule: 3, 6, 12, 24, then 30 s, each x 0.75-1.25. */
static void test_retry_gap_schedule(void)
{
    const uint32_t base[8] = {3000, 6000, 12000, 24000, 30000, 30000, 30000, 30000};
    for (unsigned sends = 1; sends <= 8; sends++) {
        CHECK(atalaia_retry_gap_ms(sends, 250) == base[sends - 1]); /* the middle: x 1.000 */
        CHECK(atalaia_retry_gap_ms(sends, 0) == base[sends - 1] * 3 / 4);
        CHECK(atalaia_retry_gap_ms(sends, 500) == base[sends - 1] * 5 / 4);
        for (uint32_t d = 0; d < 2000; d += 7) {
            uint32_t g = atalaia_retry_gap_ms(sends, d);
            CHECK(g >= base[sends - 1] * 3 / 4 && g <= base[sends - 1] * 5 / 4);
        }
    }
    CHECK(atalaia_retry_gap_ms(0, 250) == 3000);     /* "no send yet" counts as the first */
    CHECK(atalaia_retry_gap_ms(1000, 250) == 30000); /* never above 30 s, whatever the count */
    CHECK(atalaia_retry_gap_ms(5, 4294967295u) <= 37500);
}

void run_flood_tests(void)
{
    test_dedupe_basic();
    test_dedupe_expire();
    test_dedupe_evict_lru();
    test_jitter_range();
    test_jitter_varies();
    test_relay_decision();
    test_relay_slot_count();
    test_relay_delay_ranges();
    test_relay_cancelled_when_the_ack_is_overheard();
    test_relay_ack_only_on_the_path();
    test_relay_probability();
    test_relay_neighbours_expire_and_evict();
    test_retry_gap_schedule();
}
