/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Host box: a Field Box's game logic on Linux, for end-to-end tests with
 * the field controller and the host modem (controller/tests/test_box_e2e.py).
 *
 * It runs the firmware's own box_game.c, radio/field_link.c,
 * radio_protocol.c, node_runner.c, preset_store.c, state_persist.c and
 * event_log.c with the real core and mbedtls AES-CCM. What differs from
 * the ESP32 shell is only the platform:
 *   - the radio is UDP on 127.0.0.1 ("air"): every datagram received is a
 *     packet heard, every packet sent goes to the air peer port;
 *   - NVS (epoch, game key, join, join key) and LittleFS (presets, saved
 *     state, event log) are files in --state-dir, so killing the process
 *     and starting it again with the same directory is a battery pull;
 *   - the team buttons and the serial console are lines on stdin.
 *
 *   box_host --state-dir DIR --modes DIR [--air-port N] [--air-peer N]
 *            [--join-key HEX] [--state-ms N] [--name NAME]
 *
 * stdin, one command per line:
 *   @join atalaia:join:...      join (as typed on the serial console)
 *   @joinkey <64 hex>           set the field join key
 *   hold <button 1-4> <ms>      hold a team button for ms, then release it
 *   keys <0-9*#...>             keypad presses (keypad.key events to the mode)
 *   status                      print one STATUS line (JSON)
 *   quit
 * stdout: "READY air=<port>", then LOG, SCREEN and STATUS lines.
 */
#define _POSIX_C_SOURCE 200809L

#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#include <poll.h>
#include <signal.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#include "atalaia/version.h"
#include "box_game.h"
#include "builtin_presets.h"
#include "button_tracker.h"
#include "hal/stub/hal_stub.h"
#include "serial_console.h"
#include "state_persist.h"

static int air_sock = -1;
static struct sockaddr_in air_peer;
static bool have_peer;
static char dir[256];

static uint32_t mono_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint32_t)((uint64_t)ts.tv_sec * 1000u + (uint64_t)ts.tv_nsec / 1000000u);
}

static void out(const char *fmt, ...) __attribute__((format(printf, 1, 2)));

static void out(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    vprintf(fmt, ap);
    va_end(ap);
    putchar('\n');
    fflush(stdout);
}

/* ---- Files for NVS --------------------------------------------------------------- */

static void path_of(char *buf, size_t cap, const char *name)
{
    snprintf(buf, cap, "%s/%s", dir, name);
}

static int read_file(const char *name, uint8_t *buf, size_t cap)
{
    char p[300];
    path_of(p, sizeof(p), name);
    FILE *f = fopen(p, "rb");
    if (f == NULL) return 0;
    size_t n = fread(buf, 1, cap, f);
    fclose(f);
    return (int)n;
}

static int write_file(const char *name, const uint8_t *buf, size_t len)
{
    char p[300], tmp[310];
    path_of(p, sizeof(p), name);
    snprintf(tmp, sizeof(tmp), "%s.tmp", p);
    FILE *f = fopen(tmp, "wb");
    if (f == NULL) return -1;
    bool ok = fwrite(buf, 1, len, f) == len;
    ok = fflush(f) == 0 && ok;
    fclose(f);
    if (!ok || rename(tmp, p) != 0) return -1;
    return 0;
}

static int erase_file(const char *name)
{
    char p[300];
    path_of(p, sizeof(p), name);
    remove(p);
    return 0;
}

static int nvs_read_epoch(void *ctx, uint16_t *epoch)
{
    (void)ctx;
    uint8_t b[2];
    if (read_file("epoch", b, 2) != 2) return -1;
    *epoch = (uint16_t)(b[0] << 8 | b[1]);
    return 0;
}

static int nvs_write_epoch(void *ctx, uint16_t epoch)
{
    (void)ctx;
    uint8_t b[2] = {(uint8_t)(epoch >> 8), (uint8_t)epoch};
    return write_file("epoch", b, 2);
}

static int nvs_read_key(void *ctx, uint8_t key[16])
{
    (void)ctx;
    return read_file("game_key", key, 16) == 16 ? 0 : -1;
}

static int nvs_write_key(void *ctx, const uint8_t key[16])
{
    (void)ctx;
    return write_file("game_key", key, 16);
}

static int nvs_erase_key(void *ctx)
{
    (void)ctx;
    return erase_file("game_key");
}

static const atalaia_radio_nvs_ops_t nvs_ops = {
    .read_epoch = nvs_read_epoch,
    .write_epoch = nvs_write_epoch,
    .read_key = nvs_read_key,
    .write_key = nvs_write_key,
    .erase_key = nvs_erase_key,
    .ctx = NULL,
};

