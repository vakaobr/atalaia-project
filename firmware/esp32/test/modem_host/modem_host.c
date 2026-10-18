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

static uint32_t duty_budget_ms = 360000; /* g2: 10% of an hour */
static uint32_t duty_used_ms = 0;

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
    /* Same rough airtime as the ESP HAL: (len + 20) ms at SF7/BW125. */
    uint32_t airtime = (uint32_t)len + 20u;
    modem_tx_status_t status = MODEM_TX_OK;
    if (duty_used_ms + airtime > duty_budget_ms) {
        status = MODEM_TX_DUTY_CYCLE;
    } else {
        duty_used_ms += airtime;
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
    (void)freq_hz;
    return 0;
}

static uint32_t io_duty_remaining(void *ctx)
{
    (void)ctx;
    return duty_used_ms >= duty_budget_ms ? 0 : duty_budget_ms - duty_used_ms;
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
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--serial-port") == 0) {
            serial_port = arg_value(argc, argv, &i);
        } else if (strcmp(argv[i], "--air-port") == 0) {
            air_port = arg_value(argc, argv, &i);
        } else if (strcmp(argv[i], "--air-peer") == 0) {
            peer_port = arg_value(argc, argv, &i);
        } else if (strcmp(argv[i], "--epoch-window") == 0) {
            window = arg_value(argc, argv, &i);
        } else if (strcmp(argv[i], "--duty-budget-ms") == 0) {
            duty_budget_ms = (uint32_t)arg_value(argc, argv, &i);
        } else if (strcmp(argv[i], "--no-radio") == 0) {
            radio = false;
        } else {
            fprintf(stderr, "modem_host: unknown option %s\n", argv[i]);
            return 2;
        }
    }
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
        .ctx = NULL,
    };
    static modem_t modem;
    modem_init(&modem, &io, &atalaia_crypto_mbedtls, "host", radio, (uint16_t)window);

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
    }
}
