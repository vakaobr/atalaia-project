/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * Flash-backed append log for game events. On ESP the underlying
 * storage is LittleFS; on the test build it uses standard file I/O.
 * The log persists across reboots so unACKed events can be replayed
 * on reconnect.
 */
#ifndef ATALAIA_EVENT_LOG_H
#define ATALAIA_EVENT_LOG_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Maximum log size before overflow (256 KB). */
#define EVENT_LOG_MAX_SIZE (256U * 1024U)

/* Telemetry entries are cached and flushed periodically. */
#define EVENT_LOG_TELEM_CACHE    8
#define EVENT_LOG_TELEM_FLUSH_MS 5000

typedef enum {
    EVENT_LOG_NORMAL = 0,
    EVENT_LOG_CRITICAL,
    EVENT_LOG_TELEMETRY,
} event_log_priority_t;

/* On-disk entry header: 4 bytes. */
typedef struct {
    uint16_t seq;
    uint8_t priority;
    uint8_t data_len;
} event_log_entry_header_t;

typedef struct {
    uint16_t seq;
    event_log_priority_t priority;
    uint8_t data[200];
    uint8_t data_len;
} event_log_entry_t;

typedef void (*event_log_replay_cb)(const event_log_entry_t *entry, void *user);

typedef struct {
    char path[128];
    uint16_t ack_seq; /* entries up to this seq are ACKed */
    size_t file_size;
    bool full;

    /* Telemetry write cache. */
    event_log_entry_t telem_cache[EVENT_LOG_TELEM_CACHE];
    int telem_count;
    uint32_t telem_last_flush_ms;
} event_log_t;

/* Initialise the log. base_path is e.g. "/littlefs/log". */
int event_log_init(event_log_t *log, const char *base_path);

/* Append an entry. Critical entries are flushed immediately;
 * telemetry entries are cached and flushed every 5 seconds. */
int event_log_append(event_log_t *log, const event_log_entry_t *entry);

/* Flush the telemetry cache to disk (called periodically). */
int event_log_flush(event_log_t *log);

/* Replay entries from seq onward. cb is called for each entry. */
int event_log_replay_from(event_log_t *log, uint16_t seq, event_log_replay_cb cb, void *user);

/* Mark entries up to seq as ACKed. */
void event_log_ack(event_log_t *log, uint16_t seq);

/* Remove ACKed entries from the file, compacting it. */
int event_log_compact(event_log_t *log);

/* Delete the log file (on game end). */
int event_log_clear(event_log_t *log);

#endif /* ATALAIA_EVENT_LOG_H */
