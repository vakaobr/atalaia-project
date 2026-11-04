/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * A simulated module for the box's side of the expansion port: the real module core
 * (firmware/module-core/, draft RFC "The expansion port", increment 7) behind a fake I2C bus. The
 * port driver's host tests (test_expansion.c, test_expansion_box.c) and the host box's --module
 * (box_host/) use it; it replaced increment 6's C model of a module (decisions EXPI6-16, EXPI7-19,
 * EXPI8-3).
 *
 * Every write and read goes through the core's own I2C calls (mc_write, mc_read), so STATUS,
 * COMMAND, the event queue, the lease and the limits are the core's. Two things are the
 * simulation's:
 *   - the IDENT and CHANNEL frames a read answers are kept here as bytes, made by the core from
 *     the module's configuration, so a test can spoil them (a bad magic, a channel without its
 *     max on) as a faulty module's firmware would, which the core itself never sends;
 *   - counters of the COMMANDs the core took, by op, for the tests.
 */
#ifndef ATALAIA_MODULE_SIM_H
#define ATALAIA_MODULE_SIM_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "module_core.h"

typedef struct {
    mc_module_t core;
    mc_config_t cfg;
    bool ok; /* the core took the configuration */
    /* What the box reads at IDENT and CHANNEL (a test may change them). */
    uint8_t ident[MC_IDENT_LEN];
    uint8_t channel[MC_MAX_CHANNELS][MC_CHANNEL_LEN];
    uint8_t pointer, pointer_index; /* the register the next read answers, as the box set it */
    uint8_t outputs;                /* the outputs' levels as the core last switched them */
    const char *refusal;            /* why the last COMMAND was refused, NULL when taken */
    int acks, arms, outputs_taken, leases, all_offs, clear_freshes, locates, configs;
} module_sim_t;

/* A module with this configuration, started (FRESH) at now_ms. False when the core refuses it. */
bool module_sim_init(module_sim_t *m, const mc_config_t *cfg, uint32_t now_ms);

/* A module answering these IDENT and CHANNEL frames (n of them, by index), as the shared vectors'
 * reference modules give them, at 7-bit address addr, started at 0. False when the frames do not
 * make a configuration the core takes. */
bool module_sim_from_frames(module_sim_t *m, uint8_t addr, const uint8_t *ident,
                            const uint8_t *const *channels, int n);

/* The protocol's reference modules by name: "target" (one hit channel, model 0x0001) or "out4"
 * (model 0x0002: four relay outputs, siren, strobe, smoke and a generic one), at addr (0: the
 * model's default, 0x58 or 0x5C). False for another name or an address outside 0x58-0x5F. */
bool module_sim_named(module_sim_t *m, const char *name, uint8_t addr, uint32_t now_ms);

/* A restart (brown-out, watchdog): mc_init again. */
void module_sim_restart(module_sim_t *m, uint32_t now_ms);

/* A write reaching the module (the bytes after the address byte). A register pointer write is
 * taken quietly; anything else is a COMMAND: true when taken, false when refused (m->refusal). */
bool module_sim_write(module_sim_t *m, uint32_t now_ms, const uint8_t *data, size_t len);

/* A read of len bytes at the register pointer. */
void module_sim_read(module_sim_t *m, uint32_t now_ms, uint8_t *out, size_t len);

/* An input event felt at now_ms (kept only while the channel is armed). */
bool module_sim_hit(module_sim_t *m, uint32_t now_ms, uint8_t channel, uint8_t kind, uint8_t value);

/* The outputs bitmap and the flags a STATUS read at now_ms would show (nothing cleared). */
void module_sim_state(module_sim_t *m, uint32_t now_ms, uint8_t *outputs, uint8_t *flags);

/* The armed channels, and the events the module holds. */
uint8_t module_sim_armed(const module_sim_t *m);
int module_sim_queued(const module_sim_t *m);

#endif /* ATALAIA_MODULE_SIM_H */
