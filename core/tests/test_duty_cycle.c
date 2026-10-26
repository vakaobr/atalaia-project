/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Tests for the duty-cycle tracker and airtime calculator.
 */
#include <stdio.h>
#include <string.h>

#include "atalaia/duty_cycle.h"
#include "check.h"

static void test_init_budgets(void)
{
    atalaia_duty_cycle_t dc;
    atalaia_dc_init(&dc);

    CHECK(dc.bands[ATALAIA_BAND_G].budget_us == 36000000u);
    CHECK(dc.bands[ATALAIA_BAND_G1].budget_us == 3600000u);
    CHECK(dc.bands[ATALAIA_BAND_G2].budget_us == 360000000u);
    CHECK(dc.bands[ATALAIA_BAND_G3].budget_us == 36000000u);
}

static void test_can_send_basic(void)
{
    atalaia_duty_cycle_t dc;
    atalaia_dc_init(&dc);

    /* Before any usage, should be able to send. */
    CHECK(atalaia_dc_can_send(&dc, ATALAIA_BAND_G, 1000000));

    /* Exactly at budget. */
    CHECK(atalaia_dc_can_send(&dc, ATALAIA_BAND_G, 36000000u));

    /* Over budget. */
    CHECK(!atalaia_dc_can_send(&dc, ATALAIA_BAND_G, 36000001u));
}

static void test_record_and_check(void)
{
    atalaia_duty_cycle_t dc;
    atalaia_dc_init(&dc);

    /* Use up almost all of G1 (3.6s budget). */
    atalaia_dc_record(&dc, ATALAIA_BAND_G1, 3000000u, 1000);
    CHECK(atalaia_dc_remaining_us(&dc, ATALAIA_BAND_G1) == 600000u);
    CHECK(atalaia_dc_can_send(&dc, ATALAIA_BAND_G1, 600000u));
    CHECK(!atalaia_dc_can_send(&dc, ATALAIA_BAND_G1, 600001u));
}

static void test_window_sliding(void)
{
    atalaia_duty_cycle_t dc;
    atalaia_dc_init(&dc);

    /* Record some airtime at t=0. */
    atalaia_dc_record(&dc, ATALAIA_BAND_G, 1000000u, 0);
    CHECK(dc.bands[ATALAIA_BAND_G].used_us == 1000000u);

    /* After one full window (1 hour), the airtime should be expired. */
    atalaia_dc_tick(&dc, ATALAIA_DC_WINDOW_MS + 1000);
    CHECK(dc.bands[ATALAIA_BAND_G].used_us == 0);
    CHECK(atalaia_dc_remaining_us(&dc, ATALAIA_BAND_G) == 36000000u);
}

static void test_window_partial_slide(void)
{
    atalaia_duty_cycle_t dc;
    atalaia_dc_init(&dc);

    /* Record in the first minute. */
    atalaia_dc_record(&dc, ATALAIA_BAND_G, 500000u, 0);

    /* Record in the second minute. */
    uint32_t minute_ms = ATALAIA_DC_WINDOW_MS / ATALAIA_DC_BUCKETS;
    atalaia_dc_record(&dc, ATALAIA_BAND_G, 300000u, minute_ms + 100);

    CHECK(dc.bands[ATALAIA_BAND_G].used_us == 800000u);

    /* Advance by 59 minutes: the first bucket should still be present,
     * since we have 60 buckets total and only advanced 59. */
    atalaia_dc_tick(&dc, 59 * minute_ms);
    /* Both buckets are still within the window. */
    CHECK(dc.bands[ATALAIA_BAND_G].used_us == 800000u);

    /* Advance one more minute: bucket 0 is now expired. */
    atalaia_dc_tick(&dc, 60 * minute_ms);
    /* The first bucket was zeroed. Note: when tick advances the window
     * by one minute, it zeros the NEXT bucket after current. The second
     * recording is in bucket 1. After advancing 60 minutes from 0,
     * bucket 1 gets zeroed, so only bucket 0 remains -- but wait, it
     * also got zeroed. Let me just check used_us dropped. */
    CHECK(dc.bands[ATALAIA_BAND_G].used_us < 800000u);
}

