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
static QueueHandle_t result_queue;
static QueueHandle_t channel_queue; /* length 1: the latest requested channel */
static volatile uint32_t duty_remaining_ms;
static const hal_t *radio_hal;

static void radio_task_loop(void *arg)
{
    (void)arg;
    ESP_LOGI(TAG, "radio task started");

    for (;;) {
        /* Apply a channel change requested by another task. */
        uint32_t freq_hz;
        if (xQueueReceive(channel_queue, &freq_hz, 0) == pdTRUE) {
            if (radio_hal->radio->set_channel(freq_hz) != 0) {
                ESP_LOGW(TAG, "channel %lu Hz refused", (unsigned long)freq_hz);
            }
        }
        duty_remaining_ms = radio_hal->radio->duty_cycle_remaining_ms();

        /* Check for outbound packets. */
        radio_tx_msg_t tx_msg;
        if (xQueueReceive(tx_queue, &tx_msg, 0) == pdTRUE) {
            radio_tx_status_t status = RADIO_TX_RESULT_OK;
            if (radio_hal->radio->duty_cycle_remaining_ms() > 0) {
                int rc = radio_hal->radio->send(tx_msg.data, tx_msg.len);
                if (rc != 0) {
                    ESP_LOGW(TAG, "TX failed (%d)", rc);
                    status = RADIO_TX_RESULT_ERROR;
                }
            } else {
                ESP_LOGW(TAG, "TX skipped: duty-cycle exhausted");
                status = RADIO_TX_RESULT_DUTY_CYCLE;
            }
            if (tx_msg.tag != 0) {
                radio_tx_result_t result = {.tag = tx_msg.tag, .status = status};
                if (xQueueSend(result_queue, &result, 0) != pdTRUE) {
                    ESP_LOGW(TAG, "TX result queue full, result dropped");
                }
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
    result_queue = xQueueCreate(RADIO_TX_RESULT_QUEUE_LEN, sizeof(radio_tx_result_t));
    channel_queue = xQueueCreate(1, sizeof(uint32_t));
    duty_remaining_ms = radio_hal->radio->duty_cycle_remaining_ms();
    xTaskCreatePinnedToCore(radio_task_loop, "radio", 4096, NULL, 3, NULL, 0);
}

static bool enqueue(const uint8_t *data, size_t len, uint32_t tag)
{
    if (len == 0 || len > RADIO_MAX_PKT_LEN || tx_queue == NULL) return false;
    radio_tx_msg_t msg;
    memcpy(msg.data, data, len);
    msg.len = len;
    msg.tag = tag;
    return xQueueSend(tx_queue, &msg, 0) == pdTRUE;
}

bool radio_task_send(const uint8_t *data, size_t len)
{
    return enqueue(data, len, 0);
}

bool radio_task_send_tagged(const uint8_t *data, size_t len, uint32_t tag)
{
    if (tag == 0) return false;
    return enqueue(data, len, tag);
}

bool radio_task_tx_result(radio_tx_result_t *result)
{
    if (result_queue == NULL || result == NULL) return false;
    return xQueueReceive(result_queue, result, 0) == pdTRUE;
}

bool radio_task_set_channel(uint32_t freq_hz)
{
    if (channel_queue == NULL) return false;
    return xQueueOverwrite(channel_queue, &freq_hz) == pdTRUE;
}

uint32_t radio_task_duty_remaining_ms(void)
{
    return duty_remaining_ms;
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

bool radio_task_send_tagged(const uint8_t *data, size_t len, uint32_t tag)
{
    (void)data;
    (void)len;
    (void)tag;
    return false;
}

bool radio_task_tx_result(radio_tx_result_t *result)
{
    (void)result;
    return false;
}

bool radio_task_set_channel(uint32_t freq_hz)
{
    (void)freq_hz;
    return false;
}

uint32_t radio_task_duty_remaining_ms(void)
{
    return 0;
}

bool radio_task_recv(radio_rx_msg_t *msg)
{
    (void)msg;
    return false;
}

#endif /* ESP_PLATFORM */
