/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Pairing a box by the code it shows (protocol/adoption.md section 7, RFC 0001
 * Amendment 8, decisions AD-15 to AD-27): an unadopted box shows a 6-digit code
 * and offers itself over the radio in pair frames (atalaia/pair_frame.h); the GM
 * types the code in the console; the controller and the box run CPace
 * (cpace.h) with it, confirm each other's key, and the controller sends the
 * field join key sealed under the agreed key. The box then adopts the field
 * exactly as by a field card or the USB cable (adoption.c's rules), and its
 * field frames start.
 *
 * What bounds an attacker without the code: one guess per run (CPace), a new
 * code after every failed run, a minute's wait after three failed runs, no more
 * runs after ten until the box restarts; at most two answers per run, one
 * offer every 15 s or more (the sub-band's duty cycle) and only while the code
 * is on the screen (5 minutes); a run's secrets wiped on every outcome; a sid
 * once used never again; a KEY that does not authenticate is ignored, not a reason to end a
 * run (anyone on the air can send one). The box seals nothing itself: only the controller
 * encrypts (KEY), under a key new to every run, with a nonce that needs no
 * random number generator. Platform-free: the shell gives the radio, the
 * random bytes, the screen and the log; the host box runs it too.
 */
#ifndef ATALAIA_BOX_PAIR_H
#define ATALAIA_BOX_PAIR_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "adoption.h"
#include "atalaia/packet.h"
#include "atalaia/pair_frame.h"

#define BOX_PAIR_SHOW_MS          300000u /* the code stays on the screen this long */
#define BOX_PAIR_OFFER_MIN_MS     15000u  /* at most one OFFER this often */
#define BOX_PAIR_OFFER_SHARE_PCT  5u      /* of the sub-band's duty cycle, while the code shows */
#define BOX_PAIR_RUN_MS           10000u  /* a run waits this long for its KEY */
#define BOX_PAIR_RUNS_BEFORE_WAIT 3u      /* failed runs in a row, then ... */
#define BOX_PAIR_WAIT_MS          60000u  /* ... a minute without runs */
#define BOX_PAIR_RUNS_MAX         10u     /* failed runs, then no more until a restart */
#define BOX_PAIR_REPLIES_PER_RUN  2u      /* REPLY sent at most twice for one START's sid */
#define BOX_PAIR_DONE_REPEATS     2u      /* DONE sent again for a repeated KEY, at most */
#define BOX_PAIR_SIDS             8u      /* sids remembered: a used one never runs again */

typedef struct {
    bool (*radio_send)(void *user, const uint8_t *pkt, size_t len);
    void (*random)(void *user, uint8_t *buf, size_t len); /* the shell's seeded generator */
    void (*screen)(void *user, const char *tmpl, const char *data_json);
    void (*log)(void *user, const char *line);
    void *user;
} box_pair_ops_t;

typedef struct {
    box_pair_ops_t ops;
    adoption_t *adopt;
    const atalaia_crypto_ops_t *crypto;
    char name[ATALAIA_PF_NAME_MAX + 1];
    uint8_t tier;
    uint32_t channel_hz; /* where the box listens: for the offers' share of the duty cycle */
    uint32_t now_ms;

    bool active;      /* a code on the screen, offers on the air */
    bool locked;      /* BOX_PAIR_RUNS_MAX failed runs: nothing until a restart */
    bool redraw;      /* the pairing screen went away: the shell shows its own again */
    bool lock_notice; /* "Pair locked" on the screen until a key (decision AD-25) */
    char code[ATALAIA_PF_CODE_DIGITS + 1];
    uint8_t pair_id[ATALAIA_PF_PAIR_ID_SIZE];
    uint32_t show_until_ms;
    uint32_t next_offer_ms;
    bool waiting; /* the minute after BOX_PAIR_RUNS_BEFORE_WAIT failed runs */
    uint32_t wait_until_ms;
    uint8_t failed_in_row;
    uint8_t failed_total;

    /* The run: one START's sid at a time. */
    bool in_run;
    uint8_t sid[ATALAIA_PF_SID_SIZE];
    atalaia_pf_keys_t keys;
    uint32_t run_until_ms;
    uint8_t replies;
    uint8_t reply_frame[ATALAIA_PF_MAX];
    size_t reply_len;
    /* The last DONE, for a KEY the controller sends again (its DONE was lost). */
    bool done_valid;
    uint8_t done_sid[ATALAIA_PF_SID_SIZE];
    uint8_t done_frame[ATALAIA_PF_MAX];
    size_t done_len;
    uint8_t done_repeats;
    uint32_t done_until_ms;

    uint8_t used_sids[BOX_PAIR_SIDS][ATALAIA_PF_SID_SIZE];
    uint8_t used_next;

    /* Counters for "@pair" and the tests. */
    uint32_t offers_sent, runs_started, runs_failed, frames_ignored, bad_keys;
} box_pair_t;

void box_pair_init(box_pair_t *p, const box_pair_ops_t *ops, adoption_t *adopt,
                   const atalaia_crypto_ops_t *crypto, const char *name, uint8_t tier,
                   uint32_t channel_hz);

/* Shows a new code and starts offering. False if the box is adopted or locked. */
bool box_pair_start(box_pair_t *p, uint32_t now_ms);
/* Stops pairing (the code leaves the screen at the next tick). */
void box_pair_stop(box_pair_t *p, const char *why);

/* A packet heard: true if it was a pair frame (handled or ignored), false otherwise. */
bool box_pair_on_packet(box_pair_t *p, const uint8_t *pkt, size_t len, uint32_t now_ms);

/* A keypad key while the code shows: '*' stops pairing, '#' shows a new code, any other
 * key is kept from the shell; with "Pair locked" on the screen any key closes it. False
 * when pairing is not on the screen. */
bool box_pair_key(box_pair_t *p, char key, uint32_t now_ms);

/* Offers and timeouts. Returns true once when the pairing screen goes away. */
bool box_pair_tick(box_pair_t *p, uint32_t now_ms);

/* The code, or the lock's notice, shows (keys go to box_pair_key). */
bool box_pair_showing(const box_pair_t *p);

#endif /* ATALAIA_BOX_PAIR_H */
