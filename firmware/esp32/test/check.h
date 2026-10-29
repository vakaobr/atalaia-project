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
extern int check_count;

#define CHECK(cond)                                                                                \
    do {                                                                                           \
        check_count++;                                                                             \
        if (!(cond)) {                                                                             \
            fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);                        \
            check_failures++;                                                                      \
        }                                                                                          \
    } while (0)

void run_game_timer_tests(void);
void run_command_dispatch_tests(void);
void run_preset_store_tests(void);
void run_legacy_files_tests(void);
void run_state_persist_tests(void);
void run_node_runner_tests(void);
void run_preset_ui_tests(void);
void run_config_store_tests(void);
void run_integration_tests(void);
void run_game_loop_tests(void);
void run_wifi_setup_tests(void);
void run_reboot_resume_tests(void);
void run_screen_renderer_tests(void);
void run_oled_view_tests(void);
void run_modem_screen_tests(void);
void run_builtin_presets_tests(void);
void run_key_filter_tests(void);
void run_event_log_tests(void);
void run_time_sync_tests(void);
void run_radio_stub_tests(void);
void run_radio_protocol_tests(void);
void run_radio_power_tests(void);
void run_radio_limits_tests(void);
void run_radio_stats_tests(void);
void run_lbt_tests(void);
void run_radio_lbt_tests(void);
void run_modem_framing_tests(void);
void run_modem_tests(void);
void run_field_link_tests(void);
void run_box_game_tests(void);
void run_box_text_tests(void);
void run_serial_console_tests(void);
void run_board_fem_tests(void);
void run_screen_template_tests(void);
void run_pod_tests(void);
void run_pod_settings_tests(void);
void run_fw_update_tests(void);
void run_mode_package_tests(void);
void run_mode_fetch_tests(void);
void run_box_beacon_tests(void);
void run_adoption_tests(void);
void run_admin_pin_tests(void);
void run_box_pair_tests(void);
void run_status_hold_tests(void);
void run_target_addon_tests(void);

#endif /* ATALAIA_FW_TEST_CHECK_H */