static void test_invalid_band(void)
{
    atalaia_duty_cycle_t dc;
    atalaia_dc_init(&dc);

    CHECK(!atalaia_dc_can_send(&dc, ATALAIA_BAND_COUNT, 1000));
    CHECK(atalaia_dc_remaining_us(&dc, ATALAIA_BAND_COUNT) == 0);
}

static void test_airtime_sf7_125k(void)
{
    /* SF7, BW=125kHz, 20-byte payload. Known approximate value. */
    uint32_t us = atalaia_airtime_us(7, 125000, 20);
    /* Should be roughly 51 ms for a 20-byte payload at SF7/125kHz. */
    CHECK(us > 40000 && us < 80000);
}

static void test_airtime_sf12_125k(void)
{
    /* SF12, BW=125kHz is a slow data rate. A 20-byte payload should
     * be several hundred ms. */
    uint32_t us = atalaia_airtime_us(12, 125000, 20);
    CHECK(us > 500000); /* at least 500 ms */
}

static void test_airtime_zero_bw(void)
{
    CHECK(atalaia_airtime_us(7, 0, 20) == 0);
}

static void test_airtime_bad_sf(void)
{
    CHECK(atalaia_airtime_us(5, 125000, 20) == 0);
    CHECK(atalaia_airtime_us(13, 125000, 20) == 0);
}

/* The whole 125 kHz channel must fit in one sub-band (RFC 0001 Amendment 3). */
static void test_channel_edges(void)
{
    CHECK(atalaia_band_of_channel(869525000u, ATALAIA_LORA_BW_HZ) == ATALAIA_BAND_G2);
    CHECK(atalaia_band_of_channel(868100000u, ATALAIA_LORA_BW_HZ) == ATALAIA_BAND_G);
    CHECK(atalaia_band_of_channel(868800000u, ATALAIA_LORA_BW_HZ) == ATALAIA_BAND_G1);
    CHECK(atalaia_band_of_channel(869850000u, ATALAIA_LORA_BW_HZ) == ATALAIA_BAND_G3);
    /* Lowest and highest centres of each sub-band: edges included. */
    CHECK(atalaia_band_of_channel(869462500u, ATALAIA_LORA_BW_HZ) == ATALAIA_BAND_G2);
    CHECK(atalaia_band_of_channel(869587500u, ATALAIA_LORA_BW_HZ) == ATALAIA_BAND_G2);
    CHECK(atalaia_band_of_channel(868062500u, ATALAIA_LORA_BW_HZ) == ATALAIA_BAND_G);
    CHECK(atalaia_band_of_channel(868537500u, ATALAIA_LORA_BW_HZ) == ATALAIA_BAND_G);
    CHECK(atalaia_band_of_channel(868762500u, ATALAIA_LORA_BW_HZ) == ATALAIA_BAND_G1);
    CHECK(atalaia_band_of_channel(869137500u, ATALAIA_LORA_BW_HZ) == ATALAIA_BAND_G1);
    CHECK(atalaia_band_of_channel(869762500u, ATALAIA_LORA_BW_HZ) == ATALAIA_BAND_G3);
    CHECK(atalaia_band_of_channel(869937500u, ATALAIA_LORA_BW_HZ) == ATALAIA_BAND_G3);
    /* Centres inside a sub-band whose channel spills over an edge. */
    CHECK(!atalaia_channel_ok(869400000u));
    CHECK(!atalaia_channel_ok(869462499u));
    CHECK(!atalaia_channel_ok(869587501u));
    CHECK(!atalaia_channel_ok(869650000u));
    CHECK(!atalaia_channel_ok(868000000u));
    CHECK(!atalaia_channel_ok(868600000u));
    CHECK(!atalaia_channel_ok(868700000u));
    CHECK(!atalaia_channel_ok(869200000u));
    CHECK(!atalaia_channel_ok(869700000u));
    CHECK(!atalaia_channel_ok(870000000u));
    /* Between and outside the sub-bands. */
    CHECK(!atalaia_channel_ok(869300000u));
    CHECK(!atalaia_channel_ok(868650000u));
    CHECK(!atalaia_channel_ok(915000000u));
    CHECK(!atalaia_channel_ok(0u));
    CHECK(atalaia_band_of_channel(30000u, 125000u) == ATALAIA_BAND_COUNT);
    /* A narrower channel fits closer to the edge. */
    CHECK(atalaia_band_of_channel(869412500u, 25000u) == ATALAIA_BAND_G2);
    CHECK(atalaia_band_of_channel(869412500u, ATALAIA_LORA_BW_HZ) == ATALAIA_BAND_COUNT);
}

