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
    ui->pin_error = false;

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
                ui->pin_error = true;
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

/* Appends text to a JSON string literal, escaping quotes and control characters. */
static size_t json_append_escaped(char *buf, size_t pos, size_t sz, const char *text)
{
    for (const char *p = text; *p && pos + 3 < sz; p++) {
        unsigned char c = (unsigned char)*p;
        if (c == '"' || c == '\\') {
            buf[pos++] = '\\';
            buf[pos++] = (char)c;
        } else if (c >= 0x20) {
            buf[pos++] = (char)c;
        }
    }
    buf[pos] = '\0';
    return pos;
}

bool preset_ui_screen(const preset_ui_t *ui, const char *const *labels, int label_count,
                      screen_update_t *out)
{
    if (!ui || !out) return false;
    const char *tmpl = NULL;
    char *data = out->data_json;
    size_t sz = sizeof(out->data_json);

    switch (ui->state) {
    case PRESET_UI_STATE_PIN_ENTRY:
        tmpl = "pin_entry";
        snprintf(data, sz, "{\"digits\":%d,\"error\":%s}", ui->pin_pos,
                 ui->pin_error ? "true" : "false");
        break;

    case PRESET_UI_STATE_PRESET_LIST: {
        tmpl = "preset_select";
        size_t pos = (size_t)snprintf(data, sz, "{\"presets\":[");
        /* The keypad picks entries 1-9, so the list holds at most nine. */
        int n = label_count < 9 ? label_count : 9;
        for (int i = 0; i < n && pos + 40 < sz; i++) {
            if (i > 0) data[pos++] = ',';
            data[pos++] = '"';
            pos = json_append_escaped(data, pos, sz - 32, labels && labels[i] ? labels[i] : "");
            data[pos++] = '"';
            data[pos] = '\0';
        }
        snprintf(data + pos, sz - pos, "],\"selected\":%d}", ui->selected_preset);
        break;
    }

    case PRESET_UI_STATE_TIMER_ADJUST:
        tmpl = "timer_adjust";
        snprintf(data, sz, "{\"timer_s\":%u}", (unsigned)ui->timer_duration_s);
        break;

    case PRESET_UI_STATE_CONFIRM: {
        tmpl = "start_confirm";
        int idx = ui->selected_preset - 1;
        const char *label =
            (labels && idx >= 0 && idx < label_count && labels[idx]) ? labels[idx] : "";
        size_t pos = (size_t)snprintf(data, sz, "{\"label\":\"");
        pos = json_append_escaped(data, pos, sz - 32, label);
        snprintf(data + pos, sz - pos, "\",\"timer_s\":%u}", (unsigned)ui->timer_duration_s);
        break;
    }

    case PRESET_UI_STATE_GAME_STARTED: return false;
    }

    snprintf(out->template_name, sizeof(out->template_name), "%s", tmpl);
    return true;
}
