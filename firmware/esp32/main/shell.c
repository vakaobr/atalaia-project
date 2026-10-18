/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * shell.c -- Atalaia Field Box firmware entry point.
 *
 * Boot sequence: detect PSRAM -> select tier -> mount storage -> init HAL
 * (missing parts are logged and skipped) -> check config -> start Wi-Fi
 * setup, rejoin a stored field game, or start the preset picker -> run the
 * game loop.
 *
 * A box plays stand-alone (the preset picker) or in a field controller's
 * game (box_game.c): joined with an NFC join card or "@join" on the serial
 * console, driven by the controller's CMD and TIME over the radio, its
 * events, STATE and scores sent back (radio/field_link.c, decision D18).
 */

#include <stdio.h>
#include <string.h>

#include "atalaia/join.h"
#include "atalaia/packet.h"
#include "atalaia/version.h"
#include "box_game.h"
#include "builtin_presets.h"
#include "button_tracker.h"
#include "config_store.h"
#include "game_timer.h"
#include "hal/hal.h"
#include "key_filter.h"
#include "mem_monitor.h"
#include "node_runner.h"
#include "preset_store.h"
#include "preset_ui.h"
#include "screen_renderer.h"
#include "state_persist.h"
#include "radio/event_log.h"
#include "radio/radio_task.h"
#include "serial_console.h"
#include "wifi_setup.h"

#ifdef ESP_PLATFORM
/* ---- ESP-IDF build ---------------------------------------------------- */
#include "display_port.h"
#include "esp_event.h"
#include "esp_littlefs.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_psram.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "hal/esp/hal_esp.h"
#include "nvs_flash.h"
#include "radio/radio_nvs_esp.h"
#include "sdkconfig.h"

/* Console input (keys, "@join", "@joinkey") from UART0 and, on the Heltec V4
 * whose only USB port is the ESP32-S3's own, from USB-Serial-JTAG. */
#define SERIAL_WANTED (CONFIG_ATALAIA_SERIAL_KEYS || CONFIG_ATALAIA_SERIAL_JOIN)
#define SERIAL_UART   (SERIAL_WANTED && CONFIG_ESP_CONSOLE_UART)
#define SERIAL_USB    (SERIAL_WANTED && CONFIG_ATALAIA_CONSOLE_USB_INPUT)
#define SERIAL_INPUT  (SERIAL_UART || SERIAL_USB)
#if SERIAL_UART
#include "driver/uart.h"
#endif
#if SERIAL_USB
#include "driver/usb_serial_jtag.h"
#include "driver/usb_serial_jtag_vfs.h"
#endif

static const char *TAG = "atalaia";

#define STORAGE_PATH "/littlefs"

/* ---- Shared state ----------------------------------------------------- */

static hal_t hal;
static node_runner_t runner;
static button_tracker_t btn_tracker;
static preset_ui_t preset_ui;
static bool picker_active; /* the keypad drives the preset picker */
static key_filter_t key_filter;
static size_t mem_limit;

static preset_summary_t presets[PRESET_MAX_SLOTS];
static const char *preset_labels[PRESET_MAX_SLOTS];
static int preset_count;
static screen_update_t picker_screen; /* last picker screen sent */

/* preset_t holds an 8 KB source buffer: static, not on a task stack. */
static preset_t game_preset;

static QueueHandle_t screen_queue;
static QueueHandle_t audio_queue;

/* Default teams until the config store provides configurable team names. */
static const char *const default_teams[] = {"red", "blue", "green", "yellow"};

/* A field controller's game (box_game.h) and its flash event log. */
static box_game_t box;
static event_log_t game_log;
static bool box_teams_set;    /* the button tracker uses the joined game's teams */
static bool box_was_active;   /* to notice the end of a field game */
static bool after_field_game; /* a field game ended: the next key brings the picker back */
static uint8_t nfc_mem[888];  /* NTAG216 user memory */
static uint8_t nfc_last_uid[10];
static uint8_t nfc_last_uid_len;
static uint32_t nfc_last_poll_ms;
#if SERIAL_UART
static serial_console_t console_uart;
static bool uart_input;
#endif
#if SERIAL_USB
static serial_console_t console_usb;
static bool usb_input;
#endif

