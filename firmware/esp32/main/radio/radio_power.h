/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * EU868 TX power calculation accounting for FEM and antenna gain.
 *
 * EU868 sub-band limits are given in ERP (dBm), ERC/REC 70-03 Annex 1:
 *   g-band  (868.0-868.6 MHz):  14 dBm ERP = 25 mW   (1% duty cycle)
 *   g1-band (868.7-869.2 MHz):  14 dBm ERP = 25 mW   (0.1%)
 *   g2-band (869.4-869.65 MHz): 27 dBm ERP = 500 mW   (10%)
 *   g3-band (869.7-870.0 MHz):  14 dBm ERP = 25 mW   (1%)
 * The table is atalaia_band_info() in the core; radio_limits.c picks the
 * limit of the game channel's sub-band (RFC 0001 Amendment 3).
 *
 * EIRP = ERP + 2.15 dBi (dipole reference).
 * Conducted power = ERP + 2.15 - antenna_gain_dBi - fem_gain_dB.
 *
 * Result is truncated (rounded down) to an integer and clamped to the
 * SX1262 range [-9, +22] dBm.  This is a pure function, testable on
 * any host.
 */
#ifndef ATALAIA_RADIO_POWER_H
#define ATALAIA_RADIO_POWER_H

#include <stdbool.h>
#include <stdint.h>

#include "atalaia/duty_cycle.h"

/* EU868 ERP limits per sub-band (dBm). */
#define ATALAIA_EU868_G_ERP_LIMIT_DBM  14 /* 25 mW, 1% DC  */
#define ATALAIA_EU868_G2_ERP_LIMIT_DBM 27 /* 500 mW, 10% DC */

/* x100 / 100 rounded toward minus infinity: the conducted power may never be rounded up, and C's
 * division rounds a negative quotient toward zero (-7.85 dBm would become -7, over the limit). */
static inline int atalaia_floor_div100(int x100)
{
    return x100 >= 0 ? x100 / 100 : -((-x100 + 99) / 100);
}

/*
 * Compute the SX1262 conducted TX power for an EU868 sub-band.
 *
 * erp_limit_dbm: the sub-band's ERP limit (use the macros above).
 * fem_gain_db:   front-end module gain in dB (0 if no FEM).
 * antenna_gain_dbi: antenna gain in dBi (2 for a typical stock omni).
 *
 * Returns the conducted power in dBm, clamped to [-9, +22].
 */
static inline int8_t atalaia_eu868_tx_power_dbm(int erp_limit_dbm, int fem_gain_db,
                                                int antenna_gain_dbi)
{
    /* Work in centi-dBm to avoid floating point.
     * EIRP = ERP + 2.15 dBi -> x100 = ERP*100 + 215.
     * Conducted = EIRP - FEM - antenna. */
    int eirp_x100 = erp_limit_dbm * 100 + 215;
    int conducted_x100 = eirp_x100 - fem_gain_db * 100 - antenna_gain_dbi * 100;
    int conducted = atalaia_floor_div100(conducted_x100); /* round down, also below zero */
    if (conducted < -9) conducted = -9;
    if (conducted > 22) conducted = 22;
    return (int8_t)conducted;
}

/*
 * The SX1262 conducted power for a sub-band of any region (RFC 0001
 * Amendment 12), by what its limit is measured as:
 *   ERP:       limit + 2.15 - antenna - FEM (as above)
 *   EIRP:      limit - antenna - FEM
 *   CONDUCTED: limit - FEM - max(0, antenna - free_gain_dbi): NCC LP0002
 *              5.8.1.2 limits the peak output at the antenna port and
 *              lowers it by the antenna gain above 6 dBi.
 * Capped at +22 dBm. Returns false, writing nothing, when even the SX1262's
 * lowest setting (-9 dBm) would exceed the limit with these gains: such a
 * channel may not be used (the old clamp to -9 dBm would have transmitted
 * over the limit).
 */
static inline bool atalaia_tx_power_for(const atalaia_band_info_t *band, int fem_gain_db,
                                        int antenna_gain_dbi, int8_t *dbm)
{
    if (band == NULL) return false;
    int x100;
    switch (band->limit_ref) {
    case ATALAIA_LIMIT_ERP:
        x100 = band->limit_dbm * 100 + 215 - fem_gain_db * 100 - antenna_gain_dbi * 100;
        break;
    case ATALAIA_LIMIT_EIRP:
        x100 = band->limit_dbm * 100 - fem_gain_db * 100 - antenna_gain_dbi * 100;
        break;
    case ATALAIA_LIMIT_CONDUCTED: {
        int over = antenna_gain_dbi - (int)band->free_gain_dbi;
        x100 = band->limit_dbm * 100 - fem_gain_db * 100 - (over > 0 ? over : 0) * 100;
        break;
    }
    default: return false;
    }
    int conducted = atalaia_floor_div100(x100); /* round down, as the Python side */
    if (conducted < -9) return false;
    if (conducted > 22) conducted = 22;
    *dbm = (int8_t)conducted;
    return true;
}

#endif /* ATALAIA_RADIO_POWER_H */
