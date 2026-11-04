/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Host tests of the I2C output module's portable part
 * (firmware/output-module/src/output.c) with the module core under it: the
 * channel list and the configuration (the out4 reference module of
 * protocol/vectors/expansion.json read back byte for byte), the I2C events as
 * pico_i2c_slave gives them, the guard, the watchdog's policy, the supply sense
 * and SUPPLY_OK, the status LED, and the whole module (core, guard and pins)
 * through power-up, the lease, the max on and a restart.
 */
#include <stdio.h>
#include <string.h>

#include "module_core.h"
#include "output.h"

static int failures;
static int checks;

#define CHECK(cond)                                                                                \
    do {                                                                                           \
        checks++;                                                                                  \
        if (!(cond)) {                                                                             \
            fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);                        \
            failures++;                                                                            \
        }                                                                                          \
    } while (0)

static const uint8_t UID[4] = {0xa1, 0xb2, 0xc3, 0xd4};

/* ---- a fake board
 * ---------------------------------------------------------------------------
 */

typedef struct {
    bool pin[OUTPUT_MAX_CHANNELS];
    int drives;
    bool supply;
} board_t;

static void board_drive(void *ctx, uint8_t channel, bool on)
{
    board_t *b = ctx;
    b->pin[channel] = on;
    b->drives++;
}

static uint8_t board_pins(const board_t *b)
{
    uint8_t bits = 0;
    for (uint8_t i = 0; i < OUTPUT_MAX_CHANNELS; i++) bits |= b->pin[i] ? (uint8_t)(1u << i) : 0;
    return bits;
}

/* The whole module as main.c puts it together: the core's set_output goes
 * through the guard to the pins. */
typedef struct {
    board_t board;
    output_guard_t guard;
    output_supply_t supply;
    mc_module_t core;
    output_i2c_t i2c;
    mc_config_t cfg;
} module_t;

static void module_set_output(void *ctx, uint8_t channel, bool on)
{
    output_guard_set(&((module_t *)ctx)->guard, channel, on);
}

static bool module_supply_ok(void *ctx)
{
    return ((module_t *)ctx)->supply.ok;
}

static bool module_start(module_t *m, const char *spec, uint8_t jumpers, uint32_t now)
{
    memset(m, 0, sizeof(*m));
    /* What the pins did before the firmware ran: all on, so power-up off is seen
     * to happen. */
    for (uint8_t i = 0; i < OUTPUT_MAX_CHANNELS; i++) m->board.pin[i] = true;
    const char *error = NULL;
    if (!output_config(&m->cfg, jumpers, spec, UID, &error)) return false;
    output_guard_init(&m->guard, &m->cfg, board_drive, &m->board);
    output_supply_init(&m->supply);
    mc_ops_t ops = {m, module_set_output, module_supply_ok};
    if (!mc_init(&m->core, &m->cfg, &ops, now)) return false;
    output_i2c_init(&m->i2c, &m->core);
    return true;
}

/* One pass of main.c's loop. */
static bool module_loop(module_t *m, uint32_t now)
{
    mc_tick(&m->core, now);
    return output_guard_check(&m->guard, now);
}

/* Runs the loop every millisecond from *t to until. */
static bool module_run(module_t *m, uint32_t *t, uint32_t until)
{
    bool ok = true;
    while (*t < until) {
        (*t)++;
        ok &= module_loop(m, *t);
    }
    return ok;
}

/* A write as the RP2040's peripheral reports it: each byte received, then the
 * stop. */
static void i2c_write(module_t *m, const uint8_t *bytes, size_t n, uint32_t t)
{
    for (size_t i = 0; i < n; i++) output_i2c_event(&m->i2c, OUTPUT_I2C_RECEIVE, bytes[i], t);
    output_i2c_event(&m->i2c, OUTPUT_I2C_FINISH, 0, t);
}

/* A pointer write, a repeated start (reported or not), then a read and its
 * stop. */
static void i2c_read(module_t *m, const uint8_t *ptr, size_t ptr_len, uint8_t *out, size_t n,
                     bool report_restart, uint32_t t)
{
    for (size_t i = 0; i < ptr_len; i++) output_i2c_event(&m->i2c, OUTPUT_I2C_RECEIVE, ptr[i], t);
    if (report_restart) output_i2c_event(&m->i2c, OUTPUT_I2C_FINISH, 0, t);
    for (size_t i = 0; i < n; i++) out[i] = output_i2c_event(&m->i2c, OUTPUT_I2C_REQUEST, 0, t);
    output_i2c_event(&m->i2c, OUTPUT_I2C_FINISH, 0, t);
}

