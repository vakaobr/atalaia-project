/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * EU868 duty-cycle tracker and LoRa airtime calculator.
 */
#include <string.h>

#include "atalaia/duty_cycle.h"

/* EU868 budgets in microseconds per hour. */
static const uint32_t band_budgets[ATALAIA_BAND_COUNT] = {
    36000000u,  /* G:  1%   of 3600s  */
    3600000u,   /* G1: 0.1% of 3600s  */
    360000000u, /* G2: 10%  of 3600s  */
    36000000u   /* G3: 1%   of 3600s  */
};

/* ERC/REC 70-03 Annex 1 (edition of February 2025): h1.5, h1.6, h1.7, h1.9.
 * In the same order as atalaia_band_t; band_budgets above follows duty_ppm. */
static const atalaia_band_info_t band_table[ATALAIA_BAND_COUNT] = {
    {868000000u, 868600000u, 10000, 14, 25},   /* g:  1%,   25 mW  */
    {868700000u, 869200000u, 1000, 14, 25},    /* g1: 0.1%, 25 mW  */
    {869400000u, 869650000u, 100000, 27, 500}, /* g2: 10%,  500 mW */
    {869700000u, 870000000u, 10000, 14, 25},   /* g3: 1%,   25 mW  */
};

const atalaia_band_info_t *atalaia_band_info(atalaia_band_t band)
{
    if ((int)band < 0 || (int)band >= ATALAIA_BAND_COUNT) {
        return NULL;
    }
    return &band_table[band];
}

atalaia_band_t atalaia_band_of_channel(uint32_t centre_hz, uint32_t bw_hz)
{
    uint64_t half = bw_hz / 2u;
    if ((uint64_t)centre_hz < half) {
        return ATALAIA_BAND_COUNT;
    }
    uint64_t lo = (uint64_t)centre_hz - half;
    uint64_t hi = (uint64_t)centre_hz + half;
    for (int b = 0; b < ATALAIA_BAND_COUNT; b++) {
        if (lo >= band_table[b].lo_hz && hi <= band_table[b].hi_hz) {
            return (atalaia_band_t)b;
        }
    }
    return ATALAIA_BAND_COUNT;
}

bool atalaia_channel_ok(uint32_t centre_hz)
{
    return atalaia_band_of_channel(centre_hz, ATALAIA_LORA_BW_HZ) != ATALAIA_BAND_COUNT;
}

void atalaia_dc_init(atalaia_duty_cycle_t *dc)
{
    memset(dc, 0, sizeof(*dc));
    for (int b = 0; b < ATALAIA_BAND_COUNT; b++) {
        dc->bands[b].budget_us = band_budgets[b];
    }
}

void atalaia_dc_tick(atalaia_duty_cycle_t *dc, uint32_t now_ms)
{
    for (int b = 0; b < ATALAIA_BAND_COUNT; b++) {
        atalaia_dc_band_t *band = &dc->bands[b];

        if (band->last_update_ms == 0 && band->used_us == 0) {
            /* First call: just initialise the timestamp. */
            band->last_update_ms = now_ms;
            continue;
        }

        /* How many minutes have elapsed since the last update? */
        uint32_t elapsed_ms = now_ms - band->last_update_ms;
        uint32_t minute_ms = ATALAIA_DC_WINDOW_MS / ATALAIA_DC_BUCKETS;
        uint32_t minutes = elapsed_ms / minute_ms;

        if (minutes == 0) {
            continue;
        }

        /* Zero out the buckets that have expired. */
        if (minutes >= ATALAIA_DC_BUCKETS) {
            memset(band->buckets, 0, sizeof(band->buckets));
            band->used_us = 0;
            band->current_bucket = (band->current_bucket + minutes) % ATALAIA_DC_BUCKETS;
        } else {
            for (uint32_t i = 0; i < minutes; i++) {
                uint32_t next = (band->current_bucket + 1 + i) % ATALAIA_DC_BUCKETS;
                band->used_us -= band->buckets[next];
                band->buckets[next] = 0;
            }
            band->current_bucket = (band->current_bucket + minutes) % ATALAIA_DC_BUCKETS;
        }

        band->last_update_ms += minutes * minute_ms;
    }
}

