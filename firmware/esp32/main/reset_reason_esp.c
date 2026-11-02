/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

#ifdef ESP_PLATFORM

#include "reset_reason.h"

#include "esp_system.h"

reset_cause_t reset_cause_this_boot(void)
{
    switch (esp_reset_reason()) {
    case ESP_RST_POWERON:
    case ESP_RST_EXT: return RESET_CAUSE_POWER;
    case ESP_RST_BROWNOUT: return RESET_CAUSE_BROWNOUT;
    case ESP_RST_SW: return RESET_CAUSE_SOFTWARE;
    case ESP_RST_PANIC: return RESET_CAUSE_PANIC;
    case ESP_RST_INT_WDT:
    case ESP_RST_TASK_WDT:
    case ESP_RST_WDT: return RESET_CAUSE_WATCHDOG;
    case ESP_RST_DEEPSLEEP: return RESET_CAUSE_DEEPSLEEP;
    default: return RESET_CAUSE_UNKNOWN;
    }
}

#endif /* ESP_PLATFORM */
