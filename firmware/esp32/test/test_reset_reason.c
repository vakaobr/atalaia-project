/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * Tests for reset_reason: each cause has its own word on the wire, and a crash is a crash.
 */
#include <string.h>

#include "check.h"
#include "reset_reason.h"

static void test_names(void)
{
    CHECK(strcmp(reset_cause_name(RESET_CAUSE_POWER), "power") == 0);
    CHECK(strcmp(reset_cause_name(RESET_CAUSE_BROWNOUT), "brownout") == 0);
    CHECK(strcmp(reset_cause_name(RESET_CAUSE_SOFTWARE), "software") == 0);
    CHECK(strcmp(reset_cause_name(RESET_CAUSE_PANIC), "panic") == 0);
    CHECK(strcmp(reset_cause_name(RESET_CAUSE_WATCHDOG), "watchdog") == 0);
    CHECK(strcmp(reset_cause_name(RESET_CAUSE_DEEPSLEEP), "deepsleep") == 0);
    CHECK(strcmp(reset_cause_name(RESET_CAUSE_UNKNOWN), "unknown") == 0);
    CHECK(strcmp(reset_cause_name((reset_cause_t)99), "unknown") == 0);
}

static void test_names_are_distinct_and_plain(void)
{
    for (int a = 0; a <= RESET_CAUSE_DEEPSLEEP; a++) {
        const char *na = reset_cause_name((reset_cause_t)a);
        for (const char *c = na; *c; c++) CHECK(*c >= 'a' && *c <= 'z');
        CHECK(strlen(na) < 16);
        for (int b = a + 1; b <= RESET_CAUSE_DEEPSLEEP; b++) {
            CHECK(strcmp(na, reset_cause_name((reset_cause_t)b)) != 0);
        }
    }
}

static void test_crashes(void)
{
    CHECK(reset_cause_is_crash(RESET_CAUSE_PANIC));
    CHECK(reset_cause_is_crash(RESET_CAUSE_WATCHDOG));
    CHECK(!reset_cause_is_crash(RESET_CAUSE_POWER));
    CHECK(!reset_cause_is_crash(RESET_CAUSE_SOFTWARE));
    CHECK(!reset_cause_is_crash(RESET_CAUSE_BROWNOUT));
    CHECK(!reset_cause_is_crash(RESET_CAUSE_UNKNOWN));
}

void run_reset_reason_tests(void)
{
    test_names();
    test_names_are_distinct_and_plain();
    test_crashes();
}
