/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Time synchronization by slew. Pure C math, no platform dependencies.
 */
#include "time_sync.h"

void atalaia_time_sync_init(atalaia_time_sync_t *ts)
{
    ts->offset_ms = 0;
    ts->slew_remaining_ms = 0;
    ts->last_beacon_ms = 0;
    ts->avg_offset_ms = 0;
    ts->beacon_count = 0;
    ts->stepped = false;
}

void atalaia_time_sync_on_beacon(atalaia_time_sync_t *ts, uint32_t controller_game_time_ms,
                                 uint32_t airtime_ms, uint32_t tx_time_us, uint32_t local_time_ms)
{
    (void)tx_time_us; /* reserved for sub-ms precision */

    /* Estimate what the controller's clock reads now, accounting for
     * the over-the-air delay. */
    uint32_t controller_now = controller_game_time_ms + airtime_ms;

    /* Positive offset = local is behind (needs to speed up).
     * Negative offset = local is ahead (needs to slow down). */
    int32_t raw_offset = (int32_t)(controller_now - local_time_ms);

    /* EMA: alpha = 0.25 (fixed-point x1000). */
    if (ts->beacon_count == 0) {
        ts->avg_offset_ms = raw_offset * 1000;
    } else {
        ts->avg_offset_ms = ts->avg_offset_ms + (raw_offset * 1000 - ts->avg_offset_ms) / 4;
    }
    ts->beacon_count++;
    ts->last_beacon_ms = local_time_ms;

    /* Use the smoothed offset for the correction decision. */
    int32_t offset = ts->avg_offset_ms / 1000;
    ts->offset_ms = offset;

    int32_t abs_offset = offset >= 0 ? offset : -offset;
    if (abs_offset < TIME_SYNC_IGNORE_THRESHOLD_MS) {
        /* Close enough: no correction needed. */
        ts->slew_remaining_ms = 0;
        ts->stepped = false;
    } else if (abs_offset >= TIME_SYNC_STEP_THRESHOLD_MS) {
        /* Too far: step immediately. */
        ts->slew_remaining_ms = 0;
        ts->stepped = true;
    } else {
        /* Slew gradually. */
        ts->slew_remaining_ms = offset;
        ts->stepped = false;
    }
}

uint32_t atalaia_time_sync_adjust(atalaia_time_sync_t *ts, uint32_t raw_delta_ms)
{
    if (ts->slew_remaining_ms == 0) {
        return raw_delta_ms;
    }

    /* Calculate adjustment for this tick.
     * Max slew rate: 50 ms per second (5%).
     * Per-tick adjustment = raw_delta_ms * 0.05. */
    int32_t max_adj = (int32_t)(raw_delta_ms * TIME_SYNC_MAX_SLEW_RATE) / 1000;
    if (max_adj == 0) max_adj = 1;

    int32_t adj;
    if (ts->slew_remaining_ms > 0) {
        /* Local is behind: stretch the delta (speed up). */
        adj = max_adj;
        if (adj > ts->slew_remaining_ms) adj = ts->slew_remaining_ms;
        ts->slew_remaining_ms -= adj;
    } else {
        /* Local is ahead: compress the delta (slow down). */
        adj = -max_adj;
        if (adj < ts->slew_remaining_ms) adj = ts->slew_remaining_ms;
        ts->slew_remaining_ms -= adj;
        /* Ensure delta doesn't go negative. */
        if (adj < 0 && (int32_t)raw_delta_ms + adj < 0) {
            adj = -(int32_t)raw_delta_ms;
        }
    }

    return (uint32_t)((int32_t)raw_delta_ms + adj);
}
