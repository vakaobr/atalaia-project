/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The Heltec V4 front-end module pin sequence (main/hal/board_fem.c): the
 * LDO powered first and high (it was held low before), the revision's mode
 * pin, then the chip enable; the reverse at power-off; and the check that
 * no team button shares a FEM pin (button 2 left GPIO 5 for the V4.3).
 * Also the LED ring's brightness scaling (hal_leds.h).
 */
#include "check.h"
#include "hal/board_fem.h"
#include "hal/hal_leds.h"

static const board_fem_pins_t v43 = {BOARD_FEM_KCT8103L, 7, 2, -1, 5};
static const board_fem_pins_t v42 = {BOARD_FEM_GC1109, 7, 2, 46, -1};

void run_board_fem_tests(void)
{
    board_pin_step_t s[BOARD_FEM_MAX_STEPS];

    /* V4.3: LDO on (and settle), CTX low = receive LNA, then enable. */
    CHECK(board_fem_power_on(&v43, s, BOARD_FEM_MAX_STEPS) == 3);
    CHECK(s[0].pin == 7 && s[0].level == 1 && s[0].delay_us == BOARD_FEM_LDO_SETTLE_US);
    CHECK(s[1].pin == 5 && s[1].level == 0);
    CHECK(s[2].pin == 2 && s[2].level == 1);
    CHECK(board_fem_power_off(&v43, s, BOARD_FEM_MAX_STEPS) == 3);
    CHECK(s[0].pin == 2 && s[0].level == 0);
    CHECK(s[2].pin == 7 && s[2].level == 0);

    /* V4.2: LDO on, CPS high = full PA, then enable; GPIO 5 untouched. */
    CHECK(board_fem_power_on(&v42, s, BOARD_FEM_MAX_STEPS) == 3);
    CHECK(s[0].pin == 7 && s[0].level == 1);
    CHECK(s[1].pin == 46 && s[1].level == 1);
    CHECK(s[2].pin == 2 && s[2].level == 1);
    CHECK(board_fem_power_off(&v42, s, BOARD_FEM_MAX_STEPS) == 3);
    CHECK(s[1].pin == 46 && s[1].level == 0);

    /* Unassigned pins are skipped; no FEM, no steps; the buffer limit holds. */
    board_fem_pins_t partial = {BOARD_FEM_KCT8103L, 7, 2, -1, -1};
    CHECK(board_fem_power_on(&partial, s, BOARD_FEM_MAX_STEPS) == 2);
    board_fem_pins_t none = {BOARD_FEM_NONE, 7, 2, -1, 5};
    CHECK(board_fem_power_on(&none, s, BOARD_FEM_MAX_STEPS) == 0);
    CHECK(board_fem_power_on(&v43, s, 1) == 1 && s[0].pin == 7);

    /* The default buttons (4, 39, 33, 34) clash with neither revision; the old
     * button 2 on GPIO 5 clashes with the V4.3 only. */
    const int buttons[] = {4, 39, 33, 34};
    CHECK(board_fem_conflict(&v43, buttons, 4) == -1);
    CHECK(board_fem_conflict(&v42, buttons, 4) == -1);
    const int old_buttons[] = {4, 5, -1, 34};
    CHECK(board_fem_conflict(&v43, old_buttons, 4) == 5);
    CHECK(board_fem_conflict(&v42, old_buttons, 4) == -1);
    const int on_ldo[] = {7};
    CHECK(board_fem_conflict(&v42, on_ldo, 1) == 7);
    CHECK(board_fem_conflict(&none, old_buttons, 4) == -1);

    CHECK(board_fem_name(BOARD_FEM_KCT8103L)[0] == 'K');

    /* The LED ring's brightness (WS2812 has none of its own): percent, clamped, rounded. */
    CHECK(hal_led_scale(255, 100) == 255);
    CHECK(hal_led_scale(255, 40) == 102);
    CHECK(hal_led_scale(255, 0) == 0);
    CHECK(hal_led_scale(200, 150) == 200);
    CHECK(hal_led_scale(200, -5) == 0);
    CHECK(hal_led_scale(1, 50) == 1);
}
