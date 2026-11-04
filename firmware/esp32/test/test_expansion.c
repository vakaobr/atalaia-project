/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Tests for the expansion port's driver, the box's side (expansion.c; draft RFC "The expansion
 * port", increment 6): every case of protocol/vectors/expansion.json (the CRC-8 and every frame
 * through expansion_vectors.h; fields, reasons, modules and timelines through
 * expansion_cases.h), the C model of a module (expansion_model.c) against the same cases, and
 * the driver against the model on a fake bus: discovery, IDENT, polling, events, retries, loss,
 * output reconciliation and the lease. Four of the lease's timelines are replayed by the driver
 * itself, write for write.
 */
#include <stdio.h>
#include <string.h>

#include "check.h"
#include "expansion.h"
#include "expansion_cases.h"
#include "expansion_model.h"
#include "expansion_vectors.h"

static void named(bool ok, const char *what, const char *name)
{
    if (!ok) fprintf(stderr, "  expansion %s: %s\n", what, name);
    CHECK(ok);
}

static bool same(const char *a, const char *b)
{
    if (a == NULL || b == NULL) return a == b;
    return strcmp(a, b) == 0;
}

static exp_command_t to_cmd(const exp_cmd_case_t *f)
{
    exp_command_t c = {0};
    c.op = f->op;
    c.seq = f->seq;
    c.armed = f->armed;
    c.channel = f->channel;
    c.mode = f->mode;
    c.duration_100ms = f->duration_100ms;
    c.on_10ms = f->on_10ms;
    c.off_10ms = f->off_10ms;
    c.lease_100ms = f->lease_100ms;
    c.seconds = f->seconds;
    c.parameter = f->parameter;
    c.value = f->value;
    return c;
}

static const exp_module_case_t *module_case(const char *name)
{
    for (size_t i = 0; i < EXP_MODULE_CASE_COUNT; i++) {
        if (strcmp(exp_module_cases[i].name, name) == 0) return &exp_module_cases[i];
    }
    return NULL;
}

static void model_of(exp_model_t *m, const char *name, int address)
{
    const exp_module_case_t *mc = module_case(name);
    CHECK(mc != NULL);
    if (mc == NULL) return;
    exp_model_init(m, (uint8_t)(address >= 0 ? address : mc->address), mc->ident, mc->channel,
                   mc->channels);
}

/* ---- The frames ------------------------------------------------------------------------- */

/* The CRC-8 (EXP-9): the shared cases, and every frame of the file, a write's CRC covering the
 * address byte as sent. */
static void test_crc8(void)
{
    const uint8_t s[] = "123456789";
    CHECK(expansion_crc8(s, 9) == 0xF4);
    CHECK(expansion_crc8(s, 0) == 0x00);
    CHECK(EXP_CRC_VECTOR_COUNT >= 7);
    for (size_t i = 0; i < EXP_CRC_VECTOR_COUNT; i++) {
        const exp_crc_vector_t *v = &exp_crc_vectors[i];
        named(expansion_crc8(v->data, v->len) == v->crc, "crc", v->name);
    }
    size_t reads = 0, writes = 0;
    for (size_t i = 0; i < EXP_FRAME_VECTOR_COUNT; i++) {
        const exp_frame_vector_t *v = &exp_frame_vectors[i];
        uint8_t covered[32];
        size_t n = 0;
        named(v->len >= 1 && v->len < sizeof(covered), "frame", v->name);
        if (v->len < 1 || v->len >= sizeof(covered)) continue;
        if (v->address >= 0) {
            covered[n++] = (uint8_t)(v->address << 1);
            writes++;
        } else {
            reads++;
        }
        memcpy(covered + n, v->bytes, v->len - 1);
        n += v->len - 1;
        named((expansion_crc8(covered, n) == v->bytes[v->len - 1]) == v->crc_ok, "frame", v->name);
    }
    CHECK(reads >= 30 && writes >= 40);
}

static void test_ident_cases(void)
{
    int valid = 0, refused = 0;
    for (size_t i = 0; i < EXP_IDENT_CASE_COUNT; i++) {
        const exp_ident_case_t *v = &exp_ident_cases[i];
        exp_ident_t id;
        memset(&id, 0, sizeof(id));
        const char *why = expansion_parse_ident(v->bytes, v->len, &id);
        named(same(why, v->reason), "ident", v->name);
        if (v->reason != NULL) {
            refused++;
            continue;
        }
        valid++;
        char model[8];
        expansion_model_name(id.model, model, sizeof(model));
        named(id.inputs == v->inputs && id.outputs == v->outputs && id.channels == v->channels &&
                  id.model == v->model && strcmp(model, v->model_name) == 0 && id.hw == v->hw &&
                  memcmp(id.fw, v->fw, 3) == 0 && memcmp(id.uid, v->uid, 4) == 0,
              "ident fields", v->name);
    }
    CHECK(valid == 3 && refused == 10);
}

static void test_channel_cases(void)
{
    int valid = 0, refused = 0;
    for (size_t i = 0; i < EXP_CHANNEL_CASE_COUNT; i++) {
        const exp_channel_case_t *v = &exp_channel_cases[i];
        exp_channel_t ch;
        memset(&ch, 0, sizeof(ch));
        const char *why = expansion_parse_channel(v->bytes, v->len, v->index, &ch);
        named(same(why, v->reason), "channel", v->name);
        if (v->reason != NULL) {
            refused++;
            continue;
        }
        valid++;
        named(ch.index == v->index && ch.kind == v->kind &&
                  ((ch.flags & EXP_CH_RELAY) != 0) == v->relay &&
                  ((ch.flags & EXP_CH_SOLID_STATE) != 0) == v->solid_state &&
                  ((ch.flags & EXP_CH_SENSES) != 0) == v->senses_supply && ch.hint == v->hint &&
                  ch.max_on_s == v->max_on_s && ch.min_off_s == v->min_off_s,
              "channel fields", v->name);
    }
    CHECK(valid == 7 && refused == 7);
    /* A hint above 5 counts as generic. */
    uint8_t f[8] = {0, EXP_KIND_OUTPUT, 1, 9, 10, 0, 0, 0};
    f[7] = expansion_crc8(f, 7);
    exp_channel_t ch;
    CHECK(expansion_parse_channel(f, 8, 0, &ch) == NULL && ch.hint == 0);
}

