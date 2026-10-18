/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * EU868 limits that follow the game channel (RFC 0001 section 8 and
 * Amendment 3): the channel's sub-band sets both the duty-cycle budget
 * (1%, 0.1% or 10% of every rolling hour) and the TX power (25 mW or
 * 500 mW ERP, less the FEM and antenna gains, decision C2).
 *
 * Airtime is tracked per sub-band with the core's 60-bucket sliding hour
 * (core/src/duty_cycle.c), so moving to another channel does not reset
 * what was already spent in a sub-band, and time on air uses the LoRa
 * formula for SF7/BW125 (atalaia_airtime_us). The ESP32 SX1262 HAL and the
 * host modem both use this; it is plain C and host-tested.
 */
#ifndef ATALAIA_RADIO_LIMITS_H
#define ATALAIA_RADIO_LIMITS_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "atalaia/duty_cycle.h"

#define RADIO_LORA_SF 7

typedef struct {
    atalaia_duty_cycle_t dc;
    uint32_t channel_hz;
    atalaia_band_t band;
    int8_t tx_power_dbm; /* SX1262 conducted power for this sub-band */
    int fem_gain_db;
    int antenna_gain_dbi;
    uint32_t budget_cap_us; /* 0 = none; a lower budget than the band's (host tests) */
} radio_limits_t;

/* No channel yet: radio_limits_set_channel() must succeed before any TX. */
void radio_limits_init(radio_limits_t *l, int fem_gain_db, int antenna_gain_dbi);

/*
 * Moves to a channel. Returns false, changing nothing, if the 125 kHz
 * channel does not fit inside one EU868 sub-band.
 */
bool radio_limits_set_channel(radio_limits_t *l, uint32_t channel_hz);

/* The conducted power a channel would get (false if the channel is not legal). */
bool radio_limits_power_for(const radio_limits_t *l, uint32_t channel_hz, int8_t *dbm);

/* Time on air of a whole packet (header + payload + MIC), in microseconds. */
uint32_t radio_limits_airtime_us(size_t packet_len);

/* The current sub-band's budget left in the rolling hour, in milliseconds. */
uint32_t radio_limits_remaining_ms(radio_limits_t *l, uint32_t now_ms);

/* True if a packet of this length fits in what is left of the budget. */
bool radio_limits_can_send(radio_limits_t *l, size_t packet_len, uint32_t now_ms);

/* Records a packet sent on the current channel. */
void radio_limits_record(radio_limits_t *l, size_t packet_len, uint32_t now_ms);

#endif /* ATALAIA_RADIO_LIMITS_H */
