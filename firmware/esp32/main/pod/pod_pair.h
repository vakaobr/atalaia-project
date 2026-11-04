/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The I/O pod's Bluetooth pairing (decisions PODPK-1 to PODPK-11), apart
 * from the Bluetooth stack: LE Secure Connections with passkey entry. The
 * pod has a display and no keyboard (IO capability DisplayOnly), so it
 * shows a 6-digit passkey on its OLED and the phone asks for it; a pairing
 * made so is protected against a man in the middle (MITM), and the bond is
 * kept (NimBLE's NVS store) so the phone pairs once.
 *
 * What this module decides, from the stack's events, on the pod task:
 *
 *   - what the OLED shows (oled_pair_view_t): nothing, the passkey with the
 *     seconds left, paired, pairing failed, too slow, "pair again" (a bond
 *     the pod does not trust), the bond-clearing hold, bonds cleared;
 *   - when to drop the link: a pairing that failed or ran out of time, and a
 *     phone connected for POD_PAIR_TIMEOUT_MS without a secure link (it holds
 *     the pod's one connection);
 *   - a bond that is not MITM-protected (made by a pod firmware before
 *     PODPK, Just Works) or that the pod no longer has (cleared, or the
 *     pod's NVS erased): the pod forgets its side of it and drops the link
 *     with HCI reason 0x05 (Authentication Failure), which the app reads as
 *     "this pod needs pairing again" (PODPK-4);
 *   - clearing every bond: the board's PRG button held POD_PAIR_CLEAR_HOLD_MS
 *     (PODPK-6).
 *
 * pod_ble_nimble.c carries out the actions; the host tests drive it alone.
 */
#ifndef ATALAIA_POD_PAIR_H
#define ATALAIA_POD_PAIR_H

#include <stdbool.h>
#include <stdint.h>

#include "oled_view.h"

/* A phone connected this long without a secure link is dropped. */
#define POD_PAIR_TIMEOUT_MS 60000
/* The Security Manager's own timeout (Core spec Vol 3 Part H 3.4): the passkey's countdown. */
#define POD_PAIR_PASSKEY_MS 30000
/* How long an outcome (paired, failed, too slow, pair again, cleared) stays on the OLED. */
#define POD_PAIR_RESULT_MS 5000
/* The PRG button held this long clears every bond; the OLED shows the hold after
 * POD_PAIR_CLEAR_SHOW_MS (a short press shows nothing). */
#define POD_PAIR_CLEAR_HOLD_MS 5000
#define POD_PAIR_CLEAR_SHOW_MS 1000

/* HCI disconnection reasons the pod gives (Core spec Vol 1 Part F). */
#define POD_PAIR_REASON_AUTH_FAIL 0x05 /* the bond is not trusted: pair again */
#define POD_PAIR_REASON_USER_TERM 0x13 /* the pairing wait is over */

/* How an encryption attempt ended. */
typedef enum {
    POD_PAIR_RESULT_OK = 0,
    POD_PAIR_RESULT_FAILED,  /* wrong passkey, cancelled, refused */
    POD_PAIR_RESULT_TIMEOUT, /* the Security Manager's 30 s ran out */
    POD_PAIR_RESULT_NO_KEY,  /* the phone used a bond the pod does not have */
} pod_pair_result_t;

/* What the glue does next (one at a time). */
typedef enum {
    POD_PAIR_ACT_NONE = 0,
    POD_PAIR_ACT_DROP,        /* disconnect, POD_PAIR_REASON_USER_TERM (failed, too slow) */
    POD_PAIR_ACT_DROP_STALE,  /* forget this phone's bond, disconnect with POD_PAIR_REASON_AUTH_FAIL
                               */
    POD_PAIR_ACT_CLEAR_BONDS, /* forget every bond, and disconnect the phone if one is connected */
} pod_pair_action_t;

typedef struct {
    uint32_t pairings;    /* new bonds made with a passkey */
    uint32_t failures;    /* pairings that failed (wrong passkey, cancelled) */
    uint32_t timeouts;    /* pairings that ran out of time, links dropped for it */
    uint32_t stale_bonds; /* bonds refused: not MITM-protected, or unknown to the pod */
    uint32_t clears;      /* bond stores cleared with the PRG button */
} pod_pair_counters_t;

typedef struct {
    bool require_mitm; /* off: an encrypted link is enough (a bench build without the passkey) */
    char name[20];     /* "atalaia-pod-XXXX": what the phone lists, on the OLED's footer */

    bool connected;
    bool secure;   /* encrypted, and MITM-protected when require_mitm */
    bool dropping; /* a drop was asked for: no more actions for this link */
    uint32_t connect_ms;

    oled_pair_t show;
    uint32_t show_ms; /* when show began */
    uint32_t passkey;

    bool button;      /* the PRG button is down */
    bool button_done; /* this press has cleared the bonds already */
    uint32_t button_ms;

    pod_pair_counters_t count;
} pod_pair_t;

void pod_pair_init(pod_pair_t *p, bool require_mitm);
void pod_pair_set_name(pod_pair_t *p, const char *name);

/* A 6-digit passkey, 000000-999999, from 32-bit random words (rand is called until one falls
 * below the last whole multiple of a million, so every passkey is as likely). */
uint32_t pod_pair_passkey(uint32_t (*rand32)(void *ctx), void *ctx);

void pod_pair_on_connect(pod_pair_t *p, uint32_t now_ms);
void pod_pair_on_disconnect(pod_pair_t *p, uint32_t now_ms);

/* The stack asks the pod to show passkey (NimBLE's BLE_SM_IOACT_DISP). */
void pod_pair_on_passkey(pod_pair_t *p, uint32_t passkey, uint32_t now_ms);

/* The link's encryption changed: result, and the link's security after it. */
pod_pair_action_t pod_pair_on_encryption(pod_pair_t *p, pod_pair_result_t result, bool encrypted,
                                         bool authenticated, uint32_t now_ms);

/* Called often (every pod loop): button is the PRG button's state now. Expires what the OLED
 * shows, drops a phone that waits too long, clears the bonds on a long press. */
pod_pair_action_t pod_pair_tick(pod_pair_t *p, uint32_t now_ms, bool button);

/* What the OLED shows now. */
void pod_pair_view(const pod_pair_t *p, uint32_t now_ms, oled_pair_view_t *out);

#endif /* ATALAIA_POD_PAIR_H */
