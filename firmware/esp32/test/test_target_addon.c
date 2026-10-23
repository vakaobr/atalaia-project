/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * Tests for target_addon (the target addon polled over I2C, decisions
 * P5J-18 and P5J-19), against a model of the addon that follows the draft
 * report format: it queues hits while armed and shows the oldest until the
 * box acknowledges it.
 */
#include <string.h>

#include "check.h"
#include "target_addon.h"

#define FAKE_QUEUE 8

typedef struct {
    bool armed;
    uint8_t seq[FAKE_QUEUE];
    uint8_t strength[FAKE_QUEUE];
    uint8_t age[FAKE_QUEUE];
    int count;
    uint8_t next_seq;
    bool overflow;
    int reads, writes;
    int fail_reads;    /* the next N reads fail (a cable pulled, a busy bus) */
    int corrupt_reads; /* the next N reads come back with a bad CRC */
    int drop_writes;   /* the next N writes are lost */
    int arm_cmds, disarm_cmds, acks;
} fake_addon_t;

static void fake_hit(fake_addon_t *a, uint8_t strength, uint8_t age)
{
    if (!a->armed) return;
    if (a->count == FAKE_QUEUE) {
        a->overflow = true;
        return;
    }
    a->seq[a->count] = a->next_seq++;
    a->strength[a->count] = strength;
    a->age[a->count] = age;
    a->count++;
}

static int fake_read(void *ctx, uint8_t *buf, size_t len)
{
    fake_addon_t *a = ctx;
    a->reads++;
    if (len != TA_REPORT_LEN) return -1;
    if (a->fail_reads > 0) {
        a->fail_reads--;
        return -1;
    }
    memset(buf, 0, len);
    buf[0] = (uint8_t)((a->armed ? TA_FLAG_ARMED : 0) | (a->count ? TA_FLAG_HIT : 0) |
                       (a->count > 1 ? TA_FLAG_MORE : 0) | (a->overflow ? TA_FLAG_OVERFLOW : 0));
    if (a->count) {
        buf[1] = a->seq[0];
        buf[2] = a->strength[0];
        buf[3] = a->age[0];
    }
    a->overflow = false;
    buf[4] = target_addon_crc8(buf, 4);
    if (a->corrupt_reads > 0) {
        a->corrupt_reads--;
        buf[2] ^= 0x10; /* a bit flipped on the cable */
    }
    return 0;
}

static int fake_write(void *ctx, const uint8_t *buf, size_t len)
{
    fake_addon_t *a = ctx;
    a->writes++;
    if (a->drop_writes > 0) {
        a->drop_writes--;
        return -1;
    }
    if (len == 1 && buf[0] == TA_CMD_ARM) {
        a->armed = true;
        a->arm_cmds++;
    } else if (len == 1 && buf[0] == TA_CMD_DISARM) {
        a->armed = false;
        a->count = 0;
        a->disarm_cmds++;
    } else if (len == 2 && buf[0] == TA_CMD_ACK) {
        a->acks++;
        if (a->count && a->seq[0] == buf[1]) {
            memmove(a->seq, a->seq + 1, (size_t)(a->count - 1));
            memmove(a->strength, a->strength + 1, (size_t)(a->count - 1));
            memmove(a->age, a->age + 1, (size_t)(a->count - 1));
            a->count--;
        }
    } else {
        return -1;
    }
    return 0;
}

static void setup(target_addon_t *ta, fake_addon_t *a)
{
    memset(a, 0, sizeof(*a));
    target_addon_bus_t bus = {fake_read, fake_write, a};
    target_addon_init(ta, &bus, TA_POLL_MS_DEFAULT);
}

static void test_crc8(void)
{
    /* CRC-8/SMBUS check value: "123456789" -> 0xF4. */
    const uint8_t s[] = "123456789";
    CHECK(target_addon_crc8(s, 9) == 0xF4);
    CHECK(target_addon_crc8(s, 0) == 0x00);
}

static void test_poll_period(void)
{
    target_addon_t ta;
    fake_addon_t a;
    target_addon_hit_t hits[4];
    setup(&ta, &a);
    /* The game task ticks every 10 ms: the addon is read on every second tick. */
    for (uint32_t t = 0; t < 1000; t += 10) target_addon_tick(&ta, t, hits, 4);
    CHECK(a.reads == 50);
    CHECK(target_addon_present(&ta));
}

static void test_arm_then_hit(void)
{
    target_addon_t ta;
    fake_addon_t a;
    target_addon_hit_t hits[4];
    setup(&ta, &a);
    target_addon_arm(&ta, true);
    CHECK(target_addon_tick(&ta, 0, hits, 4) == 0);
    CHECK(a.armed && a.arm_cmds == 1);
    fake_hit(&a, 120, 3);
    CHECK(target_addon_tick(&ta, 10, hits, 4) == 0); /* not yet: 20 ms between polls */
    CHECK(target_addon_tick(&ta, 20, hits, 4) == 1);
    CHECK(hits[0].strength == 120 && hits[0].age_ms == 30);
    CHECK(a.count == 0 && a.acks == 1);
    CHECK(target_addon_tick(&ta, 40, hits, 4) == 0); /* taken once */
    CHECK(a.arm_cmds == 1);                          /* armed: not sent again */
}

