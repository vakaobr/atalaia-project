/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Listen before talk, the box's rule (RFC 0001 Amendment 14, decision SL-25). Before a frame
 * goes on air the radio task asks the radio whether the channel is busy. If it is, the frame
 * waits a random 20-200 ms and the radio is asked again, at most ATALAIA_LBT_MAX_TRIES times in
 * a row; after that the frame is sent anyway (the study's model did the same, and dropping a
 * frame that the outbox or a retry has nothing to say about would be worse than a collision).
 * The count then starts again for the next frame.
 *
 * This is collision avoidance only. The duty-cycle budget is spent by the real send and is not
 * touched here: a CAD is not time on air.
 *
 * No time, no radio and no allocation: the caller holds the frame and the clock, asks the radio
 * (when atalaia_lbt_should_listen()) and gives the answer to atalaia_lbt_decide(). The wait
 * is drawn from the box's own entropy through the callback (the box's shell.random; a seeded
 * stub in tests), the same source the relay rules use.
 */
#ifndef ATALAIA_LBT_H
#define ATALAIA_LBT_H

#include <stdbool.h>
#include <stdint.h>

/* Busy answers in a row after which the frame goes anyway. */
#define ATALAIA_LBT_MAX_TRIES 8
/* A busy channel makes the frame wait a uniform time in this range. */
#define ATALAIA_LBT_WAIT_MIN_MS 20
#define ATALAIA_LBT_WAIT_MAX_MS 200

/* A uniform 32-bit random number from the box's own entropy source. */
typedef uint32_t (*atalaia_lbt_rand_fn)(void *ctx);

typedef enum {
    ATALAIA_LBT_SEND,        /* the channel is free: send now */
    ATALAIA_LBT_WAIT,        /* busy: hold the frame for *wait_ms, then ask again */
    ATALAIA_LBT_SEND_ANYWAY, /* busy again after 8 waits: send, the count starts again */
} atalaia_lbt_verdict_t;

typedef struct {
    atalaia_lbt_rand_fn rand;
    void *rand_ctx;
    uint8_t tries; /* busy answers for the frame in hand */
} atalaia_lbt_t;

/* rand must not be NULL. */
void atalaia_lbt_init(atalaia_lbt_t *l, atalaia_lbt_rand_fn rand, void *rand_ctx);

/*
 * False when the frame in hand has already waited ATALAIA_LBT_MAX_TRIES times: it goes without
 * another look at the channel (the study's model: 8 deferrals, then the next turn sends), so the
 * caller makes no CAD for it and gives atalaia_lbt_decide() busy = true.
 */
bool atalaia_lbt_should_listen(const atalaia_lbt_t *l);

/*
 * The radio's answer for the frame in hand. WAIT sets *wait_ms (20-200); SEND and SEND_ANYWAY
 * start the next frame's count again.
 */
atalaia_lbt_verdict_t atalaia_lbt_decide(atalaia_lbt_t *l, bool busy, uint32_t *wait_ms);

/* The frame in hand is gone without being sent: start the count again. */
void atalaia_lbt_reset(atalaia_lbt_t *l);

#endif /* ATALAIA_LBT_H */
