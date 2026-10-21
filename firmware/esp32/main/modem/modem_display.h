/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The USB radio modem's on-board OLED task (ESP-IDF only): the boot splash,
 * then the status screen (modem_screen.h) twice a second, redrawn when it
 * changes. A task of its own at the lowest priority, so the serial link and
 * the radio never wait for the display; without an OLED it logs once and
 * ends.
 */
#ifndef ATALAIA_MODEM_DISPLAY_H
#define ATALAIA_MODEM_DISPLAY_H

#include "hal_oled.h"

/*
 * Starts the display task. version is shown on the splash; radio_fault says
 * why the radio is missing (NULL when it works). Both must stay valid.
 */
void modem_display_start(const hal_oled_ops_t *oled, const char *version, const char *radio_fault);

#endif /* ATALAIA_MODEM_DISPLAY_H */