static void command(module_t *m, const uint8_t *body, size_t n, uint32_t t)
{
    uint8_t frame[16];
    uint8_t address_byte = (uint8_t)(m->cfg.address << 1);
    frame[0] = MC_REG_COMMAND;
    memcpy(&frame[1], body, n);
    frame[n + 1] = mc_crc8(mc_crc8(0, &address_byte, 1), frame, n + 1);
    i2c_write(m, frame, n + 2, t);
}

static void output_cmd(module_t *m, uint8_t ch, uint8_t mode, uint16_t dur, uint16_t on,
                       uint16_t off, uint32_t t)
{
    uint8_t b[9] = {MC_OP_OUTPUT,
                    ch,
                    mode,
                    (uint8_t)dur,
                    (uint8_t)(dur >> 8),
                    (uint8_t)on,
                    (uint8_t)(on >> 8),
                    (uint8_t)off,
                    (uint8_t)(off >> 8)};
    command(m, b, 9, t);
}

static void lease_cmd(module_t *m, uint32_t t)
{
    uint8_t b[2] = {MC_OP_LEASE, MC_LEASE_DEFAULT_100MS};
    command(m, b, 2, t);
}

static void status(module_t *m, uint8_t out[MC_STATUS_LEN], uint32_t t)
{
    uint8_t reg = MC_REG_STATUS;
    i2c_read(m, &reg, 1, out, MC_STATUS_LEN, true, t);
}

/* ---- the channel list
 * ----------------------------------------------------------------------- */

static void test_default_channels(void)
{
    mc_channel_t ch[OUTPUT_MAX_CHANNELS];
    uint8_t n = 0;
    const char *error = NULL;
    CHECK(output_parse_channels(OUTPUT_CHANNELS_DEFAULT, ch, &n, &error));
    CHECK(n == 4);
    for (uint8_t i = 0; i < n; i++) {
        CHECK(ch[i].kind == MC_KIND_OUTPUT);
        CHECK(ch[i].flags == MC_CH_RELAY);
        CHECK(ch[i].hint == 0);
        CHECK(ch[i].max_on_s == 30);
        CHECK(ch[i].min_off_s == 0);
        CHECK(ch[i].threshold == 0 && ch[i].holdoff_ms == 0 && ch[i].debounce_ms == 0);
    }
}

static void test_channel_fields(void)
{
    mc_channel_t ch[OUTPUT_MAX_CHANNELS];
    uint8_t n = 0;
    const char *error = NULL;
    CHECK(output_parse_channels("solid:horn:255:255:sense", ch, &n, &error));
    CHECK(n == 1);
    CHECK(ch[0].flags == (MC_CH_SOLID_STATE | MC_CH_SENSES_SUPPLY));
    CHECK(ch[0].hint == 5 && ch[0].max_on_s == 255 && ch[0].min_off_s == 255);

    const char *hints[] = {"generic", "siren", "strobe", "smoke", "light", "horn"};
    for (uint8_t h = 0; h < 6; h++) {
        char spec[40];
        snprintf(spec, sizeof(spec), "relay:%s:1:0", hints[h]);
        CHECK(output_parse_channels(spec, ch, &n, &error));
        CHECK(n == 1 && ch[0].hint == h && ch[0].max_on_s == 1);
    }
    CHECK(output_parse_channels("relay:light:7:3,solid:strobe:9:0", ch, &n, &error));
    CHECK(n == 2 && ch[1].flags == MC_CH_SOLID_STATE && ch[1].hint == 2 && ch[0].min_off_s == 3);
}

