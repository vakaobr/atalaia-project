/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Tests for the EU868 TX power calculation (radio_power.h).
 * Verifies the conducted power formula accounts for FEM and antenna
 * gain, truncates toward zero, and clamps to the SX1262 range.
 */
#include "check.h"
#include "radio/radio_power.h"

/* ---- Tests ---------------------------------------------------------------- */

static void test_g_band_default(void)
{
    /* FEM=14 dB, antenna=2 dBi, g-band ERP limit=14 dBm.
     * EIRP_x100 = 14*100 + 215 = 1615
     * conducted_x100 = 1615 - 1400 - 200 = 15
     * conducted = 15/100 = 0 dBm */
    int8_t p = atalaia_eu868_tx_power_dbm(ATALAIA_EU868_G_ERP_LIMIT_DBM, 14, 2);
    CHECK(p == 0);
}

static void test_g2_band_default(void)
{
    /* FEM=14 dB, antenna=2 dBi, g2-band ERP limit=27 dBm.
     * EIRP_x100 = 27*100 + 215 = 2915
     * conducted_x100 = 2915 - 1400 - 200 = 1315
     * conducted = 1315/100 = 13 dBm */
    int8_t p = atalaia_eu868_tx_power_dbm(ATALAIA_EU868_G2_ERP_LIMIT_DBM, 14, 2);
    CHECK(p == 13);
}

static void test_no_fem(void)
{
    /* FEM=0 (no FEM), antenna=2 dBi, g-band.
     * EIRP_x100 = 1615
     * conducted_x100 = 1615 - 0 - 200 = 1415
     * conducted = 1415/100 = 14 dBm */
    int8_t p = atalaia_eu868_tx_power_dbm(ATALAIA_EU868_G_ERP_LIMIT_DBM, 0, 2);
    CHECK(p == 14);
}

static void test_high_gain_antenna(void)
{
    /* FEM=14 dB, antenna=6 dBi, g-band.
     * EIRP_x100 = 1615
     * conducted_x100 = 1615 - 1400 - 600 = -385
     * conducted = -385/100 = -3 (C11 truncation toward zero)
     * Within [-9, +22] range. */
    int8_t p = atalaia_eu868_tx_power_dbm(ATALAIA_EU868_G_ERP_LIMIT_DBM, 14, 6);
    CHECK(p == -3);
}

static void test_clamp_low(void)
{
    /* FEM=30 dB, antenna=5 dBi, g-band.
     * EIRP_x100 = 1615
     * conducted_x100 = 1615 - 3000 - 500 = -1885
     * conducted = -1885/100 = -18 (truncation toward zero)
     * Clamped to -9. */
    int8_t p = atalaia_eu868_tx_power_dbm(ATALAIA_EU868_G_ERP_LIMIT_DBM, 30, 5);
    CHECK(p == -9);
}

static void test_clamp_high(void)
{
    /* FEM=0, antenna=0 dBi, g-band.
     * EIRP_x100 = 1615
     * conducted_x100 = 1615 - 0 - 0 = 1615
     * conducted = 1615/100 = 16
     * Within [-9, +22] range -- not clamped. */
    int8_t p = atalaia_eu868_tx_power_dbm(ATALAIA_EU868_G_ERP_LIMIT_DBM, 0, 0);
    CHECK(p == 16);
}

/* ---- Runner --------------------------------------------------------------- */

void run_radio_power_tests(void)
{
    test_g_band_default();
    test_g2_band_default();
    test_no_fem();
    test_high_gain_antenna();
    test_clamp_low();
    test_clamp_high();
}
