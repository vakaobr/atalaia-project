/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The expansion port in the box's game (draft RFC "The expansion port", increment 8; decisions
 * EXP-10, EXP-18 to EXP-21, EXP-29, EXPI8-*): what joins the port driver (expansion.h) to the rest
 * of the box. The game task starts it at boot and ticks it every turn, and it
 *
 *   - delivers each hit of a module's hit channel to the mode's script as `hit.hit`
 *     ({"strength": 0-255}, and "channel": n, the number in the id, when the box has more than one
 *     hit channel: draft RFC 0000 Amendment 5), only while a game runs; a hit at another moment is
 *     acknowledged and dropped;
 *   - arms the hit channels the script armed (cap("hit"):arm(), cap("hit.2"):disarm(): a script
 *     call, kept by capability id, so a target plugged in during a game is armed at once) while a
 *     game runs, and disarms every one otherwise; a game that ends forgets what was armed;
 *   - adds each output channel of a module to the output layer (outputs.h) when the module is
 *     found, with the module's hint as its function and its max on, and takes the channels out
 *     when it is lost; the output layer names them (a simple output keeps its id, a module's
 *     channel with the same function becomes "<function>.2": EXPI6-15, EXPI8-5) and the driver's
 *     node.modules entry follows;
 *   - tells the controller node.module_lost ({"modules": its entry, "reason": no_answer or
 *     bad_ident}) when a module goes during a running or paused game; node.modules itself is
 *     box_game.c's (the simple outputs' and the modules' entries in one text);
 *   - logs each module found and lost, and each hit, on the box's log (the serial console).
 *
 * Platform-free: the bus is the driver's (expansion_esp.c on the ESP32, simulated modules on the
 * module core in the host box and the host tests); the shell gives the clock and the ops.
 */
#ifndef ATALAIA_EXPANSION_BOX_H
#define ATALAIA_EXPANSION_BOX_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "expansion.h"
#include "outputs.h"

#define XB_HITS_MAX 8 /* hit, hit.2 ... hit.8 */

typedef struct {
    void *ctx;
    /* An input for the mode's script: type "hit.hit", data as compact JSON (node_runner_input). */
    void (*input)(void *ctx, const char *type, const char *data_json);
    /* An event for the controller (node.module_lost), data as compact JSON; may be NULL. */
    void (*event)(void *ctx, const char *type, const char *data_json);
    void (*log)(void *ctx, const char *line); /* may be NULL */
} xb_ops_t;

typedef struct {
    expansion_t exp;
    outputs_t *outs; /* NULL: a module's output channels are not used */
    xb_ops_t ops;
    out_game_t game; /* as the last tick said */
    uint8_t armed;   /* bit n - 1: the script armed hit.n ("hit" is 1) */
    exp_out_ref_t refs[EXP_MODULES_MAX][EXP_CHANNELS_MAX];
    uint32_t hits, dropped, lost; /* counters since boot */
    uint32_t changes;             /* bumped when the modules or their ids change */
} expansion_box_t;

/* bus: the driver's; outs: the box's output layer (may be NULL). */
void expansion_box_init(expansion_box_t *xb, const exp_bus_t *bus, outputs_t *outs,
                        const xb_ops_t *ops);

/* At boot, after the outputs and before anything else on the port: every module ALL_OFF, then
 * read and added (expansion_start). */
void expansion_box_start(expansion_box_t *xb, uint32_t now_ms);

/* Every turn of the game task, after outputs_tick: the game's state and the clock. */
void expansion_box_tick(expansion_box_t *xb, out_game_t game, uint32_t now_ms);

/* A script's call to a hit capability: target "hit" or "hit.<2-8>", method "arm" or "disarm".
 * True when it was one (kept even when no module has that capability yet), false otherwise (the
 * call goes on to command_dispatch). */
bool expansion_box_command(expansion_box_t *xb, const char *target, const char *method);

/* The box has at least one hit channel (HELLO lists `hit`, capability type 10). */
bool expansion_box_has_hit(const expansion_box_t *xb);

/* The modules' node.modules entries, as expansion_modules_text. */
size_t expansion_box_modules_text(const expansion_box_t *xb, char *out, size_t cap);

/* One JSON array of the modules for a status line: address, model, fw, caps, armed, counters. */
size_t expansion_box_status_json(const expansion_box_t *xb, char *out, size_t cap);

/* The number in a hit capability id: 1 for "hit", n for "hit.<n>" (2-8), 0 otherwise. */
int expansion_box_hit_number(const char *cap);

/* An out_backend_t set for a module's output channel (ctx: an exp_out_ref_t): the output layer's
 * desired state becomes the channel's (expansion_output). */
out_result_t expansion_box_backend_set(void *ctx, const out_want_t *want, uint32_t now_ms);

#endif /* ATALAIA_EXPANSION_BOX_H */
