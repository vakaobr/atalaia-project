/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#include "status_hold.h"

#include <stdio.h>
#include <string.h>

void status_hold_init(status_hold_t *h)
{
    memset((void *)h, 0, sizeof(*h));
}

void status_hold_state(status_hold_t *h, const char *tmpl, const char *data_json)
{
    snprintf(h->state.template_name, sizeof(h->state.template_name), "%s", tmpl);
    snprintf(h->state.data_json, sizeof(h->state.data_json), "%s", data_json);
    h->have_state = true;
    h->transient = false;
}

void status_hold_transient(status_hold_t *h, uint32_t now)
{
    h->at = now;
    h->transient = true;
}

bool status_hold_due(status_hold_t *h, uint32_t now, bool busy, screen_update_t *out)
{
    if (!h->transient || busy) return false;
    /* Signed: the main loop reads its clock once per pass, and a status drawn later in the same
     * pass (a serial "@update" handled after the read) has `at` a little after `now`. Unsigned,
     * that difference wrapped to a huge number and the status went away at once (bench,
     * 2026-10-29). */
    if ((int32_t)(now - h->at) < (int32_t)STATUS_HOLD_MS) return false;
    h->transient = false;
    if (!h->have_state) return false;
    *out = h->state;
    return true;
}
