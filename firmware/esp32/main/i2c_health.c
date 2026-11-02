/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

#include "i2c_health.h"

#include <string.h>

/* now >= t, safe across the 32-bit millisecond counter wrapping. */
static bool reached(uint32_t now_ms, uint32_t t)
{
    return (int32_t)(now_ms - t) >= 0;
}

void i2c_health_init(i2c_health_t *h)
{
    memset(h, 0, sizeof(*h));
}

bool i2c_health_allow(i2c_health_t *h, uint32_t now_ms)
{
    if (!h->suspended) return true;
    if (reached(now_ms, h->retry_at_ms)) return true;
    h->skipped++;
    return false;
}

i2c_health_event_t i2c_health_report(i2c_health_t *h, uint32_t now_ms, bool ok)
{
    if (ok) {
        h->ok++;
        bool was_suspended = h->suspended;
        h->consecutive_fail = 0;
        h->suspended = false;
        h->backoff_ms = 0;
        if (was_suspended) {
            h->recoveries++;
            return I2C_HEALTH_RECOVERED;
        }
        return I2C_HEALTH_NONE;
    }

    h->errors++;
    if (h->consecutive_fail < UINT32_MAX) h->consecutive_fail++;
    if (h->suspended) {
        /* A trial failed: wait twice as long, up to the cap. */
        h->backoff_ms = h->backoff_ms >= I2C_HEALTH_BACKOFF_MAX_MS / 2 ? I2C_HEALTH_BACKOFF_MAX_MS
                                                                       : h->backoff_ms * 2;
        h->retry_at_ms = now_ms + h->backoff_ms;
        return I2C_HEALTH_STILL_DOWN;
    }
    if (h->consecutive_fail >= I2C_HEALTH_FAIL_LIMIT) {
        h->suspended = true;
        h->suspensions++;
        h->backoff_ms = I2C_HEALTH_BACKOFF_MIN_MS;
        h->retry_at_ms = now_ms + h->backoff_ms;
        return I2C_HEALTH_SUSPENDED;
    }
    return I2C_HEALTH_NONE;
}

void i2c_bus_health_init(i2c_bus_health_t *b)
{
    memset(b, 0, sizeof(*b));
}

bool i2c_bus_health_report(i2c_bus_health_t *b, uint32_t now_ms, bool ok)
{
    if (ok) {
        b->fail_run = 0;
        return false;
    }
    if (b->fail_run < UINT32_MAX) b->fail_run++;
    if (b->fail_run < I2C_BUS_RESET_FAIL_RUN) return false;
    if (b->have_reset && !reached(now_ms, b->last_reset_ms + I2C_BUS_RESET_MIN_GAP_MS)) {
        return false;
    }
    b->fail_run = 0;
    b->last_reset_ms = now_ms;
    b->have_reset = true;
    b->resets++;
    return true;
}
