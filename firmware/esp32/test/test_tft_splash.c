/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The TFT's boot splash: how long it stays and which screen replaces it (main/tft_splash.c).
 */
#include <string.h>

#include "check.h"
#include "tft_splash.h"

static void test_early_screen_waits_for_the_time(void)
{
    tft_splash_t s;
    screen_update_t out;
    tft_splash_begin(&s, 1000, 2500);
    CHECK(tft_splash_active(&s));
    CHECK(tft_splash_offer(&s, "status", "{\"a\":1}", 1200)); /* held */
    CHECK(!tft_splash_due(&s, 3499, &out));
    CHECK(tft_splash_due(&s, 3500, &out));
    CHECK(strcmp(out.template_name, "status") == 0 && strcmp(out.data_json, "{\"a\":1}") == 0);
    CHECK(!tft_splash_active(&s));
    CHECK(!tft_splash_due(&s, 9000, &out)); /* once */
}

static void test_latest_screen_wins(void)
{
    tft_splash_t s;
    screen_update_t out;
    tft_splash_begin(&s, 0, 2500);
    CHECK(tft_splash_offer(&s, "ready", "{}", 100));
    CHECK(tft_splash_offer(&s, "standby", "{}", 200));
    CHECK(tft_splash_due(&s, 2500, &out));
    CHECK(strcmp(out.template_name, "standby") == 0);
}

static void test_late_screen_replaces_at_once(void)
{
    tft_splash_t s;
    screen_update_t out;
    tft_splash_begin(&s, 0, 2500);
    CHECK(!tft_splash_due(&s, 2600, &out)); /* time over, nothing to show: it stays */
    CHECK(tft_splash_active(&s));
    CHECK(!tft_splash_offer(&s, "ready", "{}", 4000)); /* draw it now */
    CHECK(!tft_splash_active(&s));
}

static void test_zero_hold_and_wrap(void)
{
    tft_splash_t s;
    screen_update_t out;
    tft_splash_begin(&s, 50, 0);
    CHECK(!tft_splash_active(&s));
    CHECK(!tft_splash_offer(&s, "ready", "{}", 50));
    tft_splash_begin(&s, 0xFFFFFF00u, 2500); /* the clock wraps during the splash */
    CHECK(tft_splash_offer(&s, "ready", "{}", 0xFFFFFF10u));
    CHECK(!tft_splash_due(&s, 100, &out));
    CHECK(tft_splash_due(&s, 0xFFFFFF00u + 2500u, &out));
}

void run_tft_splash_tests(void)
{
    test_early_screen_waits_for_the_time();
    test_latest_screen_wins();
    test_late_screen_replaces_at_once();
    test_zero_hold_and_wrap();
}
