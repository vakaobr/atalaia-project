/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

#ifndef HAL_AUDIO_H
#define HAL_AUDIO_H

#include <stdint.h>

typedef struct {
    int (*init)(void);
    int (*play_wav)(const char *path);
    int (*tone)(uint32_t freq_hz, uint32_t duration_ms);
    void (*stop)(void);
    void (*set_volume)(uint8_t volume); /* 0-100 */
    void (*deinit)(void);
} hal_audio_ops_t;

#endif /* HAL_AUDIO_H */
