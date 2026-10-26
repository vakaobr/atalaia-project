/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Host modem: the USB radio modem's logic (main/modem/modem.c) with real
 * AES-128-CCM (mbedtls), running on Linux for the controller's tests.
 *
 *   - the "USB serial link" is a TCP socket on 127.0.0.1: the controller
 *     opens it with pyserial's socket:// URL, exactly as it opens
 *     /dev/ttyACM0 on a Raspberry Pi;
 *   - the "air" is UDP on 127.0.0.1: every datagram received on the air
 *     port is a packet heard on the radio, and every packet the modem
 *     transmits is sent as one datagram to the air peer port.
 *
 *   modem_host [--serial-port N] [--air-port N] [--air-peer N]
 *              [--epoch-window N] [--duty-budget-ms N] [--no-radio]
 *              [--noise-floor DBM] [--noise HZ:DBM[:CAD_PCT]]... [--measure-fail HZ]
 *              [--region eu868|as923-tw]
 *
 * --region plays a modem built for that radio region (Kconfig
 * ATALAIA_RADIO_REGION; EU868 by default): it starts on the region's
 * default channel, refuses channels of other regions and names its region
 * in IDENT. The duty-cycle budget and the TX power follow the channel's
 * sub-band (radio/radio_limits.c, as on the ESP32); --duty-budget-ms caps
 * the budget lower for tests. MEASURE answers after the asked dwell, with
 * samples drawn around the channel's simulated level (--noise, else
 * --noise-floor, -120 dBm by default) and CAD detections in CAD_PCT percent
 * of the tries; --measure-fail makes a measurement of HZ fail as a radio
 * error would.
 *
 * Port 0 picks a free port. Once listening it prints one line on stdout:
 *   READY serial=<port> air=<port>
 * It serves one serial client at a time and runs until killed.
 */
#define _POSIX_C_SOURCE 200809L

#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#include "modem/modem.h"
#include "radio/noise_stats.h"
#include "radio/radio_limits.h"

/* macOS has no MSG_NOSIGNAL; SIGPIPE is ignored in main() either way. */
#ifndef MSG_NOSIGNAL
#define MSG_NOSIGNAL 0
#endif

#define PENDING_MAX 32

static int serial_listen = -1;
static int serial_client = -1;
static int air_sock = -1;
static struct sockaddr_in air_peer;
static bool have_peer = false;

/* TX outcomes are reported after the frame that caused them is handled,
 * as the real radio task does. */
static uint32_t pending_tag[PENDING_MAX];
static modem_tx_status_t pending_status[PENDING_MAX];
static int pending = 0;

/* Duty cycle and power per sub-band, as the SX1262 HAL does. */
static radio_limits_t limits;

/* Simulated noise per channel. */
#define NOISE_MAX 32
static uint32_t noise_hz[NOISE_MAX];
static int noise_dbm[NOISE_MAX];
static int noise_cad_pct[NOISE_MAX];
static int noise_count = 0;
static int noise_floor = -120;
static uint32_t measure_fail_hz = 0;

/* A measurement in progress: answered when its dwell has passed. */
static bool measure_pending = false;
static uint32_t measure_hz, measure_done_at;
static uint16_t measure_dwell;
static bool measure_cad;

static uint32_t mono_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint32_t)((uint64_t)ts.tv_sec * 1000u + (uint64_t)ts.tv_nsec / 1000000u);
}

static int io_serial_write(void *ctx, const uint8_t *buf, size_t len)
{
    (void)ctx;
    if (serial_client < 0) return -1;
    size_t done = 0;
    while (done < len) {
        ssize_t n = send(serial_client, buf + done, len - done, MSG_NOSIGNAL);
        if (n < 0) {
            if (errno == EINTR) continue;
            return -1;
        }
        done += (size_t)n;
    }
    return 0;
}

static bool io_radio_send(void *ctx, const uint8_t *pkt, size_t len, uint32_t tag)
{
    (void)ctx;
    if (pending >= PENDING_MAX) return false;
    /* The packet's LoRa time on air must fit in its sub-band's budget. */
    modem_tx_status_t status = MODEM_TX_OK;
    if (!radio_limits_can_send(&limits, len, mono_ms())) {
        status = MODEM_TX_DUTY_CYCLE;
    } else {
        radio_limits_record(&limits, len, mono_ms());
        if (have_peer) {
            sendto(air_sock, pkt, len, 0, (const struct sockaddr *)&air_peer, sizeof(air_peer));
        }
    }
    pending_tag[pending] = tag;
    pending_status[pending] = status;
    pending++;
    return true;
}