static void test_status_cases(void)
{
    int valid = 0, refused = 0, timed = 0;
    for (size_t i = 0; i < EXP_STATUS_CASE_COUNT; i++) {
        const exp_status_case_t *v = &exp_status_cases[i];
        exp_status_t st;
        const char *why = expansion_parse_status(v->bytes, v->len, v->channels, &st);
        named(same(why, v->reason), "status", v->name);
        if (v->reason != NULL) {
            refused++;
            continue;
        }
        valid++;
        bool ok = st.event == v->event && (st.flags & (uint8_t)~EXP_ST_EVENT) == v->flags &&
                  st.outputs == v->outputs && st.armed == v->armed;
        if (v->event) {
            ok = ok && st.seq == v->seq && st.channel == v->channel && st.kind == v->kind &&
                 st.value == v->value && st.age_ms == v->age_ms;
        }
        named(ok, "status fields", v->name);
        if (v->t_read_ms >= 0) {
            timed++;
            named((int32_t)(v->t_read_ms - st.age_ms) == v->t_event_ms, "status time", v->name);
        }
    }
    CHECK(valid == 8 && refused == 5 && timed == 1);
}

/* The box writes exactly the file's bytes; the model takes the good ones and refuses the others
 * for the file's reason. */
static void test_command_cases(void)
{
    int valid = 0, refused = 0;
    for (size_t i = 0; i < EXP_COMMAND_CASE_COUNT; i++) {
        const exp_command_case_t *v = &exp_command_cases[i];
        exp_model_t m;
        model_of(&m, v->module, v->address);
        if (v->reason == NULL) {
            valid++;
            exp_command_t c = to_cmd(&v->fields);
            uint8_t buf[EXP_COMMAND_MAX];
            size_t n = expansion_encode_command(&c, (uint8_t)v->address, buf, sizeof(buf));
            named(n == v->len && memcmp(buf, v->bytes, n) == 0, "command bytes", v->name);
            named(n >= 3 && n <= EXP_COMMAND_MAX, "command length", v->name);
            named(exp_model_write(&m, 0, v->bytes, v->len) && m.refusal == NULL, "command taken",
                  v->name);
        } else {
            refused++;
            bool taken = exp_model_write(&m, 0, v->bytes, v->len);
            uint8_t outputs, flags;
            exp_model_state(&m, 0, &outputs, &flags);
            named(!taken && same(m.refusal, v->reason) && (flags & EXP_ST_CMD_ERROR),
                  "command refused", v->name);
        }
    }
    CHECK(valid == 19 && refused == 23);
    exp_command_t bad = {0};
    bad.op = 9;
    uint8_t buf[EXP_COMMAND_MAX];
    CHECK(expansion_encode_command(&bad, 0x58, buf, sizeof(buf)) == 0);
    bad.op = EXP_OP_OUTPUT;
    CHECK(expansion_encode_command(&bad, 0x58, buf, 4) == 0);
}

/* A refused write sets CMD_ERROR; the next good one clears it. */
static void test_model_cmd_error(void)
{
    exp_model_t m;
    model_of(&m, "out4", -1);
    const uint8_t too_long[] = {0x10, 0x04, 0x33, 0x47};
    CHECK(!exp_model_write(&m, 0, too_long, sizeof(too_long)));
    uint8_t outputs, flags;
    exp_model_state(&m, 0, &outputs, &flags);
    CHECK(outputs == 0 && flags == (EXP_ST_FRESH | EXP_ST_CMD_ERROR));
    exp_command_t c = {0};
    c.op = EXP_OP_CLEAR_FRESH;
    uint8_t buf[EXP_COMMAND_MAX];
    size_t n = expansion_encode_command(&c, m.addr, buf, sizeof(buf));
    CHECK(exp_model_write(&m, 1, buf, n));
    exp_model_state(&m, 1, &outputs, &flags);
    CHECK(outputs == 0 && flags == 0);
}

#define TIMELINE_FLAGS (EXP_ST_LEASE_EXPIRED | EXP_ST_FRESH | EXP_ST_CMD_ERROR)

/* Every timeline, step by step, on the model (the box's encoder writes each step's bytes). */
static void test_model_timelines(void)
{
    CHECK(EXP_TIMELINE_CASE_COUNT == 7);
    for (size_t i = 0; i < EXP_TIMELINE_CASE_COUNT; i++) {
        const exp_timeline_case_t *tl = &exp_timeline_cases[i];
        exp_model_t m;
        model_of(&m, tl->module, -1);
        for (size_t j = 0; j < tl->count; j++) {
            const exp_step_case_t *s = &tl->steps[j];
            char where[96];
            snprintf(where, sizeof(where), "%s step %u at %ld ms", tl->name, (unsigned)j,
                     (long)s->t_ms);
            uint32_t t = (uint32_t)s->t_ms;
            if (s->write) {
                exp_command_t c = to_cmd(&s->fields);
                uint8_t buf[EXP_COMMAND_MAX];
                size_t n = expansion_encode_command(&c, m.addr, buf, sizeof(buf));
                named(n == s->len && memcmp(buf, s->bytes, n) == 0, "timeline bytes", where);
                if (s->delivered) {
                    named(exp_model_write(&m, t, s->bytes, s->len) == (s->accepted == 1),
                          "timeline write", where);
                }
            }
            if (s->restart) exp_model_restart(&m, t);
            if (s->expect) {
                uint8_t outputs, flags;
                exp_model_state(&m, t, &outputs, &flags);
                named(outputs == s->outputs && (flags & TIMELINE_FLAGS) == s->flags,
                      "timeline state", where);
            }
        }
    }
}

/* ---- A fake bus with models on it ------------------------------------------------------ */

#define LOG_MAX 512

typedef struct {
    uint32_t t;
    uint8_t addr;
    uint8_t bytes[EXP_COMMAND_MAX];
    size_t len;
} logged_t;

typedef struct {
    exp_model_t *at[EXP_ADDR_COUNT];
    bool unplugged[EXP_ADDR_COUNT];
    uint32_t now;
    /* faults */
    int fail_reads;           /* the next N reads fail */
    int corrupt_reads;        /* the next N reads come back with a bad CRC */
    int drop_writes;          /* the next N COMMAND writes are lost after the bus took them */
    uint8_t drop_op;          /* only writes of this op (0: any) */
    uint32_t fail_read_at[4]; /* reads at these times fail */
    int fail_read_at_n;
    uint32_t drop_write_at[4]; /* COMMAND writes at these times are lost ... */
    int drop_write_at_n;
    uint8_t drop_write_at_op; /* ... when of this op (0: any) */
    int suspended_reads;      /* the next N reads are skipped (EXP_BUS_SUSPENDED) */
    /* what happened */
    logged_t log[LOG_MAX];
    int logged;
    char trace[256]; /* the first transactions: P probe, A ALL_OFF, C other command, R read */
    size_t traced;
    int probes, reads;
} fake_bus_t;

