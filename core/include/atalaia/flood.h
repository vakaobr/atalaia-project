/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Controlled flooding with a 64-entry dedupe table (30 s expiry, LRU
 * eviction), and the relay rules of RFC 0001 Amendment 13 (decision SL-16, "A+backoff"):
 * an ACK-asking frame waits for the controller's ACK, the controller's ACK is relayed only
 * on the path it serves, everything else relays with probability min(1, 3 / neighbours),
 * all after a random delay drawn from the box's own entropy.
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

/*
 * ---- Relay rules (RFC 0001 Amendment 13; decision SL-16) -----------------------------
 *
 * What a box does with a frame it has accepted (authenticated, new in its dedupe table,
 * hop_limit left): atalaia_relay_plan() decides whether to relay it and after how long, and
 * which of ATALAIA_RELAY_SLOTS slots holds it (the caller keeps the packet bytes in a
 * parallel array indexed by the slot). atalaia_flood_jitter_ms() above is the pre-Amendment-13
 * rule (the same delay in every box); the box no longer calls it.
 *
 * The caller's part: atalaia_relay_heard() for every accepted frame whose source is a box (the
 * neighbour count comes from frames already heard, nothing new is sent), atalaia_relay_ack_heard()
 * for every accepted ACK, atalaia_relay_take_due() from the tick loop.
 */
/* Relay slots, and the tables the rules keep (the oldest entry goes when one is full). */
#define ATALAIA_RELAY_SLOTS      8
#define ATALAIA_RELAY_NEIGHBOURS 64
#define ATALAIA_RELAY_PATHS      32
/* Relay probability min(1, C / neighbours). */
#define ATALAIA_RELAY_DENSITY_C 3
/* A neighbour counts for this long after it was heard. */
#define ATALAIA_RELAY_NEIGHBOUR_MS 600000
/* A box is "on my path" this long after I relayed one of its frames. */
#define ATALAIA_RELAY_PATH_MS 30000
/* A frame that asks for an ACK waits this long, for the controller's ACK to be heard. */
#define ATALAIA_RELAY_ACK_WAIT_MIN_MS 350
#define ATALAIA_RELAY_ACK_WAIT_MAX_MS 700
/* Every other relay waits a uniform delay in this range. */
#define ATALAIA_RELAY_DELAY_MIN_MS 20
#define ATALAIA_RELAY_DELAY_MAX_MS 600

/* A uniform 32-bit random number from the box's own entropy source. */
typedef uint32_t (*atalaia_relay_rand_fn)(void *ctx);

typedef enum {
    ATALAIA_RELAY_ASKS_ACK, /* EVENT or HELLO with ack_req: wait for the controller's ACK */
    ATALAIA_RELAY_ACK,      /* the controller's ACK (type 3): only for a box on my path */
    ATALAIA_RELAY_OTHER     /* STATE, TIME, CMD, CLAIM, an EVENT that asks for no ACK */
} atalaia_relay_kind_t;

/* atalaia_relay_plan() results besides a slot index (>= 0). */
#define ATALAIA_RELAY_SKIP    (-1) /* the rules say not to relay this frame */
#define ATALAIA_RELAY_NO_SLOT (-2) /* the rules say relay, but every slot is in use: dropped */

typedef struct {
    bool used;
    bool wait_ack; /* a frame that asked for an ACK: cancelled by the controller's ACK */
    uint16_t source;
    uint16_t seq;
    uint32_t due_ms;
} atalaia_relay_slot_t;

typedef struct {
    atalaia_relay_rand_fn rand;
    void *rand_ctx;
    struct {
        uint16_t source;
        uint32_t heard_ms; /* 0: free */
    } neighbours[ATALAIA_RELAY_NEIGHBOURS];
    struct {
        uint16_t node;
        uint32_t at_ms; /* 0: free */
    } paths[ATALAIA_RELAY_PATHS];
    atalaia_relay_slot_t slots[ATALAIA_RELAY_SLOTS];
} atalaia_relay_t;

/* rand must not be NULL (the box's existing entropy; a seeded stub in tests). */
void atalaia_relay_init(atalaia_relay_t *r, atalaia_relay_rand_fn rand, void *rand_ctx);

/* A frame from a box (not the controller) was accepted: that box is a neighbour. */
void atalaia_relay_heard(atalaia_relay_t *r, uint16_t source, uint32_t now_ms);

/* Boxes heard in the last ATALAIA_RELAY_NEIGHBOUR_MS, at least 1. */
uint32_t atalaia_relay_neighbours(const atalaia_relay_t *r, uint32_t now_ms);

/*
 * Decides one accepted frame. ack_node is the box the ACK is for (kind ACK only). Returns a slot
 * index (due_ms set), ATALAIA_RELAY_SKIP or ATALAIA_RELAY_NO_SLOT. The order is the study's:
 * the path gate for an ACK, the probability draw for every frame that does not ask for an ACK
 * (the controller's ACK included), then the delay, then the slot.
 */
int atalaia_relay_plan(atalaia_relay_t *r, atalaia_relay_kind_t kind, uint16_t source, uint16_t seq,
                       uint16_t ack_node, uint32_t now_ms);

/* The controller's ACK for ack_node was heard: cancels waiting slots it covers. Returns how many.
 */
size_t atalaia_relay_ack_heard(atalaia_relay_t *r, uint16_t ack_node, uint16_t ack_seq,
                               const uint8_t *bitmap, size_t bitmap_len);

/*
 * A slot whose delay has passed, freed; -1 when none. Call until -1. A frame that waited for an
 * ACK and was not cancelled puts its source on this box's path for ATALAIA_RELAY_PATH_MS.
 */
int atalaia_relay_take_due(atalaia_relay_t *r, uint32_t now_ms);

/* Slots in use. */
size_t atalaia_relay_pending(const atalaia_relay_t *r);

#endif /* ATALAIA_FLOOD_H */
