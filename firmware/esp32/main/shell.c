/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * shell.c -- Atalaia Field Box firmware entry point.
 *
 * Boot sequence: detect PSRAM -> select tier -> init HAL -> check
 * config -> start Wi-Fi setup or preset picker -> run game loop.
 */

#include <stdio.h>
#include <string.h>

#include "atalaia/version.h"
#include "button_tracker.h"
#include "config_store.h"
#include "game_timer.h"
#include "hal/hal.h"
#include "mem_monitor.h"
#include "node_runner.h"
#include "preset_store.h"
#include "preset_ui.h"
#include "screen_renderer.h"
#include "state_persist.h"
#include "wifi_setup.h"

#ifdef ESP_PLATFORM
/* ---- ESP-IDF build ---------------------------------------------------- */
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_psram.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "hal/esp/hal_esp.h"
#include "nvs_flash.h"

static const char *TAG = "atalaia";

/* ---- Shared state ----------------------------------------------------- */

static hal_t hal;
static node_runner_t runner;
static button_tracker_t btn_tracker;
static preset_ui_t preset_ui;
static size_t mem_limit;

static QueueHandle_t screen_queue;
static QueueHandle_t audio_queue;

/* Default teams until the config store provides configurable team names. */
static const char *const default_teams[] = {"red", "blue", "green", "yellow"};

/* ------------------------------------------------------------------ */
/* FreeRTOS tasks (ADR-P1-7)                                           */
/* ------------------------------------------------------------------ */

/*
 * game_task -- core 1, priority 5, 10 ms tick.
 * Polls buttons and keypad, ticks the node runner, checks preset UI.
 */
static void task_game(void *arg)
{
    (void)arg;
    ESP_LOGI(TAG, "game task started");
    TickType_t last_wake = xTaskGetTickCount();
    const uint32_t delta_ms = 10;

    for (;;) {
        /* ---- Poll buttons -> hold / release events ---- */
        uint8_t buttons = hal.buttons->poll();
        button_tracker_update(&btn_tracker, buttons, delta_ms, &runner);

        /* ---- Poll keypad ---- */
        char key = hal.keypad->scan();
        if (key != HAL_KEY_NONE) {
            if (preset_ui_get_state(&preset_ui) != PRESET_UI_STATE_GAME_STARTED) {
                preset_ui_handle_key(&preset_ui, key);
            } else if (runner.running) {
                char json[64];
                snprintf(json, sizeof(json), "{\"key\":\"%c\"}", key);
                node_runner_input(&runner, "keypad.key", json);
            }
        }

        /* ---- Tick the game loop ---- */
        if (runner.running) {
            node_runner_tick(&runner, delta_ms);

            /* Forward screen updates to the LVGL queue. */
            for (int i = 0; i < runner.queues.screen_count; i++) {
                xQueueSend(screen_queue, &runner.queues.screens[i], 0);
            }
            runner.queues.screen_count = 0;

            /* Forward audio commands to the audio queue. */
            for (int i = 0; i < runner.queues.audio_count; i++) {
                xQueueSend(audio_queue, &runner.queues.audio[i], 0);
            }
            runner.queues.audio_count = 0;
        }

        /* ---- Check if preset UI wants to start a game ---- */
        if (preset_ui_get_state(&preset_ui) == PRESET_UI_STATE_GAME_STARTED && !runner.running) {
            int idx = preset_ui_selected_preset(&preset_ui);
            preset_t p;
            if (preset_store_load(idx, &p)) {
                p.duration_s = preset_ui_timer_duration(&preset_ui);

                /* Determine team count from config or default. */
                uint8_t team_count = 2;
                node_runner_start(&runner, &p, default_teams, team_count);
                button_tracker_init(&btn_tracker, default_teams, team_count);

                ESP_LOGI(TAG, "Game started: preset %d, timer %lu s", idx,
                         (unsigned long)p.duration_s);
            }
        }

        vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(delta_ms));
    }
}

/*
 * lvgl_task -- core 1, priority 4, 5 ms.
 * Dequeues screen_update_t messages and renders them.
 */
static void task_lvgl(void *arg)
{
    (void)arg;
    ESP_LOGI(TAG, "lvgl task started");

    for (;;) {
        screen_update_t su;
        if (xQueueReceive(screen_queue, &su, pdMS_TO_TICKS(5)) == pdTRUE) {
            screen_render(su.template_name, su.data_json);
        }

        /* TODO: lv_timer_handler() -- stub until LVGL display is wired. */

        vTaskDelay(pdMS_TO_TICKS(5));
    }
}

/*
 * audio_task -- core 0, priority 3.
 * Dequeues audio_cmd_t messages and plays clips or tones.
 */