static int store_load_join(void *ctx, uint8_t *buf, size_t cap)
{
    (void)ctx;
    return read_file("join", buf, cap);
}

static int store_save_join(void *ctx, const uint8_t *buf, size_t len)
{
    (void)ctx;
    return write_file("join", buf, len);
}

static int store_erase_join(void *ctx)
{
    (void)ctx;
    return erase_file("join");
}

static int store_load_join_key(void *ctx, uint8_t key[ATALAIA_JOIN_KEY_SIZE])
{
    (void)ctx;
    return read_file("join_key", key, ATALAIA_JOIN_KEY_SIZE) == ATALAIA_JOIN_KEY_SIZE ? 0 : -1;
}

static int store_save_join_key(void *ctx, const uint8_t key[ATALAIA_JOIN_KEY_SIZE])
{
    (void)ctx;
    return write_file("join_key", key, ATALAIA_JOIN_KEY_SIZE);
}

/* ---- Radio and shell ------------------------------------------------------------- */

static bool air_send(void *user, const uint8_t *pkt, size_t len)
{
    (void)user;
    if (!have_peer) return false;
    return sendto(air_sock, pkt, len, 0, (const struct sockaddr *)&air_peer, sizeof(air_peer)) ==
           (ssize_t)len;
}

static void shell_screen(void *user, const char *tmpl, const char *json)
{
    (void)user;
    out("SCREEN %s %s", tmpl, json);
}

static void shell_log(void *user, const char *line)
{
    (void)user;
    out("LOG %s", line);
}

static bool shell_set_channel(void *user, uint32_t hz)
{
    (void)user;
    out("LOG channel %lu Hz", (unsigned long)hz);
    return true;
}

static int shell_battery(void *user)
{
    (void)user;
    return 87;
}

/* ---- Files for the mode sources -------------------------------------------------- */

static char *slurp(const char *path, size_t *len)
{
    FILE *f = fopen(path, "rb");
    if (f == NULL) return NULL;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *buf = malloc((size_t)n + 1);
    if (buf == NULL || fread(buf, 1, (size_t)n, f) != (size_t)n) {
        fclose(f);
        free(buf);
        return NULL;
    }
    fclose(f);
    buf[n] = '\0';
    *len = (size_t)n;
    return buf;
}

static long arg_value(int argc, char **argv, int *i)
{
    if (*i + 1 >= argc) {
        fprintf(stderr, "box_host: %s needs a value\n", argv[*i]);
        exit(2);
    }
    (*i)++;
    return strtol(argv[*i], NULL, 10);
}

static int bind_udp(uint16_t port)
{
    int fd = socket(AF_INET, SOCK_DGRAM, 0);
    if (fd < 0) return -1;
    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    addr.sin_port = htons(port);
    if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
        close(fd);
        return -1;
    }
    return fd;
}

/* preset_t holds 16 KB of source: static, like on the ESP32. */
static preset_t preset;
static node_runner_t runner;
static box_game_t game;
static hal_t hal;
static event_log_t evlog;

static void print_status(void)
{
    char scores[96] = "";
    size_t o = 0;
    if (runner.node != NULL) {
        const atalaia_score_t *s = atalaia_node_score(runner.node);
        for (uint8_t t = 1; t <= game.join.team_count && o < sizeof(scores) - 16; t++) {
            o += (size_t)snprintf(scores + o, sizeof(scores) - o, "%s%lu", t > 1 ? "," : "",
                                  (unsigned long)s->gained[t]);
        }
    }
    const field_link_stats_t *st = &game.link.stats;
    out("STATUS {\"phase\":%d,\"paused\":%s,\"game_id\":%u,\"node_id\":%u,\"epoch\":%u,"
        "\"game_time_ms\":%lu,\"owner\":%u,\"scores\":[%s],\"pending\":%u,\"leader\":%u,"
        "\"term\":%lu,\"events_sent\":%lu,\"retries\":%lu,\"acked\":%lu,\"cmds\":%lu,"
        "\"times\":%lu,\"states\":%lu,\"rx_ok\":%lu,\"rx_rejected\":%lu,\"relayed\":%lu,"
        "\"have_key\":%s}",
        (int)game.phase, game.paused ? "true" : "false", game.join.game_id, game.join.node_id,
        game.link.proto.epoch, (unsigned long)runner.game_time_ms, game.owner_team, scores,
        (unsigned)field_link_pending(&game.link), game.link.leader, (unsigned long)game.link.term,
        (unsigned long)st->events_sent, (unsigned long)st->retries, (unsigned long)st->acked,
        (unsigned long)st->cmds, (unsigned long)st->times, (unsigned long)st->states_sent,
        (unsigned long)st->rx_ok, (unsigned long)st->rx_rejected, (unsigned long)st->relayed,
        game.link.proto.has_key ? "true" : "false");
}

