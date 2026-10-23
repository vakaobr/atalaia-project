/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Duty-cycle tracker, LoRa airtime calculator and the regions' table.
 */
#include <string.h>

#include "atalaia/duty_cycle.h"

/* EU868: ERC/REC 70-03 Annex 1 (edition of February 2025): h1.5, h1.6, h1.7,
 * h1.9, limits in ERP. In the same order as atalaia_band_t. The hourly budget
 * of a band is duty_ppm x 3600 us. */
static const atalaia_band_info_t eu868_bands[ATALAIA_BAND_COUNT] = {
    {868000000u, 868600000u, 10000, 14, 25, ATALAIA_LIMIT_ERP, 0},   /* g:  1%,   25 mW  */
    {868700000u, 869200000u, 1000, 14, 25, ATALAIA_LIMIT_ERP, 0},    /* g1: 0.1%, 25 mW  */
    {869400000u, 869650000u, 100000, 27, 500, ATALAIA_LIMIT_ERP, 0}, /* g2: 10%,  500 mW */
    {869700000u, 870000000u, 10000, 14, 25, ATALAIA_LIMIT_ERP, 0},   /* g3: 1%,   25 mW  */
};

/* Taiwan: NCC LP0002 (edition of 2020-07-01) 5.8.1, "other IoT devices",
 * 920-925 MHz, digital modulation (6 dB bandwidth at least 500 kHz, at most
 * 8 dBm in any 3 kHz): at most 0.5 W peak output outdoors (1 W indoors or in
 * a closed site with controlled access, not used), less the antenna gain
 * above 6 dBi. LP0002 sets no duty cycle; 10% is this project's own budget,
 * the airtime the game was designed for (decision RF-AS923-4). */
static const atalaia_band_info_t as923_tw_bands[1] = {
    {920000000u, 925000000u, 100000, 27, 500, ATALAIA_LIMIT_CONDUCTED, 6}, /* 0.5 W */
};

/* The regions (RFC 0001 Amendment 12). AS923-TW uses SF9 at 500 kHz: the
 * 500 kHz LP0002 asks of a non-hopping device, and with SF9 the same symbol
 * time (1.024 ms) and nearly the same sensitivity as SF7 at 125 kHz. Its
 * default channel, 921.5 MHz, keeps clear of LoRaWAN's 923.2 and 923.4 MHz
 * and Meshtastic's TW default (923.875 MHz) (decision RF-AS923-5). */
static const atalaia_region_info_t region_table[ATALAIA_REGION_COUNT] = {
    {"eu868", 7, 125000u, 869525000u, 0, ATALAIA_BAND_COUNT, eu868_bands},
    {"as923-tw", 9, 500000u, 921500000u, 0, 1, as923_tw_bands},
};

const atalaia_region_info_t *atalaia_region_info(atalaia_region_t region)
{
    if ((int)region < 0 || (int)region >= ATALAIA_REGION_COUNT) {
        return NULL;
    }
    return &region_table[region];
}

atalaia_region_t atalaia_region_from_code(const char *code)
{
    if (code == NULL) return ATALAIA_REGION_COUNT;
    for (int r = 0; r < ATALAIA_REGION_COUNT; r++) {
        if (strcmp(code, region_table[r].code) == 0) return (atalaia_region_t)r;
    }
    return ATALAIA_REGION_COUNT;
}

static atalaia_band_t band_in(const atalaia_band_info_t *bands, int count, uint32_t centre_hz,
                              uint32_t bw_hz)
{
    uint64_t half = bw_hz / 2u;
    if ((uint64_t)centre_hz < half) {
        return ATALAIA_BAND_COUNT;
    }
    uint64_t lo = (uint64_t)centre_hz - half;
    uint64_t hi = (uint64_t)centre_hz + half;
    for (int b = 0; b < count; b++) {
        if (lo >= bands[b].lo_hz && hi <= bands[b].hi_hz) {
            return (atalaia_band_t)b;
        }
    }
    return ATALAIA_BAND_COUNT;
}

atalaia_band_t atalaia_region_band_of_channel(atalaia_region_t region, uint32_t centre_hz)
{
    const atalaia_region_info_t *r = atalaia_region_info(region);
    if (r == NULL) return ATALAIA_BAND_COUNT;
    return band_in(r->bands, r->band_count, centre_hz, r->bw_hz);
}

bool atalaia_region_channel_ok(atalaia_region_t region, uint32_t centre_hz)
{
    return atalaia_region_band_of_channel(region, centre_hz) != ATALAIA_BAND_COUNT;
}

const atalaia_band_info_t *atalaia_region_band_info(atalaia_region_t region, atalaia_band_t band)
{
    const atalaia_region_info_t *r = atalaia_region_info(region);
    if (r == NULL || (int)band < 0 || (int)band >= r->band_count) return NULL;
    return &r->bands[band];
}

uint32_t atalaia_region_airtime_us(atalaia_region_t region, size_t packet_bytes)
{
    const atalaia_region_info_t *r = atalaia_region_info(region);
    if (r == NULL) return 0;
    return atalaia_airtime_us(r->sf, r->bw_hz, packet_bytes);
}

const atalaia_band_info_t *atalaia_band_info(atalaia_band_t band)
{
    return atalaia_region_band_info(ATALAIA_REGION_EU868, band);
}

atalaia_band_t atalaia_band_of_channel(uint32_t centre_hz, uint32_t bw_hz)
{
    return band_in(eu868_bands, ATALAIA_BAND_COUNT, centre_hz, bw_hz);
}

bool atalaia_channel_ok(uint32_t centre_hz)
{
    return atalaia_band_of_channel(centre_hz, ATALAIA_LORA_BW_HZ) != ATALAIA_BAND_COUNT;
}

void atalaia_dc_init_region(atalaia_duty_cycle_t *dc, atalaia_region_t region)
{
    memset(dc, 0, sizeof(*dc));
    for (int b = 0; b < ATALAIA_BAND_COUNT; b++) {
        const atalaia_band_info_t *info = atalaia_region_band_info(region, (atalaia_band_t)b);
        dc->bands[b].budget_us = info != NULL ? info->duty_ppm * 3600u : 0u;
    }
}

void atalaia_dc_init(atalaia_duty_cycle_t *dc)
{
    atalaia_dc_init_region(dc, ATALAIA_REGION_EU868);
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
