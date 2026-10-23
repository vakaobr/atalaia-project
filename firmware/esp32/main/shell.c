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
 * Between games the controller can update its firmware over the field Wi-Fi
 * (fw_update.c, fw_update_esp.c, protocol/firmware-update.md), and invite
 * the box into its next game over the radio (box_lobby.c,
 * protocol/field-frames.md).
 */

#include <stdio.h>
#include <string.h>

#include "admin_pin.h"
#include "adoption.h"
#include "atalaia/join.h"
#include "box_pair.h"
#include "box_text.h"
#include "atalaia/packet.h"
#include "atalaia/version.h"
#include "box_game.h"
#include "builtin_presets.h"
#include "button_tracker.h"
#include "config_store.h"
#include "fw_update_esp.h"
#include "mode_fetch_esp.h"
#include "mode_store.h"
#include "game_timer.h"
#include "hal/hal.h"
#include "key_filter.h"
#include "mem_monitor.h"
#include "node_runner.h"
#include "preset_store.h"
#include "preset_ui.h"
#include "screen_renderer.h"
#include "screen_template.h"
#include "state_persist.h"
#include "radio/event_log.h"
#include "radio/radio_task.h"
#include "serial_console.h"
#include "wifi_setup.h"

#ifdef ESP_PLATFORM
/* ---- ESP-IDF build ---------------------------------------------------- */
#include "display_port.h"
#include "oled_view.h"
#include "esp_app_desc.h"
#include "esp_event.h"
#include "esp_littlefs.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_psram.h"
#include "bootloader_random.h"
#include "esp_random.h"
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
#define SERIAL_WANTED                                                                              \
    (CONFIG_ATALAIA_SERIAL_KEYS || CONFIG_ATALAIA_SERIAL_JOIN || CONFIG_ATALAIA_SERIAL_ADOPT)
/* A team button on UART0's RX pin (GPIO 44 on the ESP32-S3) takes that pin
 * from the console: no console input on UART0 then (decision PIN-5). */
#define U0RXD_PIN 44
#if CONFIG_ATALAIA_BTN1_PIN == U0RXD_PIN || CONFIG_ATALAIA_BTN2_PIN == U0RXD_PIN
#define BUTTON_ON_U0RXD 1
#elif CONFIG_ATALAIA_BTN3_PIN == U0RXD_PIN || CONFIG_ATALAIA_BTN4_PIN == U0RXD_PIN
#define BUTTON_ON_U0RXD 1
#else
#define BUTTON_ON_U0RXD 0
#endif
#define UART_RX_FREE (CONFIG_ESP_CONSOLE_UART_NUM != 0 || !BUTTON_ON_U0RXD)
#define SERIAL_UART  (SERIAL_WANTED && CONFIG_ESP_CONSOLE_UART && UART_RX_FREE)
#define SERIAL_USB   (SERIAL_WANTED && CONFIG_ATALAIA_CONSOLE_USB_INPUT)
#define SERIAL_INPUT (SERIAL_UART || SERIAL_USB)
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

/* preset_t holds a 16 KB source buffer: static, not on a task stack. */
static preset_t game_preset;

static QueueHandle_t screen_queue;
static QueueHandle_t audio_queue;

/* Default teams until the config store provides configurable team names. */
static const char *const default_teams[] = {"red", "blue", "green", "yellow"};

/* A field controller's game (box_game.h) and its flash event log. */
static box_game_t box;
static event_log_t game_log;
static bool box_teams_set;   /* the button tracker uses the joined game's teams */
static bool box_was_active;  /* to notice the end of a field game */
static bool after_game;      /* a game ended: the next key brings the picker back */
static uint8_t nfc_mem[888]; /* NTAG216 user memory */
static uint8_t nfc_last_uid[10];
static uint8_t nfc_last_uid_len;
static uint32_t nfc_last_poll_ms;
/* The admin PIN (admin_pin.h): one check for the picker and adoption, its failure count in NVS. */
static admin_pin_t admin_guard;
/* Adoption (adoption.h): the field card, "@adopt" over the USB cable, "@joinkey". */
static adoption_t adopt;
static char adopt_mac[18];
static char adopt_name[25] = "field-box";
static adoption_identity_t adopt_id = {adopt_name, adopt_mac, ""};
/* Pairing by code over the radio (box_pair.c): an unadopted box shows a code at boot. */
static box_pair_t pairing;
static bool pair_at_boot;
static uint32_t now_ms(void);
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
extern const char holdall_node_lua_start[] asm("_binary_holdall_node_lua_start");
extern const char laststand_node_lua_start[] asm("_binary_laststand_node_lua_start");
extern const char codes_node_lua_start[] asm("_binary_codes_node_lua_start");
extern const char kill_confirmed_node_lua_start[] asm("_binary_kill_confirmed_node_lua_start");
extern const char respawn_node_lua_start[] asm("_binary_respawn_node_lua_start");
extern const char player_checkin_node_lua_start[] asm("_binary_player_checkin_node_lua_start");
extern const char medic_node_lua_start[] asm("_binary_medic_node_lua_start");
extern const char
    master_satellites_node_lua_start[] asm("_binary_master_satellites_node_lua_start");