static int io_set_channel(void *ctx, uint32_t freq_hz)
{
    (void)ctx;
    return radio_limits_set_channel(&limits, freq_hz) ? 0 : -1;
}

static uint32_t io_duty_remaining(void *ctx)
{
    (void)ctx;
    return radio_limits_remaining_ms(&limits, mono_ms());
}

static int io_measure_start(void *ctx, uint32_t freq_hz, uint16_t dwell_ms, bool cad)
{
    (void)ctx;
    if (measure_pending) return -1;
    measure_pending = true;
    measure_hz = freq_hz;
    measure_dwell = dwell_ms;
    measure_cad = cad;
    measure_done_at = mono_ms() + dwell_ms;
    return 0;
}

/* The simulated measurement: one reading per millisecond of dwell around
 * the channel's level (a deterministic +-2 dB wobble and, every 50th
 * reading, a 10 dB spike), through the same summary code as the ESP32. */
static void finish_measure(modem_t *m)
{
    int level = noise_floor;
    int cad_pct = 0;
    for (int i = 0; i < noise_count; i++) {
        if (noise_hz[i] == measure_hz) {
            level = noise_dbm[i];
            cad_pct = noise_cad_pct[i];
        }
    }
    measure_pending = false;
    if (measure_hz == measure_fail_hz) {
        modem_on_measure_result(m, -1, NULL);
        return;
    }
    static noise_acc_t acc;
    noise_acc_init(&acc);
    uint32_t x = measure_hz;
    for (uint32_t i = 0; i < measure_dwell; i++) {
        x = x * 1103515245u + 12345u;
        int r = level + (int)((x >> 16) % 5u) - 2;
        if (i % 50 == 49) r += 10;
        noise_acc_add(&acc, r);
    }
    if (measure_cad) {
        uint32_t tries = measure_dwell / 100u > 0 ? measure_dwell / 100u : 1u;
        uint32_t hits = (tries * (uint32_t)cad_pct + 50u) / 100u;
        for (uint32_t i = 0; i < tries; i++) noise_acc_cad(&acc, i < hits);
    }
    noise_result_t r;
    noise_acc_finish(&acc, measure_hz, measure_dwell, &r);
    modem_on_measure_result(m, 0, &r);
}

