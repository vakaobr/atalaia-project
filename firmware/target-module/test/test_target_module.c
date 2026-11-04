/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Host tests of the target module's portable parts (draft RFC "The expansion port", increment
 * 8): the peak detector on made-up plates (a hit, its strength, a ringing plate's hold-off, the
 * box's CONFIG), the module's configuration and address jumpers, and the I2C target's events
 * (as the RP2040's pico_i2c_slave gives them) driving the module core through a box's reads and
 * writes: IDENT, ARM, a hit in STATUS, ACK, CONFIG, LOCATE and the LED.
 */
#include <stdio.h>
#include <string.h>

#include "module_core.h"
#include "peak.h"
#include "target.h"

static int failures, checks;

#define CHECK(cond)                                                                                \
    do {                                                                                           \
        checks++;                                                                                  \
        if (!(cond)) {                                                                             \
            fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);                        \
            failures++;                                                                            \
        }                                                                                          \
    } while (0)

/* ---- The peak detector ---------------------------------------------------------------------- */

static peak_hit_t hits[16];
static int hit_count;

static void found(void *ctx, const peak_hit_t *h)
{
    (void)ctx;
    if (hit_count < 16) hits[hit_count++] = *h;
}

/* A plate struck at sample `at`: a sharp rise to `peak`, then a ringing that decays over
 * `ring_ms` (every other 0.5 ms above half of what is left). */
static void strike(uint16_t *buf, size_t n, size_t at, uint16_t peak, uint32_t ring_ms)
{
    for (size_t i = at; i < n && i < at + 4; i++) buf[i] = (uint16_t)(peak * (i - at + 1) / 4);
    size_t ring = (size_t)ring_ms * 20u;
    for (size_t i = at + 4; i < n && i < at + 4 + ring; i++) {
        uint32_t left = (uint32_t)peak * (uint32_t)(at + 4 + ring - i) / (uint32_t)ring;
        buf[i] = ((i / 10) % 2 == 0) ? (uint16_t)(left / 2) : 20;
    }
}

static uint16_t plate[20000]; /* one second at 20 ksample/s */

static void test_peak(void)
{
    peak_t p;
    /* Quiet: nothing. */
    memset(plate, 0, sizeof(plate));
    for (size_t i = 0; i < 20000; i++) plate[i] = (uint16_t)(30 + (i % 7));
    peak_init(&p, 20000, PEAK_THRESHOLD_DEFAULT, PEAK_HOLDOFF_DEFAULT_MS);
    hit_count = 0;
    CHECK(peak_block(&p, plate, 20000, found, NULL) == 0);

    /* One strike with a 30 ms ring: one hit, at its first sample over the threshold. */
    memset(plate, 0, sizeof(plate));
    strike(plate, 20000, 1000, 3000, 30);
    peak_init(&p, 20000, PEAK_THRESHOLD_DEFAULT, PEAK_HOLDOFF_DEFAULT_MS);
    hit_count = 0;
    CHECK(peak_block(&p, plate, 20000, found, NULL) == 1);
    CHECK(hit_count == 1 && hits[0].sample == 1000);
    CHECK(hits[0].strength == peak_strength(3000, PEAK_THRESHOLD_DEFAULT));
    CHECK(hits[0].strength > 150 && hits[0].strength < 200);

    /* A ring longer than the hold-off: still one hit (the hold-off waits for the ringing). */
    memset(plate, 0, sizeof(plate));
    strike(plate, 20000, 1000, 4000, 200);
    peak_init(&p, 20000, PEAK_THRESHOLD_DEFAULT, PEAK_HOLDOFF_DEFAULT_MS);
    hit_count = 0;
    CHECK(peak_block(&p, plate, 20000, found, NULL) == 1);

    /* Two strikes 100 ms apart: two hits; 30 ms apart (inside the 50 ms hold-off): one. */
    memset(plate, 0, sizeof(plate));
    strike(plate, 20000, 1000, 2000, 10);
    strike(plate, 20000, 3000, 2500, 10);
    peak_init(&p, 20000, PEAK_THRESHOLD_DEFAULT, PEAK_HOLDOFF_DEFAULT_MS);
    hit_count = 0;
    CHECK(peak_block(&p, plate, 20000, found, NULL) == 2);
    CHECK(hit_count == 2 && hits[1].sample == 3000 && hits[1].strength > hits[0].strength);
    memset(plate, 0, sizeof(plate));
    strike(plate, 20000, 1000, 2000, 5);
    strike(plate, 20000, 1600, 2500, 5);
    peak_init(&p, 20000, PEAK_THRESHOLD_DEFAULT, PEAK_HOLDOFF_DEFAULT_MS);
    CHECK(peak_block(&p, plate, 20000, NULL, NULL) == 1);
    /* ... and with the box's CONFIG hold-off of 10 ms, two. */
    peak_init(&p, 20000, PEAK_THRESHOLD_DEFAULT, 10);
    CHECK(peak_block(&p, plate, 20000, NULL, NULL) == 2);

    /* A weak tap under a raised threshold: nothing. */
    memset(plate, 0, sizeof(plate));
    strike(plate, 20000, 1000, 600, 5);
    peak_init(&p, 20000, 300, 50);
    CHECK(peak_block(&p, plate, 20000, NULL, NULL) == 1);
    peak_init(&p, 20000, 300, 50);
    peak_config(&p, 800, 50);
    CHECK(peak_block(&p, plate, 20000, NULL, NULL) == 0);

    /* The scale: 1 at the threshold, 255 at full scale, rising in between. */
    CHECK(peak_strength(300, 300) == 1 && peak_strength(100, 300) == 1);
    CHECK(peak_strength(4095, 300) == 255 && peak_strength(5000, 300) == 255);
    CHECK(peak_strength(2000, 300) < peak_strength(2100, 300));
    CHECK(peak_strength(2198, 300) == 128);
    /* A blocks's split changes nothing: sample by sample is the same. */
    memset(plate, 0, sizeof(plate));
    strike(plate, 20000, 990, 3000, 30);
    peak_init(&p, 20000, PEAK_THRESHOLD_DEFAULT, PEAK_HOLDOFF_DEFAULT_MS);
    int n = 0;
    for (size_t i = 0; i < 20000; i += 128) {
        n += peak_block(&p, plate + i, i + 128 <= 20000 ? 128 : 20000 - i, NULL, NULL);
    }
    CHECK(n == 1);
}

/* ---- The configuration ------------------------------------------------------------------- */

static void test_config(void)
{
    const uint8_t uid[4] = {1, 2, 3, 4};
    mc_config_t cfg;
    CHECK(target_config(&cfg, 0, 1, uid, 300, 50));
    CHECK(cfg.address == 0x58 && cfg.model == 0x0001 && cfg.channel_count == 1);
    CHECK(cfg.channels[0].kind == MC_KIND_HIT && cfg.channels[0].max_on_s == 0);
    CHECK(cfg.fw[0] == 1 && cfg.fw[1] == 0 && cfg.fw[2] == 0);
    CHECK(target_config(&cfg, 3, 2, uid, 300, 50) && cfg.address == 0x5B && cfg.channel_count == 2);
    CHECK(!target_config(&cfg, 4, 1, uid, 300, 50));
    CHECK(!target_config(&cfg, 0, 3, uid, 300, 50));
    mc_module_t m;
    mc_ops_t ops = {0};
    CHECK(target_config(&cfg, 1, 1, uid, 300, 50) && mc_init(&m, &cfg, &ops, 0));
    uint8_t ident[MC_IDENT_LEN];
    mc_ident_encode(&cfg, ident);
    /* "AX", version 1, inputs, one channel, model 1 (little end first). */
    CHECK(ident[0] == 0x41 && ident[1] == 0x58 && ident[2] == 1 && ident[3] == 0x01 &&
          ident[4] == 1 && ident[5] == 0x01 && ident[6] == 0x00);
    CHECK(memcmp(&ident[11], uid, 4) == 0);
}

/* ---- The I2C target's events, as a box uses them ----------------------------------------- */

static mc_module_t core;
static target_i2c_t ti;

/* A write transaction: RECEIVE per byte, then FINISH (the stop). */
static void box_write(const uint8_t *bytes, size_t n, uint32_t t)
{
    for (size_t i = 0; i < n; i++) target_i2c_event(&ti, TARGET_I2C_RECEIVE, bytes[i], t);
    target_i2c_event(&ti, TARGET_I2C_FINISH, 0, t);
}

/* A pointer write, a repeated start (FINISH: pico_i2c_slave reports the restart) and a read. */
static void box_read(uint8_t reg, uint8_t *out, size_t n, uint32_t t, bool report_restart)
{
    target_i2c_event(&ti, TARGET_I2C_RECEIVE, reg, t);
    if (report_restart) target_i2c_event(&ti, TARGET_I2C_FINISH, 0, t);
    for (size_t i = 0; i < n; i++) out[i] = target_i2c_event(&ti, TARGET_I2C_REQUEST, 0, t);
    target_i2c_event(&ti, TARGET_I2C_FINISH, 0, t);
}

/* A COMMAND with its CRC over the address byte as sent (the write address), then the rest. */
static void box_command(uint8_t addr, const uint8_t *args, size_t n, uint32_t t)
{
    uint8_t frame[12];
    frame[0] = MC_REG_COMMAND;
    memcpy(&frame[1], args, n);
    uint8_t a = (uint8_t)(addr << 1);
    uint8_t crc = mc_crc8(mc_crc8(0, &a, 1), frame, n + 1);
    frame[n + 1] = crc;
    box_write(frame, n + 2, t);
}

static void test_i2c(void)
{
    const uint8_t uid[4] = {0xE6, 0x61, 0x41, 0x03};
    mc_config_t cfg;
    target_config(&cfg, 0, 1, uid, PEAK_THRESHOLD_DEFAULT, PEAK_HOLDOFF_DEFAULT_MS);
    mc_ops_t ops = {0};
    CHECK(mc_init(&core, &cfg, &ops, 0));
    target_i2c_init(&ti, &core);

    /* The box's probe: an address with no byte (pico_i2c_slave: only FINISH). */
    target_i2c_event(&ti, TARGET_I2C_FINISH, 0, 1);
    CHECK(mc_last_result(&core) == MC_OK);

    /* IDENT, with the restart reported and without. */
    uint8_t ident[MC_IDENT_LEN], want[MC_IDENT_LEN];
    mc_ident_encode(&cfg, want);
    box_read(MC_REG_IDENT, ident, sizeof(ident), 2, true);
    CHECK(memcmp(ident, want, sizeof(want)) == 0);
    memset(ident, 0, sizeof(ident));
    box_read(MC_REG_IDENT, ident, sizeof(ident), 3, false);
    CHECK(memcmp(ident, want, sizeof(want)) == 0);

    /* CLEAR_FRESH and ARM channel 0. */
    const uint8_t clear[] = {MC_OP_CLEAR_FRESH};
    box_command(0x58, clear, 1, 4);
    const uint8_t arm[] = {MC_OP_ARM, 0x01};
    box_command(0x58, arm, 2, 5);
    CHECK(mc_armed(&core) == 0x01 && mc_last_result(&core) == MC_OK);
    CHECK((mc_status_flags(&core) & MC_ST_FRESH) == 0);

    /* A hit found by the detector, queued, and read in STATUS with its age. */
    CHECK(mc_event(&core, 0, MC_EVENT_HIT, 180, 10));
    uint8_t st[MC_STATUS_LEN];
    box_read(MC_REG_STATUS, st, sizeof(st), 25, true);
    CHECK(mc_crc8(0, st, 8) == st[8]);
    CHECK((st[0] & MC_ST_EVENT) && st[1] == 0 && (st[2] & 0x07) == 0 && (st[2] >> 4) == 1);
    CHECK(st[3] == 180 && (st[4] | (st[5] << 8)) == 15 && st[7] == 0x01);
    /* ACK: the queue is empty. */
    const uint8_t ack[] = {MC_OP_ACK, 0};
    box_command(0x58, ack, 2, 26);
    box_read(MC_REG_STATUS, st, sizeof(st), 27, true);
    CHECK((st[0] & MC_ST_EVENT) == 0);

    /* A command with a wrong CRC: refused, CMD_ERROR shown. */
    uint8_t bad[] = {MC_REG_COMMAND, MC_OP_ARM, 0x00, 0x00};
    box_write(bad, sizeof(bad), 28);
    CHECK(mc_last_result(&core) == MC_REFUSED_CRC && mc_armed(&core) == 0x01);
    box_read(MC_REG_STATUS, st, sizeof(st), 29, true);
    CHECK(st[0] & MC_ST_CMD_ERROR);

    /* CONFIG: the threshold and the hold-off the main loop gives the detector. */
    const uint8_t thr[] = {MC_OP_CONFIG, 0, MC_PARAM_THRESHOLD, 0x58, 0x02}; /* 600 */
    box_command(0x58, thr, sizeof(thr), 30);
    const uint8_t hold[] = {MC_OP_CONFIG, 0, MC_PARAM_HOLDOFF_MS, 80, 0};
    box_command(0x58, hold, sizeof(hold), 31);
    CHECK(mc_config_value(&core, 0, MC_PARAM_THRESHOLD) == 600);
    CHECK(mc_config_value(&core, 0, MC_PARAM_HOLDOFF_MS) == 80);

    /* LOCATE 2 s: the LED blinks for 2 s, then stays off; off before it. */
    CHECK(!target_led(&core, 40));
    const uint8_t locate[] = {MC_OP_LOCATE, 2};
    box_command(0x58, locate, sizeof(locate), 1000);
    CHECK(target_led(&core, 1000) && !target_led(&core, 1250) && target_led(&core, 1500));
    CHECK(!target_led(&core, 3100) && !target_led(&core, 3000 + TARGET_LOCATE_MS * 2));

    /* A write to another module's address: refused for its CRC (the address byte counts). */
    box_command(0x59, arm, 2, 3200);
    CHECK(mc_last_result(&core) == MC_REFUSED_CRC);
}

int main(void)
{
    test_peak();
    test_config();
    test_i2c();
    if (failures) {
        fprintf(stderr, "target module: %d of %d check(s) failed\n", failures, checks);
        return 1;
    }
    printf("target module: all %d checks passed\n", checks);
    return 0;
}
