/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#include "button_tracker.h"

#include <stdio.h>
#include <string.h>

void button_tracker_init(button_tracker_t *t, const char *const *team_names, int team_count)
{
    memset(t, 0, sizeof(*t));
    if (team_count > BUTTON_TRACKER_MAX) team_count = BUTTON_TRACKER_MAX;
    t->team_count = team_count;
    for (int i = 0; i < team_count; i++) {
        t->team_names[i] = team_names[i];
    }
}

void button_tracker_update(button_tracker_t *t, uint8_t pressed_bitmask, uint32_t delta_ms,
                           node_runner_t *runner)
{
    if (!t || !runner) return;

    for (int i = 0; i < t->team_count; i++) {
        bool is_pressed = (pressed_bitmask >> i) & 1u;

        if (is_pressed && !t->pressed[i]) {
            /* Newly pressed: start tracking. Modes that count presses (Kill
             * Confirmed, Respawn) get team_input.press (modes/README.md);
             * the others react to the holds only. */
            t->pressed[i] = true;
            t->held_ms[i] = 0;
            t->hold_accum[i] = 0;
            char json[128];
            snprintf(json, sizeof(json), "{\"team\":\"%s\"}", t->team_names[i]);
            node_runner_input(runner, "team_input.press", json);
        }

        if (is_pressed && t->pressed[i]) {
            /* Still held: accumulate time and fire hold events. */
            t->held_ms[i] += delta_ms;
            t->hold_accum[i] += delta_ms;

            while (t->hold_accum[i] >= BUTTON_HOLD_INTERVAL) {
                t->hold_accum[i] -= BUTTON_HOLD_INTERVAL;
                char json[128];
                snprintf(json, sizeof(json), "{\"team\":\"%s\",\"ms\":%u}", t->team_names[i],
                         (unsigned)t->held_ms[i]);
                node_runner_input(runner, "team_input.hold", json);
            }
        }

        if (!is_pressed && t->pressed[i]) {
            /* Released. */
            t->pressed[i] = false;
            char json[128];
            snprintf(json, sizeof(json), "{\"team\":\"%s\",\"ms\":%u}", t->team_names[i],
                     (unsigned)t->held_ms[i]);
            node_runner_input(runner, "team_input.release", json);
            t->held_ms[i] = 0;
            t->hold_accum[i] = 0;
        }
    }
}
