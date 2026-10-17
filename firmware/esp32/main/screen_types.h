/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Screen update message passed from game_task to lvgl_task via a queue.
 */
#ifndef ATALAIA_SCREEN_TYPES_H
#define ATALAIA_SCREEN_TYPES_H

#define SCREEN_TEMPLATE_MAX 32
#define SCREEN_DATA_MAX     512

typedef struct {
    char template_name[SCREEN_TEMPLATE_MAX];
    char data_json[SCREEN_DATA_MAX];
} screen_update_t;

#endif /* ATALAIA_SCREEN_TYPES_H */
