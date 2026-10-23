/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The scenario compiler's calls with their limits given (atalaia/scenario.h
 * uses ATALAIA_SCENARIO_MEM_LIMIT and ATALAIA_SCENARIO_INSTR_LIMIT), and what
 * one call used: for the core's tests and for measuring the limits.
 */
#ifndef ATALAIA_SCENARIO_INTERNAL_H
#define ATALAIA_SCENARIO_INTERNAL_H

#include <stddef.h>
#include <stdint.h>

typedef struct {
    size_t mem_peak;       /* the most memory the call's Lua state held at once */
    uint64_t instructions; /* the Lua instructions it ran (counted in thousands) */
} atalaia_scenario_usage_t;

/* op: "check", "compile" or "literal". usage may be NULL. */
char *atalaia_scenario_run_limited(const char *op, const char *tree, size_t len, size_t *out_len,
                                   size_t mem_limit, uint64_t instr_limit,
                                   atalaia_scenario_usage_t *usage);

#endif /* ATALAIA_SCENARIO_INTERNAL_H */
