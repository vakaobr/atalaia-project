/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Board power at boot, for the Field Box and the USB radio modem (same board).
 */

#ifdef ESP_PLATFORM

#include "hal_esp.h"

#include "driver/gpio.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"

void hal_esp_board_power_on(void)
{
#if CONFIG_ATALAIA_VEXT_CTL_PIN >= 0
    /* Vext is active low on the Heltec V4: low = the on-board OLED, the LoRa
     * front end and anything else wired to Vext are powered. */
    gpio_config_t cfg = {.pin_bit_mask = 1ULL << CONFIG_ATALAIA_VEXT_CTL_PIN,
                         .mode = GPIO_MODE_OUTPUT};
    gpio_config(&cfg);
    gpio_set_level(CONFIG_ATALAIA_VEXT_CTL_PIN, 0);
    vTaskDelay(pdMS_TO_TICKS(20)); /* let the rail and the parts on it come up */
    ESP_LOGI("hal", "Vext on (GPIO %d low)", CONFIG_ATALAIA_VEXT_CTL_PIN);
#endif
}

#endif /* ESP_PLATFORM */
