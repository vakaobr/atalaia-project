/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Host pod: the I/O pod's own code (main/pod/pod.c, pod_caps.c, pod_ble.c,
 * pod_json.c, and the modem's radio logic with real AES-128-CCM from
 * mbedtls) on Linux, so the phone's side can be tested against it: the app's
 * Dart pod client and radio link (app/test/pod/pod_host_test.dart) and the
 * field controller's end-to-end tests (controller/tests/test_pod_e2e.py).
 *
 *   - the USB link is a TCP socket on 127.0.0.1 carrying the raw bytes, as
 *     the USB-Serial-JTAG port does;
 *   - the Bluetooth link is a second TCP socket where every message is a
 *     2-byte big-endian length and its bytes: a Pod RX write from the phone,
 *     or a Pod TX notification from the pod (cut to --ble-mtu - 3 bytes, as
 *     over the air). Accepting the connection stands for a phone that has
 *     connected, paired (an encrypted link) and turned notifications on;
 *   - the "air" is UDP on 127.0.0.1, as for the host modem: every datagram
 *     received on the air port is a packet heard on the radio, every packet
 *     sent goes to the air peer port (field and pair frames too: the phone's
 *     RADIO_FIELD_TX goes on air as it is, and what is heard comes back as
 *     RADIO_FIELD_RX, so a test can use the pod where it used the modem);
 *   - the hardware is lines on stdin, and what the pod does with its outputs
 *     is lines on stdout.
 *
 *   pod_host [--usb-port N] [--ble-port N] [--ble-mtu N] [--air-port N]
 *            [--air-peer N] [--no-radio] [--buttons N] [--colour N=NAME]...
 *            [--no-keypad] [--no-nfc] [--no-leds] [--no-audio] [--no-case]
 *            [--led-count N]
 *
 * stdin, one command per line:
 *   press <1-4> | release <1-4>    a team button goes down or up
 *   hold <1-4> <ms>                down for ms, then up
 *   key <0-9*#>                    one keypad stroke
 *   tag <uid hex> [<record hex>]   a card on the NFC reader for 0.5 s (with a
 *                                  player-tag record, or none)
 *   join <uid hex>                 a join card on the reader for 0.5 s
 *   case open | case closed        the enclosure switch
 *   battery <0-100>                the battery gauge's reading
 *   status                         one STATUS line (JSON)
 *   quit
 * stdout: "READY usb=<port> ble=<port> air=<port>", then
 *   LED fill <r> <g> <b> | LED set <i> <r> <g> <b> | LED show <lit> | LED brightness <pct>
 *   TONE <hz> <ms> | AUDIO stop | AUDIO volume <pct>
 *   TX <hex>        a packet the pod's radio put on air
 *   LOG <text>      the pod's log
 *   STATUS {...}
 * Port 0 picks a free port. It serves one client per link and runs until
 * stdin closes or "quit".
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
#include <time.h>
#include <unistd.h>

#include "atalaia/join.h"
#include "atalaia/tag.h"
#include "pod/pod.h"
#include "pod/pod_ble.h"
#include "pod/pod_caps.h"
#include "radio/noise_stats.h"
#include "radio/radio_limits.h"

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

static uint32_t mono_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint32_t)((uint64_t)ts.tv_sec * 1000u + (uint64_t)ts.tv_nsec / 1000000u);
}

/* ---- Sockets ------------------------------------------------------------------------- */

static int usb_listen = -1, usb_client = -1;
static int ble_listen = -1, ble_client = -1;
static int air_sock = -1;
static struct sockaddr_in air_peer;
static bool have_peer;
static uint16_t ble_mtu = POD_BLE_MTU_WANTED;
static uint8_t ble_in[2 + 512];
static size_t ble_in_len;

static int send_all(int fd, const uint8_t *buf, size_t len)
{
    size_t done = 0;
    while (done < len) {
        ssize_t n = send(fd, buf + done, len - done, MSG_NOSIGNAL);
        if (n < 0) {
            if (errno == EINTR) continue;
            return -1;
        }
        done += (size_t)n;
    }
    return 0;
}

