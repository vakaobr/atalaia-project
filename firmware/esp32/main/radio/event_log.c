/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Flash-backed append log. Uses standard file I/O so it works on both
 * ESP (LittleFS) and Linux (test build).
 */
#include "event_log.h"

#include <stdio.h>
#include <string.h>

/* ---- File helpers -------------------------------------------------------- */

static size_t file_size(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f) return 0;
    fseek(f, 0, SEEK_END);
    long sz = ftell(f);
    fclose(f);
    return sz > 0 ? (size_t)sz : 0;
}

static int write_entry(const char *path, const event_log_entry_t *entry)
{
    FILE *f = fopen(path, "ab");
    if (!f) return -1;
    event_log_entry_header_t hdr;
    hdr.seq = entry->seq;
    hdr.priority = (uint8_t)entry->priority;
    hdr.data_len = entry->data_len;
    size_t w = fwrite(&hdr, sizeof(hdr), 1, f);
    if (w != 1) {
        fclose(f);
        return -1;
    }
    if (entry->data_len > 0) {
        w = fwrite(entry->data, 1, entry->data_len, f);
        if (w != entry->data_len) {
            fclose(f);
            return -1;
        }
    }
    fclose(f);
    return 0;
}

/* ---- Public API ---------------------------------------------------------- */

int event_log_init(event_log_t *log, const char *base_path)
{
    memset(log, 0, sizeof(*log));
    snprintf(log->path, sizeof(log->path), "%s/game.bin", base_path);
    log->file_size = file_size(log->path);
    log->full = log->file_size >= EVENT_LOG_MAX_SIZE;
    return 0;
}

int event_log_append(event_log_t *log, const event_log_entry_t *entry)
{
    if (log->full) return -1;

    if (entry->priority == EVENT_LOG_TELEMETRY) {
        /* Cache telemetry entries. */
        if (log->telem_count < EVENT_LOG_TELEM_CACHE) {
            log->telem_cache[log->telem_count++] = *entry;
            return 0;
        }
        /* Cache is full: flush first. */
        event_log_flush(log);
        if (log->telem_count < EVENT_LOG_TELEM_CACHE) {
            log->telem_cache[log->telem_count++] = *entry;
            return 0;
        }
        return -1;
    }

    /* Normal and critical: write immediately. */
    int rc = write_entry(log->path, entry);
    if (rc == 0) {
        size_t entry_size = sizeof(event_log_entry_header_t) + entry->data_len;
        log->file_size += entry_size;
        if (log->file_size >= EVENT_LOG_MAX_SIZE) {
            log->full = true;
        }
    }
    return rc;
}

int event_log_flush(event_log_t *log)
{
    for (int i = 0; i < log->telem_count; i++) {
        int rc = write_entry(log->path, &log->telem_cache[i]);
        if (rc != 0) return rc;
        size_t entry_size = sizeof(event_log_entry_header_t) + log->telem_cache[i].data_len;
        log->file_size += entry_size;
        if (log->file_size >= EVENT_LOG_MAX_SIZE) {
            log->full = true;
        }
    }
    log->telem_count = 0;
    return 0;
}

int event_log_replay_from(event_log_t *log, uint16_t seq, event_log_replay_cb cb, void *user)
{
    FILE *f = fopen(log->path, "rb");
    if (!f) return 0; /* no log file yet */

    event_log_entry_header_t hdr;
    event_log_entry_t entry;
    int count = 0;
    while (fread(&hdr, sizeof(hdr), 1, f) == 1) {
        entry.seq = hdr.seq;
        entry.priority = (event_log_priority_t)hdr.priority;
        entry.data_len = hdr.data_len;
        if (hdr.data_len > 0) {
            if (fread(entry.data, 1, hdr.data_len, f) != hdr.data_len) {
                break;
            }
        }
        if (entry.seq >= seq && entry.seq > log->ack_seq) {
            cb(&entry, user);
            count++;
        }
    }
    fclose(f);
    return count;
}

void event_log_ack(event_log_t *log, uint16_t seq)
{
    if (seq > log->ack_seq) {
        log->ack_seq = seq;
    }
}

int event_log_compact(event_log_t *log)
{
    FILE *f = fopen(log->path, "rb");
    if (!f) return 0;

    /* Read all entries, keeping only unACKed ones. */
    char tmp_path[136];
    snprintf(tmp_path, sizeof(tmp_path), "%s.tmp", log->path);
    FILE *out = fopen(tmp_path, "wb");
    if (!out) {
        fclose(f);
        return -1;
    }

    event_log_entry_header_t hdr;
    size_t new_size = 0;
    while (fread(&hdr, sizeof(hdr), 1, f) == 1) {
        uint8_t data[200];
        if (hdr.data_len > 0) {
            if (fread(data, 1, hdr.data_len, f) != hdr.data_len) break;
        }
        if (hdr.seq > log->ack_seq) {
            fwrite(&hdr, sizeof(hdr), 1, out);
            if (hdr.data_len > 0) fwrite(data, 1, hdr.data_len, out);
            new_size += sizeof(hdr) + hdr.data_len;
        }
    }
    fclose(f);
    fclose(out);

    /* Replace the old file. */
    remove(log->path);
    rename(tmp_path, log->path);
    log->file_size = new_size;
    log->full = new_size >= EVENT_LOG_MAX_SIZE;
    return 0;
}

int event_log_clear(event_log_t *log)
{
    remove(log->path);
    log->file_size = 0;
    log->ack_seq = 0;
    log->telem_count = 0;
    log->full = false;
    return 0;
}
