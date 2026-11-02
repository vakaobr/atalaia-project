/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * Tests for i2c_health: a failing device is suspended after a few failures, skipped without
 * touching the bus, tried again after a doubling back-off and brought back by one success; a run
 * of failures on the bus asks for a reset, not more often than the minimum gap.
 */
#include "check.h"
#include "i2c_health.h"

static void test_new_device_is_allowed(void)
{
    i2c_health_t h;
    i2c_health_init(&h);
    CHECK(i2c_health_allow(&h, 0));
    CHECK(i2c_health_report(&h, 0, true) == I2C_HEALTH_NONE);
    CHECK(h.ok == 1 && h.errors == 0 && !h.suspended);
}

static void test_failures_below_the_limit_do_not_suspend(void)
{
    i2c_health_t h;
    i2c_health_init(&h);
    for (int i = 0; i < I2C_HEALTH_FAIL_LIMIT - 1; i++) {
        CHECK(i2c_health_allow(&h, 10u * (unsigned)i));
        CHECK(i2c_health_report(&h, 10u * (unsigned)i, false) == I2C_HEALTH_NONE);
    }
    CHECK(!h.suspended);
    /* A success in between starts the count again. */
    CHECK(i2c_health_report(&h, 100, true) == I2C_HEALTH_NONE);
    CHECK(i2c_health_report(&h, 110, false) == I2C_HEALTH_NONE);
    CHECK(i2c_health_report(&h, 120, false) == I2C_HEALTH_NONE);
    CHECK(!h.suspended && h.consecutive_fail == 2);
}

static void test_suspended_after_the_limit_and_skipped(void)
{
    i2c_health_t h;
    i2c_health_init(&h);
    i2c_health_event_t ev = I2C_HEALTH_NONE;
    for (int i = 0; i < I2C_HEALTH_FAIL_LIMIT; i++) ev = i2c_health_report(&h, 1000, false);
    CHECK(ev == I2C_HEALTH_SUSPENDED);
    CHECK(h.suspended && h.suspensions == 1);
    CHECK(h.backoff_ms == I2C_HEALTH_BACKOFF_MIN_MS);
    /* Until the back-off has passed nothing is tried, and the skips are counted. */
    CHECK(!i2c_health_allow(&h, 1000));
    CHECK(!i2c_health_allow(&h, 1000 + I2C_HEALTH_BACKOFF_MIN_MS - 1));
    CHECK(h.skipped == 2);
    CHECK(i2c_health_allow(&h, 1000 + I2C_HEALTH_BACKOFF_MIN_MS));
}

static void test_backoff_doubles_up_to_the_cap(void)
{
    i2c_health_t h;
    i2c_health_init(&h);
    uint32_t now = 0;
    for (int i = 0; i < I2C_HEALTH_FAIL_LIMIT; i++) i2c_health_report(&h, now, false);
    uint32_t expect = I2C_HEALTH_BACKOFF_MIN_MS;
    for (int round = 0; round < 12; round++) {
        CHECK(h.backoff_ms == expect);
        now = h.retry_at_ms;
        CHECK(i2c_health_allow(&h, now));
        CHECK(i2c_health_report(&h, now, false) == I2C_HEALTH_STILL_DOWN);
        expect = expect * 2 > I2C_HEALTH_BACKOFF_MAX_MS ? I2C_HEALTH_BACKOFF_MAX_MS : expect * 2;
    }
    CHECK(h.backoff_ms == I2C_HEALTH_BACKOFF_MAX_MS);
    CHECK(h.retry_at_ms == now + I2C_HEALTH_BACKOFF_MAX_MS);
    CHECK(h.suspensions == 1); /* one suspension, however long it lasts */
}

static void test_one_success_recovers(void)
{
    i2c_health_t h;
    i2c_health_init(&h);
    for (int i = 0; i < I2C_HEALTH_FAIL_LIMIT; i++) i2c_health_report(&h, 0, false);
    CHECK(h.suspended);
    CHECK(i2c_health_allow(&h, h.retry_at_ms));
    CHECK(i2c_health_report(&h, h.retry_at_ms, true) == I2C_HEALTH_RECOVERED);
    CHECK(!h.suspended && h.consecutive_fail == 0 && h.recoveries == 1);
    CHECK(i2c_health_allow(&h, h.retry_at_ms));
    /* Suspending again starts from the shortest wait. */
    for (int i = 0; i < I2C_HEALTH_FAIL_LIMIT; i++) i2c_health_report(&h, 5000, false);
    CHECK(h.suspended && h.suspensions == 2 && h.backoff_ms == I2C_HEALTH_BACKOFF_MIN_MS);
}

static void test_millisecond_counter_wrap(void)
{
    i2c_health_t h;
    i2c_health_init(&h);
    uint32_t now = 0xFFFFFF00u; /* 256 ms before the counter wraps */
    for (int i = 0; i < I2C_HEALTH_FAIL_LIMIT; i++) i2c_health_report(&h, now, false);
    CHECK(!i2c_health_allow(&h, now + 100));
    CHECK(!i2c_health_allow(&h, now + 499)); /* 243 ms after the wrap */
    CHECK(i2c_health_allow(&h, now + 500));
}

static void test_bus_resets_after_a_run_and_not_too_often(void)
{
    i2c_bus_health_t b;
    i2c_bus_health_init(&b);
    for (int i = 0; i < I2C_BUS_RESET_FAIL_RUN - 1; i++)
        CHECK(!i2c_bus_health_report(&b, 0, false));
    CHECK(i2c_bus_health_report(&b, 0, false)); /* the run is complete: reset */
    CHECK(b.resets == 1);
    /* Another run right away waits for the minimum gap. */
    for (int i = 0; i < 20; i++) CHECK(!i2c_bus_health_report(&b, 10, false));
    CHECK(b.resets == 1);
    CHECK(i2c_bus_health_report(&b, I2C_BUS_RESET_MIN_GAP_MS, false));
    CHECK(b.resets == 2);
}

static void test_bus_success_breaks_the_run(void)
{
    i2c_bus_health_t b;
    i2c_bus_health_init(&b);
    for (int i = 0; i < 50; i++) {
        CHECK(!i2c_bus_health_report(&b, (uint32_t)i, false));
        CHECK(!i2c_bus_health_report(&b, (uint32_t)i, false));
        CHECK(!i2c_bus_health_report(&b, (uint32_t)i, true));
    }
    CHECK(b.resets == 0);
}

void run_i2c_health_tests(void)
{
    test_new_device_is_allowed();
    test_failures_below_the_limit_do_not_suspend();
    test_suspended_after_the_limit_and_skipped();
    test_backoff_doubles_up_to_the_cap();
    test_one_success_recovers();
    test_millisecond_counter_wrap();
    test_bus_resets_after_a_run_and_not_too_often();
    test_bus_success_breaks_the_run();
}
