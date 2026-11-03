/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * sound.h's outputs on the ESP32: the I2S amplifier (hal->audio) when it is fitted and the piezo
 * buzzer (hal->buzzer, CONFIG_ATALAIA_BUZZER) when the build has one. The Field Box's audio task
 * and the I/O pod's play through it.
 */
#ifndef ATALAIA_SOUND_ESP_H
#define ATALAIA_SOUND_ESP_H

#include <stdbool.h>

#include "hal/hal.h"
#include "sound.h"

/* The outputs of hal: the speaker when speaker is true (its pins are set and it started), the
 * buzzer when hal->buzzer is not NULL. hal must outlive the result. */
sound_out_t sound_esp_out(const hal_t *hal, bool speaker);

/* True when the build's I2S pins are all set (the amplifier is fitted). */
bool sound_esp_speaker_pins(void);

#endif /* ATALAIA_SOUND_ESP_H */
