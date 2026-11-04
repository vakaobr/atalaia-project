/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The I2C output module (draft RFC "The expansion port", section 3 (b),
 * increment 11): what is the same on any processor. main.c is the RP2040's side
 * (the pins, the I2C target peripheral, the ADC, the clock and the hardware
 * watchdog); everything here is portable C with host tests.
 *
 *   - Its configuration for the module core (model 0x0002 `out4`, 1-4 output
 * channels, its address 0x5C plus two jumpers), from a channel list the builder
 * sets at build time (OUTPUT_CHANNELS: what is fitted on each channel, relay or
 * solid-state, its hint, max on and min off).
 *   - The I2C target's events as the RP2040's pico_i2c_slave gives them, turned
 * into the module core's four calls.
 *   - The guard: a second, independent max on under the core's. Every level the
 * core switches goes through it; a channel on longer than its max on plus
 * OUTPUT_GUARD_SLACK_MS (which the core never allows) trips it: every channel
 * off, latched until the module restarts.
 *   - The watchdog's policy: the hardware watchdog is fed only while the main
 * loop runs the core's timers on time and the guard has not tripped; otherwise
 * the module restarts, and comes back with every output off and FRESH, as at
 * power-up.
 *   - The load supply's sense (SUPPLY_OK), from a resistor divider into an ADC
 * pin, with hysteresis.
 *   - The status LED.
 */
#ifndef ATALAIA_OUTPUT_MODULE_H
#define ATALAIA_OUTPUT_MODULE_H

#include <stdbool.h>
#include <stdint.h>

#include "module_core.h"

#define OUTPUT_MODEL        0x0002u /* `out4` (protocol/expansion-port.md, section 2) */
#define OUTPUT_HW_REV       1u
#define OUTPUT_FW_MAJOR     1u
#define OUTPUT_FW_MINOR     0u
#define OUTPUT_FW_PATCH     0u
#define OUTPUT_ADDRESS      0x5Cu /* the jumpers add 0-3: 0x5C-0x5F (EXP-7) */
#define OUTPUT_MAX_CHANNELS 4u    /* GP6-GP9 (board.h) */

/* The channel list a build takes when the builder sets none: four relay
 * channels, generic, at most 30 s on (the box's own default max on,
 * OUT_MAX_ON_DEFAULT_S), no min off, no supply sense. */
#define OUTPUT_CHANNELS_DEFAULT                                                                    \
    "relay:generic:30:0,relay:generic:30:0,"                                                       \
    "relay:generic:30:0,relay:generic:30:0"

/* The guard trips this long after a channel's max on (the core ends it at the
 * max on; its tick runs at least every 10 ms, so only a fault in the core or
 * its memory can come this far). */
#define OUTPUT_GUARD_SLACK_MS 500u

/* The hardware watchdog's timeout, and how late the core's last tick may be
 * before the policy stops feeding it (the core asks for a tick at least every
 * 10 ms). */
#define OUTPUT_WATCHDOG_MS  500u
#define OUTPUT_TICK_LATE_MS 50u

/* The supply sense: a divider of OUTPUT_SENSE_TOP_OHM over
 * OUTPUT_SENSE_BOTTOM_OHM from the sensed supply into a 12-bit ADC whose full
 * scale is OUTPUT_ADC_FULL_MV. SUPPLY_OK from OUTPUT_SUPPLY_ON_MV up (the
 * bottom of the module's 9-15 V input, RFC section 3 (b)), lost below
 * OUTPUT_SUPPLY_OFF_MV.
 */
#define OUTPUT_SENSE_TOP_OHM    100000u
#define OUTPUT_SENSE_BOTTOM_OHM 22000u
#define OUTPUT_ADC_FULL_MV      3300u
#define OUTPUT_SUPPLY_ON_MV     9000u
#define OUTPUT_SUPPLY_OFF_MV    8500u

/* The status LED: LOCATE blinks it every OUTPUT_LOCATE_MS, a fault every
 * OUTPUT_FAULT_MS. */
#define OUTPUT_LOCATE_MS 250u
#define OUTPUT_FAULT_MS  100u

/* ---- Configuration
 * -------------------------------------------------------------------------- */

/* The channel list: 1 to 4 entries joined by ",", each
 * "type:hint:max_on:min_off" or "type:hint:max_on:min_off:sense", with no
 * spaces:
 *
 *   type     relay (contacts: switching no faster than every 100 ms, patterns
 * from 100 ms) or solid (a MOSFET: patterns from 10 ms) hint     generic,
 * siren, strobe, smoke, light or horn (what the builder fitted) max_on   the
 * module's own hard limit in seconds, 1-255 min_off  the least seconds off
 * after the max on was reached, 0-255 sense    this channel's load supply is
 * the one the divider senses (SUPPLY_OK)
 *
 * Fills channels[0..*count-1] and returns true; false (with *error naming what
 * is wrong, and nothing promised in channels) for anything else. */
