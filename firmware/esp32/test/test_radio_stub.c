/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Tests for the radio HAL stub.
 */
#include <string.h>

#include "check.h"
#include "hal/hal.h"
#include "hal/stub/hal_stub.h"

static void test_radio_stub_send(void)
{
    hal_t hal;
    hal_stub_init(&hal);
    CHECK(hal.radio != NULL);
    CHECK(hal.radio->init() == 0);

    /* Send a packet. */
    uint8_t data[] = {0x01, 0x02, 0x03, 0x04, 0x05};
    CHECK(hal.radio->send(data, sizeof(data)) == 0);
    CHECK(hal_stub_radio_tx_count == 1);
    CHECK(hal_stub_radio_tx_len[0] == sizeof(data));
    CHECK(memcmp(hal_stub_radio_tx_buf[0], data, sizeof(data)) == 0);

    /* Send another. */
    uint8_t data2[] = {0xAA, 0xBB};
    CHECK(hal.radio->send(data2, sizeof(data2)) == 0);
    CHECK(hal_stub_radio_tx_count == 2);
    CHECK(hal_stub_radio_tx_len[1] == sizeof(data2));

    hal.radio->deinit();
}

static void test_radio_stub_recv(void)
{
    hal_t hal;
    hal_stub_init(&hal);
    hal.radio->init();

    /* No packet pending. */
    uint8_t buf[255];
    int8_t rssi = 0;
    CHECK(hal.radio->recv(buf, sizeof(buf), &rssi) == 0);

    /* Inject a packet. */
    hal_stub_radio_rx_buf[0] = 0xDE;
    hal_stub_radio_rx_buf[1] = 0xAD;
    hal_stub_radio_rx_len = 2;
    hal_stub_radio_rx_rssi = -75;
    hal_stub_radio_rx_pending = true;

    size_t len = hal.radio->recv(buf, sizeof(buf), &rssi);
    CHECK(len == 2);
    CHECK(buf[0] == 0xDE && buf[1] == 0xAD);
    CHECK(rssi == -75);

    /* Second recv returns nothing (consumed). */
    CHECK(hal.radio->recv(buf, sizeof(buf), &rssi) == 0);

    hal.radio->deinit();
}

static void test_radio_stub_duty_cycle(void)
{
    hal_t hal;
    hal_stub_init(&hal);
    hal.radio->init();

    CHECK(hal.radio->duty_cycle_remaining_ms() == 360000);

    hal_stub_radio_dc_remaining_ms = 0;
    CHECK(hal.radio->duty_cycle_remaining_ms() == 0);

    hal.radio->deinit();
}

static void test_radio_stub_channel(void)
{
    hal_t hal;
    hal_stub_init(&hal);
    hal.radio->init();

    CHECK(hal.radio->set_channel(868100000) == 0);
    CHECK(hal_stub_radio_channel_hz == 868100000);

    /* Default game channel (g2 sub-band). */
    CHECK(hal.radio->set_channel(869525000) == 0);
    CHECK(hal_stub_radio_channel_hz == 869525000);

    hal.radio->deinit();
}

void run_radio_stub_tests(void)
{
    test_radio_stub_send();
    test_radio_stub_recv();
    test_radio_stub_duty_cycle();
    test_radio_stub_channel();
}