/* Mode sources built into the firmware (main/CMakeLists.txt, from modes/). */
extern const char bomb_node_lua_start[] asm("_binary_bomb_node_lua_start");
extern const char domination_node_lua_start[] asm("_binary_domination_node_lua_start");

/* ------------------------------------------------------------------ */
/* Helpers                                                             */
/* ------------------------------------------------------------------ */

static void send_screen(const char *template_name, const char *data_json)
{
    screen_update_t su;
    snprintf(su.template_name, sizeof(su.template_name), "%s", template_name);
    snprintf(su.data_json, sizeof(su.data_json), "%s", data_json);
    xQueueSend(screen_queue, &su, 0);
}

/* Show the picker's current step, if it changed. */
static void show_picker(void)
{
    screen_update_t su;
    if (!preset_ui_screen(&preset_ui, preset_labels, preset_count, &su)) return;
    if (strcmp(su.template_name, picker_screen.template_name) == 0 &&
        strcmp(su.data_json, picker_screen.data_json) == 0) {
        return;
    }
    picker_screen = su;
    xQueueSend(screen_queue, &su, 0);
}

static void load_preset_list(void)
{
    preset_count = preset_store_list(presets, PRESET_MAX_SLOTS);
    for (int i = 0; i < preset_count; i++) preset_labels[i] = presets[i].label;
    ESP_LOGI(TAG, "%d preset(s) stored", preset_count);
}

static void start_picker(void)
{
    char admin_pin[9] = "1234";
    config_store_get_str("admin_pin", admin_pin, sizeof(admin_pin));
    preset_ui_init(&preset_ui, admin_pin, preset_count);
    memset(&picker_screen, 0, sizeof(picker_screen));
    picker_active = true;
    show_picker();
}

#if SERIAL_INPUT
static void serial_input_init(void)
{
#if SERIAL_UART
    serial_console_init(&console_uart);
    esp_err_t err = uart_driver_install(CONFIG_ESP_CONSOLE_UART_NUM, 1024, 0, 0, NULL, 0);
    uart_input = err == ESP_OK;
    if (!uart_input) ESP_LOGW(TAG, "UART console input unavailable: %s", esp_err_to_name(err));
#endif
#if SERIAL_USB
    /* With the driver, console output to USB is dropped after 50 ms when no host
     * listens (IDF's USB-Serial-JTAG VFS), so a box on battery never blocks. */
    serial_console_init(&console_usb);
    usb_serial_jtag_driver_config_t usb_cfg = USB_SERIAL_JTAG_DRIVER_CONFIG_DEFAULT();
    esp_err_t uerr = usb_serial_jtag_driver_install(&usb_cfg);
    usb_input = uerr == ESP_OK;
    if (usb_input) {
        usb_serial_jtag_vfs_use_driver();
    } else {
        ESP_LOGW(TAG, "USB console input unavailable: %s", esp_err_to_name(uerr));
    }
#endif
#if CONFIG_ATALAIA_SERIAL_KEYS
    ESP_LOGI(TAG, "serial keys on: type 0-9, * and # on the console");
#endif
#if CONFIG_ATALAIA_SERIAL_JOIN
    ESP_LOGI(TAG,
             "serial join on: \"@join atalaia:join:...\" or \"@joinkey <hex>\" on the console");
#endif
}

static void serial_command(const char *cmd)
{
#if CONFIG_ATALAIA_SERIAL_JOIN
    if (strncmp(cmd, "join ", 5) == 0) {
        box_join_result_t r = box_game_join_text(&box, cmd + 5);
        ESP_LOGI(TAG, "join: %s", box_join_result_name(r));
        if (r == BOX_JOIN_OK) picker_active = false;
        return;
    }
    if (strncmp(cmd, "joinkey ", 8) == 0) {
        if (box_game_active(&box)) {
            ESP_LOGW(TAG, "join key: refused while a game is joined");
        } else {
            ESP_LOGI(TAG, "join key: %s",
                     box_game_set_join_key_hex(&box, cmd + 8) ? "stored"
                                                              : "refused (64 hex digits)");
        }
        return;
    }
#endif
    ESP_LOGW(TAG, "unknown console command: @%.20s", cmd);
}

