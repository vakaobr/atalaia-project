/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * A small JSON reader for screen data: a flat JSON object written by the
 * core (mode screens) or the shell (system screens). It walks one object
 * level and skips nested values, so a key inside a nested object never
 * matches.
 */
#ifndef ATALAIA_SCREEN_JSON_H
#define ATALAIA_SCREEN_JSON_H

#include <stdbool.h>
#include <stddef.h>

/* Copies the string value of key into out (decoding escapes); "" if absent. */
bool screen_json_str(const char *json, const char *key, char *out, size_t out_sz);

/* Reads a number value of key (truncated to an integer). */
bool screen_json_int(const char *json, const char *key, long *out);

/* Reads a number value of key, fractions kept. */
bool screen_json_number(const char *json, const char *key, double *out);

/* True when key holds the literal true. */
bool screen_json_true(const char *json, const char *key);

/* Reads an array of strings into max items of item_sz bytes each (out is a
 * char[max][item_sz]). Returns the number of entries copied. */
int screen_json_str_list(const char *json, const char *key, char *out, size_t item_sz, int max);

#endif /* ATALAIA_SCREEN_JSON_H */
