/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#include "preset_ui.h"

#include <stdio.h>
#include <string.h>

#include "box_text.h"

/* Entries of the list: the games, and "Wi-Fi setup" after them when it is on. */
static int entry_count(const preset_ui_t *ui)
{
    return ui->preset_count + (ui->setup_entry ? 1 : 0);
}

/* Is the selected entry "Wi-Fi setup"? */
static bool setup_selected(const preset_ui_t *ui)
{
    return ui->setup_entry && ui->selected_preset == ui->preset_count + 1;
}

/* Pages of the preset list (at least one, which may be empty). */
static int page_count(const preset_ui_t *ui)
{
    int n = entry_count(ui);
    if (n <= PRESET_UI_PAGE_SIZE) return 1;
    return (n + PRESET_UI_PAGE_SIZE - 1) / PRESET_UI_PAGE_SIZE;
}

void preset_ui_enable_setup(preset_ui_t *ui, bool on)
{
    ui->setup_entry = on;
}

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

void preset_ui_set_guard(preset_ui_t *ui, admin_pin_t *guard)
{
    ui->guard = guard;
}

/* The PIN typed: through the box's check when it has one (admin_pin.h). */
static bool pin_ok(preset_ui_t *ui)
{
    if (ui->guard == NULL) return strcmp(ui->pin_buffer, ui->admin_pin) == 0;
    admin_pin_result_t r = admin_pin_check(ui->guard, ui->pin_buffer);
    ui->no_pin = r == ADMIN_PIN_NOT_SET;
    ui->locked_min = admin_pin_wait_min(ui->guard);
    return r == ADMIN_PIN_OK;
}

bool preset_ui_handle_key(preset_ui_t *ui, char key)
{
    if (!ui) return false;
    ui->pin_error = false;
    ui->locked_min = 0;
    ui->no_pin = false;

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
            if (pin_ok(ui)) {
                ui->pin_accepted = true;
                ui->state = PRESET_UI_STATE_PRESET_LIST;
            } else {
                /* Wrong PIN: reset buffer. */
                ui->pin_pos = 0;
                ui->pin_buffer[0] = '\0';
                ui->pin_accepted = false;
                ui->pin_error = ui->locked_min == 0 && !ui->no_pin;
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
            int idx = ui->page * PRESET_UI_PAGE_SIZE + (key - '0');
            if (idx <= entry_count(ui)) {
                ui->selected_preset = idx;
            }
            return true;
        }
        if (key == '0') {
            /* The next page, then the first again; one page: nothing to turn. */
            int pages = page_count(ui);
            if (pages > 1) {
                ui->page = (ui->page + 1) % pages;
                ui->selected_preset = ui->page * PRESET_UI_PAGE_SIZE + 1;
            }
            return true;
        }
        if (key == '#') {
            ui->state =
                setup_selected(ui) ? PRESET_UI_STATE_SETUP_CONFIRM : PRESET_UI_STATE_TIMER_ADJUST;
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

    case PRESET_UI_STATE_SETUP_CONFIRM:
        if (key == '#') {
            ui->state = PRESET_UI_STATE_SETUP_REQUESTED;
            return true;
        }
        if (key == '*') {
            ui->state = PRESET_UI_STATE_PRESET_LIST;
            return true;
        }
        return false;

    case PRESET_UI_STATE_GAME_STARTED:
    case PRESET_UI_STATE_SETUP_REQUESTED: return false;
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
        if (ui->no_pin) {
            snprintf(data, sz, "{\"digits\":%d,\"error\":false,\"no_pin\":true}", ui->pin_pos);
        } else if (ui->locked_min > 0) {
            snprintf(data, sz, "{\"digits\":%d,\"error\":false,\"locked_min\":%lu}", ui->pin_pos,
                     (unsigned long)ui->locked_min);
        } else {
            snprintf(data, sz, "{\"digits\":%d,\"error\":%s}", ui->pin_pos,
                     ui->pin_error ? "true" : "false");
        }
        break;

    case PRESET_UI_STATE_PRESET_LIST: {
        tmpl = "preset_select";
        size_t pos = (size_t)snprintf(data, sz, "{\"presets\":[");
        /* The keypad picks entries 1-9, so the list holds one page of at most nine. */
        int first = ui->page * PRESET_UI_PAGE_SIZE;
        int total = label_count + (ui->setup_entry ? 1 : 0);
        int n = total - first;
        if (n > PRESET_UI_PAGE_SIZE) n = PRESET_UI_PAGE_SIZE;
        for (int i = 0; i < n && pos + 48 < sz; i++) {
            const char *label = first + i >= label_count      ? box_text(TX_SETUP_ITEM)
                                : labels && labels[first + i] ? labels[first + i]
                                                              : "";
            if (i > 0) data[pos++] = ',';
            data[pos++] = '"';
            pos = json_append_escaped(data, pos, sz - 40, label);
            data[pos++] = '"';
            data[pos] = '\0';
        }
        int pages = page_count(ui);
        int selected = ui->selected_preset - first;
        if (pages > 1) {
            snprintf(data + pos, sz - pos, "],\"selected\":%d,\"page\":%d,\"pages\":%d}", selected,
                     ui->page + 1, pages);
        } else {
            snprintf(data + pos, sz - pos, "],\"selected\":%d}", selected);
        }
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

    case PRESET_UI_STATE_SETUP_CONFIRM:
        tmpl = "start_confirm";
        snprintf(data, sz, "{\"setup\":true}");
        break;

    case PRESET_UI_STATE_GAME_STARTED:
    case PRESET_UI_STATE_SETUP_REQUESTED: return false;
    }

    snprintf(out->template_name, sizeof(out->template_name), "%s", tmpl);
    return true;
}
