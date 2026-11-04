/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Host tests of the module core (firmware/module-core/): every vector of
 * protocol/vectors/expansion.json (through module_core_vectors.h, which tools/protogen.py writes),
 * then the I2C target's state machine, the event queue, the lease and the limits at their edges.
 */
#include <stdio.h>
#include <string.h>

#include "module_core.h"
#include "module_core_vectors.h"

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

#define CHECK_NAMED(cond, name)                                                                    \
    do {                                                                                           \
        checks++;                                                                                  \
        if (!(cond)) {                                                                             \
            fprintf(stderr, "FAIL %s:%d: %s (%s)\n", __FILE__, __LINE__, #cond, name);             \
            failures++;                                                                            \
        }                                                                                          \
    } while (0)

/* ---- a fake module's hardware -------------------------------------------- */

typedef struct {
    bool pin[MC_MAX_CHANNELS];
    int calls[MC_MAX_CHANNELS];
    int total_calls;
    bool supply;
} hw_t;

static void hw_set_output(void *ctx, uint8_t channel, bool on)
{
    hw_t *hw = ctx;
    hw->pin[channel] = on;
    hw->calls[channel]++;
    hw->total_calls++;
}

static bool hw_supply_ok(void *ctx)
{
    return ((hw_t *)ctx)->supply;
}

static uint8_t hw_pins(const hw_t *hw)
{
    uint8_t bits = 0;
    for (uint8_t i = 0; i < MC_MAX_CHANNELS; i++) bits |= hw->pin[i] ? (uint8_t)(1u << i) : 0;
    return bits;
}

static mc_config_t config_of(int module, uint8_t address)
{
    const mcv_module_t *v = &mcv_modules[module];
    mc_config_t c;
    memset(&c, 0, sizeof(c));
    c.address = address;
    c.model = v->model;
    c.hw_rev = v->hw;
    memcpy(c.fw, v->fw, 3);
    memcpy(c.uid, v->uid, 4);
    c.channel_count = v->channel_count;
    for (uint8_t i = 0; i < v->channel_count; i++) {
        c.channels[i].kind = v->channels[i].kind;
        c.channels[i].flags = v->channels[i].flags;
        c.channels[i].hint = v->channels[i].hint;
        c.channels[i].max_on_s = v->channels[i].max_on_s;
        c.channels[i].min_off_s = v->channels[i].min_off_s;
        if (v->channels[i].kind == MC_KIND_HIT) {
            c.channels[i].threshold = 30;
            c.channels[i].holdoff_ms = 50;
            c.channels[i].debounce_ms = 0;
        }
    }
    return c;
}

static int module_index(const char *name)
{
    for (size_t i = 0; i < MCV_MODULE_COUNT; i++) {
        if (strcmp(mcv_modules[i].name, name) == 0) return (int)i;
    }
    return -1;
}

static bool start(mc_module_t *m, hw_t *hw, int module, uint8_t address, uint32_t now)
{
    memset(hw, 0, sizeof(*hw));
    mc_config_t c = config_of(module, address);
    mc_ops_t ops = {hw, hw_set_output, hw_supply_ok};
    return mc_init(m, &c, &ops, now);
}

/* A COMMAND frame to m's address: register 0x10, op, arguments, CRC over the address byte first. */
static mc_result_t command(mc_module_t *m, uint32_t t, const uint8_t *body, size_t n)
{
    uint8_t frame[16];
    uint8_t address_byte = (uint8_t)(m->cfg.address << 1);
    frame[0] = MC_REG_COMMAND;
    memcpy(&frame[1], body, n);
    uint8_t crc = mc_crc8(mc_crc8(0, &address_byte, 1), frame, n + 1);
    frame[n + 1] = crc;
    return mc_write(m, frame, n + 2, t);
}

static mc_result_t cmd0(mc_module_t *m, uint32_t t, uint8_t op)
{
    return command(m, t, &op, 1);
}

static mc_result_t cmd1(mc_module_t *m, uint32_t t, uint8_t op, uint8_t a)
{
    uint8_t b[2] = {op, a};
    return command(m, t, b, 2);
}

static mc_result_t output(mc_module_t *m, uint32_t t, uint8_t ch, uint8_t mode, uint16_t dur,
                          uint16_t on, uint16_t off)
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
    return command(m, t, b, 9);
}

/* A STATUS poll as a box makes it: the pointer write, then the 9 bytes. */
static void status(mc_module_t *m, uint32_t t, uint8_t out[MC_STATUS_LEN])
{
    uint8_t reg = MC_REG_STATUS;
    mc_write(m, &reg, 1, t);
    mc_read(m, out, MC_STATUS_LEN, t);
}

/* ---- the vectors --------------------------------------------------------- */

static void test_crc(void)
{
    CHECK(mc_crc8(0, (const uint8_t *)"123456789", 9) == 0xF4);
    CHECK(mc_crc8(0, NULL, 0) == 0x00);
    const uint8_t ff = 0xFF;
    CHECK(mc_crc8(0, &ff, 1) == 0xF3);
    const uint8_t lease5c[] = {0x5C << 1, 0x10, 0x04, 0x0F};
    const uint8_t lease5d[] = {0x5D << 1, 0x10, 0x04, 0x0F};
    CHECK(mc_crc8(0, lease5c, 4) == 0xF3);
    CHECK(mc_crc8(0, lease5d, 4) == 0xDF);
    /* continued in two parts, as a write's CRC is (address byte, then the bytes) */
    CHECK(mc_crc8(mc_crc8(0, lease5c, 1), lease5c + 1, 3) == 0xF3);
}

