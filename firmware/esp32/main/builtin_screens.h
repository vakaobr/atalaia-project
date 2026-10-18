/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The screen templates built into the image: every
 * modes/<mode>/assets/screens/<name>.yaml, written into builtin_screens.c
 * at build time by builtin_screens.cmake (from the device's and the host
 * tests' CMakeLists.txt), like the mode scripts.
 */
#ifndef ATALAIA_BUILTIN_SCREENS_H
#define ATALAIA_BUILTIN_SCREENS_H

#include <stddef.h>

typedef struct {
    const char *mode_id; /* from the mode's mode.yaml, e.g. "org.atalaia.bomb" */
    const char *name;    /* the file's name without .yaml: the template ui.screen() names */
    const char *yaml;    /* the file, NUL-terminated */
    size_t len;
} builtin_screen_t;

extern const builtin_screen_t builtin_screens[];
extern const int builtin_screen_count;

#endif /* ATALAIA_BUILTIN_SCREENS_H */
