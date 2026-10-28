/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * Tests for preset_ui: the keypad-driven PIN -> preset -> timer flow.
 */
#include <stdio.h>
#include <string.h>

#include "box_text.h"
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

/* More than nine presets: '0' turns the page (decision M2-1). */
static void test_pages(void)
{
    preset_ui_t ui;
    preset_ui_init(&ui, "1234", 20);
    enter_keys(&ui, "1234#");

    /* Page 1: keys 1-9 pick presets 1-9. */
    enter_keys(&ui, "9");
    CHECK(ui.page == 0);
    CHECK(preset_ui_selected_preset(&ui) == 9);

    /* Page 2 selects its first entry; keys pick 10-18. */
    preset_ui_handle_key(&ui, '0');
    CHECK(ui.page == 1);
    CHECK(preset_ui_selected_preset(&ui) == 10);
    preset_ui_handle_key(&ui, '4');
    CHECK(preset_ui_selected_preset(&ui) == 13);

    /* Page 3 holds 19 and 20 only: 3-9 select nothing. */
    preset_ui_handle_key(&ui, '0');
    CHECK(ui.page == 2);
    CHECK(preset_ui_selected_preset(&ui) == 19);
    preset_ui_handle_key(&ui, '3');
    CHECK(preset_ui_selected_preset(&ui) == 19);
    preset_ui_handle_key(&ui, '2');
    CHECK(preset_ui_selected_preset(&ui) == 20);

    /* After the last page, the first again. */
    preset_ui_handle_key(&ui, '0');
    CHECK(ui.page == 0);
    CHECK(preset_ui_selected_preset(&ui) == 1);

    /* The pick survives the timer screen and back. */
    enter_keys(&ui, "00");
    enter_keys(&ui, "2#");
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_TIMER_ADJUST);
    preset_ui_handle_key(&ui, '*');
    CHECK(ui.page == 2);
    enter_keys(&ui, "###");
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_GAME_STARTED);
    CHECK(preset_ui_selected_preset(&ui) == 20);
}

/* Nine presets or fewer: one page, and '0' changes nothing. */
static void test_one_page_ignores_zero(void)
{
    preset_ui_t ui;
    preset_ui_init(&ui, "1234", 9);
    enter_keys(&ui, "1234#5");
    CHECK(preset_ui_handle_key(&ui, '0'));
    CHECK(ui.page == 0);
    CHECK(preset_ui_selected_preset(&ui) == 5);

    preset_ui_init(&ui, "1234", 0);
    enter_keys(&ui, "1234#0");
    CHECK(ui.page == 0);
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_PRESET_LIST);
}

/* The list's last entry, "Wi-Fi setup" (with the admin PIN as for any game): '#' asks, '#'
 * again confirms, '*' goes back; off unless the box has a setup portal. */
static void test_setup_entry(void)
{
    static const char *const labels[] = {"Bomb", "Domination"};
    preset_ui_t ui;
    screen_update_t su;

    /* Off: the list is the games, and a pick past them selects nothing. */
    preset_ui_init(&ui, "4711", 2);
    enter_keys(&ui, "4711#3");
    CHECK(preset_ui_selected_preset(&ui) == 1);
    CHECK(preset_ui_screen(&ui, labels, 2, &su));
    CHECK(strstr(su.data_json, "setup") == NULL && strstr(su.data_json, "Wi-Fi") == NULL);

    /* On: the entry follows the games, in the box's language. */
    preset_ui_init(&ui, "4711", 2);
    preset_ui_enable_setup(&ui, true);
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_PIN_ENTRY); /* behind the PIN */
    enter_keys(&ui, "4711#");
    CHECK(preset_ui_screen(&ui, labels, 2, &su));
    CHECK(strcmp(su.template_name, "preset_select") == 0);
    CHECK(strcmp(su.data_json,
                 "{\"presets\":[\"Bomb\",\"Domination\",\"Wi-Fi setup\"],\"selected\":1}") == 0);
    box_lang_set(BOX_LANG_PT);
    CHECK(preset_ui_screen(&ui, labels, 2, &su));
    CHECK(strstr(su.data_json, "\"Configurar o Wi-Fi\"") != NULL);
    box_lang_set(BOX_LANG_EN);

    /* '3' selects it; '#' asks, with its own screen. */
    enter_keys(&ui, "3");
    CHECK(preset_ui_selected_preset(&ui) == 3);
    enter_keys(&ui, "#");
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_SETUP_CONFIRM);
    CHECK(preset_ui_screen(&ui, labels, 2, &su));
    CHECK(strcmp(su.template_name, "start_confirm") == 0);
    CHECK(strcmp(su.data_json, "{\"setup\":true}") == 0);

    /* '*' goes back to the list with the entry still selected; a game's '#' is the timer. */
    enter_keys(&ui, "*");
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_PRESET_LIST);
    CHECK(preset_ui_selected_preset(&ui) == 3);
    enter_keys(&ui, "2#");
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_TIMER_ADJUST);

    /* Not confirmed by anything but '#' on the confirmation. */
    preset_ui_handle_key(&ui, '*');
    enter_keys(&ui, "3#");
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_SETUP_CONFIRM);
    CHECK(!preset_ui_handle_key(&ui, '5'));
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_SETUP_CONFIRM);
    enter_keys(&ui, "#");
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_SETUP_REQUESTED);
    CHECK(!preset_ui_screen(&ui, labels, 2, &su));
    CHECK(!preset_ui_handle_key(&ui, '#'));
}

