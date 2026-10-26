/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#include "lbt_stats.h"

#include <stdlib.h>
#include <string.h>

void lbt_stats_init(lbt_stats_t *s)
{
    memset(s, 0, sizeof(*s));
}

void lbt_stats_probe(lbt_stats_t *s, uint32_t t_us, hal_busy_why_t why, uint32_t cad_us,
                     uint32_t rearm_us)
{
    if (cad_us > 0) {
        if (s->cad_n == 0 || cad_us < s->cad_min_us) s->cad_min_us = cad_us;
        if (cad_us > s->cad_max_us) s->cad_max_us = cad_us;
        s->cad_n++;
        s->cad_sum_us += cad_us;
    }
    if (rearm_us > 0) {
        if (rearm_us > s->rearm_max_us) s->rearm_max_us = rearm_us;
        s->rearm_n++;
        s->rearm_sum_us += rearm_us;
    }
    if (s->pending_n >= LBT_PENDING_MAX) {
        s->dropped++;
        return;
    }
    s->pending[s->pending_n].t_us = t_us;
    s->pending[s->pending_n].why = (uint8_t)why;
    s->pending_n++;
}

static bool is_busy(uint8_t why)
{
    return why == HAL_BUSY_CAD || why == HAL_BUSY_PREAMBLE || why == HAL_BUSY_HEADER;
}

void lbt_stats_frame(lbt_stats_t *s, uint32_t end_us, uint32_t airtime_us, uint32_t sym_us,
                     uint32_t lost_before)
{
    uint32_t start_us = end_us - airtime_us;
    size_t keep = 0;
    for (size_t i = 0; i < s->pending_n; i++) {
        lbt_probe_t p = s->pending[i];
        if ((int32_t)(p.t_us - end_us) > 0) { /* after this frame: judged by the next */
            s->pending[keep++] = p;
            continue;
        }
        if (p.why == HAL_BUSY_ERROR) {
            s->err_n++;
            continue;
        }
        if ((int32_t)(p.t_us - start_us) < 0) {
            /* Before the frame: outside every frame, unless a frame was lost since the last one
             * (or this is the first frame heard) and this probe may have been inside it. */
            if (lost_before > 0 || !s->have_prev_end) {
                s->amb_n++;
            } else {
                s->out_n++;
                if (is_busy(p.why)) s->out_busy++;
            }
            continue;
        }
        uint32_t off = p.t_us - start_us;
        uint32_t d = airtime_us ? (uint32_t)((uint64_t)off * LBT_DECILES / airtime_us) : 0;
        if (d >= LBT_DECILES) d = LBT_DECILES - 1;
        /* Preamble 8 + sync 4.25 symbols = 12.25; the header takes the next 8. */
        uint32_t seg = off < sym_us * 49 / 4   ? LBT_SEG_PREAMBLE
                       : off < sym_us * 81 / 4 ? LBT_SEG_HEADER
                                               : LBT_SEG_PAYLOAD;
        bool hit = is_busy(p.why);
        s->in_n[d]++;
        s->seg_n[seg]++;
        if (hit) {
            s->in_hit[d]++;
            s->seg_hit[seg]++;
            if (p.why == HAL_BUSY_CAD)
                s->hit_cad++;
            else if (p.why == HAL_BUSY_PREAMBLE)
                s->hit_preamble++;
            else
                s->hit_header++;
        }
    }
    s->pending_n = keep;
    s->have_prev_end = true;
    s->prev_end_us = end_us;
    s->frames++;
    s->frames_lost += lost_before;
}

uint32_t lbt_stats_in_total(const lbt_stats_t *s)
{
    uint32_t n = 0;
    for (int i = 0; i < LBT_DECILES; i++) n += s->in_n[i];
    return n;
}

uint32_t lbt_stats_hit_total(const lbt_stats_t *s)
{
    uint32_t n = 0;
    for (int i = 0; i < LBT_DECILES; i++) n += s->in_hit[i];
    return n;
}

