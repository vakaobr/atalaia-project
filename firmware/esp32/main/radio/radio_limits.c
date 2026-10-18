/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * EU868 limits that follow the game channel. See radio_limits.h.
 */
#include "radio_limits.h"

#include <string.h>

#include "radio_power.h"

void radio_limits_init(radio_limits_t *l, int fem_gain_db, int antenna_gain_dbi)
{
    memset(l, 0, sizeof(*l));
    atalaia_dc_init(&l->dc);
    l->band = ATALAIA_BAND_COUNT;
    l->fem_gain_db = fem_gain_db;
    l->antenna_gain_dbi = antenna_gain_dbi;
}

bool radio_limits_power_for(const radio_limits_t *l, uint32_t channel_hz, int8_t *dbm)
{
    const atalaia_band_info_t *info =
        atalaia_band_info(atalaia_band_of_channel(channel_hz, ATALAIA_LORA_BW_HZ));
    if (info == NULL) return false;
    *dbm = atalaia_eu868_tx_power_dbm(info->erp_dbm, l->fem_gain_db, l->antenna_gain_dbi);
    return true;
}

bool radio_limits_set_channel(radio_limits_t *l, uint32_t channel_hz)
{
    int8_t power;
    if (!radio_limits_power_for(l, channel_hz, &power)) return false;
    l->channel_hz = channel_hz;
    l->band = atalaia_band_of_channel(channel_hz, ATALAIA_LORA_BW_HZ);
    l->tx_power_dbm = power;
    return true;
}

uint32_t radio_limits_airtime_us(size_t packet_len)
{
    return atalaia_airtime_us(RADIO_LORA_SF, ATALAIA_LORA_BW_HZ, packet_len);
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
    return radio_limits_airtime_us(packet_len) <= remaining_us(l, now_ms);
}

void radio_limits_record(radio_limits_t *l, size_t packet_len, uint32_t now_ms)
{
    if (l->band == ATALAIA_BAND_COUNT) return;
    atalaia_dc_record(&l->dc, l->band, radio_limits_airtime_us(packet_len), now_ms);
}
