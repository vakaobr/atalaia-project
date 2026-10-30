/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The per-source replay window (RFC 0001 Amendment 23, decision SR-20): the highest nonce counter
 * (epoch << 16 | seq) an authenticated packet of one source has had, and a 64-bit bitmap of the
 * 64 counters up to it. A counter above the highest is fresh; one inside the window is fresh
 * once (the bitmap says if it came before); one 64 or more below is refused as too old, so a
 * recorded packet played back later is refused even when no table remembers it by then.
 *
 * Only call atalaia_replay_accept for a packet that has authenticated (a forged counter must not
 * move the window). Every receiver keeps one window per source: the Field Box, the USB modem, and
 * the two controllers' ports of this file (simulator/atalaia_sim/replay.py,
 * app/lib/radio/replay.dart), all tested against protocol/vectors/replay_window.json.
 */
#ifndef ATALAIA_REPLAY_H
#define ATALAIA_REPLAY_H

#include <stdbool.h>
#include <stdint.h>

#define ATALAIA_REPLAY_WIDTH 64

typedef enum {
    ATALAIA_REPLAY_FRESH = 0, /* not seen: accept */
    ATALAIA_REPLAY_DUPLICATE, /* inside the window and already seen (a flood copy, or a replay) */
    ATALAIA_REPLAY_TOO_OLD,   /* 64 or more below the highest: a replay, or a copy long delayed */
} atalaia_replay_verdict_t;

typedef struct {
    uint32_t high; /* the highest counter accepted */
    uint64_t seen; /* bit i: counter (high - i) was accepted; bit 0 is high itself */
    bool have;     /* false until the first packet of the source */
} atalaia_replay_t;

static inline uint32_t atalaia_replay_ctr(uint16_t epoch, uint16_t seq)
{
    return ((uint32_t)epoch << 16) | seq;
}

void atalaia_replay_init(atalaia_replay_t *w);

/* What the verdict for ctr would be; changes nothing. */
atalaia_replay_verdict_t atalaia_replay_check(const atalaia_replay_t *w, uint32_t ctr);

/* Check and, when fresh, record ctr. Returns the verdict. */
atalaia_replay_verdict_t atalaia_replay_accept(atalaia_replay_t *w, uint32_t ctr);

#endif /* ATALAIA_REPLAY_H */