static int bind_socket(int type, uint16_t port)
{
    int fd = socket(AF_INET, type, 0);
    if (fd < 0) return -1;
    int one = 1;
    setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
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

static uint16_t bound_port(int fd)
{
    struct sockaddr_in addr;
    socklen_t len = sizeof(addr);
    getsockname(fd, (struct sockaddr *)&addr, &len);
    return ntohs(addr.sin_port);
}

/* ---- Hardware ------------------------------------------------------------------------- */

static uint8_t buttons;
static uint32_t release_at[POD_BUTTONS];
static char key_down = HAL_KEY_NONE;
static uint32_t key_up_at;
static bool card_on;
static uint32_t card_off_at;
static hal_nfc_tag_t card;
static uint8_t card_mem[POD_NFC_MEM];
static size_t card_mem_len;
static int case_raw = 0; /* closed */
static int battery = -1;
static uint16_t led_count = 24;
static uint8_t px[256][3];

static int ok_init(void)
{
    return 0;
}
static void no_deinit(void)
{
}
static uint8_t hw_buttons(void)
{
    return buttons;
}
static char hw_key(void)
{
    return key_down;
}
static bool hw_nfc(hal_nfc_tag_t *t)
{
    if (!card_on) return false;
    *t = card;
    return true;
}
static int hw_mem(uint8_t *buf, size_t cap)
{
    size_t n = card_mem_len < cap ? card_mem_len : cap;
    memcpy(buf, card_mem, n);
    return n > 0 ? (int)n : -1;
}
static void hw_fill(uint8_t r, uint8_t g, uint8_t b)
{
    for (int i = 0; i < led_count; i++) {
        px[i][0] = r;
        px[i][1] = g;
        px[i][2] = b;
    }
    out("LED fill %u %u %u", r, g, b);
}
static void hw_set(int i, uint8_t r, uint8_t g, uint8_t b)
{
    if (i < 0 || i >= led_count) return;
    px[i][0] = r;
    px[i][1] = g;
    px[i][2] = b;
}
static void hw_show(void)
{
    int lit = 0;
    for (int i = 0; i < led_count; i++) lit += (px[i][0] | px[i][1] | px[i][2]) != 0;
    out("LED show %d", lit);
}
static void hw_brightness(uint8_t pct)
{
    out("LED brightness %u", pct);
}
static void hw_tone(void *ctx, uint32_t hz, uint32_t ms)
{
    (void)ctx;
    out("TONE %lu %lu", (unsigned long)hz, (unsigned long)ms);
}
static void hw_stop(void *ctx)
{
    (void)ctx;
    out("AUDIO stop");
}
static void hw_volume(void *ctx, uint8_t pct)
{
    (void)ctx;
    out("AUDIO volume %u", pct);
}

static const hal_button_ops_t button_ops = {ok_init, hw_buttons, no_deinit};
static const hal_keypad_ops_t keypad_ops = {ok_init, hw_key, no_deinit};
static const hal_nfc_ops_t nfc_ops = {ok_init, hw_nfc, hw_mem, no_deinit};
static const hal_led_ops_t led_ops = {ok_init, hw_fill, hw_set, hw_show, hw_brightness, no_deinit};

/* ---- The pod -------------------------------------------------------------------------- */

static hal_t hal;
static pod_t pod;
static pod_caps_t caps;
static pod_ble_t ble;
static radio_limits_t limits;
static uint32_t pending_tag[32];
static modem_tx_status_t pending_status[32];
static int pending;
static bool measure_pending;
static uint32_t measure_hz, measure_done_at;
static uint16_t measure_dwell;
static bool measure_cad;

static int link_write(void *ctx, pod_link_t link, const uint8_t *frame, size_t len)
{
    (void)ctx;
    if (link == POD_LINK_BLE) return pod_ble_send_frame(&ble, frame, len);
    return usb_client >= 0 ? send_all(usb_client, frame, len) : -1;
}

static int ble_notify(void *ctx, uint16_t conn, pod_ble_chr_t chr, const uint8_t *data, size_t len)
{
    (void)ctx;
    (void)conn;
    if (chr != POD_BLE_TX) return 0; /* Pod Status is not carried on this socket */
    if (ble_client < 0) return -1;
    uint8_t msg[2 + 512];
    msg[0] = (uint8_t)(len >> 8);
    msg[1] = (uint8_t)len;
    memcpy(msg + 2, data, len);
    return send_all(ble_client, msg, len + 2) == 0 ? 0 : -1;
}

static uint32_t now(void *ctx)
{
    (void)ctx;
    return mono_ms();
}

static bool command(void *ctx, const atalaia_proxy_msg_t *m)
{
    (void)ctx;
    return pod_caps_command(&caps, m);
}

static void ident(void *ctx, atalaia_proxy_ident_t *id, bool compact)
{
    (void)ctx;
    snprintf(id->fw_version, sizeof(id->fw_version), "host-pod");
    if (pod_caps_descriptors(&caps, id->caps_json, sizeof(id->caps_json), !compact) == 0) {
        snprintf(id->caps_json, sizeof(id->caps_json), "[]");
    }
    id->has_battery = battery >= 0;
    id->battery_pct = battery >= 0 ? (uint8_t)battery : 0;
}

static bool emit(void *ctx, const char *cap, const char *event, const char *data)
{
    (void)ctx;
    return pod_event(&pod, cap, event, data);
}

static void link_active(void *ctx, pod_link_t link)
{
    (void)ctx;
    out("LOG phone on the %s link", link == POD_LINK_USB ? "usb" : "ble");
    pod_caps_report(&caps, emit, NULL);
}

static void log_line(void *ctx, const char *line)
{
    (void)ctx;
    out("LOG %s", line);
}

/* The radio, as the host modem simulates it: the duty cycle per sub-band, the air as UDP. */
static bool radio_send(void *ctx, const uint8_t *pkt, size_t len, uint32_t tag)
{
    (void)ctx;
    if (pending >= 32) return false;
    modem_tx_status_t status = MODEM_TX_OK;
    if (!radio_limits_can_send(&limits, len, mono_ms())) {
        status = MODEM_TX_DUTY_CYCLE;
    } else {
        radio_limits_record(&limits, len, mono_ms());
        if (have_peer) {
            sendto(air_sock, pkt, len, 0, (const struct sockaddr *)&air_peer, sizeof(air_peer));
        }
        char hex[2 * RADIO_MAX_PKT_LEN + 1];
        for (size_t i = 0; i < len; i++) snprintf(hex + 2 * i, 3, "%02x", pkt[i]);
        out("TX %s", hex);
    }
    pending_tag[pending] = tag;
    pending_status[pending] = status;
    pending++;
    return true;
}

static int set_channel(void *ctx, uint32_t hz)
{
    (void)ctx;
    return radio_limits_set_channel(&limits, hz) ? 0 : -1;
}

static uint32_t duty(void *ctx)
{
    (void)ctx;
    return radio_limits_remaining_ms(&limits, mono_ms());
}

static int measure_start(void *ctx, uint32_t hz, uint16_t dwell, bool cad)
{
    (void)ctx;
    if (measure_pending) return -1;
    measure_pending = true;
    measure_hz = hz;
    measure_dwell = dwell;
    measure_cad = cad;
    measure_done_at = mono_ms() + dwell;
    return 0;
}

static void finish_measure(void)
{
    measure_pending = false;
    static noise_acc_t acc;
    noise_acc_init(&acc);
    uint32_t x = measure_hz;
    for (uint32_t i = 0; i < measure_dwell; i++) {
        x = x * 1103515245u + 12345u;
        noise_acc_add(&acc, -120 + (int)((x >> 16) % 5u) - 2);
    }
    if (measure_cad) {
        for (uint32_t i = 0; i < measure_dwell / 100u + 1u; i++) noise_acc_cad(&acc, false);
    }
    noise_result_t r;
    noise_acc_finish(&acc, measure_hz, measure_dwell, &r);
    pod_on_measure_result(&pod, 0, &r);
}

/* ---- Control lines ---------------------------------------------------------------------- */

static size_t unhex(const char *s, uint8_t *out_buf, size_t cap)
{
    size_t n = 0;
    while (s[0] && s[1] && n < cap) {
        unsigned v;
        if (sscanf(s, "%2x", &v) != 1) return 0;
        out_buf[n++] = (uint8_t)v;
        s += 2;
    }
    return s[0] ? 0 : n;
}

static void put_card(const char *uid_hex, const uint8_t *mem, size_t mem_len)
{
    memset(&card, 0, sizeof(card));
    card.uid_len = (uint8_t)unhex(uid_hex, card.uid, sizeof(card.uid));
    memcpy(card_mem, mem, mem_len);
    card_mem_len = mem_len;
    card_on = card.uid_len > 0;
    card_off_at = mono_ms() + 500;
}

static void print_status(void)
{
    out("STATUS {\"usb\":%s,\"ble\":%s,\"radio_configured\":%s,\"radio_owner\":%d,\"pending\":%u,"
        "\"evt_sent\":%lu,\"evt_acked\":%lu,\"evt_lost\":%lu,\"cmds\":%lu,\"cmd_repeats\":%lu,"
        "\"cmd_unknown\":%lu,\"bad_payloads\":%lu,\"ignored\":%lu,\"links_broken\":%lu,"
        "\"field_tx\":%lu,\"field_rx\":%lu}",
        pod_link_active(&pod, POD_LINK_USB) ? "true" : "false",
        pod_link_active(&pod, POD_LINK_BLE) ? "true" : "false",
        pod.radio.configured ? "true" : "false", pod.radio_owner, (unsigned)pod_pending(&pod),
        (unsigned long)pod.count.evt_sent, (unsigned long)pod.count.evt_acked,
        (unsigned long)pod.count.evt_lost, (unsigned long)pod.count.cmds,
        (unsigned long)pod.count.cmd_repeats, (unsigned long)pod.count.cmd_unknown,
        (unsigned long)pod.count.bad_payloads, (unsigned long)pod.count.ignored,
        (unsigned long)pod.count.links_broken, (unsigned long)pod.radio.count.field_tx,
        (unsigned long)pod.radio.count.field_rx);
}

/* Returns false on "quit". */
static bool control(char *line)
{
    char *nl = strchr(line, '\n');
    if (nl) *nl = '\0';
    int n = 0, ms = 0;
    char a[160] = "", b[160] = "";
    if (sscanf(line, "press %d", &n) == 1 && n >= 1 && n <= POD_BUTTONS) {
        buttons |= (uint8_t)(1u << (n - 1));
        release_at[n - 1] = 0;
    } else if (sscanf(line, "release %d", &n) == 1 && n >= 1 && n <= POD_BUTTONS) {
        buttons &= (uint8_t) ~(1u << (n - 1));
    } else if (sscanf(line, "hold %d %d", &n, &ms) == 2 && n >= 1 && n <= POD_BUTTONS) {
        buttons |= (uint8_t)(1u << (n - 1));
        release_at[n - 1] = mono_ms() + (uint32_t)ms;
        if (release_at[n - 1] == 0) release_at[n - 1] = 1;
    } else if (strncmp(line, "key ", 4) == 0 && line[4]) {
        key_down = line[4];
        key_up_at = mono_ms() + 60;
    } else if (sscanf(line, "tag %159s %159s", a, b) >= 1) {
        uint8_t rec[ATALAIA_TAG_MAX], mem[POD_NFC_MEM];
        size_t rlen = b[0] ? unhex(b, rec, sizeof(rec)) : 0;
        size_t mlen = rlen > 0 ? atalaia_tag_to_ndef_tag(rec, rlen, mem, sizeof(mem)) : 16;
        if (rlen == 0) memset(mem, 0, 16);
        put_card(a, mem, mlen);
    } else if (sscanf(line, "join %159s", a) == 1) {
        const uint8_t payload[] = {1, 2, 3, 4, 5, 6, 7, 8};
        uint8_t mem[POD_NFC_MEM];
        size_t mlen = atalaia_join_to_ndef_tag(payload, sizeof(payload), mem, sizeof(mem));
        put_card(a, mem, mlen);
    } else if (strcmp(line, "case open") == 0) {
        case_raw = 1;
    } else if (strcmp(line, "case closed") == 0) {
        case_raw = 0;
    } else if (sscanf(line, "battery %d", &n) == 1) {
        battery = n < 0 ? -1 : n > 100 ? 100 : n;
    } else if (strcmp(line, "status") == 0) {
        print_status();
    } else if (strcmp(line, "quit") == 0) {
        return false;
    } else if (line[0]) {
        out("LOG unknown command: %s", line);
    }
    return true;
}

/* ---- Main --------------------------------------------------------------------------------- */

static long arg_value(int argc, char **argv, int *i)
{
    if (*i + 1 >= argc) {
        fprintf(stderr, "pod_host: %s needs a value\n", argv[*i]);
        exit(2);
    }
    (*i)++;
    return strtol(argv[*i], NULL, 10);
}

static void ble_disconnect(void)
{
    if (ble_client >= 0) close(ble_client);
    ble_client = -1;
    ble_in_len = 0;
    pod_ble_on_disconnect(&ble);
}

static void ble_bytes(const uint8_t *data, size_t len)
{
    for (size_t i = 0; i < len; i++) {
        if (ble_in_len >= sizeof(ble_in)) {
            ble_disconnect(); /* a write longer than any MTU allows */
            return;
        }
        ble_in[ble_in_len++] = data[i];
        if (ble_in_len < 2) continue;
        size_t want = (size_t)ble_in[0] << 8 | ble_in[1];
        if (want > (size_t)ble_mtu - 3) {
            out("LOG Bluetooth write of %u bytes, more than the MTU allows", (unsigned)want);
            ble_disconnect();
            return;
        }
        if (ble_in_len == 2 + want) {
            pod_ble_on_write(&ble, ble_in + 2, want);
            ble_in_len = 0;
        }
    }
}

int main(int argc, char **argv)
{
    long usb_port = 0, ble_port = 0, air_port = 0, peer_port = 0;
    bool radio = true;
    pod_caps_config_t cfg;
    memset(&cfg, 0, sizeof(cfg));
    static char colours[POD_BUTTONS][24];
    int nbuttons = POD_BUTTONS;
    cfg.keypad = cfg.nfc = cfg.leds = cfg.audio = cfg.tamper = true;
    radio_limits_init(&limits, 14, 2);
    radio_limits_set_channel(&limits, radio_region_default_channel_hz(RADIO_REGION));
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--usb-port") == 0) {
            usb_port = arg_value(argc, argv, &i);
        } else if (strcmp(argv[i], "--ble-port") == 0) {
            ble_port = arg_value(argc, argv, &i);
        } else if (strcmp(argv[i], "--ble-mtu") == 0) {
            long m = arg_value(argc, argv, &i);
            ble_mtu = (uint16_t)(m < POD_BLE_MTU_MIN ? POD_BLE_MTU_MIN : m > 517 ? 517 : m);
        } else if (strcmp(argv[i], "--air-port") == 0) {
            air_port = arg_value(argc, argv, &i);
        } else if (strcmp(argv[i], "--air-peer") == 0) {
            peer_port = arg_value(argc, argv, &i);
        } else if (strcmp(argv[i], "--no-radio") == 0) {
            radio = false;
        } else if (strcmp(argv[i], "--buttons") == 0) {
            nbuttons = (int)arg_value(argc, argv, &i);
        } else if (strcmp(argv[i], "--colour") == 0 && i + 1 < argc) {
            int b = 0;
            char name[24] = "";
            if (sscanf(argv[++i], "%d=%23s", &b, name) == 2 && b >= 1 && b <= POD_BUTTONS) {
                snprintf(colours[b - 1], sizeof(colours[0]), "%s", name);
                cfg.team[b - 1] = colours[b - 1];
            }
        } else if (strcmp(argv[i], "--led-count") == 0) {
            long c = arg_value(argc, argv, &i);
            led_count = (uint16_t)(c < 1 ? 1 : c > 256 ? 256 : c);
        } else if (strcmp(argv[i], "--no-keypad") == 0) {
            cfg.keypad = false;
        } else if (strcmp(argv[i], "--no-nfc") == 0) {
            cfg.nfc = false;
        } else if (strcmp(argv[i], "--no-leds") == 0) {
            cfg.leds = false;
        } else if (strcmp(argv[i], "--no-audio") == 0) {
            cfg.audio = false;
        } else if (strcmp(argv[i], "--no-case") == 0) {
            cfg.tamper = false;
        } else {
            fprintf(stderr, "pod_host: unknown option %s\n", argv[i]);
            return 2;
        }
    }
    for (int i = 0; i < POD_BUTTONS; i++) cfg.button[i] = i < nbuttons;
    cfg.led_count = led_count;
    signal(SIGPIPE, SIG_IGN);

    usb_listen = bind_socket(SOCK_STREAM, (uint16_t)usb_port);
    ble_listen = bind_socket(SOCK_STREAM, (uint16_t)ble_port);
    air_sock = bind_socket(SOCK_DGRAM, (uint16_t)air_port);
    if (usb_listen < 0 || ble_listen < 0 || air_sock < 0 || listen(usb_listen, 1) != 0 ||
        listen(ble_listen, 1) != 0) {
        perror("pod_host: bind");
        return 1;
    }
    if (peer_port > 0) {
        memset(&air_peer, 0, sizeof(air_peer));
        air_peer.sin_family = AF_INET;
        air_peer.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        air_peer.sin_port = htons((uint16_t)peer_port);
        have_peer = true;
    }

    hal.buttons = &button_ops;
    hal.keypad = &keypad_ops;
    hal.nfc = &nfc_ops;
    hal.leds = &led_ops;
    pod_audio_t audio = {hw_tone, hw_stop, hw_volume, NULL};
    pod_caps_init(&caps, &cfg, &hal, &audio);
    pod_io_t io = {link_write, now, command, ident, link_active, log_line, NULL};
    modem_io_t rio = {
        .radio_send = radio_send,
        .set_channel = set_channel,
        .duty_cycle_remaining_ms = duty,
        .now_ms = now,
        .measure_start = measure_start,
    };
    pod_init(&pod, &io, &rio, &atalaia_crypto_mbedtls, "host-pod", radio, 16);
    pod_ble_stack_t stack = {ble_notify, NULL};
    pod_ble_init(&ble, &pod, &stack, true);

    out("READY usb=%u ble=%u air=%u", bound_port(usb_listen), bound_port(ble_listen),
        bound_port(air_sock));

    char line[512];
    size_t line_len = 0;
    bool running = true;
    while (running) {
        struct pollfd fds[4];
        fds[0].fd = air_sock;
        fds[0].events = POLLIN;
        fds[1].fd = usb_client >= 0 ? usb_client : usb_listen;
        fds[1].events = POLLIN;
        fds[2].fd = ble_client >= 0 ? ble_client : ble_listen;
        fds[2].events = POLLIN;
        fds[3].fd = STDIN_FILENO;
        fds[3].events = POLLIN;
        if (poll(fds, 4, 5) < 0 && errno != EINTR) {
            perror("pod_host: poll");
            return 1;
        }
        uint32_t t = mono_ms();
        if (fds[0].revents & POLLIN) {
            uint8_t pkt[RADIO_MAX_PKT_LEN + 1];
            ssize_t got = recv(air_sock, pkt, sizeof(pkt), 0);
            if (got > 0 && got <= RADIO_MAX_PKT_LEN) pod_on_air_rx(&pod, pkt, (size_t)got, -42, 7);
        }
        if (fds[1].revents & (POLLIN | POLLHUP | POLLERR)) {
            if (usb_client < 0) {
                usb_client = accept(usb_listen, NULL, NULL);
                if (usb_client >= 0) pod_set_link_up(&pod, POD_LINK_USB, true);
            } else {
                uint8_t buf[512];
                ssize_t got = recv(usb_client, buf, sizeof(buf), 0);
                if (got <= 0) {
                    close(usb_client);
                    usb_client = -1;
                    pod_set_link_up(&pod, POD_LINK_USB, false);
                } else {
                    pod_feed(&pod, POD_LINK_USB, buf, (size_t)got);
                }
            }
        }
        if (fds[2].revents & (POLLIN | POLLHUP | POLLERR)) {
            if (ble_client < 0) {
                ble_client = accept(ble_listen, NULL, NULL);
                if (ble_client >= 0) {
                    /* Connected, the MTU exchanged, paired, notifications on. */
                    pod_ble_on_connect(&ble, 1);
                    pod_ble_on_mtu(&ble, ble_mtu);
                    pod_ble_on_encryption(&ble, true);
                    pod_ble_on_subscribe(&ble, POD_BLE_TX, true);
                }
            } else {
                uint8_t buf[512];
                ssize_t got = recv(ble_client, buf, sizeof(buf), 0);
                if (got <= 0) {
                    ble_disconnect();
                } else {
                    ble_bytes(buf, (size_t)got);
                }
            }
        }
        if (fds[3].revents & (POLLIN | POLLHUP)) {
            char chunk[256];
            ssize_t got = read(STDIN_FILENO, chunk, sizeof(chunk));
            if (got <= 0) running = false;
            for (ssize_t k = 0; k < got && running; k++) {
                if (chunk[k] == '\n' || line_len + 1 >= sizeof(line)) {
                    line[line_len] = '\0';
                    line_len = 0;
                    running = control(line);
                } else {
                    line[line_len++] = chunk[k];
                }
            }
        }

        /* The hardware's timeline. */
        for (int i = 0; i < POD_BUTTONS; i++) {
            if (release_at[i] != 0 && (int32_t)(t - release_at[i]) >= 0) {
                buttons &= (uint8_t) ~(1u << i);
                release_at[i] = 0;
            }
        }
        if (key_down != HAL_KEY_NONE && (int32_t)(t - key_up_at) >= 0) key_down = HAL_KEY_NONE;
        if (card_on && (int32_t)(t - card_off_at) >= 0) card_on = false;

        pod_caps_poll(&caps, t, cfg.tamper ? case_raw : -1, emit, NULL);
        for (int i = 0; i < pending; i++) pod_on_tx_result(&pod, pending_tag[i], pending_status[i]);
        pending = 0;
        if (measure_pending && (int32_t)(t - measure_done_at) >= 0) finish_measure();
        pod_tick(&pod);
        pod_ble_flush(&ble);
    }
    return 0;
}
