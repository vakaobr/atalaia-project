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

/*
 * Dequeue a received packet. Returns true if a packet was available.
 * Thread-safe (called from game_task).
 */
bool radio_task_recv(radio_rx_msg_t *msg);

#endif /* ATALAIA_RADIO_TASK_H */