static void task_audio(void *arg)
{
    (void)arg;
    ESP_LOGI(TAG, "audio task started");

    for (;;) {
        audio_cmd_t cmd;
        if (xQueueReceive(audio_queue, &cmd, portMAX_DELAY) == pdTRUE) {
            if (cmd.clip[0] == '\0') {
                hal.audio->stop();
            } else {
                hal.audio->play_wav(cmd.clip);
            }
        }
    }
}

/*
 * wifi_task -- core 0, priority 2.
 * Runs only during setup; sleeps in normal mode.
 */
static void task_wifi(void *arg)
{
    (void)arg;
    ESP_LOGI(TAG, "wifi task started");
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(100));
    }
}

/* ------------------------------------------------------------------ */
/* app_main                                                            */
/* ------------------------------------------------------------------ */
void app_main(void)
{
    /* PSRAM detection. */
    const char *tier;
    size_t psram_size = esp_psram_get_size();
    if (psram_size > 0) {
        ESP_LOGI(TAG, "PSRAM detected: %u KB", (unsigned)(psram_size / 1024));
        tier = "full";
        mem_limit = 256u * 1024u;
    } else {
        ESP_LOGW(TAG, "No PSRAM -- reduced tier");
        tier = "reduced";
        mem_limit = 64u * 1024u;
    }

    ESP_LOGI(TAG, "Atalaia v%s  tier=%s", atalaia_version(), tier);

    /* NVS init (needed for config_store and Wi-Fi). */
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        nvs_flash_erase();
        nvs_flash_init();
    }

    /* Network init. */
    esp_netif_init();
    esp_event_loop_create_default();

    /* HAL init. */
    hal_esp_init(&hal);

    /* Config store. */
    config_store_init();

    /* Preset and state storage. */
    preset_store_init("/littlefs");
    state_persist_init("/littlefs/state");

    /* Inter-task queues. */
    screen_queue = xQueueCreate(CMD_SCREEN_QUEUE_MAX, sizeof(screen_update_t));
    audio_queue = xQueueCreate(CMD_AUDIO_QUEUE_MAX, sizeof(audio_cmd_t));

    /* Node runner. */
    node_runner_init(&runner, &hal, mem_limit);

    /* Button tracker (default teams until game starts with preset's teams). */
    button_tracker_init(&btn_tracker, default_teams, 2);

    /* Memory monitor. */
    mem_monitor_start();

    /* Check if initial setup is needed. */
    if (!config_store_is_configured()) {
        ESP_LOGI(TAG, "Not configured -- starting Wi-Fi setup portal");
        wifi_setup_start();
    } else {
        ESP_LOGI(TAG, "Configured -- starting normal mode");

        /* Try to resume from a previously saved game (reboot recovery). */
        state_persist_data_t saved;
        preset_t resumed_preset;
        bool resumed = false;

        if (state_persist_load(&saved) && preset_store_load(saved.preset_index, &resumed_preset)) {
            uint8_t tc = saved.team_count;
            if (tc < 2) tc = 2;
            if (tc > 4) tc = 4;
            if (node_runner_resume(&runner, &saved, resumed_preset.source,
                                   resumed_preset.source_len, resumed_preset.params_json,
                                   default_teams, tc)) {
                button_tracker_init(&btn_tracker, default_teams, tc);
                runner.preset_index = saved.preset_index;
                resumed = true;
                ESP_LOGI(TAG, "Resumed game from saved state (preset %d, game_time %lu ms)",
                         saved.preset_index, (unsigned long)saved.game_time_ms);
            }
        }

        if (!resumed) {
            /* No valid saved state -- start the normal preset picker. */
            char admin_pin[9] = "1234";
            config_store_get_str("admin_pin", admin_pin, sizeof(admin_pin));

            preset_summary_t summaries[PRESET_MAX_SLOTS];
            int preset_count = preset_store_list(summaries, PRESET_MAX_SLOTS);

            preset_ui_init(&preset_ui, admin_pin, preset_count);
        }
    }

    /* FreeRTOS tasks per ADR-P1-7. */
    xTaskCreatePinnedToCore(task_game, "game", 6144, NULL, 5, NULL, 1);
    xTaskCreatePinnedToCore(task_lvgl, "lvgl", 6144, NULL, 4, NULL, 1);
    xTaskCreatePinnedToCore(task_audio, "audio", 4096, NULL, 3, NULL, 0);
    xTaskCreatePinnedToCore(task_wifi, "wifi", 4096, NULL, 2, NULL, 0);
}

#else
/* ---- Native / stub build (CI, unit tests) ----------------------------- */

int main(void)
{
    printf("Atalaia firmware v%s (stub build)\n", atalaia_version());
    return 0;
}

#endif /* ESP_PLATFORM */
