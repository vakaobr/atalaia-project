/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The target module's hit detector (draft RFC "The expansion port", section 3 (a), EXP-10): one
 * piezo channel's ADC samples in, hits out. Portable C, no SDK calls: the RP2040's ADC and DMA
 * hand it blocks of samples (main.c), the host tests hand it made-up plates.
 *
 *   - a hit starts when a sample rises above the threshold (CONFIG parameter 1, ADC counts of
 *     4095; PEAK_THRESHOLD_DEFAULT until the box sets another);
 *   - its peak is the highest sample in the PEAK_WINDOW_MS that follow; its strength is the
 *     peak scaled from the threshold (1) to full scale (255);
 *   - after the window, a hold-off (CONFIG parameter 2, ms; PEAK_HOLDOFF_DEFAULT_MS) during which
 *     nothing starts, against a ringing steel plate; it lasts until the signal has also stayed
 *     under the threshold for PEAK_QUIET_MS;
 *   - its time is its first sample's (the event's age in STATUS is counted from it).
 *
 * The scale and the defaults are first guesses, to be fixed on real plates at the bench (the
 * RFC's bench test 8, HW2).
 */
#ifndef ATALAIA_TARGET_PEAK_H
#define ATALAIA_TARGET_PEAK_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define PEAK_FULL_SCALE         4095u /* the RP2040's 12-bit ADC */
#define PEAK_THRESHOLD_DEFAULT  300u  /* about 0.24 V at the ADC pin */
#define PEAK_HOLDOFF_DEFAULT_MS 50u   /* the RFC's default */
#define PEAK_WINDOW_MS          2u    /* a hit's peak is looked for this long after it starts */
#define PEAK_QUIET_MS           5u /* the hold-off ends only after this long under the threshold */

typedef struct {
    uint16_t threshold;  /* 1 to 4094 (others are clamped) */
    uint16_t holdoff_ms; /* 0 to 65535 */
    /* state */
    bool in_hit;
    uint32_t hit_start; /* the sample count when it started */
    uint16_t peak;
    bool holding;
    uint32_t hold_until; /* the sample count the hold-off ends at */
    uint32_t samples;    /* samples seen since peak_init */
    uint32_t rate_hz;
} peak_t;

typedef struct {
    uint32_t sample; /* the sample count the hit started at */
    uint8_t strength;
} peak_hit_t;

/* A detector for samples arriving at rate_hz (20000 on the target module). */
void peak_init(peak_t *p, uint32_t rate_hz, uint16_t threshold, uint16_t holdoff_ms);

/* The box's CONFIG: new threshold and hold-off (from the next sample on). */
void peak_config(peak_t *p, uint16_t threshold, uint16_t holdoff_ms);

/* One sample; true (and *hit) when a hit's window has just ended. */
bool peak_sample(peak_t *p, uint16_t sample, peak_hit_t *hit);

/* A block of samples, calling found(ctx, hit) for each hit; the number of hits. */
int peak_block(peak_t *p, const uint16_t *samples, size_t n,
               void (*found)(void *ctx, const peak_hit_t *hit), void *ctx);

/* A peak scaled to a strength: 1 at the threshold, 255 at full scale. */
uint8_t peak_strength(uint16_t peak, uint16_t threshold);

#endif /* ATALAIA_TARGET_PEAK_H */
