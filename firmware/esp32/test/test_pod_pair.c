/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * The I/O pod's Bluetooth pairing state machine (main/pod/pod_pair.h, decisions PODPK-1 to
 * PODPK-11) without a stack: the passkey on the OLED and its countdown, paired, a wrong passkey,
 * the Security Manager's timeout, a phone that holds the link without pairing, a bond without
 * MITM protection or unknown to the pod (dropped with Authentication Failure, once), a phone
 * coming back with its bond, and clearing the bonds with the PRG button.
 */
#include <string.h>

#include "check.h"
#include "pod/pod_pair.h"

static pod_pair_t p;

static oled_pair_view_t view(uint32_t now)
{
    oled_pair_view_t v;
    pod_pair_view(&p, now, &v);
    return v;
}

static void setup(void)
{
    pod_pair_init(&p, true);
    pod_pair_set_name(&p, "atalaia-pod-1A2B");
}

/* A random source that gives the words of a list, then 0. */
static const uint32_t *words;
static int words_left, words_used;
static uint32_t next_word(void *ctx)
{
    (void)ctx;
    words_used++;
    if (words_left == 0) return 0;
    words_left--;
    return *words++;
}

static void test_passkey(void)
{
    static const uint32_t a[] = {123456u};
    words = a;
    words_left = 1;
    words_used = 0;
    CHECK(pod_pair_passkey(next_word, NULL) == 123456u);
    /* 4294967295 % 1000000 would make 0-967295 likelier: words from 4294000000 are drawn again. */
    static const uint32_t b[] = {4294967295u, 4294000000u, 4293999999u};
    words = b;
    words_left = 3;
    words_used = 0;
    CHECK(pod_pair_passkey(next_word, NULL) == 999999u && words_used == 3);
    static const uint32_t c[] = {1000000u * 7u + 42u};
    words = c;
    words_left = 1;
    CHECK(pod_pair_passkey(next_word, NULL) == 42u); /* shown "000 042" */
}

static void test_pairing_with_the_passkey(void)
{
    setup();
    oled_pair_view_t v = view(0);
    CHECK(v.show == OLED_PAIR_NONE); /* dark until a phone pairs */
    pod_pair_on_connect(&p, 1000);
    CHECK(view(1000).show == OLED_PAIR_NONE);
    pod_pair_on_passkey(&p, 42, 1500);
    v = view(1500);
    CHECK(v.show == OLED_PAIR_PASSKEY && v.passkey == 42 && v.secs_left == 30);
    CHECK(strcmp(v.name, "atalaia-pod-1A2B") == 0);
    CHECK(view(1500 + 10500).secs_left == 20); /* rounded up */
    CHECK(view(1500 + 40000).secs_left == 0);
    CHECK(pod_pair_tick(&p, 12000, false) == POD_PAIR_ACT_NONE);
    CHECK(view(12000).show == OLED_PAIR_PASSKEY); /* stays until the pairing ends */
    /* Typed right: a passkey's key, MITM-protected. */
    CHECK(pod_pair_on_encryption(&p, POD_PAIR_RESULT_OK, true, true, 15000) == POD_PAIR_ACT_NONE);
    CHECK(p.secure && p.count.pairings == 1 && view(15000).show == OLED_PAIR_PAIRED);
    /* Shown a while, then dark; a secure link is never dropped for time. */
    CHECK(pod_pair_tick(&p, 15000 + POD_PAIR_RESULT_MS - 1, false) == POD_PAIR_ACT_NONE);
    CHECK(view(19999).show == OLED_PAIR_PAIRED);
    CHECK(pod_pair_tick(&p, 15000 + POD_PAIR_RESULT_MS, false) == POD_PAIR_ACT_NONE);
    CHECK(view(20000).show == OLED_PAIR_NONE);
    CHECK(pod_pair_tick(&p, 1000 + POD_PAIR_TIMEOUT_MS * 3, false) == POD_PAIR_ACT_NONE);
    pod_pair_on_disconnect(&p, 300000);
    CHECK(!p.connected && !p.secure && view(300000).show == OLED_PAIR_NONE);
    CHECK(p.count.failures == 0);

    /* The phone comes back with its bond: encrypted at once, nothing on the OLED. */
    pod_pair_on_connect(&p, 400000);
    CHECK(pod_pair_on_encryption(&p, POD_PAIR_RESULT_OK, true, true, 400050) == POD_PAIR_ACT_NONE);
    CHECK(p.secure && view(400050).show == OLED_PAIR_NONE && p.count.pairings == 1);
}

