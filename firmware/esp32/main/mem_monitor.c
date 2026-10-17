/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#include "mem_monitor.h"

#ifdef ESP_PLATFORM

#include "esp_heap_caps.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "mem_monitor";

static void mem_monitor_task(void *arg)
{
    (void)arg;
    for (;;) {
        multi_heap_info_t dram;
        heap_caps_get_info(&dram, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
        ESP_LOGI(TAG, "DRAM free=%u min=%u largest=%u", (unsigned)dram.total_free_bytes,
                 (unsigned)dram.minimum_free_bytes, (unsigned)dram.largest_free_block);

        multi_heap_info_t psram;
        heap_caps_get_info(&psram, MALLOC_CAP_SPIRAM);
        if (psram.total_free_bytes > 0) {
            ESP_LOGI(TAG, "PSRAM free=%u min=%u", (unsigned)psram.total_free_bytes,
                     (unsigned)psram.minimum_free_bytes);
        }

        vTaskDelay(pdMS_TO_TICKS(10000));
    }
}

void mem_monitor_start(void)
{
    xTaskCreatePinnedToCore(mem_monitor_task, "mem_mon", 2048, NULL, 1, NULL, 0);
}

#else

void mem_monitor_start(void)
{
    /* No-op in stub builds. */
}

#endif
