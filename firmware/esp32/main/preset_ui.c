/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#include "preset_ui.h"

#include <stdio.h>
#include <string.h>

void preset_ui_init(preset_ui_t *ui, const char *admin_pin, int preset_count)
{
    memset(ui, 0, sizeof(*ui));
    ui->state = PRESET_UI_STATE_PIN_ENTRY;
    if (admin_pin) {
        snprintf(ui->admin_pin, sizeof(ui->admin_pin), "%s", admin_pin);
    }
    ui->preset_count = preset_count;
    ui->selected_preset = 1;
    ui->timer_duration_s = 600; /* 10 minutes default */
}

bool preset_ui_handle_key(preset_ui_t *ui, char key)
{
    if (!ui) return false;

    switch (ui->state) {
    case PRESET_UI_STATE_PIN_ENTRY:
        if (key >= '0' && key <= '9') {
            if (ui->pin_pos < PRESET_UI_PIN_MAX) {
                ui->pin_buffer[ui->pin_pos++] = key;
                ui->pin_buffer[ui->pin_pos] = '\0';
            }
            return true;
        }
        if (key == '#') {
            /* Check PIN. */
            if (strcmp(ui->pin_buffer, ui->admin_pin) == 0) {
                ui->pin_accepted = true;
                ui->state = PRESET_UI_STATE_PRESET_LIST;
            } else {
                /* Wrong PIN: reset buffer. */
                ui->pin_pos = 0;
                ui->pin_buffer[0] = '\0';
                ui->pin_accepted = false;
            }
            return true;
        }
        if (key == '*') {
            /* Backspace. */
            if (ui->pin_pos > 0) {
                ui->pin_pos--;
                ui->pin_buffer[ui->pin_pos] = '\0';
            }
            return true;
        }
        return false;

    case PRESET_UI_STATE_PRESET_LIST:
        if (key >= '1' && key <= '9') {
            int idx = key - '0';
            if (idx <= ui->preset_count) {
                ui->selected_preset = idx;
            }
            return true;
        }
        if (key == '#') {
            ui->state = PRESET_UI_STATE_TIMER_ADJUST;
            return true;
        }
        if (key == '*') {
            ui->state = PRESET_UI_STATE_PIN_ENTRY;
            ui->pin_pos = 0;
            ui->pin_buffer[0] = '\0';
            return true;
        }
        return false;

    case PRESET_UI_STATE_TIMER_ADJUST:
        if (key == '2') {
            /* Up: add 5 minutes. */
            ui->timer_duration_s += 300;
            return true;
        }
        if (key == '8') {
            /* Down: subtract 5 minutes (min 0 = unlimited). */
            if (ui->timer_duration_s >= 300) {
                ui->timer_duration_s -= 300;
            } else {
                ui->timer_duration_s = 0;
            }
            return true;
        }
        if (key == '#') {
            ui->state = PRESET_UI_STATE_CONFIRM;
            return true;
        }
        if (key == '*') {
            ui->state = PRESET_UI_STATE_PRESET_LIST;
            return true;
        }
        return false;

    case PRESET_UI_STATE_CONFIRM:
        if (key == '#') {
            ui->state = PRESET_UI_STATE_GAME_STARTED;
            return true;
        }
        if (key == '*') {
            ui->state = PRESET_UI_STATE_TIMER_ADJUST;
            return true;
        }
        return false;

    case PRESET_UI_STATE_GAME_STARTED: return false;
    }

    return false;
}

preset_ui_state_t preset_ui_get_state(const preset_ui_t *ui)
{
    return ui->state;
}

int preset_ui_selected_preset(const preset_ui_t *ui)
{
    return ui->selected_preset;
}

uint32_t preset_ui_timer_duration(const preset_ui_t *ui)
{
    return ui->timer_duration_s;
}
