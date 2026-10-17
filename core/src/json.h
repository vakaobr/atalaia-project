/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Minimal JSON for the boundary between scripts and the host: event data,
 * mode parameters and hardware command arguments. Object keys are written
 * in sorted order so output is deterministic.
 */
#ifndef ATALAIA_JSON_H
#define ATALAIA_JSON_H

#include <stddef.h>

#include "lua.h"

/*
 * Pushes the JSON text for the value at idx. Raises a Lua error for values
 * JSON cannot hold (functions, NaN, tables with mixed keys, deep nesting).
 * An empty table encodes as {}.
 */
void atalaia_json_push_encoded(lua_State *L, int idx);

/* Parses JSON text and pushes the value. Raises a Lua error on bad input. */
void atalaia_json_push_decoded(lua_State *L, const char *text);

/*
 * Writes src as a quoted JSON string into dst (always NUL-terminated,
 * truncated if needed). Needs no Lua state. Returns dst.
 */
char *atalaia_json_quote(char *dst, size_t cap, const char *src);

#endif /* ATALAIA_JSON_H */