/* One byte from a console input, without waiting. */
#if SERIAL_UART
static bool read_uart(uint8_t *c)
{
    return uart_input && uart_read_bytes(CONFIG_ESP_CONSOLE_UART_NUM, c, 1, 0) == 1;
}
#endif
#if SERIAL_USB
static bool read_usb(uint8_t *c)
{
    return usb_input && usb_serial_jtag_read_bytes(c, 1, 0) == 1;
}
#endif

/* Reads what one console input received: returns one keypad key (or
 * HAL_KEY_NONE) and handles complete '@' command lines. */
static char serial_poll_one(serial_console_t *console, bool (*read1)(uint8_t *c))
{
    uint8_t c;
    char key_out = HAL_KEY_NONE;
    while (read1(&c)) {
        char key;
        const char *command = NULL;
        serial_input_t in = serial_console_feed(console, (char)c, &key, &command);
        if (in == SERIAL_COMMAND) {
            serial_command(command);
        } else if (in == SERIAL_KEY && key_out == HAL_KEY_NONE) {
#if CONFIG_ATALAIA_SERIAL_KEYS
            key_out = key;
            break; /* one key per tick, like the keypad */
#else
            (void)key; /* keys only with CONFIG_ATALAIA_SERIAL_KEYS */
#endif
        }
    }
    return key_out;
}

static char serial_poll(void)
{
    char key = HAL_KEY_NONE;
#if SERIAL_USB
    key = serial_poll_one(&console_usb, read_usb);
#endif
#if SERIAL_UART
    if (key == HAL_KEY_NONE) key = serial_poll_one(&console_uart, read_uart);
#endif
    return key;
}
#endif

/* ---- Field game glue (box_game_t shell ops) --------------------------- */

static void box_screen(void *user, const char *tmpl, const char *data)
{
    (void)user;
    send_screen(tmpl, data);
}

static void box_log(void *user, const char *line)
{
    (void)user;
    ESP_LOGI(TAG, "field: %s", line);
}

static void box_reboot(void *user)
{
    (void)user;
    esp_restart();
}

static bool box_set_channel(void *user, uint32_t hz)
{
    (void)user;
    return hal.radio != NULL && radio_task_set_channel(hz);
}

static int box_battery(void *user)
{
    (void)user;
    hal_battery_info_t b = hal.battery->read();
    return b.voltage_mv > 0 ? (int)b.percent : -1;
}

static bool box_radio_send(void *user, const uint8_t *pkt, size_t len)
{
    (void)user;
    return radio_task_send(pkt, len);
}

static bool portal_join_key(const char *hex)
{
    return box_game_set_join_key_hex(&box, hex);
}

/* NFC join cards, while no game is being played: at most every 500 ms. */
static void poll_join_card(uint32_t now)
{
    if (box.phase == BOX_PLAYING || now - nfc_last_poll_ms < 500) return;
    nfc_last_poll_ms = now;
    hal_nfc_tag_t tag;
    if (!hal.nfc->poll(&tag)) {
        nfc_last_uid_len = 0; /* the card was taken away */
        return;
    }
    if (tag.uid_len == nfc_last_uid_len && memcmp(tag.uid, nfc_last_uid, tag.uid_len) == 0) {
        return; /* the same card is still on the reader */
    }
    memcpy(nfc_last_uid, tag.uid, sizeof(nfc_last_uid));
    nfc_last_uid_len = tag.uid_len;
    int n = hal.nfc->read_user_memory(nfc_mem, sizeof(nfc_mem));
    if (n <= 0) return;
    box_join_result_t r = box_game_join_tag(&box, nfc_mem, (size_t)n);
    if (r == BOX_JOIN_NOT_A_JOIN) return; /* some other tag */
    ESP_LOGI(TAG, "join card: %s", box_join_result_name(r));
    if (r == BOX_JOIN_OK) picker_active = false;
}

