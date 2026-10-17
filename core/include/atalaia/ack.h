/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * ACK tracker with per-priority behaviour: critical packets are retried
 * until acknowledged, normal packets are ACK'd once, and telemetry
 * packets are best-effort (no ACK expected).
 */
#ifndef ATALAIA_ACK_H
#define ATALAIA_ACK_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define ATALAIA_ACK_QUEUE_SIZE  32
#define ATALAIA_ACK_RETRY_MS    3000
#define ATALAIA_ACK_MAX_RETRIES 10

typedef enum {
    ATALAIA_ACK_PENDING,
    ATALAIA_ACK_CONFIRMED,
    ATALAIA_ACK_EXPIRED
} atalaia_ack_status_t;

typedef struct {
    uint16_t source;
    uint16_t seq;
    uint8_t priority; /* atalaia_prio_t value */
    uint8_t retries;
    uint32_t next_retry_ms;
    atalaia_ack_status_t status;
} atalaia_ack_entry_t;

typedef struct {
    atalaia_ack_entry_t entries[ATALAIA_ACK_QUEUE_SIZE];
    size_t count;
} atalaia_ack_tracker_t;

void atalaia_ack_init(atalaia_ack_tracker_t *t);

/*
 * Registers a sent packet. Telemetry (priority 0) is immediately marked
 * CONFIRMED. Returns false if the queue is full.
 */
bool atalaia_ack_register(atalaia_ack_tracker_t *t, uint16_t source, uint16_t seq, uint8_t priority,
                          uint32_t now_ms);

/* Confirms receipt of a specific (source, seq). */
void atalaia_ack_confirm(atalaia_ack_tracker_t *t, uint16_t source, uint16_t seq);

/* Confirms all entries from source with seq <= up_to_seq. */
void atalaia_ack_confirm_cumulative(atalaia_ack_tracker_t *t, uint16_t source, uint16_t up_to_seq);

/*
 * Returns entries that are PENDING and past their next_retry_ms. Fills
 * retries[] with up to max_count entries. Returns the number filled.
 */
size_t atalaia_ack_get_retries(atalaia_ack_tracker_t *t, uint32_t now_ms,
                               atalaia_ack_entry_t *retries, size_t max_count);

/*
 * Advances the tracker: increments retry counts, schedules next retry,
 * and expires entries that exceeded ATALAIA_ACK_MAX_RETRIES.
 */
void atalaia_ack_tick(atalaia_ack_tracker_t *t, uint32_t now_ms);

#endif /* ATALAIA_ACK_H */
