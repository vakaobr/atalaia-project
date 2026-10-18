/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Noise measurement on one channel (the USB modem's MEASURE command,
 * protocol/usb-modem.md): instantaneous RSSI samples taken while the
 * radio listens, summarised as minimum, mean, median, 90th percentile and
 * maximum in dBm, plus how many channel-activity detections (CAD: a LoRa
 * preamble on the channel) out of how many tries found something.
 *
 * The samples go into a 1 dB histogram, so a long dwell needs no sample
 * buffer. Plain C, no ESP-IDF dependency: host-tested, and shared by the
 * SX1262 HAL and the host modem.
 */
#ifndef ATALAIA_NOISE_STATS_H
#define ATALAIA_NOISE_STATS_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Readings below and above are counted at the ends (the SX1262 reads -127.5 to 0). */
#define NOISE_DBM_MIN (-128)
#define NOISE_DBM_MAX 0
#define NOISE_BINS    (NOISE_DBM_MAX - NOISE_DBM_MIN + 1)

/* Shortest and longest dwell one MEASURE command may ask for. */
#define NOISE_DWELL_MIN_MS 10u
#define NOISE_DWELL_MAX_MS 10000u

/* Bytes of a NOISE frame's payload (noise_result_encode). */
#define NOISE_RESULT_LEN 17

typedef struct {
    uint32_t hist[NOISE_BINS];
    uint32_t samples;
    int64_t sum_dbm;
    uint16_t cad_tries;
    uint16_t cad_detected;
} noise_acc_t;

typedef struct {
    uint32_t channel_hz;
    uint16_t dwell_ms;
    uint16_t samples; /* saturates at 65535 */
    int8_t min_dbm;
    int8_t mean_dbm; /* arithmetic mean of the dBm readings, rounded */
    int8_t p50_dbm;
    int8_t p90_dbm;
    int8_t max_dbm;
    uint16_t cad_tries;
    uint16_t cad_detected;
} noise_result_t;

void noise_acc_init(noise_acc_t *a);

/* One RSSI reading in dBm (clamped to NOISE_DBM_MIN..NOISE_DBM_MAX). */
void noise_acc_add(noise_acc_t *a, int rssi_dbm);

/* One CAD try and whether it detected LoRa activity. */
void noise_acc_cad(noise_acc_t *a, bool detected);

/*
 * The summary. Returns false (and fills nothing but channel and dwell)
 * when there were no RSSI samples.
 */
bool noise_acc_finish(const noise_acc_t *a, uint32_t channel_hz, uint16_t dwell_ms,
                      noise_result_t *out);

/*
 * The NOISE frame payload, all big-endian: channel_hz u32, dwell_ms u16,
 * samples u16, min i8, mean i8, p50 i8, p90 i8, max i8, cad_tries u16,
 * cad_detected u16. Returns NOISE_RESULT_LEN, or 0 if cap is too small.
 */
size_t noise_result_encode(const noise_result_t *r, uint8_t *buf, size_t cap);

#endif /* ATALAIA_NOISE_STATS_H */
