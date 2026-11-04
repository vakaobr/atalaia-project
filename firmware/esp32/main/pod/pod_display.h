/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The I/O pod's on-board OLED task (ESP-IDF only, CONFIG_ATALAIA_OLED_STATUS):
 * dark, except while a phone pairs over Bluetooth (pod_pair.h): the passkey,
 * then the outcome, in the OLED view's three lines (oled_text_pair). A task
 * of its own at the lowest priority, as the modem's (modem_display.c), so the
 * proxy, the radio and Bluetooth never wait for the I2C bus; without an OLED
 * it logs once and ends (the passkey is still in the log).
 */
#ifndef ATALAIA_POD_DISPLAY_H
#define ATALAIA_POD_DISPLAY_H

#include "hal_oled.h"
#include "oled_view.h"

/* Starts the display task; read(out) gives what to show now (called from that task: it must
 * copy under its own lock). */
void pod_display_start(const hal_oled_ops_t *oled, void (*read)(oled_pair_view_t *out));

#endif /* ATALAIA_POD_DISPLAY_H */
