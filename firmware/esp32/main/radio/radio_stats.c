/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The radio report line (radio_stats.h).
 */
#include "radio_stats.h"

#include <stdio.h>

/* The duty budget as a JSON number: -1 when unknown. */
static long duty_json(uint32_t ms)
{
    return ms == RADIO_STATS_DUTY_UNKNOWN ? -1L : (long)ms;
}

size_t radio_stats_box_line(char *buf, size_t cap, uint32_t t_s, unsigned game, unsigned node,
                            const radio_stats_box_t *s, uint32_t duty_remaining_ms, int final)
{
    if (cap == 0) return 0;
    int n =
        snprintf(buf, cap,
                 "{\"t_s\":%lu,\"game\":%u,\"node\":%u,\"sent\":%lu,\"retries\":%lu,"
                 "\"acked\":%lu,\"expired\":%lu,\"relayed\":%lu,\"relay_skipped\":%lu,"
                 "\"relay_cancelled\":%lu,\"relay_no_slot\":%lu,\"dup\":%lu,"
                 "\"tx_refused\":%lu,\"duty_remaining_ms\":%ld,\"neighbours\":%lu,"
                 "\"rx\":%lu,\"rx_rejected\":%lu,\"states\":%lu,\"hellos\":%lu,"
                 "\"final\":%d}",
                 (unsigned long)t_s, game, node, (unsigned long)s->sent, (unsigned long)s->retries,
                 (unsigned long)s->acked, (unsigned long)s->expired, (unsigned long)s->relayed,
                 (unsigned long)s->relay_skipped, (unsigned long)s->relay_cancelled,
                 (unsigned long)s->relay_no_slot, (unsigned long)s->dup,
                 (unsigned long)s->tx_refused, duty_json(duty_remaining_ms),
                 (unsigned long)s->neighbours, (unsigned long)s->rx, (unsigned long)s->rx_rejected,
                 (unsigned long)s->states, (unsigned long)s->hellos, final ? 1 : 0);
    if (n < 0 || (size_t)n >= cap) {
        buf[0] = '\0';
        return 0;
    }
    return (size_t)n;
}

size_t radio_stats_modem_line(char *buf, size_t cap, uint32_t t_s, unsigned game, unsigned node,
                              const radio_stats_modem_t *s, uint32_t duty_remaining_ms)
{
    if (cap == 0) return 0;
    int n = snprintf(buf, cap,
                     "{\"role\":\"modem\",\"t_s\":%lu,\"game\":%u,\"node\":%u,\"rx_ok\":%lu,"
                     "\"rx_dropped\":%lu,\"rx_auth_fail\":%lu,\"rx_dupes\":%lu,\"tx_ok\":%lu,"
                     "\"tx_fail\":%lu,\"field_rx\":%lu,\"field_tx\":%lu,"
                     "\"duty_remaining_ms\":%ld}",
                     (unsigned long)t_s, game, node, (unsigned long)s->rx_ok,
                     (unsigned long)s->rx_dropped, (unsigned long)s->rx_auth_fail,
                     (unsigned long)s->rx_dupes, (unsigned long)s->tx_ok, (unsigned long)s->tx_fail,
                     (unsigned long)s->field_rx, (unsigned long)s->field_tx,
                     duty_json(duty_remaining_ms));
    if (n < 0 || (size_t)n >= cap) {
        buf[0] = '\0';
        return 0;
    }
    return (size_t)n;
}
