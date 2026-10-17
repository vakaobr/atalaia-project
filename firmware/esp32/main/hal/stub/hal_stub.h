/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

#ifndef HAL_STUB_H
#define HAL_STUB_H

#include "../hal.h"

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

/**
 * Reset every stub counter / recorder to zero / empty.
 */
void hal_stub_reset_counters(void);

#ifdef __cplusplus
}
#endif

#endif /* HAL_STUB_H */