int main(int argc, char **argv)
{
    long air_port = 0, peer_port = 0, state_ms = 0;
    const char *modes = NULL;
    const char *join_key_hex = NULL;
    const char *name = "box-host";
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--air-port") == 0) {
            air_port = arg_value(argc, argv, &i);
        } else if (strcmp(argv[i], "--air-peer") == 0) {
            peer_port = arg_value(argc, argv, &i);
        } else if (strcmp(argv[i], "--state-ms") == 0) {
            state_ms = arg_value(argc, argv, &i);
        } else if (strcmp(argv[i], "--state-dir") == 0 && i + 1 < argc) {
            snprintf(dir, sizeof(dir), "%s", argv[++i]);
        } else if (strcmp(argv[i], "--modes") == 0 && i + 1 < argc) {
            modes = argv[++i];
        } else if (strcmp(argv[i], "--join-key") == 0 && i + 1 < argc) {
            join_key_hex = argv[++i];
        } else if (strcmp(argv[i], "--name") == 0 && i + 1 < argc) {
            name = argv[++i];
        } else {
            fprintf(stderr, "box_host: unknown option %s\n", argv[i]);
            return 2;
        }
    }
    if (!dir[0] || modes == NULL) {
        fprintf(stderr, "box_host: --state-dir and --modes are required\n");
        return 2;
    }
    signal(SIGPIPE, SIG_IGN);
    mkdir(dir, 0700);

    air_sock = bind_udp((uint16_t)air_port);
    if (air_sock < 0) {
        perror("box_host: bind");
        return 1;
    }
    if (peer_port > 0) {
        memset(&air_peer, 0, sizeof(air_peer));
        air_peer.sin_family = AF_INET;
        air_peer.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        air_peer.sin_port = htons((uint16_t)peer_port);
        have_peer = true;
    }

    /* "Flash": presets, saved state and the event log, as on the box's LittleFS. */
    char sub[300];
    snprintf(sub, sizeof(sub), "%s/presets", dir);
    mkdir(sub, 0700);
    preset_store_init(sub);
    snprintf(sub, sizeof(sub), "%s/state", dir);
    mkdir(sub, 0700);
    state_persist_init(sub);
    snprintf(sub, sizeof(sub), "%s/log", dir);
    mkdir(sub, 0700);
    event_log_init(&evlog, sub);

    /* The built-in modes, as main/CMakeLists.txt puts them in the image. */
    static const char *const builtin_modes[][2] = {
        {"bomb", "org.atalaia.bomb"},       {"domination", "org.atalaia.domination"},
        {"holdall", "org.atalaia.holdall"}, {"laststand", "org.atalaia.laststand"},
        {"codes", "org.atalaia.codes"},
    };
    enum { BUILTIN_COUNT = sizeof(builtin_modes) / sizeof(builtin_modes[0]) };
    builtin_source_t sources[BUILTIN_COUNT];
    for (int i = 0; i < BUILTIN_COUNT; i++) {
        char p[300];
        snprintf(p, sizeof(p), "%s/%s/node.lua", modes, builtin_modes[i][0]);
        sources[i].mode_id = builtin_modes[i][1];
        sources[i].source = slurp(p, &sources[i].source_len);
        if (sources[i].source == NULL) {
            fprintf(stderr, "box_host: cannot read %s\n", p);
            return 1;
        }
    }
    builtin_presets_seed(sources, BUILTIN_COUNT);

    hal_stub_init(&hal);
    node_runner_init(&runner, &hal, 0);

    atalaia_hello_t hello;
    memset(&hello, 0, sizeof(hello));
    snprintf(hello.node_name, sizeof(hello.node_name), "%s", name);
    hello.platform = 2; /* linux */
    snprintf(hello.fw_version, sizeof(hello.fw_version), "host");
    snprintf(hello.core_version, sizeof(hello.core_version), "%s", atalaia_version());
    hello.tier = 0;
    hello.capabilities_count = 0;
    hello.transports = 1;
    hello.battery_pct = 87;

    box_store_ops_t store = {store_load_join,     store_save_join,     store_erase_join,
                             store_load_join_key, store_save_join_key, NULL};
    box_shell_ops_t shell = {.screen = shell_screen,
                             .log = shell_log,
                             .reboot = NULL,
                             .set_channel = shell_set_channel,
                             .battery_pct = shell_battery,
                             .radio_send = air_send,
                             .user = NULL};
    box_game_init(&game, &runner, &preset, &store, &shell, &atalaia_crypto_mbedtls, &nvs_ops,
                  &evlog, &hello);
    if (join_key_hex != NULL && !box_game_set_join_key_hex(&game, join_key_hex)) {
        fprintf(stderr, "box_host: --join-key needs 64 hex digits\n");
        return 2;
    }
    box_game_load_join_key(&game);
    game.state_interval_ms = (uint32_t)state_ms;

    uint32_t last = mono_ms();
    if (box_game_resume(&game, last)) {
        out("LOG rejoined the stored game");
    }
    button_tracker_t buttons;
    button_tracker_init(&buttons, game.teams, game.join.team_count);
    uint8_t pressed = 0;
    uint32_t release_at[4] = {0};

    struct sockaddr_in addr;
    socklen_t alen = sizeof(addr);
    getsockname(air_sock, (struct sockaddr *)&addr, &alen);
    out("READY air=%u", ntohs(addr.sin_port));

    serial_console_t console;
    serial_console_init(&console);
    char line[1024];
    size_t line_len = 0;

    for (;;) {
        struct pollfd fds[2] = {{air_sock, POLLIN, 0}, {STDIN_FILENO, POLLIN, 0}};
        if (poll(fds, 2, 10) < 0 && errno != EINTR) {
            perror("box_host: poll");
            return 1;
        }
        uint32_t now = mono_ms();
        uint32_t delta = now - last;
        last = now;

        if (fds[0].revents & POLLIN) {
            uint8_t pkt[RADIO_MAX_PKT_LEN + 1];
            ssize_t got = recv(air_sock, pkt, sizeof(pkt), 0);
            if (got > 0 && got <= RADIO_MAX_PKT_LEN)
                box_game_on_packet(&game, pkt, (size_t)got, -48);
        }
        if (fds[1].revents & (POLLIN | POLLHUP)) {
            char buf[512];
            ssize_t got = read(STDIN_FILENO, buf, sizeof(buf));
            if (got <= 0) return 0; /* stdin closed: the test is done */
            for (ssize_t i = 0; i < got; i++) {
                /* '@' lines go through the console parser, exactly as on the box. */
                char key;
                const char *command = NULL;
                serial_input_t in = serial_console_feed(&console, buf[i], &key, &command);
                if (in == SERIAL_COMMAND) {
                    if (strncmp(command, "join ", 5) == 0) {
                        box_join_result_t r = box_game_join_text(&game, command + 5);
                        out("LOG join: %s", box_join_result_name(r));
                        button_tracker_init(&buttons, game.teams, game.join.team_count);
                    } else if (strncmp(command, "joinkey ", 8) == 0) {
                        out("LOG join key %s", box_game_set_join_key_hex(&game, command + 8)
                                                   ? "stored"
                                                   : "refused (64 hex digits)");
                    }
                    line_len = 0;
                    continue;
                }
                if (console.in_command || buf[i] == '@') continue;
                if (buf[i] == '\n') {
                    line[line_len] = '\0';
                    line_len = 0;
                    int b = 0;
                    unsigned ms = 0;
                    if (sscanf(line, "hold %d %u", &b, &ms) == 2 && b >= 1 && b <= 4) {
                        pressed |= (uint8_t)(1u << (b - 1));
                        release_at[b - 1] = now + ms;
                    } else if (strncmp(line, "keys ", 5) == 0) {
                        /* Keypad presses, as the shell sends them to a running mode. */
                        for (const char *k = line + 5; *k && runner.running; k++) {
                            char json[16];
                            snprintf(json, sizeof(json), "{\"key\":\"%c\"}", *k);
                            node_runner_input(&runner, "keypad.key", json);
                        }
                    } else if (strcmp(line, "status") == 0) {
                        print_status();
                    } else if (strcmp(line, "quit") == 0) {
                        return 0;
                    }
                } else if (line_len + 1 < sizeof(line)) {
                    line[line_len++] = buf[i];
                }
            }
        }

        for (int b = 0; b < 4; b++) {
            if ((pressed & (1u << b)) && (int32_t)(now - release_at[b]) >= 0) {
                pressed &= (uint8_t) ~(1u << b);
            }
        }
        if (game.phase == BOX_PLAYING && !game.paused && runner.running) {
            button_tracker_update(&buttons, pressed, delta, &runner);
        }
        box_game_tick(&game, delta, now);
        runner.queues.screen_count = 0;
        runner.queues.audio_count = 0;
    }
}
