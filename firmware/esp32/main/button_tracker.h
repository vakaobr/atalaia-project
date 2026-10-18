/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Button press/hold/release tracker. Translates raw GPIO button state
 * into the team_input.press / .hold / .release events that mode scripts
 * expect (see modes/README.md).
 */
#ifndef ATALAIA_BUTTON_TRACKER_H
#define ATALAIA_BUTTON_TRACKER_H

#include <stdbool.h>
#include <stdint.h>

#include "node_runner.h"

#define BUTTON_TRACKER_MAX   4
#define BUTTON_HOLD_INTERVAL 250 /* ms between hold events */

typedef struct {
    const char *team_names[BUTTON_TRACKER_MAX];
    int team_count;
    bool pressed[BUTTON_TRACKER_MAX];
    uint32_t held_ms[BUTTON_TRACKER_MAX];
    uint32_t hold_accum[BUTTON_TRACKER_MAX]; /* ms since last hold event */
} button_tracker_t;

/*
 * Initialise the tracker. team_names[i] is the team for button i+1.
 * team_count may be less than BUTTON_TRACKER_MAX; extra buttons are ignored.
 */
void button_tracker_init(button_tracker_t *t, const char *const *team_names, int team_count);

/*
 * Update the tracker with the current button bitmask and elapsed time.
 * Generates a team_input.press event when a button goes down,
 * team_input.hold events every BUTTON_HOLD_INTERVAL ms while it is held,
 * and a team_input.release event when it is released.
 * Events are fed to the runner via node_runner_input.
 */
void button_tracker_update(button_tracker_t *t, uint8_t pressed_bitmask, uint32_t delta_ms,
                           node_runner_t *runner);

#endif /* ATALAIA_BUTTON_TRACKER_H */