extern const char hacking_terminal_node_lua_start[] asm("_binary_hacking_terminal_node_lua_start");
extern const char vip_payload_node_lua_start[] asm("_binary_vip_payload_node_lua_start");
extern const char objectives_node_lua_start[] asm("_binary_objectives_node_lua_start");
extern const char money_factory_node_lua_start[] asm("_binary_money_factory_node_lua_start");

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
    preset_ui_init(&preset_ui, NULL, preset_count);
    preset_ui_set_guard(&preset_ui, &admin_guard);
    /* A wait still running, or no PIN set: said at once (decisions AD-28, AD-29). */
    preset_ui.locked_min = admin_pin_wait_min(&admin_guard);
    preset_ui.no_pin = !admin_pin_is_set(&admin_guard);
    memset(&picker_screen, 0, sizeof(picker_screen));
    picker_active = true;
    show_picker();
}

#if SERIAL_INPUT
static void serial_input_init(void)
{
#if SERIAL_WANTED && CONFIG_ESP_CONSOLE_UART && !SERIAL_UART
    ESP_LOGI(TAG, "no console input on UART0: GPIO %d is a team button", U0RXD_PIN);
#endif
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
#if CONFIG_ATALAIA_SERIAL_ADOPT
    ESP_LOGI(TAG, "USB adoption on: \"@adopt-info\", \"@adopt <hex> [<PIN>|-] [<name>]\"");
#endif
#if CONFIG_ATALAIA_SERIAL_JOIN
    ESP_LOGI(TAG, "serial join on: \"@join atalaia:join:...\", \"@joinkey <hex>\", "
                  "\"@tag <uid> [<tag>]\", \"@wifi <ssid> <password>\", "
                  "\"@update <version> <release id>\", \"@modes\", \"@forgetmodes\" "
                  "or \"@lobby\" on the console");
#endif
}

#if CONFIG_ATALAIA_SERIAL_ADOPT
#define SERIAL_ADOPT_ON 1
#else
#define SERIAL_ADOPT_ON 0
#endif
#if CONFIG_ATALAIA_SERIAL_JOIN
#define SERIAL_JOIN_ON 1
#else
#define SERIAL_JOIN_ON 0
#endif

