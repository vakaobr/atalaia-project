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
static QueueHandle_t measure_queue; /* length 1: a measurement request */
static QueueHandle_t measure_done;  /* length 1: its outcome */
static volatile bool measuring;

typedef struct {
    uint32_t freq_hz;
    uint16_t dwell_ms;
    bool cad;
} measure_req_t;

typedef struct {
    int rc;
    noise_result_t result;
} measure_out_t;
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

        /* A noise measurement (USB modem MEASURE): listens only, then back
         * to the game channel inside the HAL. */
        measure_req_t req;
        if (xQueueReceive(measure_queue, &req, 0) == pdTRUE) {
            measure_out_t out = {.rc = -1};
            memset(&out.result, 0, sizeof(out.result));
            out.rc = radio_hal->radio->measure(req.freq_hz, req.dwell_ms, req.cad, &out.result);
            xQueueOverwrite(measure_done, &out);
            measuring = false;
        }

        /* Check for outbound packets. */
        radio_tx_msg_t tx_msg;
        if (xQueueReceive(tx_queue, &tx_msg, 0) == pdTRUE) {
            radio_tx_status_t status = RADIO_TX_RESULT_OK;
            if (radio_hal->radio->duty_cycle_remaining_ms() > 0) {
                int rc = radio_hal->radio->send(tx_msg.data, tx_msg.len);
                if (rc == -3) {
                    /* This packet's time on air does not fit in what is left. */
                    ESP_LOGW(TAG, "TX skipped: duty-cycle budget too small for %u bytes",
                             (unsigned)tx_msg.len);
                    status = RADIO_TX_RESULT_DUTY_CYCLE;
                } else if (rc != 0) {
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
    measure_queue = xQueueCreate(1, sizeof(measure_req_t));
    measure_done = xQueueCreate(1, sizeof(measure_out_t));
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

bool radio_task_measure_start(uint32_t freq_hz, uint16_t dwell_ms, bool cad)
{
    if (measure_queue == NULL || radio_hal == NULL || radio_hal->radio->measure == NULL ||
        measuring) {
        return false;
    }
    measure_req_t req = {.freq_hz = freq_hz, .dwell_ms = dwell_ms, .cad = cad};
    measuring = true;
    if (xQueueSend(measure_queue, &req, 0) != pdTRUE) {
        measuring = false;
        return false;
    }
    return true;
}

bool radio_task_measure_result(noise_result_t *out, int *rc)
{
    if (measure_done == NULL || out == NULL || rc == NULL) return false;
    measure_out_t got;
    if (xQueueReceive(measure_done, &got, 0) != pdTRUE) return false;
    *out = got.result;
    *rc = got.rc;
    return true;
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

bool radio_task_measure_start(uint32_t freq_hz, uint16_t dwell_ms, bool cad)
{
    (void)freq_hz;
    (void)dwell_ms;
    (void)cad;
    return false;
}

bool radio_task_measure_result(noise_result_t *out, int *rc)
{
    (void)out;
    (void)rc;
    return false;
}

bool radio_task_recv(radio_rx_msg_t *msg)
{
    (void)msg;
    return false;
}

#endif /* ESP_PLATFORM */
