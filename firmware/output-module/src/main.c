/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The I2C output module's firmware on an RP2040 board (pico-sdk; draft RFC "The
 * expansion port", section 3 (b), increment 11; README.md, and board.h for the
 * pins). The expansion protocol, the lease and the limits are the module core's
 * (firmware/module-core/); the channel list, the guard, the watchdog's policy
 * and the supply sense are output.c's; this file is the board:
 *
 *   - the channel pins driven low before anything else (every relay off), then
 * switched only through the guard, which the core's set_output calls;
 *   - the I2C target on i2c0 (GP4 SDA, GP5 SCL) at 0x5C plus the two address
 * jumpers (GP2 and GP3, closed to GND: +1 and +2), read once at power-up; the
 * bus behind the isolator has its own pull-ups on the module's side
 * (hardware/output-module/BUILD.md); the I2C events go to the module core in
 * the I2C interrupt;
 *   - the load supply's divider on ADC0 (GP26), read every pass of the loop
 * when a channel senses it (SUPPLY_OK);
 *   - the status LED on GP14 (and a Pico's own LED): blinking while LOCATE
 * asks, fast for a fault;
 *   - the hardware watchdog (OUTPUT_WATCHDOG_MS), fed only while
 * output_watchdog_feed says so: a hung loop or a tripped guard restarts the
 * module, which comes up with every output off and FRESH, as at power-up.
 *
 * The main loop calls the module core with the I2C interrupt masked (the core
 * is not reentrant). A channel list the module refuses (a bad OUTPUT_CHANNELS
 * at build time) leaves every output off, the I2C target unstarted (the box
 * never finds the module) and the LED blinking fast.
 */
#include <stdbool.h>
#include <stdint.h>

#include "board.h"
#include "hardware/adc.h"
#include "hardware/gpio.h"
#include "hardware/i2c.h"
#include "hardware/irq.h"
#include "hardware/watchdog.h"
#include "module_core.h"
#include "output.h"
#include "pico/i2c_slave.h"
#include "pico/stdlib.h"
#include "pico/unique_id.h"

#ifndef OUTPUT_CHANNELS
#define OUTPUT_CHANNELS OUTPUT_CHANNELS_DEFAULT
#endif

#define I2C_PORT i2c0
#define I2C_HZ   100000

static const uint channel_pins[OUTPUT_MAX_CHANNELS] = {OUT_PIN_CH0, OUT_PIN_CH1, OUT_PIN_CH2,
                                                       OUT_PIN_CH3};

static mc_module_t core;
static output_i2c_t output_i2c;
static output_guard_t guard;
static output_supply_t supply;
static volatile bool supply_ok_now;

static uint32_t now_ms(void)
{
    return to_ms_since_boot(get_absolute_time());
}

/* ---- The channels
 * ---------------------------------------------------------------------------
 */

static void pins_off(void)
{
    for (uint i = 0; i < OUTPUT_MAX_CHANNELS; i++) {
        gpio_init(channel_pins[i]);
        gpio_put(channel_pins[i], false);
        gpio_set_dir(channel_pins[i], GPIO_OUT);
    }
}

static void drive(void *ctx, uint8_t channel, bool on)
{
    (void)ctx;
    if (channel < OUTPUT_MAX_CHANNELS) gpio_put(channel_pins[channel], on);
}

static void set_output(void *ctx, uint8_t channel, bool on)
{
    (void)ctx;
    output_guard_set(&guard, channel, on);
}

static bool supply_ok(void *ctx)
{
    (void)ctx;
    return supply_ok_now;
}

/* ---- The I2C target (its interrupt)
 * --------------------------------------------------------- */

static void i2c_handler(i2c_inst_t *i2c, i2c_slave_event_t event)
{
    uint32_t t = now_ms();
    switch (event) {
    case I2C_SLAVE_RECEIVE:
        output_i2c_event(&output_i2c, OUTPUT_I2C_RECEIVE, i2c_read_byte_raw(i2c), t);
        break;
    case I2C_SLAVE_REQUEST:
        i2c_write_byte_raw(i2c, output_i2c_event(&output_i2c, OUTPUT_I2C_REQUEST, 0, t));
        break;
    case I2C_SLAVE_FINISH: output_i2c_event(&output_i2c, OUTPUT_I2C_FINISH, 0, t); break;
    default: break;
    }
}

/* ---- Power-up
 * -------------------------------------------------------------------------------
 */

static uint8_t read_jumpers(void)
{
    const uint pins[2] = {OUT_PIN_JUMPER_A0, OUT_PIN_JUMPER_A1};
    uint8_t j = 0;
    for (int i = 0; i < 2; i++) {
        gpio_init(pins[i]);
        gpio_set_dir(pins[i], GPIO_IN);
        gpio_pull_up(pins[i]);
    }
    sleep_us(100);
    for (int i = 0; i < 2; i++) {
        if (!gpio_get(pins[i])) j = (uint8_t)(j | (1u << i)); /* closed: to GND */
    }
    return j;
}

static void led_init(void)
{
    gpio_init(OUT_PIN_LED);
    gpio_set_dir(OUT_PIN_LED, GPIO_OUT);
    gpio_put(OUT_PIN_LED, false);
#if defined(PICO_DEFAULT_LED_PIN) && PICO_DEFAULT_LED_PIN != OUT_PIN_LED
    gpio_init(PICO_DEFAULT_LED_PIN);
    gpio_set_dir(PICO_DEFAULT_LED_PIN, GPIO_OUT);
    gpio_put(PICO_DEFAULT_LED_PIN, false);
#endif
}

static void led_put(bool on)
{
    gpio_put(OUT_PIN_LED, on);
#if defined(PICO_DEFAULT_LED_PIN) && PICO_DEFAULT_LED_PIN != OUT_PIN_LED
    gpio_put(PICO_DEFAULT_LED_PIN, on);
#endif
}

/* A refused channel list: every output stays off, no I2C, the LED blinks fast;
 * the watchdog is never started, so nothing restarts the module into the same
 * refusal. */
static void refused(void)
{
    for (;;) {
        led_put(output_led(true, false, now_ms()));
        sleep_ms(10);
    }
}

int main(void)
{
    pins_off(); /* before anything else: every relay off */
    led_init();
    uint8_t jumpers = read_jumpers();

    pico_unique_board_id_t id;
    pico_get_unique_board_id(&id);
    mc_config_t cfg;
    const char *error = NULL;
    if (!output_config(&cfg, jumpers, OUTPUT_CHANNELS, &id.id[PICO_UNIQUE_BOARD_ID_SIZE_BYTES - 4],
                       &error)) {
        refused();
    }
    output_guard_init(&guard, &cfg, drive, NULL); /* every channel off */
    bool sensing = output_senses_supply(&cfg);
    output_supply_init(&supply);
    if (sensing) {
        adc_init();
        adc_gpio_init(OUT_PIN_SUPPLY_SENSE);
        adc_select_input(OUT_PIN_SUPPLY_SENSE - 26);
        supply_ok_now = output_supply_update(&supply, adc_read());
    }
    mc_ops_t ops = {.ctx = NULL, .set_output = set_output, .supply_ok = supply_ok};
    if (!mc_init(&core, &cfg, &ops, now_ms())) refused(); /* every output off, FRESH */

    output_i2c_init(&output_i2c, &core);
    gpio_init(OUT_PIN_SDA);
    gpio_init(OUT_PIN_SCL);
    gpio_set_function(OUT_PIN_SDA, GPIO_FUNC_I2C);
    gpio_set_function(OUT_PIN_SCL, GPIO_FUNC_I2C);
    gpio_disable_pulls(OUT_PIN_SDA); /* the module side's own pull-ups are on the isolator */
    gpio_disable_pulls(OUT_PIN_SCL);
    i2c_init(I2C_PORT, I2C_HZ);
    i2c_slave_init(I2C_PORT, cfg.address, i2c_handler);

    watchdog_enable(OUTPUT_WATCHDOG_MS, true);
    uint32_t last_tick = now_ms();
    for (;;) {
        uint32_t t = now_ms();
        if (sensing) supply_ok_now = output_supply_update(&supply, adc_read());
        irq_set_enabled(I2C0_IRQ, false);
        mc_tick(&core, t);
        last_tick = t;
        bool guard_ok = output_guard_check(&guard, t);
        bool led = output_led(!guard_ok, mc_locating(&core, t), t);
        irq_set_enabled(I2C0_IRQ, true);
        led_put(led);
        if (output_watchdog_feed(true, &guard, last_tick, now_ms())) watchdog_update();
        sleep_us(1000); /* the core's tick every millisecond */
    }
}
