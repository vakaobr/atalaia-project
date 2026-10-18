/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Noise measurement summary. See noise_stats.h.
 */
#include "noise_stats.h"

#include <string.h>

void noise_acc_init(noise_acc_t *a)
{
    memset(a, 0, sizeof(*a));
}

void noise_acc_add(noise_acc_t *a, int rssi_dbm)
{
    if (rssi_dbm < NOISE_DBM_MIN) rssi_dbm = NOISE_DBM_MIN;
    if (rssi_dbm > NOISE_DBM_MAX) rssi_dbm = NOISE_DBM_MAX;
    a->hist[rssi_dbm - NOISE_DBM_MIN]++;
    a->samples++;
    a->sum_dbm += rssi_dbm;
}

void noise_acc_cad(noise_acc_t *a, bool detected)
{
    if (a->cad_tries == UINT16_MAX) return;
    a->cad_tries++;
    if (detected) a->cad_detected++;
}

/* The smallest reading v with at least ceil(pct * samples / 100) readings <= v. */
static int8_t percentile(const noise_acc_t *a, uint32_t pct)
{
    uint64_t want = ((uint64_t)a->samples * pct + 99u) / 100u;
    if (want == 0) want = 1;
    uint64_t seen = 0;
    for (int i = 0; i < NOISE_BINS; i++) {
        seen += a->hist[i];
        if (seen >= want) return (int8_t)(i + NOISE_DBM_MIN);
    }
    return (int8_t)NOISE_DBM_MAX;
}

bool noise_acc_finish(const noise_acc_t *a, uint32_t channel_hz, uint16_t dwell_ms,
                      noise_result_t *out)
{
    memset(out, 0, sizeof(*out));
    out->channel_hz = channel_hz;
    out->dwell_ms = dwell_ms;
    out->cad_tries = a->cad_tries;
    out->cad_detected = a->cad_detected;
    if (a->samples == 0) return false;
    out->samples = a->samples > UINT16_MAX ? UINT16_MAX : (uint16_t)a->samples;
    out->min_dbm = percentile(a, 0);
    out->p50_dbm = percentile(a, 50);
    out->p90_dbm = percentile(a, 90);
    out->max_dbm = percentile(a, 100);
    /* Rounded to the nearest dB, halves away from zero (the sum is negative). */
    int64_t n = (int64_t)a->samples;
    int64_t s = a->sum_dbm;
    int64_t mean = s >= 0 ? (s + n / 2) / n : -((-s + n / 2) / n);
    out->mean_dbm = (int8_t)mean;
    return true;
}

static void put16(uint8_t *p, uint16_t v)
{
    p[0] = (uint8_t)(v >> 8);
    p[1] = (uint8_t)(v & 0xFF);
}

size_t noise_result_encode(const noise_result_t *r, uint8_t *buf, size_t cap)
{
    if (cap < NOISE_RESULT_LEN) return 0;
    buf[0] = (uint8_t)(r->channel_hz >> 24);
    buf[1] = (uint8_t)(r->channel_hz >> 16);
    buf[2] = (uint8_t)(r->channel_hz >> 8);
    buf[3] = (uint8_t)(r->channel_hz & 0xFF);
    put16(buf + 4, r->dwell_ms);
    put16(buf + 6, r->samples);
    buf[8] = (uint8_t)r->min_dbm;
    buf[9] = (uint8_t)r->mean_dbm;
    buf[10] = (uint8_t)r->p50_dbm;
    buf[11] = (uint8_t)r->p90_dbm;
    buf[12] = (uint8_t)r->max_dbm;
    put16(buf + 13, r->cad_tries);
    put16(buf + 15, r->cad_detected);
    return NOISE_RESULT_LEN;
}
