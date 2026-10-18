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
} radio_tx_msg_t;

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
 * Dequeue a received packet. Returns true if a packet was available.
 * Thread-safe (called from game_task).
 */
bool radio_task_recv(radio_rx_msg_t *msg);

#endif /* ATALAIA_RADIO_TASK_H */