static void test_channel_refusals(void)
{
    const char *bad[] = {
        "",
        "relay",
        "relay:siren",
        "relay:siren:60",
        "relay:siren:0:0",    /* a max on of 0: the box refuses it too */
        "relay:siren:256:0",  /* above 255 */
        "relay:siren:60:256", /* min off above 255 */
        "relay:siren:1000:0", /* four digits */
        "relay:siren:-1:0",
        "relay:siren:60:0:sens",    /* not sense */
        "relay:siren:60:0:sense:x", /* a sixth field */
        "relay:siren:60:0,",        /* a trailing comma */
        ",relay:siren:60:0",        /* a leading one */
        "relays:siren:60:0",        /* a type that only starts like one */
        "mosfet:siren:60:0",        /* solid, not mosfet */
        "relay:sirens:60:0",        /* a hint that only starts like one */
        "relay:fog:60:0",           /* not a hint */
        "relay:siren:60:0 ",        /* a space */
        " relay:siren:60:0",
        "relay:siren:6x:0",
        "relay:siren:60:0x",
        "relay:siren::0",
        "relay:Siren:60:0", /* lower case only */
        "relay:siren:60:0;relay:siren:60:0" /* commas between channels */,
        "relay:generic:30:0,relay:generic:30:0,relay:generic:30:0,relay:generic:30:0,"
        "relay:generic:30:0", /* five channels: the module has four pins */
    };
    for (size_t i = 0; i < sizeof(bad) / sizeof(bad[0]); i++) {
        mc_channel_t ch[OUTPUT_MAX_CHANNELS];
        uint8_t n = 99;
        const char *error = NULL;
        bool ok = output_parse_channels(bad[i], ch, &n, &error);
        if (ok) fprintf(stderr, "taken: \"%s\"\n", bad[i]);
        CHECK(!ok);
        CHECK(error != NULL && error[0] != '\0');
        CHECK(n == 99); /* count untouched */
    }
    mc_channel_t ch[OUTPUT_MAX_CHANNELS];
    uint8_t n = 0;
    CHECK(!output_parse_channels(NULL, ch, &n, NULL)); /* no error pointer: no crash */
    CHECK(!output_parse_channels("relay:x:1:0", ch, &n, NULL));
}

/* The out4 reference module of protocol/vectors/expansion.json ("out4_module"
 * and "out4_channel_0" to "_3"), built from a channel list and read back over
 * the I2C events. */
static void test_out4_reference(void)
{
    module_t m;
    CHECK(module_start(&m,
                       "relay:siren:60:0,relay:strobe:120:0,relay:smoke:30:30:sense,"
                       "solid:generic:255:0",
                       0, 0));
    CHECK(m.cfg.address == 0x5C);
    CHECK(m.cfg.model == 0x0002);
    m.cfg.hw_rev = 2; /* the vector's revision; this module's is OUTPUT_HW_REV */
    CHECK(OUTPUT_HW_REV == 1);
    mc_ops_t ops = {&m, module_set_output, module_supply_ok};
    CHECK(mc_init(&m.core, &m.cfg, &ops, 0));

    static const uint8_t ident[MC_IDENT_LEN] = {0x41, 0x58, 0x01, 0x02, 0x04, 0x02, 0x00, 0x02,
                                                0x01, 0x00, 0x00, 0xa1, 0xb2, 0xc3, 0xd4, 0xc0};
    static const uint8_t channels[4][MC_CHANNEL_LEN] = {
        {0x00, 0x10, 0x01, 0x01, 0x3c, 0x00, 0x00, 0xf1},
        {0x01, 0x10, 0x01, 0x02, 0x78, 0x00, 0x00, 0x39},
        {0x02, 0x10, 0x05, 0x03, 0x1e, 0x1e, 0x00, 0xff},
        {0x03, 0x10, 0x02, 0x00, 0xff, 0x00, 0x00, 0x17},
    };
    uint8_t out[MC_IDENT_LEN];
    uint8_t reg = MC_REG_IDENT;
    i2c_read(&m, &reg, 1, out, MC_IDENT_LEN, true, 1);
    CHECK(memcmp(out, ident, MC_IDENT_LEN) == 0);
    for (uint8_t i = 0; i < 4; i++) {
        uint8_t ptr[2] = {MC_REG_CHANNEL, i};
        /* the repeated start reported for two channels, not for the others */
        i2c_read(&m, ptr, 2, out, MC_CHANNEL_LEN, i < 2, 2);
        CHECK(memcmp(out, channels[i], MC_CHANNEL_LEN) == 0);
    }
    CHECK(output_senses_supply(&m.cfg));
}

