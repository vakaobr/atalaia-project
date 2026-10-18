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

    void (*deinit)(void);
} hal_radio_ops_t;

#endif /* HAL_RADIO_H */