static void test_wrong_passkey_and_timeouts(void)
{
    setup();
    pod_pair_on_connect(&p, 0);
    pod_pair_on_passkey(&p, 111111, 100);
    /* A wrong passkey (or the phone's Cancel): failed, shown, the link dropped at once. */
    CHECK(pod_pair_on_encryption(&p, POD_PAIR_RESULT_FAILED, false, false, 8000) ==
          POD_PAIR_ACT_DROP);
    CHECK(!p.secure && p.dropping && p.count.failures == 1 && view(8000).show == OLED_PAIR_FAILED);
    /* No time drop on top, and the drop's own disconnection counts no second failure. */
    CHECK(pod_pair_tick(&p, POD_PAIR_TIMEOUT_MS + 1, false) == POD_PAIR_ACT_NONE);
    pod_pair_on_disconnect(&p, POD_PAIR_TIMEOUT_MS + 2);
    CHECK(p.count.failures == 1);
    /* Linking again: a new passkey. The Security Manager's 30 s run out: too slow, dropped. */
    pod_pair_on_connect(&p, 0);
    pod_pair_on_passkey(&p, 222222, 9000);
    CHECK(view(9000).show == OLED_PAIR_PASSKEY && view(9000).passkey == 222222);
    CHECK(pod_pair_on_encryption(&p, POD_PAIR_RESULT_TIMEOUT, false, false, 39000) ==
          POD_PAIR_ACT_DROP);
    CHECK(p.count.timeouts == 1 && view(39000).show == OLED_PAIR_TIMEOUT);
    pod_pair_on_disconnect(&p, 39010);
    /* A phone that never pairs: let go after POD_PAIR_TIMEOUT_MS, once. */
    pod_pair_on_connect(&p, 0);
    CHECK(pod_pair_tick(&p, POD_PAIR_TIMEOUT_MS - 1, false) == POD_PAIR_ACT_NONE);
    CHECK(pod_pair_tick(&p, POD_PAIR_TIMEOUT_MS, false) == POD_PAIR_ACT_DROP);
    CHECK(p.count.timeouts == 2 && view(POD_PAIR_TIMEOUT_MS).show == OLED_PAIR_TIMEOUT);
    CHECK(pod_pair_tick(&p, POD_PAIR_TIMEOUT_MS + 10, false) == POD_PAIR_ACT_NONE);
    /* Nothing more for a link being dropped. */
    CHECK(pod_pair_on_encryption(&p, POD_PAIR_RESULT_OK, true, true, POD_PAIR_TIMEOUT_MS + 20) ==
          POD_PAIR_ACT_NONE);
    CHECK(!p.secure);
    pod_pair_on_disconnect(&p, POD_PAIR_TIMEOUT_MS + 30);
    CHECK(!p.dropping);

    /* The phone goes while the passkey shows: failed. */
    pod_pair_on_connect(&p, 100000);
    pod_pair_on_passkey(&p, 333333, 100100);
    pod_pair_on_disconnect(&p, 110000);
    CHECK(p.count.failures == 2 && view(110000).show == OLED_PAIR_FAILED);
    CHECK(pod_pair_tick(&p, 110000 + POD_PAIR_RESULT_MS, false) == POD_PAIR_ACT_NONE);
    CHECK(view(115000).show == OLED_PAIR_NONE);
    /* Not connected: no drop for time. */
    CHECK(pod_pair_tick(&p, 100000 + POD_PAIR_TIMEOUT_MS * 2, false) == POD_PAIR_ACT_NONE);
}