static void test_config(void)
{
    mc_config_t cfg;
    const char *error = NULL;
    for (uint8_t j = 0; j < 4; j++) {
        CHECK(output_config(&cfg, j, OUTPUT_CHANNELS_DEFAULT, UID, &error));
        CHECK(cfg.address == 0x5C + j);
        CHECK(cfg.fw[0] == 1 && cfg.fw[1] == 0 && cfg.fw[2] == 0);
        CHECK(memcmp(cfg.uid, UID, 4) == 0);
        CHECK(cfg.channel_count == 4);
        CHECK(!output_senses_supply(&cfg));
    }
    error = NULL;
    CHECK(!output_config(&cfg, 4, OUTPUT_CHANNELS_DEFAULT, UID, &error));
    CHECK(error != NULL);
    error = NULL;
    CHECK(!output_config(&cfg, 0, "relay:siren:0:0", UID, &error));
    CHECK(error != NULL);
    /* Every configuration the channel list allows is one the core takes. */
    CHECK(output_config(&cfg, 3, "solid:smoke:1:255:sense", UID, &error));
    module_t m;
    CHECK(module_start(&m, "solid:smoke:1:255:sense", 3, 0));
    CHECK(m.cfg.address == 0x5F);
}

/* ---- the I2C events
 * ------------------------------------------------------------------------- */

static void test_i2c_events(void)
{
    module_t m;
    CHECK(module_start(&m, OUTPUT_CHANNELS_DEFAULT, 0, 0));
    uint8_t st[MC_STATUS_LEN];
    status(&m, st, 1);
    CHECK(st[0] == MC_ST_FRESH);
    CHECK(st[8] == mc_crc8(0, st, 8));

    /* The box's probe: an address with no byte. Nothing reaches the core, nothing
     * changes. */
    output_i2c_event(&m.i2c, OUTPUT_I2C_FINISH, 0, 2);
    CHECK(m.i2c.state == 0);
    status(&m, st, 3);
    CHECK(st[0] == MC_ST_FRESH);

    /* A COMMAND write: taken at its stop. */
    output_cmd(&m, 1, MC_MODE_ON, 0, 0, 0, 4);
    CHECK(board_pins(&m.board) == 0x02);
    status(&m, st, 5);
    CHECK(st[6] == 0x02);

    /* A refused write: CMD_ERROR, nothing changed. */
    uint8_t bad[4] = {MC_REG_COMMAND, MC_OP_LEASE, 15, 0x00};
    i2c_write(&m, bad, 4, 6);
    CHECK(mc_last_result(&m.core) == MC_REFUSED_CRC);
    status(&m, st, 7);
    CHECK((st[0] & MC_ST_CMD_ERROR) && st[6] == 0x02);

    /* A byte received in a read's place (a write after a read without a FINISH)
     * ends the read. */
    uint8_t reg = MC_REG_STATUS;
    output_i2c_event(&m.i2c, OUTPUT_I2C_RECEIVE, reg, 8);
    (void)output_i2c_event(&m.i2c, OUTPUT_I2C_REQUEST, 0, 8);
    CHECK(m.i2c.state == 2);
    uint8_t off[1] = {MC_OP_ALL_OFF};
    command(&m, off, 1, 9);
    CHECK(board_pins(&m.board) == 0);
    CHECK(mc_last_result(&m.core) == MC_OK);
}

/* ---- the guard
 * ------------------------------------------------------------------------------
 */

