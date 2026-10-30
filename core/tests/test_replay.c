/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Tests for the per-source replay window (core/src/replay.c): the shared vectors
 * (protocol/vectors/replay_window.json), and the properties they cannot say.
 */
#include <stdio.h>

#include "atalaia/replay.h"
#include "check.h"
#include "replay_vectors.h"

static void test_vectors(void)
{
    for (size_t i = 0; i < REPLAY_CASE_COUNT; i++) {
        atalaia_replay_t w;
        atalaia_replay_init(&w);
        for (size_t j = 0; j < replay_cases[i].count; j++) {
            const replay_step_t *s = &replay_cases[i].steps[j];
            if (atalaia_replay_accept(&w, atalaia_replay_ctr(s->epoch, s->seq)) != s->verdict) {
                printf("replay vector %s step %zu: wrong verdict\n", replay_cases[i].name, j);
                CHECK(0);
            }
        }
    }
}

/* check() changes nothing: a packet that fails authentication later must not move the window. */
static void test_check_is_read_only(void)
{
    atalaia_replay_t w;
    atalaia_replay_init(&w);
    CHECK(atalaia_replay_accept(&w, 100) == ATALAIA_REPLAY_FRESH);
    CHECK(atalaia_replay_check(&w, 5000) == ATALAIA_REPLAY_FRESH);
    CHECK(atalaia_replay_check(&w, 5000) == ATALAIA_REPLAY_FRESH);
    CHECK(w.high == 100);
    CHECK(atalaia_replay_check(&w, 100) == ATALAIA_REPLAY_DUPLICATE);
}

/* Each counter of a long run is fresh once and a duplicate after, and anything 64 back is old. */
static void test_long_run(void)
{
    atalaia_replay_t w;
    atalaia_replay_init(&w);
    for (uint32_t c = 3; c < 5000; c += 3) {
        CHECK(atalaia_replay_accept(&w, c) == ATALAIA_REPLAY_FRESH);
        CHECK(atalaia_replay_accept(&w, c) == ATALAIA_REPLAY_DUPLICATE);
        if (c > 70) CHECK(atalaia_replay_accept(&w, c - 66) == ATALAIA_REPLAY_TOO_OLD);
    }
}

void run_replay_tests(void)
{
    test_vectors();
    test_check_is_read_only();
    test_long_run();
}
