/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * Tests for preset_ui: the keypad-driven PIN -> preset -> timer flow.
 */
#include <stdio.h>
#include <string.h>

#include "check.h"
#include "preset_ui.h"

/* ---- helpers ---- */

static void enter_keys(preset_ui_t *ui, const char *keys)
{
    for (const char *k = keys; *k; k++) {
        preset_ui_handle_key(ui, *k);
    }
}

/* ---- tests ---- */

static void test_correct_pin_accepted(void)
{
    preset_ui_t ui;
    preset_ui_init(&ui, "1234", 5);

    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_PIN_ENTRY);

    enter_keys(&ui, "1234#");

    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_PRESET_LIST);
    CHECK(ui.pin_accepted);
}

static void test_wrong_pin_rejected(void)
{
    preset_ui_t ui;
    preset_ui_init(&ui, "1234", 5);

    enter_keys(&ui, "0000#");

    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_PIN_ENTRY);
    CHECK(!ui.pin_accepted);
    /* Buffer should be cleared for retry. */
    CHECK(ui.pin_pos == 0);
}

static void test_preset_selection(void)
{
    preset_ui_t ui;
    preset_ui_init(&ui, "1234", 5);

    /* Enter correct PIN first. */
    enter_keys(&ui, "1234#");
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_PRESET_LIST);

    /* Select preset 2. */
    enter_keys(&ui, "2#");

    CHECK(preset_ui_selected_preset(&ui) == 2);
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_TIMER_ADJUST);
}

static void test_timer_adjust(void)
{
    preset_ui_t ui;
    preset_ui_init(&ui, "1234", 5);

    /* PIN -> preset select. */
    enter_keys(&ui, "1234#");
    enter_keys(&ui, "1#");
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_TIMER_ADJUST);

    uint32_t base = preset_ui_timer_duration(&ui);

    /* '2' = up: add 5 minutes (300 seconds). */
    preset_ui_handle_key(&ui, '2');
    CHECK(preset_ui_timer_duration(&ui) == base + 300);

    /* '8' = down: subtract 5 minutes. */
    preset_ui_handle_key(&ui, '8');
    CHECK(preset_ui_timer_duration(&ui) == base);
}

static void test_full_flow(void)
{
    preset_ui_t ui;
    preset_ui_init(&ui, "9999", 3);

    /* PIN entry. */
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_PIN_ENTRY);
    enter_keys(&ui, "9999#");
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_PRESET_LIST);

    /* Preset selection. */
    enter_keys(&ui, "3#");
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_TIMER_ADJUST);

    /* Timer adjust: add 5 min, then confirm. */
    preset_ui_handle_key(&ui, '2');
    enter_keys(&ui, "#");
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_CONFIRM);

    /* Final confirm. */
    enter_keys(&ui, "#");
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_GAME_STARTED);
    CHECK(preset_ui_selected_preset(&ui) == 3);
}

static void test_back_key(void)
{
    preset_ui_t ui;
    preset_ui_init(&ui, "1234", 5);

    /* PIN -> list -> timer_adjust -> back to list -> back to PIN. */
    enter_keys(&ui, "1234#");
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_PRESET_LIST);

    enter_keys(&ui, "1#");
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_TIMER_ADJUST);

    /* '*' goes back to preset list. */
    preset_ui_handle_key(&ui, '*');
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_PRESET_LIST);

    /* '*' again goes back to PIN entry. */
    preset_ui_handle_key(&ui, '*');
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_PIN_ENTRY);
}

void run_preset_ui_tests(void)
{
    test_correct_pin_accepted();
    test_wrong_pin_rejected();
    test_preset_selection();
    test_timer_adjust();
    test_full_flow();
    test_back_key();
}
