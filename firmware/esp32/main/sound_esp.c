/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * sound.h's outputs on the ESP32 (sound_esp.h).
 */
#include "sound_esp.h"

#include <sys/stat.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "sdkconfig.h"

static void buzzer_tone(void *ctx, uint32_t hz)
{
    ((const hal_t *)ctx)->buzzer->tone(hz);
}

static void speaker_tone(void *ctx, uint32_t hz, uint32_t ms)
{
    ((const hal_t *)ctx)->audio->tone(hz, ms);
}

static int speaker_file(void *ctx, const char *path)
{
    struct stat st;
    if (stat(path, &st) != 0) return -1; /* no file for this clip: its pattern plays instead */
    return ((const hal_t *)ctx)->audio->play_wav(path);
}

static void speaker_stop(void *ctx)
{
    ((const hal_t *)ctx)->audio->stop();
}

static void wait_ms(void *ctx, uint32_t ms)
{
    (void)ctx;
    vTaskDelay(pdMS_TO_TICKS(ms));
}

bool sound_esp_speaker_pins(void)
{
    return CONFIG_ATALAIA_AUDIO_BCLK_PIN >= 0 && CONFIG_ATALAIA_AUDIO_LRCLK_PIN >= 0 &&
           CONFIG_ATALAIA_AUDIO_DOUT_PIN >= 0;
}

sound_out_t sound_esp_out(const hal_t *hal, bool speaker)
{
    bool buzzer = hal->buzzer != NULL;
    speaker = speaker && hal->audio != NULL;
    sound_out_t out = {
        .ctx = (void *)hal,
        .buzzer = buzzer ? buzzer_tone : NULL,
        .speaker_tone = speaker ? speaker_tone : NULL,
        .speaker_file = speaker ? speaker_file : NULL,
        .speaker_stop = speaker ? speaker_stop : NULL,
        .wait_ms = wait_ms,
    };
    return out;
}