static exp_model_t *model_at(fake_bus_t *b, uint8_t addr)
{
    if (addr < EXP_ADDR_FIRST || addr > EXP_ADDR_LAST) return NULL;
    int i = addr - EXP_ADDR_FIRST;
    return b->unplugged[i] ? NULL : b->at[i];
}

static void trace(fake_bus_t *b, char c)
{
    if (b->traced + 1 < sizeof(b->trace)) {
        b->trace[b->traced++] = c;
        b->trace[b->traced] = '\0';
    }
}

static bool at_time(const uint32_t *times, int n, uint32_t t)
{
    for (int i = 0; i < n; i++) {
        if (times[i] == t) return true;
    }
    return false;
}

static bool fake_probe(void *ctx, uint8_t addr)
{
    fake_bus_t *b = (fake_bus_t *)ctx;
    b->probes++;
    trace(b, 'P');
    return model_at(b, addr) != NULL;
}

static int fake_write(void *ctx, uint8_t addr, const uint8_t *data, size_t len)
{
    fake_bus_t *b = (fake_bus_t *)ctx;
    exp_model_t *m = model_at(b, addr);
    if (len > 0 && data[0] == EXP_REG_COMMAND && b->logged < LOG_MAX) {
        logged_t *l = &b->log[b->logged++];
        l->t = b->now;
        l->addr = addr;
        l->len = len < EXP_COMMAND_MAX ? len : EXP_COMMAND_MAX;
        memcpy(l->bytes, data, l->len);
        trace(b, len > 1 && data[1] == EXP_OP_ALL_OFF ? 'A' : 'C');
    }
    if (m == NULL) return EXP_BUS_FAIL;
    bool op_match = b->drop_op == 0 || (len > 1 && data[1] == b->drop_op);
    if (len > 0 && data[0] == EXP_REG_COMMAND && b->drop_writes > 0 && op_match) {
        b->drop_writes--;
        return EXP_BUS_OK; /* lost on the cable: the box cannot tell */
    }
    if (len > 1 && data[0] == EXP_REG_COMMAND &&
        (b->drop_write_at_op == 0 || data[1] == b->drop_write_at_op) &&
        at_time(b->drop_write_at, b->drop_write_at_n, b->now)) {
        return EXP_BUS_OK;
    }
    exp_model_write(m, b->now, data, len);
    return EXP_BUS_OK;
}

static int fake_write_read(void *ctx, uint8_t addr, const uint8_t *out, size_t out_len, uint8_t *in,
                           size_t in_len)
{
    fake_bus_t *b = (fake_bus_t *)ctx;
    b->reads++;
    trace(b, 'R');
    if (b->suspended_reads > 0) {
        b->suspended_reads--;
        return EXP_BUS_SUSPENDED;
    }
    exp_model_t *m = model_at(b, addr);
    if (m == NULL) return EXP_BUS_FAIL;
    if (b->fail_reads > 0) {
        b->fail_reads--;
        return EXP_BUS_FAIL;
    }
    if (at_time(b->fail_read_at, b->fail_read_at_n, b->now)) return EXP_BUS_FAIL;
    exp_model_write(m, b->now, out, out_len);
    exp_model_read(m, b->now, in, in_len);
    if (b->corrupt_reads > 0 && in_len > 0) {
        b->corrupt_reads--;
        in[in_len - 1] ^= 0x5A;
    }
    return EXP_BUS_OK;
}

/* ---- What the driver tells ------------------------------------------------------------- */

#define EVENTS_MAX 64

typedef struct {
    exp_event_t ev[EVENTS_MAX];
    char text[EVENTS_MAX][EXP_MODULES_TEXT_MAX + 1];
    char cap[EVENTS_MAX][EXP_CAP_ID_MAX + 1];
    int n;
    int logs;
} sink_t;

static void sink_event(void *ctx, const exp_event_t *e)
{
    sink_t *s = (sink_t *)ctx;
    if (s->n >= EVENTS_MAX) return;
    s->ev[s->n] = *e;
    snprintf(s->text[s->n], sizeof(s->text[0]), "%s", e->text ? e->text : "");
    snprintf(s->cap[s->n], sizeof(s->cap[0]), "%s", e->cap ? e->cap : "");
    s->n++;
}

static void sink_log(void *ctx, const char *line)
{
    (void)line;
    ((sink_t *)ctx)->logs++;
}

static int count_events(const sink_t *s, exp_event_type_t type)
{
    int n = 0;
    for (int i = 0; i < s->n; i++) n += s->ev[i].type == type ? 1 : 0;
    return n;
}

static fake_bus_t bus;
static sink_t sink;
static expansion_t exp_;
static exp_model_t models[EXP_ADDR_COUNT];

static void setup(void)
{
    memset(&bus, 0, sizeof(bus));
    memset(&sink, 0, sizeof(sink));
    exp_bus_t b = {&bus, fake_probe, fake_write, fake_write_read};
    exp_ops_t ops = {&sink, sink_event, sink_log};
    expansion_init(&exp_, &b, &ops);
}

static exp_model_t *plug(const char *name, int address)
{
    exp_model_t *m = &models[address - EXP_ADDR_FIRST];
    model_of(m, name, address);
    bus.at[address - EXP_ADDR_FIRST] = m;
    bus.unplugged[address - EXP_ADDR_FIRST] = false;
    return m;
}

static void start(uint32_t t)
{
    bus.now = t;
    expansion_start(&exp_, t);
}

/* Ticks every 10 ms from `from` to `to`, both included. */
static void run(uint32_t from, uint32_t to)
{
    for (uint32_t t = from; t <= to; t += 10) {
        bus.now = t;
        expansion_tick(&exp_, t);
    }
}

static int writes_of(uint8_t addr, uint8_t op, uint32_t from, uint32_t to)
{
    int n = 0;
    for (int i = 0; i < bus.logged; i++) {
        const logged_t *l = &bus.log[i];
        if (l->addr == addr && l->len > 1 && l->bytes[1] == op && l->t >= from && l->t <= to) n++;
    }
    return n;
}

/* ---- The driver replays the lease's timelines --------------------------------------------- */

static const exp_timeline_case_t *timeline(const char *name)
{
    for (size_t i = 0; i < EXP_TIMELINE_CASE_COUNT; i++) {
        if (strcmp(exp_timeline_cases[i].name, name) == 0) return &exp_timeline_cases[i];
    }
    return NULL;
}

