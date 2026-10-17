/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Controlled flooding with a 64-entry dedupe table (30 s expiry, LRU
 * eviction) and deterministic rebroadcast jitter.
 */
#ifndef ATALAIA_FLOOD_H
#define ATALAIA_FLOOD_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define ATALAIA_DEDUPE_SIZE      64
#define ATALAIA_DEDUPE_EXPIRY_MS 30000
#define ATALAIA_JITTER_MIN_MS    10
#define ATALAIA_JITTER_MAX_MS    50

typedef struct {
    uint16_t source;
    uint16_t seq;
    uint32_t seen_at_ms;
} atalaia_dedupe_entry_t;

typedef struct {
    atalaia_dedupe_entry_t entries[ATALAIA_DEDUPE_SIZE];
    size_t count;
} atalaia_dedupe_t;

/*
 * Initialises the dedupe table. Must be called before any other function.
 */
void atalaia_dedupe_init(atalaia_dedupe_t *d);

/*
 * Returns true if (source, seq) has been seen within the expiry window.
 * If not, inserts the pair. Expired entries are reaped first; if the
 * table is still full, the oldest entry is evicted (LRU).
 */
bool atalaia_dedupe_seen(atalaia_dedupe_t *d, uint16_t source, uint16_t seq, uint32_t now_ms);

/*
 * Returns true if the packet should be relayed (hop_limit > 0 after
 * clamping to max_hops and decrementing). Sets *new_hop_limit.
 */
bool atalaia_flood_should_relay(uint8_t hop_limit, uint8_t max_hops, uint8_t *new_hop_limit);

/*
 * Deterministic jitter in [JITTER_MIN, JITTER_MAX] ms, derived from
 * (source, seq) so every node picks a different delay.
 */
uint32_t atalaia_flood_jitter_ms(uint16_t source, uint16_t seq);

#endif /* ATALAIA_FLOOD_H */
