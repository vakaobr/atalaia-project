/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Entry point of the USB radio modem firmware (CONFIG_ATALAIA_MODEM_MODE).
 * A Heltec V4.3 plugged into the field controller over USB: radio, AES-CCM,
 * dedupe and duty cycle on the ESP32-S3; no Lua, no screens, no presets
 * (ADR-P2-4). Build it with `python tools/docker_fw.py modem`.
 */
#include <string.h>

#include "atalaia/version.h"
#include "esp_log.h"
#include "hal/hal.h"
#include "modem_task.h"
#include "radio/radio_task.h"

static const char *TAG = "atalaia-modem";

extern const hal_radio_ops_t hal_esp_radio_ops;
void hal_esp_board_power_on(void);

void app_main(void)
{
    static hal_t hal;
    memset(&hal, 0, sizeof(hal));
    hal.radio = &hal_esp_radio_ops;

    ESP_LOGI(TAG, "Atalaia USB radio modem, core %s", atalaia_version());
    hal_esp_board_power_on();
    if (hal.radio->init() != 0) {
        ESP_LOGW(TAG, "radio: not available (no SX1262); TX frames get status no_radio");
        hal.radio = NULL;
    } else {
        radio_task_start(&hal);
    }
    modem_task_start(&hal);
}
