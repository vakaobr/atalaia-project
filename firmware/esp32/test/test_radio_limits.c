/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The EU868 limits that follow the game channel (radio_limits.c: duty-cycle
 * budget and TX power from the channel's sub-band, RFC 0001 Amendment 3)
 * and the noise measurement summary (noise_stats.c, the modem's MEASURE).
 */
#include <string.h>

#include "check.h"
#include "radio/noise_stats.h"
#include "radio/radio_limits.h"

/* A 47-byte packet (9 header + 30 payload + 8 MIC) at SF7/BW125:
 * 12.25 preamble symbols + 78 payload symbols of 1.024 ms = 92.416 ms. */
#define PKT     47
#define PKT_US  92416u
#define HOUR_MS 3600000u

static void test_airtime(void)
{
    CHECK(radio_limits_airtime_us(PKT) == PKT_US);
    CHECK(radio_limits_airtime_us(217) > radio_limits_airtime_us(PKT));
}

static void test_no_channel_no_tx(void)
{
    radio_limits_t l;
    radio_limits_init(&l, 14, 2);
    CHECK(l.band == ATALAIA_BAND_COUNT);
    CHECK(radio_limits_remaining_ms(&l, 1000) == 0);
    CHECK(!radio_limits_can_send(&l, PKT, 1000));
}

static void test_budget_and_power_follow_the_channel(void)
{
    radio_limits_t l;
    radio_limits_init(&l, 14, 2);

    /* g2: 10% (360 s per hour), 500 mW ERP -> 13 dBm conducted (decision C2). */
    CHECK(radio_limits_set_channel(&l, 869525000u));
    CHECK(l.band == ATALAIA_BAND_G2 && l.tx_power_dbm == 13);
    CHECK(radio_limits_remaining_ms(&l, 1000) == 360000u);

    /* g: 1% (36 s), 25 mW ERP -> 0 dBm. */
    CHECK(radio_limits_set_channel(&l, 868100000u));
    CHECK(l.band == ATALAIA_BAND_G && l.tx_power_dbm == 0);
    CHECK(radio_limits_remaining_ms(&l, 1000) == 36000u);

    /* g1: 0.1% (3.6 s), 25 mW. */
    CHECK(radio_limits_set_channel(&l, 868800000u));
    CHECK(l.band == ATALAIA_BAND_G1 && l.tx_power_dbm == 0);
    CHECK(radio_limits_remaining_ms(&l, 1000) == 3600u);

    /* g3: 1%, 25 mW. */
    CHECK(radio_limits_set_channel(&l, 869850000u));
    CHECK(l.band == ATALAIA_BAND_G3 && l.tx_power_dbm == 0);
    CHECK(radio_limits_remaining_ms(&l, 1000) == 36000u);

    /* A centre whose channel spills over a sub-band edge changes nothing. */
    CHECK(!radio_limits_set_channel(&l, 869400000u));
    CHECK(!radio_limits_set_channel(&l, 869650000u));
    CHECK(!radio_limits_set_channel(&l, 870000000u));
    CHECK(!radio_limits_set_channel(&l, 915000000u));
    CHECK(l.channel_hz == 869850000u && l.band == ATALAIA_BAND_G3);

    int8_t dbm = 0;
    CHECK(radio_limits_power_for(&l, 869475000u, &dbm) && dbm == 13);
    CHECK(radio_limits_power_for(&l, 868500000u, &dbm) && dbm == 0);
    CHECK(!radio_limits_power_for(&l, 869650000u, &dbm));

    /* Without FEM or antenna gain, g2 is capped at the SX1262's 22 dBm. */
    radio_limits_t bare;
    radio_limits_init(&bare, 0, 0);
    CHECK(radio_limits_set_channel(&bare, 869525000u) && bare.tx_power_dbm == 22);
    CHECK(radio_limits_set_channel(&bare, 868300000u) && bare.tx_power_dbm == 16);
}

static void test_budget_is_per_sub_band(void)
{
    radio_limits_t l;
    radio_limits_init(&l, 14, 2);
    CHECK(radio_limits_set_channel(&l, 868800000u)); /* g1: 3,600,000 us per hour */
    uint32_t t = 1000;
    int sent = 0;
    while (radio_limits_can_send(&l, PKT, t) && sent < 100) {
        radio_limits_record(&l, PKT, t);
        sent++;
        t += 10;
    }
    CHECK(sent == (int)(3600000u / PKT_US)); /* 38 packets */
    CHECK(radio_limits_remaining_ms(&l, t) == (3600000u - 38u * PKT_US) / 1000u);

    /* Another sub-band has its own budget... */
    CHECK(radio_limits_set_channel(&l, 869525000u));
    CHECK(radio_limits_can_send(&l, PKT, t));
    CHECK(radio_limits_remaining_ms(&l, t) == 360000u);
    radio_limits_record(&l, PKT, t);
    CHECK(radio_limits_remaining_ms(&l, t) == (360000000u - PKT_US) / 1000u);

    /* ...and going back does not reset the one already spent. */
    CHECK(radio_limits_set_channel(&l, 868800000u));
    CHECK(!radio_limits_can_send(&l, PKT, t));
    /* Another channel in the same sub-band shares it too. */
    CHECK(radio_limits_set_channel(&l, 869100000u));
    CHECK(!radio_limits_can_send(&l, PKT, t));

    /* An hour later the airtime has slid out of the window. */
    t += HOUR_MS + 60000u;
    CHECK(radio_limits_can_send(&l, PKT, t));
    CHECK(radio_limits_remaining_ms(&l, t) == 3600u);
}

static void test_budget_cap(void)
{
    radio_limits_t l;
    radio_limits_init(&l, 14, 2);
    l.budget_cap_us = 200000u; /* host-modem tests: --duty-budget-ms 200 */
    CHECK(radio_limits_set_channel(&l, 869525000u));
    CHECK(radio_limits_remaining_ms(&l, 1000) == 200u);
    radio_limits_record(&l, PKT, 1000);
    radio_limits_record(&l, PKT, 1000);
    CHECK(!radio_limits_can_send(&l, PKT, 1000));
    CHECK(radio_limits_remaining_ms(&l, 1000) == (200000u - 2u * PKT_US) / 1000u);
}

/* ---- noise_stats ---------------------------------------------------------- */

static void test_noise_summary(void)
{
    noise_acc_t a;
    noise_acc_init(&a);
    noise_result_t r;
    CHECK(!noise_acc_finish(&a, 869525000u, 100, &r)); /* no samples */
    CHECK(r.channel_hz == 869525000u && r.samples == 0);

    /* 100 readings: 80 at -120, 10 at -110, 9 at -100, 1 at -60. */
    for (int i = 0; i < 80; i++) noise_acc_add(&a, -120);
    for (int i = 0; i < 10; i++) noise_acc_add(&a, -110);
    for (int i = 0; i < 9; i++) noise_acc_add(&a, -100);
    noise_acc_add(&a, -60);
    CHECK(noise_acc_finish(&a, 868100000u, 2000, &r));
    CHECK(r.samples == 100 && r.dwell_ms == 2000);
    CHECK(r.min_dbm == -120 && r.max_dbm == -60);
    CHECK(r.p50_dbm == -120);
    CHECK(r.p90_dbm == -110); /* the 90th reading */
    /* (-9600 - 1100 - 900 - 60) / 100 = -116.6 -> -117 */
    CHECK(r.mean_dbm == -117);

    /* One more loud reading moves the 90th percentile up a bin. */
    noise_acc_add(&a, -100);
    CHECK(noise_acc_finish(&a, 868100000u, 2000, &r));
    CHECK(r.p90_dbm == -100);
}

static void test_noise_clamps_and_cad(void)
{
    noise_acc_t a;
    noise_acc_init(&a);
    noise_acc_add(&a, -200);
    noise_acc_add(&a, 25);
    noise_acc_cad(&a, true);
    noise_acc_cad(&a, false);
    noise_acc_cad(&a, true);
    noise_result_t r;
    CHECK(noise_acc_finish(&a, 869850000u, 10, &r));
    CHECK(r.min_dbm == NOISE_DBM_MIN && r.max_dbm == NOISE_DBM_MAX);
    CHECK(r.mean_dbm == -64);
    CHECK(r.cad_tries == 3 && r.cad_detected == 2);

    /* Counters saturate instead of wrapping. */
    a.cad_tries = UINT16_MAX - 1;
    noise_acc_cad(&a, false);
    noise_acc_cad(&a, true);
    CHECK(a.cad_tries == UINT16_MAX);
    a.samples = 70000;
    CHECK(noise_acc_finish(&a, 869850000u, 10, &r) && r.samples == UINT16_MAX);
}

static void test_noise_encode(void)
{
    noise_result_t r = {.channel_hz = 869525000u,
                        .dwell_ms = 300,
                        .samples = 299,
                        .min_dbm = -125,
                        .mean_dbm = -119,
                        .p50_dbm = -120,
                        .p90_dbm = -115,
                        .max_dbm = -98,
                        .cad_tries = 2,
                        .cad_detected = 1};
    uint8_t buf[NOISE_RESULT_LEN];
    CHECK(noise_result_encode(&r, buf, sizeof(buf) - 1) == 0);
    CHECK(noise_result_encode(&r, buf, sizeof(buf)) == NOISE_RESULT_LEN);
    static const uint8_t want[NOISE_RESULT_LEN] = {0x33, 0xD3, 0xE6, 0x08, 0x01, 0x2C,
                                                   0x01, 0x2B, 0x83, 0x89, 0x88, 0x8D,
                                                   0x9E, 0x00, 0x02, 0x00, 0x01};
    CHECK(memcmp(buf, want, sizeof(want)) == 0);
}

void run_radio_limits_tests(void)
{
    test_airtime();
    test_no_channel_no_tx();
    test_budget_and_power_follow_the_channel();
    test_budget_is_per_sub_band();
    test_budget_cap();
    test_noise_summary();
    test_noise_clamps_and_cad();
    test_noise_encode();
}
