/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

#ifndef HAL_BUZZER_H
#define HAL_BUZZER_H

#include <stdint.h>

/* An optional passive piezo buzzer on one GPIO (CONFIG_ATALAIA_BUZZER): square-wave tones from
 * the LEDC PWM peripheral. hal_t's buzzer is NULL when the build has none. */
typedef struct {
    int (*init)(void);
    /* Starts a tone of freq_hz (0: silent) and returns at once; sound.c times it. */
    void (*tone)(uint32_t freq_hz);
    void (*set_volume)(uint8_t volume); /* 0-100: the PWM duty, 0 = silent */
    void (*deinit)(void);
} hal_buzzer_ops_t;

#endif /* HAL_BUZZER_H */
