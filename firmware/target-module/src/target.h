/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The target module (draft RFC "The expansion port", section 3 (a), increment 8): what is the
 * same on any processor. Its configuration for the module core (model 0x0001 `target`, one or two
 * hit channels, its address from two jumpers), and the I2C target's events as the RP2040's
 * pico_i2c_slave gives them (a byte received, a byte requested, the end of a transaction: a stop
 * or a repeated start) turned into the module core's four calls. main.c is the RP2040's side: the
 * pins, the ADC and its DMA, the LED, the clock and the watchdog.
 */
#ifndef ATALAIA_TARGET_MODULE_H
#define ATALAIA_TARGET_MODULE_H

#include <stdbool.h>
#include <stdint.h>

#include "module_core.h"

#define TARGET_MODEL     0x0001u
#define TARGET_HW_REV    1u
#define TARGET_FW_MAJOR  1u
#define TARGET_FW_MINOR  0u
#define TARGET_FW_PATCH  0u
#define TARGET_ADDRESS   0x58u  /* the jumpers add 0-3: 0x58-0x5B (EXP-7) */
#define TARGET_CHANNELS  1u     /* a two-plate module: 2 */
#define TARGET_SAMPLE_HZ 20000u /* per channel (RFC section 3 (a)) */
#define TARGET_LOCATE_MS 250u   /* LOCATE: the LED toggles this often */

/* The module core's configuration: address 0x58 + jumpers (0-3, bit 0 adds 1, bit 1 adds 2),
 * channels hit channels (1 or 2) starting from threshold and holdoff_ms, the processor's unique id
 * (its last four bytes). False for jumpers above 3 or channels other than 1 and 2. */
bool target_config(mc_config_t *cfg, uint8_t jumpers, uint8_t channels, const uint8_t uid[4],
                   uint16_t threshold, uint16_t holdoff_ms);

/* The I2C target's events, in the order the peripheral gives them. */
typedef enum {
    TARGET_I2C_RECEIVE = 0, /* the box wrote a byte */
    TARGET_I2C_REQUEST,     /* the box reads a byte */
    TARGET_I2C_FINISH,      /* a stop or a repeated start */
} target_i2c_event_t;

typedef struct {
    mc_module_t *core;
    uint8_t state; /* 0 idle, 1 in a write, 2 in a read */
} target_i2c_t;

void target_i2c_init(target_i2c_t *t, mc_module_t *core);

/* One event: in, the byte received (TARGET_I2C_RECEIVE); returns the byte to send
 * (TARGET_I2C_REQUEST), 0 otherwise. A read that follows a write without a FINISH between them
 * (a repeated start the peripheral did not report) ends that write first, as the core expects. */
uint8_t target_i2c_event(target_i2c_t *t, target_i2c_event_t ev, uint8_t in, uint32_t now_ms);

/* The status LED: on while LOCATE asks (toggling every TARGET_LOCATE_MS), else off. */
bool target_led(mc_module_t *core, uint32_t now_ms);

#endif /* ATALAIA_TARGET_MODULE_H */