uint32_t lbt_permille(uint32_t a, uint32_t b)
{
    return b == 0 ? 0 : (uint32_t)(((uint64_t)a * 1000 + b / 2) / b);
}

/* One unsigned number from *p (decimal, 1..max), advancing p past it and any spaces. */
static bool next_number(const char **p, uint32_t max, uint32_t *out)
{
    char *end;
    while (**p == ' ') (*p)++;
    if (**p < '0' || **p > '9') return false;
    unsigned long v = strtoul(*p, &end, 10);
    if (v == 0 || v > max) return false;
    *out = (uint32_t)v;
    *p = end;
    while (**p == ' ') (*p)++;
    return true;
}

bool lbt_parse_cmd(const char *args, lbt_cmd_t *out)
{
    memset(out, 0, sizeof(*out));
    if (args == NULL) return false;
    while (*args == ' ') args++;
    const char *p;
    if (strncmp(args, "tx", 2) == 0 && (args[2] == 0 || args[2] == ' ')) {
        out->kind = LBT_CMD_TX;
        p = args + 2;
        out->frames = LBT_FRAMES_DEFAULT;
        if (*p && !next_number(&p, LBT_TX_FRAMES_MAX, &out->frames)) goto bad;
    } else if (strncmp(args, "probe", 5) == 0 && (args[5] == 0 || args[5] == ' ')) {
        out->kind = LBT_CMD_PROBE;
        p = args + 5;
        out->frames = LBT_FRAMES_DEFAULT;
        out->gap_min_us = LBT_GAP_MIN_US_DEFAULT;
        out->gap_max_us = LBT_GAP_MAX_US_DEFAULT;
        if (*p) {
            if (!next_number(&p, LBT_PROBE_FRAMES_MAX, &out->frames)) goto bad;
            if (*p) {
                if (!next_number(&p, 100000, &out->gap_min_us) ||
                    !next_number(&p, 100000, &out->gap_max_us) ||
                    out->gap_max_us < out->gap_min_us) {
                    goto bad;
                }
            }
        }
    } else if (strcmp(args, "stop") == 0) {
        out->kind = LBT_CMD_STOP;
        return true;
    } else if (strcmp(args, "status") == 0) {
        out->kind = LBT_CMD_STATUS;
        return true;
    } else {
        return false;
    }
    if (*p != 0) goto bad; /* trailing words */
    return true;
bad:
    memset(out, 0, sizeof(*out));
    return false;
}

uint32_t lbt_rand(uint32_t *state)
{
    uint32_t x = *state ? *state : 0x9E3779B9u;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    *state = x;
    return x;
}

uint32_t lbt_rand_range(uint32_t *state, uint32_t lo, uint32_t hi)
{
    if (hi <= lo) return lo;
    return lo + lbt_rand(state) % (hi - lo + 1);
}

bool lbt_frame_build(uint8_t *buf, size_t len, uint32_t seq, uint32_t *rng)
{
    if (len < LBT_FRAME_MIN || len > 255) return false;
    buf[0] = 'L';
    buf[1] = 'B';
    buf[2] = 'T';
    buf[3] = '1';
    for (int i = 0; i < 4; i++) buf[4 + i] = (uint8_t)(seq >> (8 * i));
    for (size_t i = LBT_FRAME_MIN; i < len; i++) buf[i] = (uint8_t)lbt_rand(rng);
    return true;
}

bool lbt_frame_parse(const uint8_t *buf, size_t len, uint32_t *seq)
{
    if (len < LBT_FRAME_MIN || memcmp(buf, "LBT1", 4) != 0) return false;
    *seq =
        (uint32_t)buf[4] | (uint32_t)buf[5] << 8 | (uint32_t)buf[6] << 16 | (uint32_t)buf[7] << 24;
    return true;
}
