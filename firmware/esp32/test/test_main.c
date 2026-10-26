/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * Firmware test entry point. Runs on Linux (no ESP-IDF) with HAL stubs.
 * LVGL runs on a headless display, so every screen the tests trigger goes
 * through the real widget code (the reference images are in test_screens.c).
 */
#include <stdio.h>

#include "check.h"
#include "test_display.h"

int check_failures = 0;
int check_count = 0;

int main(void)
{
    test_display_init();
    run_game_timer_tests();
    run_command_dispatch_tests();
    run_preset_store_tests();
    run_state_persist_tests();
    run_node_runner_tests();
    run_preset_ui_tests();
    run_config_store_tests();
    run_integration_tests();
    run_game_loop_tests();
    run_wifi_setup_tests();
    run_reboot_resume_tests();
    run_screen_renderer_tests();
    run_oled_view_tests();
    run_modem_screen_tests();
    run_builtin_presets_tests();
    run_key_filter_tests();
    run_event_log_tests();
    run_time_sync_tests();
    run_radio_stub_tests();
    run_radio_protocol_tests();
    run_radio_power_tests();
    run_radio_limits_tests();
    run_radio_stats_tests();
    run_modem_framing_tests();
    run_modem_tests();
    run_field_link_tests();
    run_box_game_tests();
    run_box_text_tests();
    run_serial_console_tests();
    run_board_fem_tests();
    run_screen_template_tests();
    run_pod_tests();
    run_fw_update_tests();
    run_mode_package_tests();
    run_mode_fetch_tests();
    run_adoption_tests();
    run_admin_pin_tests();
    run_box_pair_tests();
    run_target_addon_tests();

    if (check_failures == 0) {
        printf("firmware: all %d checks passed\n", check_count);
        return 0;
    }
    fprintf(stderr, "firmware: %d of %d check(s) failed\n", check_failures, check_count);
    return 1;
}
