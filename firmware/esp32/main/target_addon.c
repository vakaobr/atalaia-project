/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The target addon, polled over I2C (target_addon.h; decisions P5J-15 to
 * P5J-21). A stub: nothing in the Field Box calls it yet.
 */
#include "target_addon.h"

#include <string.h>

uint8_t target_addon_crc8(const uint8_t *data, size_t len)
{
    uint8_t crc = 0;
    for (size_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (int b = 0; b < 8; b++) {
            crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0x07) : (uint8_t)(crc << 1);
        }
    }
    return crc;
}

void target_addon_init(target_addon_t *ta, const target_addon_bus_t *bus, uint32_t poll_ms)
{
    memset(ta, 0, sizeof(*ta));
    if (bus) ta->bus = *bus;
    ta->poll_ms = poll_ms ? poll_ms : TA_POLL_MS_DEFAULT;
}

void target_addon_arm(target_addon_t *ta, bool armed)
{
    ta->want_armed = armed;
}

bool target_addon_present(const target_addon_t *ta)
{
    return ta->present;
}

static int send(target_addon_t *ta, const uint8_t *buf, size_t len)
{
    return ta->bus.write ? ta->bus.write(ta->bus.ctx, buf, len) : -1;
}

/* One report read; false when it failed or did not check out. */
static bool read_report(target_addon_t *ta, uint8_t r[TA_REPORT_LEN])
{
    if (!ta->bus.read || ta->bus.read(ta->bus.ctx, r, TA_REPORT_LEN) != 0) return false;
    if (target_addon_crc8(r, TA_REPORT_LEN - 1) != r[TA_REPORT_LEN - 1]) {
        ta->bad_crc++;
        return false;
    }
    return (r[0] >> 4) == 0; /* the draft's version */
}

int target_addon_tick(target_addon_t *ta, uint32_t now_ms, target_addon_hit_t *out, int cap)
{
    if (ta->polled && now_ms - ta->last_poll_ms < ta->poll_ms) return 0;
    ta->polled = true;
    ta->last_poll_ms = now_ms;

    int n = 0;
    for (int i = 0; i < TA_MAX_READS_PER_POLL; i++) {
        uint8_t r[TA_REPORT_LEN];
        if (!read_report(ta, r)) {
            if (ta->failures < UINT16_MAX) ta->failures++;
            if (ta->failures >= TA_LOST_AFTER) {
                ta->present = false;
                ta->have_seq = false; /* an addon plugged in again counts afresh */
            }
            return n;
        }
        ta->failures = 0;
        ta->present = true;
        if (r[0] & TA_FLAG_OVERFLOW) ta->dropped++;

        bool armed = (r[0] & TA_FLAG_ARMED) != 0;
        if (armed != ta->want_armed) {
            uint8_t cmd = ta->want_armed ? TA_CMD_ARM : TA_CMD_DISARM;
            send(ta, &cmd, 1); /* read again on the next poll if it was lost */
        }

        if (!(r[0] & TA_FLAG_HIT)) return n;
        uint8_t seq = r[1];
        bool repeat = ta->have_seq && seq == ta->last_seq;
        if (!repeat && ta->want_armed && n < cap) {
            out[n].strength = r[2];
            out[n].age_ms = (uint16_t)(r[3] * 10u);
            n++;
        } else if (!repeat && ta->want_armed) {
            return n; /* no room: leave it with the addon for the next poll */
        }
        uint8_t ack[2] = {TA_CMD_ACK, seq};
        ta->last_seq = seq;
        ta->have_seq = true;
        if (send(ta, ack, sizeof(ack)) != 0) return n; /* shown again, then acknowledged */
        if (!(r[0] & TA_FLAG_MORE)) return n;
    }
    return n;
}
