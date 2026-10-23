/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The scenario validator and compiler (ADR-P4-6 as amended, decision
 * PE24-109): one implementation, in Lua (the .lua files of core/scenario, embedded in the
 * core when it is built with ATALAIA_SCENARIO, the default; the Field Box's
 * firmware leaves it out), for every controller: the Pi through ctypes, the
 * phone through dart:ffi.
 *
 * A controller reads a manifest's YAML or JSON text itself and hands over
 * what it read as the manifest's data tree in JSON (core/scenario/README.md):
 * {"map": [[{"str": "id"}, {"str": "org.club.ridge"}], ...]}. Each call runs
 * in a Lua state of its own, with only the base, string, table, math and utf8
 * libraries, a memory limit and an instruction limit; the tree is data, never
 * code.
 *
 * Every function returns a NUL-terminated JSON text allocated with malloc
 * (free it with atalaia_scenario_free), its length in *out_len if out_len is
 * not NULL, or NULL when memory for the answer itself runs out:
 *
 *   {"ok": true|false, "problems": [{"path", "code", "message", "level"}]}
 *       check: every problem (protocol/vectors/scenario.json); compile also
 *       gives, without errors, "id", "version" and
 *       "files": {"mode.yaml": text, "field.lua": text}
 *   {"error": "why"}
 *       the tree is not a data tree (a caller's bug)
 *
 * A manifest past the memory or instruction limit is a problem
 * ("too_complex"), not an error. Thread-safe: no state is kept between calls.
 */
#ifndef ATALAIA_SCENARIO_H
#define ATALAIA_SCENARIO_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * The memory one call may use, and the Lua instructions it may run (counted in steps of
 * 1000). The largest manifest that compiles (64 objectives with long texts in two languages)
 * takes about 4 MB and 14 million; a manifest past either is a problem, too_complex
 * (decision PE24-113).
 */
#define ATALAIA_SCENARIO_MEM_LIMIT   (64u * 1024u * 1024u)
#define ATALAIA_SCENARIO_INSTR_LIMIT 200000000u

/* The manifest's problems. */
char *atalaia_scenario_check(const char *tree, size_t len, size_t *out_len);

/* The manifest's problems and, without errors, its package. */
char *atalaia_scenario_compile(const char *tree, size_t len, size_t *out_len);

/*
 * A value as the compiler writes it in field.lua (a Lua literal; for tests):
 * {"ok": true, "lua": text} or {"ok": false, "error": why Lua cannot hold it}.
 */
char *atalaia_scenario_literal(const char *tree, size_t len, size_t *out_len);

/* Frees an answer of the functions above (NULL is fine). */
void atalaia_scenario_free(char *answer);

#ifdef __cplusplus
}
#endif

#endif /* ATALAIA_SCENARIO_H */
