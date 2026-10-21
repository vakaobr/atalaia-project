/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The USB radio modem's OLED status (modem_screen.h): the link state from
 * the host frames, and the six lines a GM reads. The drawn screens are
 * compared with reference images in test_oled_screens.c.
 */
#include <string.h>

#include "check.h"
#include "modem/modem_screen.h"

#define TIMEOUT_MS 12000u
#define DEFAULT_HZ 869525000u

static uint32_t fake_now;

static uint32_t now_cb(void *ctx)
{
    (void)ctx;
    return fake_now;
}

static int write_cb(void *ctx, const uint8_t *buf, size_t len)
{
    (void)ctx;
    (void)buf;
    (void)len;
    return 0;
}

static void start(modem_t *m, bool radio)
{
    modem_io_t io = {.serial_write = write_cb, .now_ms = now_cb};
    fake_now = 1000;
    modem_init(m, &io, &atalaia_crypto_test_stub, "test", radio, 16);
}

static void ping(modem_t *m)
{
    uint8_t cmd[5] = {MODEM_CMD_PING, 0, 0, 0, 7};
    uint8_t frame[MODEM_FRAME_MAX];
    size_t n = modem_frame_encode(MODEM_FRAME_CMD, cmd, sizeof(cmd), frame, sizeof(frame));
    modem_feed_serial(m, frame, n);
}

static modem_screen_state_t state_of(const modem_t *m, uint32_t duty_ms, const char *fault)
{
    modem_screen_state_t s;
    modem_screen_state(m, fake_now, TIMEOUT_MS, DEFAULT_HZ, duty_ms, fault, &s);
    return s;
}

static void test_link_follows_host_frames(void)
{
    static modem_t m;
    start(&m, true);
    CHECK(state_of(&m, 0, NULL).link == MODEM_LINK_WAITING);
    fake_now = 20000; /* nothing yet: still waiting, never "down" */
    CHECK(state_of(&m, 0, NULL).link == MODEM_LINK_WAITING);
    ping(&m);
    CHECK(m.host_seen);
    CHECK(state_of(&m, 0, NULL).link == MODEM_LINK_UP);
    fake_now += TIMEOUT_MS; /* exactly the timeout: still up */
    CHECK(state_of(&m, 0, NULL).link == MODEM_LINK_UP);
    fake_now += 1;
    CHECK(state_of(&m, 0, NULL).link == MODEM_LINK_DOWN);
    ping(&m);
    CHECK(state_of(&m, 0, NULL).link == MODEM_LINK_UP);

    /* A corrupted frame (bad CRC) is not the host talking. */
    static modem_t q;
    start(&q, true);
    uint8_t cmd[1] = {MODEM_CMD_STATUS};
    uint8_t frame[MODEM_FRAME_MAX];
    size_t n = modem_frame_encode(MODEM_FRAME_CMD, cmd, sizeof(cmd), frame, sizeof(frame));
    frame[n - 1] ^= 0xFF;
    modem_feed_serial(&q, frame, n);
    CHECK(!q.host_seen);
}

static void test_state_copies_the_status_counters(void)
{
    static modem_t m;
    start(&m, true);
    modem_screen_state_t s = state_of(&m, 359900, NULL);
    CHECK(s.channel_hz == DEFAULT_HZ); /* the boot channel until one is set */
    CHECK(!s.configured && s.radio_ok && s.fault[0] == '\0');
    CHECK(s.duty_ms == 359900);
    m.configured = true;
    m.game_id = 4660;
    m.channel_hz = 868100000u;
    m.count.rx_ok = 5;
    m.count.rx_auth_fail = 2;
    m.count.tx_ok = 7;
    m.count.tx_fail = 1;
    s = state_of(&m, 1000, NULL);
    CHECK(s.configured && s.game_id == 4660 && s.channel_hz == 868100000u);
    CHECK(s.rx == 5 && s.rx_auth_fail == 2 && s.tx == 7 && s.tx_fail == 1);

    static modem_t r;
    start(&r, false);
    s = state_of(&r, 5000, "SX1262 not found");
    CHECK(!s.radio_ok && s.duty_ms == 0);
    CHECK(strcmp(s.fault, "SX1262 not found") == 0);
    s = state_of(&r, 0, NULL); /* the reason unknown */
    CHECK(strcmp(s.fault, "no SX1262 radio") == 0);
}

