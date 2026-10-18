/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Minimal test helpers for the firmware shell (same pattern as core/tests/check.h).
 */
#ifndef ATALAIA_FW_TEST_CHECK_H
#define ATALAIA_FW_TEST_CHECK_H

#include <stdio.h>

extern int check_failures;

#define CHECK(cond)                                                                                \
    do {                                                                                           \
        if (!(cond)) {                                                                             \
            fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);                        \
            check_failures++;                                                                      \
        }                                                                                          \
    } while (0)

void run_game_timer_tests(void);
void run_command_dispatch_tests(void);
void run_preset_store_tests(void);
void run_state_persist_tests(void);
void run_node_runner_tests(void);
void run_preset_ui_tests(void);
void run_config_store_tests(void);
void run_integration_tests(void);
void run_game_loop_tests(void);
void run_wifi_setup_tests(void);
void run_reboot_resume_tests(void);
void run_screen_renderer_tests(void);
void run_builtin_presets_tests(void);
void run_key_filter_tests(void);
void run_event_log_tests(void);
void run_time_sync_tests(void);
void run_radio_stub_tests(void);
void run_radio_protocol_tests(void);
void run_radio_power_tests(void);

#endif /* ATALAIA_FW_TEST_CHECK_H */
