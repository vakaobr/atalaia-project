/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The bench test of listen-before-talk's gate (decision SL-25, docs/runbooks/lbt-bench-gate.md):
 * the arithmetic, apart from the radio so that it is host-tested. A transmitter board sends frames
 * of a real STATE's length; a prober board calls channel_busy() every few milliseconds and
 * receives them. A frame's time on air is known only when it ends (RxDone, whose time and the
 * frame's airtime give [start, end]), so the probes wait in a list and are classified when the
 * frame arrives: inside the frame, a hit if the channel was found busy, by tenth of the frame and
 * by part (preamble, header, payload); outside every frame, busy is a false busy. A frame the
 * prober did not receive (a gap in the sequence numbers) leaves a stretch whose probes cannot be
 * placed: they are counted apart and judge nothing.
 *
 * Times are 32-bit microseconds (esp_timer's low half; a difference is taken as signed).
 */
#ifndef ATALAIA_LBT_STATS_H
#define ATALAIA_LBT_STATS_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "hal/hal_radio.h"

#define LBT_PENDING_MAX 1024
#define LBT_DECILES     10
/* The bench frame: "LBT1", the sequence number, then filler. The shortest is the header. */
#define LBT_FRAME_MIN 8
/* A real STATE's length (RFC 0001): the transmitter picks one in this range. */
#define LBT_STATE_LEN_MIN 48
#define LBT_STATE_LEN_MAX 56
/* The pause between a frame's end and the next: random, in this range. */
#define LBT_TX_GAP_MIN_MS 300
#define LBT_TX_GAP_MAX_MS 700

/* A summary after this many frames. */
#define LBT_SUMMARY_EVERY 25
/* The console commands' limits. */
#define LBT_TX_FRAMES_MAX      1000 /* about 90 s of air: 2.5 % of an hour */
#define LBT_PROBE_FRAMES_MAX   5000
#define LBT_FRAMES_DEFAULT     300
#define LBT_GAP_MIN_US_DEFAULT 2000
#define LBT_GAP_MAX_US_DEFAULT 5000

typedef enum {
    LBT_SEG_PREAMBLE = 0,
    LBT_SEG_HEADER = 1,
    LBT_SEG_PAYLOAD = 2,
    LBT_SEGS = 3
} lbt_seg_t;

typedef struct {
    uint32_t t_us;
    uint8_t why; /* hal_busy_why_t */
} lbt_probe_t;

typedef struct {
    lbt_probe_t pending[LBT_PENDING_MAX];
    size_t pending_n;
    uint32_t dropped; /* probes that did not fit in the list */
    bool have_prev_end;
    uint32_t prev_end_us;

    uint32_t frames;
    uint32_t frames_lost; /* from gaps in the sequence numbers */
    uint32_t in_n[LBT_DECILES], in_hit[LBT_DECILES];
    uint32_t seg_n[LBT_SEGS], seg_hit[LBT_SEGS];
    uint32_t hit_cad, hit_preamble, hit_header; /* in-frame hits, by why */
    uint32_t out_n, out_busy;                   /* outside every frame; busy there = false busy */
    uint32_t amb_n;                             /* in a stretch where a frame was lost */
    uint32_t err_n;                             /* probes the radio did not answer */

    uint32_t cad_n;
    uint64_t cad_sum_us;
    uint32_t cad_min_us, cad_max_us;
    uint32_t rearm_n;
    uint64_t rearm_sum_us;
    uint32_t rearm_max_us;
} lbt_stats_t;

void lbt_stats_init(lbt_stats_t *s);

/* One probe's outcome and, when a CAD ran / the receiver was re-armed, how long they took. */
void lbt_stats_probe(lbt_stats_t *s, uint32_t t_us, hal_busy_why_t why, uint32_t cad_us,
                     uint32_t rearm_us);

/*
 * A received frame: it ended at end_us and took airtime_us; sym_us is a symbol (2^SF / BW);
 * lost_before is how many frames the sequence numbers say were sent since the last one received.
 * Classifies every waiting probe up to end_us.
 */
void lbt_stats_frame(lbt_stats_t *s, uint32_t end_us, uint32_t airtime_us, uint32_t sym_us,
                     uint32_t lost_before);

/* Totals: probes inside frames and hits among them. */
uint32_t lbt_stats_in_total(const lbt_stats_t *s);
uint32_t lbt_stats_hit_total(const lbt_stats_t *s);

/* a * 1000 / b rounded (per mille), 0 when b is 0. */
uint32_t lbt_permille(uint32_t a, uint32_t b);

/* ---- the console command ("tx 300", "probe 300 2000 5000", "stop", "status") ---- */

typedef enum {
    LBT_CMD_BAD = 0,
    LBT_CMD_TX,
    LBT_CMD_PROBE,
    LBT_CMD_STOP,
    LBT_CMD_STATUS
} lbt_cmd_kind_t;

typedef struct {
    lbt_cmd_kind_t kind;
    uint32_t frames;
    uint32_t gap_min_us, gap_max_us; /* probe: the gap between two probes' starts */
    /* "proxy=as923": the AS923-TW modulation on 868.3 MHz (lbt_profile.h). The options below
     * mean something only with it: peak= / min= (-1: the region table's), power= (dBm
     * conducted, INT8_MIN: the proxy's default). */
    bool proxy;
    int det_peak, det_min, power_dbm;
} lbt_cmd_t;

/* Parses what follows "@lbt ": "tx|probe [numbers] [proxy=as923 [peak=N] [min=N] [power=dBm]]",
 * "stop", "status". False (and kind BAD) if it is not one of them or a number is out of range
 * (with the proxy, tx frames are capped by its duty budget, lbt_profile_frames_max). */
bool lbt_parse_cmd(const char *args, lbt_cmd_t *out);

/* ---- the bench frame and the random numbers ---- */

/* xorshift32: nonzero state in, next value out. */
uint32_t lbt_rand(uint32_t *state);
uint32_t lbt_rand_range(uint32_t *state, uint32_t lo, uint32_t hi); /* lo..hi inclusive */

/* Builds a frame of len bytes (LBT_FRAME_MIN..255) carrying seq. */
bool lbt_frame_build(uint8_t *buf, size_t len, uint32_t seq, uint32_t *rng);
/* True if buf is a bench frame; its sequence number in *seq. */
bool lbt_frame_parse(const uint8_t *buf, size_t len, uint32_t *seq);

#endif /* ATALAIA_LBT_STATS_H */