/* With no games at all the entry is the whole list; and past nine entries it goes on the last
 * page. */
static void test_setup_entry_pages(void)
{
    preset_ui_t ui;
    preset_ui_init(&ui, "4711", 0);
    preset_ui_enable_setup(&ui, true);
    enter_keys(&ui, "4711#");
    enter_keys(&ui, "#");
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_SETUP_CONFIRM);

    /* Nine games and the entry: two pages, the entry alone on the second. */
    preset_ui_init(&ui, "4711", 9);
    preset_ui_enable_setup(&ui, true);
    enter_keys(&ui, "4711#");
    enter_keys(&ui, "0");
    CHECK(ui.page == 1);
    CHECK(preset_ui_selected_preset(&ui) == 10);
    enter_keys(&ui, "2");
    CHECK(preset_ui_selected_preset(&ui) == 10); /* nothing there */
    enter_keys(&ui, "##");
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_SETUP_REQUESTED);

    /* Nine games with the entry off stay one page. */
    preset_ui_init(&ui, "4711", 9);
    enter_keys(&ui, "4711#0");
    CHECK(ui.page == 0);
}

/* "Adopt to another field" (decision PKB-4): behind the admin PIN, asks once, off unless the box is
 * adopted and has a radio; after "Wi-Fi setup" when both are on. */
static void test_adopt_entry(void)
{
    static const char *const labels[] = {"Bomb", "Domination"};
    preset_ui_t ui;
    screen_update_t su;

    /* Off: nothing past the games. */
    preset_ui_init(&ui, "4711", 2);
    preset_ui_enable_setup(&ui, true);
    enter_keys(&ui, "4711#4");
    CHECK(preset_ui_selected_preset(&ui) == 1);

    /* On alone: entry 3, in the box's language; it asks with its own screen. */
    preset_ui_init(&ui, "4711", 2);
    preset_ui_enable_adopt(&ui, true);
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_PIN_ENTRY); /* behind the PIN */
    enter_keys(&ui, "4711#");
    CHECK(preset_ui_screen(&ui, labels, 2, &su));
    CHECK(strcmp(su.data_json, "{\"presets\":[\"Bomb\",\"Domination\",\"Change field\"],"
                               "\"selected\":1}") == 0);
    box_lang_set(BOX_LANG_PT);
    CHECK(preset_ui_screen(&ui, labels, 2, &su));
    CHECK(strstr(su.data_json, "\"Mudar de campo\"") != NULL);
    box_lang_set(BOX_LANG_EN);
    enter_keys(&ui, "3#");
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_ADOPT_CONFIRM);
    CHECK(preset_ui_screen(&ui, labels, 2, &su));
    CHECK(strcmp(su.template_name, "start_confirm") == 0);
    CHECK(strcmp(su.data_json, "{\"adopt\":true}") == 0);
    /* '*' goes back with the entry selected; only '#' confirms. */
    enter_keys(&ui, "*");
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_PRESET_LIST);
    CHECK(preset_ui_selected_preset(&ui) == 3);
    enter_keys(&ui, "#");
    CHECK(!preset_ui_handle_key(&ui, '5'));
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_ADOPT_CONFIRM);
    enter_keys(&ui, "#");
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_ADOPT_REQUESTED);
    CHECK(!preset_ui_screen(&ui, labels, 2, &su));
    CHECK(!preset_ui_handle_key(&ui, '#'));

    /* With "Wi-Fi setup" too: setup is entry 3 and asks to set up, adopt is entry 4. */
    preset_ui_init(&ui, "4711", 2);
    preset_ui_enable_setup(&ui, true);
    preset_ui_enable_adopt(&ui, true);
    enter_keys(&ui, "4711#");
    CHECK(preset_ui_screen(&ui, labels, 2, &su));
    CHECK(strstr(su.data_json, "\"Wi-Fi setup\",\"Change field\"") != NULL);
    enter_keys(&ui, "3#");
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_SETUP_CONFIRM);
    enter_keys(&ui, "*4#");
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_ADOPT_CONFIRM);

    /* With no games the entry is the whole list; and a game's '#' is still the timer. */
    preset_ui_init(&ui, "4711", 2);
    preset_ui_enable_adopt(&ui, true);
    enter_keys(&ui, "4711#2#");
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_TIMER_ADJUST);
    preset_ui_init(&ui, "4711", 0);
    preset_ui_enable_adopt(&ui, true);
    enter_keys(&ui, "4711##");
    CHECK(preset_ui_get_state(&ui) == PRESET_UI_STATE_ADOPT_CONFIRM);
}

void run_preset_ui_tests(void)
{
    test_adopt_entry();
    test_setup_entry();
    test_setup_entry_pages();
    test_correct_pin_accepted();
    test_wrong_pin_rejected();
    test_preset_selection();
    test_timer_adjust();
    test_full_flow();
    test_back_key();
    test_pages();
    test_one_page_ignores_zero();
}
