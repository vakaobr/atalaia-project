/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Wi-Fi captive portal for first-time node configuration. Opens a
 * SoftAP named atalaia-XXXX, serves an embedded HTML config page,
 * and writes settings to NVS on submit.
 */
#ifndef ATALAIA_WIFI_SETUP_H
#define ATALAIA_WIFI_SETUP_H

#include <stdbool.h>

/*
 * Start the captive-portal setup flow. On ESP32 this starts SoftAP,
 * DNS redirection and an HTTP server. In stub builds it does nothing.
 * Returns 0 on success.
 */
int wifi_setup_start(void);

/* The SoftAP name (atalaia-XXXX) after wifi_setup_start(); "" before it or in stub builds. */
const char *wifi_setup_ssid(void);

/* Stop the captive portal and free resources. */
void wifi_setup_stop(void);

/*
 * Parse a single field from a URL-encoded form body (e.g. "name=val&k2=v2").
 * URL-decodes %XX sequences and '+' (space). Copies at most out_sz-1 bytes
 * into out and NUL-terminates.
 *
 * Returns true if the field was found, false otherwise (out is set to "").
 * Platform-independent: works on both ESP32 and Linux.
 */
bool parse_form_field(const char *body, const char *key, char *out, int out_sz);

#endif /* ATALAIA_WIFI_SETUP_H */
