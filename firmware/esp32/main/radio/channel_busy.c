/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#include "channel_busy.h"

#include <stddef.h>

hal_busy_why_t cb_rx_state(cb_track_t *t, uint16_t irq, uint32_t epoch, int64_t now_us,
                           uint32_t max_frame_us, bool *clear_flags)
{
    if (clear_flags != NULL) *clear_flags = false;
    if (irq & CB_IRQ_RX_DONE) {
        t->tracking = false;
        return HAL_BUSY_RX_DONE;
    }
    if (irq & CB_IRQ_HEADER_ERR) {
        /* The frame cannot be received; the flags are cleared so the next frame starts clean. */
        t->tracking = false;
        if (clear_flags != NULL) *clear_flags = true;
        return HAL_BUSY_FREE;
    }
    if (!(irq & (CB_IRQ_PREAMBLE | CB_IRQ_HEADER_VALID))) {
        t->tracking = false;
        return HAL_BUSY_FREE;
    }
    if (!t->tracking || t->epoch != epoch) {
        t->tracking = true;
        t->epoch = epoch;
        t->first_seen = now_us;
    }
    if (now_us - t->first_seen > (int64_t)max_frame_us) {
        t->tracking = false;
        if (clear_flags != NULL) *clear_flags = true;
        return HAL_BUSY_FREE;
    }
    return (irq & CB_IRQ_HEADER_VALID) ? HAL_BUSY_HEADER : HAL_BUSY_PREAMBLE;
}