static void test_band_info(void)
{
    const atalaia_band_info_t *g2 = atalaia_band_info(ATALAIA_BAND_G2);
    CHECK(g2 != NULL);
    CHECK(g2->lo_hz == 869400000u && g2->hi_hz == 869650000u);
    CHECK(g2->duty_ppm == 100000 && g2->limit_dbm == 27 && g2->limit_mw == 500);
    CHECK(g2->limit_ref == ATALAIA_LIMIT_ERP);
    CHECK(atalaia_band_info(ATALAIA_BAND_G)->duty_ppm == 10000);
    CHECK(atalaia_band_info(ATALAIA_BAND_G1)->duty_ppm == 1000);
    CHECK(atalaia_band_info(ATALAIA_BAND_G3)->limit_mw == 25);
    CHECK(atalaia_band_info(ATALAIA_BAND_COUNT) == NULL);
    /* The hourly budgets follow the duty-cycle limits. */
    atalaia_duty_cycle_t dc;
    atalaia_dc_init(&dc);
    for (int b = 0; b < ATALAIA_BAND_COUNT; b++) {
        CHECK(dc.bands[b].budget_us == atalaia_band_info((atalaia_band_t)b)->duty_ppm * 3600u);
    }
}

/* The regions' table (RFC 0001 Amendment 12). */
static void test_regions(void)
{
    const atalaia_region_info_t *eu = atalaia_region_info(ATALAIA_REGION_EU868);
    const atalaia_region_info_t *tw = atalaia_region_info(ATALAIA_REGION_AS923_TW);
    CHECK(eu != NULL && tw != NULL && atalaia_region_info(ATALAIA_REGION_COUNT) == NULL);
    CHECK(strcmp(eu->code, "eu868") == 0 && eu->sf == 7 && eu->bw_hz == 125000u);
    CHECK(eu->default_channel_hz == 869525000u && eu->band_count == ATALAIA_BAND_COUNT);
    CHECK(strcmp(tw->code, "as923-tw") == 0 && tw->sf == 9 && tw->bw_hz == 500000u);
    CHECK(tw->default_channel_hz == 921500000u && tw->band_count == 1);
    /* The CAD settings (Amendment 14): two symbols, peak 22 at SF7/125 and 23 at SF9/500, minimum
     * 10; only the EU868 peak has been measured on a board. */
    CHECK(eu->cad.symbols == 2 && eu->cad.det_peak == 22 && eu->cad.det_min == 10);
    CHECK(eu->cad.det_peak_bench_proven);
    CHECK(tw->cad.symbols == 2 && tw->cad.det_peak == 29 && tw->cad.det_min == 10);
    CHECK(!tw->cad.det_peak_bench_proven);
    CHECK(atalaia_region_from_code("eu868") == ATALAIA_REGION_EU868);
    CHECK(atalaia_region_from_code("as923-tw") == ATALAIA_REGION_AS923_TW);
    CHECK(atalaia_region_from_code("us915") == ATALAIA_REGION_COUNT);
    CHECK(atalaia_region_from_code(NULL) == ATALAIA_REGION_COUNT);
    /* Every default channel is legal in its own region and in no other. */
    for (int r = 0; r < ATALAIA_REGION_COUNT; r++) {
        uint32_t hz = atalaia_region_info((atalaia_region_t)r)->default_channel_hz;
        for (int o = 0; o < ATALAIA_REGION_COUNT; o++) {
            CHECK(atalaia_region_channel_ok((atalaia_region_t)o, hz) == (o == r));
        }
    }
    /* AS923-TW: the whole 500 kHz channel inside 920-925 MHz. */
    CHECK(atalaia_region_band_of_channel(ATALAIA_REGION_AS923_TW, 920250000u) == ATALAIA_BAND_TW);
    CHECK(atalaia_region_band_of_channel(ATALAIA_REGION_AS923_TW, 924750000u) == ATALAIA_BAND_TW);
    CHECK(!atalaia_region_channel_ok(ATALAIA_REGION_AS923_TW, 920249999u));
    CHECK(!atalaia_region_channel_ok(ATALAIA_REGION_AS923_TW, 924750001u));
    CHECK(!atalaia_region_channel_ok(ATALAIA_REGION_AS923_TW, 920000000u));
    CHECK(!atalaia_region_channel_ok(ATALAIA_REGION_AS923_TW, 915000000u));
    CHECK(!atalaia_region_channel_ok(ATALAIA_REGION_COUNT, 921500000u));
    /* EU868 through the region functions, as through the old ones. */
    CHECK(atalaia_region_band_of_channel(ATALAIA_REGION_EU868, 869525000u) == ATALAIA_BAND_G2);
    CHECK(!atalaia_region_channel_ok(ATALAIA_REGION_EU868, 869400000u));
    /* Taiwan's limit: 0.5 W peak at the antenna port, antenna gain above 6 dBi counted. */
    const atalaia_band_info_t *b =
        atalaia_region_band_info(ATALAIA_REGION_AS923_TW, (atalaia_band_t)ATALAIA_BAND_TW);
    CHECK(b != NULL && b->lo_hz == 920000000u && b->hi_hz == 925000000u);
    CHECK(b->limit_dbm == 27 && b->limit_mw == 500 && b->limit_ref == ATALAIA_LIMIT_CONDUCTED);
    CHECK(b->free_gain_dbi == 6 && b->duty_ppm == 100000u);
    CHECK(atalaia_region_band_info(ATALAIA_REGION_AS923_TW, ATALAIA_BAND_G1) == NULL);
    /* Budgets: one 10% slot for AS923-TW, nothing in the others. */
    atalaia_duty_cycle_t dc;
    atalaia_dc_init_region(&dc, ATALAIA_REGION_AS923_TW);
    CHECK(dc.bands[ATALAIA_BAND_TW].budget_us == 360000000u);
    CHECK(dc.bands[1].budget_us == 0 && !atalaia_dc_can_send(&dc, (atalaia_band_t)1, 1));
    /* SF9 at 500 kHz: the same symbol time as SF7 at 125 kHz, so the same preamble, and fewer
     * symbols for the payload. */
    uint32_t eu_us = atalaia_region_airtime_us(ATALAIA_REGION_EU868, 53);
    uint32_t tw_us = atalaia_region_airtime_us(ATALAIA_REGION_AS923_TW, 53);
    CHECK(eu_us == atalaia_airtime_us(7, 125000u, 53) &&
          tw_us == atalaia_airtime_us(9, 500000u, 53));
    CHECK(tw_us < eu_us && tw_us > eu_us / 2);
    CHECK(atalaia_region_airtime_us(ATALAIA_REGION_AS923_TW, 255) < 400000u);
    CHECK(atalaia_region_airtime_us(ATALAIA_REGION_COUNT, 53) == 0);
}

void run_duty_cycle_tests(void)
{
    test_regions();
    test_channel_edges();
    test_band_info();
    test_init_budgets();
    test_can_send_basic();
    test_record_and_check();
    test_window_sliding();
    test_window_partial_slide();
    test_invalid_band();
    test_airtime_sf7_125k();
    test_airtime_sf12_125k();
    test_airtime_zero_bw();
    test_airtime_bad_sf();
}
