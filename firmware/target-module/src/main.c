/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The target module's firmware on an RP2040 board (pico-sdk; draft RFC "The expansion port",
 * section 3 (a), increment 8; README.md for the pins). The expansion protocol is the module core's
 * (firmware/module-core/); this file is the board:
 *
 *   - the clock at 48 MHz (the port gives the module 25 mA at most), no USB stdio;
 *   - the I2C target on i2c0 (GP4 SDA, GP5 SCL, no pull-ups: the box's port board has them) at
 *     0x58 plus the two address jumpers on GP2 and GP3 (closed to GND: +1 and +2), read once at
 *     power-up; its events go to the module core in the I2C interrupt (target.c);
 *   - the piezo on ADC0 (GP26; a two-plate build adds ADC1 on GP27), sampled continuously at
 *     20 ksample/s per plate into two DMA buffers in turn; the main loop runs each full buffer
 *     through the peak detector (peak.c) with the box's CONFIG threshold and hold-off, and queues
 *     each hit with its time (mc_event; a disarmed plate's hits are dropped by the core);
 *   - the status LED on GP14 (and a Pico's own LED) blinking while LOCATE asks, off otherwise;
 *   - the watchdog (1 s): a hung loop restarts the module, which comes up FRESH, as at power-up.
 *
 * The main loop calls the module core with the I2C interrupt masked (the core is not reentrant).
 */
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "hardware/adc.h"
#include "hardware/clocks.h"
#include "hardware/dma.h"
#include "hardware/gpio.h"
#include "hardware/i2c.h"
#include "hardware/irq.h"
#include "hardware/sync.h"
#include "hardware/watchdog.h"
#include "module_core.h"
#include "peak.h"
#include "pico/i2c_slave.h"
#include "pico/stdlib.h"
#include "pico/unique_id.h"
#include "target.h"

#ifndef TARGET_PLATES
#define TARGET_PLATES TARGET_CHANNELS
#endif

#define PIN_SDA       4
#define PIN_SCL       5
#define PIN_JUMPER_A0 2
#define PIN_JUMPER_A1 3
#define PIN_LED       14
#define PIN_ADC0      26 /* ADC input 0; a second plate on 27, ADC input 1 */
#define I2C_PORT      i2c0
#define I2C_HZ        100000
#define BLOCK         (128u * TARGET_PLATES) /* samples per DMA buffer: 6.4 ms */

static mc_module_t core;
static target_i2c_t target_i2c;
static peak_t peaks[TARGET_PLATES];

static uint16_t buffers[2][BLOCK];
static int dma_chan[2];
static volatile uint32_t ready_mask;  /* bit n: buffer n is full */
static volatile uint32_t ready_ms[2]; /* when it filled */
static volatile uint32_t overruns;    /* a buffer filled again before the loop read it */

static uint32_t now_ms(void)
{
    return to_ms_since_boot(get_absolute_time());
}

/* ---- The I2C target (its interrupt) ----------------------------------------------------- */

static void i2c_handler(i2c_inst_t *i2c, i2c_slave_event_t event)
{
    uint32_t t = now_ms();
    switch (event) {
    case I2C_SLAVE_RECEIVE:
        target_i2c_event(&target_i2c, TARGET_I2C_RECEIVE, i2c_read_byte_raw(i2c), t);
        break;
    case I2C_SLAVE_REQUEST:
        i2c_write_byte_raw(i2c, target_i2c_event(&target_i2c, TARGET_I2C_REQUEST, 0, t));
        break;
    case I2C_SLAVE_FINISH: target_i2c_event(&target_i2c, TARGET_I2C_FINISH, 0, t); break;
    default: break;
    }
}

/* ---- The ADC and its DMA ------------------------------------------------------------------ */

static void dma_handler(void)
{
    for (int b = 0; b < 2; b++) {
        if (dma_channel_get_irq0_status((uint)dma_chan[b])) {
            dma_channel_acknowledge_irq0((uint)dma_chan[b]);
            /* Ready for its next turn (the other buffer is being filled now). */
            dma_channel_set_write_addr((uint)dma_chan[b], buffers[b], false);
            if (ready_mask & (1u << b)) overruns++;
            ready_ms[b] = now_ms();
            ready_mask |= 1u << b;
        }
    }
}

static void adc_start(void)
{
    adc_init();
    for (int p = 0; p < TARGET_PLATES; p++) adc_gpio_init(PIN_ADC0 + p);
    adc_select_input(0);
    if (TARGET_PLATES > 1) adc_set_round_robin((1u << TARGET_PLATES) - 1u);
    adc_fifo_setup(true, true, 1, false, false);
    /* The ADC's clock is 48 MHz whatever the system clock: one conversion every div + 1 cycles. */
    adc_set_clkdiv(48000000.0f / (float)(TARGET_SAMPLE_HZ * TARGET_PLATES) - 1.0f);
    for (int b = 0; b < 2; b++) dma_chan[b] = dma_claim_unused_channel(true);
    for (int b = 0; b < 2; b++) {
        dma_channel_config c = dma_channel_get_default_config((uint)dma_chan[b]);
        channel_config_set_transfer_data_size(&c, DMA_SIZE_16);
        channel_config_set_read_increment(&c, false);
        channel_config_set_write_increment(&c, true);
        channel_config_set_dreq(&c, DREQ_ADC);
        channel_config_set_chain_to(&c, (uint)dma_chan[1 - b]);
        dma_channel_configure((uint)dma_chan[b], &c, buffers[b], &adc_hw->fifo, BLOCK, false);
        dma_channel_set_irq0_enabled((uint)dma_chan[b], true);
    }
    irq_set_exclusive_handler(DMA_IRQ_0, dma_handler);
    irq_set_enabled(DMA_IRQ_0, true);
    dma_channel_start((uint)dma_chan[0]);
    adc_run(true);
}

/* A full buffer through the detectors: each hit queued with its time (now less its age). */
static void take_block(int b)
{
    uint32_t done = ready_ms[b];
    for (uint32_t i = 0; i < BLOCK; i++) {
        uint32_t plate = i % TARGET_PLATES;
        peak_hit_t hit;
        if (peak_sample(&peaks[plate], buffers[b][i] & 0x0FFFu, &hit)) {
            uint32_t behind = peaks[plate].samples - hit.sample; /* samples since it started */
            uint32_t rest = (BLOCK - 1u - i) / TARGET_PLATES;    /* ... and to the block's end */
            uint32_t age = (behind + rest) * 1000u / TARGET_SAMPLE_HZ;
            uint32_t t = done - age;
            irq_set_enabled(I2C0_IRQ, false);
            mc_event(&core, (uint8_t)plate, MC_EVENT_HIT, hit.strength, t);
            irq_set_enabled(I2C0_IRQ, true);
        }
    }
}

/* ---- Power-up ------------------------------------------------------------------------------- */

static uint8_t read_jumpers(void)
{
    const uint pins[2] = {PIN_JUMPER_A0, PIN_JUMPER_A1};
    uint8_t j = 0;
    for (int i = 0; i < 2; i++) {
        gpio_init(pins[i]);
        gpio_set_dir(pins[i], GPIO_IN);
        gpio_pull_up(pins[i]);
    }
    sleep_us(100);
    for (int i = 0; i < 2; i++) {
        if (!gpio_get(pins[i])) j = (uint8_t)(j | (1u << i)); /* closed: to GND */
        gpio_disable_pulls(pins[i]); /* no current through a closed jumper after this */
    }
    return j;
}

static void led_init(void)
{
    gpio_init(PIN_LED);
    gpio_set_dir(PIN_LED, GPIO_OUT);
    gpio_put(PIN_LED, false);
#if defined(PICO_DEFAULT_LED_PIN) && PICO_DEFAULT_LED_PIN != PIN_LED
    gpio_init(PICO_DEFAULT_LED_PIN);
    gpio_set_dir(PICO_DEFAULT_LED_PIN, GPIO_OUT);
    gpio_put(PICO_DEFAULT_LED_PIN, false);
#endif
}

static void led_put(bool on)
{
    gpio_put(PIN_LED, on);
#if defined(PICO_DEFAULT_LED_PIN) && PICO_DEFAULT_LED_PIN != PIN_LED
    gpio_put(PICO_DEFAULT_LED_PIN, on);
#endif
}

int main(void)
{
    /* 48 MHz from the start: the port's 25 mA (to be measured at the first build, HW2). */
    set_sys_clock_khz(48000, true);
    led_init(); /* off at power-up */
    uint8_t jumpers = read_jumpers();

    pico_unique_board_id_t id;
    pico_get_unique_board_id(&id);
    mc_config_t cfg;
    target_config(&cfg, jumpers, TARGET_PLATES, &id.id[PICO_UNIQUE_BOARD_ID_SIZE_BYTES - 4],
                  PEAK_THRESHOLD_DEFAULT, PEAK_HOLDOFF_DEFAULT_MS);
    mc_ops_t ops = {.ctx = NULL, .set_output = NULL, .supply_ok = NULL};
    mc_init(&core, &cfg, &ops, now_ms()); /* FRESH, nothing armed, no event */
    for (int p = 0; p < TARGET_PLATES; p++) {
        peak_init(&peaks[p], TARGET_SAMPLE_HZ, PEAK_THRESHOLD_DEFAULT, PEAK_HOLDOFF_DEFAULT_MS);
    }

    target_i2c_init(&target_i2c, &core);
    gpio_init(PIN_SDA);
    gpio_init(PIN_SCL);
    gpio_set_function(PIN_SDA, GPIO_FUNC_I2C);
    gpio_set_function(PIN_SCL, GPIO_FUNC_I2C);
    gpio_disable_pulls(PIN_SDA); /* the box's port board pulls the bus up (P5J-17) */
    gpio_disable_pulls(PIN_SCL);
    i2c_init(I2C_PORT, I2C_HZ);
    i2c_slave_init(I2C_PORT, cfg.address, i2c_handler);

    adc_start();
    watchdog_enable(1000, true);

    uint16_t threshold[TARGET_PLATES], holdoff[TARGET_PLATES];
    for (int p = 0; p < TARGET_PLATES; p++) {
        threshold[p] = PEAK_THRESHOLD_DEFAULT;
        holdoff[p] = PEAK_HOLDOFF_DEFAULT_MS;
    }
    for (;;) {
        watchdog_update();
        uint32_t t = now_ms();
        irq_set_enabled(I2C0_IRQ, false);
        mc_tick(&core, t);
        bool led = target_led(&core, t);
        for (int p = 0; p < TARGET_PLATES; p++) {
            uint16_t th = mc_config_value(&core, (uint8_t)p, MC_PARAM_THRESHOLD);
            uint16_t ho = mc_config_value(&core, (uint8_t)p, MC_PARAM_HOLDOFF_MS);
            if (th != threshold[p] || ho != holdoff[p]) {
                threshold[p] = th;
                holdoff[p] = ho;
                peak_config(&peaks[p], th, ho);
            }
        }
        irq_set_enabled(I2C0_IRQ, true);
        led_put(led);
        for (int b = 0; b < 2; b++) {
            if (ready_mask & (1u << b)) {
                take_block(b);
                uint32_t save = save_and_disable_interrupts();
                ready_mask &= ~(1u << b);
                restore_interrupts(save);
            }
        }
        __wfi(); /* the next DMA buffer (every 6.4 ms) or an I2C transaction */
    }
}
