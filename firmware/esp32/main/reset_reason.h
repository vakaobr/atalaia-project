/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Why the box restarted, as the controller hears it: the `reason` of node.rebooted. The chip says
 * why it came up (esp_reset_reason(), mapped in reset_reason_esp.c); this file names each cause
 * in the words of the protocol (protocol/schema/events.yaml, node.rebooted) so a crash is not
 * taken for a power cut (bench, 2026-10-31: six panic restarts logged as "power").
 */
#ifndef ATALAIA_RESET_REASON_H
#define ATALAIA_RESET_REASON_H

#include <stdbool.h>

typedef enum {
    RESET_CAUSE_UNKNOWN = 0,
    RESET_CAUSE_POWER,    /* power on, or a pin reset */
    RESET_CAUSE_BROWNOUT, /* the supply dipped */
    RESET_CAUSE_SOFTWARE, /* esp_restart(): an update, the @reboot command, a CMD reboot */
    RESET_CAUSE_PANIC,    /* a crash: abort, exception, assert */
    RESET_CAUSE_WATCHDOG, /* a watchdog bit: interrupt, task or system */
    RESET_CAUSE_DEEPSLEEP,
} reset_cause_t;

/* The wire word: "power", "brownout", "software", "panic", "watchdog", "deepsleep" or "unknown".
 * Plain [a-z], so it needs no JSON escape. */
const char *reset_cause_name(reset_cause_t cause);

/* A crash the staff should hear about as one: a panic or a watchdog. */
bool reset_cause_is_crash(reset_cause_t cause);

/* What this boot's reset was (reset_reason_esp.c; the host tests set it by hand). */
reset_cause_t reset_cause_this_boot(void);

#endif /* ATALAIA_RESET_REASON_H */