static void serial_command(const char *cmd)
{
    if (SERIAL_ADOPT_ON || SERIAL_JOIN_ON) {
        /* "@admin-pin <new>" while none is set, "@admin-pin <PIN> <new>" (decision AD-30). */
        static char pin_reply[160];
        if (admin_pin_command(&admin_guard, cmd, pin_reply, sizeof(pin_reply))) {
            ESP_LOGI(TAG, "%s", pin_reply);
            return;
        }
    }
    bool adopt_cmd =
        SERIAL_ADOPT_ON && (strcmp(cmd, "adopt-info") == 0 || strncmp(cmd, "adopt ", 6) == 0);
    bool joinkey_cmd = SERIAL_JOIN_ON && strncmp(cmd, "joinkey ", 8) == 0;
    if (adopt_cmd || joinkey_cmd) {
        /* The controller reads the "ATALAIA-ADOPT {json}" line (protocol/adoption.md). */
        static char reply[ADOPTION_REPLY_MAX];
        if (adoption_command(&adopt, cmd, &adopt_id, now_ms(), reply, sizeof(reply))) {
            if (adopt_cmd) {
                printf("%s\n", reply);
                fflush(stdout);
            } else {
                ESP_LOGI(TAG, "%s", reply);
            }
        }
        return;
    }
#if CONFIG_ATALAIA_SERIAL_JOIN
    if (strncmp(cmd, "join ", 5) == 0) {
        box_join_result_t r = box_game_join_text(&box, cmd + 5);
        ESP_LOGI(TAG, "join: %s", box_join_result_name(r));
        if (r == BOX_JOIN_OK) picker_active = false;
        return;
    }
    if (strncmp(cmd, "tag ", 4) == 0) {
        /* A player tag without a reader (bring-up, Wokwi): "@tag <uid hex> [<payload hex>]". */
        if (!box_game_tag_text(&box, cmd + 4)) {
            ESP_LOGW(TAG, "tag: refused (no game running, or not \"<uid hex> [<payload hex>]\")");
        }
        return;
    }
    if (strncmp(cmd, "wifi ", 5) == 0) {
        /* "@wifi <ssid> <password>": the field Wi-Fi firmware updates use (no spaces in the
         * SSID here; the setup portal takes any). An open network: "@wifi <ssid>". */
        char ssid[33] = "", pass[65] = "";
        const char *sp = strchr(cmd + 5, ' ');
        size_t n = sp ? (size_t)(sp - (cmd + 5)) : strlen(cmd + 5);
        if (n >= 1 && n < sizeof(ssid)) {
            memcpy(ssid, cmd + 5, n);
            snprintf(pass, sizeof(pass), "%s", sp ? sp + 1 : "");
        }
        ESP_LOGI(TAG, "field Wi-Fi: %s",
                 fw_update_esp_set_wifi(ssid, pass)
                     ? "stored"
                     : "refused (SSID 1-32 bytes, password 8-64 or none)");
        return;
    }
    if (strncmp(cmd, "update ", 7) == 0) {
        /* "@update <version> <release id>": as the controller's CMD update (the same checks). */
        char version[40] = "", id[24] = "", params[96];
        if (sscanf(cmd + 7, "%39s %23s", version, id) == 2) {
            snprintf(params, sizeof(params), "{\"id\":\"%s\",\"version\":\"%s\"}", id, version);
            if (box_game_playing(&box)) {
                ESP_LOGW(TAG, "update refused: a game is being played");
            } else {
                fw_update_esp_offer(params);
            }
        } else {
            ESP_LOGW(TAG, "update: \"@update <version> <release id>\"");
        }
        return;
    }
    if (strcmp(cmd, "modes") == 0) {
        /* The mode packages this box fetched (mode_store.h). */
        ms_fetched_t m[MS_FETCHED_MAX];
        int n = mode_store_list(m, MS_FETCHED_MAX);
        ESP_LOGI(TAG, "%d fetched mode package(s); %u mode key(s)", n,
                 (unsigned)mode_fetch_esp_key_count());
        for (int i = 0; i < n; i++) {
            ESP_LOGI(TAG, "  %s %s key %s, %lu bytes", m[i].id, m[i].version, m[i].key_id,
                     (unsigned long)m[i].bytes);
        }
        return;
    }
    if (strcmp(cmd, "forgetmodes") == 0) {
        if (box_game_active(&box)) {
            ESP_LOGW(TAG, "forgetmodes: not in a game");
        } else {
            ESP_LOGI(TAG, "forgot %d fetched mode(s)", mode_store_forget_all());
            load_preset_list();
        }
        return;
    }
    if (strcmp(cmd, "pair") == 0) {
        /* A new pairing code (protocol/adoption.md): only on an unadopted box, with a radio. */
        if (hal.radio == NULL) {
            ESP_LOGW(TAG, "pair: no radio");
        } else if (!box_pair_start(&pairing, now_ms())) {
            ESP_LOGW(TAG, "pair: %s",
                     adopt.adopted ? "this box is adopted (another field: the card or the cable, "
                                     "with the admin PIN)"
                                   : "locked after too many failed runs; restart the box");
        }
        return;
    }
    if (strcmp(cmd, "lobby") == 0) {
        /* Between games (protocol/field-frames.md): what the controller sees of this box. */
        char hex[17];
        box_lobby_device_hex(&box, hex);
        ESP_LOGI(TAG,
                 "lobby: device %s, %s, channel %lu Hz, last game %u (%s), invites %lu "
                 "accepted, %lu refused, %lu frames ignored",
                 hex[0] ? hex : "none (no join key)",
                 box_lobby_available(&box) ? "free for an invite" : "in a game",
                 (unsigned long)box.lobby.channel_hz, box.lobby.last_game,
                 box.lobby.last_role[0] ? box.lobby.last_role : "-",
                 (unsigned long)box.lobby.invites_accepted,
                 (unsigned long)box.lobby.invites_refused, (unsigned long)box.lobby.frames_ignored);
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

/* The ESP32-S3's hardware RNG (device id, tokens, field frame nonces). */
/*
 * Random bytes for the device id, the tokens and timing spread (never a field frame's nonce,
 * which is counter-based: box_lobby.c, decision RJ-15). ESP-IDF calls the S3's RNG truly
 * random only while Wi-Fi or Bluetooth runs, or between bootloader_random_enable() and
 * _disable(), which a Field Box between games often is not. So app_main collects 32 bytes of
 * true entropy at boot with the SAR ADC's noise on (before any ADC or I2S driver starts), and
 * every request is SHA-256 of that seed, the board's MAC (two boards never share a stream), a
 * counter and fresh esp_fill_random bytes: as good as the boot entropy even when the RNG is not.
 */
static uint8_t boot_seed[32];
static uint32_t random_ctr;

static void collect_boot_entropy(void)
{
    uint8_t pool[32 + 6] = {0};
    bootloader_random_enable();
    esp_fill_random(pool, 32);
    bootloader_random_disable();
    esp_efuse_mac_get_default(pool + 32);
    atalaia_sha256(pool, sizeof(pool), boot_seed);
    memset(pool, 0, sizeof(pool));
}

static void box_random(void *user, uint8_t *buf, size_t len)
{
    (void)user;
    while (len > 0) {
        uint8_t in[32 + 4 + 16];
        memcpy(in, boot_seed, 32);
        random_ctr++;
        memcpy(in + 32, &random_ctr, 4);
        esp_fill_random(in + 36, 16);
        uint8_t out[32];
        atalaia_sha256(in, sizeof(in), out);
        size_t take = len < sizeof(out) ? len : sizeof(out);
        memcpy(buf, out, take);
        buf += take;
        len -= take;
        memset(in, 0, sizeof(in));
        memset(out, 0, sizeof(out));
    }
}

/* CMD update (protocol/firmware-update.md): box_game never passes one during a game. */
static void box_update(void *user, const char *params_json)
{
    (void)user;
    fw_update_esp_offer(params_json);
}

/* A join whose mode packages the box lacks (mode_fetch.h): fetched on their own task. */
static void box_fetch_modes(void *user, const atalaia_join_t *join)
{
    (void)user;
    mode_fetch_esp_start(join);
}

static void update_screen(const char *tmpl, const char *data_json)
{
    send_screen(tmpl, data_json);
}

static int update_battery(void)
{
    return box_battery(NULL);
}

/* The setup portal's "field join key" follows the adoption rules too (no PIN: a box
 * adopted to another field keeps that field). */
static bool portal_join_key(const char *hex)
{
    char cmd[80], reply[ADOPTION_REPLY_MAX];
    snprintf(cmd, sizeof(cmd), "joinkey %.70s", hex);
    adoption_command(&adopt, cmd, &adopt_id, now_ms(), reply, sizeof(reply));
    ESP_LOGI(TAG, "setup portal: %s", reply);
    return strcmp(reply, "join key: stored") == 0;
}

/* ---- the admin PIN (admin_pin.h, decisions AD-28 to AD-30) ---- */

#if CONFIG_ATALAIA_SKIP_SETUP
#define ADMIN_PIN_BENCH_BUILD true
#else
#define ADMIN_PIN_BENCH_BUILD false
#endif

static bool pin_load_failures(void *user, uint32_t *failures)
{
    (void)user;
    *failures = config_store_get_u32("pin_fails", 0);
    return true;
}

static bool pin_store_failures(void *user, uint32_t failures)
{
    (void)user;
    config_store_set_u32("pin_fails", failures);
    return config_store_get_u32("pin_fails", failures + 1u) == failures;
}

static bool pin_store(void *user, const char *pin)
{
    (void)user;
    config_store_set_str("admin_pin", pin);
    return true;
}

static uint32_t pin_now(void *user)
{
    (void)user;
    return now_ms();
}

static void admin_guard_init(void)
{
    char stored[ADMIN_PIN_MAX + 2] = "";
    bool have = config_store_get_str("admin_pin", stored, sizeof(stored)) && stored[0] != '\0';
    char pin[ADMIN_PIN_MAX + 1];
    admin_pin_effective(have ? stored : NULL, ADMIN_PIN_BENCH_BUILD, pin);
    if (ADMIN_PIN_BENCH_BUILD && !have) {
        ESP_LOGW(TAG, "admin PIN %s (a bench build, CONFIG_ATALAIA_SKIP_SETUP): never on a field",
                 ADMIN_PIN_BENCH);
    } else if (pin[0] == '\0') {
        ESP_LOGW(TAG,
                 "no admin PIN set%s: the game picker and adoption to another field are "
                 "refused until one is (\"@admin-pin <PIN>\" on the USB console)",
                 have ? " (the stored one is too easy to guess)" : "");
    }
    admin_pin_ops_t ops = {.load_failures = pin_load_failures,
                           .store_failures = pin_store_failures,
                           .store_pin = pin_store,
                           .now_ms = pin_now,
                           .ctx = NULL};
    admin_pin_init(&admin_guard, &ops, pin);
    memset(stored, 0, sizeof(stored));
    memset(pin, 0, sizeof(pin));
    if (admin_pin_wait_ms(&admin_guard) > 0) {
        ESP_LOGW(TAG, "%lu wrong admin PINs in a row: the next try waits %lu min",
                 (unsigned long)admin_guard.failures,
                 (unsigned long)admin_pin_wait_min(&admin_guard));
    }
}

/* ---- adoption's shell ops (adoption.h) ---- */

static bool adopt_busy(void *user)
{
    (void)user;
    return box_game_active(&box) || runner.running; /* a field game joined, or a game played */
}

static bool adopt_store(void *user, const uint8_t key[ADOPTION_KEY_SIZE], const char *name)
{
    (void)user;
    if (!box_game_set_join_key(&box, key)) return false;
    config_store_set_str("field_name", name);
    return true;
}

static void adopt_log(void *user, const char *line)
{
    (void)user;
    ESP_LOGI(TAG, "%s", line);
}

/*
 * NFC, at most every 300 ms while a game runs (player tags, protocol/nfc-tag.md)
 * and every 500 ms otherwise (join cards). A card is read once per tap.
 * During a game a card with a player tag goes to the mode as nfc.tag, as
 * does any card without an Atalaia record (reason "unsigned"); a join card
 * is handled as a join, as before (refused while a joined game is played).
 */
static void poll_nfc(uint32_t now)
{
    bool playing = runner.running;
    if (now - nfc_last_poll_ms < (playing ? 300u : 500u)) return;
    if (!playing && box.phase == BOX_PLAYING) return;
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
    /* A field card (adoption.h) is neither a player tag nor a join; during a game it is
     * only logged, so the field's master secret never reaches a mode. */
    const uint8_t *card = NULL;
    if (n > 0 && adoption_card_from_ndef_tag(nfc_mem, (size_t)n, &card) > 0) {
        adopt_result_t ar;
        if (playing) {
            ESP_LOGW(TAG, "field card: ignored during a game");
        } else {
            adoption_tap(&adopt, nfc_mem, (size_t)n, now, &ar);
        }
        memset(nfc_mem, 0, sizeof(nfc_mem));
        return;
    }
    if (playing) {
        const uint8_t *payload = NULL;
        size_t len = n > 0 ? atalaia_tag_from_ndef_tag(nfc_mem, (size_t)n, &payload) : 0;
        const uint8_t *join = NULL;
        bool join_card = n > 0 && atalaia_join_from_ndef_tag(nfc_mem, (size_t)n, &join) > 0;
        if (len > 0 || !join_card) {
            box_game_tag(&box, tag.uid, tag.uid_len, len > 0 ? payload : NULL, len);
            return;
        }
    }
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
    /* The firmware's own version (PROJECT_VER: the core's, or a release candidate's), which a
     * firmware update compares; the core's is core_version. */
    snprintf(hello.fw_version, sizeof(hello.fw_version), "%s", esp_app_get_description()->version);
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
                           .update = box_update,
                           /* A join may fetch missing modes only with a mode key built in. */
                           .fetch_modes = mode_fetch_esp_key_count() > 0 ? box_fetch_modes : NULL,
                           .random = box_random,
                           .user = NULL};
    box_game_init(&box, &runner, &game_preset, nvs ? atalaia_box_store_esp() : &no_store, &ops,
                  &atalaia_crypto_mbedtls, nvs, &game_log, &hello);
    box.state_interval_ms = (uint32_t)CONFIG_ATALAIA_STATE_INTERVAL_S * 1000u;
    box.has_picker = true; /* "ready" says a key brings the game picker */
    /* battery.low below this level, only with a MAX17048 (box_battery() is -1 without one). */
    box.battery_low_pct = (uint8_t)CONFIG_ATALAIA_BATTERY_LOW_PCT;
    if (!atalaia_nvs_encrypted()) {
        ESP_LOGW(TAG, "NVS encryption is off: the game key and the field join key are stored in "
                      "plain NVS (development only; BRING_UP.md step 0)");
    }
    admin_guard_init();
    adoption_ops_t aops = {.busy = adopt_busy,
                           .store = adopt_store,
                           .screen = box_screen,
                           .log = adopt_log,
                           .ctx = NULL};
    adoption_init(&adopt, &aops, NULL);
    adoption_set_pin(&adopt, &admin_guard);
    uint8_t mac[6];
    if (esp_efuse_mac_get_default(mac) == ESP_OK) {
        /* As the ESP32-S3's USB-Serial-JTAG gives it for its serial number. */
        snprintf(adopt_mac, sizeof(adopt_mac), "%02X:%02X:%02X:%02X:%02X:%02X", mac[0], mac[1],
                 mac[2], mac[3], mac[4], mac[5]);
    }
    snprintf(adopt_name, sizeof(adopt_name), "%s", name);
    adopt_id.fw = esp_app_get_description()->version;
    if (box_game_load_join_key(&box)) {
        char field_name[ADOPTION_NAME_MAX + 1] = "";
        config_store_get_str("field_name", field_name, sizeof(field_name));
        adoption_restore(&adopt, box.join_key, field_name);
        ESP_LOGI(TAG, "adopted to field %s \"%s\"", adopt.fingerprint, adopt.name);
    } else {
        const char *dev = CONFIG_ATALAIA_DEV_JOIN_KEY;
        if (dev[0] != '\0' && box_game_use_join_key_hex(&box, dev)) {
            ESP_LOGW(TAG, "not adopted; using the development field join key "
                          "(CONFIG_ATALAIA_DEV_JOIN_KEY)");
        } else {
            ESP_LOGW(TAG, "not adopted: join cards are refused until the field adopts this box "
                          "(a field card, the USB cable or \"@joinkey\"; protocol/adoption.md)");
        }
    }
    box_pair_ops_t pops = {.radio_send = box_radio_send,
                           .random = box_random,
                           .screen = box_screen,
                           .log = adopt_log,
                           .user = NULL};
    uint32_t listen_hz = (uint32_t)CONFIG_ATALAIA_RADIO_DEFAULT_CHANNEL_HZ;
    box_pair_init(&pairing, &pops, &adopt, &atalaia_crypto_mbedtls, name, hello.tier, listen_hz);
    /* An unadopted box with a radio shows a pairing code once the picker is up (task_game). */
    pair_at_boot = !adopt.adopted && hal.radio != NULL;
    if (pair_at_boot) {
        ESP_LOGI(TAG, "pairing: listening on %lu Hz (the default channel) for a field controller",
                 (unsigned long)listen_hz);
    }
    wifi_setup_set_join_key_handler(portal_join_key);
    fw_update_esp_init(&box, update_screen, update_battery);
    mode_fetch_esp_init(&box, update_screen, hello.tier != 0, mem_limit);
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

    /* Shown until the mode draws its own screen. */
    char data[SCREEN_DATA_MAX];
    const char *label = game_preset.label[0] ? game_preset.label : game_preset.mode_id;
    snprintf(data, sizeof(data), "{\"title\":\"%s\",\"mode\":\"%.40s\",\"timer_s\":%u}",
             box_text(TX_GAME_ON_UP), label, (unsigned)game_preset.duration_s);
    send_screen("status", data);

    /* A new seed for rand() in every game picked on the box, as the controller gives every
     * field game one, so a Hacking Terminal does not set the same puzzle each game (M4-6). */
    runner.game_seed = esp_random();

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

/*
 * A stand-alone game reached game.end (its timer ran out, or the mode ended
 * it): stop the runner and forget the saved state, so a reboot does not
 * resume a finished game, and let the next key bring the picker back, as
 * after a field game. A mode that drew no screen in that last tick (drew_end)
 * gets the final screen, not a frozen phase screen.
 */
static void end_standalone_game(bool drew_end)
{
    node_runner_stop(&runner);
    state_persist_clear();
    if (!drew_end) send_screen("final_score", "{}");
    after_game = true;
    ESP_LOGI(TAG, "game over: press any key for the game picker");
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
            /* A pair frame (type 10, in the clear) is pairing's; everything else the game's. */
            if (box_pair_on_packet(&pairing, rx.data, rx.len, now)) continue;
            box_game_on_packet(&box, rx.data, rx.len, rx.rssi);
        }
        if (pair_at_boot) {
            pair_at_boot = false;
            box_pair_start(&pairing, now); /* over the picker; '*' gives the picker back */
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
        /* An invite over the radio joined a game while the picker or the last game's
         * final screen was showing: the next key is the new game's, not the picker's. */
        if ((picker_active || after_game) && box.phase == BOX_JOINED) {
            picker_active = false;
            after_game = false;
        }
        uint8_t buttons = hal.buttons->poll();
        button_tracker_update(&btn_tracker, buttons, delta_ms, &runner);

        /* ---- Poll keypad: one press per key stroke ---- */
        char key = key_filter_update(&key_filter, hal.keypad->scan());
#if SERIAL_INPUT
        char serial = serial_poll();
        if (key == HAL_KEY_NONE) key = serial;
#endif
        if (key != HAL_KEY_NONE && box_pair_showing(&pairing) && box_pair_key(&pairing, key, now)) {
            key = HAL_KEY_NONE; /* '*' leaves pairing, '#' a new code */
        }
        if (box_pair_tick(&pairing, now) && picker_active && !adoption_active(&adopt)) {
            memset(&picker_screen, 0, sizeof(picker_screen));
            show_picker(); /* the code left the screen: the picker's step again */
        }
        if (box_pair_showing(&pairing)) box_lobby_cancel_ready_screen(&box);
        if (key != HAL_KEY_NONE && adoption_active(&adopt) && adoption_key(&adopt, key, now)) {
            key = HAL_KEY_NONE; /* the admin PIN for another field's card, or closing a result */
        }
        /* An adoption on the screen (its PIN prompt, its result): no "Ready" over it. */
        if (adoption_active(&adopt)) box_lobby_cancel_ready_screen(&box);
        if (adoption_tick(&adopt, now) && picker_active) {
            memset(&picker_screen, 0, sizeof(picker_screen));
            show_picker(); /* adoption left the screen: the picker's step again */
        }
        if (key != HAL_KEY_NONE) {
            if (picker_active) {
                preset_ui_handle_key(&preset_ui, key);
                show_picker();
            } else if (runner.running) {
                char json[64];
                snprintf(json, sizeof(json), "{\"key\":\"%c\"}", key);
                node_runner_input(&runner, "keypad.key", json);
            } else if (after_game) {
                after_game = false;
                box_lobby_cancel_ready_screen(&box); /* the picker, not "ready", from now on */
                start_picker();
            }
        }

        /* ---- NFC: join cards, and player tags while a game runs ---- */
        poll_nfc(now);

        /* ---- Start the game the picker confirmed ---- */
        if (picker_active && preset_ui_get_state(&preset_ui) == PRESET_UI_STATE_GAME_STARTED &&
            !runner.running) {
            start_game();
        }

        /* ---- Tick the game loop (a field game ticks its own runner, time-synced; between
         * games box_game_tick runs only the lobby: announcements, invites) ---- */
        bool field_game = box_game_active(&box);
        fw_update_esp_poll();  /* a failed update the controller has not heard of: over LoRa */
        mode_fetch_esp_poll(); /* a mode fetch that is over: join its game, or say why not */
        box_game_tick(&box, delta_ms, now);
        if (field_game) {
            /* ticked above */
        } else if (runner.running) {
            int screens_before = runner.queues.screen_count;
            node_runner_tick(&runner, delta_ms);
            if (node_runner_status(&runner) == ATALAIA_NODE_ENDED) {
                end_standalone_game(runner.queues.screen_count > screens_before);
            }
        }
        if (box_was_active && !box_game_active(&box)) after_game = true;
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

#ifndef CONFIG_ATALAIA_OLED_SPLASH_MS
#define CONFIG_ATALAIA_OLED_SPLASH_MS 0
#endif

static uint32_t now_ms(void)
{
    return (uint32_t)(esp_timer_get_time() / 1000);
}

/* The running game's time for the OLED's held-time tick: one 32-bit word the game task
 * writes whole (node_runner_tick), read here from the LVGL task. */
static uint32_t game_clock_ms(void)
{
    return *(volatile const uint32_t *)&runner.game_time_ms;
}

/* The team buttons held down now, for the OLED's hold bar on a zone's screens (BN-26): read
 * from the LVGL task while the game task updates them (whole words; a name read as it is
 * replaced shows for one frame at most). */
static int held_buttons(oled_hold_t *holds, int max)
{
    if (!*(volatile const bool *)&runner.running) return 0;
    int n = 0;
    int count = *(volatile const int *)&btn_tracker.team_count;
    for (int i = 0; i < count && i < BUTTON_TRACKER_MAX && n < max; i++) {
        const char *team = *(const char *volatile const *)&btn_tracker.team_names[i];
        if (!*(volatile const bool *)&btn_tracker.pressed[i] || !team) continue;
        snprintf(holds[n].team, sizeof(holds[n].team), "%s", team);
        holds[n].ms = *(volatile const uint32_t *)&btn_tracker.held_ms[i];
        n++;
    }
    return n;
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
    lv_obj_t *oled_scr = display_port_oled_init(hal.oled);
    if (oled_scr) {
        /* The whole version; the splash shows its short form (FV-8). */
        oled_view_splash(oled_scr, esp_app_get_description()->version, now_ms(),
                         CONFIG_ATALAIA_OLED_SPLASH_MS);
        oled_view_set_game_clock(game_clock_ms);
        oled_view_set_hold_reader(held_buttons);
    }

    for (;;) {
        screen_update_t su;
        while (xQueueReceive(screen_queue, &su, 0) == pdTRUE) {
            ESP_LOGI(TAG, "screen %s %s", su.template_name, su.data_json);
            if (!screen_render(su.template_name, su.data_json)) {
                ESP_LOGW(TAG, "unknown screen template '%s'", su.template_name);
            }
            if (oled_scr) oled_view_handle(oled_scr, su.template_name, su.data_json, now_ms());
        }
        if (oled_scr) oled_view_poll(oled_scr, now_ms());
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

static bool mount_storage(void)
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
    return err == ESP_OK;
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
        {"org.atalaia.holdall", holdall_node_lua_start, strlen(holdall_node_lua_start)},
        {"org.atalaia.laststand", laststand_node_lua_start, strlen(laststand_node_lua_start)},
        {"org.atalaia.codes", codes_node_lua_start, strlen(codes_node_lua_start)},
        {"org.atalaia.kill_confirmed", kill_confirmed_node_lua_start,
         strlen(kill_confirmed_node_lua_start)},
        {"org.atalaia.respawn", respawn_node_lua_start, strlen(respawn_node_lua_start)},
        {"org.atalaia.player_checkin", player_checkin_node_lua_start,
         strlen(player_checkin_node_lua_start)},
        {"org.atalaia.medic", medic_node_lua_start, strlen(medic_node_lua_start)},
        {"org.atalaia.master_satellites", master_satellites_node_lua_start,
         strlen(master_satellites_node_lua_start)},
        {"org.atalaia.hacking_terminal", hacking_terminal_node_lua_start,
         strlen(hacking_terminal_node_lua_start)},
        {"org.atalaia.vip_payload", vip_payload_node_lua_start, strlen(vip_payload_node_lua_start)},
        {"org.atalaia.objectives", objectives_node_lua_start, strlen(objectives_node_lua_start)},
        {"org.atalaia.money_factory", money_factory_node_lua_start,
         strlen(money_factory_node_lua_start)},
    };
    int n = builtin_presets_seed(sources, (int)(sizeof(sources) / sizeof(sources[0])));
    if (n > 0) ESP_LOGI(TAG, "stored %d built-in preset(s)", n);
}

void app_main(void)
{
    /* True entropy first, while no ADC or I2S driver runs yet (bootloader_random_enable()
     * takes the SAR ADC; decision RJ-15). */
    collect_boot_entropy();

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

    ESP_LOGI(TAG, "Atalaia firmware v%s (core v%s)  tier=%s", esp_app_get_description()->version,
             atalaia_version(), tier);

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
    bool storage_ok = mount_storage();

    /* An image a firmware update just installed confirms itself here, or rolls back. */
    fw_update_esp_boot(hal.radio != NULL, storage_ok);
    preset_store_init(STORAGE_PATH);
    /* Fetched mode packages (mode_store.h): a commit a power loss cut short is finished or
     * forgotten; their screens come from storage. */
    mode_store_init(STORAGE_PATH);
    screen_template_set_fetched(mode_store_screen);
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
        pair_at_boot = false; /* the portal's screen; "@pair" after the setup */
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
            node_runner_set_mode(&runner, game_preset.mode_id);
            if (node_runner_resume(&runner, &saved, game_preset.source, game_preset.source_len,
                                   game_preset.params_json, default_teams, tc, true)) {
                button_tracker_init(&btn_tracker, default_teams, tc);
                runner.preset_index = saved.preset_index;
                resumed = true;
                ESP_LOGI(TAG, "Resumed game from saved state (preset %d, game_time %lu ms)",
                         saved.preset_index, (unsigned long)saved.game_time_ms);
            }
        }

        if (!resumed && adopt.adopted && box.lobby.ready && !pair_at_boot) {
            /* A free adopted box: "Ready / next game" from boot, as after a game; a key brings
             * the picker (and its admin PIN) as there (decision BN-10). */
            after_game = true;
            box_lobby_show_ready(&box);
        } else if (!resumed) {
            /* Not adopted (pairing over the picker), or no radio: the preset picker. */
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
