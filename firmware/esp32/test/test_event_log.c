/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Tests for the flash-backed event log (standard file I/O backend).
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "check.h"
#include "radio/event_log.h"

/* Temporary directory for log files. */
#ifdef _WIN32
#define LOG_DIR "."
#else
#define LOG_DIR "/tmp/atalaia_event_log_test"
#endif

static void ensure_dir(void)
{
#ifndef _WIN32
    /* mkdir -p */
    (void)!system("mkdir -p " LOG_DIR);
#endif
}

static void cleanup(void)
{
    char path[256];
    snprintf(path, sizeof(path), "%s/game.bin", LOG_DIR);
    remove(path);
    snprintf(path, sizeof(path), "%s/game.bin.tmp", LOG_DIR);
    remove(path);
}

/* ---- Replay helper ------------------------------------------------------ */

#define MAX_REPLAY 32

typedef struct {
    event_log_entry_t entries[MAX_REPLAY];
    int count;
} replay_state_t;

static void replay_cb(const event_log_entry_t *entry, void *user)
{
    replay_state_t *rs = user;
    if (rs->count < MAX_REPLAY) {
        rs->entries[rs->count] = *entry;
    }
    rs->count++;
}

/* ---- Tests --------------------------------------------------------------- */

static void test_append_and_replay(void)
{
    ensure_dir();
    cleanup();

    event_log_t log;
    CHECK(event_log_init(&log, LOG_DIR) == 0);

    /* Append 3 normal entries. */
    for (uint16_t i = 1; i <= 3; i++) {
        event_log_entry_t e = {0};
        e.seq = i;
        e.priority = EVENT_LOG_NORMAL;
        e.data[0] = (uint8_t)i;
        e.data_len = 1;
        CHECK(event_log_append(&log, &e) == 0);
    }

    /* Replay from seq 1. */
    replay_state_t rs = {.count = 0};
    int replayed = event_log_replay_from(&log, 1, replay_cb, &rs);
    CHECK(replayed == 3);
    CHECK(rs.count == 3);
    CHECK(rs.entries[0].seq == 1);
    CHECK(rs.entries[1].seq == 2);
    CHECK(rs.entries[2].seq == 3);
    CHECK(rs.entries[0].data[0] == 1);

    /* Replay from seq 2 skips entry 1. */
    rs.count = 0;
    replayed = event_log_replay_from(&log, 2, replay_cb, &rs);
    CHECK(replayed == 2);
    CHECK(rs.entries[0].seq == 2);

    cleanup();
}

static void test_compact(void)
{
    ensure_dir();
    cleanup();

    event_log_t log;
    event_log_init(&log, LOG_DIR);

    for (uint16_t i = 1; i <= 5; i++) {
        event_log_entry_t e = {0};
        e.seq = i;
        e.priority = EVENT_LOG_NORMAL;
        e.data_len = 0;
        event_log_append(&log, &e);
    }

    /* ACK first 3 and compact. */
    event_log_ack(&log, 3);
    CHECK(event_log_compact(&log) == 0);

    /* Only entries 4 and 5 remain. */
    replay_state_t rs = {.count = 0};
    event_log_replay_from(&log, 1, replay_cb, &rs);
    CHECK(rs.count == 2);
    CHECK(rs.entries[0].seq == 4);
    CHECK(rs.entries[1].seq == 5);

    cleanup();
}

static void test_critical_flush(void)
{
    ensure_dir();
    cleanup();

    event_log_t log;
    event_log_init(&log, LOG_DIR);

    /* Critical entry should be written to file immediately. */
    event_log_entry_t e = {0};
    e.seq = 1;
    e.priority = EVENT_LOG_CRITICAL;
    e.data[0] = 0xAB;
    e.data_len = 1;
    CHECK(event_log_append(&log, &e) == 0);

    /* The file should be non-empty. */
    CHECK(log.file_size > 0);

    /* Re-open and replay to verify persistence. */
    event_log_t log2;
    event_log_init(&log2, LOG_DIR);
    replay_state_t rs = {.count = 0};
    event_log_replay_from(&log2, 1, replay_cb, &rs);
    CHECK(rs.count == 1);
    CHECK(rs.entries[0].seq == 1);
    CHECK(rs.entries[0].data[0] == 0xAB);

    cleanup();
}

static void test_telemetry_cache(void)
{
    ensure_dir();
    cleanup();

    event_log_t log;
    event_log_init(&log, LOG_DIR);

    /* Telemetry entries are cached, not written immediately. */
    for (uint16_t i = 1; i <= 4; i++) {
        event_log_entry_t e = {0};
        e.seq = i;
        e.priority = EVENT_LOG_TELEMETRY;
        e.data_len = 0;
        CHECK(event_log_append(&log, &e) == 0);
    }
    CHECK(log.telem_count == 4);
    CHECK(log.file_size == 0); /* nothing on disk yet */

    /* Flush writes them. */
    CHECK(event_log_flush(&log) == 0);
    CHECK(log.telem_count == 0);
    CHECK(log.file_size > 0);

    /* Replay sees them. */
    replay_state_t rs = {.count = 0};
    event_log_replay_from(&log, 1, replay_cb, &rs);
    CHECK(rs.count == 4);

    cleanup();
}

static void test_overflow(void)
{
    ensure_dir();
    cleanup();

    event_log_t log;
    event_log_init(&log, LOG_DIR);

    /* Write entries until we exceed the limit. */
    event_log_entry_t e = {0};
    e.priority = EVENT_LOG_NORMAL;
    memset(e.data, 0xCC, sizeof(e.data));
    e.data_len = 200;

    int count = 0;
    for (uint16_t seq = 1; seq < 2000; seq++) {
        e.seq = seq;
        if (event_log_append(&log, &e) != 0) break;
        count++;
    }
    CHECK(log.full);
    /* Verify we wrote roughly 256KB / (4+200) = ~1260 entries. */
    CHECK(count > 1000 && count < 1400);

    cleanup();
}

static void test_clear(void)
{
    ensure_dir();
    cleanup();

    event_log_t log;
    event_log_init(&log, LOG_DIR);

    event_log_entry_t e = {0};
    e.seq = 1;
    e.priority = EVENT_LOG_NORMAL;
    e.data_len = 0;
    event_log_append(&log, &e);

    CHECK(event_log_clear(&log) == 0);
    CHECK(log.file_size == 0);
    CHECK(!log.full);

    /* Replay is empty. */
    replay_state_t rs = {.count = 0};
    event_log_replay_from(&log, 1, replay_cb, &rs);
    CHECK(rs.count == 0);

    cleanup();
}

void run_event_log_tests(void)
{
    test_append_and_replay();
    test_compact();
    test_critical_flush();
    test_telemetry_cache();
    test_overflow();
    test_clear();
}
