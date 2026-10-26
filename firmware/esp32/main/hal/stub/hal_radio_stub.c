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

#include "atalaia/duty_cycle.h"
#include "../../radio/channel_busy.h"
#include "hal_stub.h"

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

/* The noise the stub "hears" when asked to measure, and measure() calls. */
int hal_stub_radio_noise_dbm = -118;
atalaia_region_t hal_stub_radio_region = RADIO_REGION;
int hal_stub_radio_measure_calls;

/* The listen-before-talk test (channel_busy): the IRQ status the receiver "has" while armed, what a
 * CAD would find, the clock, and what the stub did. */
uint16_t hal_stub_radio_irq;
bool hal_stub_radio_cad_detects;
bool hal_stub_radio_cad_fails;
int64_t hal_stub_radio_now_us;
int hal_stub_radio_cad_calls;
int hal_stub_radio_rx_rearms;
int64_t hal_stub_radio_rx_done_us;
static cb_track_t busy_track;
static uint32_t irq_epoch;

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
    hal_stub_radio_noise_dbm = -118;
    hal_stub_radio_region = RADIO_REGION;
    hal_stub_radio_measure_calls = 0;
    hal_stub_radio_irq = 0;
    hal_stub_radio_cad_detects = false;
    hal_stub_radio_cad_fails = false;
    hal_stub_radio_now_us = 0;
    hal_stub_radio_cad_calls = 0;
    hal_stub_radio_rx_rearms = 0;
    hal_stub_radio_rx_done_us = 0;
    memset(&busy_track, 0, sizeof(busy_track));
    irq_epoch = 0;
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
    /* The same rule as the SX1262 HAL: the channel inside one of the region's sub-bands. */
    if (!atalaia_region_channel_ok(hal_stub_radio_region, freq_hz)) return -1;
    hal_stub_radio_channel_hz = freq_hz;
    return 0;
}

static int stub_radio_set_mode(hal_radio_mode_t mode)
{
    hal_stub_radio_mode = mode;
    if (mode == HAL_RADIO_MODE_RX) {
        hal_stub_radio_irq = 0;
        irq_epoch++;
    }
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

static int stub_radio_measure(uint32_t freq_hz, uint32_t dwell_ms, bool cad, noise_result_t *out)
{
    hal_stub_radio_measure_calls++;
    if (!atalaia_region_channel_ok(hal_stub_radio_region, freq_hz)) return -2;
    /* One reading per millisecond around the configured level, one CAD per 100 ms. */
    noise_acc_t acc;
    noise_acc_init(&acc);
    for (uint32_t i = 0; i < dwell_ms; i++) {
        noise_acc_add(&acc, hal_stub_radio_noise_dbm + (int)(i % 3) - 1);
        if (cad && i % 100 == 0) noise_acc_cad(&acc, false);
    }
    return noise_acc_finish(&acc, freq_hz, (uint16_t)dwell_ms, out) ? 0 : -1;
}

/* The same steps as the SX1262 HAL's channel_busy(), on the injected IRQ status and CAD result. */
static int stub_radio_channel_busy(hal_radio_busy_t *info)
{
    hal_radio_busy_t local;
    if (info == NULL) info = &local;
    info->why = HAL_BUSY_FREE;
    info->cad_us = 0;
    info->rearm_us = 0;
    info->sample_us = hal_stub_radio_now_us;
    if (hal_stub_radio_mode == HAL_RADIO_MODE_RX) {
        bool clear = false;
        hal_busy_why_t why =
            cb_rx_state(&busy_track, hal_stub_radio_irq, irq_epoch, hal_stub_radio_now_us,
                        atalaia_region_airtime_us(hal_stub_radio_region, 255) / 4 * 5, &clear);
        if (clear) {
            hal_stub_radio_irq &= (uint16_t)~CB_IRQ_FLAGS;
            irq_epoch++;
        }
        info->why = why;
        if (why == HAL_BUSY_PREAMBLE || why == HAL_BUSY_HEADER) return 1;
        if (why == HAL_BUSY_RX_DONE) return 0;
    }
    hal_stub_radio_cad_calls++;
    hal_stub_radio_irq = 0;
    irq_epoch++;
    info->cad_us = 3000;
    hal_stub_radio_mode = HAL_RADIO_MODE_RX; /* re-armed */
    hal_stub_radio_rx_rearms++;
    info->rearm_us = 200;
    if (hal_stub_radio_cad_fails) {
        info->why = HAL_BUSY_ERROR;
        return -1;
    }
    info->why = hal_stub_radio_cad_detects ? HAL_BUSY_CAD : HAL_BUSY_FREE;
    return hal_stub_radio_cad_detects ? 1 : 0;
}

static int64_t stub_radio_last_rx_done_us(void)
{
    return hal_stub_radio_rx_done_us;
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
    .measure = stub_radio_measure,
    .channel_busy = stub_radio_channel_busy,
    .last_rx_done_us = stub_radio_last_rx_done_us,
    .deinit = stub_radio_deinit,
};