static void test_count(void)
{
    char s[8];
    modem_screen_count(0, 4, s, sizeof(s));
    CHECK(strcmp(s, "0") == 0);
    modem_screen_count(9999, 4, s, sizeof(s));
    CHECK(strcmp(s, "9999") == 0);
    modem_screen_count(12345, 4, s, sizeof(s));
    CHECK(strcmp(s, "12k") == 0);
    modem_screen_count(999999, 4, s, sizeof(s));
    CHECK(strcmp(s, "999k") == 0);
    modem_screen_count(1000000, 4, s, sizeof(s));
    CHECK(strcmp(s, "1M") == 0);
    modem_screen_count(999, 3, s, sizeof(s));
    CHECK(strcmp(s, "999") == 0);
    modem_screen_count(1000, 3, s, sizeof(s));
    CHECK(strcmp(s, "1k") == 0);
    modem_screen_count(4294967295u, 3, s, sizeof(s));
    CHECK(strcmp(s, "4G") == 0);
    modem_screen_count(4294967295u, 4, s, sizeof(s));
    CHECK(strcmp(s, "4G") == 0);
}

static modem_screen_state_t sample(void)
{
    modem_screen_state_t s;
    memset(&s, 0, sizeof(s));
    s.link = MODEM_LINK_UP;
    s.configured = true;
    s.game_id = 4660;
    s.channel_hz = 869525000u;
    s.tx = 1234;
    s.tx_fail = 3;
    s.rx = 56789;
    s.rx_auth_fail = 0;
    s.radio_ok = true;
    s.duty_ms = 359900;
    return s;
}

static void test_text_in_game(void)
{
    modem_screen_state_t s = sample();
    modem_screen_text_t t;
    modem_screen_text(&s, &t);
    CHECK(strcmp(t.line[0], "LINK          OK") == 0);
    CHECK(strcmp(t.line[1], "GAME        4660") == 0);
    CHECK(strcmp(t.line[2], "CH   869.525 MHz") == 0);
    CHECK(strcmp(t.line[3], "TX 1234   fail 3") == 0);
    CHECK(strcmp(t.line[4], "RX 56k    auth 0") == 0);
    CHECK(strcmp(t.line[5], "DUTY 359.9s left") == 0);
    for (int i = 0; i < MODEM_SCREEN_LINES; i++) {
        CHECK(!t.inverted[i]);
        CHECK(strlen(t.line[i]) <= MODEM_SCREEN_COLS);
    }
}

static void test_text_states(void)
{
    modem_screen_state_t s = sample();
    modem_screen_text_t t;

    s.link = MODEM_LINK_WAITING;
    s.configured = false;
    modem_screen_text(&s, &t);
    CHECK(strcmp(t.line[0], "LINK     waiting") == 0);
    CHECK(!t.inverted[0]);
    CHECK(strcmp(t.line[1], "IDLE     no game") == 0);

    s.link = MODEM_LINK_DOWN;
    s.measuring = true;
    modem_screen_text(&s, &t);
    CHECK(strcmp(t.line[0], "LINK        DOWN") == 0);
    CHECK(t.inverted[0]);
    CHECK(strcmp(t.line[1], "IDLE   measuring") == 0);

    s = sample();
    s.duty_ms = 0; /* no budget left: TX waits */
    modem_screen_text(&s, &t);
    CHECK(strcmp(t.line[5], "DUTY   0.0s left") == 0);
    CHECK(t.inverted[5]);
    s.duty_ms = 3600000;
    modem_screen_text(&s, &t);
    CHECK(strcmp(t.line[5], "DUTY  3600s left") == 0);

    s = sample();
    s.tx = 4294967295u;
    s.tx_fail = 4294967295u;
    modem_screen_text(&s, &t);
    CHECK(strcmp(t.line[3], "TX 4G    fail 4G") == 0);
}

static void test_text_radio_fault(void)
{
    modem_screen_state_t s = sample();
    s.configured = false;
    s.radio_ok = false;
    strcpy(s.fault, "SX1262 not found (BUSY stuck)");
    modem_screen_text_t t;
    modem_screen_text(&s, &t);
    CHECK(strcmp(t.line[0], "LINK          OK") == 0);
    CHECK(strcmp(t.line[2], "RADIO FAULT") == 0);
    CHECK(t.inverted[2]);
    CHECK(strcmp(t.line[3], "SX1262 not found") == 0);
    CHECK(strcmp(t.line[4], "(BUSY stuck)") == 0);
    CHECK(strcmp(t.line[5], "no TX, no RX") == 0);

    strcpy(s.fault, "SX1262errors0x0020longword");
    modem_screen_text(&s, &t); /* no space: cut at 16 columns */
    CHECK(strcmp(t.line[3], "SX1262errors0x00") == 0);
    CHECK(strcmp(t.line[4], "20longword") == 0);
}

void run_modem_screen_tests(void)
{
    test_link_follows_host_frames();
    test_state_copies_the_status_counters();
    test_count();
    test_text_in_game();
    test_text_states();
    test_text_radio_fault();
}
