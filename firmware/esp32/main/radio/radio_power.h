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

#include <stdint.h>

/* EU868 ERP limits per sub-band (dBm). */
#define ATALAIA_EU868_G_ERP_LIMIT_DBM  14 /* 25 mW, 1% DC  */
#define ATALAIA_EU868_G2_ERP_LIMIT_DBM 27 /* 500 mW, 10% DC */

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
    int conducted = conducted_x100 / 100; /* truncation = round-down */
    if (conducted < -9) conducted = -9;
    if (conducted > 22) conducted = 22;
    return (int8_t)conducted;
}

#endif /* ATALAIA_RADIO_POWER_H */
