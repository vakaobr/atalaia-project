/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The module core: the module's side of the expansion port's protocol v1
 * (protocol/expansion-port.md; draft RFC "The expansion port", increment 7). Portable C with no
 * platform calls: the module's firmware (the target module on pico-sdk, the I2C output module, a
 * community module) owns the I2C target peripheral, the clock, its pins and its sensors, and hands
 * the core
 *
 *   - the I2C target's four moments: an address match (start or repeated start, read or write), a
 *     byte received, a byte requested, a stop (mc_i2c_start, mc_i2c_receive, mc_i2c_request,
 *     mc_i2c_stop);
 *   - its clock, a free-running millisecond counter that may wrap (now_ms everywhere);
 *   - its input events (mc_event) and a regular mc_tick, at least every 10 ms, better every 1 ms,
 *     which runs the outputs' timers (durations, patterns, max on, the lease).
 *
 * The core answers IDENT, CHANNEL and STATUS, takes or refuses COMMAND writes (setting CMD_ERROR),
 * queues events (MORE, OVERFLOW, a sequence counter), and switches the outputs through
 * mc_ops_t.set_output under the module's hard limits: the lease (every output off when it runs out,
 * LEASE_EXPIRED), each channel's max on and min off, a relay's 100 ms, the pattern floors, and
 * every output off at power-up (mc_init).
 *
 * Not reentrant: every call for one module must come from one context. A port whose I2C callbacks
 * run in an interrupt calls mc_tick and mc_event with that interrupt masked (on the RP2040, a
 * critical section or the I2C IRQ disabled around them). Nothing is allocated; mc_module_t is the
 * whole state (under 700 bytes).
 */
#ifndef ATALAIA_MODULE_CORE_H
#define ATALAIA_MODULE_CORE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define MC_PROTOCOL_VERSION 1u
#define MC_FIRST_ADDRESS    0x58u
#define MC_LAST_ADDRESS     0x5Fu
#define MC_MAX_CHANNELS     8u

/* Events a module holds until the box acknowledges them (the protocol asks for at least 16). */
#ifndef MC_EVENT_QUEUE_LEN
#define MC_EVENT_QUEUE_LEN 16u
#endif

/* Registers and their lengths (section 2). */
#define MC_REG_IDENT    0x00u
#define MC_REG_CHANNEL  0x01u
#define MC_REG_STATUS   0x02u
#define MC_REG_COMMAND  0x10u
#define MC_IDENT_LEN    16u
#define MC_CHANNEL_LEN  8u
#define MC_STATUS_LEN   9u
#define MC_MAX_READ_LEN 16u

/* COMMAND ops. */
#define MC_OP_ACK         0x01u
#define MC_OP_ARM         0x02u
#define MC_OP_OUTPUT      0x03u
#define MC_OP_LEASE       0x04u
#define MC_OP_ALL_OFF     0x05u
#define MC_OP_CLEAR_FRESH 0x06u
#define MC_OP_LOCATE      0x07u
#define MC_OP_CONFIG      0x08u

/* OUTPUT modes. */
#define MC_MODE_OFF     0u
#define MC_MODE_ON      1u
#define MC_MODE_PATTERN 2u

/* CONFIG parameters (an input's tuning). */
#define MC_PARAM_THRESHOLD   1u
#define MC_PARAM_HOLDOFF_MS  2u
#define MC_PARAM_DEBOUNCE_MS 3u

/* A channel's kind (CHANNEL byte 1). */
#define MC_KIND_HIT     0x01u
#define MC_KIND_CONTACT 0x02u
#define MC_KIND_OUTPUT  0x10u

/* A channel's flags (CHANNEL byte 2). An output channel is exactly one of relay and solid-state. */
#define MC_CH_RELAY         0x01u
#define MC_CH_SOLID_STATE   0x02u
#define MC_CH_SENSES_SUPPLY 0x04u

/* An event's kind (STATUS byte 2, bits 4-7). */
#define MC_EVENT_HIT    1u
#define MC_EVENT_CLOSED 2u
#define MC_EVENT_OPENED 3u

/* STATUS flags (byte 0). */
#define MC_ST_EVENT         0x01u
#define MC_ST_MORE          0x02u
#define MC_ST_OVERFLOW      0x04u
#define MC_ST_SUPPLY_OK     0x08u
#define MC_ST_LEASE_EXPIRED 0x10u
#define MC_ST_FRESH         0x20u
#define MC_ST_CMD_ERROR     0x40u