static void test_guard(void)
{
    mc_config_t cfg;
    CHECK(output_config(&cfg, 0, "relay:siren:2:0,solid:strobe:1:0", UID, NULL));
    board_t b;
    memset(&b, 0, sizeof(b));
    b.pin[0] = b.pin[1] = true;
    output_guard_t g;
    output_guard_init(&g, &cfg, board_drive, &b);
    CHECK(board_pins(&b) == 0);
    CHECK(g.limit_ms[0] == 2000u + OUTPUT_GUARD_SLACK_MS);
    CHECK(g.limit_ms[1] == 1000u + OUTPUT_GUARD_SLACK_MS);

    output_guard_set(&g, 0, true);
    CHECK(board_pins(&b) == 0x01 && output_guard_levels(&g) == 0x01);
    CHECK(output_guard_check(&g, 100)); /* timed from here */
    CHECK(output_guard_check(&g, 100 + 2000 + OUTPUT_GUARD_SLACK_MS));
    /* Off and on again restarts the count (a pattern never trips it). */
    output_guard_set(&g, 0, false);
    CHECK(output_guard_check(&g, 3000));
    output_guard_set(&g, 0, true);
    CHECK(output_guard_check(&g, 3001));
    CHECK(output_guard_check(&g, 3001 + 2000));
    output_guard_set(&g, 0, true); /* the same level again changes nothing */
    output_guard_set(&g, 1, true);
    CHECK(output_guard_check(&g, 3001 + 2000 + OUTPUT_GUARD_SLACK_MS));
    CHECK(board_pins(&b) == 0x03);
    /* One millisecond past channel 0's limit: every channel off, for good. */
    CHECK(!output_guard_check(&g, 3001 + 2000 + OUTPUT_GUARD_SLACK_MS + 1));
    CHECK(output_guard_tripped(&g));
    CHECK(board_pins(&b) == 0 && output_guard_levels(&g) == 0);
    output_guard_set(&g, 1, true);
    CHECK(board_pins(&b) == 0);
    CHECK(!output_guard_check(&g, 6000));
    output_guard_set(&g, 7, true); /* a channel the module lacks: ignored */
    CHECK(board_pins(&b) == 0);

    /* A clock that wraps. */
    output_guard_init(&g, &cfg, board_drive, &b);
    output_guard_set(&g, 1, true);
    CHECK(output_guard_check(&g, 0xFFFFFF00u));
    CHECK(output_guard_check(&g, 0xFFFFFF00u + 1000u + OUTPUT_GUARD_SLACK_MS));
    CHECK(!output_guard_check(&g, 0xFFFFFF00u + 1000u + OUTPUT_GUARD_SLACK_MS + 1u));
}

/* ---- the watchdog's policy
 * ------------------------------------------------------------------ */

static void test_watchdog(void)
{
    mc_config_t cfg;
    CHECK(output_config(&cfg, 0, "relay:siren:1:0", UID, NULL));
    board_t b;
    memset(&b, 0, sizeof(b));
    output_guard_t g;
    output_guard_init(&g, &cfg, board_drive, &b);
    CHECK(output_watchdog_feed(true, &g, 1000, 1000));
    CHECK(output_watchdog_feed(true, &g, 1000, 1000 + OUTPUT_TICK_LATE_MS));
    CHECK(!output_watchdog_feed(true, &g, 1000, 1000 + OUTPUT_TICK_LATE_MS + 1));
    CHECK(!output_watchdog_feed(false, &g, 1000, 1000));
    CHECK(output_watchdog_feed(true, &g, 0xFFFFFFF0u, 0x10u)); /* across a wrap */
    output_guard_set(&g, 0, true);
    output_guard_check(&g, 0);
    output_guard_check(&g, 1000 + OUTPUT_GUARD_SLACK_MS + 1);
    CHECK(!output_watchdog_feed(true, &g, 2000, 2000));
    /* The watchdog restarts the module well within the lease. */
    CHECK(OUTPUT_WATCHDOG_MS < MC_LEASE_DEFAULT_100MS * 100u);
    CHECK(OUTPUT_TICK_LATE_MS < OUTPUT_WATCHDOG_MS);
}

/* ---- the supply sense
 * ----------------------------------------------------------------------- */

/* The ADC reading a supply of mv gives through the divider. */
static uint16_t raw_for(uint32_t mv)
{
    uint64_t r = (uint64_t)mv * OUTPUT_SENSE_BOTTOM_OHM * 4095u /
                 ((uint64_t)(OUTPUT_SENSE_TOP_OHM + OUTPUT_SENSE_BOTTOM_OHM) * OUTPUT_ADC_FULL_MV);
    return (uint16_t)(r > 4095u ? 4095u : r);
}