static void box_start(const char *tier)
{
    const atalaia_radio_nvs_ops_t *nvs = atalaia_radio_nvs_esp_init();
    if (event_log_init(&game_log, STORAGE_PATH) != 0) {
        ESP_LOGW(TAG, "event log unavailable");
    }
    atalaia_hello_t hello;
    memset(&hello, 0, sizeof(hello));
    char name[25] = "field-box";
    config_store_get_str("node_name", name, sizeof(name));
    snprintf(hello.node_name, sizeof(hello.node_name), "%s", name);
    hello.platform = 1; /* esp32s3 */
    snprintf(hello.fw_version, sizeof(hello.fw_version), "%s", atalaia_version());
    snprintf(hello.core_version, sizeof(hello.core_version), "%s", atalaia_version());
    hello.tier = strcmp(tier, "full") == 0 ? 0 : 1;
    hello.transports = 1; /* LoRa */
    hello.battery_pct = 0xFF;
    box_store_ops_t no_store = {0};
    box_shell_ops_t ops = {.screen = box_screen,
                           .log = box_log,
                           .reboot = box_reboot,
                           .set_channel = box_set_channel,
                           .battery_pct = box_battery,
                           .radio_send = box_radio_send,
                           .user = NULL};
    box_game_init(&box, &runner, &game_preset, nvs ? atalaia_box_store_esp() : &no_store, &ops,
                  &atalaia_crypto_mbedtls, nvs, &game_log, &hello);
    box.state_interval_ms = (uint32_t)CONFIG_ATALAIA_STATE_INTERVAL_S * 1000u;
    if (!atalaia_nvs_encrypted()) {
        ESP_LOGW(TAG, "NVS encryption is off: the game key and the field join key are stored in "
                      "plain NVS (development only; BRING_UP.md step 0)");
    }
    if (!box_game_load_join_key(&box)) {
        const char *dev = CONFIG_ATALAIA_DEV_JOIN_KEY;
        if (dev[0] != '\0' && box_game_use_join_key_hex(&box, dev)) {
            ESP_LOGW(TAG, "using the development field join key (CONFIG_ATALAIA_DEV_JOIN_KEY)");
        } else {
            ESP_LOGW(TAG, "no field join key: join cards are refused until it is set "
                          "(\"@joinkey\" or the setup portal)");
        }
    }
    wifi_setup_set_join_key_handler(portal_join_key);
}

/* Start the game the picker chose. */
static void start_game(void)
{
    picker_active = false;
    int pick = preset_ui_selected_preset(&preset_ui);
    int slot = (pick >= 1 && pick <= preset_count) ? presets[pick - 1].index : pick;
    if (!preset_store_load(slot, &game_preset)) {
        ESP_LOGE(TAG, "cannot load preset %d", slot);
        start_picker();
        return;
    }
    game_preset.duration_s = preset_ui_timer_duration(&preset_ui);

    /* Shown until the mode draws its own screen (Domination draws none while it runs). */
    char data[SCREEN_DATA_MAX];
    const char *label = game_preset.label[0] ? game_preset.label : game_preset.mode_id;
    snprintf(data, sizeof(data), "{\"title\":\"Game on\",\"mode\":\"%.40s\",\"timer_s\":%u}", label,
             (unsigned)game_preset.duration_s);
    send_screen("status", data);

    /* Determine team count from config or default. */
    uint8_t team_count = 2;
    if (!node_runner_start(&runner, &game_preset, default_teams, team_count)) {
        ESP_LOGE(TAG, "cannot start preset %d (%s)", slot, game_preset.mode_id);
        start_picker();
        return;
    }
    runner.preset_index = slot;
    button_tracker_init(&btn_tracker, default_teams, team_count);
    ESP_LOGI(TAG, "Game started: preset %d (%s), timer %lu s", slot, label,
             (unsigned long)game_preset.duration_s);
}

/* ------------------------------------------------------------------ */
/* FreeRTOS tasks (ADR-P1-7)                                           */
/* ------------------------------------------------------------------ */

/*
 * game_task -- core 1, priority 5, 10 ms tick.
 * Polls buttons and keypad, ticks the node runner, drives the preset picker.
 */
