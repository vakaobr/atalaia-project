/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The radio report lines (radio/radio_stats.c, decision SL-18): the format
 * tools/bench_radio_log.py reads.
 */
#include <string.h>

#include "check.h"
#include "radio/radio_stats.h"

static void test_box_line(void)
{
    radio_stats_box_t s = {.sent = 9,
                           .retries = 31,
                           .acked = 2,
                           .expired = 1,
                           .relayed = 140,
                           .relay_skipped = 12,
                           .relay_cancelled = 3,
                           .relay_no_slot = 4,
                           .dup = 77,
                           .tx_refused = 5,
                           .rx = 300,
                           .rx_rejected = 6,
                           .states = 40,
                           .hellos = 8,
                           .neighbours = 4};
    char line[RADIO_STATS_LINE_MAX];
    size_t n = radio_stats_box_line(line, sizeof(line), 120, 4243, 7, &s, 359900, 0);
    CHECK(n == strlen(line) && n > 0);
    CHECK(strcmp(line,
                 "{\"t_s\":120,\"game\":4243,\"node\":7,\"sent\":9,\"retries\":31,\"acked\":2,"
                 "\"expired\":1,\"relayed\":140,\"relay_skipped\":12,\"relay_cancelled\":3,"
                 "\"relay_no_slot\":4,\"dup\":77,\"tx_refused\":5,\"duty_remaining_ms\":359900,"
                 "\"neighbours\":4,\"rx\":300,\"rx_rejected\":6,\"states\":40,\"hellos\":8,"
                 "\"final\":0}") == 0);
    CHECK(strchr(line, '\n') == NULL);
    /* The last line of a game, and a budget the shell cannot read. */
    n = radio_stats_box_line(line, sizeof(line), 5400, 4243, 7, &s, RADIO_STATS_DUTY_UNKNOWN, 1);
    CHECK(n > 0 && strstr(line, "\"duty_remaining_ms\":-1,") != NULL &&
          strstr(line, "\"final\":1}") != NULL);
}

static void test_widest_line_fits(void)
{
    radio_stats_box_t s;
    memset(&s, 0xFF, sizeof(s)); /* every counter at 4294967295 */
    char line[RADIO_STATS_LINE_MAX];
    size_t n =
        radio_stats_box_line(line, sizeof(line), 0xFFFFFFFEu, 65535, 65535, &s, 0xFFFFFFFEu, 1);
    CHECK(n > 0 && n < RADIO_STATS_LINE_MAX - 32); /* room to spare for more keys */
    radio_stats_modem_t m;
    memset(&m, 0xFF, sizeof(m));
    n = radio_stats_modem_line(line, sizeof(line), 0xFFFFFFFEu, 65535, 65535, &m, 0xFFFFFFFEu);
    CHECK(n > 0 && n < RADIO_STATS_LINE_MAX);
}

static void test_too_small_buffer(void)
{
    radio_stats_box_t s;
    memset(&s, 0, sizeof(s));
    char small[40];
    memset(small, 'x', sizeof(small));
    CHECK(radio_stats_box_line(small, sizeof(small), 1, 1, 1, &s, 1, 0) == 0);
    CHECK(small[0] == '\0'); /* an empty string, not half a line */
    CHECK(radio_stats_box_line(small, 0, 1, 1, 1, &s, 1, 0) == 0);
}

static void test_modem_line(void)
{
    radio_stats_modem_t m = {.rx_ok = 50,
                             .rx_dropped = 4,
                             .rx_auth_fail = 1,
                             .rx_dupes = 30,
                             .tx_ok = 20,
                             .tx_fail = 2,
                             .field_rx = 45,
                             .field_tx = 19};
    char line[RADIO_STATS_LINE_MAX];
    CHECK(radio_stats_modem_line(line, sizeof(line), 60, 4243, 0, &m, 300000) > 0);
    CHECK(strcmp(line,
                 "{\"role\":\"modem\",\"t_s\":60,\"game\":4243,\"node\":0,\"rx_ok\":50,"
                 "\"rx_dropped\":4,\"rx_auth_fail\":1,\"rx_dupes\":30,\"tx_ok\":20,\"tx_fail\":2,"
                 "\"field_rx\":45,\"field_tx\":19,\"duty_remaining_ms\":300000}") == 0);
}

void run_radio_stats_tests(void)
{
    test_box_line();
    test_widest_line_fits();
    test_too_small_buffer();
    test_modem_line();
}