static void test_burst_in_one_poll(void)
{
    target_addon_t ta;
    fake_addon_t a;
    target_addon_hit_t hits[8];
    setup(&ta, &a);
    target_addon_arm(&ta, true);
    target_addon_tick(&ta, 0, hits, 8);
    for (int i = 0; i < 6; i++) fake_hit(&a, (uint8_t)(50 + i), 0);
    /* Up to four reports per poll; the rest on the next. */
    CHECK(target_addon_tick(&ta, 20, hits, 8) == TA_MAX_READS_PER_POLL);
    CHECK(hits[0].strength == 50 && hits[3].strength == 53);
    CHECK(target_addon_tick(&ta, 40, hits, 8) == 2);
    CHECK(hits[0].strength == 54 && hits[1].strength == 55);
    /* Not more than the caller has room for; the rest stays with the addon. */
    fake_hit(&a, 1, 0);
    fake_hit(&a, 2, 0);
    CHECK(target_addon_tick(&ta, 60, hits, 1) == 1 && hits[0].strength == 1);
    CHECK(a.count == 1);
    CHECK(target_addon_tick(&ta, 80, hits, 1) == 1 && hits[0].strength == 2);
}

static void test_lost_ack_is_not_a_second_hit(void)
{
    target_addon_t ta;
    fake_addon_t a;
    target_addon_hit_t hits[4];
    setup(&ta, &a);
    target_addon_arm(&ta, true);
    target_addon_tick(&ta, 0, hits, 4);
    fake_hit(&a, 99, 0);
    a.drop_writes = 1; /* the ACK is lost: the addon shows the same hit again */
    CHECK(target_addon_tick(&ta, 20, hits, 4) == 1);
    CHECK(a.count == 1);
    CHECK(target_addon_tick(&ta, 40, hits, 4) ==
          0); /* the same sequence: acknowledged, not reported */
    CHECK(a.count == 0);
    fake_hit(&a, 7, 0);
    CHECK(target_addon_tick(&ta, 60, hits, 4) == 1 && hits[0].strength == 7);
}

static void test_bad_reads(void)
{
    target_addon_t ta;
    fake_addon_t a;
    target_addon_hit_t hits[4];
    setup(&ta, &a);
    target_addon_arm(&ta, true);
    target_addon_tick(&ta, 0, hits, 4);
    fake_hit(&a, 200, 0);
    a.corrupt_reads = 1; /* refused for its CRC; read again on the next poll */
    CHECK(target_addon_tick(&ta, 20, hits, 4) == 0);
    CHECK(ta.bad_crc == 1 && a.count == 1);
    CHECK(target_addon_tick(&ta, 40, hits, 4) == 1 && hits[0].strength == 200);
    /* A few failed reads (a busy bus) do not lose the addon; 25 in a row do. */
    a.fail_reads = TA_LOST_AFTER - 1;
    uint32_t t = 60;
    for (int i = 0; i < TA_LOST_AFTER - 1; i++, t += 20) target_addon_tick(&ta, t, hits, 4);
    CHECK(target_addon_present(&ta));
    target_addon_tick(&ta, t, hits, 4);
    t += 20;
    CHECK(target_addon_present(&ta));
    a.fail_reads = TA_LOST_AFTER;
    for (int i = 0; i < TA_LOST_AFTER; i++, t += 20) target_addon_tick(&ta, t, hits, 4);
    CHECK(!target_addon_present(&ta));
    /* Plugged in again (a new addon counts from 0): its first hit is new. */
    a.next_seq = 0;
    a.armed = false;
    target_addon_tick(&ta, t, hits, 4); /* present again, armed again */
    t += 20;
    CHECK(target_addon_present(&ta) && a.armed);
    fake_hit(&a, 33, 0);
    CHECK(target_addon_tick(&ta, t, hits, 4) == 1 && hits[0].strength == 33);
}

static void test_disarmed(void)
{
    target_addon_t ta;
    fake_addon_t a;
    target_addon_hit_t hits[4];
    setup(&ta, &a);
    /* Never armed: an addon that still reports a hit is acknowledged, not heard. */
    a.armed = true;
    fake_hit(&a, 80, 0);
    CHECK(target_addon_tick(&ta, 0, hits, 4) == 0);
    CHECK(a.disarm_cmds == 1 && !a.armed);
    /* A lost ARM is sent again on the next poll. */
    target_addon_arm(&ta, true);
    a.drop_writes = 1;
    target_addon_tick(&ta, 20, hits, 4);
    CHECK(!a.armed);
    target_addon_tick(&ta, 40, hits, 4);
    CHECK(a.armed && a.arm_cmds == 1);
    /* Disarmed at the game's end: later hits are not reported. */
    target_addon_arm(&ta, false);
    target_addon_tick(&ta, 60, hits, 4);
    CHECK(!a.armed);
    fake_hit(&a, 90, 0); /* the model ignores hits while disarmed, as the addon must */
    CHECK(target_addon_tick(&ta, 80, hits, 4) == 0);
}

static void test_overflow_counted(void)
{
    target_addon_t ta;
    fake_addon_t a;
    target_addon_hit_t hits[TA_MAX_READS_PER_POLL];
    setup(&ta, &a);
    target_addon_arm(&ta, true);
    target_addon_tick(&ta, 0, hits, TA_MAX_READS_PER_POLL);
    for (int i = 0; i < FAKE_QUEUE + 2; i++) fake_hit(&a, 60, 0);
    int got = 0;
    for (uint32_t t = 20; t < 200; t += 20)
        got += target_addon_tick(&ta, t, hits, TA_MAX_READS_PER_POLL);
    CHECK(got == FAKE_QUEUE);
    CHECK(ta.dropped == 1);
}

void run_target_addon_tests(void)
{
    test_crc8();
    test_poll_period();
    test_arm_then_hit();
    test_burst_in_one_poll();
    test_lost_ack_is_not_a_second_hit();
    test_bad_reads();
    test_disarmed();
    test_overflow_counted();
}
