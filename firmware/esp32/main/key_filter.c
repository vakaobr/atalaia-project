/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#include "key_filter.h"

#include "hal/hal_keypad.h"

void key_filter_init(key_filter_t *f)
{
    f->candidate = HAL_KEY_NONE;
    f->stable = 0;
    f->state = HAL_KEY_NONE;
}

char key_filter_update(key_filter_t *f, char raw)
{
    if (raw == f->candidate) {
        if (f->stable < KEY_FILTER_STABLE_SCANS) f->stable++;
    } else {
        f->candidate = raw;
        f->stable = 1;
    }
    if (f->stable < KEY_FILTER_STABLE_SCANS || f->candidate == f->state) return HAL_KEY_NONE;
    f->state = f->candidate;
    return f->state;
}
