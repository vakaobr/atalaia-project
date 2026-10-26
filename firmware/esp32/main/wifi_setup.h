/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Wi-Fi captive portal for first-time node configuration. Opens a
 * SoftAP named atalaia-XXXX, serves an embedded HTML config page,
 * and writes settings to NVS on submit.
 *
 * It is a captive portal as phones expect: a DNS responder answers every name with the AP's
 * address, and every other page (the operating systems' connectivity checks, /generate_204,
 * /hotspot-detect.html, /connecttest.txt) redirects to the setup page, so a phone opens it by
 * itself after joining the network. The page and its answers are in the box's languages
 * (en, pt, de, zh-tw): the box's own language when a game gave one, else the browser's
 * Accept-Language, else English; "/?lang=pt" chooses one.
 */
#ifndef ATALAIA_WIFI_SETUP_H
#define ATALAIA_WIFI_SETUP_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "box_text.h"

/*
 * Start the captive-portal setup flow. On ESP32 this starts SoftAP,
 * a DNS responder and an HTTP server. In stub builds it does nothing.
 * Returns 0 on success.
 */
int wifi_setup_start(void);

/* The SoftAP name (atalaia-XXXX) after wifi_setup_start(); "" before it or in stub builds. */
const char *wifi_setup_ssid(void);

/* Stop the captive portal and free resources. */
void wifi_setup_stop(void);

/*
 * Where the form's optional field join key (64 hex digits, protocol/join.md)
 * goes; the handler returns false if it is not a valid key. Set by the shell
 * before wifi_setup_start(). Without a handler the field is ignored.
 */
void wifi_setup_set_join_key_handler(bool (*handler)(const char *hex));

/*
 * Why the form's admin PIN is refused, or NULL: 4-8 digits, and not one too easy to guess
 * (admin_pin_weak: 1234, 0000, a sequence, a repeated pair). A Field Box has no default
 * PIN; this is where its first one is set (decision AD-29).
 */
const char *wifi_setup_pin_problem(const char *pin);

/*
 * The page's language (every text of the portal): an explicit one ("?lang=pt", query_lang,
 * "" or NULL for none) first; else the box's, when a game gave it one (box_text.h); else the
 * best of the browser's Accept-Language the box has a language for (by q value, then order;
 * "zh-TW" and "zh-Hant" are Traditional Chinese, "zh-CN" is not); else English.
 */
box_lang_t wifi_setup_pick_lang(const char *query_lang, const char *accept_language);

/* The portal's answers to a form that cannot be saved, and the page that says it did. */
typedef enum {
    WS_MSG_BAD_BODY,
    WS_MSG_NAME,
    WS_MSG_REGION, /* %s: the region this box is built for */
    WS_MSG_PIN_DIGITS,
    WS_MSG_PIN_WEAK,
    WS_MSG_JOIN_KEY,
    WS_MSG_WIFI_PASS,
    WS_MSG_SAVED,
    WS_MSG_COUNT,
} wifi_setup_msg_t;
const char *wifi_setup_msg(box_lang_t lang, wifi_setup_msg_t msg);

/* wifi_setup_pin_problem in a language. */
const char *wifi_setup_pin_problem_in(box_lang_t lang, const char *pin);

/*
 * The captive portal's DNS answer to one query packet: every A (and ANY) question for any name
 * is answered with ip (a 30 s TTL), every other type (AAAA, ...) with no answer (NOERROR, so a
 * phone falls back to A). Writes into out (cap bytes) and returns its length, or 0 for a packet
 * that is not one standard query with one question (a response, another opcode, a compressed
 * or cut name, ...): no answer. The answer is at most 16 bytes longer than the question.
 */
size_t wifi_setup_dns_reply(const uint8_t *query, size_t len, uint8_t *out, size_t cap,
                            const uint8_t ip[4]);

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
