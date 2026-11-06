/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * wifi_args.c -- the "@wifi" line's SSID and password (wifi_args.h).
 */
#include "wifi_args.h"

#include <string.h>

static bool is_hex(char c)
{
    return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F');
}

bool wifi_ssid_valid(const char *ssid)
{
    size_t n = strlen(ssid);
    return n >= 1 && n <= WIFI_SSID_MAX;
}

bool wifi_pass_valid(const char *pass)
{
    size_t n = strlen(pass);
    if (n == 0) return true;
    if (n >= 8 && n <= 63) return true;
    if (n != 64) return false;
    for (size_t i = 0; i < n; i++) {
        if (!is_hex(pass[i])) return false;
    }
    return true;
}

/*
 * One double-quoted argument at *p (on its opening quote) into out (cap bytes with the NUL).
 * Moves *p past the closing quote. A value longer than cap - 1 sets *too_long and is cut,
 * the rest still read for its quotes and escapes.
 */
static wifi_args_result_t quoted(const char **p, char *out, size_t cap, bool *too_long)
{
    const char *s = *p + 1;
    size_t n = 0;
    *too_long = false;
    for (;;) {
        char c = *s++;
        if (c == '\0') return WIFI_ARGS_UNTERMINATED;
        if (c == '"') break;
        if (c == '\\') {
            c = *s++;
            if (c == '\0') return WIFI_ARGS_UNTERMINATED;
            if (c != '"' && c != '\\') return WIFI_ARGS_BAD_ESCAPE;
        }
        if (n + 1 < cap) {
            out[n++] = c;
        } else {
            *too_long = true;
        }
    }
    out[n] = '\0';
    *p = s;
    return WIFI_ARGS_OK;
}

static wifi_args_result_t fail(wifi_args_result_t r, char *ssid, char *pass)
{
    ssid[0] = '\0';
    pass[0] = '\0';
    return r;
}

wifi_args_result_t wifi_args_parse(const char *args, char ssid[WIFI_SSID_MAX + 1],
                                   char pass[WIFI_PASS_MAX + 1])
{
    const char *p = args;
    bool too_long = false;
    ssid[0] = '\0';
    pass[0] = '\0';

    /* The SSID: quoted, or the first word as before. */
    if (*p == '"') {
        wifi_args_result_t r = quoted(&p, ssid, WIFI_SSID_MAX + 1, &too_long);
        if (r != WIFI_ARGS_OK) return fail(r, ssid, pass);
        if (too_long || ssid[0] == '\0') return fail(WIFI_ARGS_SSID_LENGTH, ssid, pass);
        if (*p != '\0' && *p != ' ') return fail(WIFI_ARGS_AFTER_QUOTE, ssid, pass);
    } else {
        const char *sp = strchr(p, ' ');
        size_t n = sp ? (size_t)(sp - p) : strlen(p);
        if (n == 0) return fail(WIFI_ARGS_NO_SSID, ssid, pass);
        if (n > WIFI_SSID_MAX) return fail(WIFI_ARGS_SSID_LENGTH, ssid, pass);
        memcpy(ssid, p, n);
        ssid[n] = '\0';
        p += n;
    }
    if (*p == '\0') return WIFI_ARGS_OK; /* an open network */
    p++;                                 /* the one space after the SSID */

    /* The password: quoted (only trailing spaces after it), or the rest of the line as typed. */
    if (*p == '"') {
        wifi_args_result_t r = quoted(&p, pass, WIFI_PASS_MAX + 1, &too_long);
        if (r != WIFI_ARGS_OK) return fail(r, ssid, pass);
        if (too_long) return fail(WIFI_ARGS_PASSWORD_LENGTH, ssid, pass);
        while (*p == ' ') p++;
        if (*p != '\0') return fail(WIFI_ARGS_AFTER_QUOTE, ssid, pass);
    } else {
        size_t n = strlen(p);
        if (n > WIFI_PASS_MAX) return fail(WIFI_ARGS_PASSWORD_LENGTH, ssid, pass);
        memcpy(pass, p, n + 1);
    }
    if (!wifi_pass_valid(pass)) return fail(WIFI_ARGS_PASSWORD_LENGTH, ssid, pass);
    return WIFI_ARGS_OK;
}

const char *wifi_args_error(wifi_args_result_t r)
{
    switch (r) {
    case WIFI_ARGS_OK: return "stored";
    case WIFI_ARGS_NO_SSID:
        return "refused: no network name (@wifi <ssid> <password>, or @wifi \"My Field\" "
               "\"pass word\" for spaces)";
    case WIFI_ARGS_UNTERMINATED:
        return "refused: a quote is not closed (end each name or password in \")";
    case WIFI_ARGS_BAD_ESCAPE:
        return "refused: in quotes, a backslash goes only before \" or \\ (\\\" and \\\\)";
    case WIFI_ARGS_AFTER_QUOTE:
        return "refused: text after a closing quote (a space between the name and the password, "
               "nothing after a quoted password)";
    case WIFI_ARGS_SSID_LENGTH: return "refused: the network name is 1-32 bytes";
    case WIFI_ARGS_PASSWORD_LENGTH:
        return "refused: the password is 8-63 characters, 64 hex digits, or none";
    }
    return "refused";
}
