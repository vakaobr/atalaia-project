/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * A CMD's arguments (see pod_json.h).
 */
#include "pod_json.h"

#include <stdlib.h>
#include <string.h>

static size_t skip_ws(const char *s, size_t i)
{
    while (s[i] == ' ' || s[i] == '\t' || s[i] == '\n' || s[i] == '\r') i++;
    return i;
}

/* The index just past the string starting at s[i] (a '"'), or 0. */
static size_t skip_string(const char *s, size_t i)
{
    if (s[i] != '"') return 0;
    for (i++; s[i]; i++) {
        if (s[i] == '\\') {
            if (!s[i + 1]) return 0;
            i++;
        } else if (s[i] == '"') {
            return i + 1;
        }
    }
    return 0;
}

/* The index just past the value starting at s[i], or 0. */
static size_t skip_value(const char *s, size_t i)
{
    i = skip_ws(s, i);
    if (s[i] == '"') return skip_string(s, i);
    if (s[i] == '{' || s[i] == '[') {
        int depth = 0;
        while (s[i]) {
            if (s[i] == '"') {
                i = skip_string(s, i);
                if (i == 0) return 0;
                continue;
            }
            if (s[i] == '{' || s[i] == '[') depth++;
            if (s[i] == '}' || s[i] == ']') {
                if (--depth == 0) return i + 1;
            }
            i++;
        }
        return 0;
    }
    size_t start = i;
    while (s[i] && s[i] != ',' && s[i] != '}' && s[i] != ']' && s[i] != ' ') i++;
    return i > start ? i : 0;
}

/* Copies the string at s[i] (a '"') into out, unescaped. */
static bool read_string(const char *s, size_t i, char *out, size_t cap)
{
    if (s[i] != '"' || cap == 0) return false;
    size_t o = 0;
    for (i++; s[i] && s[i] != '"'; i++) {
        char c = s[i];
        if (c == '\\') {
            c = s[++i];
            if (c != '"' && c != '\\' && c != '/') return false;
        }
        if (o + 1 >= cap) return false;
        out[o++] = c;
    }
    if (s[i] != '"') return false;
    out[o] = '\0';
    return true;
}

static bool read_number(const char *s, size_t i, double *out)
{
    if (strncmp(s + i, "true", 4) == 0) {
        *out = 1;
        return true;
    }
    if (strncmp(s + i, "false", 5) == 0) {
        *out = 0;
        return true;
    }
    char *end = NULL;
    double v = strtod(s + i, &end);
    if (end == s + i) return false;
    *out = v;
    return true;
}

/* The index of the value of a top-level key, or 0. */
static size_t find_key(const char *json, const char *key)
{
    if (json == NULL || key == NULL) return 0;
    size_t i = skip_ws(json, 0);
    if (json[i] != '{') return 0;
    i = skip_ws(json, i + 1);
    size_t klen = strlen(key);
    while (json[i] == '"') {
        size_t end = skip_string(json, i);
        if (end == 0) return 0;
        bool match = end - i - 2 == klen && strncmp(json + i + 1, key, klen) == 0;
        i = skip_ws(json, end);
        if (json[i] != ':') return 0;
        i = skip_ws(json, i + 1);
        if (match) return i;
        i = skip_value(json, i);
        if (i == 0) return 0;
        i = skip_ws(json, i);
        if (json[i] != ',') return 0;
        i = skip_ws(json, i + 1);
    }
    return 0;
}

/* The index of element index of the "args" array, or 0. */
static size_t find_arg(const char *json, size_t index)
{
    size_t i = find_key(json, "args");
    if (i == 0 || json[i] != '[') return 0;
    i = skip_ws(json, i + 1);
    for (size_t n = 0; json[i] && json[i] != ']'; n++) {
        if (n == index) return i;
        i = skip_value(json, i);
        if (i == 0) return 0;
        i = skip_ws(json, i);
        if (json[i] != ',') return 0;
        i = skip_ws(json, i + 1);
    }
    return 0;
}

bool pod_json_str(const char *json, const char *key, char *out, size_t cap)
{
    size_t i = find_key(json, key);
    return i != 0 && read_string(json, i, out, cap);
}

bool pod_json_num(const char *json, const char *key, double *out)
{
    size_t i = find_key(json, key);
    return i != 0 && read_number(json, i, out);
}

bool pod_json_arg_str(const char *json, size_t index, char *out, size_t cap)
{
    size_t i = find_arg(json, index);
    return i != 0 && read_string(json, i, out, cap);
}

bool pod_json_arg_num(const char *json, size_t index, double *out)
{
    size_t i = find_arg(json, index);
    return i != 0 && read_number(json, i, out);
}
