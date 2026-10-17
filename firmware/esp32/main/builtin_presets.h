/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Built-in presets: the games a Field Box offers out of the box. They are
 * written to the preset store on boot when it holds no presets, so a new
 * or erased box (and the Wokwi emulator) can start a game without any
 * upload. The mode sources come from modes/ at build time.
 */
#ifndef ATALAIA_BUILTIN_PRESETS_H
#define ATALAIA_BUILTIN_PRESETS_H

#include <stddef.h>

typedef struct {
    const char *mode_id; /* e.g. "org.atalaia.bomb" */
    const char *source;  /* node.lua */
    size_t source_len;
} builtin_source_t;

/*
 * Write the built-in presets (Bomb, Domination) to slots 1, 2, ... when the
 * store holds no presets. sources supplies node.lua for each mode; presets
 * whose mode has no source are skipped. Returns the number of presets
 * written (0 when the store already had presets).
 */
int builtin_presets_seed(const builtin_source_t *sources, int source_count);

#endif /* ATALAIA_BUILTIN_PRESETS_H */
