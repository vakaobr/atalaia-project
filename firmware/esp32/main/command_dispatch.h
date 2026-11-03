/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Routes hardware commands from the core's command callback to the
 * appropriate HAL subsystem or inter-task queue.
 */
#ifndef ATALAIA_COMMAND_DISPATCH_H
#define ATALAIA_COMMAND_DISPATCH_H

#include "hal/hal.h"
#include "screen_types.h"

/* Maximum number of queued screen updates for test inspection. */
#define CMD_SCREEN_QUEUE_MAX 16
#define CMD_AUDIO_QUEUE_MAX  16

/* A clip to play (clip set); a tone (clip empty, tone_ms > 0); or stop (clip empty, tone_ms 0).
 * The audio task plays them through sound.c on the speaker and the piezo buzzer. */
typedef struct {
    char clip[64];
    uint16_t tone_hz;
    uint16_t tone_ms;
} audio_cmd_t;

typedef struct {
    screen_update_t screens[CMD_SCREEN_QUEUE_MAX];
    int screen_count;
    audio_cmd_t audio[CMD_AUDIO_QUEUE_MAX];
    int audio_count;
} command_queues_t;

void command_queues_init(command_queues_t *q);

/*
 * Dispatch a command from the core callback. Parses target/method and
 * routes to the appropriate subsystem:
 *   "ui"   / "screen" -> screen queue
 *   "audio"/ "play"   -> audio queue
 *   "audio"/ "tone"   -> audio queue (empty clip, tone_hz/tone_ms from [freq, ms])
 *   "audio"/ "stop"   -> audio queue (empty clip, tone_ms 0)
 *   "ring" / "fill"   -> hal->leds->fill
 *   "ring" / "progress" -> hal->leds (computed)
 *   "ring" / "set_brightness" -> hal->leds->set_brightness
 */
void command_dispatch(const char *target, const char *method, const char *args_json, hal_t *hal,
                      command_queues_t *queues);

#endif /* ATALAIA_COMMAND_DISPATCH_H */
