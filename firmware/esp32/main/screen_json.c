/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * A small JSON reader for screen data, shared by the TFT renderer
 * (screen_renderer.c) and the on-board OLED status view (oled_view.c).
 */
#include "screen_json.h"

#include <stdlib.h>
#include <string.h>

/*
 * Template data is a flat JSON object written by the core (mode screens)
 * or the shell (system screens). The reader walks one object level and
 * skips nested values, so a key inside a nested object never matches.
 */

static const char *json_ws(const char *p)
{
    while (p && (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r')) p++;
    return p;
}

/* Returns the character after the string that starts at p (p points at '"'). */
static const char *json_skip_string(const char *p)
{
    p++;
    while (*p && *p != '"') {
        if (*p == '\\' && p[1]) p++;
        p++;
    }
    return *p == '"' ? p + 1 : NULL;
}

/* Returns the character after the value that starts at p, or NULL. */
static const char *json_skip_value(const char *p)
{
    p = json_ws(p);
    if (!p || !*p) return NULL;
    if (*p == '"') return json_skip_string(p);
    if (*p == '{' || *p == '[') {
        int depth = 0;
        while (*p) {
            if (*p == '"') {
                p = json_skip_string(p);
                if (!p) return NULL;
                continue;
            }
            if (*p == '{' || *p == '[') depth++;
            if (*p == '}' || *p == ']') {
                depth--;
                if (depth == 0) return p + 1;
            }
            p++;
        }
        return NULL;
    }
    while (*p && *p != ',' && *p != '}' && *p != ']' && *p != ' ' && *p != '\n') p++;
    return p;
}

/* Finds the value of a top-level key in a JSON object. */
static const char *json_find(const char *json, const char *key)
{
    const char *p = json_ws(json);
    if (!p || *p != '{') return NULL;
    p = json_ws(p + 1);
    size_t key_len = strlen(key);
    while (p && *p == '"') {
        const char *name = p + 1;
        const char *after = json_skip_string(p);
        if (!after) return NULL;
        bool match = (size_t)(after - 1 - name) == key_len && memcmp(name, key, key_len) == 0;
        p = json_ws(after);
        if (*p != ':') return NULL;
        p = json_ws(p + 1);
        if (match) return p;
        p = json_ws(json_skip_value(p));
        if (!p || *p != ',') return NULL;
        p = json_ws(p + 1);
    }
    return NULL;
}

/* Copies a JSON string value (p points at '"') into out, decoding escapes. */
static bool json_copy_string(const char *p, char *out, size_t out_sz)
{
    if (!p || *p != '"' || out_sz == 0) return false;
    p++;
    size_t n = 0;
    while (*p && *p != '"') {
        char c = *p++;
        if (c == '\\' && *p) {
            char e = *p++;
            if (e == 'n' || e == 't' || e == 'r') {
                c = ' ';
            } else if (e == 'u') {
                long code = 0;
                for (int i = 0; i < 4 && *p; i++, p++) {
                    char h = *p;
                    int v = (h >= '0' && h <= '9')   ? h - '0'
                            : (h >= 'a' && h <= 'f') ? h - 'a' + 10
                            : (h >= 'A' && h <= 'F') ? h - 'A' + 10
                                                     : 0;
                    code = code * 16 + v;
                }
                c = (code >= 0x20 && code < 0x7f) ? (char)code : '?';
            } else {
                c = e; /* \" \\ \/ */
            }
        }
        if (n + 1 < out_sz) out[n++] = c;
    }
    out[n] = '\0';
    return *p == '"';
}

bool screen_json_str(const char *json, const char *key, char *out, size_t out_sz)
{
    out[0] = '\0';
    return json_copy_string(json_find(json, key), out, out_sz);
}

bool screen_json_number(const char *json, const char *key, double *out)
{
    const char *p = json_find(json, key);
    if (!p) return false;
    char *end;
    double v = strtod(p, &end);
    if (end == p) return false;
    *out = v;
    return true;
}

bool screen_json_int(const char *json, const char *key, long *out)
{
    double v;
    if (!screen_json_number(json, key, &v)) return false;
    *out = (long)v;
    return true;
}

bool screen_json_true(const char *json, const char *key)
{
    const char *p = json_find(json, key);
    return p && strncmp(p, "true", 4) == 0;
}

/* Reads a JSON array of strings. Returns the number of entries copied. */
int screen_json_str_list(const char *json, const char *key, char *out, size_t item_sz, int max)
{
    const char *p = json_find(json, key);
    if (!p || *p != '[') return 0;
    p = json_ws(p + 1);
    int n = 0;
    while (p && *p == '"' && n < max) {
        json_copy_string(p, out + (size_t)n++ * item_sz, item_sz);
        p = json_ws(json_skip_string(p));
        if (!p || *p != ',') break;
        p = json_ws(p + 1);
    }
    return n;
}
