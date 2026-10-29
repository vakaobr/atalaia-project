/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * A transient status screen (an update's or a mode fetch's refusal or failure) is
 * shown for STATUS_HOLD_MS, and then the screen the box's state calls for comes
 * back: nothing else redraws an idle box. The shell tells this module about every
 * screen it draws for the state (the picker, the lobby, the final score, a game's
 * screens: status_hold_state) and about every status screen of the update tasks
 * (status_hold_transient, from any task); the main loop asks status_hold_due.
 */
#ifndef ATALAIA_STATUS_HOLD_H
#define ATALAIA_STATUS_HOLD_H

#include <stdbool.h>
#include <stdint.h>

#include "screen_types.h"

/* How long a refusal or failure stays on the screen. */
#define STATUS_HOLD_MS 8000u

typedef struct {
    screen_update_t state; /* the last screen drawn for the box's state */
    bool have_state;
    volatile uint32_t at;    /* when the last transient status was drawn */
    volatile bool transient; /* a transient status is the last thing drawn */
} status_hold_t;

void status_hold_init(status_hold_t *h);

/* A state screen was drawn (it replaced any transient one). Main task only. */
void status_hold_state(status_hold_t *h, const char *tmpl, const char *data_json);

/* A transient status screen was drawn now (any task; progress screens renew it). */
void status_hold_transient(status_hold_t *h, uint32_t now);

/* True once, when the transient screen has been up STATUS_HOLD_MS with no network job running
 * (`busy`) and nothing drawn over it: `out` is then the state screen to draw again. */
bool status_hold_due(status_hold_t *h, uint32_t now, bool busy, screen_update_t *out);

#endif
