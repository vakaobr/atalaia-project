/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The limits that follow the game channel in the radio's region (RFC 0001
 * section 8, Amendments 3 and 12): the channel's sub-band sets both the
 * duty-cycle budget and the TX power. EU868: 1%, 0.1% or 10% of every
 * rolling hour, 25 mW or 500 mW ERP, less the FEM and antenna gains
 * (decision C2). AS923-TW: 0.5 W peak at the antenna port, less the FEM gain
 * and the antenna gain above 6 dBi, and this project's 10%.
 *
 * Airtime is tracked per sub-band with the core's 60-bucket sliding hour
 * (core/src/duty_cycle.c), so moving to another channel does not reset
 * what was already spent in a sub-band, and time on air uses the LoRa
 * formula at the region's SF and bandwidth (atalaia_region_airtime_us:
 * SF7/125 kHz in EU868, SF9/500 kHz in AS923-TW). A channel whose limit the
 * SX1262 cannot keep even at its lowest power is refused. The ESP32 SX1262
 * HAL and the host modem both use this; it is plain C and host-tested.
 */
#ifndef ATALAIA_RADIO_LIMITS_H
#define ATALAIA_RADIO_LIMITS_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "atalaia/duty_cycle.h"
#include "radio_region.h"

typedef struct {
    atalaia_duty_cycle_t dc;
    atalaia_region_t region; /* RADIO_REGION after init */
    uint32_t channel_hz;
    atalaia_band_t band;
    int8_t tx_power_dbm; /* SX1262 conducted power for this sub-band */
    int fem_gain_db;
    int antenna_gain_dbi;
    uint32_t budget_cap_us; /* 0 = none; a lower budget than the band's (host tests) */
} radio_limits_t;

/* The build's region, no channel yet: radio_limits_set_channel() must succeed before any TX. */
void radio_limits_init(radio_limits_t *l, int fem_gain_db, int antenna_gain_dbi);

/* Another region (host tests and the host modem's --region): its budgets, no channel yet.
 * False, changing nothing, for an unknown region. */
bool radio_limits_set_region(radio_limits_t *l, atalaia_region_t region);

/*
 * Moves to a channel. Returns false, changing nothing, if the channel (at the
 * region's bandwidth) does not fit inside one of the region's sub-bands, or
 * its limit cannot be kept with these gains.
 */
bool radio_limits_set_channel(radio_limits_t *l, uint32_t channel_hz);

/* The conducted power a channel would get (false if the channel is not legal). */
bool radio_limits_power_for(const radio_limits_t *l, uint32_t channel_hz, int8_t *dbm);

/* Time on air of a whole packet (header + payload + MIC) in the region, in microseconds. */
uint32_t radio_limits_airtime_us(const radio_limits_t *l, size_t packet_len);

/* The current sub-band's budget left in the rolling hour, in milliseconds. */
uint32_t radio_limits_remaining_ms(radio_limits_t *l, uint32_t now_ms);

/* True if a packet of this length fits in what is left of the budget (and in the region's
 * dwell rule, when it has one). */
bool radio_limits_can_send(radio_limits_t *l, size_t packet_len, uint32_t now_ms);

/* Records a packet sent on the current channel. */
void radio_limits_record(radio_limits_t *l, size_t packet_len, uint32_t now_ms);

#endif /* ATALAIA_RADIO_LIMITS_H */
