/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The field admin's settings of a box's outputs, at the box (decision EXP-28: outputs stay off on
 * a box until a person at that box, with the admin PIN, enables them):
 *
 *   - the picker's "Outputs" entry (preset_ui.h, behind the admin PIN): one screen per output,
 *     "start_confirm" with "output" in its data (screen_renderer.c, oled_view.c). Keys: '1'
 *     enabled or not, '2' the next function (out.<n>, siren, strobe, smoke, light, horn), '3'
 *     the next max on (5, 10, 30, 60, 120, 300, 600 s), '5' the 1 s test, '0' the next output,
 *     '#' or '*' back to the picker. Each change is stored at once (outputs_configure);
 *   - the serial console: "@outputs" lists them; "@output <n> enable|disable|test",
 *     "@output <n> function <name>" and "@output <n> max <seconds>" change them, with the admin
 *     PIN as the last word in a release build (admin_pin_gate_serial; outputs_admin_args gives
 *     its word count).
 *
 * Only while no game runs: the shell offers neither during a game, and outputs_configure and
 * outputs_test refuse then. Platform-free (the host tests, the host box).
 */
#ifndef ATALAIA_OUTPUTS_ADMIN_H
#define ATALAIA_OUTPUTS_ADMIN_H

#include <stdbool.h>
#include <stddef.h>

#include "outputs.h"
#include "screen_types.h"

typedef struct {
    outputs_t *outputs;
    bool open;
    int index;    /* the output on the screen */
    bool testing; /* the last key was the test, and it ran */
} outputs_admin_t;

/* Opens the screen on the first output (nothing when the box has none). */
void outputs_admin_open(outputs_admin_t *a, outputs_t *o);
bool outputs_admin_active(const outputs_admin_t *a);

/* A key while open; false when it closed the screen ('#', '*'), true otherwise. */
bool outputs_admin_key(outputs_admin_t *a, char key);

/* The screen while open ("start_confirm" with "output", "of", "gpio", "fn", "enabled", "max_s"
 * and "testing"); false when closed. */
bool outputs_admin_screen(const outputs_admin_t *a, screen_update_t *out);

/* The next max on after max_s in the screen's list (after the last: the first). */
uint32_t outputs_admin_next_max(uint32_t max_s);

/* The next function after fn for output index (out.<index + 1>, then the named ones). */
const char *outputs_admin_next_function(int index, const char *fn);

/* For the PIN gate: how many words follow "output" in a console line that is an output change
 * ("output 1 enable": 2, "output 1 function siren": 3); -1 for any other line ("outputs" too,
 * which changes nothing and needs no PIN). */
int outputs_admin_args(const char *cmd);

/* "outputs" or "output ..." (the line without '@', its PIN already checked and cut off): true
 * when it was one of them, with one line in reply. busy: a game is joined or running (changes
 * and the test are refused). */
bool outputs_admin_command(outputs_t *o, const char *cmd, bool busy, char *reply, size_t cap);

#endif /* ATALAIA_OUTPUTS_ADMIN_H */
