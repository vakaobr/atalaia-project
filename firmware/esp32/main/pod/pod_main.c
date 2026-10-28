/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Entry point of the I/O pod firmware (CONFIG_ATALAIA_POD_MODE, ADR-P3-3):
 * a Heltec WiFi LoRa 32 V4 that lends its buttons, keypad, LED ring, sound,
 * NFC reader, enclosure switch and LoRa radio to a phone over USB or
 * Bluetooth LE (protocol/capability-proxy.md). No Lua, no screens, no
 * presets, no Wi-Fi. Build it with `python tools/docker_fw.py pod`.
 *
 * Boot: NVS (Bluetooth bonds, PHY calibration), Vext on, then each part of
 * the Field Box's hardware abstraction; a part that is missing is logged and
 * left out of IDENT. The radio's front-end module (V4.3 KCT8103L or V4.2
 * GC1109, Kconfig) is powered by the radio HAL once the SX1262 answers.
 */
#include <string.h>

#include "atalaia/version.h"
#include "esp_app_desc.h"
#include "esp_log.h"
#include "fw_layout_esp.h"
#include "hal/hal.h"
#include "hal/esp/hal_esp.h"
#include "nvs_flash.h"
#include "pod_caps.h"
#include "pod_config.h"
#include "pod_task.h"
#include "radio/radio_task.h"
#include "sdkconfig.h"

static const char *TAG = "atalaia-pod";

extern const hal_button_ops_t hal_esp_button_ops;
extern const hal_keypad_ops_t hal_esp_keypad_ops;
extern const hal_led_ops_t hal_esp_led_ops;
extern const hal_nfc_ops_t hal_esp_nfc_ops;
extern const hal_audio_ops_t hal_esp_audio_ops;
extern const hal_battery_ops_t hal_esp_battery_ops;
extern const hal_radio_ops_t hal_esp_radio_ops;

#ifndef CONFIG_ATALAIA_LED_COUNT
#define CONFIG_ATALAIA_LED_COUNT 24
#endif

void app_main(void)
{
    static hal_t hal;
    memset(&hal, 0, sizeof(hal));
    ESP_LOGI(TAG, "Atalaia I/O pod %s, core %s", esp_app_get_description()->version,
             atalaia_version());

    /* A pod has no storage to lose: a table other than this firmware's is logged only. */
    fw_layout_esp_check(NULL, 0);

    /* NVS: NimBLE keeps its bonds there, the PHY its calibration. */
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        nvs_flash_erase();
        nvs_flash_init();
    }

    hal_esp_board_power_on(); /* Vext (GPIO 36 low) before anything is probed */

    static const int button_pins[POD_BUTTONS] = {CONFIG_ATALAIA_BTN1_PIN, CONFIG_ATALAIA_BTN2_PIN,
                                                 CONFIG_ATALAIA_BTN3_PIN, CONFIG_ATALAIA_BTN4_PIN};
    static const char *const teams[POD_BUTTONS] = {
        CONFIG_ATALAIA_POD_BTN1_TEAM, CONFIG_ATALAIA_POD_BTN2_TEAM, CONFIG_ATALAIA_POD_BTN3_TEAM,
        CONFIG_ATALAIA_POD_BTN4_TEAM};
    pod_caps_config_t cfg;
    memset(&cfg, 0, sizeof(cfg));

    hal.buttons = &hal_esp_button_ops;
    if (hal.buttons->init() != 0) {
        ESP_LOGW(TAG, "team buttons: GPIO setup failed");
        hal.buttons = NULL;
    } else {
        for (int i = 0; i < POD_BUTTONS; i++) {
            cfg.button[i] = button_pins[i] >= 0;
            cfg.team[i] = teams[i][0] != '\0' ? teams[i] : NULL;
        }
    }
    hal.keypad = &hal_esp_keypad_ops;
    cfg.keypad = hal.keypad->init() == 0;
    if (!cfg.keypad) ESP_LOGW(TAG, "keypad: not available");
#if CONFIG_ATALAIA_KP_P7_BUTTON > 0
    /* That button is on the keypad expander's P7: fitted when the expander is. */
    if (hal.buttons != NULL && cfg.keypad) cfg.button[CONFIG_ATALAIA_KP_P7_BUTTON - 1] = true;
#endif
    hal.leds = &hal_esp_led_ops;
    cfg.leds = CONFIG_ATALAIA_LED_PIN >= 0 && CONFIG_ATALAIA_LED_COUNT > 0 && hal.leds->init() == 0;
    cfg.led_count = CONFIG_ATALAIA_LED_COUNT;
    if (!cfg.leds) ESP_LOGW(TAG, "LED ring: not available");
    hal.nfc = &hal_esp_nfc_ops;
    cfg.nfc = hal.nfc->init() == 0;
    if (!cfg.nfc) ESP_LOGW(TAG, "NFC: not available");
    hal.audio = &hal_esp_audio_ops;
    /* The audio HAL "succeeds" with no pins (audio disabled): not fitted then. */
    cfg.audio = CONFIG_ATALAIA_AUDIO_BCLK_PIN >= 0 && CONFIG_ATALAIA_AUDIO_LRCLK_PIN >= 0 &&
                CONFIG_ATALAIA_AUDIO_DOUT_PIN >= 0 && hal.audio->init() == 0;
    if (!cfg.audio) ESP_LOGW(TAG, "audio: not available");
    hal.battery = &hal_esp_battery_ops;
    if (hal.battery->init() != 0) hal.battery = NULL; /* battery level unknown */
    cfg.tamper = CONFIG_ATALAIA_POD_TAMPER_PIN >= 0;

    hal.radio = &hal_esp_radio_ops;
    if (hal.radio->init() != 0) {
        ESP_LOGW(TAG, "radio: not available (no SX1262); RADIO_TX gets status no_radio");
        hal.radio = NULL;
    } else {
        radio_task_start(&hal);
    }
    pod_task_start(&hal, &cfg);
}