static void test_ident_vectors(void)
{
    for (size_t i = 0; i < MCV_IDENT_COUNT; i++) {
        const mcv_ident_t *v = &mcv_idents[i];
        mc_module_t m;
        hw_t hw;
        CHECK_NAMED(start(&m, &hw, v->module, mcv_modules[v->module].address, 0), v->name);
        uint8_t got[MC_IDENT_LEN + 2];
        uint8_t reg = MC_REG_IDENT;
        CHECK_NAMED(mc_write(&m, &reg, 1, 0) == MC_OK, v->name);
        mc_read(&m, got, sizeof(got), 0);
        CHECK_NAMED(memcmp(got, v->bytes, MC_IDENT_LEN) == 0, v->name);
        CHECK_NAMED(got[MC_IDENT_LEN] == 0xFF && got[MC_IDENT_LEN + 1] == 0xFF, v->name);
        CHECK_NAMED(got[3] == mcv_modules[v->module].classes, v->name);
        uint8_t enc[MC_IDENT_LEN];
        mc_ident_encode(&m.cfg, enc);
        CHECK_NAMED(memcmp(enc, v->bytes, MC_IDENT_LEN) == 0, v->name);
    }
}

static void test_channel_vectors(void)
{
    for (size_t i = 0; i < MCV_CHANNEL_COUNT; i++) {
        const mcv_channel_frame_t *v = &mcv_channel_frames[i];
        mc_module_t m;
        hw_t hw;
        CHECK_NAMED(start(&m, &hw, v->module, mcv_modules[v->module].address, 0), v->name);
        uint8_t ptr[2] = {MC_REG_CHANNEL, v->index};
        CHECK_NAMED(mc_write(&m, ptr, 2, 0) == MC_OK, v->name);
        uint8_t got[MC_CHANNEL_LEN];
        mc_read(&m, got, sizeof(got), 0);
        CHECK_NAMED(memcmp(got, v->bytes, MC_CHANNEL_LEN) == 0, v->name);
        CHECK_NAMED(!(mc_status_flags(&m) & MC_ST_CMD_ERROR), v->name);
    }
}

/* Each STATUS of the file through the encoder; and, for each a module can come to, the state
 * reached through the protocol itself, read as the box reads it. */
static bool status_reached(const mcv_status_t *v, uint8_t got[MC_STATUS_LEN])
{
    mc_module_t m;
    hw_t hw;
    uint32_t t = 1000;
    start(&m, &hw, v->module, mcv_modules[v->module].address, 0);
    if (strcmp(v->name, "target_idle_armed") == 0) {
        cmd0(&m, t, MC_OP_CLEAR_FRESH);
        cmd1(&m, t, MC_OP_ARM, 0x01);
    } else if (strcmp(v->name, "target_hit_with_more") == 0) {
        cmd0(&m, t, MC_OP_CLEAR_FRESH);
        cmd1(&m, t, MC_OP_ARM, 0x01);
        for (uint8_t s = 0; s < 7; s++) {
            mc_event(&m, 0, MC_EVENT_HIT, 10, t);
            cmd1(&m, t, MC_OP_ACK, s);
        }
        mc_event(&m, 0, MC_EVENT_HIT, 200, 9965);
        mc_event(&m, 0, MC_EVENT_HIT, 100, 9990);
        t = 10000;
    } else if (strcmp(v->name, "target_fresh_after_restart") == 0) {
        /* as it starts */
    } else if (strcmp(v->name, "out4_two_on_supply_ok") == 0) {
        hw.supply = true;
        cmd0(&m, t, MC_OP_CLEAR_FRESH);
        output(&m, t, 0, MC_MODE_ON, 0, 0, 0);
        output(&m, t, 2, MC_MODE_ON, 0, 0, 0);
    } else if (strcmp(v->name, "out4_lease_expired") == 0) {
        hw.supply = true;
        cmd0(&m, t, MC_OP_CLEAR_FRESH);
        output(&m, t, 0, MC_MODE_ON, 0, 0, 0);
        t += 1500;
    } else if (strcmp(v->name, "out4_command_refused") == 0) {
        cmd0(&m, t, MC_OP_CLEAR_FRESH);
        output(&m, t, 0, MC_MODE_ON, 0, 0, 0);
        cmd1(&m, t, MC_OP_LEASE, 51);
    } else if (strcmp(v->name, "m8001_hit_on_channel_0_light_on") == 0) {
        cmd0(&m, t, MC_OP_CLEAR_FRESH);
        cmd1(&m, t, MC_OP_ARM, 0x01);
        mc_event(&m, 0, MC_EVENT_HIT, 1, t);
        cmd1(&m, t, MC_OP_ACK, 0);
        mc_event(&m, 0, MC_EVENT_HIT, 90, t);
        output(&m, t, 1, MC_MODE_ON, 0, 0, 0);
        t += 1000;
    } else {
        return false; /* not a state a module with a 16-event queue comes to (OVERFLOW, no MORE) */
    }
    status(&m, t, got);
    return true;
}

static void test_status_vectors(void)
{
    int reached = 0;
    for (size_t i = 0; i < MCV_STATUS_COUNT; i++) {
        const mcv_status_t *v = &mcv_statuses[i];
        mc_status_t s = {v->flags, v->seq,    v->channel, v->kind,
                         v->value, v->age_ms, v->outputs, v->armed};
        uint8_t got[MC_STATUS_LEN];
        mc_status_encode(&s, got);
        CHECK_NAMED(memcmp(got, v->bytes, MC_STATUS_LEN) == 0, v->name);
        if (status_reached(v, got)) {
            reached++;
            CHECK_NAMED(memcmp(got, v->bytes, MC_STATUS_LEN) == 0, v->name);
        }
    }
    CHECK(reached == (int)MCV_STATUS_COUNT - 1);
}

