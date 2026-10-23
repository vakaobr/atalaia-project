/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The target addon on the box's I2C bus, polled: no interrupt line
 * (decisions P5J-15 to P5J-21, hardware/target-addon/BUILD.md). A STUB: the
 * addon's I2C address, its "identify" request and its processor are not
 * decided, and nothing in the Field Box calls this yet; it fixes the polling
 * logic and a DRAFT report format so the addon's firmware and the box's can
 * be written against the same thing, and is tested on the host against a
 * model of the addon (test/test_target_addon.c).
 *
 * Draft wire format (P5J-19), all at 3.3 V, 100 kHz:
 *   The box reads TA_REPORT_LEN bytes:
 *     [0] flags: TA_FLAG_ARMED, TA_FLAG_HIT (bytes 1-3 hold a hit),
 *         TA_FLAG_MORE (more hits wait behind it), TA_FLAG_OVERFLOW (the
 *         addon dropped hits since its last report); bits 4-7: the draft's
 *         version, 0
 *     [1] the hit's sequence number (the addon counts its hits, wrapping)
 *     [2] the hit's strength, 0-255 (the `hit` capability's `strength`)
 *     [3] the hit's age in 10 ms units, saturating at 255 (how long ago the
 *         addon felt it)
 *     [4] CRC-8 (polynomial 0x07, initial 0x00) of bytes 0-3
 *   The box writes:
 *     TA_CMD_ACK, seq    the box has taken that hit; the addon shows the next
 *     TA_CMD_ARM         report hits from now on
 *     TA_CMD_DISARM      stop reporting hits (and drop any it holds)
 *   The addon keeps showing the same hit until it is acknowledged, so a
 *   report lost on the cable is read again, and a lost ACK only makes the box
 *   see the same sequence number again (it acknowledges it once more and
 *   reports nothing).
 */
#ifndef ATALAIA_TARGET_ADDON_H
#define ATALAIA_TARGET_ADDON_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define TA_REPORT_LEN 5

#define TA_FLAG_ARMED    0x01
#define TA_FLAG_HIT      0x02
#define TA_FLAG_MORE     0x04
#define TA_FLAG_OVERFLOW 0x08

#define TA_CMD_ACK    0x01
#define TA_CMD_ARM    0x02
#define TA_CMD_DISARM 0x03

/* Read the addon every 20 ms: two of the game task's 10 ms ticks (P5J-18). */
#define TA_POLL_MS_DEFAULT 20
/* Reports read in one poll while the addon says more hits wait. */
#define TA_MAX_READS_PER_POLL 4
/* Failed reads in a row before the addon counts as gone (0.5 s at 20 ms). */
#define TA_LOST_AFTER 25

/* The bus, as the box gives it: 0 on success. On the box these would be the
 * I2C reads and writes at the addon's address (not decided yet). */
typedef struct {
    int (*read)(void *ctx, uint8_t *buf, size_t len);
    int (*write)(void *ctx, const uint8_t *buf, size_t len);
    void *ctx;
} target_addon_bus_t;

typedef struct {
    uint8_t strength;
    uint16_t age_ms; /* how long before the read the addon felt it */
} target_addon_hit_t;

typedef struct {
    target_addon_bus_t bus;
    uint32_t poll_ms;
    uint32_t last_poll_ms;
    bool polled;     /* polled at least once */
    bool want_armed; /* what the game asked (cap("hit"):arm() / :disarm()) */
    bool present;    /* the last reads answered with a good report */
    bool have_seq;   /* last_seq holds the last hit taken */
    uint8_t last_seq;
    uint16_t failures; /* failed reads in a row */
    uint32_t dropped;  /* reports saying the addon dropped hits (overflow) */
    uint32_t bad_crc;  /* reports refused for their CRC */
} target_addon_t;

/* CRC-8, polynomial 0x07, initial value 0 (the draft's report check). */
uint8_t target_addon_crc8(const uint8_t *data, size_t len);

void target_addon_init(target_addon_t *ta, const target_addon_bus_t *bus, uint32_t poll_ms);

/* The game's arm / disarm: sent on the next poll, and again while the
 * addon's report disagrees. */
void target_addon_arm(target_addon_t *ta, bool armed);

/*
 * Call every game tick. Polls when poll_ms has passed since the last poll,
 * and puts up to `cap` new hits in `out` (each to go to the script as
 * hit.hit with its strength). Returns how many.
 * Hits felt while the game has the addon disarmed are acknowledged and
 * dropped.
 */
int target_addon_tick(target_addon_t *ta, uint32_t now_ms, target_addon_hit_t *out, int cap);

/* True while the addon answers (false before the first good report, and
 * after TA_LOST_AFTER failed reads in a row). */
bool target_addon_present(const target_addon_t *ta);

#endif /* ATALAIA_TARGET_ADDON_H */