static void test_supply(void)
{
    CHECK(output_supply_mv(0) == 0);
    uint32_t full = output_supply_mv(4095);
    CHECK(full >= 18290 && full <= 18300);          /* 3.3 V x 122 / 22 */
    CHECK(output_supply_mv(0xF000 | 4095) == full); /* only 12 bits */
    /* 15 V, the top of the module's input, stays within the ADC's range. */
    CHECK(raw_for(15000) < 4095);
    uint32_t mv12 = output_supply_mv(raw_for(12000));
    CHECK(mv12 > 11990 && mv12 <= 12000);

    output_supply_t s;
    output_supply_init(&s);
    CHECK(!s.ok);
    CHECK(output_supply_update(&s, raw_for(12000))); /* the first reading primes the filter */
    /* A short dip (a relay's spike) does not drop it. */
    CHECK(output_supply_update(&s, 0));
    for (int i = 0; i < 20; i++) output_supply_update(&s, raw_for(12000));
    CHECK(s.ok);
    /* Hysteresis: 8.7 V holds an ok supply, does not make one. */
    for (int i = 0; i < 100; i++) output_supply_update(&s, raw_for(8700));
    CHECK(s.ok);
    for (int i = 0; i < 100; i++) output_supply_update(&s, raw_for(8000));
    CHECK(!s.ok);
    for (int i = 0; i < 100; i++) output_supply_update(&s, raw_for(8700));
    CHECK(!s.ok);
    for (int i = 0; i < 100; i++) output_supply_update(&s, raw_for(9300));
    CHECK(s.ok);
    output_supply_init(&s);
    CHECK(!output_supply_update(&s, raw_for(5000)));
    CHECK(!output_supply_update(&s, 0));
}

static void test_supply_ok_flag(void)
{
    uint8_t st[MC_STATUS_LEN];
    module_t m;
    /* A channel that senses: SUPPLY_OK follows the divider. */
    CHECK(module_start(&m, "relay:smoke:30:30:sense,relay:siren:60:0", 0, 0));
    status(&m, st, 1);
    CHECK(!(st[0] & MC_ST_SUPPLY_OK));
    output_supply_update(&m.supply, raw_for(12000));
    status(&m, st, 2);
    CHECK(st[0] & MC_ST_SUPPLY_OK);
    for (int i = 0; i < 100; i++) output_supply_update(&m.supply, raw_for(3000));
    status(&m, st, 3);
    CHECK(!(st[0] & MC_ST_SUPPLY_OK));
    /* No channel senses: never SUPPLY_OK, whatever the pin reads. */
    CHECK(module_start(&m, OUTPUT_CHANNELS_DEFAULT, 0, 0));
    output_supply_update(&m.supply, raw_for(12000));
    CHECK(m.supply.ok);
    status(&m, st, 1);
    CHECK(!(st[0] & MC_ST_SUPPLY_OK));
}

/* ---- the LED
 * --------------------------------------------------------------------------------
 */

static void test_led(void)
{
    CHECK(!output_led(false, false, 0));
    CHECK(!output_led(false, false, 300));
    CHECK(output_led(false, true, 0));
    CHECK(output_led(false, true, OUTPUT_LOCATE_MS - 1));
    CHECK(!output_led(false, true, OUTPUT_LOCATE_MS));
    CHECK(output_led(true, true, 0));
    CHECK(!output_led(true, true, OUTPUT_FAULT_MS)); /* a fault blinks faster than LOCATE */
    CHECK(output_led(true, false, 2 * OUTPUT_FAULT_MS));
}

/* ---- the whole module
 * ----------------------------------------------------------------------- */

static void test_power_up_off(void)
{
    module_t m;
    CHECK(module_start(&m, "relay:siren:60:0,solid:strobe:120:0", 0, 0));
    /* Every pin off (each was on before the firmware ran): the guard drove all
     * four, the fitted two and the two unused, and the core the fitted two once
     * more through it. */
    CHECK(board_pins(&m.board) == 0);
    CHECK(m.board.drives == 6);
    CHECK(mc_outputs(&m.core) == 0);
    CHECK(mc_status_flags(&m.core) & MC_ST_FRESH);
}

static void test_lease(void)
{
    module_t m;
    uint32_t t = 0;
    CHECK(module_start(&m, OUTPUT_CHANNELS_DEFAULT, 0, t));
    output_cmd(&m, 0, MC_MODE_ON, 0, 0, 0, t);
    CHECK(board_pins(&m.board) == 0x01);
    /* The box refreshes every 500 ms: on. */
    for (int i = 0; i < 6; i++) {
        CHECK(module_run(&m, &t, t + 500));
        lease_cmd(&m, t);
    }
    CHECK(board_pins(&m.board) == 0x01);
    /* The box stops: off 1.5 s after the last refresh, LEASE_EXPIRED; the guard
     * never tripped. */
    uint32_t last = t;
    CHECK(module_run(&m, &t, last + 1499));
    CHECK(board_pins(&m.board) == 0x01);
    CHECK(module_run(&m, &t, last + 1500));
    CHECK(board_pins(&m.board) == 0);
    CHECK(mc_status_flags(&m.core) & MC_ST_LEASE_EXPIRED);
    CHECK(!output_guard_tripped(&m.guard));
}

