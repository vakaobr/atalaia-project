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
    run_builtin_presets_tests();
    run_key_filter_tests();
    run_event_log_tests();
    run_time_sync_tests();
    run_radio_stub_tests();
    run_radio_protocol_tests();
    run_radio_power_tests();

    if (check_failures == 0) {
        printf("firmware: all tests passed\n");
        return 0;
    }
    fprintf(stderr, "firmware: %d check(s) failed\n", check_failures);
    return 1;
}
