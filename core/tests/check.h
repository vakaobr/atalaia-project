/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Minimal test helpers for the core. Replace with a proper framework once
 * the core grows.
 */
#ifndef ATALAIA_TEST_CHECK_H
#define ATALAIA_TEST_CHECK_H

#include <stdio.h>

extern int check_failures;

#define CHECK(cond)                                                                                \
    do {                                                                                           \
        if (!(cond)) {                                                                             \
            fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);                        \
            check_failures++;                                                                      \
        }                                                                                          \
    } while (0)

void run_node_tests(void);
void run_codec_tests(void);
void run_packet_tests(void);
void run_flood_tests(void);
void run_ack_tests(void);
void run_duty_cycle_tests(void);
void run_msg_codec_tests(void);
void run_crypto_mbedtls_tests(void);
void run_field_api_tests(void);
void run_join_tests(void);
void run_tag_tests(void);
void run_screen_template_tests(void);
void run_proxy_tests(void);
void run_geo_tests(void);

#endif /* ATALAIA_TEST_CHECK_H */