static void task_game(void *arg)
{
    (void)arg;
    ESP_LOGI(TAG, "game task started");
    TickType_t last_wake = xTaskGetTickCount();
    const uint32_t delta_ms = 10;

    for (;;) {
        uint32_t now = (uint32_t)(esp_timer_get_time() / 1000);

        /* ---- Radio: packets heard by the radio task ---- */
        radio_rx_msg_t rx;
        while (radio_task_recv(&rx)) {
            box_game_on_packet(&box, rx.data, rx.len, rx.rssi);
        }

        /* ---- Poll buttons -> hold / release events ---- */
        if (box.phase == BOX_PLAYING && !box_teams_set) {
            /* The joined game's teams on the buttons (up to four). */
            int teams =
                box.join.team_count > BUTTON_TRACKER_MAX ? BUTTON_TRACKER_MAX : box.join.team_count;
            button_tracker_init(&btn_tracker, box.teams, teams);
            box_teams_set = true;
        } else if (box.phase == BOX_IDLE && box_teams_set) {
            button_tracker_init(&btn_tracker, default_teams, 2);
            box_teams_set = false;
        }
        uint8_t buttons = hal.buttons->poll();
        button_tracker_update(&btn_tracker, buttons, delta_ms, &runner);

        /* ---- Poll keypad: one press per key stroke ---- */
        char key = key_filter_update(&key_filter, hal.keypad->scan());
#if SERIAL_INPUT
        char serial = serial_poll();
        if (key == HAL_KEY_NONE) key = serial;
#endif
        if (key != HAL_KEY_NONE) {
            if (picker_active) {
                preset_ui_handle_key(&preset_ui, key);
                show_picker();
            } else if (runner.running) {
                char json[64];
                snprintf(json, sizeof(json), "{\"key\":\"%c\"}", key);
                node_runner_input(&runner, "keypad.key", json);
            } else if (after_field_game) {
                after_field_game = false;
                start_picker();
            }
        }

        /* ---- NFC join cards ---- */
        poll_join_card(now);

        /* ---- Start the game the picker confirmed ---- */
        if (picker_active && preset_ui_get_state(&preset_ui) == PRESET_UI_STATE_GAME_STARTED &&
            !runner.running) {
            start_game();
        }

        /* ---- Tick the game loop (a field game ticks its own runner, time-synced) ---- */
        if (box_game_active(&box)) {
            box_game_tick(&box, delta_ms, now);
        } else if (runner.running) {
            node_runner_tick(&runner, delta_ms);
        }
        if (box_was_active && !box_game_active(&box)) after_field_game = true;
        box_was_active = box_game_active(&box);
        if (runner.running || runner.queues.screen_count || runner.queues.audio_count) {
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

        vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(delta_ms));
    }
}

/*
 * lvgl_task -- core 1, priority 4, 5 ms.
 * Owns LVGL: brings up the display, renders queued screens, runs LVGL timers.
 */
static void task_lvgl(void *arg)
{
    (void)arg;
    ESP_LOGI(TAG, "lvgl task started");
    display_port_init(hal.display);

    for (;;) {
        screen_update_t su;
        while (xQueueReceive(screen_queue, &su, 0) == pdTRUE) {
            ESP_LOGI(TAG, "screen %s %s", su.template_name, su.data_json);
            if (!screen_render(su.template_name, su.data_json)) {
                ESP_LOGW(TAG, "unknown screen template '%s'", su.template_name);
            }
        }
        display_port_handle();
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
/* Boot                                                                */
/* ------------------------------------------------------------------ */

static void mount_storage(void)
{
    esp_vfs_littlefs_conf_t conf = {
        .base_path = STORAGE_PATH,
        .partition_label = "storage",
        .format_if_mount_failed = true, /* a new or erased box formats its storage once */
    };
    esp_err_t err = esp_vfs_littlefs_register(&conf);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "storage mount failed (%s): presets and resume unavailable",
                 esp_err_to_name(err));
    }
}

/*
 * Bring up each peripheral. A part that is missing or fails is logged and
 * left out; the box still boots (the Wokwi emulator has no PN532, MAX17048,
 * SX1262 or I2S amplifier). The display comes up on the LVGL task.
 */
static void hal_start(void)
{
    if (hal.buttons->init() != 0) ESP_LOGW(TAG, "team buttons: GPIO setup failed");
    if (hal.keypad->init() != 0) ESP_LOGW(TAG, "keypad: not available");
    if (hal.leds->init() != 0) ESP_LOGW(TAG, "LED ring: not available");
    if (hal.nfc->init() != 0) ESP_LOGW(TAG, "NFC: not available");
    if (hal.audio->init() != 0) ESP_LOGW(TAG, "audio: not available");
    if (hal.battery->init() != 0) ESP_LOGW(TAG, "battery gauge: not available");
    if (hal.radio->init() != 0) {
        ESP_LOGW(TAG, "radio: not available (no SX1262)");
        hal.radio = NULL; /* signal to the rest of the shell */
    }
    hal.audio->set_volume((uint8_t)config_store_get_u32("volume", 80));
}

