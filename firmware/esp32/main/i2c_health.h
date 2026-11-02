/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Error counting and back-off for the shared I2C bus (hal/esp/hal_esp_i2c.c). Pure logic, no
 * ESP-IDF, so the host tests cover it.
 *
 * A bad solder joint, a loose connector or a noisy bus must never take the box down (bench,
 * 2026-10-31: a keypad with bad joints rebooted board 5 six times in three minutes). Each device
 * on the bus has a health record: after I2C_HEALTH_FAIL_LIMIT failed transactions in a row the
 * device is "suspended" and the driver skips it (the caller gets a quick failure and the box
 * carries on without its keypad, OLED, NFC reader or gauge); a trial transaction is allowed
 * after a back-off that doubles up to I2C_HEALTH_BACKOFF_MAX_MS, and the first success brings the
 * device back. The bus as a whole counts failures of every device: a run of them asks for a bus
 * reset (clock out stuck slaves, reset the controller), not more often than
 * I2C_BUS_RESET_MIN_GAP_MS.
 */
#ifndef ATALAIA_I2C_HEALTH_H
#define ATALAIA_I2C_HEALTH_H

#include <stdbool.h>
#include <stdint.h>

/* Consecutive failures that suspend a device. */
#define I2C_HEALTH_FAIL_LIMIT 3
/* First and longest wait before a suspended device gets a trial transaction. */
#define I2C_HEALTH_BACKOFF_MIN_MS 500u
#define I2C_HEALTH_BACKOFF_MAX_MS 30000u
/* Consecutive failures on the bus (any device) that ask for a bus reset, and the least time
 * between two resets. */
#define I2C_BUS_RESET_FAIL_RUN   3
#define I2C_BUS_RESET_MIN_GAP_MS 1000u

typedef enum {
    I2C_HEALTH_NONE = 0,   /* nothing changed */
    I2C_HEALTH_SUSPENDED,  /* the failure that suspended the device (log it once) */
    I2C_HEALTH_STILL_DOWN, /* a trial failed: back-off doubled */
    I2C_HEALTH_RECOVERED,  /* the first success after a suspension */
} i2c_health_event_t;

typedef struct {
    uint32_t consecutive_fail;
    bool suspended;
    uint32_t backoff_ms; /* the wait that applies now (when suspended) */
    uint32_t retry_at_ms;
    /* Counters since boot. */
    uint32_t ok;
    uint32_t errors;
    uint32_t skipped; /* transactions not tried while suspended */
    uint32_t suspensions;
    uint32_t recoveries;
} i2c_health_t;

typedef struct {
    uint32_t fail_run; /* consecutive failures, any device */
    uint32_t last_reset_ms;
    bool have_reset;
    uint32_t resets;
} i2c_bus_health_t;

void i2c_health_init(i2c_health_t *h);

/* May a transaction be tried now? False while suspended and the back-off has not passed (and
 * the skip is counted). The caller that gets true while suspended makes the one trial. */
bool i2c_health_allow(i2c_health_t *h, uint32_t now_ms);

/* The outcome of a tried transaction. */
i2c_health_event_t i2c_health_report(i2c_health_t *h, uint32_t now_ms, bool ok);

void i2c_bus_health_init(i2c_bus_health_t *b);

/* One tried transaction's outcome, on the bus. True when the bus should be reset now. */
bool i2c_bus_health_report(i2c_bus_health_t *b, uint32_t now_ms, bool ok);

#endif /* ATALAIA_I2C_HEALTH_H */
