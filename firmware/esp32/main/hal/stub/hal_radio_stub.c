/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Radio HAL stub for Linux-hosted tests and the Wokwi emulator (no SX1262).
 * Records sent packets so tests can assert on them, and allows injecting
 * received packets.
 */
#include "../hal_radio.h"

#include <string.h>

/* ---- Test-assertion state ------------------------------------------------ */

#define RADIO_STUB_MAX_PACKETS 16
#define RADIO_STUB_MAX_PKT_LEN 255

int hal_stub_radio_tx_count;
uint8_t hal_stub_radio_tx_buf[RADIO_STUB_MAX_PACKETS][RADIO_STUB_MAX_PKT_LEN];
size_t hal_stub_radio_tx_len[RADIO_STUB_MAX_PACKETS];

/* Inject an RX packet by writing here before calling recv. */
uint8_t hal_stub_radio_rx_buf[RADIO_STUB_MAX_PKT_LEN];
size_t hal_stub_radio_rx_len;
int8_t hal_stub_radio_rx_rssi;
bool hal_stub_radio_rx_pending;

uint32_t hal_stub_radio_channel_hz;
hal_radio_mode_t hal_stub_radio_mode;

/* Simulated duty-cycle remaining (g2 10% = 360,000 ms/h). */
uint32_t hal_stub_radio_dc_remaining_ms = 360000;

void hal_stub_radio_reset(void)
{
    hal_stub_radio_tx_count = 0;
    memset(hal_stub_radio_tx_buf, 0, sizeof(hal_stub_radio_tx_buf));
    memset(hal_stub_radio_tx_len, 0, sizeof(hal_stub_radio_tx_len));
    hal_stub_radio_rx_len = 0;
    hal_stub_radio_rx_rssi = 0;
    hal_stub_radio_rx_pending = false;
    hal_stub_radio_channel_hz = 0;
    hal_stub_radio_mode = HAL_RADIO_MODE_SLEEP;
    hal_stub_radio_dc_remaining_ms = 360000;
}

/* ---- Stub ops ------------------------------------------------------------ */

static int stub_radio_init(void)
{
    hal_stub_radio_reset();
    return 0;
}

static int stub_radio_send(const uint8_t *data, size_t len)
{
    if (len == 0 || len > RADIO_STUB_MAX_PKT_LEN) return -1;
    int idx = hal_stub_radio_tx_count;
    if (idx < RADIO_STUB_MAX_PACKETS) {
        memcpy(hal_stub_radio_tx_buf[idx], data, len);
        hal_stub_radio_tx_len[idx] = len;
    }
    hal_stub_radio_tx_count++;
    return 0;
}

static size_t stub_radio_recv(uint8_t *buf, size_t max_len, int8_t *rssi)
{
    if (!hal_stub_radio_rx_pending || hal_stub_radio_rx_len == 0) {
        return 0;
    }
    size_t copy = hal_stub_radio_rx_len;
    if (copy > max_len) copy = max_len;
    memcpy(buf, hal_stub_radio_rx_buf, copy);
    if (rssi) *rssi = hal_stub_radio_rx_rssi;
    hal_stub_radio_rx_pending = false;
    hal_stub_radio_rx_len = 0;
    return copy;
}

static int stub_radio_set_channel(uint32_t freq_hz)
{
    hal_stub_radio_channel_hz = freq_hz;
    return 0;
}

static int stub_radio_set_mode(hal_radio_mode_t mode)
{
    hal_stub_radio_mode = mode;
    return 0;
}

static int8_t stub_radio_rssi(void)
{
    return -50;
}

static uint32_t stub_radio_duty_cycle_remaining_ms(void)
{
    return hal_stub_radio_dc_remaining_ms;
}

static void stub_radio_deinit(void)
{
    hal_stub_radio_reset();
}

const hal_radio_ops_t hal_stub_radio_ops = {
    .init = stub_radio_init,
    .send = stub_radio_send,
    .recv = stub_radio_recv,
    .set_channel = stub_radio_set_channel,
    .set_mode = stub_radio_set_mode,
    .rssi = stub_radio_rssi,
    .duty_cycle_remaining_ms = stub_radio_duty_cycle_remaining_ms,
    .deinit = stub_radio_deinit,
};
