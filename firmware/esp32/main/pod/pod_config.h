/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The I/O pod's settings from Kconfig (menu "I/O pod", Kconfig.projbuild),
 * with the same defaults for the host builds. The pod uses the Field Box's
 * pins for its buttons, keypad expander, LED ring, NFC reader, battery gauge,
 * amplifier and radio; the display's pins are free (no display on a pod).
 */
#ifndef ATALAIA_POD_CONFIG_H
#define ATALAIA_POD_CONFIG_H

#ifdef ESP_PLATFORM
#include "sdkconfig.h"
#endif

/* A team button's colour, or "": button N is the game's N-th team (PF6). */
#ifndef CONFIG_ATALAIA_POD_BTN1_TEAM
#define CONFIG_ATALAIA_POD_BTN1_TEAM ""
#endif
#ifndef CONFIG_ATALAIA_POD_BTN2_TEAM
#define CONFIG_ATALAIA_POD_BTN2_TEAM ""
#endif
#ifndef CONFIG_ATALAIA_POD_BTN3_TEAM
#define CONFIG_ATALAIA_POD_BTN3_TEAM ""
#endif
#ifndef CONFIG_ATALAIA_POD_BTN4_TEAM
#define CONFIG_ATALAIA_POD_BTN4_TEAM ""
#endif

/* The enclosure switch: a GPIO with its pull-up, -1 for none (decision PF8). */
#ifndef CONFIG_ATALAIA_POD_TAMPER_PIN
#define CONFIG_ATALAIA_POD_TAMPER_PIN 47
#endif

#ifndef CONFIG_ATALAIA_MODEM_EPOCH_WINDOW
#define CONFIG_ATALAIA_MODEM_EPOCH_WINDOW 16
#endif

/* Kconfig leaves a bool that is off undefined: 0/1 macros for the code. */
#ifdef ESP_PLATFORM
#ifdef CONFIG_ATALAIA_POD_TAMPER_OPEN_HIGH
#define POD_TAMPER_OPEN_LEVEL 1
#else
#define POD_TAMPER_OPEN_LEVEL 0
#endif
#ifdef CONFIG_ATALAIA_POD_BLE
#define POD_BLE_ENABLED 1
#else
#define POD_BLE_ENABLED 0
#endif
#ifdef CONFIG_ATALAIA_POD_BLE_ENCRYPTED
#define POD_BLE_ENCRYPTED 1
#else
#define POD_BLE_ENCRYPTED 0
#endif
#else /* host builds: the defaults */
#define POD_TAMPER_OPEN_LEVEL 1
#define POD_BLE_ENABLED       1
#define POD_BLE_ENCRYPTED     1
#endif

#endif /* ATALAIA_POD_CONFIG_H */
