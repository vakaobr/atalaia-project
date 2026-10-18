/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * Time synchronization by slew: adjusts local game time toward the
 * controller's clock using TIME beacon messages. Pure C math with
 * no platform dependencies.
 *
 * Step if |offset| >= 500 ms, slew if < 500 ms, ignore if < 5 ms.
 * Max slew rate 5%/s (50 ms/s). EMA of last 4 offsets (alpha 0.25).
 */
#ifndef ATALAIA_TIME_SYNC_H
#define ATALAIA_TIME_SYNC_H

#include <stdbool.h>
#include <stdint.h>

/* Thresholds. */
#define TIME_SYNC_STEP_THRESHOLD_MS   500
#define TIME_SYNC_IGNORE_THRESHOLD_MS 5
#define TIME_SYNC_MAX_SLEW_RATE       50 /* ms/s = 5% */

typedef struct {
    int32_t offset_ms;         /* current correction (positive = local behind) */
    int32_t slew_remaining_ms; /* remaining slew to apply */
    uint32_t last_beacon_ms;   /* local time of last beacon */
    int32_t avg_offset_ms;     /* EMA of offsets (x1000 for fixed-point) */
    uint32_t beacon_count;     /* number of beacons received */
    bool stepped;              /* true if the last update was a step */
} atalaia_time_sync_t;

void atalaia_time_sync_init(atalaia_time_sync_t *ts);

/*
 * Process a TIME beacon. controller_game_time_ms is the controller's
 * game clock at the time the beacon was sent; airtime_ms is the
 * estimated over-the-air delay; tx_time_us is unused (reserved for
 * sub-ms precision); local_time_ms is the local game time when the
 * beacon was received.
 */
void atalaia_time_sync_on_beacon(atalaia_time_sync_t *ts, uint32_t controller_game_time_ms,
                                 uint32_t airtime_ms, uint32_t tx_time_us, uint32_t local_time_ms);

/*
 * Adjust a time delta during active slew. Returns the adjusted delta
 * that should be passed to atalaia_node_advance(). During positive slew
 * (local behind) the delta is stretched; during negative slew (local
 * ahead) it is compressed.
 */
uint32_t atalaia_time_sync_adjust(atalaia_time_sync_t *ts, uint32_t raw_delta_ms);

#endif /* ATALAIA_TIME_SYNC_H */