bool output_parse_channels(const char *spec, mc_channel_t channels[OUTPUT_MAX_CHANNELS],
                           uint8_t *count, const char **error);

/* The module core's configuration: address 0x5C + jumpers (0-3: bit 0 adds 1,
 * bit 1 adds 2), the channels of spec, the processor's unique id (its last four
 * bytes). False, with *error set, for jumpers above 3 or a spec
 * output_parse_channels refuses. */
bool output_config(mc_config_t *cfg, uint8_t jumpers, const char *spec, const uint8_t uid[4],
                   const char **error);

/* True when a channel of cfg senses the supply (the firmware then reads the
 * divider's ADC pin). */
bool output_senses_supply(const mc_config_t *cfg);

/* ---- The I2C target
 * ------------------------------------------------------------------------- */

typedef enum {
    OUTPUT_I2C_RECEIVE = 0, /* the box wrote a byte */
    OUTPUT_I2C_REQUEST,     /* the box reads a byte */
    OUTPUT_I2C_FINISH,      /* a stop or a repeated start */
} output_i2c_event_t;

typedef struct {
    mc_module_t *core;
    uint8_t state; /* 0 idle, 1 in a write, 2 in a read */
} output_i2c_t;

void output_i2c_init(output_i2c_t *t, mc_module_t *core);

/* One event: in, the byte received (OUTPUT_I2C_RECEIVE); returns the byte to
 * send (OUTPUT_I2C_REQUEST), 0 otherwise. A read that follows a write without a
 * FINISH between them (a repeated start the peripheral did not report) ends
 * that write first, as the core expects. */
uint8_t output_i2c_event(output_i2c_t *t, output_i2c_event_t ev, uint8_t in, uint32_t now_ms);

/* ---- The guard
 * ------------------------------------------------------------------------------
 */

typedef struct {
    void *ctx;
    void (*drive)(void *ctx, uint8_t channel, bool on); /* the pin itself */
    uint8_t count;
    uint32_t limit_ms[OUTPUT_MAX_CHANNELS]; /* max on + OUTPUT_GUARD_SLACK_MS */
    uint8_t level;                          /* bit n: channel n is driven on */
    uint8_t timed;                          /* bit n: since[n] holds when it turned on */
    uint32_t since[OUTPUT_MAX_CHANNELS];
    bool tripped;
} output_guard_t;

/* Takes each channel's max on from cfg and drives every pin off (all
 * OUTPUT_MAX_CHANNELS of them, fitted or not). */
void output_guard_init(output_guard_t *g, const mc_config_t *cfg,
                       void (*drive)(void *ctx, uint8_t channel, bool on), void *ctx);

/* What the core's set_output calls (it has no clock: output_guard_check times
 * each on). Once the guard has tripped, every channel stays off whatever the
 * core asks. */
void output_guard_set(output_guard_t *g, uint8_t channel, bool on);

/* Every pass of the main loop: false, and every channel driven off for good,
 * when a channel has been on for longer than its limit (or the guard had
 * already tripped). */
bool output_guard_check(output_guard_t *g, uint32_t now_ms);

uint8_t output_guard_levels(const output_guard_t *g); /* bit n: channel n is driven on */
bool output_guard_tripped(const output_guard_t *g);

/* ---- The watchdog's policy
 * ------------------------------------------------------------------ */

/* Whether the main loop feeds the hardware watchdog now: the module's
 * configuration was valid, the guard has not tripped, and the core's last tick
 * (at last_tick_ms) is at most OUTPUT_TICK_LATE_MS old. When this says no, the
 * watchdog restarts the module within OUTPUT_WATCHDOG_MS. */
bool output_watchdog_feed(bool config_ok, const output_guard_t *g, uint32_t last_tick_ms,
                          uint32_t now_ms);

/* ---- The supply sense
 * ----------------------------------------------------------------------- */

typedef struct {
    bool primed;
    bool ok;
    uint32_t filtered_mv;
} output_supply_t;

void output_supply_init(output_supply_t *s);

/* A 12-bit ADC reading of the divider, in millivolts at the supply's terminal.
 */
uint32_t output_supply_mv(uint16_t raw);

/* One reading (at least every few ms): filtered (an eighth of each new
 * reading), then SUPPLY_OK from OUTPUT_SUPPLY_ON_MV up, lost below
 * OUTPUT_SUPPLY_OFF_MV. Returns the new state. */
bool output_supply_update(output_supply_t *s, uint16_t raw);

/* ---- The status LED
 * ------------------------------------------------------------------------- */

/* fault (a refused configuration or a tripped guard): blinking every
 * OUTPUT_FAULT_MS; LOCATE: every OUTPUT_LOCATE_MS; else off. */
bool output_led(bool fault, bool locating, uint32_t now_ms);

#endif /* ATALAIA_OUTPUT_MODULE_H */
