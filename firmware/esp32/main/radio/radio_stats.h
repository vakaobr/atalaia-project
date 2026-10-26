/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The one-line radio report of the field test (decision SL-18): a box and the modem each
 * log, once a minute, a JSON object on one line that tools/bench_radio_log.py reads.
 * Platform-free, no heap: the caller gives the buffer (RADIO_STATS_LINE_MAX is enough for
 * every field at its widest). Reading counters and formatting them changes nothing the
 * radio does.
 *
 *   I (123456) radio_stats: {"t_s":120,"game":4243,"node":7,"sent":9,...}
 *
 * The log tag is RADIO_STATS_TAG; the shell adds the "I (ms) tag: " prefix.
 */
#ifndef ATALAIA_RADIO_STATS_H
#define ATALAIA_RADIO_STATS_H

#include <stddef.h>
#include <stdint.h>

#define RADIO_STATS_TAG       "radio_stats"
#define RADIO_STATS_LINE_MAX  512
#define RADIO_STATS_PERIOD_MS 60000u
/* duty_remaining_ms when the shell cannot say (the line then carries -1). */
#define RADIO_STATS_DUTY_UNKNOWN 0xFFFFFFFFu

/* A box's counters since its link came up (field_link_stats_t, plus the neighbour count). */
typedef struct {
    uint32_t sent, retries, acked, expired; /* events: first sends, resends, ... */
    uint32_t relayed, relay_skipped, relay_cancelled, relay_no_slot;
    uint32_t dup, tx_refused; /* duplicates heard, duty-cycle refusals */
    uint32_t rx, rx_rejected, states, hellos;
    uint32_t neighbours; /* boxes heard in the last 10 minutes */
} radio_stats_box_t;

/* The modem's counters (modem_counters_t). */
typedef struct {
    uint32_t rx_ok, rx_dropped, rx_auth_fail, rx_dupes;
    uint32_t tx_ok, tx_fail, field_rx, field_tx;
} radio_stats_modem_t;

/*
 * Writes one box line (no newline) to buf: {"t_s","game","node","sent","retries","acked",
 * "expired","relayed","relay_skipped","relay_cancelled","relay_no_slot","dup","tx_refused",
 * "duty_remaining_ms","neighbours","rx","rx_rejected","states","hellos","final"}. t_s is the
 * box's uptime in seconds; final is 1 on the line that closes a game. Returns the length, or 0
 * if cap is too small (buf then holds an empty string).
 */
size_t radio_stats_box_line(char *buf, size_t cap, uint32_t t_s, unsigned game, unsigned node,
                            const radio_stats_box_t *s, uint32_t duty_remaining_ms, int final);

/* Writes one modem line: {"role":"modem","t_s","game","node","rx_ok","rx_dropped",
 * "rx_auth_fail","rx_dupes","tx_ok","tx_fail","field_rx","field_tx","duty_remaining_ms"}. */
size_t radio_stats_modem_line(char *buf, size_t cap, uint32_t t_s, unsigned game, unsigned node,
                              const radio_stats_modem_t *s, uint32_t duty_remaining_ms);

#endif
