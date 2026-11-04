/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The I/O pod's expansion port, lent to the phone (draft RFC "The expansion port", increment 9,
 * the port half; decision EXP-26; protocol/capability-proxy.md, "The pod's expansion port"): the
 * box's port driver (expansion.h) and its game-side glue (expansion_box.h) on the pod's I2C bus,
 * with the phone in the game's place.
 *
 *   id        type     events (EVT)                          commands (CMD)
 *   hit       hit      hit {"strength"} (+ "channel" with    arm, disarm
 *   hit.2 ...          two hit channels)
 *   <use>     output   -                                     on {"ms"}, off, pulse {"ms"},
 *                                                            pattern {"on_ms","off_ms","ms"}
 *   pod       -        modules {"modules", "max_on_s",       -
 *                      "withheld"},
 *                      module_lost {"modules", "reason"}
 *
 * A module's hit channels are lent as `hit`, `hit.2` (EXPI6-15): their hits go to the phone as
 * EVTs while a phone is on a link, and only the channels the phone armed (CMD arm) report them;
 * when the last link goes every channel is disarmed and the arming forgotten (the phone arms
 * again when it links again). A module's output channels join the pod's output layer
 * (pod_outputs.h, beside the simple outputs) and are lent as `output` without the "feedback"
 * flag, but only on a pod built to lend them (CONFIG_ATALAIA_POD_MODULE_OUTPUTS: a pod has no
 * admin PIN, so building it in is the person at the pod enabling them, EXP-28), each at most the
 * build's longest on and the module's own. The pod holds the module's lease: its driver refreshes
 * it while an output should be on, and the output layer turns every output off when the phone's
 * link goes or falls silent, so a module's outputs are off within 1.5 s of that whatever happens
 * to the pod (EXP-11, EXP-26).
 *
 * What the field learns (EXP-21, decision EXPI9-19): after every IDENT, and whenever the modules
 * or the lent outputs change, the pod sends the EVT "pod" "modules" with the node.modules text a
 * box would send (protocol/expansion-port.md, section 7: its enabled simple outputs
 * "g33:servo:siren", then its modules "58:target/1.0.0:hit") and each lent output's longest on in
 * seconds ({"siren": 30}); the phone passes the text on to the controller as node.modules and
 * takes the longest ons for its own model. A pod with an output fitted adds "withheld", the
 * outputs fitted that it does not lend (pod_port_withheld_text; "" when it lends every one), which
 * the phone tells the controller as node.outputs_disabled, so the console shows them as a box's
 * outputs fitted but not enabled (decision PROPC-6). A module that stops answering while a phone is
 * on a link is the EVT "pod" "module_lost" ({"modules": its entry, "reason"}), which the phone
 * tells the controller as node.module_lost during a game. A change of the lent capabilities sends
 * IDENT again first (ops.ident_changed). An older phone drops these EVTs: they name no capability
 * of IDENT.
 *
 * Without a bus (a pod built without the port, or one whose bus did not install) only the simple
 * outputs are told.
 *
 * Plain C: host-tested on the module core behind a fake bus (test/test_pod.c) and run by the
 * host pod (test/pod_host, --module).
 */
#ifndef ATALAIA_POD_PORT_H
#define ATALAIA_POD_PORT_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "atalaia/proxy.h"
#include "expansion_box.h"
#include "pod.h"
#include "pod_caps.h"
#include "pod_outputs.h"

#define POD_PORT_TEXT_MAX OUT_MODULES_MAX /* node.modules' text: 100 bytes */

typedef struct {
    bool module_outputs; /* lend a module's output channels (CONFIG_ATALAIA_POD_MODULE_OUTPUTS) */
    uint32_t module_max_on_s; /* their longest on (1-600; the module's own when lower) */
} pod_port_config_t;

typedef struct {
    void *ctx;
    /* An EVT to the phone (pod_event). */
    pod_emit_fn emit;
    /* The capabilities IDENT lends changed (a module found or lost, an output renamed): send
     * IDENT again on every active link. May be NULL. */
    void (*ident_changed)(void *ctx);
    void (*log)(void *ctx, const char *line); /* may be NULL */
} pod_port_ops_t;