typedef struct {
    const char *name;
    uint8_t channel;
    uint32_t until_ms;           /* the desired on, set at 0 */
    uint32_t stop_from, stop_to; /* the box does not tick in between (a crash) */
    uint32_t all_off_at;         /* expansion_all_off then (0: never) */
    uint32_t restart_at;         /* the model restarts then (0: never) */
    uint32_t fail_reads[2];      /* reads at these times fail (0: none) */
    uint32_t drop_at;            /* the write of drop_op then is lost (UINT32_MAX: none) */
    uint8_t drop_op;
} replay_t;

static void replay(const replay_t *r)
{
    const exp_timeline_case_t *tl = timeline(r->name);
    CHECK(tl != NULL);
    if (tl == NULL) return;
    setup();
    const exp_module_case_t *mc = module_case(tl->module);
    exp_model_t *m = plug(tl->module, mc->address);
    for (int i = 0; i < 2; i++) {
        if (r->fail_reads[i] != 0) bus.fail_read_at[bus.fail_read_at_n++] = r->fail_reads[i];
    }
    if (r->drop_at != UINT32_MAX) bus.drop_write_at[bus.drop_write_at_n++] = r->drop_at;
    bus.drop_write_at_op = r->drop_op;
    start(0);
    exp_desired_t want = {EXP_MODE_ON, r->until_ms, 0, 0};
    CHECK(expansion_output(&exp_, (uint8_t)mc->address, r->channel, &want, 0) == EXP_OK);
    uint32_t end = (uint32_t)tl->steps[tl->count - 1].t_ms;
    size_t next = 0;
    for (uint32_t t = 0; t <= end; t++) {
        if (r->restart_at != 0 && t == r->restart_at) exp_model_restart(m, t);
        if (r->all_off_at != 0 && t == r->all_off_at) expansion_all_off(&exp_);
        bool stopped = t > r->stop_from && t < r->stop_to;
        if (t % 10 == 0 && !stopped) {
            bus.now = t;
            expansion_tick(&exp_, t);
        }
        for (; next < tl->count && (uint32_t)tl->steps[next].t_ms == t; next++) {
            const exp_step_case_t *s = &tl->steps[next];
            /* A state between two writes of one moment is the model's to check, not ours. */
            bool later = next + 1 < tl->count && (uint32_t)tl->steps[next + 1].t_ms == t;
            if (!s->expect || later) continue;
            uint8_t outputs, flags;
            exp_model_state(m, t, &outputs, &flags);
            char where[80];
            snprintf(where, sizeof(where), "%s at %u ms", r->name, (unsigned)t);
            named(outputs == s->outputs && (flags & TIMELINE_FLAGS) == s->flags, "replay state",
                  where);
        }
    }
    /* The box's writes are the timeline's, at the same moments, byte for byte. */
    int k = 0;
    bool ok = true;
    for (size_t j = 0; j < tl->count; j++) {
        const exp_step_case_t *s = &tl->steps[j];
        if (!s->write) continue;
        if (k >= bus.logged) {
            ok = false;
            fprintf(stderr, "  replay %s: no write at %ld ms\n", r->name, (long)s->t_ms);
            break;
        }
        const logged_t *l = &bus.log[k++];
        if (l->t != (uint32_t)s->t_ms || l->len != s->len || memcmp(l->bytes, s->bytes, s->len)) {
            ok = false;
            fprintf(stderr, "  replay %s: write %d at %u ms (op %u), timeline %ld ms (op %u)\n",
                    r->name, k, (unsigned)l->t, l->len > 1 ? l->bytes[1] : 0, (long)s->t_ms,
                    s->fields.op);
            break;
        }
    }
    if (ok && k != bus.logged) {
        fprintf(stderr, "  replay %s: %d writes, timeline %d (extra at %u ms, op %u)\n", r->name,
                bus.logged, k, (unsigned)bus.log[k].t, bus.log[k].bytes[1]);
        ok = false;
    }
    named(ok, "replay", r->name);
}

static void test_driver_replays_timelines(void)
{
    const replay_t lease_runs_out = {"lease_runs_out", 0,          0, 1000, 3000, 3100, 0,
                                     {0, 0},           UINT32_MAX, 0};
    const replay_t lost_write = {"lost_write_repaired", 1, 5000, 0, 0, 0, 0, {0, 0}, 0,
                                 EXP_OP_OUTPUT};
    const replay_t restart = {"module_restart", 0, 10000, 0, 0, 0, 800, {0, 0}, UINT32_MAX, 0};
    const replay_t missed = {
        "pulse_spanning_missed_polls", 0, 1000, 0, 0, 0, 0, {250, 750}, 500, EXP_OP_LEASE};
    replay(&lease_runs_out);
    replay(&lost_write);
    replay(&restart);
    replay(&missed);
}

/* ---- The driver against the model -------------------------------------------------------- */

static void test_discovery_at_boot(void)
{
    setup();
    plug("target", 0x58);
    plug("out4", 0x5C);
    start(0);
    CHECK(expansion_module_count(&exp_) == 2);
    CHECK(count_events(&sink, EXP_EVT_ADDED) == 2);
    /* Every address probed, ALL_OFF to both before any read, then the reads. */
    CHECK(strncmp(bus.trace, "PAPPPPAPPP", 10) == 0);
    CHECK(strchr(bus.trace, 'R') > strrchr(bus.trace, 'P'));
    CHECK(writes_of(0x58, EXP_OP_ALL_OFF, 0, 0) == 1 && writes_of(0x5C, EXP_OP_ALL_OFF, 0, 0) == 1);
    CHECK(writes_of(0x58, EXP_OP_CLEAR_FRESH, 0, 0) == 1);
    CHECK(models[0].clear_freshes == 1 && (models[0].flags & EXP_ST_FRESH) == 0);
    const exp_module_t *t = expansion_module(&exp_, 0x58);
    CHECK(t != NULL && t->inputs == 1 && t->outputs == 0 && strcmp(t->cap[0], "hit") == 0);
    const exp_module_t *o = expansion_module(&exp_, 0x5C);
    CHECK(o != NULL && o->outputs == 0x0F && strcmp(o->cap[0], "siren") == 0 &&
          strcmp(o->cap[1], "strobe") == 0 && strcmp(o->cap[2], "smoke") == 0 &&
          strcmp(o->cap[3], "out.4") == 0);
    char text[EXP_MODULES_TEXT_MAX + 1];
    expansion_modules_text(&exp_, text, sizeof(text));
    CHECK(strcmp(text, "58:target/1.0.0:hit;5c:out4/1.0.0:siren,strobe,smoke,out.4") == 0);
    uint8_t addr = 0, ch = 9;
    CHECK(expansion_find(&exp_, "smoke", &addr, &ch) && addr == 0x5C && ch == 2);
    CHECK(!expansion_find(&exp_, "horn", NULL, NULL));
    /* An input module is polled every 20 ms, an output-only one every 250 ms. */
    run(10, 1000);
    CHECK(o->polls >= 3 && o->polls <= 5 && t->polls >= 49 && t->polls <= 51);
}

