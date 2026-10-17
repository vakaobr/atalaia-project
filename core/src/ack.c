/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * ACK tracker implementation.
 */
#include <string.h>

#include "atalaia/ack.h"
#include "atalaia/protocol.h" /* for ATALAIA_PRIO_TELEMETRY */

void atalaia_ack_init(atalaia_ack_tracker_t *t)
{
    memset(t, 0, sizeof(*t));
}

bool atalaia_ack_register(atalaia_ack_tracker_t *t, uint16_t source, uint16_t seq, uint8_t priority,
                          uint32_t now_ms)
{
    if (t->count >= ATALAIA_ACK_QUEUE_SIZE) {
        return false;
    }

    atalaia_ack_entry_t *e = &t->entries[t->count];
    e->source = source;
    e->seq = seq;
    e->priority = priority;
    e->retries = 0;

    /* Telemetry is best-effort: mark confirmed immediately. */
    if (priority == ATALAIA_PRIO_TELEMETRY) {
        e->status = ATALAIA_ACK_CONFIRMED;
        e->next_retry_ms = 0;
    } else {
        e->status = ATALAIA_ACK_PENDING;
        e->next_retry_ms = now_ms + ATALAIA_ACK_RETRY_MS;
    }

    t->count++;
    return true;
}

void atalaia_ack_confirm(atalaia_ack_tracker_t *t, uint16_t source, uint16_t seq)
{
    for (size_t i = 0; i < t->count; i++) {
        if (t->entries[i].source == source && t->entries[i].seq == seq) {
            t->entries[i].status = ATALAIA_ACK_CONFIRMED;
            return;
        }
    }
}

void atalaia_ack_confirm_cumulative(atalaia_ack_tracker_t *t, uint16_t source, uint16_t up_to_seq)
{
    for (size_t i = 0; i < t->count; i++) {
        if (t->entries[i].source == source && t->entries[i].seq <= up_to_seq) {
            t->entries[i].status = ATALAIA_ACK_CONFIRMED;
        }
    }
}

size_t atalaia_ack_get_retries(atalaia_ack_tracker_t *t, uint32_t now_ms,
                               atalaia_ack_entry_t *retries, size_t max_count)
{
    size_t found = 0;
    for (size_t i = 0; i < t->count && found < max_count; i++) {
        atalaia_ack_entry_t *e = &t->entries[i];
        if (e->status == ATALAIA_ACK_PENDING && now_ms >= e->next_retry_ms) {
            retries[found] = *e;
            found++;
        }
    }
    return found;
}

void atalaia_ack_tick(atalaia_ack_tracker_t *t, uint32_t now_ms)
{
    for (size_t i = 0; i < t->count; i++) {
        atalaia_ack_entry_t *e = &t->entries[i];
        if (e->status != ATALAIA_ACK_PENDING) {
            continue;
        }
        if (now_ms < e->next_retry_ms) {
            continue;
        }
        e->retries++;
        if (e->retries >= ATALAIA_ACK_MAX_RETRIES) {
            e->status = ATALAIA_ACK_EXPIRED;
        } else {
            e->next_retry_ms = now_ms + ATALAIA_ACK_RETRY_MS;
        }
    }
}
