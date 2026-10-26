/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The radio settings of a listen-before-talk bench run (lbt_profile.h).
 */
#include "lbt_profile.h"

#include <limits.h>
#include <string.h>

#include "lbt_stats.h"

void lbt_profile_build(lbt_profile_t *p, atalaia_region_t region)
{
    memset(p, 0, sizeof(*p));
    const atalaia_region_info_t *r = atalaia_region_info(region);
    if (r == NULL) {
        region = ATALAIA_REGION_EU868;
        r = atalaia_region_info(region);
    }
    p->name = "build";
    p->mod_from = r->code;
    p->sf = r->sf;
    p->bw_hz = r->bw_hz;
    p->freq_hz = r->default_channel_hz;
    p->cad = r->cad;
    p->tx_power_dbm = 127;
    atalaia_band_t b = atalaia_region_band_of_channel(region, p->freq_hz);
    const atalaia_band_info_t *bi = atalaia_region_band_info(region, b);
    if (bi != NULL) {
        p->eu868_band = (uint8_t)b;
        p->duty_ppm = bi->duty_ppm;
        p->limit_dbm = bi->limit_dbm;
    }
}

bool lbt_profile_as923_eu868(lbt_profile_t *p, int det_peak, int det_min, int power_dbm)
{
    if (det_peak != -1 && (det_peak < 10 || det_peak > 40)) return false;
    if (det_min != -1 && (det_min < 1 || det_min > 30)) return false;
    if (power_dbm != INT8_MIN && (power_dbm < -9 || power_dbm > 22)) return false;
    const atalaia_region_info_t *as = atalaia_region_info(ATALAIA_REGION_AS923_TW);
    const atalaia_band_info_t *g = atalaia_band_info(ATALAIA_BAND_G);
    if (as == NULL || g == NULL) return false;
    lbt_profile_t t;
    memset(&t, 0, sizeof(t));
    t.name = "as923-eu868";
    t.mod_from = as->code;
    t.sf = as->sf;
    t.bw_hz = as->bw_hz;
    t.freq_hz = LBT_PROXY_FREQ_HZ;
    t.cad = as->cad;
    if (det_peak != -1) {
        t.cad.det_peak = (uint8_t)det_peak;
        t.cad.det_peak_bench_proven = false;
    }
    if (det_min != -1) t.cad.det_min = (uint8_t)det_min;
    t.proxy = true;
    t.eu868_band = ATALAIA_BAND_G;
    t.duty_ppm = g->duty_ppm;
    t.limit_dbm = g->limit_dbm;
    t.tx_power_dbm = power_dbm == INT8_MIN ? LBT_PROXY_POWER_DEFAULT_DBM : (int8_t)power_dbm;
    if (!lbt_profile_channel_ok(&t)) return false;
    *p = t;
    return true;
}

bool lbt_profile_channel_ok(const lbt_profile_t *p)
{
    if (!p->proxy) return true;
    uint32_t half = p->bw_hz / 2u;
    if (p->freq_hz < half) return false;
    uint32_t lo = p->freq_hz - half, hi = p->freq_hz + half;
    /* The whole channel inside the one EU868 sub-band the profile names... */
    const atalaia_band_info_t *b = atalaia_band_info((atalaia_band_t)p->eu868_band);
    if (b == NULL || lo < b->lo_hz || hi > b->hi_hz) return false;
    if (atalaia_band_of_channel(p->freq_hz, p->bw_hz) != (atalaia_band_t)p->eu868_band) {
        return false;
    }
    /* ... and nowhere near an AS923 frequency. */
    for (int r = 0; r < ATALAIA_REGION_COUNT; r++) {
        if (r == ATALAIA_REGION_EU868) continue;
        const atalaia_region_info_t *ri = atalaia_region_info((atalaia_region_t)r);
        for (int i = 0; ri != NULL && i < ri->band_count; i++) {
            if (hi >= ri->bands[i].lo_hz && lo <= ri->bands[i].hi_hz) return false;
        }
    }
    return true;
}

uint32_t lbt_profile_airtime_us(const lbt_profile_t *p, size_t len)
{
    return atalaia_airtime_us(p->sf, p->bw_hz, len);
}

uint32_t lbt_profile_budget_ms(const lbt_profile_t *p)
{
    return p->duty_ppm * 3600u / 1000u;
}

uint32_t lbt_profile_guard_ms(const lbt_profile_t *p)
{
    return (uint32_t)((uint64_t)lbt_profile_budget_ms(p) * LBT_GUARD_PERCENT_LEFT / 100u);
}

uint32_t lbt_profile_frames_max(const lbt_profile_t *p)
{
    uint32_t spend_us = (lbt_profile_budget_ms(p) - lbt_profile_guard_ms(p)) * 1000u;
    uint32_t air = lbt_profile_airtime_us(p, LBT_STATE_LEN_MAX);
    uint32_t n = air == 0 ? 0 : spend_us / air;
    return n > LBT_TX_FRAMES_MAX ? LBT_TX_FRAMES_MAX : n;
}

uint32_t lbt_profile_frames_default(const lbt_profile_t *p)
{
    uint32_t def = p->proxy ? LBT_PROXY_FRAMES_DEFAULT : LBT_FRAMES_DEFAULT;
    uint32_t max = lbt_profile_frames_max(p);
    return def > max ? max : def;
}

void lbt_profile_to_hal(const lbt_profile_t *p, hal_radio_profile_t *out)
{
    out->sf = p->sf;
    out->bw_hz = p->bw_hz;
    out->freq_hz = p->freq_hz;
    out->cad = p->cad;
    out->eu868_band = p->eu868_band;
    out->tx_power_dbm = p->tx_power_dbm;
}