/* The lease and the limits (sections 2 and 4). */
#define MC_LEASE_DEFAULT_100MS            15u
#define MC_LEASE_LEAST_100MS              5u
#define MC_LEASE_MOST_100MS               50u
#define MC_RELAY_LEAST_CHANGE_MS          100u
#define MC_RELAY_LEAST_PATTERN_10MS       10u
#define MC_SOLID_STATE_LEAST_PATTERN_10MS 1u

/* What the module has on one channel; the core writes its CHANNEL descriptor from it. */
typedef struct {
    uint8_t kind;      /* MC_KIND_HIT, MC_KIND_CONTACT or MC_KIND_OUTPUT */
    uint8_t flags;     /* MC_CH_*; an output is relay or solid-state */
    uint8_t hint;      /* 0 generic, 1 siren, 2 strobe, 3 smoke, 4 light, 5 horn */
    uint8_t max_on_s;  /* outputs: the module's own hard limit, 1-255; inputs: 0 */
    uint8_t min_off_s; /* outputs: the least seconds off after the max on was reached */
    /* Inputs: the tuning CONFIG starts from (the firmware reads it back with mc_config_value). */
    uint16_t threshold;
    uint16_t holdoff_ms;
    uint16_t debounce_ms;
} mc_channel_t;

/* Who the module is; the core writes its IDENT from it (classes and channel count from channels).
 */
typedef struct {
    uint8_t address; /* 7-bit, 0x58-0x5F, the jumpers' choice: a write's CRC covers it */
    uint16_t model;  /* 0x0001 target, 0x0002 out4, 0x8000-0xFFFF community models */
    uint8_t hw_rev;
    uint8_t fw[3];  /* major, minor, patch */
    uint8_t uid[4]; /* from the processor's own unique id */
    uint8_t channel_count;
    mc_channel_t channels[MC_MAX_CHANNELS];
} mc_config_t;

/* What the core asks of the module's firmware. */
typedef struct {
    void *ctx;
    /* Switch an output channel's load (required when the module has an output). Called only when
     * the level changes, and once for every output with on = false in mc_init. */
    void (*set_output)(void *ctx, uint8_t channel, bool on);
    /* Optional: the load supply is present (SUPPLY_OK, for a module with a channel that senses it).
     */
    bool (*supply_ok)(void *ctx);
} mc_ops_t;

/* Why a write was refused (the vectors' reasons, and the two refusals of the moment). */
typedef enum {
    MC_OK = 0,
    MC_REFUSED_CRC,
    MC_REFUSED_REGISTER,
    MC_REFUSED_LENGTH,
    MC_REFUSED_OP,
    MC_REFUSED_RANGE,
    MC_REFUSED_MIN_OFF,      /* an on or pattern during the channel's min off */
    MC_REFUSED_RELAY_CHANGE, /* a relay turned on less than 100 ms after it turned off */
} mc_result_t;

/* A STATUS's fields, for mc_status_encode. */
typedef struct {
    uint8_t flags; /* MC_ST_* (MC_ST_EVENT says the event fields mean something) */
    uint8_t seq;
    uint8_t channel;
    uint8_t kind;
    uint8_t value;
    uint16_t age_ms;
    uint8_t outputs;
    uint8_t armed;
} mc_status_t;

typedef struct {
    uint32_t t_ms;
    uint8_t seq;
    uint8_t channel;
    uint8_t kind;
    uint8_t value;
} mc_event_t;

typedef struct {
    uint8_t mode; /* MC_MODE_* */
    bool has_end, has_last_off, has_min_off;
    uint32_t start_ms;    /* when the mode (and a pattern's cycle) started */
    uint32_t on_since_ms; /* when it last turned on, for the max on */
    uint32_t end_ms;      /* when its duration ends (has_end) */
    uint32_t on_ms, off_ms;
    uint32_t min_off_until_ms; /* refused until then (after a max on) */
    uint32_t last_off_ms;      /* when it last turned off (has_last_off; a relay's 100 ms) */
} mc_output_t;

