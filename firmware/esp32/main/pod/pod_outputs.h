/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The I/O pod's simple outputs, lent to the phone (draft RFC "The expansion port", increment 9,
 * decision EXP-26; protocol/capability-proxy.md, "Outputs"): the box's output layer (outputs.h)
 * and its simple outputs' RMT bursts (simple_out.h) on the pod's free GPIO 33 (and 1), driven by
 * the phone's CMDs instead of a mode script.
 *
 *   id        type     events   commands (CMD args)
 *   <use>     output   -        on {"ms"}, off, pulse {"ms"}, pattern {"on_ms","off_ms","ms"}
 *
 * The id is the output's use (siren, strobe, smoke, light, horn, out.<n>; a second of the same
 * use siren.2), set in the pod's build (ATALAIA_POD_OUT<n>_FUNCTION: a pod has no admin PIN), and
 * its descriptor says "feedback": false (nothing tells the pod a switch is plugged in). Only the
 * enabled outputs are listed.
 *
 * The phone runs the game's rules (on only while the game runs, off at its start, pause, end and
 * a halted script, the end's 10 s grace: the app's prop shell); the pod keeps the output safe
 * whatever the phone does (EXP-26, EXP-29):
 *   - the output layer's own limits: the longest on of its build, a change at most every 500 ms
 *     (a shorter pulse lasts 500 ms, a faster pattern is refused, an on within 500 ms of the last
 *     off is refused), ms 1 to 600000;
 *   - outputs switch on only while a phone is on a link; when the last link goes (USB unplugged,
 *     Bluetooth lost, an EVT nobody acknowledged) every output goes off at once;
 *   - the lease: while an output is on, the phone sends a frame at least every
 *     POD_OUT_KEEPALIVE_MS (a RADIO_CMD PING when it has nothing else to say); after
 *     POD_OUT_QUIET_MS without one, every output goes off (a phone whose app hung keeps its USB
 *     link up);
 *   - the bursts: the simple output's pulses stop within 0.5 s of the pod's loop stopping, and
 *     the RC switch opens on the lost signal (EXP-32, EXP-37).
 * Off within 2 s of the link going, in every case.
 *
 * Plain C: host-tested with a fake RMT (test/test_pod_outputs.c) and run by the host pod.
 */
#ifndef ATALAIA_POD_OUTPUTS_H
#define ATALAIA_POD_OUTPUTS_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "atalaia/proxy.h"
#include "outputs.h"

#define POD_OUT_QUIET_MS     1500 /* an output on and no frame from the phone this long: off */
#define POD_OUT_KEEPALIVE_MS 500  /* how often the phone speaks while an output is on */

typedef struct {
    outputs_t out;       /* the channels: the shell adds them (simple_out_esp_init, the host pod) */
    bool linked;         /* a phone was on a link, and not silent, at the last tick */
    uint32_t commands;   /* CMDs for an output, acted on */
    uint32_t refused;    /* ... refused (bad arguments, too soon, out of the rules) */
    uint32_t link_offs;  /* every output off: the phone's link went */
    uint32_t quiet_offs; /* every output off: the phone fell silent with one on */
} pod_outputs_t;

/* ops: the output layer's log (and its events, which the pod does not send: the phone tells the
 * field output.switched itself). May be NULL. */
void pod_outputs_init(pod_outputs_t *po, const outputs_ops_t *ops);

/* True for the id of an enabled output: its CMDs go to pod_outputs_command. */
bool pod_outputs_owns(const pod_outputs_t *po, const char *cap_id);

/*
 * The enabled outputs' descriptors added to IDENT's capability array json (len bytes, "[...]",
 * NUL-terminated, in a buffer of cap): a simple output {"id":"siren","type":"output",
 * "feedback":false}, without "feedback" unless feedback; a module's output channel (the expansion
 * port, pod_port.h) {"id":"strobe","type":"output"}. Returns the new length, or 0 when they do not
 * fit (json is then unchanged).
 */
size_t pod_outputs_append(const pod_outputs_t *po, char *json, size_t len, size_t cap,
                          bool feedback);

/* A CMD for one of the outputs. False for a method an output does not have; a known method
 * with bad arguments, or one the rules refuse, is true (acted on: refused, logged, counted). */
bool pod_outputs_command(pod_outputs_t *po, const atalaia_proxy_msg_t *m);

/*
 * Every turn of the pod's loop: phone_on (pod_phone_on), when the phone last spoke
 * (pod_heard_ms) and the clock. Applies the link and lease rules and drives the bursts.
 */
void pod_outputs_tick(pod_outputs_t *po, bool phone_on, uint32_t heard_ms, uint32_t now_ms);

/* An output is on (asked for, its time not over). */
bool pod_outputs_any_on(const pod_outputs_t *po);

#endif /* ATALAIA_POD_OUTPUTS_H */