static void test_command_vectors(void)
{
    int taken = 0, refused = 0;
    for (size_t i = 0; i < MCV_COMMAND_COUNT; i++) {
        const mcv_command_t *v = &mcv_commands[i];
        mc_module_t m;
        hw_t hw;
        CHECK_NAMED(start(&m, &hw, v->module, v->address, 0), v->name);
        uint8_t before_flags = mc_status_flags(&m);
        mc_result_t r = mc_write(&m, v->bytes, v->len, 100);
        CHECK_NAMED(mc_last_result(&m) == r, v->name);
        if (v->reason == NULL) {
            taken++;
            CHECK_NAMED(r == MC_OK, v->name);
            CHECK_NAMED(!(mc_status_flags(&m) & MC_ST_CMD_ERROR), v->name);
        } else {
            refused++;
            CHECK_NAMED(strcmp(mc_result_name(r), v->reason) == 0, v->name);
            /* refused: CMD_ERROR, and nothing else changed */
            CHECK_NAMED(mc_status_flags(&m) == (before_flags | MC_ST_CMD_ERROR), v->name);
            CHECK_NAMED(mc_outputs(&m) == 0 && mc_armed(&m) == 0, v->name);
            CHECK_NAMED(m.lease_ms == 1500 && !m.has_deadline, v->name);
            CHECK_NAMED(hw.total_calls == 0 || hw_pins(&hw) == 0, v->name);
            /* and the next accepted write clears it */
            CHECK_NAMED(cmd0(&m, 200, MC_OP_ALL_OFF) == MC_OK, v->name);
            CHECK_NAMED(!(mc_status_flags(&m) & MC_ST_CMD_ERROR), v->name);
        }
    }
    CHECK(taken == 19 && refused == (int)MCV_COMMAND_COUNT - 19);
}

/* The lease's timelines: each step at its time, its write delivered (or lost) through the I2C
 * calls, then the STATUS the box would read, and the pins the module drives, against the file. */
static void test_timelines(void)
{
    for (size_t i = 0; i < MCV_TIMELINE_COUNT; i++) {
        const mcv_timeline_t *tl = &mcv_timelines[i];
        mc_module_t m;
        hw_t hw;
        CHECK_NAMED(start(&m, &hw, tl->module, mcv_modules[tl->module].address, 0), tl->name);
        for (size_t s = 0; s < tl->count; s++) {
            const mcv_step_t *st = &tl->steps[s];
            char what[96];
            snprintf(what, sizeof(what), "%s step %zu at %u ms", tl->name, s, (unsigned)st->t_ms);
            mc_tick(&m, st->t_ms);
            if (st->what == MCV_RESTART) {
                mc_config_t c = m.cfg;
                mc_ops_t ops = m.ops;
                CHECK_NAMED(mc_init(&m, &c, &ops, st->t_ms), what);
            } else if (st->what == MCV_WRITE && st->delivered) {
                mc_result_t r = mc_write(&m, st->bytes, st->len, st->t_ms);
                CHECK_NAMED((r == MC_OK) == st->accepted, what);
            }
            if (!st->has_expect) continue;
            uint8_t got[MC_STATUS_LEN];
            status(&m, st->t_ms, got);
            CHECK_NAMED(mc_crc8(0, got, 8) == got[8], what);
            CHECK_NAMED(got[6] == st->expect_outputs, what);
            uint8_t mask = MC_ST_LEASE_EXPIRED | MC_ST_FRESH | MC_ST_CMD_ERROR;
            CHECK_NAMED((got[0] & mask) == st->expect_flags, what);
            CHECK_NAMED(hw_pins(&hw) == st->expect_outputs, what);
        }
    }
}

/* ---- set-up and power-up -------------------------------------------------- */

static void test_init(void)
{
    hw_t hw;
    mc_module_t m;
    int out4 = module_index("out4");
    mc_ops_t ops = {&hw, hw_set_output, hw_supply_ok};

    /* power-up: every output driven off once, FRESH, the default lease */
    memset(&hw, 0, sizeof(hw));
    for (int i = 0; i < 4; i++) hw.pin[i] = true; /* whatever the pins did before */
    mc_config_t c = config_of(out4, 0x5C);
    CHECK(mc_init(&m, &c, &ops, 0));
    CHECK(hw_pins(&hw) == 0);
    for (int i = 0; i < 4; i++) CHECK(hw.calls[i] == 1);
    CHECK(mc_status_flags(&m) == MC_ST_FRESH);
    CHECK(m.lease_ms == 1500);
    CHECK(mc_armed(&m) == 0);

    mc_config_t bad;
    bad = c, bad.address = 0x57;
    CHECK(!mc_init(&m, &bad, &ops, 0));
    bad = c, bad.address = 0x60;
    CHECK(!mc_init(&m, &bad, &ops, 0));
    bad = c, bad.channel_count = 0;
    CHECK(!mc_init(&m, &bad, &ops, 0));
    bad = c, bad.channel_count = 9;
    CHECK(!mc_init(&m, &bad, &ops, 0));
    bad = c, bad.channels[0].max_on_s = 0;
    CHECK(!mc_init(&m, &bad, &ops, 0));
    bad = c, bad.channels[0].flags = MC_CH_RELAY | MC_CH_SOLID_STATE;
    CHECK(!mc_init(&m, &bad, &ops, 0));
    bad = c, bad.channels[0].flags = MC_CH_SENSES_SUPPLY;
    CHECK(!mc_init(&m, &bad, &ops, 0));
    bad = c, bad.channels[0].kind = 0x20;
    CHECK(!mc_init(&m, &bad, &ops, 0));
    mc_ops_t no_pins = {&hw, NULL, NULL};
    CHECK(!mc_init(&m, &c, &no_pins, 0));
    CHECK(!mc_init(&m, &c, NULL, 0));

    mc_config_t t = config_of(module_index("target"), 0x58);
    bad = t, bad.channels[0].max_on_s = 5;
    CHECK(!mc_init(&m, &bad, NULL, 0));
    CHECK(mc_init(&m, &t, NULL, 0)); /* an input-only module needs no pins */
    t.channels[0].kind = MC_KIND_CONTACT;
    CHECK(mc_init(&m, &t, NULL, 0));
    uint8_t ident[MC_IDENT_LEN];
    mc_ident_encode(&m.cfg, ident);
    CHECK(ident[3] == 0x01 && ident[4] == 1);

    CHECK(strcmp(mc_result_name(MC_REFUSED_MIN_OFF), "min_off") == 0);
    CHECK(strcmp(mc_result_name(MC_REFUSED_RELAY_CHANGE), "relay_change") == 0);
    CHECK(strcmp(mc_result_name((mc_result_t)99), "?") == 0);
}