/* The whole state of one module; read it only through the functions below. */
typedef struct {
    mc_config_t cfg;
    mc_ops_t ops;
    uint32_t now_ms; /* the clock the timers have run to */
    /* flags */
    bool fresh, lease_expired, cmd_error;
    mc_result_t last_result;
    /* outputs and the lease */
    mc_output_t out[MC_MAX_CHANNELS];
    uint8_t applied; /* the levels last handed to set_output */
    uint32_t lease_ms;
    bool has_deadline;
    uint32_t deadline_ms;
    /* inputs */
    uint8_t armed;
    uint16_t config[MC_MAX_CHANNELS][3];
    mc_event_t queue[MC_EVENT_QUEUE_LEN];
    uint8_t head, count, next_seq;
    bool overflow;
    uint32_t locate_until_ms;
    bool locating;
    /* the I2C transaction */
    uint8_t pointer, pointer_index; /* the register (and channel) the next read answers */
    bool reading, writing;
    uint8_t rx[16];
    size_t rx_len;    /* bytes received in this write, kept or not */
    uint8_t crc_prev; /* CRC-8 over the address byte and every byte but the last */
    uint8_t crc_all;  /* ... and the last */
    uint8_t tx[MC_MAX_READ_LEN];
    uint8_t tx_len, tx_pos;
    bool tx_status_overflow; /* this read reports OVERFLOW: cleared once it is read in full */
} mc_module_t;

/* CRC-8/SMBUS (polynomial 0x07, initial 0, no reflection, no final XOR), continued from crc. */
uint8_t mc_crc8(uint8_t crc, const uint8_t *data, size_t len);

/* The frames a box reads, each with its CRC: IDENT from cfg, CHANNEL index's descriptor, STATUS. */
void mc_ident_encode(const mc_config_t *cfg, uint8_t out[MC_IDENT_LEN]);
bool mc_channel_encode(const mc_config_t *cfg, uint8_t index, uint8_t out[MC_CHANNEL_LEN]);
void mc_status_encode(const mc_status_t *s, uint8_t out[MC_STATUS_LEN]);

/* Checks cfg (address 0x58-0x5F, 1-8 channels of a known kind, an output relay or solid-state
 * with a max on of 1-255, an input with a max on of 0) and starts the module as at power-up: every
 * output off (set_output called with false for each), FRESH, a 1.5 s lease, nothing armed, no
 * event. False, and nothing started, when cfg is not valid. A module's restart is mc_init again. */
bool mc_init(mc_module_t *m, const mc_config_t *cfg, const mc_ops_t *ops, uint32_t now_ms);

/* Runs the timers up to now_ms (a duration, a max on or a lease that ends at now_ms has ended) and
 * switches what changed. */
void mc_tick(mc_module_t *m, uint32_t now_ms);

/* The I2C target. start: the module's address matched (after a start or a repeated start), read
 * or write; a write that a repeated start ends is taken then. receive: a byte the box wrote.
 * request: the next byte of the read (0xFF past the register's end or with no register chosen).
 * stop: the transaction ended; a write is taken or refused now. */
void mc_i2c_start(mc_module_t *m, bool read, uint32_t now_ms);
void mc_i2c_receive(mc_module_t *m, uint8_t byte);
uint8_t mc_i2c_request(mc_module_t *m);
void mc_i2c_stop(mc_module_t *m, uint32_t now_ms);

/* A whole write (the bytes after the address byte) or read, through the four calls above: for
 * tests, and for a port whose peripheral hands over whole transactions. mc_write returns what
 * became of it (MC_OK also for a register pointer or an empty probe). */
mc_result_t mc_write(mc_module_t *m, const uint8_t *bytes, size_t len, uint32_t now_ms);
void mc_read(mc_module_t *m, uint8_t *out, size_t len, uint32_t now_ms);

/* An input event at t_ms (at or before now): queued and true, or false when the channel is not an
 * input, the kind is not its (hit on a hit channel, closed or opened on a contact), the channel is
 * not armed (events of a disarmed channel are dropped), or the queue is full (OVERFLOW). */
bool mc_event(mc_module_t *m, uint8_t channel, uint8_t kind, uint8_t value, uint32_t t_ms);

/* What the module's firmware reads back. */
uint8_t mc_outputs(const mc_module_t *m);      /* bit n: channel n's output is on */
uint8_t mc_armed(const mc_module_t *m);        /* bit n: channel n's input is armed */
uint8_t mc_status_flags(const mc_module_t *m); /* MC_ST_* as the next STATUS would show them */
uint16_t mc_config_value(const mc_module_t *m, uint8_t channel, uint8_t parameter);
bool mc_locating(mc_module_t *m, uint32_t now_ms); /* LOCATE asked for the status LED to blink */
mc_result_t mc_last_result(const mc_module_t *m);  /* the last COMMAND write's */
const char *mc_result_name(mc_result_t r);         /* "ok", "crc", "register", ... */

#ifdef __cplusplus
}
#endif

#endif /* ATALAIA_MODULE_CORE_H */
