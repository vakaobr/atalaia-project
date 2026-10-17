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

typedef struct {
    char clip[64];
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
 *   "audio"/ "stop"   -> audio queue (empty clip)
 *   "ring" / "fill"   -> hal->leds->fill
 *   "ring" / "progress" -> hal->leds (computed)
 *   "ring" / "set_brightness" -> hal->leds->set_brightness
 */
void command_dispatch(const char *target, const char *method, const char *args_json, hal_t *hal,
                      command_queues_t *queues);

#endif /* ATALAIA_COMMAND_DISPATCH_H */
