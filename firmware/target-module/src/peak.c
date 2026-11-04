/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The target module's hit detector (peak.h).
 */
#include "peak.h"

#include <string.h>

static uint16_t clamp_threshold(uint16_t t)
{
    if (t < 1u) return 1u;
    if (t >= PEAK_FULL_SCALE) return (uint16_t)(PEAK_FULL_SCALE - 1u);
    return t;
}

void peak_init(peak_t *p, uint32_t rate_hz, uint16_t threshold, uint16_t holdoff_ms)
{
    memset(p, 0, sizeof(*p));
    p->rate_hz = rate_hz ? rate_hz : 1u;
    peak_config(p, threshold, holdoff_ms);
}

void peak_config(peak_t *p, uint16_t threshold, uint16_t holdoff_ms)
{
    p->threshold = clamp_threshold(threshold);
    p->holdoff_ms = holdoff_ms;
}

uint8_t peak_strength(uint16_t peak, uint16_t threshold)
{
    threshold = clamp_threshold(threshold);
    if (peak <= threshold) return 1u;
    if (peak >= PEAK_FULL_SCALE) return 255u;
    uint32_t span = PEAK_FULL_SCALE - threshold;
    uint32_t s = 1u + ((uint32_t)(peak - threshold) * 254u + span / 2u) / span;
    return (uint8_t)(s > 255u ? 255u : s);
}

static uint32_t ms_to_samples(const peak_t *p, uint32_t ms)
{
    return (uint32_t)(((uint64_t)ms * p->rate_hz + 999u) / 1000u);
}

bool peak_sample(peak_t *p, uint16_t sample, peak_hit_t *hit)
{
    uint32_t n = p->samples++;
    bool above = sample > p->threshold;
    if (p->in_hit) {
        if (sample > p->peak) p->peak = sample;
        if (n - p->hit_start + 1u >= ms_to_samples(p, PEAK_WINDOW_MS)) {
            p->in_hit = false;
            p->holding = true;
            p->hold_until = n + 1u + ms_to_samples(p, p->holdoff_ms);
            if (hit != NULL) {
                hit->sample = p->hit_start;
                hit->strength = peak_strength(p->peak, p->threshold);
            }
            return true;
        }
        return false;
    }
    if (p->holding) {
        /* The hold-off ends once its time is over and the plate has been quiet (no sample above
         * the threshold) for PEAK_QUIET_MS: a ringing plate keeps it going. */
        uint32_t quiet_end = n + ms_to_samples(p, PEAK_QUIET_MS);
        if (above && (int32_t)(quiet_end - p->hold_until) > 0) p->hold_until = quiet_end;
        if ((int32_t)(n - p->hold_until) >= 0) p->holding = false;
        return false;
    }
    if (above) {
        p->in_hit = true;
        p->hit_start = n;
        p->peak = sample;
    }
    return false;
}

int peak_block(peak_t *p, const uint16_t *samples, size_t n,
               void (*found)(void *ctx, const peak_hit_t *hit), void *ctx)
{
    int hits = 0;
    for (size_t i = 0; i < n; i++) {
        peak_hit_t h;
        if (peak_sample(p, samples[i], &h)) {
            hits++;
            if (found != NULL) found(ctx, &h);
        }
    }
    return hits;
}