static void test_hot_plug(void)
{
    setup();
    start(0);
    CHECK(expansion_module_count(&exp_) == 0);
    run(10, 500);
    plug("target", 0x59);
    /* Each empty address every 2 s, one every 250 ms in turn: 0x59 at 500 ms, 2500 ms, ... */
    bus.probes = 0;
    run(510, 2490);
    CHECK(expansion_module_count(&exp_) == 0 && bus.probes == 7);
    run(2500, 2500);
    CHECK(expansion_module_count(&exp_) == 1 && count_events(&sink, EXP_EVT_ADDED) == 1);
    CHECK(writes_of(0x59, EXP_OP_ALL_OFF, 2500, 2500) == 1);
    CHECK(writes_of(0x59, EXP_OP_CLEAR_FRESH, 2500, 2500) == 1);
    CHECK(strcmp(sink.text[0], "59:target/1.0.0:hit") == 0);
    /* An address with a module is not probed; a second target is hit.2. */
    bus.probes = 0;
    run(2510, 4500);
    CHECK(bus.probes == 7);
    plug("target", 0x5A);
    run(4510, 6500);
    const exp_module_t *m2 = expansion_module(&exp_, 0x5A);
    CHECK(m2 != NULL && strcmp(m2->cap[0], "hit.2") == 0);
}

static void test_refused_ident_and_channels(void)
{
    setup();
    exp_model_t *m = plug("target", 0x58);
    m->ident[0] = 0x42; /* bad magic, CRC fixed */
    m->ident[15] = expansion_crc8(m->ident, 15);
    exp_model_t *mixed = plug("m8001", 0x5D);
    mixed->channel[1][4] = 0; /* the light channel without a max on */
    mixed->channel[1][7] = expansion_crc8(mixed->channel[1], 7);
    start(0);
    CHECK(expansion_module(&exp_, 0x58) == NULL);
    const exp_module_t *x = expansion_module(&exp_, 0x5D);
    CHECK(x != NULL && x->usable == 1 && x->inputs == 1 && x->outputs == 0);
    char text[EXP_MODULES_TEXT_MAX + 1];
    expansion_modules_text(&exp_, text, sizeof(text));
    CHECK(strcmp(text, "5d:m8001/0.2.1:hit") == 0);
    /* Retried at the next probe of its address. */
    m->ident[0] = 0x41;
    m->ident[15] = expansion_crc8(m->ident, 15);
    run(10, 2000);
    CHECK(expansion_module(&exp_, 0x58) != NULL);
    /* A module with no usable channel is not added. */
    setup();
    exp_model_t *t = plug("target", 0x58);
    t->channel[0][1] = EXP_KIND_CONTACT;
    t->channel[0][7] = expansion_crc8(t->channel[0], 7);
    start(0);
    CHECK(expansion_module_count(&exp_) == 0 && sink.logs > 0);
}

static void test_discovery_reads_are_retried(void)
{
    setup();
    plug("out4", 0x5C);
    bus.corrupt_reads = 2; /* the IDENT twice */
    start(0);
    CHECK(expansion_module_count(&exp_) == 1);
    setup();
    plug("out4", 0x5C);
    bus.fail_reads = 3; /* every try of the IDENT */
    start(0);
    CHECK(expansion_module_count(&exp_) == 0);
    run(10, 1240);
    CHECK(expansion_module_count(&exp_) == 0);
    run(1250, 1250); /* found at the next probe of its address */
    CHECK(expansion_module_count(&exp_) == 1);
}

static void test_events(void)
{
    setup();
    exp_model_t *m = plug("target", 0x58);
    start(0);
    run(10, 20);
    CHECK(m->armed == 0); /* the box arms nothing by itself */
    CHECK(expansion_arm(&exp_, 0x58, 0xFF) == EXP_OK);
    CHECK(expansion_arm(&exp_, 0x5C, 1) == EXP_NO_SUCH);
    run(30, 40);
    CHECK(m->armed == 1 && m->arms == 1);
    /* A hit 15 ms before the next read: reported once, on the box's clock, and acknowledged. */
    exp_model_hit(m, 45, 0, EXP_EV_HIT, 200);
    run(50, 100);
    CHECK(count_events(&sink, EXP_EVT_INPUT) == 1);
    const exp_event_t *e = &sink.ev[sink.n - 1];
    CHECK(e->type == EXP_EVT_INPUT && e->address == 0x58 && e->channel == 0 &&
          e->kind == EXP_EV_HIT && e->value == 200 && e->t_ms == 45);
    CHECK(strcmp(sink.cap[sink.n - 1], "hit") == 0);
    CHECK(m->count == 0 && m->acks == 1);
    /* Three at once: all within one poll (MORE). */
    exp_model_hit(m, 101, 0, EXP_EV_HIT, 1);
    exp_model_hit(m, 102, 0, EXP_EV_HIT, 2);
    exp_model_hit(m, 103, 0, EXP_EV_HIT, 3);
    run(110, 120);
    CHECK(count_events(&sink, EXP_EVT_INPUT) == 4 && m->count == 0);
    CHECK(sink.ev[sink.n - 3].value == 1 && sink.ev[sink.n - 1].value == 3);
    CHECK(sink.ev[sink.n - 1].t_ms == 103);
    /* Six at once: four reads in a poll, the rest at the next. */
    for (int i = 0; i < 6; i++) exp_model_hit(m, 121, 0, EXP_EV_HIT, (uint8_t)(10 + i));
    run(130, 140);
    CHECK(count_events(&sink, EXP_EVT_INPUT) == 8 && m->count == 2);
    run(150, 160);
    CHECK(count_events(&sink, EXP_EVT_INPUT) == 10 && m->count == 0);
}

static void test_lost_ack_is_not_reported_twice(void)
{
    setup();
    exp_model_t *m = plug("target", 0x58);
    start(0);
    expansion_arm(&exp_, 0x58, 1);
    run(10, 40);
    exp_model_hit(m, 41, 0, EXP_EV_HIT, 77);
    bus.drop_writes = 1;
    bus.drop_op = EXP_OP_ACK;
    run(50, 60);
    CHECK(count_events(&sink, EXP_EVT_INPUT) == 1 && m->count == 1);
    run(70, 80);
    CHECK(count_events(&sink, EXP_EVT_INPUT) == 1);
    CHECK(m->count == 0); /* acknowledged again at the next poll */
    const exp_module_t *x = expansion_module(&exp_, 0x58);
    CHECK(x->repeats == 1 && writes_of(0x58, EXP_OP_ACK, 50, 80) == 2);
    /* After a restart its numbers start again: seq 0 again is a new event. */
    exp_model_restart(m, 100);
    run(90, 140);
    CHECK(m->armed == 1 && (m->flags & EXP_ST_FRESH) == 0);
    exp_model_hit(m, 141, 0, EXP_EV_HIT, 5);
    run(150, 160);
    CHECK(count_events(&sink, EXP_EVT_INPUT) == 2 && sink.ev[sink.n - 1].value == 5);
}