static void test_max_on(void)
{
    module_t m;
    uint32_t t = 0;
    CHECK(module_start(&m, "relay:smoke:30:30,solid:strobe:2:0", 0, t));
    output_cmd(&m, 0, MC_MODE_ON, 0, 0, 0, t);
    CHECK(board_pins(&m.board) == 0x01);
    /* Leased all along: the core's max on ends it at 30 s, before the guard's
     * limit. */
    bool ok = true;
    while (t < 31000) {
        ok &= module_run(&m, &t, t + 500);
        lease_cmd(&m, t);
    }
    CHECK(ok);
    CHECK(board_pins(&m.board) == 0);
    CHECK(!output_guard_tripped(&m.guard));
    /* Min off: refused until 30 s later. */
    output_cmd(&m, 0, MC_MODE_ON, 0, 0, 0, t);
    CHECK(mc_last_result(&m.core) == MC_REFUSED_MIN_OFF);
    CHECK(board_pins(&m.board) == 0);
    /* A solid-state 10 ms pattern runs for its max on of 2 s without tripping the
     * guard. */
    output_cmd(&m, 1, MC_MODE_PATTERN, 0, 1, 1, t);
    CHECK(mc_last_result(&m.core) == MC_OK);
    int edges = 0;
    bool was = m.board.pin[1];
    for (int i = 0; i < 1500; i++) {
        ok &= module_loop(&m, ++t);
        if (m.board.pin[1] != was) edges++;
        was = m.board.pin[1];
    }
    CHECK(ok && edges > 100);
    CHECK(!output_guard_tripped(&m.guard));
    /* A relay's pattern under 100 ms is refused. */
    output_cmd(&m, 0, MC_MODE_PATTERN, 0, 5, 5, t);
    CHECK(mc_last_result(&m.core) == MC_REFUSED_RANGE);
}

/* The guard under a core that keeps a channel on past its max on (memory gone
 * wrong): it trips, every pin goes off, and the watchdog's policy stops
 * feeding. */
static void test_guard_under_a_faulty_core(void)
{
    module_t m;
    uint32_t t = 0;
    CHECK(module_start(&m, "relay:siren:2:0,relay:strobe:60:0", 0, t));
    output_cmd(&m, 0, MC_MODE_ON, 0, 0, 0, t);
    output_cmd(&m, 1, MC_MODE_ON, 0, 0, 0, t);
    CHECK(board_pins(&m.board) == 0x03);
    m.core.cfg.channels[0].max_on_s = 255; /* the fault */
    bool ok = true;
    while (t < 4000) {
        ok &= module_run(&m, &t, t + 500);
        lease_cmd(&m, t);
    }
    CHECK(!ok);
    CHECK(output_guard_tripped(&m.guard));
    CHECK(board_pins(&m.board) == 0);
    CHECK(!output_watchdog_feed(true, &m.guard, t, t));
    /* Whatever the core asks now, nothing comes on. */
    lease_cmd(&m, t);
    output_cmd(&m, 1, MC_MODE_ON, 0, 0, 0, t);
    module_loop(&m, ++t);
    CHECK(board_pins(&m.board) == 0);
    /* The watchdog's restart is a new start: off, FRESH, usable again. */
    CHECK(module_start(&m, "relay:siren:2:0,relay:strobe:60:0", 0, t));
    CHECK(board_pins(&m.board) == 0);
    CHECK(mc_status_flags(&m.core) & MC_ST_FRESH);
    output_cmd(&m, 1, MC_MODE_ON, 0, 0, 0, t);
    CHECK(board_pins(&m.board) == 0x02);
}

int main(void)
{
    test_default_channels();
    test_channel_fields();
    test_channel_refusals();
    test_out4_reference();
    test_config();
    test_i2c_events();
    test_guard();
    test_watchdog();
    test_supply();
    test_supply_ok_flag();
    test_led();
    test_power_up_off();
    test_lease();
    test_max_on();
    test_guard_under_a_faulty_core();
    if (failures) {
        fprintf(stderr, "%d of %d checks failed\n", failures, checks);
        return 1;
    }
    printf("output module: %d checks passed\n", checks);
    return 0;
}
