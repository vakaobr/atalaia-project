/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Tests for the ACK tracker: register, confirm, retry and priority
 * behaviour.
 */
#include <stdio.h>
#include <string.h>

#include "atalaia/ack.h"
#include "atalaia/protocol.h"
#include "check.h"

static void test_register_and_confirm(void)
{
    atalaia_ack_tracker_t t;
    atalaia_ack_init(&t);

    CHECK(atalaia_ack_register(&t, 1, 10, ATALAIA_PRIO_NORMAL, 0));
    CHECK(t.count == 1);
    CHECK(t.entries[0].status == ATALAIA_ACK_PENDING);

    atalaia_ack_confirm(&t, 1, 10);
    CHECK(t.entries[0].status == ATALAIA_ACK_CONFIRMED);
}

static void test_telemetry_auto_confirm(void)
{
    atalaia_ack_tracker_t t;
    atalaia_ack_init(&t);

    CHECK(atalaia_ack_register(&t, 1, 20, ATALAIA_PRIO_TELEMETRY, 0));
    CHECK(t.entries[0].status == ATALAIA_ACK_CONFIRMED);
}

static void test_confirm_cumulative(void)
{
    atalaia_ack_tracker_t t;
    atalaia_ack_init(&t);

    atalaia_ack_register(&t, 5, 1, ATALAIA_PRIO_NORMAL, 0);
    atalaia_ack_register(&t, 5, 2, ATALAIA_PRIO_NORMAL, 0);
    atalaia_ack_register(&t, 5, 3, ATALAIA_PRIO_CRITICAL, 0);
    atalaia_ack_register(&t, 5, 4, ATALAIA_PRIO_NORMAL, 0);

    atalaia_ack_confirm_cumulative(&t, 5, 3);

    CHECK(t.entries[0].status == ATALAIA_ACK_CONFIRMED);
    CHECK(t.entries[1].status == ATALAIA_ACK_CONFIRMED);
    CHECK(t.entries[2].status == ATALAIA_ACK_CONFIRMED);
    CHECK(t.entries[3].status == ATALAIA_ACK_PENDING);
}

static void test_get_retries(void)
{
    atalaia_ack_tracker_t t;
    atalaia_ack_init(&t);

    atalaia_ack_register(&t, 1, 1, ATALAIA_PRIO_CRITICAL, 0);
    atalaia_ack_register(&t, 1, 2, ATALAIA_PRIO_NORMAL, 0);

    /* Before the retry interval: nothing. */
    atalaia_ack_entry_t retries[4];
    size_t n = atalaia_ack_get_retries(&t, 1000, retries, 4);
    CHECK(n == 0);

    /* After the retry interval: both pending. */
    n = atalaia_ack_get_retries(&t, ATALAIA_ACK_RETRY_MS + 1, retries, 4);
    CHECK(n == 2);
}

static void test_tick_expires(void)
{
    atalaia_ack_tracker_t t;
    atalaia_ack_init(&t);

    atalaia_ack_register(&t, 1, 1, ATALAIA_PRIO_NORMAL, 0);

    /* Simulate ticking past max retries. */
    uint32_t now = 0;
    for (int i = 0; i < ATALAIA_ACK_MAX_RETRIES; i++) {
        now += ATALAIA_ACK_RETRY_MS;
        atalaia_ack_tick(&t, now);
    }
    CHECK(t.entries[0].status == ATALAIA_ACK_EXPIRED);
}

static void test_critical_keeps_retrying(void)
{
    atalaia_ack_tracker_t t;
    atalaia_ack_init(&t);

    atalaia_ack_register(&t, 1, 1, ATALAIA_PRIO_CRITICAL, 0);

    /* After a few ticks, it is still pending (not expired yet). */
    uint32_t now = 0;
    for (int i = 0; i < 5; i++) {
        now += ATALAIA_ACK_RETRY_MS;
        atalaia_ack_tick(&t, now);
    }
    CHECK(t.entries[0].status == ATALAIA_ACK_PENDING);
    CHECK(t.entries[0].retries == 5);
}

static void test_queue_full(void)
{
    atalaia_ack_tracker_t t;
    atalaia_ack_init(&t);

    for (uint16_t i = 0; i < ATALAIA_ACK_QUEUE_SIZE; i++) {
        CHECK(atalaia_ack_register(&t, 1, i, ATALAIA_PRIO_NORMAL, 0));
    }
    /* Queue is full now. */
    CHECK(!atalaia_ack_register(&t, 1, 9999, ATALAIA_PRIO_NORMAL, 0));
}

void run_ack_tests(void)
{
    test_register_and_confirm();
    test_telemetry_auto_confirm();
    test_confirm_cumulative();
    test_get_retries();
    test_tick_expires();
    test_critical_keeps_retrying();
    test_queue_full();
}
