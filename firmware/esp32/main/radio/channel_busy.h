/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The receiver-state half of the listen-before-talk busy test (decision SL-25, step 1): given
 * the SX1262's IRQ status read while it is in receive, is a frame being received? Plain C,
 * shared by the SX1262 HAL and the host stub, and host-tested.
 *
 * The chip sets PreambleDetected (bit 2) when it finds a LoRa preamble and HeaderValid (bit 4)
 * when it has decoded a frame's header; RxDone (bit 1) ends the frame. The flags stay set until
 * the IRQ status is cleared, and a frame that never finishes (another network's sync word, a
 * header error) would leave them set for good, so a flag is believed for at most one frame
 * of the longest length (255 bytes) from when it was first seen; after that it is cleared.
 */
#ifndef ATALAIA_CHANNEL_BUSY_H
#define ATALAIA_CHANNEL_BUSY_H

#include <stdbool.h>
#include <stdint.h>

#include "hal/hal_radio.h"

#define CB_IRQ_RX_DONE      (1u << 1)
#define CB_IRQ_PREAMBLE     (1u << 2)
#define CB_IRQ_HEADER_VALID (1u << 4)
#define CB_IRQ_HEADER_ERR   (1u << 5)
/* The flags channel_busy() clears itself when a frame did not finish. */
#define CB_IRQ_FLAGS (CB_IRQ_PREAMBLE | CB_IRQ_HEADER_VALID | CB_IRQ_HEADER_ERR)

typedef struct {
    bool tracking;      /* a flag has been seen and is not yet resolved */
    uint32_t epoch;     /* the IRQ-clear count when it was first seen */
    int64_t first_seen; /* microseconds */
} cb_track_t;

/*
 * Reads the receiver's state from the IRQ status. epoch counts how many times the HAL cleared
 * the IRQ status (a clear drops the flags, so a flag seen after one is a new frame's);
 * max_frame_us is the longest a frame can take. *clear_flags is set when the caller must clear
 * the preamble and header flags (a frame that did not finish). Returns:
 *   HAL_BUSY_RX_DONE   a frame ended: not busy, and nothing may disturb the pending read;
 *   HAL_BUSY_HEADER    a valid header: a frame is on air;
 *   HAL_BUSY_PREAMBLE  a preamble: a frame is starting;
 *   HAL_BUSY_FREE      no flag, a header error or a flag older than max_frame_us.
 */
hal_busy_why_t cb_rx_state(cb_track_t *t, uint16_t irq, uint32_t epoch, int64_t now_us,
                           uint32_t max_frame_us, bool *clear_flags);

#endif /* ATALAIA_CHANNEL_BUSY_H */