/* ---- the I2C target ------------------------------------------------------- */

static void test_i2c(void)
{
    mc_module_t m;
    hw_t hw;
    int out4 = module_index("out4");
    uint8_t got[MC_STATUS_LEN];
    start(&m, &hw, out4, 0x5C, 0);

    /* No register chosen yet: 0xFF, as an empty bus. */
    mc_read(&m, got, 3, 0);
    CHECK(got[0] == 0xFF && got[1] == 0xFF && got[2] == 0xFF);
    /* A request outside any read is 0xFF too. */
    CHECK(mc_i2c_request(&m) == 0xFF);

    /* The box's probe, an address with no byte, changes nothing. */
    mc_i2c_start(&m, false, 0);
    mc_i2c_stop(&m, 0);
    CHECK(mc_status_flags(&m) == MC_ST_FRESH);

    /* A refused write shows CMD_ERROR; the STATUS pointer write of the next poll leaves it. */
    CHECK(cmd1(&m, 10, MC_OP_LEASE, 4) == MC_REFUSED_RANGE);
    status(&m, 20, got);
    CHECK(got[0] & MC_ST_CMD_ERROR);
    status(&m, 30, got);
    CHECK(got[0] & MC_ST_CMD_ERROR);
    uint8_t ptr[2] = {MC_REG_CHANNEL, 1};
    mc_write(&m, ptr, 2, 30);
    CHECK(mc_status_flags(&m) & MC_ST_CMD_ERROR);
    CHECK(mc_last_result(&m) == MC_REFUSED_RANGE);

    /* A pointer write and the read after a repeated start, with no stop between. */
    mc_i2c_start(&m, false, 40);
    mc_i2c_receive(&m, MC_REG_CHANNEL);
    mc_i2c_receive(&m, 2);
    mc_i2c_start(&m, true, 40);
    uint8_t ch[MC_CHANNEL_LEN];
    for (unsigned i = 0; i < MC_CHANNEL_LEN; i++) ch[i] = mc_i2c_request(&m);
    CHECK(mc_i2c_request(&m) == 0xFF); /* past the register's end */
    mc_i2c_stop(&m, 40);
    CHECK(ch[0] == 2 && ch[1] == MC_KIND_OUTPUT && ch[4] == 30 && ch[5] == 30);
    CHECK(mc_crc8(0, ch, 7) == ch[7]);

    /* A channel the module does not have: 0xFF, which the box refuses (its CRC). */
    uint8_t ptr9[2] = {MC_REG_CHANNEL, 4};
    CHECK(mc_write(&m, ptr9, 2, 50) == MC_OK);
    mc_read(&m, ch, MC_CHANNEL_LEN, 50);
    for (unsigned i = 0; i < MC_CHANNEL_LEN; i++) CHECK(ch[i] == 0xFF);

    /* A COMMAND that a repeated start ends is taken then, and the read after it sees it. */
    uint8_t frame[4] = {MC_REG_COMMAND, MC_OP_CLEAR_FRESH, 0};
    uint8_t ab = 0x5C << 1;
    frame[2] = mc_crc8(mc_crc8(0, &ab, 1), frame, 2);
    mc_i2c_start(&m, false, 60);
    for (int i = 0; i < 3; i++) mc_i2c_receive(&m, frame[i]);
    mc_i2c_start(&m, true, 60); /* the pointer is still CHANNEL 4: 0xFF */
    CHECK(mc_i2c_request(&m) == 0xFF);
    mc_i2c_stop(&m, 60);
    CHECK(!(mc_status_flags(&m) & MC_ST_FRESH));
    CHECK(!(mc_status_flags(&m) & MC_ST_CMD_ERROR));

    /* Bytes a read ignores; a byte received outside a write is ignored. */
    mc_i2c_receive(&m, 0x55);
    CHECK(mc_status_flags(&m) == 0);

    /* A write longer than any frame: its CRC is still checked over every byte. */
    uint8_t lng[21];
    memset(lng, 0, sizeof(lng));
    lng[0] = MC_REG_COMMAND;
    lng[1] = MC_OP_ALL_OFF;
    lng[20] = mc_crc8(mc_crc8(0, &ab, 1), lng, 20);
    CHECK(mc_write(&m, lng, 21, 70) == MC_REFUSED_LENGTH);
    lng[20] ^= 1;
    CHECK(mc_write(&m, lng, 21, 70) == MC_REFUSED_CRC);
    lng[0] = MC_REG_IDENT;
    lng[20] = mc_crc8(mc_crc8(0, &ab, 1), lng, 20);
    CHECK(mc_write(&m, lng, 21, 70) == MC_REFUSED_REGISTER);
    /* A pointer to IDENT with an extra byte is a write to a read-only register. */
    uint8_t ident2[3] = {MC_REG_IDENT, 0, 0};
    ident2[2] = mc_crc8(mc_crc8(0, &ab, 1), ident2, 2);
    CHECK(mc_write(&m, ident2, 3, 70) == MC_REFUSED_REGISTER);
    /* One byte that is not a pointer: too short to hold a CRC. */
    uint8_t one = MC_REG_COMMAND;
    CHECK(mc_write(&m, &one, 1, 70) == MC_REFUSED_CRC);
    uint8_t chan_only = MC_REG_CHANNEL;
    CHECK(mc_write(&m, &chan_only, 1, 70) == MC_REFUSED_CRC);
}

