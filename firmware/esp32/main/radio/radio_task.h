/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * Radio FreeRTOS task: owns the radio HAL on core 0, priority 3.
 * Drains a TX queue and fills an RX queue. Non-ESP builds provide
 * no-op stubs that compile but do not create real tasks.
 */
#ifndef ATALAIA_RADIO_TASK_H
#define ATALAIA_RADIO_TASK_H

#include <stddef.h>
#include <stdint.h>

#include "hal/hal.h"

#ifdef ESP_PLATFORM
#include "sdkconfig.h"
#endif

#define RADIO_TX_QUEUE_LEN 8
#define RADIO_RX_QUEUE_LEN 8
#define RADIO_MAX_PKT_LEN  255

typedef struct {
    uint8_t data[RADIO_MAX_PKT_LEN];
    size_t len;
    uint32_t tag; /* 0 = no result wanted; otherwise reported by radio_task_tx_result() */
} radio_tx_msg_t;

/* Outcome of a tagged transmission. */
typedef enum {
    RADIO_TX_RESULT_OK = 0,
    RADIO_TX_RESULT_DUTY_CYCLE = 1, /* budget exhausted: not sent */
    RADIO_TX_RESULT_ERROR = 2,      /* HAL send failed or timed out */
} radio_tx_status_t;

typedef struct {
    uint32_t tag;
    radio_tx_status_t status;
} radio_tx_result_t;

#define RADIO_TX_RESULT_QUEUE_LEN 8

typedef struct {
    uint8_t data[RADIO_MAX_PKT_LEN];
    size_t len;
    int8_t rssi;
    uint32_t timestamp_ms;
} radio_rx_msg_t;

/* Listen before talk's counters (RFC 0001 Amendment 14; radio_lbt.h): CADs run, frames that
 * waited for a busy channel, frames sent after the eighth busy answer in a row. */
typedef struct {
    uint32_t cads;
    uint32_t deferrals;
    uint32_t gave_up;
} radio_lbt_stats_t;

/*
 * The random source the listen-before-talk wait is drawn from (the box's shell.random; timing
 * spread, never a nonce). Call before radio_task_start(); without it the task uses the ESP32's
 * esp_fill_random. Whatever it is, it is called from the radio task.
 */
typedef void (*radio_task_random_fn)(void *ctx, uint8_t *buf, size_t len);
void radio_task_set_random(radio_task_random_fn fn, void *ctx);

/*
 * Start the radio task. Creates TX/RX queues and the FreeRTOS task.
 * On non-ESP builds this is a no-op.
 */
void radio_task_start(const hal_t *hal);

/*
 * Enqueue a packet for transmission. Returns true if the packet was
 * successfully queued, false if the queue is full.
 * Thread-safe (called from game_task).
 */
bool radio_task_send(const uint8_t *data, size_t len);

/*
 * Like radio_task_send, but the outcome is reported through
 * radio_task_tx_result() with the given tag (which must not be 0).
 * Used by the USB modem to answer every TX frame with a TX_ACK.
 */
bool radio_task_send_tagged(const uint8_t *data, size_t len, uint32_t tag);

/* Dequeue the outcome of a tagged transmission. Returns true if one was available. */
bool radio_task_tx_result(radio_tx_result_t *result);

/*
 * Asks the radio task to retune to freq_hz before its next TX or RX (the
 * task owns the SPI bus, so other tasks must not call the HAL directly).
 * Returns false if the task is not running.
 */
bool radio_task_set_channel(uint32_t freq_hz);

/* The duty-cycle budget left, as last read by the radio task (ms). */
uint32_t radio_task_duty_remaining_ms(void);

/* Listen before talk's counters since the task started (zeros when it is off or not running). */
void radio_task_lbt_stats(radio_lbt_stats_t *out);

/*
 * Asks the radio task to measure the noise on freq_hz for dwell_ms (the
 * HAL's measure op; nothing is transmitted). The task does it before its
 * next TX or RX, then goes back to its own channel. Returns false if a
 * measurement is already running, the HAL cannot measure, or the task is
 * not running. The outcome comes back through radio_task_measure_result().
 */
bool radio_task_measure_start(uint32_t freq_hz, uint16_t dwell_ms, bool cad);

/*
 * The outcome of the last measurement, once: true if one was waiting. *rc
 * is the HAL's return code (0 = *out is valid).
 */
bool radio_task_measure_result(noise_result_t *out, int *rc);

/*
 * Dequeue a received packet. Returns true if a packet was available.
 * Thread-safe (called from game_task).
 */
bool radio_task_recv(radio_rx_msg_t *msg);

#if CONFIG_ATALAIA_LBT_BENCH
/*
 * The bench test of listen-before-talk (radio/lbt_bench.c, docs/runbooks/lbt-bench-gate.md): runs
 * fn in the radio task, in place of its loop (nothing is sent or received for the game meanwhile:
 * the task owns the SPI bus), until fn returns. False if the task is not running or a bench test
 * already is. fn polls radio_task_bench_stop_requested().
 */
typedef void (*radio_task_bench_fn)(const hal_radio_ops_t *radio);
bool radio_task_bench_start(radio_task_bench_fn fn);
bool radio_task_bench_running(void);
void radio_task_bench_request_stop(void);
bool radio_task_bench_stop_requested(void);
#endif

#endif /* ATALAIA_RADIO_TASK_H */
