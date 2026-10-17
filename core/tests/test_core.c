/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Tests for events, scores and random numbers, and the test entry point.
 */
#include <stdio.h>
#include <string.h>

#include "atalaia/event.h"
#include "atalaia/score.h"
#include "atalaia/version.h"
#include "check.h"
#include "rand.h"

int check_failures = 0;

static void test_version(void)
{
    CHECK(strcmp(atalaia_version(), "0.1.0") == 0);
    CHECK(ATALAIA_PROTOCOL_VERSION == 1);
}

static void test_event_init(void)
{
    atalaia_event_t ev;
    CHECK(atalaia_event_init(&ev, 7, 42, 1500, "zone.captured", 2, 1, ATALAIA_PRIO_NORMAL));
    CHECK(ev.node == 7 && ev.seq == 42 && ev.t_ms == 1500);
    CHECK(ev.team == 2 && ev.squad == 1);
    CHECK(strcmp(ev.type, "zone.captured") == 0);

    CHECK(!atalaia_event_init(&ev, 1, 1, 0, "", 1, 0, ATALAIA_PRIO_NORMAL));
    CHECK(!atalaia_event_init(&ev, 1, 1, 0, NULL, 1, 0, ATALAIA_PRIO_NORMAL));
    CHECK(!atalaia_event_init(&ev, 1, 1, 0, "x", 251, 0, ATALAIA_PRIO_NORMAL));

    char long_type[ATALAIA_EVENT_TYPE_MAX + 1];
    memset(long_type, 'a', sizeof(long_type) - 1);
    long_type[sizeof(long_type) - 1] = '\0';
    CHECK(!atalaia_event_init(&ev, 1, 1, 0, long_type, 1, 0, ATALAIA_PRIO_NORMAL));
}

static void test_event_order(void)
{
    atalaia_event_t a, b, c;
    atalaia_event_init(&a, 1, 5, 1000, "bomb.armed", 1, 0, ATALAIA_PRIO_CRITICAL);
    atalaia_event_init(&b, 2, 1, 1000, "zone.captured", 2, 0, ATALAIA_PRIO_NORMAL);
    atalaia_event_init(&c, 1, 5, 1000, "bomb.armed", 1, 0, ATALAIA_PRIO_CRITICAL);

    CHECK(atalaia_event_compare(&a, &b) < 0);
    CHECK(atalaia_event_compare(&b, &a) > 0);
    CHECK(atalaia_event_compare(&a, &c) == 0);
    CHECK(atalaia_event_same_id(&a, &c));
    CHECK(!atalaia_event_same_id(&a, &b));
}

static void test_prio_names(void)
{
    CHECK(strcmp(atalaia_prio_name(ATALAIA_PRIO_CRITICAL), "critical") == 0);
    CHECK(strcmp(atalaia_prio_name(ATALAIA_PRIO_TELEMETRY), "telemetry") == 0);
}

static void test_score(void)
{
    atalaia_score_t s;
    atalaia_score_init(&s);
    CHECK(atalaia_score_add(&s, 1, 10));
    CHECK(atalaia_score_add(&s, 1, -3));
    CHECK(atalaia_score_add(&s, 2, 5));
    CHECK(!atalaia_score_add(&s, ATALAIA_TEAM_NONE, 1));
    CHECK(!atalaia_score_add(&s, 251, 1));
    CHECK(atalaia_score_net(&s, 1) == 7);
    CHECK(atalaia_score_net(&s, 2) == 5);
    CHECK(atalaia_score_net(&s, 3) == 0);

    /* Counters saturate instead of wrapping, including INT32_MIN. */
    atalaia_score_t big;
    atalaia_score_init(&big);
    for (int i = 0; i < 3; i++) {
        atalaia_score_add(&big, 1, INT32_MAX);
        atalaia_score_add(&big, 1, INT32_MIN);
    }
    CHECK(big.gained[1] == UINT32_MAX);
    CHECK(big.lost[1] == UINT32_MAX);

    /* A node cut off from the field keeps scoring; merging the controller's
     * stale copy with the node's newer copy keeps the newer counters, and
     * merging in either order gives the same result. */
    atalaia_score_t stale = s;
    atalaia_score_add(&s, 1, 4);
    atalaia_score_add(&s, 2, -1);
    atalaia_score_t a = stale;
    atalaia_score_t b = s;
    atalaia_score_merge(&a, &s);
    atalaia_score_merge(&b, &stale);
    CHECK(atalaia_score_net(&a, 1) == 11);
    CHECK(atalaia_score_net(&a, 2) == 4);
    CHECK(memcmp(&a, &b, sizeof(a)) == 0);
}

static void test_rand(void)
{
    atalaia_rand_t a, b, c;
    atalaia_rand_seed(&a, 1234, 1);
    atalaia_rand_seed(&b, 1234, 1);
    atalaia_rand_seed(&c, 1234, 2);
    int same = 0;
    for (int i = 0; i < 100; i++) {
        uint32_t x = atalaia_rand_next(&a);
        CHECK(x == atalaia_rand_next(&b));
        same += x == atalaia_rand_next(&c);
    }
    CHECK(same < 5); /* another node gets another sequence */

    int seen[6] = {0};
    for (int i = 0; i < 6000; i++) {
        uint32_t x = atalaia_rand_below(&a, 6);
        CHECK(x < 6);
        if (x < 6) {
            seen[x]++;
        }
        double u = atalaia_rand_unit(&a);
        CHECK(u >= 0.0 && u < 1.0);
    }
    for (int i = 0; i < 6; i++) {
        CHECK(seen[i] > 800 && seen[i] < 1200);
    }
}

int main(void)
{
    test_version();
    test_event_init();
    test_event_order();
    test_prio_names();
    test_score();
    test_rand();
    run_node_tests();
    run_codec_tests();

    if (check_failures == 0) {
        printf("core: all tests passed\n");
        return 0;
    }
    fprintf(stderr, "core: %d check(s) failed\n", check_failures);
    return 1;
}
