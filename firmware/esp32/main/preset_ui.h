/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * On-device preset picker driven by the keypad. The GM enters the admin
 * PIN, picks a preset, adjusts the timer and starts the game.
 */
#ifndef ATALAIA_PRESET_UI_H
#define ATALAIA_PRESET_UI_H

#include <stdbool.h>
#include <stdint.h>

#define PRESET_UI_PIN_MAX 8

typedef enum {
    PRESET_UI_STATE_PIN_ENTRY,
    PRESET_UI_STATE_PRESET_LIST,
    PRESET_UI_STATE_TIMER_ADJUST,
    PRESET_UI_STATE_CONFIRM,
    PRESET_UI_STATE_GAME_STARTED,
} preset_ui_state_t;

typedef struct {
    preset_ui_state_t state;
    char pin_buffer[PRESET_UI_PIN_MAX + 1];
    int pin_pos;
    char admin_pin[PRESET_UI_PIN_MAX + 1];
    int selected_preset;
    int preset_count;
    uint32_t timer_duration_s;
    bool pin_accepted;
} preset_ui_t;

/*
 * Initialise the preset UI. admin_pin is the PIN the GM must enter.
 * preset_count is how many presets are available.
 */
void preset_ui_init(preset_ui_t *ui, const char *admin_pin, int preset_count);

/*
 * Handle a keypad key press. Returns true if the UI consumed the key.
 * Keys: '0'-'9' for digits, '#' for confirm/enter, '*' for back/cancel.
 */
bool preset_ui_handle_key(preset_ui_t *ui, char key);

/* Get the current state. */
preset_ui_state_t preset_ui_get_state(const preset_ui_t *ui);

/* Get the selected preset index (1-based, valid after GAME_STARTED). */
int preset_ui_selected_preset(const preset_ui_t *ui);

/* Get the adjusted timer duration in seconds. */
uint32_t preset_ui_timer_duration(const preset_ui_t *ui);

#endif /* ATALAIA_PRESET_UI_H */