typedef struct {
    expansion_box_t xb;
    bool on; /* the port's bus is there: the driver runs */
    pod_outputs_t *po;
    pod_port_config_t cfg;
    pod_port_ops_t ops;
    bool phone;   /* a phone was on a link at the last tick */
    bool tell;    /* an IDENT went out: the modules EVT follows at the next tick */
    bool told;    /* the modules EVT went out since the phone linked */
    bool said;    /* a modules EVT with something in it went out since boot */
    int listing;  /* the outputs the last pod_port_ident_caps listed (a proposal: ident_sent) */
    bool trimmed; /* the last IDENT sent left outputs out: a channel found since waits for one */
    char told_text[POD_PORT_TEXT_MAX + 1];
    char told_max[96];
    bool told_has_withheld; /* the last modules EVT carried "withheld" */
    char told_withheld[POD_PORT_TEXT_MAX + 1];
    uint32_t hits, module_lost; /* sent to the phone */
} pod_port_t;

/* bus: the pod's I2C bus (NULL: no port; only the simple outputs are told). po: the pod's
 * outputs, whose output layer takes a module's output channels. */
void pod_port_init(pod_port_t *pp, const exp_bus_t *bus, pod_outputs_t *po,
                   const pod_port_config_t *cfg, const pod_port_ops_t *ops);

/* At boot, after the outputs: every module ALL_OFF, then read and added. */
void pod_port_start(pod_port_t *pp, uint32_t now_ms);

/* Every turn of the pod's loop, after pod_outputs_tick: phone_on (pod_phone_on) and the clock.
 * Hot-plug, polls, hits to the phone, arming, the modules' lease, and the modules EVT. */
void pod_port_tick(pod_port_t *pp, bool phone_on, uint32_t now_ms);

/* True for a hit capability id while the port runs ("hit", "hit.2" ...): its CMDs go to
 * pod_port_command (kept even before a module has it, as a box keeps a script's arming). */
bool pod_port_owns(const pod_port_t *pp, const char *cap_id);

/* CMD arm or disarm for a hit capability. False for another method. */
bool pod_port_command(pod_port_t *pp, const atalaia_proxy_msg_t *m);

/*
 * IDENT's capability array for this pod (the io's ident callback): the parts (pod_caps), then the
 * port's hit sensors, then the outputs (the simple outputs, then a module's), leaving out what
 * the level says (pod_ident_level_t): from POD_IDENT_COMPACT the buttons' colours, the outputs'
 * "feedback" flags and the hit sensors' "channel"; at POD_IDENT_TRIM the last `trim` outputs; at
 * POD_IDENT_NO_PORT every output and the hit sensors. Returns how many outputs it lists. Changes
 * no output (pod_port_ident_sent does); marks the modules EVT due (it follows every IDENT).
 * Writes "[]" when nothing fits.
 */
int pod_port_ident_caps(pod_port_t *pp, const pod_caps_t *caps, pod_ident_level_t level, int trim,
                        char *out, size_t cap);

/*
 * The IDENT that went out (the io's ident_sent): the last pod_port_ident_caps' outputs are lent,
 * the others withheld (decision EXPI9-27): turned off if on, refused (pod_outputs_owns is false,
 * the output layer refuses them as disabled) and left out of the modules EVT, until an IDENT
 * lists them again. At POD_IDENT_LEVELS (sent without capabilities) every output is withheld.
 * Logs the ones left out.
 */
void pod_port_ident_sent(pod_port_t *pp, pod_ident_level_t level);

/* node.modules' text as a box makes it: the enabled simple outputs, then the modules' entries,
 * whole entries only, at most POD_PORT_TEXT_MAX bytes; a withheld output is left out (a module
 * whose channels are all withheld too). Its length. */
size_t pod_port_modules_text(const pod_port_t *pp, char *out, size_t cap);

/* node.outputs_disabled's text as a box makes it (decisions EXPL-20, PROPC-6, PROPC-7): the
 * simple outputs not lent, then per module its output channels not lent, in its node.modules form
 * with only those ids ("g33:servo:siren;5c:out4/1.0.0:strobe,out.4"): withheld from IDENT for want
 * of room (pod_port_ident_sent), or a module's channel on a pod not built to lend them. Whole
 * entries only, at most POD_PORT_TEXT_MAX bytes; its length, 0 when every output fitted is lent
 * (or the pod has none). */
size_t pod_port_withheld_text(const pod_port_t *pp, char *out, size_t cap);

/* The lent outputs' longest on, {"siren":30,"strobe.2":10} ("{}" for none; a withheld output is
 * not lent). Its length, 0 when it does not fit. */
size_t pod_port_max_on_json(const pod_port_t *pp, char *out, size_t cap);

/* One JSON array of the port's modules, as a box's @modules ("[]" without the port). */
size_t pod_port_status_json(const pod_port_t *pp, char *out, size_t cap);

#endif /* ATALAIA_POD_PORT_H */
