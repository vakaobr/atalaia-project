/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * A refused or failed update (or mode fetch) shows its status screen for a few
 * seconds, then the screen of the box's state comes back (main/status_hold.c).
 */
#include <string.h>

#include "check.h"
#include "status_hold.h"

static void test_returns_to_the_state_screen(void)
{
    status_hold_t h;
    screen_update_t out;
    status_hold_init(&h);
    status_hold_state(&h, "picker", "{\"step\":1}");
    status_hold_transient(&h, 1000); /* "update refused: bad_offer" */
    CHECK(!status_hold_due(&h, 1000, false, &out));
    CHECK(!status_hold_due(&h, 1000 + STATUS_HOLD_MS - 1, false, &out));
    CHECK(status_hold_due(&h, 1000 + STATUS_HOLD_MS, false, &out));
    CHECK(strcmp(out.template_name, "picker") == 0 && strcmp(out.data_json, "{\"step\":1}") == 0);
    CHECK(!status_hold_due(&h, 1000 + 2 * STATUS_HOLD_MS, false, &out)); /* once */
}

static void test_the_last_state_screen_wins(void)
{
    status_hold_t h;
    screen_update_t out;
    status_hold_init(&h);
    status_hold_state(&h, "picker", "{}");
    status_hold_state(&h, "final_score", "{\"a\":1}"); /* the game ended meanwhile */
    status_hold_transient(&h, 0);
    CHECK(status_hold_due(&h, STATUS_HOLD_MS, false, &out));
    CHECK(strcmp(out.template_name, "final_score") == 0);
}

static void test_something_drew_meanwhile(void)
{
    status_hold_t h;
    screen_update_t out;
    status_hold_init(&h);
    status_hold_state(&h, "lobby", "{}");
    status_hold_transient(&h, 0);
    status_hold_state(&h, "game", "{\"s\":1}"); /* a game screen replaced the status */
    CHECK(!status_hold_due(&h, STATUS_HOLD_MS * 3, false, &out));
}

static void test_busy_and_progress_renew(void)
{
    status_hold_t h;
    screen_update_t out;
    status_hold_init(&h);
    status_hold_state(&h, "lobby", "{}");
    status_hold_transient(&h, 0); /* "updating 10%" */
    CHECK(!status_hold_due(&h, STATUS_HOLD_MS * 2, true, &out)); /* the download runs on */
    status_hold_transient(&h, STATUS_HOLD_MS * 2);               /* it failed */
    CHECK(!status_hold_due(&h, STATUS_HOLD_MS * 2 + 100, false, &out));
    CHECK(status_hold_due(&h, STATUS_HOLD_MS * 3, false, &out));
    CHECK(strcmp(out.template_name, "lobby") == 0);
}

static void test_no_state_screen_and_wrap(void)
{
    status_hold_t h;
    screen_update_t out;
    status_hold_init(&h);
    status_hold_transient(&h, 5);
    CHECK(!status_hold_due(&h, 5 + STATUS_HOLD_MS, false, &out)); /* nothing to go back to */
    status_hold_state(&h, "lobby", "{}");
    status_hold_transient(&h, 0xFFFFFFF0u); /* the millisecond clock wraps */
    CHECK(!status_hold_due(&h, 100, false, &out));
    CHECK(status_hold_due(&h, 0xFFFFFFF0u + STATUS_HOLD_MS, false, &out));
}

void run_status_hold_tests(void)
{
    test_returns_to_the_state_screen();
    test_the_last_state_screen_wins();
    test_something_drew_meanwhile();
    test_busy_and_progress_renew();
    test_no_state_screen_and_wrap();
}