/* ---- Field game: radio task first, so a rejoined box can send at once ---- */

static void seed_presets(void)
{
    const builtin_source_t sources[] = {
        {"org.atalaia.bomb", bomb_node_lua_start, strlen(bomb_node_lua_start)},
        {"org.atalaia.domination", domination_node_lua_start, strlen(domination_node_lua_start)},
    };
    int n = builtin_presets_seed(sources, 2);
    if (n > 0) ESP_LOGI(TAG, "stored %d built-in preset(s)", n);
}

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

    /* Config store. */
    config_store_init();

    /* HAL init: power the peripherals (Vext), assign the drivers, then bring up each part. */
    hal_esp_board_power_on();
    hal_esp_init(&hal);
    hal_start();
    key_filter_init(&key_filter);
#if SERIAL_INPUT
    serial_input_init();
#endif

    /* Preset and state storage. */
    mount_storage();
    preset_store_init(STORAGE_PATH);
    state_persist_init(STORAGE_PATH "/state");
    seed_presets();
    load_preset_list();

    /* Inter-task queues. */
    screen_queue = xQueueCreate(CMD_SCREEN_QUEUE_MAX, sizeof(screen_update_t));
    audio_queue = xQueueCreate(CMD_AUDIO_QUEUE_MAX, sizeof(audio_cmd_t));

    /* Node runner. */
    node_runner_init(&runner, &hal, mem_limit);

    /* Button tracker (default teams until game starts with preset's teams). */
    button_tracker_init(&btn_tracker, default_teams, 2);

    /* The radio task (core 0, priority 3), only if the radio HAL init succeeded,
     * then the field game: its storage, its key, and a stored game to rejoin. */
    if (hal.radio != NULL) {
        radio_task_start(&hal);
    }
    box_start(tier);

    /* Memory monitor. */
    mem_monitor_start();

    /* Check if initial setup is needed. */
    bool configured = config_store_is_configured();
#if CONFIG_ATALAIA_SKIP_SETUP
    if (!configured) ESP_LOGW(TAG, "setup skipped (CONFIG_ATALAIA_SKIP_SETUP): default settings");
    configured = true;
#endif
    if (!configured) {
        ESP_LOGI(TAG, "Not configured -- starting Wi-Fi setup portal");
        wifi_setup_start();
        char data[64];
        snprintf(data, sizeof(data), "{\"ssid\":\"%s\"}", wifi_setup_ssid());
        send_screen("wifi_setup", data);
    } else {
        ESP_LOGI(TAG, "Configured -- starting normal mode");

        /* A field game stored before a reboot comes first (ADR-P2-12): rejoin it. */
        state_persist_data_t saved;
        bool resumed = box_game_resume(&box, (uint32_t)(esp_timer_get_time() / 1000));
        if (resumed) ESP_LOGI(TAG, "rejoined field game %u", box.join.game_id);

        /* Otherwise resume a stand-alone game (reboot recovery). */
        if (!resumed && state_persist_load(&saved) &&
            preset_store_load(saved.preset_index, &game_preset)) {
            uint8_t tc = saved.team_count;
            if (tc < 2) tc = 2;
            if (tc > 4) tc = 4;
            if (node_runner_resume(&runner, &saved, game_preset.source, game_preset.source_len,
                                   game_preset.params_json, default_teams, tc)) {
                button_tracker_init(&btn_tracker, default_teams, tc);
                runner.preset_index = saved.preset_index;
                resumed = true;
                ESP_LOGI(TAG, "Resumed game from saved state (preset %d, game_time %lu ms)",
                         saved.preset_index, (unsigned long)saved.game_time_ms);
            }
        }

        if (!resumed) {
            /* No valid saved state -- start the normal preset picker. */
            start_picker();
        }
    }

    /* FreeRTOS tasks per ADR-P1-7. */
    /* 12 KB: Lua, the join codec and the field link all run on the game task. */
    xTaskCreatePinnedToCore(task_game, "game", 12288, NULL, 5, NULL, 1);
    xTaskCreatePinnedToCore(task_lvgl, "lvgl", 8192, NULL, 4, NULL, 1);
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