static void test_overflow_and_disarmed(void)
{
    setup();
    exp_model_t *m = plug("target", 0x58);
    start(0);
    expansion_arm(&exp_, 0x58, 1);
    run(10, 40);
    for (int i = 0; i < 20; i++) exp_model_hit(m, 41, 0, EXP_EV_HIT, (uint8_t)i);
    run(50, 200);
    CHECK(count_events(&sink, EXP_EVT_INPUT) == 16);
    CHECK(count_events(&sink, EXP_EVT_OVERFLOW) == 1);
    /* The module still holds an event of a channel the box disarmed: dropped, acknowledged. */
    expansion_arm(&exp_, 0x58, 0);
    exp_model_hit(m, 201, 0, EXP_EV_HIT, 9); /* the model is still armed until the next poll */
    run(210, 260);
    CHECK(count_events(&sink, EXP_EVT_INPUT) == 16 && m->count == 0 && m->armed == 0);
    CHECK(expansion_module(&exp_, 0x58)->dropped == 1);
}

static void test_refused_status_and_loss(void)
{
    setup();
    exp_model_t *m = plug("target", 0x58);
    start(0);
    expansion_arm(&exp_, 0x58, 1);
    run(10, 40);
    /* A bad CRC: read again at the next poll; the event is not lost. */
    exp_model_hit(m, 41, 0, EXP_EV_HIT, 50);
    bus.corrupt_reads = 1;
    run(50, 60);
    CHECK(count_events(&sink, EXP_EVT_INPUT) == 0);
    run(70, 80);
    CHECK(count_events(&sink, EXP_EVT_INPUT) == 1);
    const exp_module_t *x = expansion_module(&exp_, 0x58);
    CHECK(x->refused_status == 1 && x->fails == 0);
    /* 24 failed reads in a row, then a good one: still there. Skipped polls count too. */
    bus.fail_reads = 20;
    bus.suspended_reads = 4;
    run(90, 100 + 23 * 20); /* polls at 100 ... 560 */
    CHECK(expansion_module(&exp_, 0x58) != NULL && expansion_module(&exp_, 0x58)->fails == 24);
    run(570, 580);
    CHECK(expansion_module(&exp_, 0x58)->fails == 0);
    /* Unplugged: gone after 25 failed reads, 0.5 s. */
    bus.unplugged[0] = true;
    uint32_t t0 = 600;
    run(t0, t0 + 23 * 20);
    CHECK(expansion_module_count(&exp_) == 1);
    run(t0 + 24 * 20, t0 + 24 * 20);
    CHECK(expansion_module_count(&exp_) == 0 && count_events(&sink, EXP_EVT_LOST) == 1);
    const exp_event_t *e = &sink.ev[sink.n - 1];
    CHECK(e->type == EXP_EVT_LOST && strcmp(e->reason, "no_answer") == 0 &&
          strcmp(sink.text[sink.n - 1], "58:target/1.0.0:hit") == 0);
    /* Plugged back: found again at the next probe of its address, armed nothing. */
    bus.unplugged[0] = false;
    exp_model_restart(m, t0 + 500);
    run(t0 + 500, t0 + 2500);
    CHECK(expansion_module_count(&exp_) == 1 && count_events(&sink, EXP_EVT_ADDED) == 2);
    CHECK(m->armed == 0);
}

static void test_output_only_module_gone_after_6_s(void)
{
    setup();
    exp_model_t *m = plug("out4", 0x5C);
    start(0);
    exp_desired_t on = {EXP_MODE_ON, 0, 0, 0};
    CHECK(expansion_output(&exp_, 0x5C, 0, &on, 0) == EXP_OK);
    run(0, 1000);
    bus.unplugged[4] = true;
    run(1010, 6990);
    CHECK(expansion_module_count(&exp_) == 1);
    run(7000, 7250);
    CHECK(expansion_module_count(&exp_) == 0);
    /* Back: added off; the old desired state is gone with the module. */
    bus.unplugged[4] = false;
    exp_model_restart(m, 7300);
    run(7300, 9300);
    CHECK(expansion_module_count(&exp_) == 1);
    run(9310, 30000);
    uint8_t outputs;
    exp_model_state(m, 30000, &outputs, NULL);
    CHECK(outputs == 0 && expansion_module(&exp_, 0x5C)->out[0].want.mode == EXP_MODE_OFF);
}

static void test_swapped_module(void)
{
    setup();
    exp_model_t *m = plug("target", 0x5D);
    start(0);
    run(10, 100);
    /* Within the 0.5 s a different module comes up at the same address: FRESH, another IDENT. */
    model_of(m, "m8001", 0x5D);
    exp_model_restart(m, 105);
    run(110, 140);
    CHECK(count_events(&sink, EXP_EVT_LOST) == 1);
    int lost = -1;
    for (int i = 0; i < sink.n; i++) lost = sink.ev[i].type == EXP_EVT_LOST ? i : lost;
    CHECK(lost >= 0 && strcmp(sink.ev[lost].reason, "bad_ident") == 0);
    CHECK(count_events(&sink, EXP_EVT_ADDED) == 2);
    const exp_module_t *x = expansion_module(&exp_, 0x5D);
    CHECK(x != NULL && x->ident.model == 0x8001);
    /* The same module restarting is not lost. */
    exp_model_restart(m, 200);
    run(150, 300);
    CHECK(count_events(&sink, EXP_EVT_LOST) == 1 && expansion_module(&exp_, 0x5D)->restarts == 1);
}

