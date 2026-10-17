/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Minimal test runner for the core skeleton. Replace with a proper
 * framework once the core grows.
 */
#include "atalaia/event.h"
#include "atalaia/version.h"

#include <stdio.h>
#include <string.h>

static int failures = 0;

#define CHECK(cond)                                                     \
    do {                                                                \
        if (!(cond)) {                                                  \
            fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); \
            failures++;                                                 \
        }                                                               \
    } while (0)

static void test_version(void)
{
    CHECK(strcmp(atalaia_version(), "0.0.1") == 0);
    CHECK(ATALAIA_PROTOCOL_VERSION == 1);
}

static void test_event_init(void)
{
    atalaia_event_t ev;
    CHECK(atalaia_event_init(&ev, 7, 42, 1500, "zone.captured", 2, 1,
                             ATALAIA_PRIO_NORMAL));
    CHECK(ev.node == 7 && ev.seq == 42 && ev.t_ms == 1500);
    CHECK(ev.team == 2 && ev.squad == 1);
    CHECK(strcmp(ev.type, "zone.captured") == 0);

    CHECK(!atalaia_event_init(&ev, 1, 1, 0, "", 1, 0, ATALAIA_PRIO_NORMAL));
    CHECK(!atalaia_event_init(&ev, 1, 1, 0, NULL, 1, 0, ATALAIA_PRIO_NORMAL));
    CHECK(!atalaia_event_init(&ev, 1, 1, 0, "x", 251, 0, ATALAIA_PRIO_NORMAL));

    char long_type[ATALAIA_EVENT_TYPE_MAX + 1];
    memset(long_type, 'a', sizeof(long_type) - 1);
    long_type[sizeof(long_type) - 1] = '\0';
    CHECK(!atalaia_event_init(&ev, 1, 1, 0, long_type, 1, 0,
                              ATALAIA_PRIO_NORMAL));
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

int main(void)
{
    test_version();
    test_event_init();
    test_event_order();
    test_prio_names();

    if (failures == 0) {
        printf("core: all tests passed\n");
        return 0;
    }
    fprintf(stderr, "core: %d check(s) failed\n", failures);
    return 1;
}
