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
     * conducted = floor(-3.85) = -4 (rounded down: never over the limit)
     * Within [-9, +22] range. */
    int8_t p = atalaia_eu868_tx_power_dbm(ATALAIA_EU868_G_ERP_LIMIT_DBM, 14, 6);
    CHECK(p == -4);
}

static void test_clamp_low(void)
{
    /* FEM=30 dB, antenna=5 dBi, g-band.
     * EIRP_x100 = 1615
     * conducted_x100 = 1615 - 3000 - 500 = -1885
     * conducted = floor(-18.85) = -19 (rounded down)
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

/* atalaia_tx_power_for: every kind of limit, and false when -9 dBm is still too much. */
static void test_power_for_each_kind_of_limit(void)
{
    int8_t p = 99;
    const atalaia_band_info_t *g2 = atalaia_band_info(ATALAIA_BAND_G2);
    CHECK(atalaia_tx_power_for(g2, 14, 2, &p) && p == 13); /* as atalaia_eu868_tx_power_dbm */
    /* A 10 dBi whip (the bench's third board): 5.15 dBm on g2 is 5; -7.85 dBm on g is -8, never
     * the -7 a division toward zero gives, which would be 0.85 dB over 25 mW ERP. */
    CHECK(atalaia_tx_power_for(g2, 14, 10, &p) && p == 5);
    CHECK(atalaia_tx_power_for(atalaia_band_info(ATALAIA_BAND_G), 14, 10, &p) && p == -8);
    CHECK(atalaia_tx_power_for(atalaia_band_info(ATALAIA_BAND_G), 14, 6, &p) && p == -4);
    const atalaia_band_info_t *tw =
        atalaia_region_band_info(ATALAIA_REGION_AS923_TW, (atalaia_band_t)ATALAIA_BAND_TW);
    CHECK(atalaia_tx_power_for(tw, 14, 2, &p) && p == 13);
    CHECK(atalaia_tx_power_for(tw, 14, 6, &p) && p == 13);
    CHECK(atalaia_tx_power_for(tw, 14, 8, &p) && p == 11);
    CHECK(atalaia_tx_power_for(tw, 0, 0, &p) && p == 22); /* the SX1262's top */
    atalaia_band_info_t eirp = *tw;
    eirp.limit_ref = ATALAIA_LIMIT_EIRP;
    CHECK(atalaia_tx_power_for(&eirp, 14, 2, &p) && p == 11);
    /* g with a 30 dB FEM: -15 dBm needed, below the chip's -9: refused, p untouched. */
    p = 99;
    CHECK(!atalaia_tx_power_for(atalaia_band_info(ATALAIA_BAND_G), 30, 2, &p) && p == 99);
    CHECK(!atalaia_tx_power_for(NULL, 14, 2, &p));
    atalaia_band_info_t odd = *tw;
    odd.limit_ref = 7;
    CHECK(!atalaia_tx_power_for(&odd, 14, 2, &p));
}

void run_radio_power_tests(void)
{
    test_power_for_each_kind_of_limit();
    test_g_band_default();
    test_g2_band_default();
    test_no_fem();
    test_high_gain_antenna();
    test_clamp_low();
    test_clamp_high();
}
