/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Controlled flooding: dedupe table and rebroadcast jitter.
 */
#include <string.h>

#include "atalaia/flood.h"

void atalaia_dedupe_init(atalaia_dedupe_t *d)
{
    memset(d, 0, sizeof(*d));
}

/*
 * Returns the index of the oldest entry, or (size_t)-1 if the table is
 * empty. Used for LRU eviction.
 */
static size_t find_oldest(const atalaia_dedupe_t *d)
{
    if (d->count == 0) {
        return (size_t)-1;
    }
    size_t oldest = 0;
    for (size_t i = 1; i < d->count; i++) {
        if (d->entries[i].seen_at_ms < d->entries[oldest].seen_at_ms) {
            oldest = i;
        }
    }
    return oldest;
}

/*
 * Expires entries older than ATALAIA_DEDUPE_EXPIRY_MS. Maintains
 * compactness by swapping the last entry into the removed slot.
 */
static void expire(atalaia_dedupe_t *d, uint32_t now_ms)
{
    size_t i = 0;
    while (i < d->count) {
        uint32_t age = now_ms - d->entries[i].seen_at_ms;
        if (age >= ATALAIA_DEDUPE_EXPIRY_MS) {
            d->entries[i] = d->entries[d->count - 1];
            d->count--;
        } else {
            i++;
        }
    }
}

bool atalaia_dedupe_seen(atalaia_dedupe_t *d, uint16_t source, uint16_t seq, uint32_t now_ms)
{
    /* Expire old entries first so stale matches are not found. */
    expire(d, now_ms);

    /* Check if already present and refresh the timestamp. */
    for (size_t i = 0; i < d->count; i++) {
        if (d->entries[i].source == source && d->entries[i].seq == seq) {
            d->entries[i].seen_at_ms = now_ms;
            return true;
        }
    }

    size_t slot;
    if (d->count < ATALAIA_DEDUPE_SIZE) {
        slot = d->count;
        d->count++;
    } else {
        slot = find_oldest(d);
    }
    d->entries[slot].source = source;
    d->entries[slot].seq = seq;
    d->entries[slot].seen_at_ms = now_ms;
    return false;
}

bool atalaia_flood_should_relay(uint8_t hop_limit, uint8_t max_hops, uint8_t *new_hop_limit)
{
    if (hop_limit == 0) {
        *new_hop_limit = 0;
        return false;
    }
    if (hop_limit > max_hops) {
        hop_limit = max_hops;
    }
    *new_hop_limit = hop_limit - 1;
    return *new_hop_limit > 0 || hop_limit == 1;
    /* hop_limit==1: relay once more with new_hop_limit==0 means the
     * receiver won't relay again. We do relay it (true), but with 0. */
}

uint32_t atalaia_flood_jitter_ms(uint16_t source, uint16_t seq)
{
    /* FNV-1a hash of (source, seq) mapped to [JITTER_MIN, JITTER_MAX]. */
    uint32_t h = 2166136261u;
    h ^= (uint32_t)(source & 0xFF);
    h *= 16777619u;
    h ^= (uint32_t)(source >> 8);
    h *= 16777619u;
    h ^= (uint32_t)(seq & 0xFF);
    h *= 16777619u;
    h ^= (uint32_t)(seq >> 8);
    h *= 16777619u;

    uint32_t range = ATALAIA_JITTER_MAX_MS - ATALAIA_JITTER_MIN_MS + 1;
    return ATALAIA_JITTER_MIN_MS + (h % range);
}