bool atalaia_dc_can_send(const atalaia_duty_cycle_t *dc, atalaia_band_t band, uint32_t airtime_us)
{
    if ((int)band < 0 || (int)band >= ATALAIA_BAND_COUNT) {
        return false;
    }
    const atalaia_dc_band_t *b = &dc->bands[band];
    return (uint64_t)b->used_us + airtime_us <= b->budget_us;
}

void atalaia_dc_record(atalaia_duty_cycle_t *dc, atalaia_band_t band, uint32_t airtime_us,
                       uint32_t now_ms)
{
    if ((int)band < 0 || (int)band >= ATALAIA_BAND_COUNT) {
        return;
    }
    atalaia_dc_tick(dc, now_ms);
    atalaia_dc_band_t *b = &dc->bands[band];
    b->buckets[b->current_bucket] += airtime_us;
    b->used_us += airtime_us;
}

uint32_t atalaia_dc_remaining_us(const atalaia_duty_cycle_t *dc, atalaia_band_t band)
{
    if ((int)band < 0 || (int)band >= ATALAIA_BAND_COUNT) {
        return 0;
    }
    const atalaia_dc_band_t *b = &dc->bands[band];
    if (b->used_us >= b->budget_us) {
        return 0;
    }
    return b->budget_us - b->used_us;
}

/*
 * LoRa airtime calculation.
 *
 * T_symbol = 2^SF / BW
 * T_preamble = (n_preamble + 4.25) * T_symbol   (n_preamble = 8)
 *
 * For the payload:
 *   numerator   = 8 * PL - 4 * SF + 28 + 16  (CRC on)
 *   denominator = 4 * (SF - 2 * DE)
 *   DE = 1 for SF >= 11, 0 otherwise
 *   CR = 1 (coding rate 4/5)
 *   payload_symbols = 8 + max(ceil(numerator / denominator) * (CR + 4), 0)
 *
 * T_payload = payload_symbols * T_symbol
 * Total = T_preamble + T_payload, in microseconds.
 */
uint32_t atalaia_airtime_us(uint8_t sf, uint32_t bw_hz, size_t payload_bytes)
{
    if (bw_hz == 0 || sf < 6 || sf > 12) {
        return 0;
    }

    /* T_symbol in microseconds: (2^SF / BW) * 1e6 */
    uint64_t t_sym_us = ((uint64_t)1 << sf) * 1000000ULL / bw_hz;

    /* Preamble: (8 + 4.25) * T_symbol = 12.25 * T_symbol.
     * Use fixed-point: 1225 * t_sym / 100. */
    uint64_t t_preamble_us = 1225ULL * t_sym_us / 100;

    /* Data-rate optimisation for SF >= 11. */
    uint8_t de = (sf >= 11) ? 1 : 0;
    uint8_t cr = 1; /* coding rate 4/5 */

    int32_t num = (int32_t)(8 * payload_bytes) - 4 * (int32_t)sf + 28 + 16;
    int32_t den = 4 * ((int32_t)sf - 2 * (int32_t)de);

    int32_t payload_symbols;
    if (num <= 0 || den <= 0) {
        payload_symbols = 8;
    } else {
        /* ceil(num / den) */
        int32_t ceil_div = (num + den - 1) / den;
        payload_symbols = 8 + ceil_div * (cr + 4);
    }

    uint64_t t_payload_us = (uint64_t)payload_symbols * t_sym_us;
    uint64_t total = t_preamble_us + t_payload_us;

    /* Clamp to uint32_t. */
    if (total > UINT32_MAX) {
        return UINT32_MAX;
    }
    return (uint32_t)total;
}
