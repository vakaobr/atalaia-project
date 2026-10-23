/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

#ifndef HAL_STUB_H
#define HAL_STUB_H

#include "../hal.h"
#include "../../radio/radio_region.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Initialise the HAL with stub (no-op) implementations.
 * Used for Linux-hosted integration tests.
 */
void hal_stub_init(hal_t *hal);

/* ---- test-assertion counters ---- */

extern int hal_stub_led_fill_count;
extern char hal_stub_led_last_fill[4]; /* [0]=r, [1]=g, [2]=b, [3]=0 */

extern int hal_stub_audio_play_count;
extern char hal_stub_audio_last_clip[64];

/* ---- radio stub counters ---- */

extern int hal_stub_radio_tx_count;
extern uint8_t hal_stub_radio_tx_buf[16][255];
extern size_t hal_stub_radio_tx_len[16];
extern uint8_t hal_stub_radio_rx_buf[255];
extern size_t hal_stub_radio_rx_len;
extern int8_t hal_stub_radio_rx_rssi;
extern bool hal_stub_radio_rx_pending;
extern uint32_t hal_stub_radio_channel_hz;
extern uint32_t hal_stub_radio_dc_remaining_ms;
extern int hal_stub_radio_noise_dbm;
/* The region the stub radio checks channels against (the build's, RADIO_REGION, after reset). */
extern atalaia_region_t hal_stub_radio_region;
extern int hal_stub_radio_measure_calls;

void hal_stub_radio_reset(void);

/* ---- NFC stub: the user memory a tag would return (0 bytes = no tag) ---- */

extern uint8_t hal_stub_nfc_mem[888];
extern size_t hal_stub_nfc_mem_len;

/**
 * Reset every stub counter / recorder to zero / empty.
 */
void hal_stub_reset_counters(void);

#ifdef __cplusplus
}
#endif

#endif /* HAL_STUB_H */
