/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * Radio HAL: SX1262 LoRa (or stub for testing).
 * ADR-P2-4 defines the ops interface.
 */
#ifndef HAL_RADIO_H
#define HAL_RADIO_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "radio/noise_stats.h"

typedef enum {
    HAL_RADIO_MODE_SLEEP = 0,
    HAL_RADIO_MODE_STANDBY,
    HAL_RADIO_MODE_RX,
    HAL_RADIO_MODE_TX,
} hal_radio_mode_t;

/*
 * Why channel_busy() answered as it did (SL-25 step 1, docs/review/decisions-to-review.md).
 * A CAD alone sees only a frame's preamble (about 12.5 ms of a 92 ms frame at SF7/125 kHz); the
 * receiver's own state covers the rest: the SX1262 flags "preamble detected" and "header valid"
 * while it receives a frame.
 */
typedef enum {
    HAL_BUSY_FREE = 0,     /* nothing heard: no flag, and the CAD saw no activity */
    HAL_BUSY_CAD = 1,      /* the CAD detected a LoRa preamble */
    HAL_BUSY_PREAMBLE = 2, /* the receiver is on a preamble it detected (no CAD was run) */
    HAL_BUSY_HEADER = 3,   /* the receiver decoded a valid header: a frame is on air (no CAD) */
    HAL_BUSY_RX_DONE = 4,  /* a frame has just ended and waits to be read: not busy (no CAD) */
    HAL_BUSY_ERROR = 5,    /* the radio did not answer */
} hal_busy_why_t;

/* What one channel_busy() call measured (the bench test, docs/runbooks/lbt-bench-gate.md). */
typedef struct {
    hal_busy_why_t why;
    int64_t sample_us; /* esp_timer time at which the channel was looked at (the CAD's middle) */
    uint32_t cad_us;   /* the whole CAD, standby to its result; 0 when none was run */
    uint32_t rearm_us; /* putting the radio back in receive; 0 when none was needed */
} hal_radio_busy_t;

typedef struct {
    /*
     * Initialise the radio hardware (SPI, GPIOs, probe the chip).
     * Returns 0 on success, -1 if the radio is not present or does not
     * answer (BUSY stuck high, no SPI reply, configuration failed); the
     * hardware is released again in that case.
     */
    int (*init)(void);

    /*
     * Send a packet. Returns 0 on success, -1 on a radio error (BUSY
     * timeout, SPI failure), -2 if TX_DONE never came (TX timeout), -3 if
     * the packet's time on air does not fit in the duty-cycle budget left
     * on the current channel's sub-band (nothing is sent).
     */
    int (*send)(const uint8_t *data, size_t len);

    /*
     * Non-blocking receive. Copies at most max_len bytes into buf and
     * writes the RSSI to *rssi. Returns the number of bytes received,
     * or 0 if nothing is available.
     */
    size_t (*recv)(uint8_t *buf, size_t max_len, int8_t *rssi);

    /*
     * Set the channel frequency in Hz (e.g. 869525000). The 125 kHz channel
     * must fit inside one EU868 sub-band; the TX power and the duty-cycle
     * budget then follow that sub-band. Returns 0, or -1 if refused.
     */
    int (*set_channel)(uint32_t freq_hz);

    /* Set the radio operating mode. */
    int (*set_mode)(hal_radio_mode_t mode);

    /* Read the current RSSI (dBm); INT8_MIN if the chip did not answer. */
    int8_t (*rssi)(void);

    /* Remaining duty-cycle budget in milliseconds for the current sub-band. */
    uint32_t (*duty_cycle_remaining_ms)(void);

    /*
     * Measure the noise on freq_hz for dwell_ms without transmitting:
     * instantaneous RSSI samples while listening and, if cad is set,
     * channel-activity detections in between (noise_stats.h). The radio
     * goes back to its own channel afterwards. Returns 0, -1 on a radio
     * error, -2 if the channel is not legal. May be NULL (no measurement).
     */
    int (*measure)(uint32_t freq_hz, uint32_t dwell_ms, bool cad, noise_result_t *out);

    /*
     * Listen-before-talk test (SL-25 step 1): is a frame on air right now? First the receiver's
     * state (a preamble detected or a header valid: a frame is being received, so the radio is
     * left alone: a CAD would abort that reception), then, if nothing is flagged, one CAD, then
     * back to receive. Returns 1 if busy, 0 if free, -1 on a radio error. *info (may be NULL)
     * says why and how long it took. May be NULL (the radio cannot test: the channel is free).
     * The radio task calls it before every transmission when listen before talk is on
     * (radio/radio_lbt.c, RFC 0001 Amendment 14); the bench test calls it too.
     */
    int (*channel_busy)(hal_radio_busy_t *info);

    /*
     * The esp_timer time (microseconds) of the DIO1 edge behind the last frame recv() returned:
     * when the chip finished receiving it. 0 if the HAL does not keep it. May be NULL.
     */
    int64_t (*last_rx_done_us)(void);

    /*
     * How long recv() waits for a frame when none has arrived, in milliseconds (the default is 50).
     * With listen before talk on, the radio task shortens it so that a frame's wait is honoured to
     * about 10 ms rather than 60. May be NULL (the wait stays what it is).
     */
    void (*set_recv_wait_ms)(uint32_t ms);

    void (*deinit)(void);
} hal_radio_ops_t;

/* channel_busy() through the ops, true when busy; an error or a HAL without the test is "free". */
static inline bool hal_radio_channel_busy(const hal_radio_ops_t *radio, hal_radio_busy_t *info)
{
    if (info != NULL) {
        info->why = HAL_BUSY_FREE;
        info->sample_us = 0;
        info->cad_us = 0;
        info->rearm_us = 0;
    }
    if (radio == NULL || radio->channel_busy == NULL) return false;
    return radio->channel_busy(info) == 1;
}

#endif /* HAL_RADIO_H */
