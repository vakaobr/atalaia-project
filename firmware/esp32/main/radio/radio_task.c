/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Radio FreeRTOS task: TX/RX loop on core 0, priority 3.
 */
#include "radio_task.h"

#include <string.h>

#ifdef ESP_PLATFORM

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"

static const char *TAG = "radio_task";

static QueueHandle_t tx_queue;
static QueueHandle_t rx_queue;
static const hal_t *radio_hal;

static void radio_task_loop(void *arg)
{
    (void)arg;
    ESP_LOGI(TAG, "radio task started");

    for (;;) {
        /* Check for outbound packets. */
        radio_tx_msg_t tx_msg;
        if (xQueueReceive(tx_queue, &tx_msg, 0) == pdTRUE) {
            if (radio_hal->radio->duty_cycle_remaining_ms() > 0) {
                int rc = radio_hal->radio->send(tx_msg.data, tx_msg.len);
                if (rc != 0) {
                    ESP_LOGW(TAG, "TX failed");
                }
            } else {
                ESP_LOGW(TAG, "TX skipped: duty-cycle exhausted");
            }
        }

        /* Check for inbound packets (50ms timeout). */
        uint8_t rx_buf[RADIO_MAX_PKT_LEN];
        int8_t rssi = 0;
        size_t rx_len = radio_hal->radio->recv(rx_buf, sizeof(rx_buf), &rssi);
        if (rx_len > 0) {
            radio_rx_msg_t rx_msg;
            memcpy(rx_msg.data, rx_buf, rx_len);
            rx_msg.len = rx_len;
            rx_msg.rssi = rssi;
            rx_msg.timestamp_ms = (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS);
            if (xQueueSend(rx_queue, &rx_msg, 0) != pdTRUE) {
                ESP_LOGW(TAG, "RX queue full, packet dropped");
            }
        }

        vTaskDelay(pdMS_TO_TICKS(10));
    }
}

void radio_task_start(const hal_t *hal)
{
    radio_hal = hal;
    tx_queue = xQueueCreate(RADIO_TX_QUEUE_LEN, sizeof(radio_tx_msg_t));
    rx_queue = xQueueCreate(RADIO_RX_QUEUE_LEN, sizeof(radio_rx_msg_t));
    xTaskCreatePinnedToCore(radio_task_loop, "radio", 4096, NULL, 3, NULL, 0);
}

bool radio_task_send(const uint8_t *data, size_t len)
{
    if (len == 0 || len > RADIO_MAX_PKT_LEN || tx_queue == NULL) return false;
    radio_tx_msg_t msg;
    memcpy(msg.data, data, len);
    msg.len = len;
    return xQueueSend(tx_queue, &msg, 0) == pdTRUE;
}

bool radio_task_recv(radio_rx_msg_t *msg)
{
    if (rx_queue == NULL || msg == NULL) return false;
    return xQueueReceive(rx_queue, msg, 0) == pdTRUE;
}

#else
/* ---- Stub build (no FreeRTOS) ------------------------------------------- */

void radio_task_start(const hal_t *hal)
{
    (void)hal;
}

bool radio_task_send(const uint8_t *data, size_t len)
{
    (void)data;
    (void)len;
    return false;
}

bool radio_task_recv(radio_rx_msg_t *msg)
{
    (void)msg;
    return false;
}

#endif /* ESP_PLATFORM */