static uint32_t io_now(void *ctx)
{
    (void)ctx;
    return mono_ms();
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

static long arg_value(int argc, char **argv, int *i)
{
    if (*i + 1 >= argc) {
        fprintf(stderr, "modem_host: %s needs a value\n", argv[*i]);
        exit(2);
    }
    (*i)++;
    return strtol(argv[*i], NULL, 10);
}

int main(int argc, char **argv)
{
    long serial_port = 0, air_port = 0, peer_port = 0, window = 16;
    bool radio = true;
    atalaia_region_t region = RADIO_REGION;
    /* The ESP32 HAL's defaults: 14 dB FEM, 2 dBi antenna, the default channel. */
    radio_limits_init(&limits, 14, 2);
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--region") == 0) {
            region = atalaia_region_from_code(i + 1 < argc ? argv[++i] : NULL);
            if (region == ATALAIA_REGION_COUNT) {
                fprintf(stderr, "modem_host: --region eu868 or as923-tw\n");
                return 2;
            }
        } else if (strcmp(argv[i], "--serial-port") == 0) {
            serial_port = arg_value(argc, argv, &i);
        } else if (strcmp(argv[i], "--air-port") == 0) {
            air_port = arg_value(argc, argv, &i);
        } else if (strcmp(argv[i], "--air-peer") == 0) {
            peer_port = arg_value(argc, argv, &i);
        } else if (strcmp(argv[i], "--epoch-window") == 0) {
            window = arg_value(argc, argv, &i);
        } else if (strcmp(argv[i], "--duty-budget-ms") == 0) {
            limits.budget_cap_us = (uint32_t)arg_value(argc, argv, &i) * 1000u;
        } else if (strcmp(argv[i], "--noise-floor") == 0) {
            noise_floor = (int)arg_value(argc, argv, &i);
        } else if (strcmp(argv[i], "--measure-fail") == 0) {
            measure_fail_hz = (uint32_t)arg_value(argc, argv, &i);
        } else if (strcmp(argv[i], "--noise") == 0) {
            if (i + 1 >= argc || noise_count >= NOISE_MAX) {
                fprintf(stderr, "modem_host: --noise HZ:DBM[:CAD_PCT]\n");
                return 2;
            }
            i++;
            unsigned long hz = 0;
            int dbm = 0, pct = 0;
            if (sscanf(argv[i], "%lu:%d:%d", &hz, &dbm, &pct) < 2) {
                fprintf(stderr, "modem_host: bad --noise %s\n", argv[i]);
                return 2;
            }
            noise_hz[noise_count] = (uint32_t)hz;
            noise_dbm[noise_count] = dbm;
            noise_cad_pct[noise_count] = pct;
            noise_count++;
        } else if (strcmp(argv[i], "--no-radio") == 0) {
            radio = false;
        } else {
            fprintf(stderr, "modem_host: unknown option %s\n", argv[i]);
            return 2;
        }
    }
    radio_limits_set_region(&limits, region);
    radio_limits_set_channel(&limits, radio_region_default_channel_hz(region));
    signal(SIGPIPE, SIG_IGN);

    serial_listen = bind_socket(SOCK_STREAM, (uint16_t)serial_port);
    air_sock = bind_socket(SOCK_DGRAM, (uint16_t)air_port);
    if (serial_listen < 0 || air_sock < 0 || listen(serial_listen, 1) != 0) {
        perror("modem_host: bind");
        return 1;
    }
    if (peer_port > 0) {
        memset(&air_peer, 0, sizeof(air_peer));
        air_peer.sin_family = AF_INET;
        air_peer.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        air_peer.sin_port = htons((uint16_t)peer_port);
        have_peer = true;
    }

    modem_io_t io = {
        .serial_write = io_serial_write,
        .radio_send = io_radio_send,
        .set_channel = io_set_channel,
        .duty_cycle_remaining_ms = io_duty_remaining,
        .now_ms = io_now,
        .measure_start = io_measure_start,
        .ctx = NULL,
    };
    static modem_t modem;
    modem_init(&modem, &io, &atalaia_crypto_mbedtls, "host", radio, (uint16_t)window);
    modem.region = region;

    printf("READY serial=%u air=%u\n", bound_port(serial_listen), bound_port(air_sock));
    fflush(stdout);

    for (;;) {
        struct pollfd fds[3];
        int n = 0;
        fds[n].fd = air_sock;
        fds[n++].events = POLLIN;
        fds[n].fd = serial_client >= 0 ? serial_client : serial_listen;
        fds[n++].events = POLLIN;
        if (poll(fds, (nfds_t)n, 10) < 0 && errno != EINTR) {
            perror("modem_host: poll");
            return 1;
        }
        if (fds[0].revents & POLLIN) {
            uint8_t pkt[RADIO_MAX_PKT_LEN + 1];
            ssize_t got = recv(air_sock, pkt, sizeof(pkt), 0);
            if (got > 0 && got <= RADIO_MAX_PKT_LEN) {
                modem_on_air_rx(&modem, pkt, (size_t)got, -42, 7);
            }
        }
        if (fds[1].revents & (POLLIN | POLLHUP | POLLERR)) {
            if (serial_client < 0) {
                serial_client = accept(serial_listen, NULL, NULL);
            } else {
                uint8_t buf[512];
                ssize_t got = recv(serial_client, buf, sizeof(buf), 0);
                if (got <= 0) {
                    close(serial_client);
                    serial_client = -1;
                } else {
                    modem_feed_serial(&modem, buf, (size_t)got);
                }
            }
        }
        for (int i = 0; i < pending; i++) {
            modem_on_tx_result(&modem, pending_tag[i], pending_status[i]);
        }
        pending = 0;
        if (measure_pending && (int32_t)(mono_ms() - measure_done_at) >= 0) {
            finish_measure(&modem);
        }
    }
}
