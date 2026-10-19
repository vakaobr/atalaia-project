/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The I/O pod's task (ESP-IDF only, CONFIG_ATALAIA_POD_MODE): the USB link
 * (the ESP32-S3's USB-Serial-JTAG CDC port, decision PF3), the Bluetooth LE
 * link (pod_ble_nimble.c), the capabilities (pod_caps.c), the radio task and
 * the proxy (pod.c), all on one FreeRTOS task (core 1, priority 5, ADR-P3-3);
 * tones play on an audio task (core 0, priority 2).
 */
#ifndef ATALAIA_POD_TASK_H
#define ATALAIA_POD_TASK_H

#include "hal/hal.h"
#include "pod_caps.h"

/*
 * Starts the links and the pod task. hal->radio is NULL when no radio chip
 * answered at boot (has_radio false in IDENT; RADIO_TX answered no_radio);
 * cfg says which of the other parts are fitted.
 */
void pod_task_start(const hal_t *hal, const pod_caps_config_t *cfg);

#endif /* ATALAIA_POD_TASK_H */
