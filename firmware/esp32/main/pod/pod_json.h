/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Reading a CMD's arguments: the core's capability proxy decoder gives them
 * as a compact JSON object (core/src/proxy.c), such as {"team":"red"},
 * {"freq":2000,"ms":150} or {"args":[40]}. These look up a top-level key, or
 * an element of the "args" array, and read a string or a number. Plain C.
 */
#ifndef ATALAIA_POD_JSON_H
#define ATALAIA_POD_JSON_H

#include <stdbool.h>
#include <stddef.h>

/* The string value of a top-level key, unescaped (\" \\ \/ only). */
bool pod_json_str(const char *json, const char *key, char *out, size_t cap);

/* The number value of a top-level key (true/false read as 1/0). */
bool pod_json_num(const char *json, const char *key, double *out);

/* Element index of the top-level "args" array, as a string or a number. */
bool pod_json_arg_str(const char *json, size_t index, char *out, size_t cap);
bool pod_json_arg_num(const char *json, size_t index, double *out);

#endif /* ATALAIA_POD_JSON_H */
