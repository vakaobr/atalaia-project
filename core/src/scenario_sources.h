/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The scenario compiler's Lua sources (the .lua files of core/scenario), embedded by the
 * build: core/cmake/embed_scenario.cmake writes scenario_sources.c into the
 * build folder from the files themselves, so they are never copied by hand.
 */
#ifndef ATALAIA_SCENARIO_SOURCES_H
#define ATALAIA_SCENARIO_SOURCES_H

#include <stddef.h>

typedef struct {
    const char *name; /* the file's name without .lua: "validator", "runtime" */
    const char *text;
    size_t len;
} atalaia_scenario_source_t;

extern const atalaia_scenario_source_t atalaia_scenario_sources[];
extern const size_t atalaia_scenario_source_count;

#endif /* ATALAIA_SCENARIO_SOURCES_H */
