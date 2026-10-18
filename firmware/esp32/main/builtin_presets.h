/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Built-in presets: the games a Field Box offers out of the box, and the
 * modes a field controller's join can name. Each is written to the preset
 * store on boot when no stored preset uses its mode, so a new or erased box
 * (and the Wokwi emulator) can start a game without any upload, and a box
 * updated to a firmware with more built-in modes gets them. The mode
 * sources come from modes/ at build time.
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
 * Write each built-in preset (Bomb, Domination, Hold-All Domination, Last
 * Stand, Codes) whose mode no stored preset uses, into the lowest free
 * slots, in that order. A built-in mode already stored gets the source from
 * this image when it differs (the firmware owns the built-in modes).
 * sources supplies node.lua for each mode; presets whose mode has no source
 * are skipped. Returns the number of presets written.
 */
int builtin_presets_seed(const builtin_source_t *sources, int source_count);

#endif /* ATALAIA_BUILTIN_PRESETS_H */