/* ---- inputs and the event queue ------------------------------------------- */

static void test_events(void)
{
    mc_module_t m;
    hw_t hw;
    uint8_t got[MC_STATUS_LEN];
    int target = module_index("target");
    start(&m, &hw, target, 0x58, 0);

    /* Disarmed at power-up: events are dropped. */
    CHECK(!mc_event(&m, 0, MC_EVENT_HIT, 50, 0));
    CHECK(cmd1(&m, 0, MC_OP_ARM, 0x01) == MC_OK);
    /* Not its kind, not a channel, not an input. */
    CHECK(!mc_event(&m, 0, MC_EVENT_CLOSED, 0, 0));
    CHECK(!mc_event(&m, 1, MC_EVENT_HIT, 50, 0));
    CHECK(!mc_event(&m, 0, 0, 50, 0));

    /* 16 held; the 17th dropped with OVERFLOW; the shown event stays the oldest. */
    for (int i = 0; i < 16; i++) CHECK(mc_event(&m, 0, MC_EVENT_HIT, (uint8_t)i, (uint32_t)i));
    CHECK(!mc_event(&m, 0, MC_EVENT_HIT, 99, 20));
    status(&m, 100, got);
    CHECK(got[0] == (MC_ST_EVENT | MC_ST_MORE | MC_ST_OVERFLOW | MC_ST_FRESH));
    CHECK(got[1] == 0 && got[2] == 0x10 && got[3] == 0 && got[4] == 100 && got[5] == 0);
    CHECK(got[7] == 0x01);
    /* OVERFLOW was reported by that read: gone from the next. */
    status(&m, 101, got);
    CHECK(!(got[0] & MC_ST_OVERFLOW));
    /* A wrong or repeated ACK is taken and changes nothing. */
    CHECK(cmd1(&m, 102, MC_OP_ACK, 5) == MC_OK);
    status(&m, 103, got);
    CHECK(got[1] == 0);
    /* ACK walks the queue; the dropped event took no number. */
    for (uint8_t s = 0; s < 15; s++) CHECK(cmd1(&m, 104, MC_OP_ACK, s) == MC_OK);
    status(&m, 105, got);
    CHECK(got[0] == (MC_ST_EVENT | MC_ST_FRESH) && got[1] == 15 && got[3] == 15);
    CHECK(cmd1(&m, 106, MC_OP_ACK, 15) == MC_OK);
    status(&m, 107, got);
    CHECK((got[0] & (MC_ST_EVENT | MC_ST_MORE)) == 0);
    CHECK(got[1] == 0 && got[2] == 0 && got[3] == 0 && got[4] == 0 && got[5] == 0);
    CHECK(mc_event(&m, 0, MC_EVENT_HIT, 1, 107));
    status(&m, 107, got);
    CHECK(got[1] == 16);

    /* A read cut short does not count as reporting OVERFLOW. */
    start(&m, &hw, target, 0x58, 0);
    cmd1(&m, 0, MC_OP_ARM, 0x01);
    for (int i = 0; i < 17; i++) mc_event(&m, 0, MC_EVENT_HIT, 1, 0);
    uint8_t reg = MC_REG_STATUS;
    mc_write(&m, &reg, 1, 1);
    mc_read(&m, got, 4, 1);
    CHECK(got[0] & MC_ST_OVERFLOW);
    CHECK(mc_status_flags(&m) & MC_ST_OVERFLOW);
    status(&m, 2, got);
    CHECK(got[0] & MC_ST_OVERFLOW);
    CHECK(!(mc_status_flags(&m) & MC_ST_OVERFLOW));

    /* The sequence wraps; the age saturates; an event stamped after the clock reads age 0. */
    start(&m, &hw, target, 0x58, 0);
    cmd1(&m, 0, MC_OP_ARM, 0x01);
    for (int s = 0; s < 256; s++) {
        mc_event(&m, 0, MC_EVENT_HIT, 1, 0);
        cmd1(&m, 0, MC_OP_ACK, (uint8_t)s);
    }
    CHECK(mc_event(&m, 0, MC_EVENT_HIT, 7, 0));
    status(&m, 70000, got);
    CHECK(got[1] == 0 && got[3] == 7 && got[4] == 0xFF && got[5] == 0xFF);
    cmd1(&m, 70000, MC_OP_ACK, 0);
    CHECK(mc_event(&m, 0, MC_EVENT_HIT, 8, 70500));
    status(&m, 70001, got);
    CHECK(got[1] == 1 && got[4] == 0 && got[5] == 0);

    /* Disarming drops the held events of that channel, and only those. */
    int m8001 = module_index("m8001");
    mc_config_t two = config_of(m8001, 0x5D);
    two.channels[1] = two.channels[0]; /* two hit channels */
    mc_ops_t ops = {&hw, hw_set_output, hw_supply_ok};
    CHECK(mc_init(&m, &two, &ops, 0));
    CHECK(cmd1(&m, 0, MC_OP_ARM, 0x03) == MC_OK);
    mc_event(&m, 0, MC_EVENT_HIT, 10, 0);
    mc_event(&m, 1, MC_EVENT_HIT, 11, 0);
    mc_event(&m, 0, MC_EVENT_HIT, 12, 0);
    mc_event(&m, 1, MC_EVENT_HIT, 13, 0);
    CHECK(cmd1(&m, 1, MC_OP_ARM, 0x02) == MC_OK);
    status(&m, 2, got);
    CHECK(got[0] & MC_ST_MORE);
    CHECK(got[2] == 0x11 && got[3] == 11 && got[1] == 1 && got[7] == 0x02);
    cmd1(&m, 3, MC_OP_ACK, 1);
    status(&m, 4, got);
    CHECK(!(got[0] & MC_ST_MORE) && got[3] == 13 && got[1] == 3);
    /* ARM naming an output or a missing channel is refused and changes nothing. */
    start(&m, &hw, m8001, 0x5D, 0);
    CHECK(cmd1(&m, 0, MC_OP_ARM, 0x01) == MC_OK);
    CHECK(cmd1(&m, 0, MC_OP_ARM, 0x03) == MC_REFUSED_RANGE);
    CHECK(cmd1(&m, 0, MC_OP_ARM, 0x05) == MC_REFUSED_RANGE);
    CHECK(mc_armed(&m) == 0x01);

    /* A contact channel takes closed and opened. */
    mc_config_t contact = config_of(target, 0x58);
    contact.channels[0].kind = MC_KIND_CONTACT;
    CHECK(mc_init(&m, &contact, NULL, 0));
    cmd1(&m, 0, MC_OP_ARM, 0x01);
    CHECK(!mc_event(&m, 0, MC_EVENT_HIT, 1, 0));
    CHECK(mc_event(&m, 0, MC_EVENT_CLOSED, 0, 0));
    CHECK(mc_event(&m, 0, MC_EVENT_OPENED, 0, 5));
    status(&m, 5, got);
    CHECK(got[2] == 0x20 && got[4] == 5);

    /* CONFIG keeps an input's tuning for the firmware; LOCATE for its LED. */
    start(&m, &hw, target, 0x58, 0);
    CHECK(mc_config_value(&m, 0, MC_PARAM_THRESHOLD) == 30);
    CHECK(mc_config_value(&m, 0, MC_PARAM_HOLDOFF_MS) == 50);
    uint8_t cfgv[5] = {MC_OP_CONFIG, 0, MC_PARAM_HOLDOFF_MS, 0x2C, 0x01};
    CHECK(command(&m, 0, cfgv, 5) == MC_OK);
    CHECK(mc_config_value(&m, 0, MC_PARAM_HOLDOFF_MS) == 300);
    CHECK(mc_config_value(&m, 0, 4) == 0 && mc_config_value(&m, 1, 1) == 0);
    uint8_t cfg0[5] = {MC_OP_CONFIG, 0, 0, 1, 0};
    CHECK(command(&m, 0, cfg0, 5) == MC_REFUSED_RANGE);
    CHECK(!mc_locating(&m, 0));
    CHECK(cmd1(&m, 1000, MC_OP_LOCATE, 3) == MC_OK);
    CHECK(mc_locating(&m, 3999));
    CHECK(!mc_locating(&m, 4000));
    CHECK(cmd1(&m, 5000, MC_OP_LOCATE, 10) == MC_OK);
    CHECK(cmd1(&m, 6000, MC_OP_LOCATE, 0) == MC_OK);
    CHECK(!mc_locating(&m, 6000));
}

