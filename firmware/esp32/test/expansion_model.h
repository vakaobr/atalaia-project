/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * THE C MODEL OF A MODULE, for the host tests of the box's port driver (expansion.c; draft RFC
 * "The expansion port", increment 6). It is a test double, not the module core: increment 7's
 * portable module core (the I2C target side) replaces it in these tests, behind the same few
 * calls (init, restart, write, read, hit, state).
 *
 * What it does, as protocol/expansion-port.md says and simulator/atalaia_sim/expansion.py's
 * ModuleModel does for the outputs:
 *   - answers IDENT, CHANNEL (after a pointer write of the register and the index) and STATUS;
 *   - takes or refuses COMMAND writes with the protocol's reasons (crc, register, length, op,
 *     range; and at that moment min_off and relay_change), setting CMD_ERROR when it refuses;
 *   - outputs on, off and patterns with their durations, the max on and min off of each
 *     channel, a relay's 100 ms, and the lease (default 1.5 s): every output off and
 *     LEASE_EXPIRED when it runs out while one is on;
 *   - inputs: a queue of EXP_MODEL_QUEUE events shown oldest first with their age until
 *     acknowledged, MORE, OVERFLOW (cleared by the STATUS read that reports it), ARM (a set;
 *     disarming drops held events of those channels), events of a disarmed channel dropped;
 *   - FRESH from a (re)start until CLEAR_FRESH.
 * Each call first runs the module's timers up to t: a duration, a max on or a lease ending at t
 * has ended, a duration or max on before the lease at the same moment.
 */
#ifndef ATALAIA_EXPANSION_MODEL_H
#define ATALAIA_EXPANSION_MODEL_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "expansion.h"

#define EXP_MODEL_QUEUE 16

typedef struct {
    uint8_t mode;
    uint32_t start;
    bool on_known;
    uint32_t on_since;
    bool end_known;
    uint32_t end;
    uint32_t on_ms, off_ms;
    uint32_t min_off_until;
    bool off_known;
    uint32_t last_off;
} exp_model_out_t;

typedef struct {
    uint8_t seq, channel, kind, value;
    uint32_t t;
} exp_model_event_t;

typedef struct {
    uint8_t addr;
    uint8_t ident[EXP_IDENT_LEN];
    uint8_t channel[EXP_CHANNELS_MAX][EXP_CHANNEL_LEN];
    exp_channel_t ch[EXP_CHANNELS_MAX];
    int channels;
    /* state */
    uint32_t t;
    exp_model_out_t out[EXP_CHANNELS_MAX];
    uint32_t lease_ms;
    bool deadline_known;
    uint32_t deadline;
    uint8_t flags; /* EXP_ST_FRESH, _LEASE_EXPIRED, _CMD_ERROR, _OVERFLOW */
    uint8_t armed;
    exp_model_event_t q[EXP_MODEL_QUEUE];
    int count;
    uint8_t next_seq;
    uint8_t reg, index; /* the register pointer */
    bool supply_ok;
    uint16_t config[EXP_CHANNELS_MAX][4];
    uint8_t locate_s;
    const char *refusal; /* why the last write was refused, NULL when taken */
    int acks, arms, outputs_taken, leases, all_offs, clear_freshes;
} exp_model_t;

/* A module at 7-bit address addr answering this IDENT frame and these CHANNEL frames (n of
 * them, by index), started (FRESH) at t = 0. */
void exp_model_init(exp_model_t *m, uint8_t addr, const uint8_t *ident,
                    const uint8_t *const *channels, int n);

/* A restart (brown-out, watchdog): every output off, inputs disarmed and dropped, FRESH. */
void exp_model_restart(exp_model_t *m, uint32_t t);

/* A write reaching the module at t (the bytes after the address byte). A pointer write (the
 * register alone, or CHANNEL's register and index) is taken quietly; anything else is a COMMAND:
 * true when taken, false when refused (CMD_ERROR, and m->refusal says why). */
bool exp_model_write(exp_model_t *m, uint32_t t, const uint8_t *data, size_t len);

/* A read at t of len bytes at the register pointer. */
void exp_model_read(exp_model_t *m, uint32_t t, uint8_t *out, size_t len);

/* An input event felt at t (kept only while the channel is armed). */
void exp_model_hit(exp_model_t *m, uint32_t t, uint8_t channel, uint8_t kind, uint8_t value);

/* The outputs bitmap and the flags a STATUS read at t would show (without clearing anything). */
void exp_model_state(exp_model_t *m, uint32_t t, uint8_t *outputs, uint8_t *flags);

#endif /* ATALAIA_EXPANSION_MODEL_H */
