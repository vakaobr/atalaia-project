/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The region's limits that follow the game channel. See radio_limits.h.
 */
#include "radio_limits.h"

#include <string.h>

#include "radio_power.h"

void radio_limits_init(radio_limits_t *l, int fem_gain_db, int antenna_gain_dbi)
{
    memset(l, 0, sizeof(*l));
    l->fem_gain_db = fem_gain_db;
    l->antenna_gain_dbi = antenna_gain_dbi;
    radio_limits_set_region(l, RADIO_REGION);
}

bool radio_limits_set_region(radio_limits_t *l, atalaia_region_t region)
{
    if (atalaia_region_info(region) == NULL) return false;
    l->region = region;
    atalaia_dc_init_region(&l->dc, region);
    l->band = ATALAIA_BAND_COUNT;
    l->channel_hz = 0;
    l->tx_power_dbm = 0;
    return true;
}

static atalaia_band_t band_of(const radio_limits_t *l, uint32_t channel_hz)
{
    if (l->bw_override_hz != 0) return atalaia_band_of_channel(channel_hz, l->bw_override_hz);
    return atalaia_region_band_of_channel(l->region, channel_hz);
}

bool radio_limits_set_modulation(radio_limits_t *l, uint8_t sf, uint32_t bw_hz)
{
    if (l->region != ATALAIA_REGION_EU868 || sf < 5 || sf > 12 || bw_hz == 0) return false;
    l->sf_override = sf;
    l->bw_override_hz = bw_hz;
    l->band = ATALAIA_BAND_COUNT;
    l->channel_hz = 0;
    l->tx_power_dbm = 0;
    return true;
}

void radio_limits_clear_modulation(radio_limits_t *l)
{
    l->sf_override = 0;
    l->bw_override_hz = 0;
    l->band = ATALAIA_BAND_COUNT;
    l->channel_hz = 0;
    l->tx_power_dbm = 0;
}

bool radio_limits_power_for(const radio_limits_t *l, uint32_t channel_hz, int8_t *dbm)
{
    const atalaia_band_info_t *info = atalaia_region_band_info(l->region, band_of(l, channel_hz));
    return atalaia_tx_power_for(info, l->fem_gain_db, l->antenna_gain_dbi, dbm);
}

bool radio_limits_set_channel(radio_limits_t *l, uint32_t channel_hz)
{
    int8_t power;
    if (!radio_limits_power_for(l, channel_hz, &power)) return false;
    l->channel_hz = channel_hz;
    l->band = band_of(l, channel_hz);
    l->tx_power_dbm = power;
    return true;
}

uint32_t radio_limits_airtime_us(const radio_limits_t *l, size_t packet_len)
{
    if (l->bw_override_hz != 0) {
        return atalaia_airtime_us(l->sf_override, l->bw_override_hz, packet_len);
    }
    return atalaia_region_airtime_us(l->region, packet_len);
}

static uint32_t remaining_us(radio_limits_t *l, uint32_t now_ms)
{
    if (l->band == ATALAIA_BAND_COUNT) return 0;
    atalaia_dc_tick(&l->dc, now_ms);
    uint32_t left = atalaia_dc_remaining_us(&l->dc, l->band);
    if (l->budget_cap_us != 0) {
        uint32_t used = l->dc.bands[l->band].used_us;
        uint32_t cap_left = used >= l->budget_cap_us ? 0 : l->budget_cap_us - used;
        if (cap_left < left) left = cap_left;
    }
    return left;
}

uint32_t radio_limits_remaining_ms(radio_limits_t *l, uint32_t now_ms)
{
    return remaining_us(l, now_ms) / 1000u;
}

bool radio_limits_can_send(radio_limits_t *l, size_t packet_len, uint32_t now_ms)
{
    uint32_t air_us = radio_limits_airtime_us(l, packet_len);
    const atalaia_region_info_t *r = atalaia_region_info(l->region);
    /* A region with a dwell rule: no single transmission longer than it. */
    if (r != NULL && r->max_dwell_ms != 0 && air_us > r->max_dwell_ms * 1000u) return false;
    return air_us <= remaining_us(l, now_ms);
}

void radio_limits_record(radio_limits_t *l, size_t packet_len, uint32_t now_ms)
{
    if (l->band == ATALAIA_BAND_COUNT) return;
    atalaia_dc_record(&l->dc, l->band, radio_limits_airtime_us(l, packet_len), now_ms);
}
