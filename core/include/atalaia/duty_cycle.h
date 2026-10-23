/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Duty-cycle tracker with per-sub-band airtime budgets and a 60-bucket
 * sliding one-hour window, and the regulatory regions a field can be in
 * (EU868, AS923 as Taiwan uses it): their sub-bands, limits and LoRa
 * settings, in one table (RFC 0001 Amendment 12).
 */
#ifndef ATALAIA_DUTY_CYCLE_H
#define ATALAIA_DUTY_CYCLE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define ATALAIA_DC_WINDOW_MS (3600U * 1000U) /* 1 hour */
#define ATALAIA_DC_BUCKETS   60

/*
 * A sub-band's index inside its region. EU868 has four (the names below);
 * AS923-TW one (index 0, 920-925 MHz). ATALAIA_BAND_COUNT is both the most
 * a region may have and "no sub-band".
 */
typedef enum {
    ATALAIA_BAND_G = 0, /* EU868 868.0-868.6  MHz, 1%   (36 000 ms/h)  */
    ATALAIA_BAND_G1,    /* EU868 868.7-869.2  MHz, 0.1% (3 600 ms/h)   */
    ATALAIA_BAND_G2,    /* EU868 869.4-869.65 MHz, 10%  (360 000 ms/h)  */
    ATALAIA_BAND_G3,    /* EU868 869.7-870.0  MHz, 1%   (36 000 ms/h)   */
    ATALAIA_BAND_COUNT
} atalaia_band_t;

#define ATALAIA_BAND_TW 0 /* AS923-TW's only sub-band, 920-925 MHz */

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
#define ATALAIA_LORA_BW_HZ 125000u /* EU868 games use SF7 / 125 kHz (RFC 0001) */

/* What a power limit is measured as. */
typedef enum {
    ATALAIA_LIMIT_ERP = 0,       /* radiated, half-wave dipole reference (EU868) */
    ATALAIA_LIMIT_EIRP = 1,      /* radiated, isotropic reference */
    ATALAIA_LIMIT_CONDUCTED = 2, /* peak output at the antenna port (NCC LP0002 5.8.1.2):
                                  * antenna gain above free_gain_dbi counts against it */
} atalaia_limit_ref_t;

typedef struct {
    uint32_t lo_hz;        /* lower edge */
    uint32_t hi_hz;        /* upper edge */
    uint32_t duty_ppm;     /* duty-cycle budget in parts per million: 10000 = 1% */
    int8_t limit_dbm;      /* power limit: 14 dBm = 25 mW, 27 dBm = 500 mW */
    uint16_t limit_mw;     /* the same limit in mW */
    uint8_t limit_ref;     /* atalaia_limit_ref_t */
    uint8_t free_gain_dbi; /* LIMIT_CONDUCTED: antenna gain allowed before it reduces power */
} atalaia_band_info_t;

/*
 * Regulatory regions (RFC 0001 Amendment 12). The number is the join
 * payload's key 18; a box's firmware is built for one region (Kconfig
 * ATALAIA_RADIO_REGION) and refuses the others.
 */
typedef enum {
    ATALAIA_REGION_EU868 = 0,    /* Europe, 863-870 MHz (ERC/REC 70-03 Annex 1) */
    ATALAIA_REGION_AS923_TW = 1, /* Taiwan, 920-925 MHz (NCC LP0002 5.8, LoRaWAN AS923-1) */
    ATALAIA_REGION_COUNT
} atalaia_region_t;

typedef struct {
    const char *code;            /* "eu868", "as923-tw": the API's and the config's name */
    uint8_t sf;                  /* LoRa spreading factor of every game packet */
    uint32_t bw_hz;              /* LoRa bandwidth: the channel's width */
    uint32_t default_channel_hz; /* the boot and pairing channel */
    uint32_t max_dwell_ms;       /* longest single transmission (0: no rule) */
    uint8_t band_count;          /* sub-bands, at most ATALAIA_BAND_COUNT */
    const atalaia_band_info_t *bands;
} atalaia_region_info_t;

/* The region's table entry (NULL when out of range). */
const atalaia_region_info_t *atalaia_region_info(atalaia_region_t region);

/* The region named code ("eu868", "as923-tw"), or ATALAIA_REGION_COUNT. */
atalaia_region_t atalaia_region_from_code(const char *code);

/*
 * The region's sub-band that holds the whole channel (centre +- bw/2, edges
 * included), or ATALAIA_BAND_COUNT.
 */
atalaia_band_t atalaia_region_band_of_channel(atalaia_region_t region, uint32_t centre_hz);

/* True if a game channel fits inside one of the region's sub-bands. */
bool atalaia_region_channel_ok(atalaia_region_t region, uint32_t centre_hz);

/* A sub-band of a region (NULL when either is out of range). */
const atalaia_band_info_t *atalaia_region_band_info(atalaia_region_t region, atalaia_band_t band);

/* Time on air of a whole packet at the region's SF and bandwidth, in microseconds. */
uint32_t atalaia_region_airtime_us(atalaia_region_t region, size_t packet_bytes);

/* Initialises the tracker with the region's budgets (unused slots get 0). */
void atalaia_dc_init_region(atalaia_duty_cycle_t *dc, atalaia_region_t region);

/* The EU868 table entry of a band (NULL for ATALAIA_BAND_COUNT or out of range). */
const atalaia_band_info_t *atalaia_band_info(atalaia_band_t band);

/*
 * The EU868 sub-band that holds a channel of the given bandwidth, or
 * ATALAIA_BAND_COUNT if none does. The whole channel must fit: centre -
 * bw/2 and centre + bw/2 both inside one sub-band (its edges included). A
 * centre inside a sub-band whose channel spills over the edge (869.40 MHz
 * at 125 kHz) is refused.
 */
atalaia_band_t atalaia_band_of_channel(uint32_t centre_hz, uint32_t bw_hz);

/* True if a game channel (125 kHz) fits inside one EU868 sub-band. */
bool atalaia_channel_ok(uint32_t centre_hz);

/* Initialises all bands with their EU868 budgets (atalaia_dc_init_region, EU868). */
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
