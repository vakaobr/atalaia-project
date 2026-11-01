/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

#include "reset_reason.h"

const char *reset_cause_name(reset_cause_t cause)
{
    switch (cause) {
    case RESET_CAUSE_POWER: return "power";
    case RESET_CAUSE_BROWNOUT: return "brownout";
    case RESET_CAUSE_SOFTWARE: return "software";
    case RESET_CAUSE_PANIC: return "panic";
    case RESET_CAUSE_WATCHDOG: return "watchdog";
    case RESET_CAUSE_DEEPSLEEP: return "deepsleep";
    case RESET_CAUSE_UNKNOWN:
    default: return "unknown";
    }
}

bool reset_cause_is_crash(reset_cause_t cause)
{
    return cause == RESET_CAUSE_PANIC || cause == RESET_CAUSE_WATCHDOG;
}
