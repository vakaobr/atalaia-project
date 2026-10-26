/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Controlled flooding: the dedupe table, the pre-Amendment-13 rebroadcast jitter, and the relay
 * rules of RFC 0001 Amendment 13 (decision SL-16).
 */
#include <string.h>

#include "atalaia/ack.h"
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

/* ---- Relay rules (RFC 0001 Amendment 13) ----------------------------------------------- */

void atalaia_relay_init(atalaia_relay_t *r, atalaia_relay_rand_fn rand, void *rand_ctx)
{
    memset(r, 0, sizeof(*r));
    r->rand = rand;
    r->rand_ctx = rand_ctx;
}

static uint32_t stamp(uint32_t now_ms)
{
    return now_ms != 0 ? now_ms : 1; /* 0 marks a free entry */
}

/* Milliseconds since t (a stamp), never negative: a stamp of 1 made at time 0 is not in the future.
 */
static uint32_t age_ms(uint32_t now_ms, uint32_t t)
{
    int32_t d = (int32_t)(now_ms - t);
    return d < 0 ? 0 : (uint32_t)d;
}

void atalaia_relay_heard(atalaia_relay_t *r, uint16_t source, uint32_t now_ms)
{
    size_t victim = 0;
    for (size_t i = 0; i < ATALAIA_RELAY_NEIGHBOURS; i++) {
        if (r->neighbours[i].heard_ms != 0 && r->neighbours[i].source == source) {
            r->neighbours[i].heard_ms = stamp(now_ms);
            return;
        }
    }
    /* A free entry, else the one heard longest ago. */
    for (size_t i = 0; i < ATALAIA_RELAY_NEIGHBOURS; i++) {
        if (r->neighbours[i].heard_ms == 0) {
            victim = i;
            break;
        }
        if (age_ms(now_ms, r->neighbours[i].heard_ms) >
            age_ms(now_ms, r->neighbours[victim].heard_ms)) {
            victim = i;
        }
    }
    r->neighbours[victim].source = source;
    r->neighbours[victim].heard_ms = stamp(now_ms);
}

uint32_t atalaia_relay_neighbours(const atalaia_relay_t *r, uint32_t now_ms)
{
    uint32_t n = 0;
    for (size_t i = 0; i < ATALAIA_RELAY_NEIGHBOURS; i++) {
        if (r->neighbours[i].heard_ms != 0 &&
            age_ms(now_ms, r->neighbours[i].heard_ms) <= ATALAIA_RELAY_NEIGHBOUR_MS) {
            n++;
        }
    }
    return n > 0 ? n : 1;
}

static bool on_path(const atalaia_relay_t *r, uint16_t node, uint32_t now_ms)
{
    for (size_t i = 0; i < ATALAIA_RELAY_PATHS; i++) {
        if (r->paths[i].at_ms != 0 && r->paths[i].node == node) {
            return age_ms(now_ms, r->paths[i].at_ms) <= ATALAIA_RELAY_PATH_MS;
        }
    }
    return false;
}

static void put_on_path(atalaia_relay_t *r, uint16_t node, uint32_t now_ms)
{
    size_t victim = 0;
    for (size_t i = 0; i < ATALAIA_RELAY_PATHS; i++) {
        if (r->paths[i].at_ms != 0 && r->paths[i].node == node) {
            r->paths[i].at_ms = stamp(now_ms);
            return;
        }
    }
    for (size_t i = 0; i < ATALAIA_RELAY_PATHS; i++) {
        if (r->paths[i].at_ms == 0) {
            victim = i;
            break;
        }
        if (age_ms(now_ms, r->paths[i].at_ms) > age_ms(now_ms, r->paths[victim].at_ms)) victim = i;
    }
    r->paths[victim].node = node;
    r->paths[victim].at_ms = stamp(now_ms);
}

int atalaia_relay_plan(atalaia_relay_t *r, atalaia_relay_kind_t kind, uint16_t source, uint16_t seq,
                       uint16_t ack_node, uint32_t now_ms)
{
    if (kind == ATALAIA_RELAY_ACK && !on_path(r, ack_node, now_ms)) return ATALAIA_RELAY_SKIP;
    if (kind != ATALAIA_RELAY_ASKS_ACK) {
        /* Relay with probability min(1, C / n): a draw below C out of n. */
        uint32_t n = atalaia_relay_neighbours(r, now_ms);
        if (n > ATALAIA_RELAY_DENSITY_C && r->rand(r->rand_ctx) % n >= ATALAIA_RELAY_DENSITY_C) {
            return ATALAIA_RELAY_SKIP;
        }
    }
    uint32_t delay;
    if (kind == ATALAIA_RELAY_ASKS_ACK) {
        delay = ATALAIA_RELAY_ACK_WAIT_MIN_MS +
                r->rand(r->rand_ctx) %
                    (ATALAIA_RELAY_ACK_WAIT_MAX_MS - ATALAIA_RELAY_ACK_WAIT_MIN_MS + 1);
    } else {
        delay =
            ATALAIA_RELAY_DELAY_MIN_MS +
            r->rand(r->rand_ctx) % (ATALAIA_RELAY_DELAY_MAX_MS - ATALAIA_RELAY_DELAY_MIN_MS + 1);
    }
    for (size_t i = 0; i < ATALAIA_RELAY_SLOTS; i++) {
        atalaia_relay_slot_t *s = &r->slots[i];
        if (s->used) continue;
        s->used = true;
        s->wait_ack = kind == ATALAIA_RELAY_ASKS_ACK;
        s->source = source;
        s->seq = seq;
        s->due_ms = now_ms + delay;
        return (int)i;
    }
    return ATALAIA_RELAY_NO_SLOT;
}

size_t atalaia_relay_ack_heard(atalaia_relay_t *r, uint16_t ack_node, uint16_t ack_seq,
                               const uint8_t *bitmap, size_t bitmap_len)
{
    size_t n = 0;
    for (size_t i = 0; i < ATALAIA_RELAY_SLOTS; i++) {
        atalaia_relay_slot_t *s = &r->slots[i];
        if (s->used && s->wait_ack && s->source == ack_node &&
            atalaia_ack_covers(ack_seq, bitmap, bitmap_len, s->seq)) {
            s->used = false;
            n++;
        }
    }
    return n;
}

int atalaia_relay_take_due(atalaia_relay_t *r, uint32_t now_ms)
{
    for (size_t i = 0; i < ATALAIA_RELAY_SLOTS; i++) {
        atalaia_relay_slot_t *s = &r->slots[i];
        if (!s->used || (int32_t)(now_ms - s->due_ms) < 0) continue;
        s->used = false;
        if (s->wait_ack) put_on_path(r, s->source, now_ms);
        return (int)i;
    }
    return -1;
}

size_t atalaia_relay_pending(const atalaia_relay_t *r)
{
    size_t n = 0;
    for (size_t i = 0; i < ATALAIA_RELAY_SLOTS; i++) {
        if (r->slots[i].used) n++;
    }
    return n;
}