static void test_stale_bonds(void)
{
    /* A Just Works bond from a pod firmware before PODPK: encrypted, not MITM-protected. The pod
     * forgets it and drops the link with Authentication Failure: the app pairs again. */
    setup();
    pod_pair_on_connect(&p, 0);
    CHECK(pod_pair_on_encryption(&p, POD_PAIR_RESULT_OK, true, false, 80) ==
          POD_PAIR_ACT_DROP_STALE);
    CHECK(!p.secure && p.dropping && p.count.stale_bonds == 1);
    CHECK(view(80).show == OLED_PAIR_AGAIN);
    /* One action only: no time drop on top. */
    CHECK(pod_pair_tick(&p, POD_PAIR_TIMEOUT_MS + 1, false) == POD_PAIR_ACT_NONE);
    pod_pair_on_disconnect(&p, POD_PAIR_TIMEOUT_MS + 2);

    /* The phone comes back with that bond, which the pod no longer has: the same answer. */
    pod_pair_on_connect(&p, 100000);
    CHECK(pod_pair_on_encryption(&p, POD_PAIR_RESULT_NO_KEY, false, false, 100050) ==
          POD_PAIR_ACT_DROP_STALE);
    CHECK(p.count.stale_bonds == 2 && view(100050).show == OLED_PAIR_AGAIN);
    pod_pair_on_disconnect(&p, 100100);
    /* The app forgot its bond: a fresh pairing with the passkey, once and for all. */
    pod_pair_on_connect(&p, 110000);
    pod_pair_on_passkey(&p, 654321, 110100);
    CHECK(pod_pair_on_encryption(&p, POD_PAIR_RESULT_OK, true, true, 118000) == POD_PAIR_ACT_NONE);
    CHECK(p.secure && p.count.pairings == 1 && p.count.stale_bonds == 2);

    /* A Just Works build (no passkey): such a link is enough. */
    pod_pair_init(&p, false);
    pod_pair_on_connect(&p, 0);
    CHECK(pod_pair_on_encryption(&p, POD_PAIR_RESULT_OK, true, false, 50) == POD_PAIR_ACT_NONE);
    CHECK(p.secure && p.count.stale_bonds == 0);
    /* Events of no link are ignored. */
    pod_pair_init(&p, true);
    CHECK(pod_pair_on_encryption(&p, POD_PAIR_RESULT_OK, true, false, 50) == POD_PAIR_ACT_NONE);
}

static void test_clearing_bonds(void)
{
    setup();
    /* A short press shows nothing and clears nothing. */
    CHECK(pod_pair_tick(&p, 1000, true) == POD_PAIR_ACT_NONE);
    CHECK(pod_pair_tick(&p, 1000 + POD_PAIR_CLEAR_SHOW_MS - 1, true) == POD_PAIR_ACT_NONE);
    CHECK(view(1999).show == OLED_PAIR_NONE);
    CHECK(pod_pair_tick(&p, 2100, false) == POD_PAIR_ACT_NONE);
    CHECK(view(2100).show == OLED_PAIR_NONE && p.count.clears == 0);
    /* Let go after the hold showed: back to dark, nothing cleared. */
    pod_pair_tick(&p, 10000, true);
    pod_pair_tick(&p, 12500, true);
    oled_pair_view_t v = view(12500);
    CHECK(v.show == OLED_PAIR_CLEARING && v.progress == 50);
    pod_pair_tick(&p, 13000, false);
    CHECK(view(13000).show == OLED_PAIR_NONE && p.count.clears == 0);
    /* Held 5 s with a phone connected: every bond goes, the phone is dropped, once a press. */
    pod_pair_on_connect(&p, 20000);
    pod_pair_on_encryption(&p, POD_PAIR_RESULT_OK, true, true, 20050);
    CHECK(pod_pair_tick(&p, 30000, true) == POD_PAIR_ACT_NONE);
    CHECK(pod_pair_tick(&p, 30000 + POD_PAIR_CLEAR_HOLD_MS - 1, true) == POD_PAIR_ACT_NONE);
    CHECK(view(34999).progress == 99);
    CHECK(pod_pair_tick(&p, 30000 + POD_PAIR_CLEAR_HOLD_MS, true) == POD_PAIR_ACT_CLEAR_BONDS);
    CHECK(p.count.clears == 1 && !p.secure && p.dropping);
    CHECK(view(35000).show == OLED_PAIR_CLEARED);
    CHECK(pod_pair_tick(&p, 38000, true) == POD_PAIR_ACT_NONE); /* still held: not again */
    CHECK(view(38000).show == OLED_PAIR_CLEARED);
    pod_pair_tick(&p, 38500, false);
    CHECK(view(38500).show == OLED_PAIR_CLEARED); /* the outcome stays its time */
    pod_pair_tick(&p, 35000 + POD_PAIR_RESULT_MS, false);
    CHECK(view(40000).show == OLED_PAIR_NONE && p.count.clears == 1);
}

void run_pod_pair_tests(void)
{
    test_passkey();
    test_pairing_with_the_passkey();
    test_wrong_passkey_and_timeouts();
    test_stale_bonds();
    test_clearing_bonds();
}
