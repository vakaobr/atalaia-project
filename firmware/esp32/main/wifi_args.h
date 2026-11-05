/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The arguments of the serial console's "@wifi" line: the field Wi-Fi's name (SSID) and
 * password (decisions WIFI-1 to WIFI-9).
 *
 *   @wifi <ssid> [<password>]              as before: the SSID is the first word, the password
 *                                          the rest of the line as typed (spaces included)
 *   @wifi "My Field" "pass word"           either one in double quotes, with \" and \\ inside
 *   @wifi "My Field" pass word             a quoted SSID, the rest of the line the password
 *   @wifi "My Field"                       an open network ("" as the password too)
 *
 * The SSID is 1-32 bytes; the password none, 8-63 characters or 64 hex digits (WPA2's
 * pre-shared key), the limits after the quotes and escapes are taken off.
 * Platform-free (the host tests).
 */
#ifndef ATALAIA_WIFI_ARGS_H
#define ATALAIA_WIFI_ARGS_H

#include <stdbool.h>
#include <stddef.h>

#define WIFI_SSID_MAX 32 /* bytes */
#define WIFI_PASS_MAX 64 /* 64 hex digits; a passphrase is 63 characters at most */

typedef enum {
    WIFI_ARGS_OK = 0,
    WIFI_ARGS_NO_SSID,         /* nothing, or a leading space, where the SSID goes */
    WIFI_ARGS_UNTERMINATED,    /* a quote opened and never closed */
    WIFI_ARGS_BAD_ESCAPE,      /* a backslash in quotes not before " or \ */
    WIFI_ARGS_AFTER_QUOTE,     /* text straight after a closing quote, or after the password's */
    WIFI_ARGS_SSID_LENGTH,     /* an SSID longer than 32 bytes, or "" */
    WIFI_ARGS_PASSWORD_LENGTH, /* 1-7 characters, 64 that are not all hex digits, or over 64 */
} wifi_args_result_t;

/* Parses what follows "@wifi " into ssid (33 bytes) and pass (65 bytes; "" for an open
 * network). On an error both are left empty. */
wifi_args_result_t wifi_args_parse(const char *args, char ssid[WIFI_SSID_MAX + 1],
                                   char pass[WIFI_PASS_MAX + 1]);

/* True for a password the box can use: none, 8-63 characters, or 64 hex digits. */
bool wifi_pass_valid(const char *pass);

/* A short English line for a result, for the console's log ("stored" for WIFI_ARGS_OK). */
const char *wifi_args_error(wifi_args_result_t r);

#endif /* ATALAIA_WIFI_ARGS_H */