/* ---- outputs, the lease and the limits ------------------------------------ */

static void test_outputs(void)
{
    mc_module_t m;
    hw_t hw;
    uint8_t got[MC_STATUS_LEN];
    int out4 = module_index("out4");

    /* The lease only runs out while an output is on. */
    start(&m, &hw, out4, 0x5C, 0);
    cmd1(&m, 0, MC_OP_LEASE, 15);
    mc_tick(&m, 5000);
    CHECK(!(mc_status_flags(&m) & MC_ST_LEASE_EXPIRED));
    /* The longest lease: on until 5 s after the last refresh. */
    CHECK(cmd1(&m, 5000, MC_OP_LEASE, 50) == MC_OK);
    CHECK(output(&m, 5000, 0, MC_MODE_ON, 0, 0, 0) == MC_OK);
    mc_tick(&m, 9999);
    CHECK(hw_pins(&hw) == 0x01);
    mc_tick(&m, 10000);
    CHECK(hw_pins(&hw) == 0 && (mc_status_flags(&m) & MC_ST_LEASE_EXPIRED));
    /* ALL_OFF and CLEAR_FRESH leave LEASE_EXPIRED; a LEASE clears it. */
    cmd0(&m, 10001, MC_OP_ALL_OFF);
    cmd0(&m, 10001, MC_OP_CLEAR_FRESH);
    CHECK(mc_status_flags(&m) & MC_ST_LEASE_EXPIRED);
    cmd1(&m, 10002, MC_OP_LEASE, 15);
    CHECK(!(mc_status_flags(&m) & MC_ST_LEASE_EXPIRED));
    /* The lease turns every output off, the solid-state pattern too. */
    output(&m, 11000, 0, MC_MODE_ON, 0, 0, 0);
    output(&m, 11000, 3, MC_MODE_PATTERN, 0, 2, 2);
    mc_tick(&m, 12499);
    CHECK(mc_outputs(&m) & 0x01);
    mc_tick(&m, 12500);
    CHECK(mc_outputs(&m) == 0 && hw_pins(&hw) == 0);

    /* A duration ending at the lease's moment ends by its duration. */
    start(&m, &hw, out4, 0x5C, 0);
    output(&m, 0, 0, MC_MODE_ON, 15, 0, 0);
    mc_tick(&m, 1500);
    CHECK(hw_pins(&hw) == 0 && !(mc_status_flags(&m) & MC_ST_LEASE_EXPIRED));
    /* So does a max on: a 1 s channel under a 1 s lease. */
    mc_config_t c = config_of(out4, 0x5C);
    c.channels[3].max_on_s = 1;
    mc_ops_t ops = {&hw, hw_set_output, hw_supply_ok};
    CHECK(mc_init(&m, &c, &ops, 0));
    cmd1(&m, 0, MC_OP_LEASE, 10);
    output(&m, 0, 3, MC_MODE_ON, 0, 0, 0);
    status(&m, 1000, got);
    CHECK(got[6] == 0 && !(got[0] & MC_ST_LEASE_EXPIRED));
    /* min off 0: on again at once */
    CHECK(output(&m, 1000, 3, MC_MODE_ON, 0, 0, 0) == MC_OK);

    /* A second on keeps the first on's time for the max on (smoke: 30 s on, 30 s off). */
    start(&m, &hw, out4, 0x5C, 0);
    output(&m, 0, 2, MC_MODE_ON, 0, 0, 0);
    for (uint32_t t = 500; t < 20000; t += 500) cmd1(&m, t, MC_OP_LEASE, 15);
    output(&m, 20000, 2, MC_MODE_ON, 0, 0, 0);
    for (uint32_t t = 20500; t < 30000; t += 500) cmd1(&m, t, MC_OP_LEASE, 15);
    mc_tick(&m, 29999);
    CHECK(hw_pins(&hw) == 0x04);
    mc_tick(&m, 30000);
    CHECK(hw_pins(&hw) == 0);
    /* min off refuses a pattern too; an off is never refused */
    CHECK(output(&m, 45000, 2, MC_MODE_PATTERN, 0, 10, 10) == MC_REFUSED_MIN_OFF);
    CHECK(output(&m, 45000, 2, MC_MODE_OFF, 0, 0, 0) == MC_OK);
    CHECK(output(&m, 60000, 2, MC_MODE_PATTERN, 0, 10, 10) == MC_OK);

    /* A relay: at most every 100 ms, also after a pattern's on time; while on, any change goes. */
    start(&m, &hw, out4, 0x5C, 0);
    CHECK(output(&m, 0, 1, MC_MODE_PATTERN, 0, 10, 10) == MC_OK);
    mc_tick(&m, 150);
    CHECK(hw_pins(&hw) == 0); /* off since 100 */
    CHECK(output(&m, 150, 1, MC_MODE_ON, 0, 0, 0) == MC_REFUSED_RELAY_CHANGE);
    CHECK(output(&m, 199, 1, MC_MODE_PATTERN, 0, 10, 10) == MC_REFUSED_RELAY_CHANGE);
    CHECK(output(&m, 210, 1, MC_MODE_ON, 0, 0, 0) == MC_OK); /* in its on time */
    CHECK(hw_pins(&hw) == 0x02);
    CHECK(output(&m, 220, 1, MC_MODE_OFF, 0, 0, 0) == MC_OK);
    CHECK(output(&m, 319, 1, MC_MODE_ON, 0, 0, 0) == MC_REFUSED_RELAY_CHANGE);
    CHECK(output(&m, 320, 1, MC_MODE_ON, 0, 0, 0) == MC_OK);
    /* ALL_OFF counts as the relay turning off. */
    cmd0(&m, 400, MC_OP_ALL_OFF);
    CHECK(output(&m, 450, 1, MC_MODE_ON, 0, 0, 0) == MC_REFUSED_RELAY_CHANGE);
    /* A solid-state channel switches as fast as it is told. */
    CHECK(output(&m, 450, 3, MC_MODE_ON, 0, 0, 0) == MC_OK);
    CHECK(output(&m, 451, 3, MC_MODE_OFF, 0, 0, 0) == MC_OK);
    CHECK(output(&m, 452, 3, MC_MODE_ON, 0, 0, 0) == MC_OK);

    /* A solid-state pattern's edges reach the pin, each once. */
    start(&m, &hw, out4, 0x5C, 0);
    output(&m, 0, 3, MC_MODE_PATTERN, 0, 1, 1); /* 10 ms on, 10 ms off */
    for (uint32_t t = 1; t <= 100; t++) mc_tick(&m, t);
    CHECK(hw.calls[3] == 12);    /* off at power-up, on at 0, then 10 edges (10 ms to 100 ms) */
    CHECK(hw_pins(&hw) == 0x08); /* at 100 ms, a new on time */

    /* A refused OUTPUT does not refresh the lease. */
    start(&m, &hw, out4, 0x5C, 0);
    output(&m, 0, 0, MC_MODE_ON, 0, 0, 0);
    CHECK(output(&m, 1000, 5, MC_MODE_ON, 0, 0, 0) == MC_REFUSED_RANGE);
    mc_tick(&m, 1500);
    CHECK(hw_pins(&hw) == 0 && (mc_status_flags(&m) & MC_ST_LEASE_EXPIRED));
    /* An OUTPUT off refreshes it and clears LEASE_EXPIRED. */
    CHECK(output(&m, 1600, 1, MC_MODE_OFF, 0, 0, 0) == MC_OK);
    CHECK(!(mc_status_flags(&m) & MC_ST_LEASE_EXPIRED));

    /* SUPPLY_OK only from a module with a channel that senses it. */
    start(&m, &hw, out4, 0x5C, 0);
    hw.supply = true;
    CHECK(mc_status_flags(&m) & MC_ST_SUPPLY_OK);
    hw.supply = false;
    CHECK(!(mc_status_flags(&m) & MC_ST_SUPPLY_OK));
    start(&m, &hw, module_index("m8001"), 0x5D, 0);
    hw.supply = true;
    CHECK(!(mc_status_flags(&m) & MC_ST_SUPPLY_OK));

    /* A restart (mc_init again) comes back off and FRESH. */
    start(&m, &hw, out4, 0x5C, 0);
    cmd0(&m, 0, MC_OP_CLEAR_FRESH);
    output(&m, 0, 0, MC_MODE_ON, 0, 0, 0);
    CHECK(hw_pins(&hw) == 0x01);
    mc_config_t again = m.cfg;
    mc_ops_t ops2 = m.ops;
    mc_init(&m, &again, &ops2, 100);
    CHECK(hw_pins(&hw) == 0 && mc_status_flags(&m) == MC_ST_FRESH);

    /* The clock never goes back. */
    start(&m, &hw, out4, 0x5C, 1000);
    output(&m, 1000, 0, MC_MODE_ON, 5, 0, 0);
    mc_tick(&m, 500);
    CHECK(hw_pins(&hw) == 0x01);
    mc_tick(&m, 1500);
    CHECK(hw_pins(&hw) == 0);
    /* A write stamped before the core's clock counts from the clock. */
    start(&m, &hw, out4, 0x5C, 0);
    mc_tick(&m, 1000);
    output(&m, 500, 3, MC_MODE_ON, 5, 0, 0);
    mc_tick(&m, 1499);
    CHECK(hw_pins(&hw) == 0x08);
    mc_tick(&m, 1500);
    CHECK(hw_pins(&hw) == 0);
}