static void test_outputs_and_lease(void)
{
    setup();
    exp_model_t *m = plug("out4", 0x5C);
    start(0);
    uint8_t outputs, flags;
    /* A 10 s siren: OUTPUT with 100 (10 s), refreshed while on, off by the module's timer. */
    exp_desired_t want = {EXP_MODE_ON, 10000 + 1000, 0, 0};
    CHECK(expansion_output(&exp_, 0x5C, 0, &want, 1000) == EXP_OK);
    run(1000, 1000);
    CHECK(writes_of(0x5C, EXP_OP_OUTPUT, 1000, 1000) == 1);
    CHECK(bus.log[bus.logged - 1].bytes[4] == 100);
    run(1010, 10990);
    exp_model_state(m, 10990, &outputs, &flags);
    CHECK(outputs == 1 && flags == 0);
    CHECK(writes_of(0x5C, EXP_OP_LEASE, 1000, 10990) == 19);
    run(11000, 12000);
    exp_model_state(m, 12000, &outputs, &flags);
    CHECK(outputs == 0 && flags == 0);
    CHECK(writes_of(0x5C, EXP_OP_LEASE, 11000, 12000) == 0);
    CHECK(writes_of(0x5C, EXP_OP_OUTPUT, 1010, 12000) == 0); /* nothing to repair */
    /* Off before its time: OUTPUT off at once. */
    want.until_ms = 20000;
    expansion_output(&exp_, 0x5C, 1, &want, 12000);
    run(12010, 13000);
    exp_desired_t off = {EXP_MODE_OFF, 0, 0, 0};
    CHECK(expansion_output(&exp_, 0x5C, 1, &off, 13000) == EXP_OK);
    run(13010, 13010);
    exp_model_state(m, 13010, &outputs, NULL);
    CHECK(outputs == 0 && writes_of(0x5C, EXP_OP_OUTPUT, 13010, 13010) == 1);
    /* An output the box wants off but the module shows on is turned off at the next poll. */
    const uint8_t on_ch3[] = {0x10, 0x03, 0x03, 0x01, 0, 0, 0, 0, 0, 0, 0};
    uint8_t frame[EXP_COMMAND_MAX];
    memcpy(frame, on_ch3, sizeof(on_ch3));
    uint8_t covered[EXP_COMMAND_MAX + 1] = {0x5C << 1};
    memcpy(covered + 1, frame, 10);
    frame[10] = expansion_crc8(covered, 11);
    CHECK(exp_model_write(m, 13015, frame, 11));
    run(13020, 13300);
    exp_model_state(m, 13300, &outputs, NULL);
    CHECK(outputs == 0);
    /* The box stops: the module turns everything off within 1.5 s of the last refresh. */
    want.until_ms = 0;
    expansion_output(&exp_, 0x5C, 0, &want, 14000);
    run(14000, 15000);
    int last = bus.logged - 1;
    uint32_t last_write = bus.log[last].t;
    exp_model_state(m, last_write + 1499, &outputs, NULL);
    CHECK(outputs == 1);
    exp_model_state(m, last_write + 1500, &outputs, &flags);
    CHECK(outputs == 0 && (flags & EXP_ST_LEASE_EXPIRED));
    /* All off: ALL_OFF, and nothing comes back on. */
    setup();
    m = plug("out4", 0x5C);
    start(0);
    want.until_ms = 0;
    expansion_output(&exp_, 0x5C, 0, &want, 0);
    expansion_output(&exp_, 0x5C, 1, &want, 0);
    run(0, 600);
    expansion_all_off(&exp_);
    run(610, 2000);
    exp_model_state(m, 2000, &outputs, NULL);
    CHECK(outputs == 0 && writes_of(0x5C, EXP_OP_ALL_OFF, 610, 610) == 1);
    CHECK(writes_of(0x5C, EXP_OP_LEASE, 620, 2000) == 0 &&
          writes_of(0x5C, EXP_OP_OUTPUT, 620, 2000) == 0);
}

static void test_output_arguments(void)
{
    setup();
    plug("out4", 0x5C);
    plug("target", 0x58);
    start(0);
    exp_desired_t p = {EXP_MODE_PATTERN, 1000, 50, 50};
    CHECK(expansion_output(&exp_, 0x5C, 1, &p, 0) == EXP_BAD_ARGS); /* a relay: 100 ms */
    CHECK(expansion_output(&exp_, 0x5C, 3, &p, 0) == EXP_OK);       /* solid-state */
    p.on_ms = 100;
    p.off_ms = 100;
    CHECK(expansion_output(&exp_, 0x5C, 1, &p, 0) == EXP_OK);
    p.on_ms = 10001;
    CHECK(expansion_output(&exp_, 0x5C, 1, &p, 0) == EXP_BAD_ARGS);
    exp_desired_t bad = {3, 0, 0, 0};
    CHECK(expansion_output(&exp_, 0x5C, 0, &bad, 0) == EXP_BAD_ARGS);
    exp_desired_t on = {EXP_MODE_ON, 0, 0, 0};
    CHECK(expansion_output(&exp_, 0x5C, 4, &on, 0) == EXP_NO_SUCH);
    CHECK(expansion_output(&exp_, 0x58, 0, &on, 0) == EXP_NO_SUCH); /* an input */
    CHECK(expansion_output(&exp_, 0x5D, 0, &on, 0) == EXP_NO_SUCH);
    exp_desired_t past = {EXP_MODE_ON, 5, 0, 0};
    CHECK(expansion_output(&exp_, 0x5C, 0, &past, 10) == EXP_BAD_ARGS);
}

/* A running pattern is not "repaired" by the reconciliation; one the module lost is. */
static void test_pattern_reconciled(void)
{
    setup();
    exp_model_t *m = plug("out4", 0x5C);
    start(0);
    exp_desired_t p = {EXP_MODE_PATTERN, 5000, 500, 500};
    CHECK(expansion_output(&exp_, 0x5C, 1, &p, 0) == EXP_OK);
    run(0, 4000);
    CHECK(writes_of(0x5C, EXP_OP_OUTPUT, 0, 4000) == 1);
    uint8_t outputs;
    exp_model_state(m, 4100, &outputs, NULL);
    CHECK(outputs == 2);
    run(4010, 6000);
    exp_model_state(m, 6000, &outputs, NULL);
    CHECK(outputs == 0 && writes_of(0x5C, EXP_OP_OUTPUT, 0, 6000) == 1);
    /* The module restarts in the middle of a pattern: sent again with what is left. */
    p.until_ms = 20000;
    expansion_output(&exp_, 0x5C, 1, &p, 6000);
    run(6010, 8000);
    exp_model_restart(m, 8005);
    run(8010, 8500);
    CHECK(writes_of(0x5C, EXP_OP_OUTPUT, 8010, 8500) == 1 && m->outputs_taken >= 1);
    exp_model_state(m, 8600, &outputs, NULL);
    CHECK((m->out[1].mode == EXP_MODE_PATTERN));
}

/* The module's max on is the box's too: the box stops refreshing and does not fight the module;
 * a start during its min off is refused at the box. */
