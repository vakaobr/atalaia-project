/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

#ifndef HAL_H
#define HAL_H

#include "hal_audio.h"
#include "hal_battery.h"
#include "hal_buttons.h"
#include "hal_display.h"
#include "hal_keypad.h"
#include "hal_leds.h"
#include "hal_nfc.h"
#include "hal_radio.h"

typedef struct {
    const hal_button_ops_t *buttons;
    const hal_keypad_ops_t *keypad;
    const hal_led_ops_t *leds;
    const hal_display_ops_t *display;
    const hal_nfc_ops_t *nfc;
    const hal_audio_ops_t *audio;
    const hal_battery_ops_t *battery;
    const hal_radio_ops_t *radio;
} hal_t;

#endif /* HAL_H */