/* The millisecond clock wraps after 49 days: timers across it. */
static void test_clock_wrap(void)
{
    mc_module_t m;
    hw_t hw;
    int out4 = module_index("out4");
    const uint32_t t0 = 0xFFFFFC00u; /* 1024 ms before the wrap */
    start(&m, &hw, out4, 0x5C, t0);
    output(&m, t0, 0, MC_MODE_ON, 10, 0, 0); /* 1 s */
    mc_tick(&m, t0 + 999);
    CHECK(hw_pins(&hw) == 0x01);
    mc_tick(&m, t0 + 1000);
    CHECK(hw_pins(&hw) == 0 && !(mc_status_flags(&m) & MC_ST_LEASE_EXPIRED));
    /* the lease across the wrap */
    output(&m, t0 + 1000, 1, MC_MODE_ON, 0, 0, 0);
    mc_tick(&m, t0 + 2499);
    CHECK(hw_pins(&hw) == 0x02);
    mc_tick(&m, t0 + 2500);
    CHECK(hw_pins(&hw) == 0 && (mc_status_flags(&m) & MC_ST_LEASE_EXPIRED));
    /* min off across the wrap, and long after it */
    output(&m, t0 + 3000, 2, MC_MODE_ON, 0, 0, 0);
    for (uint32_t t = 500; t <= 30000; t += 500) cmd1(&m, t0 + 3000 + t, MC_OP_LEASE, 15);
    mc_tick(&m, t0 + 33000);
    CHECK(hw_pins(&hw) == 0);
    CHECK(output(&m, t0 + 62999, 2, MC_MODE_ON, 0, 0, 0) == MC_REFUSED_MIN_OFF);
    CHECK(output(&m, t0 + 63000, 2, MC_MODE_ON, 10, 0, 0) == MC_OK);
    /* an event's age across the wrap */
    start(&m, &hw, module_index("target"), 0x58, t0);
    cmd1(&m, t0, MC_OP_ARM, 0x01);
    mc_event(&m, 0, MC_EVENT_HIT, 1, t0 + 1000);
    uint8_t got[MC_STATUS_LEN];
    status(&m, t0 + 1300, got);
    CHECK(got[4] == 44 && got[5] == 1); /* 300 ms */
    /* 25 days on, a min off long passed is not back */
    start(&m, &hw, out4, 0x5C, 0);
    output(&m, 0, 2, MC_MODE_ON, 0, 0, 0);
    for (uint32_t t = 500; t <= 30000; t += 500) cmd1(&m, t, MC_OP_LEASE, 15);
    mc_tick(&m, 31000);
    mc_tick(&m, 0x7FFF0000u);
    CHECK(output(&m, 0x7FFF0000u, 2, MC_MODE_ON, 10, 0, 0) == MC_OK);
}

int main(void)
{
    test_crc();
    test_ident_vectors();
    test_channel_vectors();
    test_status_vectors();
    test_command_vectors();
    test_timelines();
    test_init();
    test_i2c();
    test_events();
    test_outputs();
    test_clock_wrap();
    printf("module core: %d checks, %d failed (vectors: %zu IDENT, %zu CHANNEL, %zu STATUS, %zu "
           "COMMAND, "
           "%zu timelines)\n",
           checks, failures, MCV_IDENT_COUNT, MCV_CHANNEL_COUNT, MCV_STATUS_COUNT,
           MCV_COMMAND_COUNT, MCV_TIMELINE_COUNT);
    return failures == 0 ? 0 : 1;
}
