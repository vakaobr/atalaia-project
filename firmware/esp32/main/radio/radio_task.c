/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Radio FreeRTOS task: TX/RX loop on core 0, priority 3.
 */
#include "radio_task.h"

#include <string.h>

#include "radio_lbt.h"

#ifdef ESP_PLATFORM

#include "esp_log.h"
#include "esp_random.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "sdkconfig.h"

static const char *TAG = "radio_task";

#if CONFIG_ATALAIA_LBT_BENCH
static radio_task_bench_fn volatile bench_fn;
static volatile bool bench_running;
static volatile bool bench_stop;
#endif

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

/* The transmit stage with listen before talk (radio_lbt.h, RFC 0001 Amendment 14). */
#ifdef CONFIG_ATALAIA_LBT
#define LBT_ENABLED true
#else
#define LBT_ENABLED false
#endif
static radio_txs_t txs;
static radio_task_random_fn random_fn;
static void *random_ctx;

void radio_task_set_random(radio_task_random_fn fn, void *ctx)
{
    random_fn = fn;
    random_ctx = ctx;
}

static uint32_t lbt_rand(void *ctx)
{
    (void)ctx;
    uint32_t v;
    if (random_fn != NULL) {
        random_fn(random_ctx, (uint8_t *)&v, sizeof(v));
    } else {
        esp_fill_random(&v, sizeof(v));
    }
    return v;
}

static uint32_t now_ms(void)
{
    return (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS);
}

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

#if CONFIG_ATALAIA_LBT_BENCH
        /* The listen-before-talk bench test takes the radio until it returns. */
        if (bench_fn != NULL) {
            radio_task_bench_fn fn = bench_fn;
            bench_fn = NULL;
            bench_running = true;
            fn(radio_hal->radio);
            bench_running = false;
            bench_stop = false;
            continue;
        }
#endif

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

        /* Outbound: take a frame into the transmit stage when it is empty, then give it its turn.
         * A busy channel (listen before talk) holds the frame there and the loop goes on: the
         * task keeps receiving while it waits. */
        if (!radio_txs_busy(&txs)) {
            radio_tx_msg_t tx_msg;
            if (xQueueReceive(tx_queue, &tx_msg, 0) == pdTRUE) {
                radio_txs_load(&txs, &tx_msg, now_ms());
            }
        }
        if (radio_txs_busy(&txs)) {
            uint32_t tag = 0;
            radio_tx_status_t status = RADIO_TX_RESULT_OK;
            if (radio_txs_step(&txs, now_ms(), &tag, &status) == RADIO_TXS_DONE) {
                if (status == RADIO_TX_RESULT_DUTY_CYCLE) {
                    ESP_LOGW(TAG, "TX skipped: duty-cycle budget too small or exhausted");
                } else if (status != RADIO_TX_RESULT_OK) {
                    ESP_LOGW(TAG, "TX failed");
                }
#if CONFIG_ATALAIA_RADIO_LOG_PACKETS
                else {
                    ESP_LOGI(TAG, "TX %u bytes, %lu ms budget left", (unsigned)txs.msg.len,
                             (unsigned long)radio_hal->radio->duty_cycle_remaining_ms());
                }
#endif
                if (tag != 0) {
                    radio_tx_result_t result = {.tag = tag, .status = status};
                    if (xQueueSend(result_queue, &result, 0) != pdTRUE) {
                        ESP_LOGW(TAG, "TX result queue full, result dropped");
                    }
                }
            }
        }

        /* Check for inbound packets (50ms timeout). */
        uint8_t rx_buf[RADIO_MAX_PKT_LEN];
        int8_t rssi = 0;
        size_t rx_len = radio_hal->radio->recv(rx_buf, sizeof(rx_buf), &rssi);
        if (rx_len > 0) {
#if CONFIG_ATALAIA_RADIO_LOG_PACKETS
            ESP_LOGI(TAG, "RX %u bytes, RSSI %d dBm", (unsigned)rx_len, rssi);
#endif
            radio_rx_msg_t rx_msg;
            memcpy(rx_msg.data, rx_buf, rx_len);
            rx_msg.len = rx_len;
            rx_msg.rssi = rssi;
            rx_msg.timestamp_ms = (uint32_t)(xTaskGetTickCount() * portTICK_PERIOD_MS);
            if (xQueueSend(rx_queue, &rx_msg, 0) != pdTRUE) {
                ESP_LOGW(TAG, "RX queue full, packet dropped");
            }
        }

        /* With listen before talk the loop turns every ~10 ms (recv waits 10 ms at most, then one
         * tick), so a held frame's wait is honoured to about that; without it, as it always was
         * (recv up to 50 ms, then 10 ms). */
        vTaskDelay(LBT_ENABLED ? 1 : pdMS_TO_TICKS(10));
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
    radio_txs_init(&txs, radio_hal->radio, LBT_ENABLED, lbt_rand, NULL);
    if (LBT_ENABLED && radio_hal->radio->set_recv_wait_ms != NULL) {
        radio_hal->radio->set_recv_wait_ms(10);
    }
#if CONFIG_ATALAIA_LBT_BENCH
    /* The bench test of listen-before-talk formats its log lines on this task's stack. */
    const uint32_t stack = 8192;
#else
    const uint32_t stack = 4096;
#endif
    xTaskCreatePinnedToCore(radio_task_loop, "radio", stack, NULL, 3, NULL, 0);
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

void radio_task_lbt_stats(radio_lbt_stats_t *out)
{
    if (out != NULL) *out = txs.stats;
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

#if CONFIG_ATALAIA_LBT_BENCH
bool radio_task_bench_start(radio_task_bench_fn fn)
{
    if (radio_hal == NULL || fn == NULL || bench_running || bench_fn != NULL) return false;
    bench_stop = false;
    bench_fn = fn;
    return true;
}

bool radio_task_bench_running(void)
{
    return bench_running || bench_fn != NULL;
}

void radio_task_bench_request_stop(void)
{
    bench_stop = true;
}

bool radio_task_bench_stop_requested(void)
{
    return bench_stop;
}
#endif

bool radio_task_recv(radio_rx_msg_t *msg)
{
    if (rx_queue == NULL || msg == NULL) return false;
    return xQueueReceive(rx_queue, msg, 0) == pdTRUE;
}

#else
/* ---- Stub build (no FreeRTOS) ------------------------------------------- */

void radio_task_set_random(radio_task_random_fn fn, void *ctx)
{
    (void)fn;
    (void)ctx;
}

void radio_task_lbt_stats(radio_lbt_stats_t *out)
{
    if (out != NULL) memset(out, 0, sizeof(*out));
}

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
