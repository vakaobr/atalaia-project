/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * EU868 duty-cycle tracker with per-sub-band airtime budgets and a
 * 60-bucket sliding one-hour window.
 */
#ifndef ATALAIA_DUTY_CYCLE_H
#define ATALAIA_DUTY_CYCLE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define ATALAIA_DC_WINDOW_MS (3600U * 1000U) /* 1 hour */
#define ATALAIA_DC_BUCKETS   60

typedef enum {
    ATALAIA_BAND_G = 0, /* 868.0-868.6  MHz, 1%   (36 000 ms/h)  */
    ATALAIA_BAND_G1,    /* 868.7-869.2  MHz, 0.1% (3 600 ms/h)   */
    ATALAIA_BAND_G2,    /* 869.4-869.65 MHz, 10%  (360 000 ms/h)  */
    ATALAIA_BAND_G3,    /* 869.7-870.0  MHz, 1%   (36 000 ms/h)   */
    ATALAIA_BAND_COUNT
} atalaia_band_t;

typedef struct {
    uint32_t buckets[ATALAIA_DC_BUCKETS]; /* airtime_us per minute */
    uint32_t budget_us;                   /* total allowed per hour */
    uint32_t used_us;                     /* sum of all buckets    */
    uint32_t current_bucket;
    uint32_t last_update_ms;
} atalaia_dc_band_t;

typedef struct {
    atalaia_dc_band_t bands[ATALAIA_BAND_COUNT];
} atalaia_duty_cycle_t;

/*
 * The EU868 sub-bands a game channel may use, as in ERC Recommendation
 * 70-03 Annex 1 (h1.5, h1.6, h1.7, h1.9) and ETSI EN 300 220-2 V3.2.1
 * Table B.1. The labels g, g1, g2, g3 are this project's own (RFC 0001
 * section 8); the older ERC lettering called 869.4-869.65 MHz "g3".
 * See RFC 0001 Amendment 3.
 */
#define ATALAIA_LORA_BW_HZ 125000u /* every game uses SF7 / 125 kHz (RFC 0001) */

typedef struct {
    uint32_t lo_hz;    /* lower edge */
    uint32_t hi_hz;    /* upper edge */
    uint32_t duty_ppm; /* duty-cycle limit in parts per million: 10000 = 1% */
    int8_t erp_dbm;    /* ERP limit: 14 dBm = 25 mW, 27 dBm = 500 mW */
    uint16_t erp_mw;   /* the same limit in mW */
} atalaia_band_info_t;

/* The table entry of a band (NULL for ATALAIA_BAND_COUNT or out of range). */
const atalaia_band_info_t *atalaia_band_info(atalaia_band_t band);

/*
 * The sub-band that holds a channel of the given bandwidth, or
 * ATALAIA_BAND_COUNT if none does. The whole channel must fit: centre -
 * bw/2 and centre + bw/2 both inside one sub-band (its edges included). A
 * centre inside a sub-band whose channel spills over the edge (869.40 MHz
 * at 125 kHz) is refused.
 */
atalaia_band_t atalaia_band_of_channel(uint32_t centre_hz, uint32_t bw_hz);

/* True if a game channel (125 kHz) fits inside one EU868 sub-band. */
bool atalaia_channel_ok(uint32_t centre_hz);

/* Initialises all bands with their EU868 budgets. */
void atalaia_dc_init(atalaia_duty_cycle_t *dc);

/* Advances the sliding window, zeroing expired buckets. */
void atalaia_dc_tick(atalaia_duty_cycle_t *dc, uint32_t now_ms);

/* True if used + airtime_us <= budget. */
bool atalaia_dc_can_send(const atalaia_duty_cycle_t *dc, atalaia_band_t band, uint32_t airtime_us);

/* Records airtime_us in the current bucket. */
void atalaia_dc_record(atalaia_duty_cycle_t *dc, atalaia_band_t band, uint32_t airtime_us,
                       uint32_t now_ms);

/* Remaining budget in microseconds for this band. */
uint32_t atalaia_dc_remaining_us(const atalaia_duty_cycle_t *dc, atalaia_band_t band);

/*
 * LoRa airtime in microseconds for a given SF, bandwidth (Hz) and
 * payload size (total bytes including header + MIC).
 */
uint32_t atalaia_airtime_us(uint8_t sf, uint32_t bw_hz, size_t payload_bytes);

#endif /* ATALAIA_DUTY_CYCLE_H */
