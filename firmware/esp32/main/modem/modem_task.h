/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * USB radio modem task (ESP-IDF only): owns the serial link to the field
 * controller and moves frames between it, the modem logic (modem.c) and
 * the radio task. Built only when CONFIG_ATALAIA_MODEM_MODE is set.
 */
#ifndef ATALAIA_MODEM_TASK_H
#define ATALAIA_MODEM_TASK_H

#include "hal/hal.h"

/*
 * Starts the serial link and the modem task. hal->radio is NULL when no
 * radio chip answered at boot: the modem still runs, reports "radio":
 * "none" in IDENT and STATUS, and answers every TX with MODEM_TX_NO_RADIO.
 */
void modem_task_start(const hal_t *hal);

#endif /* ATALAIA_MODEM_TASK_H */
