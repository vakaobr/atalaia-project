/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Keypad debounce and edge detection. The keypad drivers report the key
 * held down at each scan; the game loop wants one press per key stroke.
 */
#ifndef ATALAIA_KEY_FILTER_H
#define ATALAIA_KEY_FILTER_H

#include <stdint.h>

/* A key must read the same in this many consecutive scans (10 ms apart). */
#define KEY_FILTER_STABLE_SCANS 3

typedef struct {
    char candidate; /* last raw reading */
    uint8_t stable; /* consecutive scans with that reading */
    char state;     /* debounced key (or HAL_KEY_NONE) */
} key_filter_t;

void key_filter_init(key_filter_t *f);

/*
 * Feed one raw scan (HAL_KEY_NONE when no key is down). Returns a key once,
 * when it becomes the debounced state; holding it returns nothing more
 * until it is released. Otherwise returns HAL_KEY_NONE.
 */
char key_filter_update(key_filter_t *f, char raw);

#endif /* ATALAIA_KEY_FILTER_H */
