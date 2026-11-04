/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The expansion port's driver, the box's side (draft RFC "The expansion port", increment 6;
 * decisions EXP-7 to EXP-14; protocol/expansion-port.md, "expansion protocol v1"). It replaces
 * the target addon's stub (target_addon.c) and its draft report of P5J-19.
 *
 * Modules sit at 0x58-0x5F on the box's I2C bus, behind the M12 socket, at most
 * EXP_MODULES_MAX of them. The driver:
 *   - finds them: at boot every address is probed and each module that answers is sent ALL_OFF
 *     before anything else, then read (IDENT, every CHANNEL) and sent CLEAR_FRESH; after that each
 *     empty address is probed every EXP_PROBE_MS, one address every EXP_PROBE_STEP_MS in turn
 *     (hot-plug: a module plugged in is found within 2 s), and a module found then is read,
 *     sent ALL_OFF and CLEAR_FRESH and added. An IDENT the box refuses (protocol section 2) keeps
 *     the module out until the next probe of its address; a refused CHANNEL leaves that channel
 *     unused and the others in use; a module with no usable channel is not added;
 *   - polls each module's STATUS (every EXP_POLL_INPUT_MS for a module with inputs, every
 *     EXP_POLL_OUTPUT_MS for an output-only one), up to EXP_READS_PER_POLL reads while MORE is
 *     set: an event is reported once with its time on the box's clock (t_read - age, EXP-10) and
 *     acknowledged; a sequence number seen again (a lost ACK) is acknowledged again and not
 *     reported; an event of a channel the box has not armed is acknowledged and dropped;
 *     OVERFLOW, CMD_ERROR and LEASE_EXPIRED are counted and logged; FRESH (the module restarted)
 *     makes the box read its IDENT again (a different module there is the old one lost,
 *     `bad_ident`, and the new one added), clear the flag and send its state again;
 *   - counts a STATUS it refuses (CRC, length, channel, event kind), a read the bus fails and a
 *     poll the bus skips (a suspended device: i2c_health.h) as a failed read; EXP_LOST_AFTER in
 *     a row and the module is gone (`no_answer`): its outputs count as off and its desired state
 *     is dropped;
 *   - reconciles each output channel's desired state with the outputs bitmap of every STATUS
 *     (EXP-12): a channel that should be on and is not gets its command again with what is left
 *     of its duration, rounded up to 100 ms; one that should be off and is on gets `off`. While
 *     any output of a module should be on, the box writes OUTPUT or LEASE to it at least every
 *     EXP_LEASE_REFRESH_MS with a lease of EXP_LEASE_100MS (1.5 s), so whatever stops the box,
 *     the module turns its outputs off within 1.5 s (EXP-11). expansion_all_off turns every
 *     output off with ALL_OFF.
 *
 * Every write is tried once: a write the bus or the module loses is repaired by the next poll's
 * reconciliation (and a lost LEASE leaves two more before the lease runs out), as the protocol's
 * timelines show. Reads at discovery (IDENT, CHANNEL) are tried EXP_DISCOVERY_TRIES times.
 *
 * Platform-free: the bus is a small interface (exp_bus_t; expansion_esp.c on the ESP32, the
 * host tests' simulated modules on the module core in test/module_sim.c), the clock is the
 * caller's, and what the driver learns goes to callbacks. Nothing calls it yet: the game task,
 * hits to the script, node.modules and node.module_lost come with increment 8.
 */
#ifndef ATALAIA_EXPANSION_H
#define ATALAIA_EXPANSION_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* ---- The protocol (protocol/expansion-port.md) ---------------------------------------- */

#define EXP_ADDR_FIRST   0x58
#define EXP_ADDR_LAST    0x5F
#define EXP_ADDR_COUNT   (EXP_ADDR_LAST - EXP_ADDR_FIRST + 1)
#define EXP_MODULES_MAX  4
#define EXP_CHANNELS_MAX 8
#define EXP_PROTOCOL     1
#define EXP_MAGIC0       0x41 /* "AX" */
#define EXP_MAGIC1       0x58

#define EXP_REG_IDENT   0x00
#define EXP_REG_CHANNEL 0x01
#define EXP_REG_STATUS  0x02
#define EXP_REG_COMMAND 0x10
#define EXP_IDENT_LEN   16
#define EXP_CHANNEL_LEN 8
#define EXP_STATUS_LEN  9
#define EXP_COMMAND_MAX 11 /* after the address byte: register, op, 8 argument bytes, CRC */

/* IDENT byte 3 */
#define EXP_CLASS_INPUTS  0x01
#define EXP_CLASS_OUTPUTS 0x02

/* CHANNEL byte 1 and 2 */
#define EXP_KIND_HIT       0x01
#define EXP_KIND_CONTACT   0x02 /* reserved: a v1 box does not use it */
#define EXP_KIND_OUTPUT    0x10
#define EXP_CH_RELAY       0x01
#define EXP_CH_SOLID_STATE 0x02
#define EXP_CH_SENSES      0x04
#define EXP_HINT_COUNT     6 /* generic, siren, strobe, smoke, light, horn */

/* STATUS byte 0 */
#define EXP_ST_EVENT         0x01
#define EXP_ST_MORE          0x02
#define EXP_ST_OVERFLOW      0x04
#define EXP_ST_SUPPLY_OK     0x08
#define EXP_ST_LEASE_EXPIRED 0x10
#define EXP_ST_FRESH         0x20
#define EXP_ST_CMD_ERROR     0x40

/* STATUS byte 2's kind */
#define EXP_EV_HIT    1
#define EXP_EV_CLOSED 2
#define EXP_EV_OPENED 3

/* COMMAND ops */
#define EXP_OP_ACK         0x01
#define EXP_OP_ARM         0x02
#define EXP_OP_OUTPUT      0x03
#define EXP_OP_LEASE       0x04
#define EXP_OP_ALL_OFF     0x05
#define EXP_OP_CLEAR_FRESH 0x06
#define EXP_OP_LOCATE      0x07
#define EXP_OP_CONFIG      0x08

#define EXP_MODE_OFF     0
#define EXP_MODE_ON      1
#define EXP_MODE_PATTERN 2

/* ---- The driver's timing (EXP-8, EXP-11, EXP-14) ---------------------------------------- */

#define EXP_POLL_INPUT_MS    20
#define EXP_POLL_OUTPUT_MS   250
#define EXP_READS_PER_POLL   4
#define EXP_LOST_AFTER       25
#define EXP_PROBE_MS         2000 /* each empty address is probed this often ... */
#define EXP_PROBE_STEP_MS    (EXP_PROBE_MS / EXP_ADDR_COUNT) /* ... one at a time */
#define EXP_DISCOVERY_TRIES  3
#define EXP_LEASE_100MS      15
#define EXP_LEASE_REFRESH_MS 500
#define EXP_RELAY_CHANGE_MS  100 /* a relay channel turns on again no sooner after an off */
#define EXP_RELAY_PATTERN_MS 100 /* a pattern's least on and off time on a relay channel */
#define EXP_SOLID_PATTERN_MS 10  /* ... and on any other */
#define EXP_PATTERN_MAX_MS   10000
#define EXP_PATTERN_EDGE_MS  30 /* a pattern's level is not compared this close to an edge */
#define EXP_MODULES_TEXT_MAX 100
#define EXP_CAP_ID_MAX       23

/* ---- Frames ------------------------------------------------------------------------------ */

/* CRC-8/SMBUS: polynomial 0x07, initial 0, no reflection, no final XOR. */
uint8_t expansion_crc8(const uint8_t *data, size_t len);

typedef struct {
    bool inputs, outputs;
    uint8_t channels; /* 1-8 */
    uint16_t model;
    uint8_t hw;
    uint8_t fw[3];
    uint8_t uid[4];
} exp_ident_t;

typedef struct {
    uint8_t index;
    uint8_t kind;  /* EXP_KIND_HIT or EXP_KIND_OUTPUT */
    uint8_t flags; /* EXP_CH_* */
    uint8_t hint;  /* 0-5; above 5 read as 0, generic */
    uint8_t max_on_s, min_off_s;
} exp_channel_t;

typedef struct {
    uint8_t flags; /* EXP_ST_* */
    bool event;
    uint8_t seq, channel, kind, value;
    uint16_t age_ms;
    uint8_t outputs, armed;
} exp_status_t;

typedef struct {
    uint8_t op; /* EXP_OP_* */
    uint8_t seq, armed, channel, mode, lease_100ms, seconds, parameter;
    uint16_t duration_100ms, on_10ms, off_10ms, value;
} exp_command_t;

/* Each returns NULL when the box takes the frame (and fills *out), else the reason in the shared
 * vectors' words: length, crc, magic, version, classes, channels; index, kind, max_on; channel,
 * event_kind. */
const char *expansion_parse_ident(const uint8_t *frame, size_t len, exp_ident_t *out);
const char *expansion_parse_channel(const uint8_t *frame, size_t len, int index,
                                    exp_channel_t *out);
const char *expansion_parse_status(const uint8_t *frame, size_t len, int channels,
                                   exp_status_t *out);

/* A COMMAND write after the address byte (register, op, arguments, CRC over the address byte
 * as sent and the rest) for the module at 7-bit address addr: its length, 0 for an unknown op
 * or too small a buffer. */
size_t expansion_encode_command(const exp_command_t *c, uint8_t addr, uint8_t *out, size_t cap);

/* target, out4, or m and four lower-case hex digits (out: at least 6 bytes). */
void expansion_model_name(uint16_t model, char *out, size_t cap);

/* ---- The bus ------------------------------------------------------------------------------ */

#define EXP_BUS_OK        0
#define EXP_BUS_FAIL      (-1) /* NACK, timeout, bus error */
#define EXP_BUS_SUSPENDED (-2) /* not tried: the device is in back-off (a failed read) */

typedef struct {
    void *ctx;
    /* True when a device answers a one-byte address write at addr. */
    bool (*probe)(void *ctx, uint8_t addr);
    /* One write transaction: data after the address byte. */
    int (*write)(void *ctx, uint8_t addr, const uint8_t *data, size_t len);
    /* A pointer write, a repeated start and a read of in_len bytes. */
    int (*write_read)(void *ctx, uint8_t addr, const uint8_t *out, size_t out_len, uint8_t *in,
                      size_t in_len);
} exp_bus_t;

/* ---- What the driver tells ------------------------------------------------------------- */

typedef enum {
    EXP_EVT_ADDED = 0, /* a module was found and added */
    EXP_EVT_LOST,      /* a module is gone: reason no_answer or bad_ident; text its entry */
    EXP_EVT_INPUT,     /* an input event: channel, kind (EXP_EV_*), value, t_ms, cap */
    EXP_EVT_OVERFLOW,  /* the module dropped events since its last report */
} exp_event_type_t;

typedef struct {
    exp_event_type_t type;
    uint8_t address;
    uint8_t channel;
    uint8_t kind;
    uint8_t value;
    uint32_t t_ms;      /* the input event's time on the box's clock */
    const char *cap;    /* the channel's capability id (input events) */
    const char *reason; /* lost: no_answer, bad_ident */
    const char *text;   /* added, lost: the module's node.modules entry */
} exp_event_t;

typedef struct {
    void *ctx;
    void (*event)(void *ctx, const exp_event_t *e); /* may be NULL */
    void (*log)(void *ctx, const char *line);       /* may be NULL */
} exp_ops_t;

/* ---- State ------------------------------------------------------------------------------ */

/* An output channel's desired state (EXP-12). until_ms 0: no end of its own (until off, the
 * channel's max on or the lease). */
typedef struct {
    uint8_t mode; /* EXP_MODE_* */
    uint32_t until_ms;
    uint32_t on_ms, off_ms; /* a pattern's */
} exp_desired_t;

typedef struct {
    exp_desired_t want;
    bool dirty;        /* to be sent at the next tick */
    bool on_known;     /* on_since is set: the box's own copy of the module's max on */
    uint32_t on_since; /* when the box first sent this on */
    uint32_t sent_ms;  /* when it last sent it (a pattern's phase) */
    bool off_known;
    uint32_t off_ms_at;     /* when it last sent off (a relay's 100 ms) */
    bool min_off;           /* the module's min off after its max on: */
    uint32_t min_off_until; /* the box holds new starts until then */
    bool ends_known;        /* what the box last sent ends on the module's timer ... */
    uint32_t ends_at;       /* ... then (its duration rounded up, or its max on) */
} exp_output_t;

typedef struct {
    bool used;
    uint8_t addr;
    uint8_t ident_raw[EXP_IDENT_LEN];
    exp_ident_t ident;
    exp_channel_t ch[EXP_CHANNELS_MAX];
    uint8_t usable;  /* bit n: channel n's descriptor was taken */
    uint8_t inputs;  /* usable hit channels */
    uint8_t outputs; /* usable output channels */
    char cap[EXP_CHANNELS_MAX][EXP_CAP_ID_MAX + 1];
    uint32_t next_poll;
    uint16_t fails; /* failed reads in a row */
    bool have_seq;
    uint8_t last_seq;
    uint8_t armed_want;
    exp_output_t out[EXP_CHANNELS_MAX];
    bool all_off_pending;
    bool lease_known;
    uint32_t lease_ms; /* the last OUTPUT or LEASE written */
    uint8_t last_flags;
    /* counters since the module was added */
    uint32_t polls, read_errors, refused_status, events, repeats, dropped, overflows, cmd_errors,
        lease_expiries, restarts, writes, write_errors, resends;
} exp_module_t;

typedef struct {
    exp_bus_t bus;
    exp_ops_t ops;
    exp_module_t mod[EXP_MODULES_MAX];
    bool started;
    uint32_t next_probe;
    uint8_t probe_next; /* the next address to probe, from EXP_ADDR_FIRST */
    int reprobe;        /* an address to probe at the next tick (a swapped module), or -1 */
    uint32_t now;
    char text[EXP_MODULES_TEXT_MAX + 1]; /* the last event's entry */
} expansion_t;

typedef enum {
    EXP_OK = 0,
    EXP_NO_SUCH,  /* no module at that address, or no such output channel */
    EXP_BAD_ARGS, /* a mode out of range, a pattern under the channel's floor or over 10 s */
    EXP_TOO_SOON, /* the module's min off after its max on has not passed */
} exp_result_t;

void expansion_init(expansion_t *e, const exp_bus_t *bus, const exp_ops_t *ops);

/* At boot, before anything else on the port: probes every address, sends ALL_OFF to each that
 * answers, then reads and adds the modules. */
void expansion_start(expansion_t *e, uint32_t now_ms);

/* Every turn of the game task: hot-plug probing, pending writes, polls and lease refreshes. */
void expansion_tick(expansion_t *e, uint32_t now_ms);

/* The module at addr, or NULL. */
const exp_module_t *expansion_module(const expansion_t *e, uint8_t addr);
int expansion_module_count(const expansion_t *e);

/* Which input channels of the module at addr report events (a set, not a toggle; channels that
 * are not usable hit channels are left out). Sent with ARM at the next poll and kept so. */
exp_result_t expansion_arm(expansion_t *e, uint8_t addr, uint8_t bitmap);

/* An output channel's desired state, sent at the next tick and reconciled after. The module's
 * max on and min off are the box's too (EXP-13): an on outlives neither, and a start during the
 * min off that followed a max on is EXP_TOO_SOON. */
exp_result_t expansion_output(expansion_t *e, uint8_t addr, uint8_t channel,
                              const exp_desired_t *want, uint32_t now_ms);

/* Every output of every module off now (ALL_OFF at the next tick): boot, pause, end, halt. */
void expansion_all_off(expansion_t *e);

/* The module and channel whose capability id is cap: true when found. */
bool expansion_find(const expansion_t *e, const char *cap, uint8_t *addr, uint8_t *channel);

/* node.modules' entries for the modules ("58:target/1.0.0:hit;5c:out4/1.0.0:siren,strobe"), in
 * address order, whole entries only, at most EXP_MODULES_TEXT_MAX bytes; its length. */
size_t expansion_modules_text(const expansion_t *e, char *out, size_t cap);

/* One module's entry; its length (0 when it has no capability). */
size_t expansion_module_text(const exp_module_t *m, char *out, size_t cap);

/* ---- Behind the output layer (outputs.h) -------------------------------------------------- */

/* An out_backend_t's ctx for a module's output channel: outputs.c's drive(on, live) becomes the
 * channel's desired state (on until off, bounded by the module's max on and the lease; off).
 * Increment 8 adds such channels to the output layer. */
typedef struct {
    expansion_t *exp;
    uint8_t addr;
    uint8_t channel;
} exp_out_ref_t;

void expansion_backend_drive(void *ctx, bool on, bool live, uint32_t now_ms);

#endif /* ATALAIA_EXPANSION_H */
