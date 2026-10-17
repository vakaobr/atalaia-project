/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * Tests for key_filter: one press per key stroke, bounces ignored.
 */
#include "check.h"
#include "hal/hal_keypad.h"
#include "key_filter.h"

static int presses(key_filter_t *f, const char *scans, char *last)
{
    int n = 0;
    for (const char *s = scans; *s; s++) {
        char raw = *s == '.' ? HAL_KEY_NONE : *s;
        char k = key_filter_update(f, raw);
        if (k != HAL_KEY_NONE) {
            n++;
            *last = k;
        }
    }
    return n;
}

static void test_held_key_is_one_press(void)
{
    key_filter_t f;
    key_filter_init(&f);
    char last = 0;
    CHECK(presses(&f, "..5555555555555...", &last) == 1);
    CHECK(last == '5');
}

static void test_bounce_is_ignored(void)
{
    key_filter_t f;
    key_filter_init(&f);
    char last = 0;
    /* Contact bounce shorter than the stable window, then a clean press. */
    CHECK(presses(&f, "1.1.1.111111..", &last) == 1);
    CHECK(last == '1');
    /* Glitches of one or two scans never register. */
    CHECK(presses(&f, "....2..3.....", &last) == 0);
}

static void test_repeated_strokes(void)
{
    key_filter_t f;
    key_filter_init(&f);
    char last = 0;
    CHECK(presses(&f, "1111....1111....####...", &last) == 3);
    CHECK(last == '#');
}

static void test_direct_key_change(void)
{
    key_filter_t f;
    key_filter_init(&f);
    char last = 0;
    /* Rolling from one key to another without a gap gives both. */
    CHECK(presses(&f, "44444666666", &last) == 2);
    CHECK(last == '6');
}

void run_key_filter_tests(void)
{
    test_held_key_is_one_press();
    test_bounce_is_ignored();
    test_repeated_strokes();
    test_direct_key_change();
}
