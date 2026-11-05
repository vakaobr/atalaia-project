/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * On-device preset picker driven by the keypad. The GM enters the admin
 * PIN, picks a preset, adjusts the timer and starts the game. With a check
 * set (preset_ui_set_guard, as the box does) the PIN goes through
 * admin_pin.h: its failure count, its waits, and no PIN set on a Field Box.
 *
 * With the setup entry on (preset_ui_enable_setup, a Field Box that has a setup portal), the
 * list ends with one more entry after the games, "Wi-Fi setup": '#' on it asks once more
 * ('#' again confirms, '*' goes back) and then the state is PRESET_UI_STATE_SETUP_REQUESTED,
 * which the shell answers by clearing the "configured" flag and restarting into the portal.
 * It sits behind the same admin PIN as every game.
 *
 * With the adopt entry on (preset_ui_enable_adopt, a box that is adopted and has a radio), the list
 * ends with one more, "Adopt to another field" (after "Wi-Fi setup" when both are on; decision
 * PKB-4): '#' on it asks once more ('#' again confirms, '*' goes back) and then the state is
 * PRESET_UI_STATE_ADOPT_REQUESTED, which the shell answers by letting the box show a pairing code
 * for another field (adoption_allow_move, box_pair_start). Nothing is forgotten until a field
 * has paired. It sits behind the same admin PIN as every game.
 *
 * With the outputs entry on (preset_ui_enable_outputs, a box built with a simple output), the
 * list ends with "Outputs" (after the two above): '#' on it gives
 * PRESET_UI_STATE_OUTPUTS_REQUESTED, which the shell answers with the outputs screen
 * (outputs_admin.h: enable, function, max on, the 1 s test; decision EXP-28), and then sets the
 * state back to PRESET_UI_STATE_PRESET_LIST. Behind the same admin PIN as every game.
 *
 * With the leave entry on (preset_ui_enable_leave: the menu the shell opens over a field game,
 * with no games and no other entry; decisions STUCK-20 to STUCK-33), the list ends with "Leave
 * the game": '#' on it asks once more ('#' again confirms, '*' goes back) and then the state is
 * PRESET_UI_STATE_LEAVE_REQUESTED, which the shell answers by ending the box's game as a
 * GAME_OVER for it would (box_game_leave). Behind the same admin PIN. In that menu '*' with no
 * digit typed closes it (PRESET_UI_STATE_CLOSED: the game's screen again).
 */
#ifndef ATALAIA_PRESET_UI_H
#define ATALAIA_PRESET_UI_H

#include <stdbool.h>
#include <stdint.h>

#include "admin_pin.h"
#include "screen_types.h"

#define PRESET_UI_PIN_MAX 8
/* The keypad picks entries 1-9 of a page; '0' turns to the next page (decision M2-1). */
#define PRESET_UI_PAGE_SIZE 9

typedef enum {
    PRESET_UI_STATE_PIN_ENTRY,
    PRESET_UI_STATE_PRESET_LIST,
    PRESET_UI_STATE_TIMER_ADJUST,
    PRESET_UI_STATE_CONFIRM,
    PRESET_UI_STATE_GAME_STARTED,
    PRESET_UI_STATE_SETUP_CONFIRM,     /* "Set up again?" */
    PRESET_UI_STATE_SETUP_REQUESTED,   /* confirmed: the shell restarts the box into the portal */
    PRESET_UI_STATE_ADOPT_CONFIRM,     /* "Change field?" */
    PRESET_UI_STATE_ADOPT_REQUESTED,   /* confirmed: the shell shows a pairing code */
    PRESET_UI_STATE_OUTPUTS_REQUESTED, /* "Outputs": the shell shows the outputs screen */
    PRESET_UI_STATE_LEAVE_CONFIRM,     /* "Leave the game?" */
    PRESET_UI_STATE_LEAVE_REQUESTED,   /* confirmed: the shell ends the box's game */
    PRESET_UI_STATE_CLOSED,            /* the menu over a game was closed with '*' */
} preset_ui_state_t;

typedef struct {
    preset_ui_state_t state;
    char pin_buffer[PRESET_UI_PIN_MAX + 1];
    int pin_pos;
    char admin_pin[PRESET_UI_PIN_MAX + 1];
    int selected_preset; /* 1-based, across every page */
    int preset_count;
    int page; /* 0-based page of PRESET_UI_PAGE_SIZE entries on the list screen */
    uint32_t timer_duration_s;
    bool pin_accepted;
    bool pin_error;      /* the last PIN was wrong; cleared by the next key */
    admin_pin_t *guard;  /* NULL: admin_pin compared as it is (host tests) */
    uint32_t locked_min; /* the last '#' met a wait of this many minutes (0: none) */
    bool no_pin;         /* the last '#' met a box with no admin PIN set */
    bool setup_entry;    /* the list ends with "Wi-Fi setup" (entry preset_count + 1) */
    bool adopt_entry;    /* and with "Adopt to another field" after it */
    bool outputs_entry;  /* and with "Outputs" after it */
    bool leave_entry;    /* and with "Leave the game" last (the menu over a field game) */
} preset_ui_t;

/* Adds (or removes) the list's last entry, "Wi-Fi setup". Off by default. */
void preset_ui_enable_setup(preset_ui_t *ui, bool on);

/* Adds (or removes) the list's last entry, "Adopt to another field". Off by default. */
void preset_ui_enable_adopt(preset_ui_t *ui, bool on);

/* Adds (or removes) the list's last entry, "Outputs". Off by default. */
void preset_ui_enable_outputs(preset_ui_t *ui, bool on);

/* Adds (or removes) the list's last entry, "Leave the game", and lets '*' with no digit typed
 * close the menu. Off by default. */
void preset_ui_enable_leave(preset_ui_t *ui, bool on);

/* The box's admin PIN check (admin_pin.h), shared with adoption. */
void preset_ui_set_guard(preset_ui_t *ui, admin_pin_t *guard);

/*
 * Initialise the preset UI. admin_pin is the PIN the GM must enter.
 * preset_count is how many presets are available.
 */
void preset_ui_init(preset_ui_t *ui, const char *admin_pin, int preset_count);

/*
 * Handle a keypad key press. Returns true if the UI consumed the key.
 * Keys: '0'-'9' for digits, '#' for confirm/enter, '*' for back/cancel. On the preset
 * list, '1'-'9' pick an entry of the current page and '0' shows the next page (the
 * first again after the last), selecting its first entry.
 */
bool preset_ui_handle_key(preset_ui_t *ui, char key);

/* Get the current state. */
preset_ui_state_t preset_ui_get_state(const preset_ui_t *ui);

/* Get the selected preset index (1-based, valid after GAME_STARTED). */
int preset_ui_selected_preset(const preset_ui_t *ui);

/* Get the adjusted timer duration in seconds. */
uint32_t preset_ui_timer_duration(const preset_ui_t *ui);

/*
 * Describe the screen for the current state (pin_entry, preset_select,
 * timer_adjust or start_confirm; see screen_renderer.h). labels[i] is the
 * label of list entry i + 1; labels may be NULL when label_count is 0. The
 * list screen holds the current page only, with "page" and "pages" when there
 * is more than one, and "admin":true in the menu over a game (preset_ui_enable_leave).
 * Returns false in PRESET_UI_STATE_GAME_STARTED, PRESET_UI_STATE_SETUP_REQUESTED,
 * PRESET_UI_STATE_ADOPT_REQUESTED, PRESET_UI_STATE_OUTPUTS_REQUESTED,
 * PRESET_UI_STATE_LEAVE_REQUESTED and PRESET_UI_STATE_CLOSED, which have no picker screen.
 * PRESET_UI_STATE_SETUP_CONFIRM is the "start_confirm" template with "setup":true,
 * PRESET_UI_STATE_ADOPT_CONFIRM the same with "adopt":true, PRESET_UI_STATE_LEAVE_CONFIRM with
 * "leave":true.
 */
bool preset_ui_screen(const preset_ui_t *ui, const char *const *labels, int label_count,
                      screen_update_t *out);

#endif /* ATALAIA_PRESET_UI_H */