static void test_max_on_and_min_off(void)
{
    setup();
    exp_model_t *m = plug("out4", 0x5C);
    start(0);
    exp_desired_t on = {EXP_MODE_ON, 0, 0, 0};
    CHECK(expansion_output(&exp_, 0x5C, 2, &on, 0) == EXP_OK); /* smoke: 30 s, then 30 s off */
    run(0, 29990);
    uint8_t outputs, flags;
    exp_model_state(m, 29990, &outputs, NULL);
    CHECK(outputs == 4);
    run(30000, 40000);
    exp_model_state(m, 40000, &outputs, &flags);
    CHECK(outputs == 0 && (flags & EXP_ST_CMD_ERROR) == 0);
    CHECK(writes_of(0x5C, EXP_OP_OUTPUT, 30000, 40000) == 0 &&
          writes_of(0x5C, EXP_OP_LEASE, 30000, 40000) == 0);
    CHECK(expansion_output(&exp_, 0x5C, 2, &on, 40000) == EXP_TOO_SOON);
    CHECK(expansion_output(&exp_, 0x5C, 2, &on, 59990) == EXP_TOO_SOON);
    exp_desired_t pulse = {EXP_MODE_ON, 61000, 0, 0};
    CHECK(expansion_output(&exp_, 0x5C, 2, &pulse, 60000) == EXP_OK);
    run(60000, 60000);
    exp_model_state(m, 60000, &outputs, &flags);
    CHECK(outputs == 4 && (flags & EXP_ST_CMD_ERROR) == 0);
    run(60010, 61500);
    exp_model_state(m, 61500, &outputs, NULL);
    CHECK(outputs == 0);
}

/* A relay channel turned off turns on again no sooner than 100 ms later: the box waits. */
static void test_relay_100_ms(void)
{
    setup();
    exp_model_t *m = plug("out4", 0x5C);
    start(0);
    exp_desired_t on = {EXP_MODE_ON, 0, 0, 0}, off = {EXP_MODE_OFF, 0, 0, 0};
    expansion_output(&exp_, 0x5C, 0, &on, 0);
    run(0, 50);
    expansion_output(&exp_, 0x5C, 0, &off, 50);
    run(50, 50);
    expansion_output(&exp_, 0x5C, 0, &on, 60);
    run(60, 140);
    CHECK(writes_of(0x5C, EXP_OP_OUTPUT, 60, 140) == 0);
    run(150, 150);
    uint8_t outputs, flags;
    exp_model_state(m, 150, &outputs, &flags);
    CHECK(writes_of(0x5C, EXP_OP_OUTPUT, 150, 150) == 1 && outputs == 1 &&
          (flags & EXP_ST_CMD_ERROR) == 0);
}

static void test_backend_drive(void)
{
    setup();
    exp_model_t *m = plug("out4", 0x5C);
    start(0);
    exp_out_ref_t ref = {&exp_, 0x5C, 1};
    expansion_backend_drive(&ref, true, true, 0);
    run(0, 0);
    expansion_backend_drive(&ref, true, true, 10); /* the same level: nothing new */
    run(10, 1000);
    uint8_t outputs;
    exp_model_state(m, 1000, &outputs, NULL);
    CHECK(outputs == 2 && writes_of(0x5C, EXP_OP_OUTPUT, 0, 1000) == 1);
    expansion_backend_drive(&ref, false, false, 1000);
    run(1010, 1010);
    exp_model_state(m, 1010, &outputs, NULL);
    CHECK(outputs == 0 && writes_of(0x5C, EXP_OP_OUTPUT, 1010, 1010) == 1);
    exp_out_ref_t nobody = {&exp_, 0x5F, 0};
    expansion_backend_drive(&nobody, true, true, 1020); /* no module: nothing */
    CHECK(writes_of(0x5F, EXP_OP_OUTPUT, 0, 2000) == 0);
}

/* node.modules' entries, as the shared texts have them. */
static void test_modules_text(void)
{
    const char *two_targets = NULL, *community = NULL, *none = NULL;
    for (size_t i = 0; i < EXP_MODULES_TEXT_COUNT; i++) {
        if (strcmp(exp_modules_texts[i][0], "two_targets") == 0)
            two_targets = exp_modules_texts[i][1];
        if (strcmp(exp_modules_texts[i][0], "community_model") == 0)
            community = exp_modules_texts[i][1];
        if (strcmp(exp_modules_texts[i][0], "none") == 0) none = exp_modules_texts[i][1];
    }
    CHECK(two_targets != NULL && community != NULL && none != NULL);
    char text[EXP_MODULES_TEXT_MAX + 1];
    setup();
    start(0);
    CHECK(expansion_modules_text(&exp_, text, sizeof(text)) == 0 && strcmp(text, none) == 0);
    setup();
    plug("target", 0x58);
    exp_model_t *b = plug("target", 0x59);
    b->ident[10] = 1; /* firmware 1.0.1 */
    b->ident[15] = expansion_crc8(b->ident, 15);
    start(0);
    expansion_modules_text(&exp_, text, sizeof(text));
    CHECK(two_targets != NULL && strcmp(text, two_targets) == 0);
    setup();
    plug("m8001", 0x5D);
    start(0);
    expansion_modules_text(&exp_, text, sizeof(text));
    CHECK(community != NULL && strcmp(text, community) == 0);
    /* At most 100 bytes, whole entries only; at most four modules. */
    setup();
    for (int a = EXP_ADDR_FIRST; a <= EXP_ADDR_LAST; a++) plug("out4", a);
    start(0);
    CHECK(expansion_module_count(&exp_) == EXP_MODULES_MAX);
    size_t n = expansion_modules_text(&exp_, text, sizeof(text));
    CHECK(n <= EXP_MODULES_TEXT_MAX && n == strlen(text) && text[n - 1] != ';');
    CHECK(strstr(text, "5b:out4") == NULL); /* the fifth is not added */
    char model[8];
    expansion_model_name(0x8001, model, sizeof(model));
    CHECK(strcmp(model, "m8001") == 0);
}

void run_expansion_tests(void)
{
    test_crc8();
    test_ident_cases();
    test_channel_cases();
    test_status_cases();
    test_command_cases();
    test_model_cmd_error();
    test_model_timelines();
    test_driver_replays_timelines();
    test_discovery_at_boot();
    test_hot_plug();
    test_refused_ident_and_channels();
    test_discovery_reads_are_retried();
    test_events();
    test_lost_ack_is_not_reported_twice();
    test_overflow_and_disarmed();
    test_refused_status_and_loss();
    test_output_only_module_gone_after_6_s();
    test_swapped_module();
    test_outputs_and_lease();
    test_output_arguments();
    test_pattern_reconciled();
    test_max_on_and_min_off();
    test_relay_100_ms();
    test_backend_drive();
    test_modules_text();
}
